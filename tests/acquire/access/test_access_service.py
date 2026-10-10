from dataclasses import replace
from pathlib import Path

import pytest

from aletheia_nexus.acquire.access import PaperRequest, service
from aletheia_nexus.acquire.access.browser import (
    BrowserCapabilityUnavailable,
    BrowserSession,
)
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserRecoveryResult,
    ElsevierAccessAttempt,
    ElsevierAccessConfig,
    ElsevierAccessStatus,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryResult,
    FullTextCandidate,
    HostType,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
)
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    RouteAttempt,
    RouteCandidateOrigin,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    ResolutionStatus,
    RetrievedPage,
    RouteResolutionResult,
)


def _candidate(
    url="https://publisher.example/article",
    *,
    url_type=CandidateUrlType.LANDING_PAGE,
):
    return FullTextCandidate(
        doi="10.1000/target",
        url=url,
        provenance=(),
        url_type=url_type,
        host_type=HostType.PUBLISHER,
    )


def _base(status=FullTextAcquisitionStatus.EXHAUSTED, *, candidate=None):
    candidate = candidate or _candidate()
    discovery = DiscoveryResult(
        doi="10.1000/target",
        candidates=(candidate,),
        providers=(),
    )
    verified = None
    if status == FullTextAcquisitionStatus.VERIFIED:
        verified = AcquisitionResult(
            candidate=candidate,
            status=AcquisitionStatus.VERIFIED,
            file_path=Path("paper.pdf"),
        )
    return MultiRouteAcquisitionResult(
        doi="10.1000/target",
        status=status,
        discovery=discovery,
        verified_result=verified,
        expected_title="Target Article",
    )


@pytest.mark.parametrize(
    "preference,enabled,expected",
    [
        ("auto", True, ["public", "cnki"]),
        ("auto", False, ["public", "generic"]),
        ("exclude_cnki", True, ["public", "generic"]),
    ],
)
def test_first_seen_indexed_english_journal_routes_before_generic_challenge(
    monkeypatch, tmp_path, preference, enabled, expected
):
    from types import SimpleNamespace

    calls = []
    base = replace(
        _base(),
        metadata=SimpleNamespace(
            title="Target Article",
            journal="Journal of Electrochemistry",
            issn=("2993-074X",),
            publisher="Editorial office",
        ),
    )
    monkeypatch.setattr(
        service, "acquire_full_text", lambda *a, **k: calls.append("public") or base
    )
    artifact = AcquisitionResult(
        candidate=_candidate(),
        status=AcquisitionStatus.VERIFIED,
        file_path=tmp_path / "verified.pdf",
    )
    from aletheia_nexus.acquire.access.models import BrowserFileAttempt

    attempt = BrowserAccessAttempt(
        _candidate(),
        None,
        BrowserAttemptStatus.VERIFIED,
        file_attempts=(BrowserFileAttempt(candidate=_candidate(), result=artifact),),
    )
    monkeypatch.setattr(
        service,
        "acquire_with_browser_provider",
        lambda *a, **k: calls.append("cnki") or attempt,
    )
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **k: (
            calls.append("generic")
            or BrowserRecoveryResult(
                doi="10.1000/target",
                attempts=(),
                verified_result=None,
                profile_dir=tmp_path,
            )
        ),
    )
    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        source_preference=preference,
        auto_official_api=False,
        browser_config=BrowserAccessConfig(cnki_enabled=enabled),
    )
    assert calls == expected
    if enabled and preference == "auto":
        assert result.status == MaximizedAcquisitionStatus.VERIFIED
        assert any(
            "cnki_indexed_issn:2993-074X" in e
            for e in result.browser_attempts[0].evidence
        )


