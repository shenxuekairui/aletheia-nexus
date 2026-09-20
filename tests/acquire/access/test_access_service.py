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
