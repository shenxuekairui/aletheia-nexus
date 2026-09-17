import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote, urlsplit

from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryResult,
    FullTextCandidate,
    FullTextVersion,
    HostType,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.ranking import canonicalize_candidate_url
from aletheia_nexus.acquire.discovery.service import discover_full_text
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    DocumentRole,
)
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FileAttempt,
    FileCandidateOrigin,
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    RouteAttempt,
    RouteCandidateOrigin,
    TitleSource,
)
from aletheia_nexus.acquire.fulltext.orchestration.route_expansion import (
    ExpandedRouteCandidate,
    derive_route_expansions,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivedFullTextCandidate,
    ResolutionStatus,
)
from aletheia_nexus.acquire.fulltext.resolution.service import resolve_full_text_route
from aletheia_nexus.acquire.fulltext.retry import validate_retry_config
from aletheia_nexus.acquire.fulltext.service import acquire_direct_pdf
from aletheia_nexus.acquire.fulltext.urls import derive_https_url
from aletheia_nexus.acquire.metadata.exceptions import MetadataError
from aletheia_nexus.acquire.metadata.retry import get_metadata_with_retry
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata

DEFAULT_MAX_ROUTE_ATTEMPTS = 16
DEFAULT_MAX_FILE_ATTEMPTS = 24
DEFAULT_MAX_ROUTE_DEPTH = 2
DEFAULT_MAX_ROUTE_EXPANSIONS_PER_PAGE = 4
DEFAULT_HTTPS_PROBE_TIMEOUT = 5.0

_DISCOVERY_FAILURE_STATUSES = {
    ProviderDiscoveryStatus.CONFIGURATION_ERROR,
    ProviderDiscoveryStatus.REQUEST_ERROR,
    ProviderDiscoveryStatus.NETWORK_ERROR,
    ProviderDiscoveryStatus.RATE_LIMITED,
    ProviderDiscoveryStatus.SERVICE_ERROR,
    ProviderDiscoveryStatus.PARSE_ERROR,
    ProviderDiscoveryStatus.ERROR,
}
_ROUTE_HOST_SCORE = {
    HostType.REPOSITORY: 60,
    HostType.PUBLISHER: 50,
    HostType.RESOLVER: 20,
    HostType.INDEX: 10,
    HostType.UNKNOWN: 0,
}
_VERSION_SCORE = {
    FullTextVersion.PUBLISHED: 30,
    FullTextVersion.ACCEPTED: 20,
    FullTextVersion.SUBMITTED: 10,
    FullTextVersion.UNKNOWN: 0,
}
_HTTPS_PROBE_FALLBACK_STATUSES = {
    ResolutionStatus.NETWORK_ERROR,
    ResolutionStatus.NOT_FOUND,
    ResolutionStatus.REDIRECT_ERROR,
    ResolutionStatus.SERVICE_ERROR,
}


@dataclass(frozen=True, slots=True)
class _QueuedRoute:
    candidate: FullTextCandidate
    origin: RouteCandidateOrigin
    depth: int = 0
    parent_url: str | None = None
    expansion_method: str | None = None
    evidence: tuple[str, ...] = ()