@pytest.mark.parametrize(
    "preference,enabled,called",
    [
        ("cnki", True, True),
        ("cnki", False, False),
        ("exclude_cnki", True, False),
        ("auto", True, True),
    ],
)
def test_doi_less_routing_controls_do_not_invoke_old_doi_pipeline(
    monkeypatch, tmp_path, preference, enabled, called
):
    monkeypatch.setattr(
        service,
        "acquire_full_text",
        lambda *a, **k: pytest.fail("DOI-less must not use DOI resolver"),
    )
    calls = []

    def provider(*args, **kwargs):
        calls.append(args[0].request)
        return BrowserAccessAttempt(_candidate(), None, BrowserAttemptStatus.AMBIGUOUS)

    monkeypatch.setattr(service, "acquire_with_browser_provider", provider)
    request = PaperRequest(title="中文研究论文测试题名", authors=("张三",))
    result = service.acquire_full_text_maximized(
        request,
        output_dir=tmp_path,
        source_preference=preference,
        browser_config=BrowserAccessConfig(cnki_enabled=enabled),
    )
    assert bool(calls) is called
    assert result.status == (
        MaximizedAcquisitionStatus.AMBIGUOUS
        if called
        else MaximizedAcquisitionStatus.EXHAUSTED
    )


def test_cnki_started_download_cannot_replay_or_be_masked_by_generic_auth(
    monkeypatch, tmp_path
):
    candidate = _candidate("https://kns.cnki.net/kcms2/article/abstract")
    base = _base(candidate=candidate)
    monkeypatch.setattr(service, "acquire_full_text", lambda *a, **k: base)
    attempt = BrowserAccessAttempt(
        candidate,
        candidate.url,
        BrowserAttemptStatus.RETRIEVAL_FAILED,
        download_started=True,
        evidence=("CNKI transport failure",),
    )
    monkeypatch.setattr(
        service, "acquire_with_browser_provider", lambda *a, **k: attempt
    )
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **k: pytest.fail("Started CNKI download must not be replayed"),
    )
    result = service.acquire_full_text_maximized("10.1000/target", output_dir=tmp_path)
    assert result.browser_attempts[0].status == BrowserAttemptStatus.RETRIEVAL_FAILED
    assert len(result.browser_attempts) == 1
    assert result.status != MaximizedAcquisitionStatus.INTERACTION_REQUIRED


def test_explicit_cnki_skips_public_but_local_file_still_takes_precedence(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        service,
        "acquire_full_text",
        lambda *a, **k: pytest.fail("CNKI-only cannot use public DOI pipeline"),
    )
    calls = []
    monkeypatch.setattr(
        service,
        "acquire_with_browser_provider",
        lambda *a, **k: (
            calls.append("cnki")
            or BrowserAccessAttempt(
                _candidate(), None, BrowserAttemptStatus.NO_FILE_CANDIDATES
            )
        ),
    )
    service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        expected_title="English title",
        source_preference="cnki",
    )
    assert calls == ["cnki"]
    from aletheia_nexus.acquire.access.models import MaximizedAcquisitionResult

    monkeypatch.setattr(
        service,
        "resolve_user_operated_access",
        lambda *a, **k: (
            calls.append("local")
            or MaximizedAcquisitionResult(
                "10.1000/target", MaximizedAcquisitionStatus.VERIFIED, _base()
            )
        ),
    )
    service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        local_pdf_path=tmp_path / "chosen.pdf",
        source_preference="cnki",
    )
    assert calls == ["cnki", "local"]


