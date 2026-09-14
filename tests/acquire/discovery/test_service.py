from aletheia_nexus.acquire.discovery.exceptions import DiscoveryNetworkError
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.service import discover_full_text


def test_discover_full_text_isolates_provider_failure(monkeypatch):
    candidate = FullTextCandidate(
        doi="10.1000/test",
        url="https://example.org/paper.pdf",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
    )

    def fail_openalex(*args, **kwargs):
        raise DiscoveryNetworkError("OpenAlex unavailable")

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        fail_openalex,
    )
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_unpaywall",
        lambda *args, **kwargs: (candidate,),
    )

    result = discover_full_text(
        "10.1000/test",
        unpaywall_email="person@example.org",
    )

    assert result.candidates == (candidate,)
    assert result.providers[0].status == ProviderDiscoveryStatus.ERROR
    assert result.providers[1].status == ProviderDiscoveryStatus.SUCCESS


def test_discover_full_text_skips_unpaywall_without_email(monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        lambda *args, **kwargs: (),
    )

    result = discover_full_text("10.1000/test")

    assert result.providers[1].provider == DiscoveryProvider.UNPAYWALL
    assert result.providers[1].status == ProviderDiscoveryStatus.SKIPPED
