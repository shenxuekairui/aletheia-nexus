"""Delivery is independent of unrelated, unreadable embedded documents."""

from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import browser_route
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.discovery.models import FullTextCandidate


@pytest.mark.parametrize("download_state", ["completed", "canceled"])
def test_viewer_save_survives_unreadable_title_and_delayed_download(
    tmp_path, download_state
):
    import json
    from pathlib import Path

    from test_browser_response import _CdpContext, _pdf_bytes

    from aletheia_nexus.acquire.access.browser_engine.viewer import (
        NativeViewerDownloadError,
        trigger_pdf_viewer_save,
    )

    context = _CdpContext()
    session = context.browser.session
    original_send = session.send
    directory = []

    def send(method, params=None):
        original_send(method, params)
        if method == "Browser.setDownloadBehavior" and params.get("downloadPath"):
            directory.append(Path(params["downloadPath"]))
        if method == "Target.getTargets":
            return {
                "targetInfos": [
                    {
                        "type": "webview",
                        "targetId": "viewer",
                        "url": "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html",
                        "title": "Electrochemical reduction of carboxylic acids",
                    }
                ]
            }
        if method == "Target.attachToTarget":
            return {"sessionId": "viewer-session"}
        if method == "Target.sendMessageToTarget":
            session.handlers["Target.receivedMessageFromTarget"](
                {
                    "sessionId": "viewer-session",
                    "message": json.dumps(
                        {"id": 1, "result": {"result": {"value": {"clicked": True}}}}
                    ),
                }
            )

    session.send = send

    class Page:
        url = "https://publisher.example/document.pdf"
        polls = 0

        def title(self):
            raise TimeoutError("Page observation is unavailable")

        def wait_for_timeout(self, milliseconds):
            self.polls += 1
            if self.polls == 1:
                session.handlers["Browser.downloadWillBegin"](
                    {"guid": "delayed", "url": self.url}
                )
            elif self.polls == 2:
                (directory[0] / "delayed").write_bytes(_pdf_bytes())
                session.handlers["Browser.downloadProgress"](
                    {"guid": "delayed", "state": download_state}
                )

    page = Page()

    def save():
        return trigger_pdf_viewer_save(
            context,
            page,
            doi="10.1000/example",
            output_dir=tmp_path,
            expected_title="Electrochemical reduction of carboxylic acids",
            timeout=1,
            max_bytes=100000,
        )

    if download_state == "canceled":
        with pytest.raises(
            NativeViewerDownloadError, match="NativeDownloadCanceled"
        ) as caught:
            save()
        assert caught.value.url == page.url
        assert page.polls == 2 and session.detached
        assert not directory[0].exists()
        return
    result = save()
    assert result is not None
    assert result[0].read_bytes().startswith(b"%PDF-")
    assert page.polls == 2 and session.detached


@pytest.mark.parametrize("native_only", [False, True])
def test_canceled_save_uses_observed_endpoint_once_and_keeps_its_gate(
    monkeypatch, tmp_path, native_only
):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    from aletheia_nexus.acquire.access.browser_engine.viewer import (
        NativeViewerDownloadError,
    )
    from aletheia_nexus.acquire.access.models import BrowserAccessAttempt

    page = _RoutePage("https://publisher.example/article")
    unavailable = ChallengeReport(
        ChallengeKind.UNKNOWN, (browser_route._OBSERVATION_UNAVAILABLE,)
    )
    gate = ChallengeReport(ChallengeKind.CAPTCHA)
    endpoint = "https://publisher.example/article-pdf/123/document.pdf"
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: unavailable)
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda p, **k: (unavailable, (unavailable,), False),
    )

    def canceled(*args, **kwargs):
        raise NativeViewerDownloadError("NativeDownloadCanceled", endpoint)

    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", canceled)
    calls = []
    original = browser_route.attempt_browser_route

    def recover(*args, source, **kwargs):
        calls.append(source.url)
        assert kwargs["_navigation_referrer"] == page.url
        assert (
            kwargs["_browser_native_only"] and not kwargs["_allow_runtime_pdf_handoff"]
        )
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=endpoint,
            status=BrowserAttemptStatus.INTERACTION_REQUIRED,
            challenge_history=(gate,),
        )

    monkeypatch.setattr(browser_route, "attempt_browser_route", recover)
    result = original(
        _RouteContext(page),
        page,
        source=FullTextCandidate(doi="10.1000/example", url=page.url, provenance=()),
        output_dir=tmp_path,
        expected_title="Target article",
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
        _navigate_source=False,
        _browser_native_only=native_only,
    )
    assert calls == ([] if native_only else [endpoint])
    assert result.file_attempts[0].error == "NativeDownloadCanceled"
    assert result.file_attempts[0].candidate.url == endpoint
    assert result.status == (
        BrowserAttemptStatus.RETRIEVAL_FAILED
        if native_only
        else BrowserAttemptStatus.INTERACTION_REQUIRED
    )
    assert result.challenge_history[-1] == (unavailable if native_only else gate)


