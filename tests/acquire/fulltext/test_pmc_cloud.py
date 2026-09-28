from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryNetworkError,
    DiscoveryParseError,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    HostType,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.fulltext import pmc_cloud


def _discovery(url="https://pmc.ncbi.nlm.nih.gov/articles/PMC10909753/pdf/main.pdf"):
    candidate = FullTextCandidate(
        doi="10.1016/j.heliyon.2024.e27078",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        host_type=HostType.REPOSITORY,
    )
    return DiscoveryResult(
        doi=candidate.doi,
        candidates=(candidate,),
        providers=(),
    )


def _open_metadata(**overrides):
    values = {
        "doi": "10.1016/j.heliyon.2024.e27078",
        "is_pmc_openaccess": True,
        "is_manuscript": False,
        "is_retracted": False,
        "license_code": "CC BY",
        "pdf_url": (
            "s3://pmc-oa-opendata/PMC10909753.1/PMC10909753.1.pdf"
            "?md5=43a05cddf85c7a28a42df0878a45518c"
        ),
    }
    values.update(overrides)
    return values


def test_pmc_cloud_adds_verified_metadata_pdf_route(monkeypatch):
    monkeypatch.setattr(
        pmc_cloud,
        "get_text",
        lambda *args, **kwargs: (
            """
          <ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
            <CommonPrefixes><Prefix>PMC10909753.1/</Prefix></CommonPrefixes>
          </ListBucketResult>
        """
        ),
    )
    monkeypatch.setattr(
        pmc_cloud,
        "get_json",
        lambda *args, **kwargs: _open_metadata(),
    )

    result = pmc_cloud.augment_with_pmc_cloud(_discovery(), timeout=10)

    official = next(
        candidate
        for candidate in result.candidates
        if candidate.provenance == (DiscoveryProvider.PMC_CLOUD,)
    )
    assert official.url == (
        "https://pmc-oa-opendata.s3.amazonaws.com/"
        "PMC10909753.1/PMC10909753.1.pdf"
        "?md5=43a05cddf85c7a28a42df0878a45518c"
    )
    assert official.url_type == CandidateUrlType.PDF
    assert official.source_name == pmc_cloud.PMC_CLOUD_SOURCE_NAME
    assert result.providers[-1].status == ProviderDiscoveryStatus.SUCCESS


def test_pmc_cloud_recognizes_legacy_numeric_pmc_url(monkeypatch):
    seen = []
    monkeypatch.setattr(
        pmc_cloud,
        "_version_prefixes",
        lambda pmcid, **kwargs: seen.append(pmcid) or (),
    )

    result = pmc_cloud.augment_with_pmc_cloud(
        _discovery("https://www.ncbi.nlm.nih.gov/pmc/articles/10909753"),
        timeout=10,
    )

    assert seen == ["PMC10909753"]
    assert result.providers[-1].status == ProviderDiscoveryStatus.NO_CANDIDATES


def test_pmc_cloud_rejects_metadata_for_different_doi(monkeypatch):
    monkeypatch.setattr(
        pmc_cloud,
        "_version_prefixes",
        lambda *args, **kwargs: ("PMC10909753.1",),
    )
    monkeypatch.setattr(
        pmc_cloud,
        "get_json",
        lambda *args, **kwargs: _open_metadata(doi="10.1000/different"),
    )

    result = pmc_cloud.augment_with_pmc_cloud(_discovery(), timeout=10)

    assert result.providers[-1].status == ProviderDiscoveryStatus.PARSE_ERROR
    assert all(
        DiscoveryProvider.PMC_CLOUD not in candidate.provenance
        for candidate in result.candidates
    )


def test_pmc_cloud_skips_article_version_without_pdf(monkeypatch):
    monkeypatch.setattr(
        pmc_cloud,
        "_version_prefixes",
        lambda *args, **kwargs: ("PMC10909753.1",),
    )
    monkeypatch.setattr(
        pmc_cloud,
        "get_json",
        lambda *args, **kwargs: _open_metadata(pdf_url=None),
    )

    result = pmc_cloud.augment_with_pmc_cloud(_discovery(), timeout=10)

    assert result.providers[-1].status == ProviderDiscoveryStatus.NO_CANDIDATES


def test_pmc_cloud_does_not_call_network_without_pmc_candidate(monkeypatch):
    monkeypatch.setattr(
        pmc_cloud,
        "get_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )
    discovery = _discovery("https://publisher.example/article.pdf")

    assert pmc_cloud.augment_with_pmc_cloud(discovery, timeout=10) is discovery


def test_pmc_cloud_is_idempotent_after_provider_was_recorded(monkeypatch):
    discovery = _discovery()
    discovery = DiscoveryResult(
        doi=discovery.doi,
        candidates=discovery.candidates,
        providers=(
            ProviderDiscoveryResult(
                provider=DiscoveryProvider.PMC_CLOUD,
                status=ProviderDiscoveryStatus.NO_CANDIDATES,
                candidates=(),
            ),
        ),
    )
    monkeypatch.setattr(
        pmc_cloud,
        "get_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")),
    )

    assert pmc_cloud.augment_with_pmc_cloud(discovery, timeout=10) is discovery


def test_pmc_cloud_retries_transient_listing_failure(monkeypatch):
    calls = 0

    def list_versions(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise DiscoveryNetworkError("temporary network failure")
        return ("PMC10909753.1",)

    monkeypatch.setattr(pmc_cloud, "_version_prefixes", list_versions)
    monkeypatch.setattr(
        pmc_cloud,
        "get_json",
        lambda *args, **kwargs: _open_metadata(),
    )

    result = pmc_cloud.augment_with_pmc_cloud(
        _discovery(), timeout=10, max_attempts=2, backoff_base=0
    )

    assert calls == 2
    assert result.providers[-1].status == ProviderDiscoveryStatus.SUCCESS
    assert result.providers[-1].attempts == 2


def test_pmc_cloud_keeps_good_version_when_another_version_is_invalid(monkeypatch):
    monkeypatch.setattr(
        pmc_cloud,
        "_version_prefixes",
        lambda *args, **kwargs: ("PMC10909753.1", "PMC10909753.2"),
    )

    original_candidate_from_metadata = pmc_cloud._candidate_from_metadata

    def metadata(*, prefix, **kwargs):
        if prefix.endswith(".1"):
            raise DiscoveryParseError("invalid first version")
        return original_candidate_from_metadata(
            doi="10.1016/j.heliyon.2024.e27078",
            prefix=prefix,
            timeout=10,
        )

    monkeypatch.setattr(pmc_cloud, "_candidate_from_metadata", metadata)
    monkeypatch.setattr(
        pmc_cloud,
        "get_json",
        lambda *args, **kwargs: _open_metadata(
            pdf_url="s3://pmc-oa-opendata/PMC10909753.2/article.pdf"
        ),
    )

    result = pmc_cloud.augment_with_pmc_cloud(_discovery(), timeout=10)

    assert result.providers[-1].status == ProviderDiscoveryStatus.SUCCESS
    assert result.providers[-1].error is not None
    assert len(result.providers[-1].candidates) == 1
