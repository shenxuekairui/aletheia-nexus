import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from aletheia_nexus.acquire.discovery.exceptions import DiscoveryError
from aletheia_nexus.acquire.discovery.models import (
    DiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.retry import validate_retry_config
from aletheia_nexus.acquire.discovery.service import discover_full_text
from aletheia_nexus.core.identifiers.doi import normalize_doi


class DiscoveryStatus(StrEnum):
    """Stable outcome for one DOI in batch discovery."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NO_CANDIDATES = "NO_CANDIDATES"
    NOT_FOUND = "NOT_FOUND"
    INVALID_DOI = "INVALID_DOI"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class DiscoveryLookupResult:
    """Batch discovery result preserving input, identity, and runtime."""

    input_value: object
    doi: str | None
    status: DiscoveryStatus
    discovery: DiscoveryResult | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0


_FAILURE_STATUSES = {
    ProviderDiscoveryStatus.CONFIGURATION_ERROR,
    ProviderDiscoveryStatus.REQUEST_ERROR,
    ProviderDiscoveryStatus.NETWORK_ERROR,
    ProviderDiscoveryStatus.RATE_LIMITED,
    ProviderDiscoveryStatus.SERVICE_ERROR,
    ProviderDiscoveryStatus.PARSE_ERROR,
    ProviderDiscoveryStatus.ERROR,
}


def _classify_discovery(result: DiscoveryResult) -> DiscoveryStatus:
    """Map provider-level outcomes to one stable batch status."""

    has_failure = any(
        provider.status in _FAILURE_STATUSES for provider in result.providers
    )

    if result.candidates:
        return (
            DiscoveryStatus.PARTIAL_SUCCESS if has_failure else DiscoveryStatus.SUCCESS
        )

    if has_failure:
        return DiscoveryStatus.ERROR

    attempted = [
        provider
        for provider in result.providers
        if provider.status != ProviderDiscoveryStatus.SKIPPED
    ]

    if attempted and all(
        provider.status == ProviderDiscoveryStatus.NOT_FOUND for provider in attempted
    ):
        return DiscoveryStatus.NOT_FOUND

    return DiscoveryStatus.NO_CANDIDATES


def _summarize_error(
    result: DiscoveryResult,
    status: DiscoveryStatus,
) -> str | None:
    """Return a concise batch-level error while preserving full provider details."""

    if status in {DiscoveryStatus.SUCCESS, DiscoveryStatus.NO_CANDIDATES}:
        return None

    if status == DiscoveryStatus.NOT_FOUND:
        relevant = {ProviderDiscoveryStatus.NOT_FOUND}
    else:
        relevant = _FAILURE_STATUSES

    messages = [
        f"{provider.provider.value}: {provider.error}"
        for provider in result.providers
        if provider.status in relevant and provider.error
    ]

    return "; ".join(messages) or None


def discover_full_text_batch(
    values: Iterable[object],
    *,
    unpaywall_email: str | None = None,
    openalex_api_key: str | None = None,
    deduplicate: bool = True,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> list[DiscoveryLookupResult]:
    """Discover possible full-text routes for multiple DOI inputs.

    Batch items remain intentionally sequential in v0.4.2. Within each DOI,
    independent Discovery providers may overlap their network waits through the
    bounded provider-level concurrency implemented by ``discover_full_text``.
    """

    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TypeError("discover_full_text_batch() expects an iterable of DOI values")

    if not isinstance(deduplicate, bool):
        raise TypeError("deduplicate must be a boolean")

    if unpaywall_email is not None and not isinstance(unpaywall_email, str):
        raise TypeError("unpaywall_email must be a string or None")

    if openalex_api_key is not None and not isinstance(openalex_api_key, str):
        raise TypeError("openalex_api_key must be a string or None")

    validate_retry_config(max_attempts, backoff_base)

    results: list[DiscoveryLookupResult] = []
    seen: set[str] = set()

    for value in values:
        item_started_at = time.perf_counter()

        try:
            doi = normalize_doi(value)
        except (TypeError, ValueError) as exc:
            results.append(
                DiscoveryLookupResult(
                    input_value=value,
                    doi=None,
                    status=DiscoveryStatus.INVALID_DOI,
                    error=str(exc),
                    elapsed_seconds=time.perf_counter() - item_started_at,
                )
            )
            continue

        if deduplicate and doi in seen:
            continue

        seen.add(doi)

        try:
            discovery = discover_full_text(
                doi,
                unpaywall_email=unpaywall_email,
                openalex_api_key=openalex_api_key,
                max_attempts=max_attempts,
                backoff_base=backoff_base,
            )
        except DiscoveryError as exc:
            results.append(
                DiscoveryLookupResult(
                    input_value=value,
                    doi=doi,
                    status=DiscoveryStatus.ERROR,
                    error=str(exc),
                    elapsed_seconds=time.perf_counter() - item_started_at,
                )
            )
            continue

        status = _classify_discovery(discovery)
        results.append(
            DiscoveryLookupResult(
                input_value=value,
                doi=doi,
                status=status,
                discovery=discovery,
                error=_summarize_error(discovery, status),
                elapsed_seconds=time.perf_counter() - item_started_at,
            )
        )

    return results
