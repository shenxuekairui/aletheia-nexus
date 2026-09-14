import time
from collections.abc import Callable

from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryConfigurationError,
    DiscoveryError,
    DiscoveryNetworkError,
    DiscoveryNotFoundError,
    DiscoveryParseError,
    DiscoveryRateLimitError,
    DiscoveryRequestError,
    DiscoveryServiceError,
)
from aletheia_nexus.acquire.discovery.models import (
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.openalex import discover_openalex
from aletheia_nexus.acquire.discovery.ranking import merge_and_rank_candidates
from aletheia_nexus.acquire.discovery.retry import (
    RetryCallError,
    call_with_retry,
    validate_retry_config,
)
from aletheia_nexus.acquire.discovery.unpaywall import discover_unpaywall
from aletheia_nexus.core.identifiers.doi import normalize_doi

ProviderCall = Callable[[], tuple[FullTextCandidate, ...]]


def _clean_optional_config(value: str | None, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")
    return value.strip() or None


def _provider_status_for_error(error: DiscoveryError) -> ProviderDiscoveryStatus:
    if isinstance(error, DiscoveryConfigurationError):
        return ProviderDiscoveryStatus.CONFIGURATION_ERROR
    if isinstance(error, DiscoveryNotFoundError):
        return ProviderDiscoveryStatus.NOT_FOUND
    if isinstance(error, DiscoveryRequestError):
        return ProviderDiscoveryStatus.REQUEST_ERROR
    if isinstance(error, DiscoveryNetworkError):
        return ProviderDiscoveryStatus.NETWORK_ERROR
    if isinstance(error, DiscoveryRateLimitError):
        return ProviderDiscoveryStatus.RATE_LIMITED
    if isinstance(error, DiscoveryServiceError):
        return ProviderDiscoveryStatus.SERVICE_ERROR
    if isinstance(error, DiscoveryParseError):
        return ProviderDiscoveryStatus.PARSE_ERROR
    return ProviderDiscoveryStatus.ERROR


def _run_provider(
    provider: DiscoveryProvider,
    call: ProviderCall,
    *,
    max_attempts: int,
    backoff_base: float,
) -> ProviderDiscoveryResult:
    try:
        candidates, attempts, elapsed_seconds = call_with_retry(
            call,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
    except RetryCallError as exc:
        return ProviderDiscoveryResult(
            provider=provider,
            status=_provider_status_for_error(exc.error),
            candidates=(),
            error=str(exc.error),
            attempts=exc.attempts,
            elapsed_seconds=exc.elapsed_seconds,
        )

    status = (
        ProviderDiscoveryStatus.SUCCESS
        if candidates
        else ProviderDiscoveryStatus.NO_CANDIDATES
    )
    return ProviderDiscoveryResult(
        provider=provider,
        status=status,
        candidates=candidates,
        attempts=attempts,
        elapsed_seconds=elapsed_seconds,
    )


def discover_full_text(
    doi: str,
    *,
    unpaywall_email: str | None = None,
    openalex_api_key: str | None = None,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> DiscoveryResult:
    """Discover and rank full-text candidates while isolating provider failures."""

    validate_retry_config(max_attempts, backoff_base)

    clean_unpaywall_email = _clean_optional_config(
        unpaywall_email,
        name="unpaywall_email",
    )
    clean_openalex_api_key = _clean_optional_config(
        openalex_api_key,
        name="openalex_api_key",
    )
    started_at = time.perf_counter()
    normalized_doi = normalize_doi(doi)

    provider_results: list[ProviderDiscoveryResult] = []

    provider_results.append(
        _run_provider(
            DiscoveryProvider.OPENALEX,
            lambda: discover_openalex(
                normalized_doi,
                api_key=clean_openalex_api_key,
            ),
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
    )

    if clean_unpaywall_email:
        provider_results.append(
            _run_provider(
                DiscoveryProvider.UNPAYWALL,
                lambda: discover_unpaywall(
                    normalized_doi,
                    email=clean_unpaywall_email,
                ),
                max_attempts=max_attempts,
                backoff_base=backoff_base,
            )
        )
    else:
        provider_results.append(
            ProviderDiscoveryResult(
                provider=DiscoveryProvider.UNPAYWALL,
                status=ProviderDiscoveryStatus.SKIPPED,
                candidates=(),
                error="Unpaywall requires an email parameter",
                attempts=0,
                elapsed_seconds=0.0,
            )
        )

    candidates = [
        candidate for result in provider_results for candidate in result.candidates
    ]

    return DiscoveryResult(
        doi=normalized_doi,
        candidates=merge_and_rank_candidates(candidates),
        providers=tuple(provider_results),
        elapsed_seconds=time.perf_counter() - started_at,
    )
