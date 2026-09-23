import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote, urlsplit

from aletheia_nexus.acquire.access.browser import (
    BrowserCapabilityUnavailable,
    BrowserSession,
    acquire_with_browser,
)
from aletheia_nexus.acquire.access.elsevier import acquire_elsevier_pdf
from aletheia_nexus.acquire.access.manual import resolve_user_operated_access
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
    ElsevierAccessConfig,
    ElsevierAccessStatus,
    MaximizedAcquisitionResult,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.access.publisher_routes import (
    canonical_pdf_route,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
    HostType,
)
from aletheia_nexus.acquire.discovery.ranking import canonicalize_candidate_url
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
)
from aletheia_nexus.acquire.fulltext.orchestration.service import (
    DEFAULT_MAX_FILE_ATTEMPTS,
    DEFAULT_MAX_ROUTE_ATTEMPTS,
    DEFAULT_MAX_ROUTE_DEPTH,
    DEFAULT_MAX_ROUTE_EXPANSIONS_PER_PAGE,
    acquire_full_text,
)
from aletheia_nexus.acquire.fulltext.resolution.models import ResolutionStatus
from aletheia_nexus.core.identifiers.doi import normalize_doi


def _url_key(url: str) -> str:
    try:
        return canonicalize_candidate_url(url)
    except (TypeError, ValueError):
        return url.strip().split("#", 1)[0]


def _resolver_candidate(doi: str) -> FullTextCandidate:
    return FullTextCandidate(
        doi=doi,
        url=f"https://doi.org/{quote(doi, safe='/')}",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.RESOLVER,
        source_name="DOI resolver browser fallback",
    )


def _canonical_publisher_pdf_candidate(
    candidate: FullTextCandidate,
) -> FullTextCandidate | None:
    """Derive a documented same-publisher DOI PDF route for supported hosts."""

    route = canonical_pdf_route(candidate.doi, candidate.url)
    if route is None:
        return None
    url, source_name = route
    return replace(
        candidate,
        url=url,
        url_type=CandidateUrlType.PDF,
        host_type=HostType.PUBLISHER,
        source_name=source_name,
    )


def _browser_route_score(
    candidate: FullTextCandidate,
    *,
    explicit_access_barrier: bool,
) -> int:
    """Prioritize routes where a real browser can add capability over v0.5."""

    score = 0
    if explicit_access_barrier:
        score += 1000
    if candidate.host_type == HostType.PUBLISHER:
        score += 200
    elif candidate.host_type == HostType.RESOLVER:
        score += 100
    elif candidate.host_type == HostType.REPOSITORY:
        score += 50
    if candidate.url_type == CandidateUrlType.LANDING_PAGE:
        score += 40
    elif candidate.url_type == CandidateUrlType.PDF:
        # An authenticated browser can add the most value to a concrete
        # publisher PDF endpoint that public HTTP retrieval could not access.
        score += 300
    elif candidate.url_type == CandidateUrlType.UNKNOWN:
        score += 20
    if urlsplit(candidate.url).scheme.lower() == "https":
        score += 5
    if candidate.source_name and candidate.source_name.startswith(
        "Publisher canonical"
    ):
        score += 700
    path = urlsplit(candidate.url).path.casefold()
    if any(marker in path for marker in ("_si_", "/supp", "supplement")):
        score -= 800
    return score