def test_foreign_metadata_with_translated_title_retains_browser_routes(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    base = replace(
        _base(),
        expected_title="用户提供的中文翻译题名",
        metadata=SimpleNamespace(
            doi="10.1000/target",
            year=2024,
            title="Original English article",
            journal="Nature",
            publisher="Nature",
        ),
    )
    monkeypatch.setattr(service, "acquire_full_text", lambda *a, **k: base)
    monkeypatch.setattr(
        service,
        "acquire_with_browser_provider",
        lambda *a, **k: pytest.fail("Foreign metadata must not start CNKI"),
    )
    routes = []

    def browser(**kwargs):
        from aletheia_nexus.acquire.fulltext.storage import _publication_fields

        assert _publication_fields(kwargs["doi"]) == (2024, "Nature")
        routes.extend(kwargs["routes"])
        return BrowserRecoveryResult(doi=base.doi, attempts=())

    monkeypatch.setattr(service, "acquire_with_browser", browser)
    service.acquire_full_text_maximized(
        base.doi, output_dir=tmp_path, auto_official_api=False
    )
    assert any("doi.org" in candidate.url for candidate in routes)


@pytest.mark.parametrize(
    "publisher_outcome", ["verified", "exhausted", "interaction", "started"]
)
def test_weak_chinese_title_respects_original_publisher_flow(
    monkeypatch, tmp_path, publisher_outcome
):
    base = replace(_base(), expected_title="缺少可靠来源的中文题名")
    calls = []
    monkeypatch.setattr(
        service, "acquire_full_text", lambda *a, **k: calls.append("public") or base
    )

    def browser(**kwargs):
        calls.append("publisher")
        attempt = BrowserAccessAttempt(
            _candidate(),
            None,
            BrowserAttemptStatus.INTERACTION_REQUIRED
            if publisher_outcome == "interaction"
            else BrowserAttemptStatus.NO_FILE_CANDIDATES,
            download_started=publisher_outcome == "started",
        )
        return BrowserRecoveryResult(
            doi=base.doi,
            attempts=(attempt,),
            verified_result=_base(FullTextAcquisitionStatus.VERIFIED).verified_result
            if publisher_outcome == "verified"
            else None,
        )

    monkeypatch.setattr(service, "acquire_with_browser", browser)
    monkeypatch.setattr(
        service,
        "acquire_with_browser_provider",
        lambda *a, **k: (
            calls.append("cnki")
            or BrowserAccessAttempt(
                _candidate(), None, BrowserAttemptStatus.NO_FILE_CANDIDATES
            )
        ),
    )
    service.acquire_full_text_maximized(
        base.doi, output_dir=tmp_path, auto_official_api=False
    )
    assert calls == (
        ["public", "publisher", "cnki"]
        if publisher_outcome == "exhausted"
        else ["public", "publisher"]
    )


def test_browser_recovery_plan_includes_discovery_and_resolver():
    base = _base()
    routes = service.browser_recovery_routes(base, limit=8)

    assert routes[0].url == "https://publisher.example/article"
    assert any(
        route.url.startswith("https://doi.org/10.1000/target") for route in routes
    )


def test_browser_recovery_plan_adds_acs_canonical_pdf_route():
    candidate = FullTextCandidate(
        doi="10.1021/cr050182l",
        url="https://pubs.acs.org/doi/10.1021/cr050182l",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.PUBLISHER,
    )
    base = MultiRouteAcquisitionResult(
        doi=candidate.doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(
            doi=candidate.doi,
            candidates=(candidate,),
            providers=(),
        ),
        expected_title="Target Article",
    )

    routes = service.browser_recovery_routes(base, limit=3)

    assert routes[0].url == "https://pubs.acs.org/doi/pdf/10.1021/cr050182l"
    assert routes[0].url_type == CandidateUrlType.PDF


@pytest.mark.parametrize("pdf_host", [HostType.PUBLISHER, HostType.UNKNOWN])
def test_recovery_plan_keeps_observed_pdf_before_inferred_route(pdf_host):
    landing = _candidate("https://onlinelibrary.wiley.com/doi/10.1000/target")
    observed = replace(
        landing,
        url="https://files.example/article.pdf",
        url_type=CandidateUrlType.PDF,
        host_type=pdf_host,
        source_name="Observed article metadata",
    )
    base = _base(candidate=landing)
    base = replace(
        base, discovery=replace(base.discovery, candidates=(landing, observed))
    )

    routes = service.browser_recovery_routes(base, limit=1)
    assert routes == (observed,)


def test_recovery_plan_preserves_observed_canonical_url_provenance():
    observed = replace(
        _candidate(
            "https://onlinelibrary.wiley.com/doi/pdf/10.1000/target",
            url_type=CandidateUrlType.PDF,
        ),
        source_name="Observed article metadata",
    )
    routes = service.browser_recovery_routes(_base(candidate=observed), limit=1)
    assert routes == (observed,)


def test_browser_recovery_plan_adds_acs_pdf_route_from_doi():
    doi = "10.1021/jacs.6c03536"
    base = MultiRouteAcquisitionResult(
        doi=doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(doi=doi, candidates=(), providers=()),
        expected_title="Target Article",
    )

    routes = service.browser_recovery_routes(base, limit=3)

    assert routes[0].url == "https://pubs.acs.org/doi/pdf/10.1021/jacs.6c03536"


def test_browser_recovery_plan_adds_thieme_pdf_route_from_doi():
    doi = "10.1055/a-2508-9744"
    base = MultiRouteAcquisitionResult(
        doi=doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(doi=doi, candidates=(), providers=()),
        expected_title="Target Article",
    )

    routes = service.browser_recovery_routes(base, limit=3)

    assert routes[0].url == (
        "https://www.thieme-connect.com/products/ejournals/pdf/10.1055/a-2508-9744.pdf"
    )


def test_browser_recovery_plan_prioritizes_nature_article_pdf():
    candidate = FullTextCandidate(
        doi="10.1038/35104620",
        url="https://www.nature.com/articles/35104620",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.PUBLISHER,
    )
    base = MultiRouteAcquisitionResult(
        doi=candidate.doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(
            doi=candidate.doi,
            candidates=(candidate,),
            providers=(),
        ),
        expected_title="Materials for fuel-cell technologies",
    )

    routes = service.browser_recovery_routes(base, limit=2)

    assert routes[0].url == "https://www.nature.com/articles/35104620.pdf"
    assert routes[0].url_type == CandidateUrlType.PDF


def test_browser_recovery_plan_adds_wiley_subdomain_pdf_route():
    candidate = FullTextCandidate(
        doi="10.1111/j.1151-2916.1993.tb03645.x",
        url=(
            "https://ceramics.onlinelibrary.wiley.com/doi/"
            "10.1111/j.1151-2916.1993.tb03645.x"
        ),
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.PUBLISHER,
    )
    base = MultiRouteAcquisitionResult(
        doi=candidate.doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(
            doi=candidate.doi,
            candidates=(candidate,),
            providers=(),
        ),
        expected_title="Target Article",
    )

    routes = service.browser_recovery_routes(base, limit=3)

    assert routes[0].url.endswith("/doi/pdf/10.1111/j.1151-2916.1993.tb03645.x")
    assert routes[0].url_type == CandidateUrlType.PDF


def test_browser_recovery_derives_canonical_route_from_resolved_final_url():
    resolver = FullTextCandidate(
        doi="10.1002/ente.202100008",
        url="https://doi.org/10.1002/ente.202100008",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.RESOLVER,
    )
    final_url = "https://onlinelibrary.wiley.com/doi/10.1002/ente.202100008"
    resolved = RouteResolutionResult(
        source_candidate=resolver,
        status=ResolutionStatus.ACCESS_BLOCKED,
        page=RetrievedPage(
            requested_url=resolver.url,
            final_url=final_url,
            http_status=403,
            content_type="text/html",
            text=None,
            size_bytes=0,
        ),
    )
    base = MultiRouteAcquisitionResult(
        doi=resolver.doi,
        status=FullTextAcquisitionStatus.ACCESS_BLOCKED,
        discovery=DiscoveryResult(
            doi=resolver.doi,
            candidates=(resolver,),
            providers=(),
        ),
        route_attempts=(
            RouteAttempt(
                candidate=resolver,
                origin=RouteCandidateOrigin.DOI_RESOLVER_FALLBACK,
                result=resolved,
            ),
        ),
        expected_title="Target Article",
    )

    routes = service.browser_recovery_routes(base, limit=2)

    assert routes[0].url == (
        "https://onlinelibrary.wiley.com/doi/pdf/10.1002/ente.202100008"
    )


@pytest.mark.parametrize(
    ("doi", "landing_url", "expected_url"),
    [
        (
            "10.1002/ente.202100008",
            "https://onlinelibrary.wiley.com/doi/10.1002/ente.202100008",
            "https://onlinelibrary.wiley.com/doi/pdf/10.1002/ente.202100008",
        ),
        (
            "10.1080/19443994.2012.719466",
            "https://www.tandfonline.com/doi/full/10.1080/19443994.2012.719466",
            "https://www.tandfonline.com/doi/pdf/10.1080/19443994.2012.719466",
        ),
        (
            "10.1061/(ASCE)0733-9372(2007)133:11(1004)",
            (
                "https://ascelibrary.org/doi/10.1061/"
                "%28ASCE%290733-9372%282007%29133%3A11%281004%29"
            ),
            (
                "https://ascelibrary.org/doi/pdf/10.1061/"
                "%28ASCE%290733-9372%282007%29133%3A11%281004%29"
            ),
        ),
        (
            "10.3390/membranes11030183",
            "https://www.mdpi.com/2077-0375/11/3/183",
            "https://www.mdpi.com/2077-0375/11/3/183/pdf",
        ),
        (
            "10.1038/35104620",
            "https://www.nature.com/articles/35104620",
            "https://www.nature.com/articles/35104620.pdf",
        ),
        (
            "10.1038/nature02863",
            "https://www.nature.com/articles/nature02863",
            "https://www.nature.com/articles/nature02863.pdf",
        ),
        (
            "10.1055/a-2508-9744",
            "https://www.thieme-connect.com/products/ejournals/abstract/10.1055/a-2508-9744",
            "https://www.thieme-connect.com/products/ejournals/pdf/10.1055/a-2508-9744.pdf",
        ),
        (
            "10.1055/a-2508-9744",
            "https://doi.org/10.1055/a-2508-9744",
            "https://www.thieme-connect.com/products/ejournals/pdf/10.1055/a-2508-9744.pdf",
        ),
    ],
)
def test_supported_publishers_derive_canonical_pdf_route(
    doi,
    landing_url,
    expected_url,
):
    candidate = FullTextCandidate(
        doi=doi,
        url=landing_url,
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.PUBLISHER,
    )

    derived = service._canonical_publisher_pdf_candidate(candidate)

    assert derived is not None
    assert derived.url == expected_url
    assert derived.url_type == CandidateUrlType.PDF


def test_ieee_xplore_does_not_derive_automated_pdf_route():
    candidate = FullTextCandidate(
        doi="10.1109/ICEET.2009.450",
        url="https://ieeexplore.ieee.org/document/5366888/",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.PUBLISHER,
    )

    assert service._canonical_publisher_pdf_candidate(candidate) is None


def test_publisher_route_rejects_credentialed_or_nonstandard_port_url():
    candidate = FullTextCandidate(
        doi="10.1038/35104620",
        url="https://name:secret@www.nature.com/articles/35104620",
        provenance=(),
    )
    assert service._canonical_publisher_pdf_candidate(candidate) is None
    assert (
        service._canonical_publisher_pdf_candidate(
            replace(
                candidate,
                url="https://www.nature.com:8443/articles/35104620",
            )
        )
        is None
    )


def test_ieee_maximized_uses_browser_page_after_public_routes(monkeypatch, tmp_path):
    doi = "10.1109/iceet.2009.450"
    candidate = FullTextCandidate(
        doi=doi,
        url="https://ieeexplore.ieee.org/document/5366888/",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.PUBLISHER,
    )
    base = MultiRouteAcquisitionResult(
        doi=doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(doi=doi, candidates=(candidate,), providers=()),
        expected_title="Test IEEE article",
    )
    calls = []

    def fake_public(requested_doi, **kwargs):
        calls.append(("public", requested_doi))
        return base

    def fake_browser(**kwargs):
        calls.append(("browser", kwargs["doi"]))
        assert kwargs["routes"][0].url == candidate.url
        assert kwargs["expected_title"] == "Test IEEE article"
        return BrowserRecoveryResult(doi=doi)

    monkeypatch.setattr(service, "acquire_full_text", fake_public)
    monkeypatch.setattr(service, "acquire_with_browser", fake_browser)

    result = service.acquire_full_text_maximized(
        doi,
        output_dir=tmp_path,
        expected_title="Test IEEE article",
    )

    assert calls == [("public", doi), ("browser", doi)]
    assert result.status == MaximizedAcquisitionStatus.EXHAUSTED


def test_canonical_article_route_outranks_supplement_route():
    canonical = FullTextCandidate(
        doi="10.1021/acs.est.0c06552",
        url="https://pubs.acs.org/doi/pdf/10.1021/acs.est.0c06552",
        provenance=(),
        url_type=CandidateUrlType.PDF,
        host_type=HostType.PUBLISHER,
        source_name="Publisher canonical DOI PDF route",
    )
    supplement = replace(
        canonical,
        url="https://acs.figshare.com/ndownloader/files/es0c06552_si_001.pdf",
        source_name="Publisher supplement",
    )

    assert service._browser_route_score(
        canonical,
        explicit_access_barrier=False,
    ) > service._browser_route_score(
        supplement,
        explicit_access_barrier=True,
    )


def test_maximized_stops_when_v05_already_verified(monkeypatch, tmp_path):
    base = _base(FullTextAcquisitionStatus.VERIFIED)
    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)

    def should_not_open_browser(**kwargs):
        raise AssertionError("browser must not start after v0.5 VERIFIED")

    monkeypatch.setattr(service, "acquire_with_browser", should_not_open_browser)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
    )

    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert result.verified_result == base.verified_result
    assert result.browser_attempts == ()


