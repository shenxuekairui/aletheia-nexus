from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.discovery.ranking import merge_and_rank_candidates


def test_merge_preserves_complementary_non_conflicting_metadata():
    url = "https://example.org/paper.pdf"
    first = FullTextCandidate(
        doi="10.1000/test",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.ACCEPTED,
        host_type=HostType.REPOSITORY,
        source_name="Example Repository",
    )
    second = FullTextCandidate(
        doi="10.1000/test",
        url=url,
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.ACCEPTED,
        host_type=HostType.REPOSITORY,
        license="cc-by",
        is_best=True,
    )

    result = merge_and_rank_candidates([first, second])[0]

    assert result.provenance == (
        DiscoveryProvider.OPENALEX,
        DiscoveryProvider.UNPAYWALL,
    )
    assert result.source_name == "Example Repository"
    assert result.license == "cc-by"
    assert result.is_best is True


def test_merge_collapses_equivalent_handle_resolver_routes():
    first = FullTextCandidate(
        doi="10.1000/test",
        url="http://hdl.handle.net/21.11116/0000-0001-B9B9-E",
        provenance=(DiscoveryProvider.OPENALEX,),
        host_type=HostType.RESOLVER,
    )
    second = FullTextCandidate(
        doi="10.1000/test",
        url="https://hdl.handle.net/21.11116/0000-0001-B9B9-E",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        host_type=HostType.RESOLVER,
    )

    result = merge_and_rank_candidates([first, second])

    assert len(result) == 1
    assert result[0].url == "https://hdl.handle.net/21.11116/0000-0001-B9B9-E"
    assert result[0].provenance == (
        DiscoveryProvider.OPENALEX,
        DiscoveryProvider.UNPAYWALL,
    )


def test_merge_does_not_fill_conflicting_secondary_metadata():
    url = "https://example.org/paper"
    chosen = FullTextCandidate(
        doi="10.1000/test",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.ACCEPTED,
        host_type=HostType.REPOSITORY,
    )
    second = FullTextCandidate(
        doi="10.1000/test",
        url=url,
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.LANDING_PAGE,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.SUBMITTED,
        host_type=HostType.REPOSITORY,
        license="cc-by",
        source_name="Repository A",
    )
    third = FullTextCandidate(
        doi="10.1000/test",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.UNKNOWN,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.SUBMITTED,
        host_type=HostType.REPOSITORY,
        license="cc0",
        source_name="Repository B",
    )

    result = merge_and_rank_candidates([chosen, second, third])[0]

    assert result.license is None
    assert result.source_name is None


def test_merge_clears_conflict_even_when_priority_candidate_has_value():
    url = "https://example.org/paper.pdf"
    priority = FullTextCandidate(
        doi="10.1000/test",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.PUBLISHED,
        host_type=HostType.PUBLISHER,
        license="cc-by",
        source_name="Publisher A",
    )
    conflicting = FullTextCandidate(
        doi="10.1000/test",
        url=url,
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.LANDING_PAGE,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.ACCEPTED,
        host_type=HostType.REPOSITORY,
        license="cc0",
        source_name="Repository B",
    )

    result = merge_and_rank_candidates([priority, conflicting])[0]

    assert result.license is None
    assert result.source_name is None


def test_acquisition_priority_prefers_pdf_over_published_landing_page():
    published_landing = FullTextCandidate(
        doi="10.1000/test",
        url="https://doi.org/10.1000/test",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.LANDING_PAGE,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.PUBLISHED,
        host_type=HostType.RESOLVER,
    )
    accepted_pdf = FullTextCandidate(
        doi="10.1000/test",
        url="https://repo.example.org/paper.pdf",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.ACCEPTED,
        host_type=HostType.REPOSITORY,
    )

    result = merge_and_rank_candidates([published_landing, accepted_pdf])

    assert result[0] == accepted_pdf