def browser_recovery_routes(
    base_result: MultiRouteAcquisitionResult,
    *,
    limit: int,
) -> tuple[FullTextCandidate, ...]:
    """Build a bounded browser recovery plan from the complete v0.5 trace."""

    if not isinstance(base_result, MultiRouteAcquisitionResult):
        raise TypeError("base_result must be a MultiRouteAcquisitionResult")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")

    scored: dict[str, tuple[int, int, FullTextCandidate]] = {}
    order = 0

    def add(candidate: FullTextCandidate, *, barrier: bool) -> None:
        nonlocal order
        key = _url_key(candidate.url)
        score = _browser_route_score(
            candidate,
            explicit_access_barrier=barrier,
        )
        existing = scored.get(key)
        if existing is None or score > existing[0]:
            scored[key] = (score, order, candidate)
        order += 1

    for attempt in base_result.route_attempts:
        add(
            attempt.candidate,
            barrier=attempt.result.status
            in {ResolutionStatus.AUTH_REQUIRED, ResolutionStatus.ACCESS_BLOCKED},
        )
        if attempt.result.page is not None and attempt.result.page.final_url:
            try:
                final = replace(attempt.candidate, url=attempt.result.page.final_url)
            except Exception:
                final = None
            if final is not None:
                add(
                    final,
                    barrier=attempt.result.status
                    in {
                        ResolutionStatus.AUTH_REQUIRED,
                        ResolutionStatus.ACCESS_BLOCKED,
                    },
                )

    for attempt in base_result.file_attempts:
        add(
            attempt.candidate,
            barrier=attempt.result.status
            in {AcquisitionStatus.AUTH_REQUIRED, AcquisitionStatus.ACCESS_BLOCKED},
        )
        if attempt.result.retrieved is not None:
            final_url = attempt.result.retrieved.final_url
            if final_url:
                add(
                    replace(attempt.candidate, url=final_url),
                    barrier=attempt.result.status
                    in {
                        AcquisitionStatus.AUTH_REQUIRED,
                        AcquisitionStatus.ACCESS_BLOCKED,
                    },
                )

    for candidate in base_result.discovery.candidates:
        add(candidate, barrier=False)

    # Supported publishers expose stable, official PDF paths even when their
    # rendered entitlement page omits the PDF anchor. These are legitimate
    # publisher endpoints, not access-control bypasses; any login, CAPTCHA, or
    # subscription response is still handled by the normal browser workflow.
    source_candidates = list(base_result.discovery.candidates)
    source_candidates.append(_resolver_candidate(base_result.doi))
    source_candidates.extend(
        attempt.candidate for attempt in base_result.route_attempts
    )
    for attempt in base_result.route_attempts:
        if attempt.result.page is None or not attempt.result.page.final_url:
            continue
        try:
            source_candidates.append(
                replace(attempt.candidate, url=attempt.result.page.final_url)
            )
        except (TypeError, ValueError):
            continue
    for candidate in source_candidates:
        canonical_pdf = _canonical_publisher_pdf_candidate(candidate)
        if canonical_pdf is not None:
            add(canonical_pdf, barrier=False)

    add(_resolver_candidate(base_result.doi), barrier=False)

    ranked = sorted(
        scored.values(),
        key=lambda item: (-item[0], item[1]),
    )
    return tuple(item[2] for item in ranked[:limit])


def _should_try_elsevier_api(base_result: MultiRouteAcquisitionResult) -> bool:
    doi = base_result.doi.lower()
    if doi.startswith("10.1016/"):
        return True

    if base_result.metadata is not None:
        publisher = (base_result.metadata.publisher or "").lower()
        if "elsevier" in publisher or "cell press" in publisher:
            return True

    candidates = list(base_result.discovery.candidates)
    candidates.extend(attempt.candidate for attempt in base_result.route_attempts)
    candidates.extend(attempt.candidate for attempt in base_result.file_attempts)
    for candidate in candidates:
        host = (urlsplit(candidate.url).hostname or "").lower()
        if (
            host == "sciencedirect.com"
            or host.endswith(".sciencedirect.com")
            or host == "elsevier.com"
            or host.endswith(".elsevier.com")
        ):
            return True
    return False


