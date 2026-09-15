import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

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
ProviderTask = tuple[DiscoveryProvider, ProviderCall]

_MAX_PROVIDER_WORKERS = 2


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


def _run_provider_tasks(
    tasks: list[ProviderTask],
    *,
    max_attempts: int,
    backoff_base: float,
) -> tuple[ProviderDiscoveryResult, ...]:
    """Run independent providers concurrently while preserving task order.

    Concurrency is intentionally bounded to two workers in v0.4.2. Batch-level
    processing remains sequential, so this optimization only overlaps network
    waits for providers belonging to the same DOI.
    """

    if not tasks:
        return ()

    if len(tasks) == 1:
        provider, call = tasks[0]
        return (
            _run_provider(
                provider,
                call,
                max_attempts=max_attempts,
                backoff_base=backoff_base,
            ),
        )

    worker_count = min(_MAX_PROVIDER_WORKERS, len(tasks))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="an-discovery-provider",
    ) as executor:
        futures = [
            executor.submit(
                _run_provider,
                provider,
                call,
                max_attempts=max_attempts,
                backoff_base=backoff_base,
            )
            for provider, call in tasks
        ]
        return tuple(future.result() for future in futures)


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

    tasks: list[ProviderTask] = [
        (
            DiscoveryProvider.OPENALEX,
            lambda: discover_openalex(
                normalized_doi,
                api_key=clean_openalex_api_key,
            ),
        )
    ]

    if clean_unpaywall_email:
        tasks.append(
            (
                DiscoveryProvider.UNPAYWALL,
                lambda: discover_unpaywall(
                    normalized_doi,
                    email=clean_unpaywall_email,
                ),
            )
        )

    provider_results = list(
        _run_provider_tasks(
            tasks,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
    )

    if not clean_unpaywall_email:
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
