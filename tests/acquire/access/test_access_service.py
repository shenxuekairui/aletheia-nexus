from pathlib import Path

from aletheia_nexus.acquire.access import service
from aletheia_nexus.acquire.access.browser import (
    BrowserCapabilityUnavailable,
    BrowserSession,
)
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserRecoveryResult,
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


def test_browser_recovery_plan_includes_discovery_and_resolver():
    base = _base()
    routes = service.browser_recovery_routes(base, limit=8)

    assert routes[0].url == "https://publisher.example/article"
    assert any(
        route.url.startswith("https://doi.org/10.1000/target") for route in routes
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
