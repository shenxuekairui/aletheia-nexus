import pytest

from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    DocumentRole,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.orchestration import service
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    DerivedFullTextCandidate,
    ResolutionStatus,
    RetrievedPage,
    RouteResolutionResult,
)


def _candidate(
    url: str, *, url_type: CandidateUrlType = CandidateUrlType.LANDING_PAGE
) -> FullTextCandidate:
    return FullTextCandidate(
        doi="10.1000/target",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=url_type,
    )


def _discovery(*candidates: FullTextCandidate) -> DiscoveryResult:
    return DiscoveryResult(
        doi="10.1000/target",
        candidates=tuple(candidates),
        providers=(
            ProviderDiscoveryResult(
                provider=DiscoveryProvider.OPENALEX,
                status=(
                    ProviderDiscoveryStatus.SUCCESS
                    if candidates
                    else ProviderDiscoveryStatus.NO_CANDIDATES
                ),
                candidates=tuple(candidates),
            ),
        ),
    )


def test_max_route_expansions_per_page_rejects_none_at_api_boundary(tmp_path):
    with pytest.raises(TypeError, match="max_route_expansions_per_page"):
        service.acquire_from_discovery(
            _discovery(),
            output_dir=tmp_path,
            max_route_expansions_per_page=None,
            use_doi_resolver_fallback=False,
        )


def test_invalid_pdf_page_fallback_respects_route_depth_limit(monkeypatch, tmp_path):
    start = _candidate("https://publisher.example/article")
    pdf = _candidate(
        "https://publisher.example/article.pdf",
        url_type=CandidateUrlType.PDF,
    )
    fallback_url = "https://publisher.example/interstitial"
    resolve_calls: list[str] = []

    def resolve(candidate, **kwargs):
        resolve_calls.append(candidate.url)
        if candidate.url == start.url:
            derived = DerivedFullTextCandidate(
                candidate=pdf,
                parent_url=start.url,
                source_page_url=start.url,
                method=DerivationMethod.CITATION_PDF_URL,
                role_hint=DocumentRole.ARTICLE,
                evidence=("citation_pdf_url",),
                priority=100,
            )
            html = "<html><body>article</body></html>"
            return RouteResolutionResult(
                source_candidate=candidate,
                status=ResolutionStatus.RESOLVED,
                candidates=(derived,),
                page=RetrievedPage(
                    requested_url=start.url,
                    final_url=start.url,
                    http_status=200,
                    content_type="text/html",
                    text=html,
                    size_bytes=len(html),
                ),
                attempts=1,
            )
        raise AssertionError(
            f"route depth limit leaked fallback route: {candidate.url}"
        )

    def acquire(candidate, **kwargs):
        resource = RetrievedResource(
            requested_url=candidate.url,
            final_url=fallback_url,
            http_status=200,
            content_type="text/html",
            size_bytes=32,
            sha256="0" * 64,
            local_path=None,
            redirects=(),
        )
        return AcquisitionResult(
            candidate=candidate,
            status=AcquisitionStatus.INVALID_PDF,
            retrieved=resource,
        )

    monkeypatch.setattr(service, "resolve_full_text_route", resolve)
    monkeypatch.setattr(service, "acquire_direct_pdf", acquire)
    monkeypatch.setattr(service, "derive_route_expansions", lambda **kwargs: ())

    result = service.acquire_from_discovery(
        _discovery(start),
        output_dir=tmp_path,
        max_route_depth=0,
        use_doi_resolver_fallback=False,
    )

    assert resolve_calls == [start.url]
    assert result.max_route_depth_reached == 0
    assert len(result.file_attempts) == 1
