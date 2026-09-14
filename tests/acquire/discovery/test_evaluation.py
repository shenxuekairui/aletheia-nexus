from aletheia_nexus.acquire.discovery.evaluation import (
    summarize_provider_contributions,
)
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    FullTextVersion,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)


def _provider_result(
    provider: DiscoveryProvider,
    candidates: tuple[FullTextCandidate, ...],
) -> ProviderDiscoveryResult:
    return ProviderDiscoveryResult(
        provider=provider,
        status=(
            ProviderDiscoveryStatus.SUCCESS
            if candidates
            else ProviderDiscoveryStatus.NO_CANDIDATES
        ),
        candidates=candidates,
        attempts=1,
    )


def test_provider_contribution_counts_unique_shared_and_metadata_only_value():
    doi = "10.1000/test"
    shared_openalex = FullTextCandidate(
        doi=doi,
        url="http://hdl.handle.net/123/abc",
        provenance=(DiscoveryProvider.OPENALEX,),
        version=FullTextVersion.PUBLISHED,
        source_name="Example Journal",
    )
    shared_unpaywall = FullTextCandidate(
        doi=doi,
        url="https://hdl.handle.net/123/abc",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.PUBLISHED,
        license="cc-by",
        is_best=True,
    )
    openalex_unique = FullTextCandidate(
        doi=doi,
        url="https://pubmed.ncbi.nlm.nih.gov/123",
        provenance=(DiscoveryProvider.OPENALEX,),
    )
    unpaywall_unique = FullTextCandidate(
        doi=doi,
        url="https://repo.example.org/paper.pdf",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        access_type=AccessType.OPEN_ACCESS,
    )

    discovery = DiscoveryResult(
        doi=doi,
        candidates=(),
        providers=(
            _provider_result(
                DiscoveryProvider.OPENALEX,
                (shared_openalex, openalex_unique),
            ),
            _provider_result(
                DiscoveryProvider.UNPAYWALL,
                (shared_unpaywall, unpaywall_unique),
            ),
        ),
    )

    contributions = {
        item.provider: item for item in summarize_provider_contributions([discovery])
    }
    openalex = contributions[DiscoveryProvider.OPENALEX]
    unpaywall = contributions[DiscoveryProvider.UNPAYWALL]

    assert openalex.candidate_routes == 2
    assert openalex.unique_routes == 1
    assert openalex.shared_routes == 1
    assert openalex.exclusive_source_name == 1
    assert openalex.exclusive_version == 0

    assert unpaywall.candidate_routes == 2
    assert unpaywall.unique_routes == 1
    assert unpaywall.shared_routes == 1
    assert unpaywall.exclusive_access_type == 1
    assert unpaywall.exclusive_license == 1
    assert unpaywall.exclusive_is_best == 1
    assert unpaywall.exclusive_version == 0
    assert unpaywall.exclusive_metadata_total == 3


def test_provider_contribution_records_disagreement_without_assigning_exclusive_value():
    doi = "10.1000/test"
    openalex_candidate = FullTextCandidate(
        doi=doi,
        url="https://example.org/paper",
        provenance=(DiscoveryProvider.OPENALEX,),
        license="cc-by",
    )
    unpaywall_candidate = FullTextCandidate(
        doi=doi,
        url="https://example.org/paper",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        license="cc-by-nc",
    )
    discovery = DiscoveryResult(
        doi=doi,
        candidates=(),
        providers=(
            _provider_result(DiscoveryProvider.OPENALEX, (openalex_candidate,)),
            _provider_result(DiscoveryProvider.UNPAYWALL, (unpaywall_candidate,)),
        ),
    )

    contributions = summarize_provider_contributions([discovery])

    assert all(item.exclusive_license == 0 for item in contributions)
    assert all(item.metadata_disagreements == 1 for item in contributions)


def test_provider_contribution_keeps_provider_with_zero_candidates_visible():
    discovery = DiscoveryResult(
        doi="10.1000/test",
        candidates=(),
        providers=(
            _provider_result(DiscoveryProvider.OPENALEX, ()),
            _provider_result(DiscoveryProvider.UNPAYWALL, ()),
        ),
    )

    contributions = summarize_provider_contributions([discovery])

    assert [item.provider for item in contributions] == [
        DiscoveryProvider.OPENALEX,
        DiscoveryProvider.UNPAYWALL,
    ]
    assert all(item.candidate_routes == 0 for item in contributions)
