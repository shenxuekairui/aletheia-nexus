from collections.abc import Callable

from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryError,
    DiscoveryNotFoundError,
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
from aletheia_nexus.acquire.discovery.unpaywall import discover_unpaywall
from aletheia_nexus.core.identifiers.doi import normalize_doi

ProviderCall = Callable[[], tuple[FullTextCandidate, ...]]


def _run_provider(
    provider: DiscoveryProvider,
    call: ProviderCall,
) -> ProviderDiscoveryResult:
    try:
        candidates = call()
    except DiscoveryNotFoundError as exc:
        return ProviderDiscoveryResult(
            provider=provider,
            status=ProviderDiscoveryStatus.NOT_FOUND,
            candidates=(),
            error=str(exc),
        )
    except DiscoveryError as exc:
        return ProviderDiscoveryResult(
            provider=provider,
            status=ProviderDiscoveryStatus.ERROR,
            candidates=(),
            error=str(exc),
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
    )


def discover_full_text(
    doi: str,
    *,
    unpaywall_email: str | None = None,
    openalex_api_key: str | None = None,
) -> DiscoveryResult:
    """Discover and rank full-text candidates while isolating provider failures."""

    normalized_doi = normalize_doi(doi)
    provider_results: list[ProviderDiscoveryResult] = []

    provider_results.append(
        _run_provider(
            DiscoveryProvider.OPENALEX,
            lambda: discover_openalex(
                normalized_doi,
                api_key=openalex_api_key,
            ),
        )
    )

    if unpaywall_email:
        provider_results.append(
            _run_provider(
                DiscoveryProvider.UNPAYWALL,
                lambda: discover_unpaywall(
                    normalized_doi,
                    email=unpaywall_email,
                ),
            )
        )
    else:
        provider_results.append(
            ProviderDiscoveryResult(
                provider=DiscoveryProvider.UNPAYWALL,
                status=ProviderDiscoveryStatus.SKIPPED,
                candidates=(),
                error="Unpaywall requires an email parameter",
            )
        )

    candidates = [
        candidate
        for result in provider_results
        for candidate in result.candidates
    ]

    return DiscoveryResult(
        doi=normalized_doi,
        candidates=merge_and_rank_candidates(candidates),
        providers=tuple(provider_results),
    )