def _final_status_from_browser(
    base_result: MultiRouteAcquisitionResult,
    attempts,
    *,
    elsevier_attempt=None,
) -> tuple[MaximizedAcquisitionStatus, str]:
    statuses = {attempt.status for attempt in attempts}

    if BrowserAttemptStatus.INTERACTION_REQUIRED in statuses:
        return (
            MaximizedAcquisitionStatus.INTERACTION_REQUIRED,
            "Browser recovery reached an unresolved login, SSO, MFA, CAPTCHA, "
            "or browser challenge that requires user interaction.",
        )
    if BrowserAttemptStatus.ENTITLEMENT_REQUIRED in statuses:
        return (
            MaximizedAcquisitionStatus.ENTITLEMENT_REQUIRED,
            "Browser recovery reached an explicit subscription/entitlement boundary.",
        )
    if BrowserAttemptStatus.ACCESS_DENIED in statuses:
        return (
            MaximizedAcquisitionStatus.ACCESS_DENIED,
            "Browser recovery encountered an explicit access-denied boundary "
            "and no route obtained a verified article.",
        )

    if elsevier_attempt is not None:
        if elsevier_attempt.status == ElsevierAccessStatus.AUTH_REQUIRED:
            return (
                MaximizedAcquisitionStatus.AUTH_REQUIRED,
                "The configured Elsevier API credentials were rejected or missing, "
                "and browser recovery did not obtain a verified article.",
            )
        if elsevier_attempt.status == ElsevierAccessStatus.ENTITLEMENT_REQUIRED:
            return (
                MaximizedAcquisitionStatus.ENTITLEMENT_REQUIRED,
                "Elsevier reported an entitlement boundary and browser recovery "
                "did not obtain a verified article.",
            )
        if elsevier_attempt.status == ElsevierAccessStatus.ACCESS_DENIED:
            return (
                MaximizedAcquisitionStatus.ACCESS_DENIED,
                "Elsevier denied API access and browser recovery did not obtain "
                "a verified article.",
            )

    if statuses and statuses <= {BrowserAttemptStatus.UNSAFE_URL}:
        return (
            MaximizedAcquisitionStatus.UNSAFE_URL,
            "All browser recovery routes were rejected by browser URL safety preflight.",
        )

    if statuses and statuses <= {
        BrowserAttemptStatus.ERROR,
        BrowserAttemptStatus.NAVIGATION_ERROR,
        BrowserAttemptStatus.BROWSER_UNAVAILABLE,
    }:
        return (
            MaximizedAcquisitionStatus.ERROR,
            "All browser recovery routes failed with browser/navigation errors.",
        )

    return (
        MaximizedAcquisitionStatus.EXHAUSTED,
        "Public/direct and browser-backed routes were exhausted without a verified "
        "main-article PDF.",
    )


