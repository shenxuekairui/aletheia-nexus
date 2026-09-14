from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.discovery.ranking import merge_and_rank_candidates


def test_merge_deduplicates_url_and_preserves_provenance():
    first = FullTextCandidate(
        doi="10.1000/test",
        url="HTTPS://Example.org/paper.pdf#page=1",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.PUBLISHED,
        host_type=HostType.PUBLISHER,
    )
    second = FullTextCandidate(
        doi="10.1000/test",
        url="https://example.org/paper.pdf",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.PUBLISHED,
        host_type=HostType.PUBLISHER,
    )

    result = merge_and_rank_candidates([first, second])

    assert len(result) == 1
    assert result[0].url == "https://example.org/paper.pdf"
    assert result[0].provenance == (
        DiscoveryProvider.OPENALEX,
        DiscoveryProvider.UNPAYWALL,
    )


def test_merge_normalizes_markdown_wrapped_url_before_deduplication():
    clean_url = "https://example.org/paper.pdf"
    wrapped = FullTextCandidate(
        doi="10.1000/test",
        url=f"[{clean_url}]({clean_url})",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
    )
    clean = FullTextCandidate(
        doi="10.1000/test",
        url=clean_url,
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
    )

    result = merge_and_rank_candidates([wrapped, clean])

    assert len(result) == 1
    assert result[0].url == clean_url
    assert result[0].provenance == (
        DiscoveryProvider.OPENALEX,
        DiscoveryProvider.UNPAYWALL,
    )


def test_direct_pdf_ranks_ahead_of_landing_page():
    landing = FullTextCandidate(
        doi="10.1000/test",
        url="https://example.org/article",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.LANDING_PAGE,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.PUBLISHED,
        host_type=HostType.PUBLISHER,
    )
    pdf = FullTextCandidate(
        doi="10.1000/test",
        url="https://repo.example.org/article.pdf",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.ACCEPTED,
        host_type=HostType.REPOSITORY,
    )

    result = merge_and_rank_candidates([landing, pdf])

    assert result[0] == pdf
