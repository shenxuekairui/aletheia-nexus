from dataclasses import replace

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
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FileCandidateOrigin,
    FullTextAcquisitionStatus,
    RouteCandidateOrigin,
    TitleSource,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    DerivedFullTextCandidate,
    ResolutionStatus,
    RouteResolutionResult,
)
from aletheia_nexus.core.models import PaperMetadata


def _candidate(url: str, url_type: CandidateUrlType) -> FullTextCandidate:
    return FullTextCandidate(
        doi="10.1000/target",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=url_type,
    )


def _discovery(
    *candidates: FullTextCandidate,
    provider_status: ProviderDiscoveryStatus = ProviderDiscoveryStatus.SUCCESS,
) -> DiscoveryResult:
    provider = ProviderDiscoveryResult(
        provider=DiscoveryProvider.OPENALEX,
        status=provider_status,
        candidates=tuple(candidates),
    )
    skipped = ProviderDiscoveryResult(
        provider=DiscoveryProvider.UNPAYWALL,
        status=ProviderDiscoveryStatus.SKIPPED,
        candidates=(),
    )
    return DiscoveryResult(
        doi="10.1000/target",
        candidates=tuple(candidates),
        providers=(provider, skipped),
    )


def _acquisition(
    candidate: FullTextCandidate,
    status: AcquisitionStatus,
    *,
    retrieved: RetrievedResource | None = None,
) -> AcquisitionResult:
    return AcquisitionResult(
        candidate=candidate,
        status=status,
        retrieved=retrieved,
    )


def _derived(
    parent: FullTextCandidate,
    url: str,
    *,
    method: DerivationMethod = DerivationMethod.CITATION_PDF_URL,
    role: DocumentRole = DocumentRole.ARTICLE,
) -> DerivedFullTextCandidate:
    return DerivedFullTextCandidate(
        candidate=replace(parent, url=url, url_type=CandidateUrlType.PDF),
        parent_url=parent.url,
        source_page_url=parent.url,
        method=method,
        role_hint=role,
        evidence=("test evidence",),
        priority=100,
    )


def test_direct_verified_pdf_stops_before_route_resolution(monkeypatch, tmp_path):
    direct = _candidate("https://example.org/paper.pdf", CandidateUrlType.PDF)
    landing = _candidate("https://example.org/article", CandidateUrlType.LANDING_PAGE)

    monkeypatch.setattr(
        service,
        "acquire_direct_pdf",
        lambda candidate, **kwargs: _acquisition(candidate, AcquisitionStatus.VERIFIED),
    )

    def should_not_resolve(*args, **kwargs):
        raise AssertionError("route resolution should not run after direct success")

    monkeypatch.setattr(service, "resolve_full_text_route", should_not_resolve)

    result = service.acquire_from_discovery(
        _discovery(direct, landing),
        output_dir=tmp_path,
    )

    assert result.status == FullTextAcquisitionStatus.VERIFIED
    assert len(result.file_attempts) == 1
    assert result.file_attempts[0].origin == FileCandidateOrigin.DISCOVERY
    assert result.route_attempts == ()


def test_failed_direct_pdf_falls_back_to_route_and_verifies(monkeypatch, tmp_path):
    direct = _candidate("https://example.org/bad.pdf", CandidateUrlType.PDF)
    landing = _candidate("https://example.org/article", CandidateUrlType.LANDING_PAGE)
    derived = _derived(landing, "https://example.org/good.pdf")

    def acquire(candidate, **kwargs):
        status = (
            AcquisitionStatus.VERIFIED
            if candidate.url.endswith("good.pdf")
            else AcquisitionStatus.INVALID_PDF
        )
        return _acquisition(candidate, status)

    monkeypatch.setattr(service, "acquire_direct_pdf", acquire)
    monkeypatch.setattr(
        service,
        "resolve_full_text_route",
        lambda candidate, **kwargs: RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.RESOLVED,
            candidates=(derived,),
            attempts=1,
        ),
    )

    result = service.acquire_from_discovery(
        _discovery(direct, landing),
        output_dir=tmp_path,
    )

    assert result.status == FullTextAcquisitionStatus.VERIFIED
    assert [attempt.candidate.url for attempt in result.file_attempts] == [
        direct.url,
        derived.candidate.url,
    ]
    assert result.page_route_attempts == 1


def test_http_pdf_tries_https_upgrade_before_original(monkeypatch, tmp_path):
    direct = _candidate("http://repo.example.org/paper.pdf", CandidateUrlType.PDF)
    upgraded = _derived(
        direct,
        "https://repo.example.org/paper.pdf",
        method=DerivationMethod.HTTPS_UPGRADE,
        role=DocumentRole.UNKNOWN,
    )
    attempted_urls: list[str] = []

    monkeypatch.setattr(
        service,
        "resolve_full_text_route",
        lambda candidate, **kwargs: RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.RESOLVED,
            candidates=(upgraded,),
            attempts=0,
        ),
    )

    def acquire(candidate, **kwargs):
        attempted_urls.append(candidate.url)
        return _acquisition(candidate, AcquisitionStatus.VERIFIED)

    monkeypatch.setattr(service, "acquire_direct_pdf", acquire)

    result = service.acquire_from_discovery(
        _discovery(direct),
        output_dir=tmp_path,
    )

    assert result.status == FullTextAcquisitionStatus.VERIFIED
    assert attempted_urls == [upgraded.candidate.url]
    assert result.route_attempts[0].origin == RouteCandidateOrigin.PDF_TRANSFORM
    assert result.page_route_attempts == 0