def acquire_full_text_maximized(
    doi: str,
    *,
    output_dir: str | Path,
    browser_config: BrowserAccessConfig | None = None,
    browser_session: BrowserSession | None = None,
    elsevier_config: ElsevierAccessConfig | None = None,
    auto_official_api: bool = True,
    expected_title: str | None = None,
    local_pdf_path: str | Path | None = None,
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
) -> MaximizedAcquisitionResult:
    """Maximize legitimate full-text acquisition across all supported access layers.

    v0.5 remains the first stage because it is cheap, deterministic and hardened.
    Configured official-provider credentials are discovered from the environment by
    default, or may be supplied explicitly. An applicable authenticated API is tried
    next. Only remaining non-VERIFIED outcomes escalate to persistent browser
    recovery.
    No access mechanism may weaken scientific validation.
    """

    if browser_config is not None and not isinstance(
        browser_config, BrowserAccessConfig
    ):
        raise TypeError("browser_config must be a BrowserAccessConfig or None")
    if elsevier_config is not None and not isinstance(
        elsevier_config, ElsevierAccessConfig
    ):
        raise TypeError("elsevier_config must be an ElsevierAccessConfig or None")
    if not isinstance(auto_official_api, bool):
        raise TypeError("auto_official_api must be a boolean")
    if browser_session is not None and not isinstance(browser_session, BrowserSession):
        raise TypeError("browser_session must be a BrowserSession or None")
    if browser_session is not None and browser_config is not None:
        raise ValueError("browser_config and browser_session are mutually exclusive")

    normalized_doi = normalize_doi(doi)
    started_at = time.perf_counter()
    config = (
        browser_session.config
        if browser_session is not None
        else browser_config or BrowserAccessConfig()
    )

    # An explicitly supplied file takes precedence over network acquisition.
    if local_pdf_path is not None:
        return replace(
            resolve_user_operated_access(
                normalized_doi,
                output_dir=output_dir,
                expected_title=expected_title,
                local_pdf_path=local_pdf_path,
                max_bytes=config.max_bytes,
                keep_unverified=keep_unverified,
            ),
            elapsed_seconds=time.perf_counter() - started_at,
        )

    base = acquire_full_text(
        normalized_doi,
        output_dir=output_dir,
        expected_title=expected_title,
        unpaywall_email=unpaywall_email,
        openalex_api_key=openalex_api_key,
        metadata_mailto=metadata_mailto,
        auto_metadata=auto_metadata,
        max_route_attempts=max_route_attempts,
        max_file_attempts=max_file_attempts,
        max_route_depth=max_route_depth,
        max_route_expansions_per_page=max_route_expansions_per_page,
        discovery_max_attempts=discovery_max_attempts,
        metadata_max_attempts=metadata_max_attempts,
        max_attempts_per_route=max_attempts_per_route,
        max_attempts_per_file=max_attempts_per_file,
        backoff_base=backoff_base,
        timeout=timeout,
        keep_unverified=keep_unverified,
        skip_supplement_hints=skip_supplement_hints,
        use_doi_resolver_fallback=use_doi_resolver_fallback,
    )

    if (
        base.status == FullTextAcquisitionStatus.VERIFIED
        and base.verified_result is not None
    ):
        return MaximizedAcquisitionResult(
            doi=normalized_doi,
            status=MaximizedAcquisitionStatus.VERIFIED,
            base_result=base,
            verified_result=base.verified_result,
            elapsed_seconds=time.perf_counter() - started_at,
            message=(
                "v0.5 acquired and verified the article; authenticated escalation "
                "was unnecessary."
            ),
        )

    if elsevier_config is None and auto_official_api:
        elsevier_config = ElsevierAccessConfig.from_env()

    elsevier_attempt = None
    if elsevier_config is not None and _should_try_elsevier_api(base):
        elsevier_attempt = acquire_elsevier_pdf(
            normalized_doi,
            config=elsevier_config,
            output_dir=output_dir,
            expected_title=base.expected_title,
        )
        if (
            elsevier_attempt.status == ElsevierAccessStatus.VERIFIED
            and elsevier_attempt.result is not None
        ):
            return MaximizedAcquisitionResult(
                doi=normalized_doi,
                status=MaximizedAcquisitionStatus.VERIFIED,
                base_result=base,
                elsevier_attempt=elsevier_attempt,
                verified_result=elsevier_attempt.result,
                elapsed_seconds=time.perf_counter() - started_at,
                message="Official Elsevier API acquired a verified main article.",
            )

    routes = browser_recovery_routes(
        base,
        limit=config.max_source_routes,
    )

    try:
        if browser_session is not None:
            recovery = browser_session.acquire(
                doi=normalized_doi,
                routes=routes,
                output_dir=output_dir,
                expected_title=base.expected_title,
            )
        else:
            recovery = acquire_with_browser(
                doi=normalized_doi,
                routes=routes,
                output_dir=output_dir,
                expected_title=base.expected_title,
                config=config,
            )
    except BrowserCapabilityUnavailable as exc:
        return MaximizedAcquisitionResult(
            doi=normalized_doi,
            status=MaximizedAcquisitionStatus.BROWSER_UNAVAILABLE,
            base_result=base,
            elsevier_attempt=elsevier_attempt,
            elapsed_seconds=time.perf_counter() - started_at,
            message=str(exc),
        )
    except Exception as exc:
        return MaximizedAcquisitionResult(
            doi=normalized_doi,
            status=MaximizedAcquisitionStatus.ERROR,
            base_result=base,
            elsevier_attempt=elsevier_attempt,
            elapsed_seconds=time.perf_counter() - started_at,
            message=(f"Browser recovery failed unexpectedly: {type(exc).__name__}"),
        )

    if recovery.verified_result is not None:
        return MaximizedAcquisitionResult(
            doi=normalized_doi,
            status=MaximizedAcquisitionStatus.VERIFIED,
            base_result=base,
            browser_attempts=recovery.attempts,
            elsevier_attempt=elsevier_attempt,
            verified_result=recovery.verified_result,
            elapsed_seconds=time.perf_counter() - started_at,
            message="Browser-backed recovery acquired a verified main article.",
        )

    status, message = _final_status_from_browser(
        base,
        recovery.attempts,
        elsevier_attempt=elsevier_attempt,
    )
    return MaximizedAcquisitionResult(
        doi=normalized_doi,
        status=status,
        base_result=base,
        browser_attempts=recovery.attempts,
        elsevier_attempt=elsevier_attempt,
        elapsed_seconds=time.perf_counter() - started_at,
        message=message,
    )