@pytest.mark.parametrize("post_click", [False, True])
@pytest.mark.parametrize("matching_pdf", [False, True])
def test_unreadable_widget_does_not_discard_verified_native_pdf(
    monkeypatch, tmp_path, post_click, matching_pdf
):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    title = "Electrochemical reduction of carboxylic acids"
    page = _RoutePage("https://publisher.example/article")
    context = _RouteContext(page)
    source = FullTextCandidate(doi="10.1000/example", url=page.url, provenance=())
    clear = ChallengeReport(ChallengeKind.NONE)
    unavailable = ChallengeReport(
        ChallengeKind.UNKNOWN,
        (browser_route._OBSERVATION_UNAVAILABLE, "Embedded document scan incomplete"),
    )
    clicked = []
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda p: clear if post_click and not clicked else unavailable,
    )
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda p, **k: (
            (clear, (), False)
            if post_click and not clicked
            else (unavailable, (unavailable,), False)
        ),
    )
    monkeypatch.setattr(
        browser_route,
        "validate_page_identity",
        lambda **k: SimpleNamespace(status=SimpleNamespace(value="MATCH"), evidence=()),
    )
    monkeypatch.setattr(browser_route, "parse_html", lambda html: object())
    monkeypatch.setattr(browser_route, "derive_pdf_candidates", lambda **k: ())
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *a, **k: None
    )
    monkeypatch.setattr(
        browser_route, "_trigger_pdf_viewer_same_origin_fetch", lambda *a, **k: False
    )
    monkeypatch.setattr(
        browser_route, "_runtime_publisher_pdf_candidate", lambda *a: None
    )
    monkeypatch.setattr(
        browser_route, "_ieee_selected_institution_available", lambda p: False
    )
    monkeypatch.setattr(
        browser_route,
        "_click_semantic_pdf_control",
        lambda p: clicked.append(True) or True,
    )
    monkeypatch.setattr(
        browser_route,
        "_request_pdf_candidate",
        lambda *a, **k: pytest.fail("Must not replay HTTP after an unreadable widget"),
    )

    saved = []

    def save(*args, **kwargs):
        if post_click and not clicked:
            return None
        stage = tmp_path / "native-stage"
        stage.mkdir()
        path = stage / "browser-file"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_metadata(
            {
                "/Title": title
                if matching_pdf
                else "An unrelated quantum cosmology article"
            }
        )
        writer.write(path)
        saved.append(path)
        return path, stage

    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", save)
    result = browser_route.attempt_browser_route(
        context,
        page,
        source=source,
        output_dir=tmp_path / "output",
        expected_title=title,
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
        _navigate_source=False,
    )
    assert unavailable in result.challenge_history
    assert bool(result.status == BrowserAttemptStatus.VERIFIED) == matching_pdf
    assert len(saved) == 1 and not saved[0].exists()
    assert result.file_attempts[-1].method == "browser_viewer_save"
    assert page.goto_calls == []


@pytest.mark.parametrize(
    "kind",
    [
        ChallengeKind.CAPTCHA,
        ChallengeKind.AUTHENTICATION,
        ChallengeKind.MFA,
        ChallengeKind.ENTITLEMENT,
    ],
)
def test_native_save_recovery_does_not_override_confirmed_access_boundary(
    monkeypatch, tmp_path, kind
):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    page = _RoutePage("https://publisher.example/article")
    report = ChallengeReport(kind)
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: report)
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda p, **k: (report, (report,), True),
    )
    monkeypatch.setattr(
        browser_route,
        "_trigger_pdf_viewer_save",
        lambda *a, **k: pytest.fail(
            "Confirmed access gate must retain the usual handoff"
        ),
    )
    result = browser_route.attempt_browser_route(
        _RouteContext(page),
        page,
        source=FullTextCandidate(doi="10.1000/example", url=page.url, provenance=()),
        output_dir=tmp_path,
        expected_title="Target article",
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
        _navigate_source=False,
    )
    assert result.status != BrowserAttemptStatus.VERIFIED
    assert result.challenge_history[-1] == report