def test_invalid_pdf_html_response_is_reinterpreted_as_route(monkeypatch, tmp_path):
    direct = _candidate("https://example.org/download", CandidateUrlType.PDF)
    final_route = "https://example.org/article"
    final_pdf = "https://example.org/article.pdf"
    calls: list[tuple[str, str]] = []

    def acquire(candidate, **kwargs):
        calls.append(("file", candidate.url))
        if candidate.url == final_pdf:
            return _acquisition(candidate, AcquisitionStatus.VERIFIED)
        return _acquisition(
            candidate,
            AcquisitionStatus.INVALID_PDF,
            retrieved=RetrievedResource(
                requested_url=candidate.url,
                final_url=final_route,
                http_status=200,
                content_type="text/html; charset=utf-8",
                size_bytes=100,
                sha256="0" * 64,
                local_path=None,
            ),
        )

    def resolve(candidate, **kwargs):
        calls.append(("route", candidate.url))
        derived = _derived(candidate, final_pdf)
        return RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.RESOLVED,
            candidates=(derived,),
            attempts=1,
        )

    monkeypatch.setattr(service, "acquire_direct_pdf", acquire)
    monkeypatch.setattr(service, "resolve_full_text_route", resolve)

    result = service.acquire_from_discovery(
        _discovery(direct),
        output_dir=tmp_path,
    )

    assert result.status == FullTextAcquisitionStatus.VERIFIED
    assert calls == [
        ("file", direct.url),
        ("route", final_route),
        ("file", final_pdf),
    ]
    assert result.route_attempts[0].origin == RouteCandidateOrigin.INVALID_PDF_FALLBACK


def test_duplicate_derived_file_is_not_downloaded_twice(monkeypatch, tmp_path):
    route_a = _candidate("https://example.org/a", CandidateUrlType.LANDING_PAGE)
    route_b = _candidate("https://example.org/b", CandidateUrlType.LANDING_PAGE)
    shared_pdf = "https://cdn.example.org/shared.pdf"

    monkeypatch.setattr(
        service,
        "resolve_full_text_route",
        lambda candidate, **kwargs: RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.RESOLVED,
            candidates=(_derived(candidate, shared_pdf),),
            attempts=1,
        ),
    )
    monkeypatch.setattr(
        service,
        "acquire_direct_pdf",
        lambda candidate, **kwargs: _acquisition(
            candidate, AcquisitionStatus.RETRIEVED_UNVERIFIED
        ),
    )

    result = service.acquire_from_discovery(
        _discovery(route_a, route_b),
        output_dir=tmp_path,
        use_doi_resolver_fallback=False,
    )

    assert result.status == FullTextAcquisitionStatus.EXHAUSTED
    assert len(result.file_attempts) == 1
    assert result.duplicate_file_candidates_skipped == 1


def test_supplement_hint_is_skipped_before_article_candidate(monkeypatch, tmp_path):
    landing = _candidate("https://example.org/article", CandidateUrlType.LANDING_PAGE)
    supplement = _derived(
        landing,
        "https://example.org/si.pdf",
        role=DocumentRole.SUPPLEMENT,
    )
    article = _derived(landing, "https://example.org/main.pdf")

    monkeypatch.setattr(
        service,
        "resolve_full_text_route",
        lambda candidate, **kwargs: RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.RESOLVED,
            candidates=(supplement, article),
            attempts=1,
        ),
    )
    monkeypatch.setattr(
        service,
        "acquire_direct_pdf",
        lambda candidate, **kwargs: _acquisition(candidate, AcquisitionStatus.VERIFIED),
    )

    result = service.acquire_from_discovery(
        _discovery(landing),
        output_dir=tmp_path,
    )

    assert result.status == FullTextAcquisitionStatus.VERIFIED
    assert result.supplement_candidates_skipped == 1
    assert [attempt.candidate.url for attempt in result.file_attempts] == [
        article.candidate.url
    ]


def test_empty_discovery_distinguishes_no_candidates_from_provider_failure(tmp_path):
    no_candidates = _discovery(provider_status=ProviderDiscoveryStatus.NO_CANDIDATES)
    failed = _discovery(provider_status=ProviderDiscoveryStatus.NETWORK_ERROR)

    first = service.acquire_from_discovery(
        no_candidates,
        output_dir=tmp_path,
        use_doi_resolver_fallback=False,
    )
    second = service.acquire_from_discovery(
        failed,
        output_dir=tmp_path,
        use_doi_resolver_fallback=False,
    )

    assert first.status == FullTextAcquisitionStatus.NO_CANDIDATES
    assert second.status == FullTextAcquisitionStatus.DISCOVERY_FAILED