def _validate_optional_limit(value: int | None, *, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer or None")
    if value < 1:
        raise ValueError(f"{name} must be at least 1")


def _validate_positive_int(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be at least 1")


def _validate_depth(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _url_key(url: str) -> str:
    try:
        return canonicalize_candidate_url(url)
    except (TypeError, ValueError):
        return url.strip()


def _discovery_failed_without_candidates(discovery: DiscoveryResult) -> bool:
    return not discovery.candidates and any(
        provider.status in _DISCOVERY_FAILURE_STATUSES
        for provider in discovery.providers
    )


def _doi_resolver_candidate(doi: str) -> FullTextCandidate:
    """Build the standard DOI resolver route without pretending a provider found it."""

    return FullTextCandidate(
        doi=doi,
        url=f"https://doi.org/{quote(doi, safe='/')}",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.RESOLVER,
        source_name="DOI resolver fallback",
    )


def _route_priority(candidate: FullTextCandidate) -> int:
    """Prefer routes likely to yield usable files at lower request cost."""

    score = _ROUTE_HOST_SCORE[candidate.host_type]
    score += _VERSION_SCORE[candidate.version]
    if candidate.access_type == AccessType.OPEN_ACCESS:
        score += 100
    if candidate.is_best:
        score += 20
    if urlsplit(candidate.url).scheme.lower() == "https":
        score += 5
    return score


def _https_upgrade_route(candidate: FullTextCandidate) -> FullTextCandidate | None:
    """Derive an explicit HTTPS alternative for an HTTP page route."""

    upgraded = derive_https_url(candidate.url)
    return replace(candidate, url=upgraded) if upgraded is not None else None


def _is_page_like_invalid_pdf(result: AcquisitionResult) -> bool:
    if result.status != AcquisitionStatus.INVALID_PDF or result.retrieved is None:
        return False

    content_type = (result.retrieved.content_type or "").lower()
    if "html" in content_type or "xhtml" in content_type:
        return True
    if content_type.startswith("text/"):
        return True

    return bool(
        result.retrieved.redirects
    ) and not result.retrieved.final_url.lower().split("?", 1)[0].endswith(".pdf")


def _fallback_route_from_invalid_pdf(
    result: AcquisitionResult,
) -> FullTextCandidate | None:
    if not _is_page_like_invalid_pdf(result) or result.retrieved is None:
        return None
    return replace(
        result.candidate,
        url=result.retrieved.final_url,
        url_type=CandidateUrlType.LANDING_PAGE,
    )


def _metadata_lookup(
    doi: str,
    *,
    mailto: str | None,
    max_attempts: int,
    backoff_base: float,
) -> tuple[PaperMetadata | None, str | None]:
    try:
        metadata = get_metadata_with_retry(
            doi,
            mailto=mailto,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
    except MetadataError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return metadata, None


def _exclusive_access_outcome(
    *,
    route_attempts: list[RouteAttempt],
    file_attempts: list[FileAttempt],
    discovery_failed: bool,
) -> FullTextAcquisitionStatus | None:
    """Preserve access causes only when every terminal branch is an access barrier."""

    if discovery_failed:
        return None

    terminal_statuses: list[str] = []
    for attempt in route_attempts:
        if attempt.result.status != ResolutionStatus.RESOLVED:
            terminal_statuses.append(attempt.result.status.value)
    for attempt in file_attempts:
        if attempt.result.status != AcquisitionStatus.VERIFIED:
            terminal_statuses.append(attempt.result.status.value)

    barriers = {
        ResolutionStatus.ACCESS_BLOCKED.value,
        ResolutionStatus.AUTH_REQUIRED.value,
    }
    if not terminal_statuses or any(
        status not in barriers for status in terminal_statuses
    ):
        return None
    if ResolutionStatus.AUTH_REQUIRED.value in terminal_statuses:
        return FullTextAcquisitionStatus.AUTH_REQUIRED
    return FullTextAcquisitionStatus.ACCESS_BLOCKED


def _queue_expansions(
    route_queue: deque[_QueuedRoute],
    expansions: tuple[ExpandedRouteCandidate, ...],
    *,
    depth: int,
) -> int:
    """Put strong next-hop routes first while preserving their ranked order."""

    if not expansions:
        return 0
    entries = [
        _QueuedRoute(
            candidate=item.candidate,
            origin=RouteCandidateOrigin.PAGE_EXPANSION,
            depth=depth,
            parent_url=item.parent_url,
            expansion_method=item.method.value,
            evidence=item.evidence,
        )
        for item in expansions
    ]
    for entry in reversed(entries):
        route_queue.appendleft(entry)
    return len(entries)


def _initial_route_entries(
    candidates: list[FullTextCandidate],
) -> list[_QueuedRoute]:
    """Prefer a traceable HTTPS alternative before each legacy HTTP page route."""

    entries: list[_QueuedRoute] = []
    for candidate in candidates:
        upgraded = _https_upgrade_route(candidate)
        if upgraded is not None:
            entries.append(
                _QueuedRoute(
                    candidate=upgraded,
                    origin=RouteCandidateOrigin.URL_TRANSFORM,
                    parent_url=candidate.url,
                    expansion_method="HTTPS_UPGRADE",
                    evidence=(
                        "Legacy HTTP route was upgraded to HTTPS before retrieval",
                    ),
                )
            )
        entries.append(
            _QueuedRoute(
                candidate=candidate,
                origin=RouteCandidateOrigin.DISCOVERY,
            )
        )
    return entries


def acquire_from_discovery(
    discovery: DiscoveryResult,
    *,
    output_dir: str | Path,
    expected_title: str | None = None,
    max_route_attempts: int | None = DEFAULT_MAX_ROUTE_ATTEMPTS,
    max_file_attempts: int | None = DEFAULT_MAX_FILE_ATTEMPTS,
    max_route_depth: int = DEFAULT_MAX_ROUTE_DEPTH,
    max_route_expansions_per_page: int = DEFAULT_MAX_ROUTE_EXPANSIONS_PER_PAGE,
    max_attempts_per_route: int = 2,
    max_attempts_per_file: int = 2,
    backoff_base: float = 0.5,
    timeout: float = 30.0,
    keep_unverified: bool = False,
    skip_supplement_hints: bool = True,
    use_doi_resolver_fallback: bool = True,
) -> MultiRouteAcquisitionResult:
    """Orchestrate Discovery, route resolution, fallback, and validation.

    Concrete file routes are tried first. Page routes are then expanded adaptively:
    every useful route is resolved, its derived PDFs are validated immediately,
    and only high-confidence next-hop page routes are followed within strict depth
    and attempt budgets. Legacy HTTP page routes receive an explicit short HTTPS
    probe before the original route. The first VERIFIED main article stops the
    workflow.
    """

    if not isinstance(discovery, DiscoveryResult):
        raise TypeError("discovery must be a DiscoveryResult")
    if expected_title is not None and not isinstance(expected_title, str):
        raise TypeError("expected_title must be a string or None")
    if not isinstance(keep_unverified, bool):
        raise TypeError("keep_unverified must be a boolean")
    if not isinstance(skip_supplement_hints, bool):
        raise TypeError("skip_supplement_hints must be a boolean")
    if not isinstance(use_doi_resolver_fallback, bool):
        raise TypeError("use_doi_resolver_fallback must be a boolean")
    _validate_optional_limit(max_route_attempts, name="max_route_attempts")
    _validate_optional_limit(max_file_attempts, name="max_file_attempts")
    _validate_depth(max_route_depth, name="max_route_depth")
    _validate_positive_int(
        max_route_expansions_per_page,
        name="max_route_expansions_per_page",
    )
    validate_retry_config(max_attempts_per_route, backoff_base)
    validate_retry_config(max_attempts_per_file, backoff_base)
    if expected_title is not None:
        expected_title = expected_title.strip() or None

    started_at = time.perf_counter()
    doi = normalize_doi(discovery.doi)
    discovery_failed = _discovery_failed_without_candidates(discovery)
    route_attempts: list[RouteAttempt] = []
    file_attempts: list[FileAttempt] = []
    seen_file_urls: set[str] = set()
    seen_route_urls: set[str] = set()
    duplicate_file_candidates_skipped = 0
    duplicate_route_candidates_skipped = 0
    supplement_candidates_skipped = 0
    route_expansions_enqueued = 0
    max_route_depth_reached = 0
    page_route_attempts = 0
    file_limit_hit = False
    route_limit_hit = False
    verified_result: AcquisitionResult | None = None
    fallback_routes: list[FullTextCandidate] = []

    if not discovery.candidates and not use_doi_resolver_fallback:
        status = (
            FullTextAcquisitionStatus.DISCOVERY_FAILED
            if discovery_failed
            else FullTextAcquisitionStatus.NO_CANDIDATES
        )
        message = (
            "Discovery returned no candidates because at least one provider failed"
            if status == FullTextAcquisitionStatus.DISCOVERY_FAILED
            else "Discovery returned no full-text candidates"
        )
        return MultiRouteAcquisitionResult(
            doi=doi,
            status=status,
            discovery=discovery,
            expected_title=expected_title,
            title_source=TitleSource.USER if expected_title else TitleSource.NONE,
            elapsed_seconds=time.perf_counter() - started_at,
            message=message,
        )

    def attempt_file(
        candidate: FullTextCandidate,
        *,
        origin: FileCandidateOrigin,
        derived: DerivedFullTextCandidate | None = None,
    ) -> tuple[AcquisitionResult | None, FullTextCandidate | None]:
        nonlocal duplicate_file_candidates_skipped
        nonlocal supplement_candidates_skipped
        nonlocal file_limit_hit
        nonlocal verified_result

        if (
            derived is not None
            and derived.role_hint == DocumentRole.SUPPLEMENT
            and skip_supplement_hints
        ):
            supplement_candidates_skipped += 1
            return None, None

        key = _url_key(candidate.url)
        if key in seen_file_urls:
            duplicate_file_candidates_skipped += 1
            return None, None

        if max_file_attempts is not None and len(file_attempts) >= max_file_attempts:
            file_limit_hit = True
            return None, None

        seen_file_urls.add(key)
        result = acquire_direct_pdf(
            candidate,
            output_dir=output_dir,
            expected_title=expected_title,
            max_attempts=max_attempts_per_file,
            backoff_base=backoff_base,
            timeout=timeout,
            keep_unverified=keep_unverified,
        )
        file_attempts.append(
            FileAttempt(
                candidate=candidate,
                origin=origin,
                result=result,
                parent_url=derived.parent_url if derived else None,
                derivation_method=derived.method if derived else None,
                role_hint=derived.role_hint if derived else DocumentRole.UNKNOWN,
                evidence=derived.evidence if derived else (),
            )
        )

        if result.retrieved is not None:
            seen_file_urls.add(_url_key(result.retrieved.final_url))

        if result.status == AcquisitionStatus.VERIFIED:
            verified_result = result
            return result, None

        return result, _fallback_route_from_invalid_pdf(result)

    direct_candidates = [
        candidate
        for candidate in discovery.candidates
        if candidate.url_type == CandidateUrlType.PDF
    ]
    discovered_routes = sorted(
        (
            candidate
            for candidate in discovery.candidates
            if candidate.url_type != CandidateUrlType.PDF
        ),
        key=_route_priority,
        reverse=True,
    )

    for candidate in direct_candidates:
        if candidate.url.lower().startswith("http://"):
            transform = resolve_full_text_route(
                candidate,
                expected_title=expected_title,
                max_attempts=max_attempts_per_route,
                backoff_base=backoff_base,
                timeout=timeout,
            )
            route_attempts.append(
                RouteAttempt(
                    candidate=candidate,
                    origin=RouteCandidateOrigin.PDF_TRANSFORM,
                    result=transform,
                )
            )
            if transform.status == ResolutionStatus.RESOLVED:
                for derived in transform.candidates:
                    _, fallback = attempt_file(
                        derived.candidate,
                        origin=FileCandidateOrigin.DERIVED,
                        derived=derived,
                    )
                    if fallback is not None:
                        fallback_routes.append(fallback)
                    if verified_result is not None or file_limit_hit:
                        break

        if verified_result is not None or file_limit_hit:
            break

        _, fallback = attempt_file(
            candidate,
            origin=FileCandidateOrigin.DISCOVERY,
        )
        if fallback is not None:
            fallback_routes.append(fallback)
        if verified_result is not None or file_limit_hit:
            break

    route_queue: deque[_QueuedRoute] = deque(_initial_route_entries(discovered_routes))
    route_queue.extend(
        _QueuedRoute(
            candidate=candidate,
            origin=RouteCandidateOrigin.INVALID_PDF_FALLBACK,
        )
        for candidate in fallback_routes
    )
    doi_fallback_pending = use_doi_resolver_fallback

    if max_file_attempts is not None and len(file_attempts) >= max_file_attempts:
        file_limit_hit = verified_result is None

    while (
        (route_queue or doi_fallback_pending)
        and verified_result is None
        and not file_limit_hit
    ):
        if not route_queue:
            route_queue.append(
                _QueuedRoute(
                    candidate=_doi_resolver_candidate(doi),
                    origin=RouteCandidateOrigin.DOI_RESOLVER_FALLBACK,
                )
            )
            doi_fallback_pending = False

        entry = route_queue.popleft()
        candidate = entry.candidate
        key = _url_key(candidate.url)
        if key in seen_route_urls:
            duplicate_route_candidates_skipped += 1
            continue

        if max_route_attempts is not None and page_route_attempts >= max_route_attempts:
            route_limit_hit = True
            break

        seen_route_urls.add(key)
        max_route_depth_reached = max(max_route_depth_reached, entry.depth)
        route_timeout = (
            min(timeout, DEFAULT_HTTPS_PROBE_TIMEOUT)
            if entry.origin == RouteCandidateOrigin.URL_TRANSFORM
            else timeout
        )
        resolution = resolve_full_text_route(
            candidate,
            expected_title=expected_title,
            max_attempts=max_attempts_per_route,
            backoff_base=backoff_base,
            timeout=route_timeout,
        )
        page_route_attempts += 1
        route_attempts.append(
            RouteAttempt(
                candidate=candidate,
                origin=entry.origin,
                result=resolution,
                depth=entry.depth,
                parent_url=entry.parent_url,
                expansion_method=entry.expansion_method,
                evidence=entry.evidence,
            )
        )

        if resolution.page is not None:
            seen_route_urls.add(_url_key(resolution.page.final_url))

        if (
            entry.origin == RouteCandidateOrigin.URL_TRANSFORM
            and entry.parent_url is not None
            and resolution.status not in _HTTPS_PROBE_FALLBACK_STATUSES
        ):
            seen_route_urls.add(_url_key(entry.parent_url))

        if resolution.status == ResolutionStatus.RESOLVED:
            for derived in resolution.candidates:
                _, fallback = attempt_file(
                    derived.candidate,
                    origin=FileCandidateOrigin.DERIVED,
                    derived=derived,
                )
                if fallback is not None and entry.depth < max_route_depth:
                    route_queue.append(
                        _QueuedRoute(
                            candidate=fallback,
                            origin=RouteCandidateOrigin.INVALID_PDF_FALLBACK,
                            depth=entry.depth + 1,
                            parent_url=candidate.url,
                            evidence=("Derived PDF returned page-like content",),
                        )
                    )
                if verified_result is not None or file_limit_hit:
                    break

        if verified_result is not None or file_limit_hit:
            break

        if entry.depth < max_route_depth and resolution.page is not None:
            expansions = derive_route_expansions(
                parent=candidate,
                resolution=resolution,
                max_candidates=max_route_expansions_per_page,
            )
            route_expansions_enqueued += _queue_expansions(
                route_queue,
                expansions,
                depth=entry.depth + 1,
            )

    exclusive_access = _exclusive_access_outcome(
        route_attempts=route_attempts,
        file_attempts=file_attempts,
        discovery_failed=discovery_failed,
    )

    if verified_result is not None:
        status = FullTextAcquisitionStatus.VERIFIED
        message = "Verified article acquired; remaining routes were not attempted"
    elif file_limit_hit or route_limit_hit:
        status = FullTextAcquisitionStatus.LIMIT_REACHED
        reasons = []
        if file_limit_hit:
            reasons.append("file attempt limit")
        if route_limit_hit:
            reasons.append("route attempt limit")
        message = "Stopped after reaching " + " and ".join(reasons)
    elif exclusive_access == FullTextAcquisitionStatus.ACCESS_BLOCKED:
        status = exclusive_access
        message = "All terminal route and file attempts were explicitly access blocked"
    elif exclusive_access == FullTextAcquisitionStatus.AUTH_REQUIRED:
        status = exclusive_access
        message = (
            "All terminal route and file attempts ended at an access/auth boundary"
        )
    elif not file_attempts:
        status = FullTextAcquisitionStatus.NO_CANDIDATES
        if discovery_failed:
            message = (
                "Discovery had provider failures and available route fallbacks did not "
                "yield a concrete main-article file candidate"
            )
        else:
            message = "No concrete main-article file candidate was available to acquire"
    else:
        status = FullTextAcquisitionStatus.EXHAUSTED
        message = "All available file and route candidates were exhausted without verification"

    return MultiRouteAcquisitionResult(
        doi=doi,
        status=status,
        discovery=discovery,
        route_attempts=tuple(route_attempts),
        file_attempts=tuple(file_attempts),
        verified_result=verified_result,
        expected_title=expected_title,
        title_source=TitleSource.USER if expected_title else TitleSource.NONE,
        duplicate_file_candidates_skipped=duplicate_file_candidates_skipped,
        duplicate_route_candidates_skipped=duplicate_route_candidates_skipped,
        supplement_candidates_skipped=supplement_candidates_skipped,
        page_route_attempts=page_route_attempts,
        route_expansions_enqueued=route_expansions_enqueued,
        max_route_depth_reached=max_route_depth_reached,
        elapsed_seconds=time.perf_counter() - started_at,
        message=message,
    )


def acquire_full_text(
    doi: str,
    *,
    output_dir: str | Path,
    expected_title: str | None = None,
    unpaywall_email: str | None = None,
    openalex_api_key: str | None = None,
    metadata_mailto: str | None = None,
    auto_metadata: bool = True,
    max_route_attempts: int | None = DEFAULT_MAX_ROUTE_ATTEMPTS,
    max_file_attempts: int | None = DEFAULT_MAX_FILE_ATTEMPTS,
    max_route_depth: int = DEFAULT_MAX_ROUTE_DEPTH,
    max_route_expansions_per_page: int = DEFAULT_MAX_ROUTE_EXPANSIONS_PER_PAGE,
    discovery_max_attempts: int = 3,
    metadata_max_attempts: int = 2,
    max_attempts_per_route: int = 2,
    max_attempts_per_file: int = 2,
    backoff_base: float = 0.5,
    timeout: float = 30.0,
    keep_unverified: bool = False,
    skip_supplement_hints: bool = True,
    use_doi_resolver_fallback: bool = True,
) -> MultiRouteAcquisitionResult:
    """Acquire a verified main article from a DOI using the complete v0.5 pipeline."""

    if expected_title is not None and not isinstance(expected_title, str):
        raise TypeError("expected_title must be a string or None")
    if not isinstance(auto_metadata, bool):
        raise TypeError("auto_metadata must be a boolean")
    if not isinstance(use_doi_resolver_fallback, bool):
        raise TypeError("use_doi_resolver_fallback must be a boolean")

    normalized_doi = normalize_doi(doi)
    started_at = time.perf_counter()
    metadata: PaperMetadata | None = None
    metadata_error: str | None = None
    effective_title = expected_title.strip() if expected_title else None
    title_source = TitleSource.USER if effective_title else TitleSource.NONE

    if effective_title is None and auto_metadata:
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="an-fulltext-bootstrap",
        ) as executor:
            discovery_future = executor.submit(
                discover_full_text,
                normalized_doi,
                unpaywall_email=unpaywall_email,
                openalex_api_key=openalex_api_key,
                max_attempts=discovery_max_attempts,
                backoff_base=backoff_base,
            )
            metadata_future = executor.submit(
                _metadata_lookup,
                normalized_doi,
                mailto=metadata_mailto,
                max_attempts=metadata_max_attempts,
                backoff_base=backoff_base,
            )
            discovery = discovery_future.result()
            metadata, metadata_error = metadata_future.result()

        if metadata is not None and metadata.title and metadata.title.strip():
            effective_title = metadata.title.strip()
            title_source = TitleSource.METADATA
    else:
        discovery = discover_full_text(
            normalized_doi,
            unpaywall_email=unpaywall_email,
            openalex_api_key=openalex_api_key,
            max_attempts=discovery_max_attempts,
            backoff_base=backoff_base,
        )

    result = acquire_from_discovery(
        discovery,
        output_dir=output_dir,
        expected_title=effective_title,
        max_route_attempts=max_route_attempts,
        max_file_attempts=max_file_attempts,
        max_route_depth=max_route_depth,
        max_route_expansions_per_page=max_route_expansions_per_page,
        max_attempts_per_route=max_attempts_per_route,
        max_attempts_per_file=max_attempts_per_file,
        backoff_base=backoff_base,
        timeout=timeout,
        keep_unverified=keep_unverified,
        skip_supplement_hints=skip_supplement_hints,
        use_doi_resolver_fallback=use_doi_resolver_fallback,
    )

    return replace(
        result,
        metadata=metadata,
        metadata_error=metadata_error,
        expected_title=effective_title,
        title_source=title_source,
        elapsed_seconds=time.perf_counter() - started_at,
    )