def test_maximized_escalates_and_accepts_only_verified_browser_result(
    monkeypatch,
    tmp_path,
):
    base = _base()
    verified = AcquisitionResult(
        candidate=_candidate(
            "https://publisher.example/article.pdf",
            url_type=CandidateUrlType.PDF,
        ),
        status=AcquisitionStatus.VERIFIED,
        file_path=tmp_path / "article.pdf",
    )
    attempt = BrowserAccessAttempt(
        source_candidate=_candidate(),
        final_url="https://publisher.example/article",
        status=BrowserAttemptStatus.VERIFIED,
        file_attempts=(),
    )
    recovery = BrowserRecoveryResult(
        doi="10.1000/target",
        attempts=(attempt,),
        verified_result=verified,
        profile_dir=tmp_path / "profile",
    )

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)
    monkeypatch.setattr(service, "acquire_with_browser", lambda **kwargs: recovery)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        browser_config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert result.verified_result == verified
    assert result.browser_attempts == (attempt,)


def test_unresolved_captcha_surfaces_interaction_required(monkeypatch, tmp_path):
    base = _base()
    attempt = BrowserAccessAttempt(
        source_candidate=_candidate(),
        final_url="https://publisher.example/challenge",
        status=BrowserAttemptStatus.INTERACTION_REQUIRED,
    )
    recovery = BrowserRecoveryResult(
        doi="10.1000/target",
        attempts=(attempt,),
        profile_dir=tmp_path / "profile",
    )

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)
    monkeypatch.setattr(service, "acquire_with_browser", lambda **kwargs: recovery)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
    )

    assert result.status == MaximizedAcquisitionStatus.INTERACTION_REQUIRED