def test_empty_discovery_can_recover_through_doi_resolver(monkeypatch, tmp_path):
    discovery = _discovery(provider_status=ProviderDiscoveryStatus.NO_CANDIDATES)
    resolved_pdf = "https://publisher.example.org/article.pdf"

    def resolve(candidate, **kwargs):
        assert candidate.url == "https://doi.org/10.1000/target"
        assert candidate.provenance == ()
        assert candidate.source_name == "DOI resolver fallback"
        return RouteResolutionResult(
            source_candidate=candidate,
            status=ResolutionStatus.RESOLVED,
            candidates=(_derived(candidate, resolved_pdf),),
            attempts=1,
        )

    monkeypatch.setattr(service, "resolve_full_text_route", resolve)
    monkeypatch.setattr(
        service,
        "acquire_direct_pdf",
        lambda candidate, **kwargs: _acquisition(candidate, AcquisitionStatus.VERIFIED),
    )

    result = service.acquire_from_discovery(
        discovery,
        output_dir=tmp_path,
        use_doi_resolver_fallback=True,
    )

    assert result.status == FullTextAcquisitionStatus.VERIFIED
    assert result.route_attempts[0].origin == RouteCandidateOrigin.DOI_RESOLVER_FALLBACK
    assert result.file_attempts[0].candidate.url == resolved_pdf


def test_file_attempt_limit_stops_before_unnecessary_route_work(monkeypatch, tmp_path):
    first = _candidate("https://example.org/one.pdf", CandidateUrlType.PDF)
    second = _candidate("https://example.org/two.pdf", CandidateUrlType.PDF)
    landing = _candidate("https://example.org/article", CandidateUrlType.LANDING_PAGE)

    monkeypatch.setattr(
        service,
        "acquire_direct_pdf",
        lambda candidate, **kwargs: _acquisition(
            candidate, AcquisitionStatus.INVALID_PDF
        ),
    )

    def should_not_resolve(*args, **kwargs):
        raise AssertionError("route work should not run after file budget is exhausted")

    monkeypatch.setattr(service, "resolve_full_text_route", should_not_resolve)

    result = service.acquire_from_discovery(
        _discovery(first, second, landing),
        output_dir=tmp_path,
        max_file_attempts=1,
    )

    assert result.status == FullTextAcquisitionStatus.LIMIT_REACHED
    assert len(result.file_attempts) == 1


def test_acquire_full_text_uses_metadata_title_when_user_title_missing(
    monkeypatch, tmp_path
):
    discovery = _discovery()
    metadata = PaperMetadata(
        doi="10.1000/target",
        title="Metadata supplied title",
        authors=(),
        journal=None,
        issn=(),
        published_date=None,
        year=None,
        publisher=None,
        work_type=None,
        volume=None,
        issue=None,
        pages=None,
        url=None,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        service, "discover_full_text", lambda *args, **kwargs: discovery
    )
    monkeypatch.setattr(
        service,
        "_metadata_lookup",
        lambda *args, **kwargs: (metadata, None),
    )

    def orchestrate(value, **kwargs):
        captured["title"] = kwargs["expected_title"]
        captured["doi_fallback"] = kwargs["use_doi_resolver_fallback"]
        return service.MultiRouteAcquisitionResult(
            doi=value.doi,
            status=FullTextAcquisitionStatus.NO_CANDIDATES,
            discovery=value,
        )

    monkeypatch.setattr(service, "acquire_from_discovery", orchestrate)

    result = service.acquire_full_text(
        "10.1000/target",
        output_dir=tmp_path,
    )

    assert captured["title"] == "Metadata supplied title"
    assert captured["doi_fallback"] is True
    assert result.metadata == metadata
    assert result.title_source == TitleSource.METADATA


def test_user_title_skips_metadata_lookup(monkeypatch, tmp_path):
    discovery = _discovery()

    monkeypatch.setattr(
        service, "discover_full_text", lambda *args, **kwargs: discovery
    )

    def should_not_lookup(*args, **kwargs):
        raise AssertionError("metadata lookup should be skipped when title is supplied")

    monkeypatch.setattr(service, "_metadata_lookup", should_not_lookup)
    monkeypatch.setattr(
        service,
        "acquire_from_discovery",
        lambda value, **kwargs: service.MultiRouteAcquisitionResult(
            doi=value.doi,
            status=FullTextAcquisitionStatus.NO_CANDIDATES,
            discovery=value,
            expected_title=kwargs["expected_title"],
        ),
    )

    result = service.acquire_full_text(
        "10.1000/target",
        output_dir=tmp_path,
        expected_title="Known title",
    )

    assert result.expected_title == "Known title"
    assert result.title_source == TitleSource.USER
