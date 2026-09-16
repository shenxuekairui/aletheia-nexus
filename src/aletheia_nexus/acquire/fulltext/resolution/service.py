import time

from aletheia_nexus.acquire.discovery.models import CandidateUrlType, FullTextCandidate
from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionAccessBlockedError,
    AcquisitionAuthRequiredError,
    AcquisitionError,
    AcquisitionNetworkError,
    AcquisitionNotFoundError,
    AcquisitionRateLimitError,
    AcquisitionRedirectError,
    AcquisitionRequestError,
    AcquisitionServiceError,
    AcquisitionTooLargeError,
    AcquisitionUnsafeUrlError,
)
from aletheia_nexus.acquire.fulltext.models import IdentityStatus
from aletheia_nexus.acquire.fulltext.resolution.derivation import (
    derive_direct_pdf_response,
    derive_https_upgrade,
    derive_pdf_candidates,
)
from aletheia_nexus.acquire.fulltext.resolution.identity import (
    classify_page_type,
    validate_page_identity,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    PageType,
    ResolutionStatus,
    RouteResolutionResult,
)
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html
from aletheia_nexus.acquire.fulltext.resolution.transport import (
    DEFAULT_MAX_PAGE_BYTES,
    DEFAULT_MAX_PAGE_REDIRECTS,
    DEFAULT_PAGE_TIMEOUT,
    retrieve_page,
)
from aletheia_nexus.acquire.fulltext.retry import (
    AcquisitionRetryError,
    call_with_retry,
    validate_retry_config,
)


def _status_for_error(error: AcquisitionError) -> ResolutionStatus:
    if isinstance(error, AcquisitionAuthRequiredError):
        return ResolutionStatus.AUTH_REQUIRED
    if isinstance(error, AcquisitionAccessBlockedError):
        return ResolutionStatus.ACCESS_BLOCKED
    if isinstance(error, AcquisitionNotFoundError):
        return ResolutionStatus.NOT_FOUND
    if isinstance(error, AcquisitionTooLargeError):
        return ResolutionStatus.TOO_LARGE
    if isinstance(error, AcquisitionUnsafeUrlError):
        return ResolutionStatus.UNSAFE_URL
    if isinstance(error, AcquisitionRedirectError):
        return ResolutionStatus.REDIRECT_ERROR
    if isinstance(error, AcquisitionRequestError):
        return ResolutionStatus.REQUEST_ERROR
    if isinstance(error, AcquisitionNetworkError):
        return ResolutionStatus.NETWORK_ERROR
    if isinstance(error, AcquisitionRateLimitError):
        return ResolutionStatus.RATE_LIMITED
    if isinstance(error, AcquisitionServiceError):
        return ResolutionStatus.SERVICE_ERROR
    return ResolutionStatus.ERROR


def resolve_full_text_route(
    candidate: FullTextCandidate,
    *,
    expected_title: str | None = None,
    max_page_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    timeout: float = DEFAULT_PAGE_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_PAGE_REDIRECTS,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> RouteResolutionResult:
    """Resolve one route into more concrete PDF candidates without acquiring them.

    Landing/unknown routes are safely fetched and parsed. Direct HTTP PDF routes
    are not re-downloaded here; they may only yield a transparent HTTPS-upgrade
    alternative. Actual file retrieval and validation remain owned by v0.5.0.
    """

    if not isinstance(candidate, FullTextCandidate):
        raise TypeError("candidate must be a FullTextCandidate")
    if expected_title is not None and not isinstance(expected_title, str):
        raise TypeError("expected_title must be a string or None")
    validate_retry_config(max_attempts, backoff_base)
    started_at = time.perf_counter()

    if candidate.url_type == CandidateUrlType.PDF:
        alternatives = derive_https_upgrade(candidate)
        return RouteResolutionResult(
            source_candidate=candidate,
            status=(
                ResolutionStatus.RESOLVED
                if alternatives
                else ResolutionStatus.NO_FILE_CANDIDATES
            ),
            candidates=alternatives,
            attempts=0,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    try:
        page, attempts, _ = call_with_retry(
            lambda: retrieve_page(
                candidate.url,
                max_bytes=max_page_bytes,
                timeout=timeout,
                max_redirects=max_redirects,
            ),
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
    except AcquisitionRetryError as exc:
        return RouteResolutionResult(
            source_candidate=candidate,
            status=_status_for_error(exc.error),
            error=str(exc.error),
            attempts=exc.attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    if page.is_pdf_response:
        derived = derive_direct_pdf_response(candidate, final_url=page.final_url)
        return RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.RESOLVED,
            candidates=(derived,),
            page=page,
            page_type=PageType.PDF_RESPONSE,
            attempts=attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    if page.text is None:
        return RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.INVALID_CONTENT,
            page=page,
            page_type=PageType.UNKNOWN,
            error=(
                f"Route returned unsupported content type: {page.content_type or 'unknown'}"
            ),
            attempts=attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    parsed = parse_html(page.text)
    identity = validate_page_identity(
        target_doi=candidate.doi,
        parsed=parsed,
        expected_title=expected_title,
    )
    page_type = classify_page_type(parsed, identity)

    # Access/challenge semantics describe the response that was actually served.
    # They take precedence over an apparent identity conflict caused by a generic
    # interstitial title or stale scholarly metadata.
    if page_type in {PageType.CHALLENGE, PageType.ACCESS_DENIED}:
        return RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.ACCESS_BLOCKED,
            page=page,
            page_type=page_type,
            identity=identity,
            error=f"Landing page classified as {page_type.value}",
            attempts=attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    if page_type == PageType.LOGIN:
        return RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.AUTH_REQUIRED,
            page=page,
            page_type=page_type,
            identity=identity,
            error="Landing page explicitly indicates an authentication/access boundary",
            attempts=attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    if identity.status == IdentityStatus.MISMATCH:
        return RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.PAGE_MISMATCH,
            page=page,
            page_type=page_type,
            identity=identity,
            error="Landing page identity conflicts with the requested paper",
            attempts=attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    derived = derive_pdf_candidates(
        parent=candidate,
        parsed=parsed,
        source_page_url=page.final_url,
    )
    return RouteResolutionResult(
        source_candidate=candidate,
        status=(
            ResolutionStatus.RESOLVED
            if derived
            else ResolutionStatus.NO_FILE_CANDIDATES
        ),
        candidates=derived,
        page=page,
        page_type=page_type,
        identity=identity,
        attempts=attempts,
        elapsed_seconds=time.perf_counter() - started_at,
    )