def test_missing_browser_dependency_is_explicit(monkeypatch, tmp_path):
    base = _base()
    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)

    def unavailable(**kwargs):
        raise BrowserCapabilityUnavailable("browser missing")

    monkeypatch.setattr(service, "acquire_with_browser", unavailable)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
    )

    assert result.status == MaximizedAcquisitionStatus.BROWSER_UNAVAILABLE
    assert result.message == "browser missing"


def test_maximized_can_use_caller_owned_browser_session(monkeypatch, tmp_path):
    base = _base()
    verified = AcquisitionResult(
        candidate=_candidate(
            "https://publisher.example/article.pdf",
            url_type=CandidateUrlType.PDF,
        ),
        status=AcquisitionStatus.VERIFIED,
        file_path=tmp_path / "article.pdf",
    )
    recovery = BrowserRecoveryResult(
        doi="10.1000/target",
        verified_result=verified,
        profile_dir=tmp_path / "profile",
    )
    session = BrowserSession(BrowserAccessConfig(profile_root=tmp_path))

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)
    monkeypatch.setattr(session, "acquire", lambda **kwargs: recovery)

    def should_not_open_temporary_session(**kwargs):
        raise AssertionError("caller-owned session should be reused")

    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        should_not_open_temporary_session,
    )

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        browser_session=session,
    )

    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert result.verified_result == verified


def test_browser_config_and_session_are_mutually_exclusive(tmp_path):
    session = BrowserSession(BrowserAccessConfig(profile_root=tmp_path))

    try:
        service.acquire_full_text_maximized(
            "10.1000/target",
            output_dir=tmp_path,
            browser_config=BrowserAccessConfig(profile_root=tmp_path),
            browser_session=session,
        )
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("expected mutually exclusive browser options to fail")


def test_official_elsevier_api_stops_before_browser_when_verified(
    monkeypatch,
    tmp_path,
):
    base = _base()
    verified = AcquisitionResult(
        candidate=_candidate(
            "https://api.elsevier.com/content/article/doi/10.1000/target",
            url_type=CandidateUrlType.PDF,
        ),
        status=AcquisitionStatus.VERIFIED,
        file_path=tmp_path / "elsevier.pdf",
    )
    api_attempt = ElsevierAccessAttempt(
        status=ElsevierAccessStatus.VERIFIED,
        result=verified,
        http_status=200,
        credential_modes=("api_key",),
    )

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)
    monkeypatch.setattr(service, "_should_try_elsevier_api", lambda value: True)
    monkeypatch.setattr(
        service,
        "acquire_elsevier_pdf",
        lambda *args, **kwargs: api_attempt,
    )

    def should_not_open_browser(**kwargs):
        raise AssertionError("browser must not run after official API VERIFIED")

    monkeypatch.setattr(service, "acquire_with_browser", should_not_open_browser)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        elsevier_config=ElsevierAccessConfig(api_key="secret"),
    )

    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert result.verified_result == verified
    assert result.elsevier_attempt == api_attempt
    assert result.browser_attempts == ()


def test_failed_elsevier_api_falls_through_to_browser(monkeypatch, tmp_path):
    base = _base()
    api_attempt = ElsevierAccessAttempt(
        status=ElsevierAccessStatus.ACCESS_DENIED,
        http_status=403,
        credential_modes=("api_key",),
    )
    browser_attempt = BrowserAccessAttempt(
        source_candidate=_candidate(),
        final_url="https://publisher.example/article",
        status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
    )
    recovery = BrowserRecoveryResult(
        doi="10.1000/target",
        attempts=(browser_attempt,),
        profile_dir=tmp_path / "profile",
    )

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)
    monkeypatch.setattr(service, "_should_try_elsevier_api", lambda value: True)
    monkeypatch.setattr(
        service,
        "acquire_elsevier_pdf",
        lambda *args, **kwargs: api_attempt,
    )
    monkeypatch.setattr(service, "acquire_with_browser", lambda **kwargs: recovery)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        elsevier_config=ElsevierAccessConfig(api_key="secret"),
    )

    assert result.status == MaximizedAcquisitionStatus.ACCESS_DENIED
    assert result.elsevier_attempt == api_attempt
    assert result.browser_attempts == (browser_attempt,)


def test_elsevier_auth_failure_is_preserved_after_browser_exhaustion():
    from aletheia_nexus.acquire.access.models import (
        ElsevierAccessAttempt,
        ElsevierAccessStatus,
    )

    base = _base()
    status, message = service._final_status_from_browser(
        base,
        (),
        elsevier_attempt=ElsevierAccessAttempt(
            status=ElsevierAccessStatus.AUTH_REQUIRED,
            http_status=401,
        ),
    )

    assert status == MaximizedAcquisitionStatus.AUTH_REQUIRED
    assert "credentials" in message.lower()


def test_elsevier_entitlement_is_preserved_after_browser_exhaustion():
    from aletheia_nexus.acquire.access.models import (
        ElsevierAccessAttempt,
        ElsevierAccessStatus,
    )

    base = _base()
    status, message = service._final_status_from_browser(
        base,
        (),
        elsevier_attempt=ElsevierAccessAttempt(
            status=ElsevierAccessStatus.ENTITLEMENT_REQUIRED,
            http_status=403,
        ),
    )

    assert status == MaximizedAcquisitionStatus.ENTITLEMENT_REQUIRED
    assert "entitlement" in message.lower()


def test_maximized_auto_discovers_elsevier_env_credentials(monkeypatch, tmp_path):
    base = _base()
    discovered = ElsevierAccessConfig(api_key="env-secret")
    api_attempt = ElsevierAccessAttempt(
        status=ElsevierAccessStatus.ACCESS_DENIED,
        http_status=403,
        credential_modes=("api_key",),
    )
    recovery = BrowserRecoveryResult(
        doi="10.1000/target",
        attempts=(),
        profile_dir=tmp_path / "profile",
    )

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)
    monkeypatch.setattr(service, "_should_try_elsevier_api", lambda value: True)
    monkeypatch.setattr(
        ElsevierAccessConfig,
        "from_env",
        classmethod(lambda cls: discovered),
    )

    seen = {}

    def fake_api(*args, **kwargs):
        seen["config"] = kwargs["config"]
        return api_attempt

    monkeypatch.setattr(service, "acquire_elsevier_pdf", fake_api)
    monkeypatch.setattr(service, "acquire_with_browser", lambda **kwargs: recovery)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
    )

    assert seen["config"] is discovered
    assert result.elsevier_attempt == api_attempt


def test_maximized_can_disable_env_provider_discovery(monkeypatch, tmp_path):
    base = _base()
    recovery = BrowserRecoveryResult(
        doi="10.1000/target",
        attempts=(),
        profile_dir=tmp_path / "profile",
    )

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)

    def should_not_read_env():
        raise AssertionError("official provider env discovery must be disabled")

    monkeypatch.setattr(
        ElsevierAccessConfig,
        "from_env",
        classmethod(lambda cls: should_not_read_env()),
    )
    monkeypatch.setattr(service, "acquire_with_browser", lambda **kwargs: recovery)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        auto_official_api=False,
    )

    assert result.elsevier_attempt is None


def test_unexpected_browser_error_does_not_persist_secret_message(
    monkeypatch,
    tmp_path,
):
    base = _base()
    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)

    def explode(**kwargs):
        raise RuntimeError("failed at https://publisher.example/pdf?token=super-secret")

    monkeypatch.setattr(service, "acquire_with_browser", explode)

    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
    )

    assert result.status == MaximizedAcquisitionStatus.ERROR
    assert result.message == "Browser recovery failed unexpectedly: RuntimeError"
    assert "super-secret" not in result.message
    assert "publisher.example" not in result.message


def test_mixed_browser_access_denied_is_not_downgraded_to_exhausted():
    base = _base()
    attempts = (
        BrowserAccessAttempt(
            source_candidate=_candidate("https://publisher.example/blocked"),
            final_url="https://publisher.example/blocked",
            status=BrowserAttemptStatus.ACCESS_DENIED,
        ),
        BrowserAccessAttempt(
            source_candidate=_candidate("https://publisher.example/no-file"),
            final_url="https://publisher.example/no-file",
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        ),
    )

    status, message = service._final_status_from_browser(base, attempts)

    assert status == MaximizedAcquisitionStatus.ACCESS_DENIED
    assert "access-denied" in message.lower()


def test_all_browser_internal_failures_surface_error():
    base = _base()
    attempts = (
        BrowserAccessAttempt(
            source_candidate=_candidate("https://publisher.example/error"),
            final_url=None,
            status=BrowserAttemptStatus.ERROR,
        ),
        BrowserAccessAttempt(
            source_candidate=_candidate("https://publisher.example/nav"),
            final_url=None,
            status=BrowserAttemptStatus.NAVIGATION_ERROR,
        ),
    )

    status, message = service._final_status_from_browser(base, attempts)

    assert status == MaximizedAcquisitionStatus.ERROR
    assert "browser/navigation errors" in message.lower()


def test_browser_config_type_error_precedes_base_acquisition(monkeypatch, tmp_path):
    def should_not_run_base(*args, **kwargs):
        raise AssertionError(
            "invalid browser_config must fail before v0.5 network work"
        )

    monkeypatch.setattr(service, "acquire_full_text", should_not_run_base)

    try:
        service.acquire_full_text_maximized(
            "10.1000/target",
            output_dir=tmp_path,
            browser_config="not-a-config",
        )
    except TypeError as exc:
        assert "browser_config" in str(exc)
    else:
        raise AssertionError("invalid browser_config must raise TypeError")
