"""Main-document viewer recovery keeps page ownership and failure evidence."""

import pytest

from aletheia_nexus.acquire.access import browser_route
from aletheia_nexus.acquire.access.browser_engine import viewer
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.discovery.models import FullTextCandidate


@pytest.mark.parametrize("kind", ["iframe", "webview"])
def test_default_save_uses_exact_owner_even_when_title_is_short(
    tmp_path, monkeypatch, kind
):
    from test_owned_viewer_save import fixture, target

    context, page, capture, commands = fixture(
        tmp_path,
        [
            target("user", "user-page", kind=kind),
            target("owned", "owned-page", kind=kind),
        ],
    )
    # The parent remains an HTML article; the native PDF may be an embedded
    # child. Matching its document URL to page.url would fail unnecessarily.
    page.url = "https://pubs.acs.org/article"
    saved = tmp_path / "native-file"
    saved.write_bytes(b"%PDF-test")
    waits, closes = [], []

    def wait(owner, seconds, **kwargs):
        assert owner is page and kwargs["wait_for_start"]
        assert {"owned-frame", "owned-viewer-frame", "owned-pdf-frame"} <= kwargs[
            "expected_frame_ids"
        ]
        waits.append(seconds)
        return saved, "https://pubs.acs.org/jp4c00353.pdf"

    capture.wait = wait
    capture.close = lambda **kwargs: closes.append(kwargs)
    monkeypatch.setattr(viewer, "CdpDownloadCapture", lambda *args: capture)
    diagnostics = []
    result = viewer.trigger_pdf_viewer_save(
        context,
        page,
        doi="10.1021/acs.jpcc.4c00353",
        expected_title=None,
        output_dir=tmp_path,
        timeout=1,
        max_bytes=1000,
        diagnostics=diagnostics,
    )
    assert result == (saved, tmp_path) and waits and not diagnostics
    assert closes == [{"remove_files": False}]
    assert [
        p["targetId"] for method, p in commands if method == "Target.attachToTarget"
    ] == ["owned"]


def test_real_context_cannot_fall_back_to_another_matching_pdf_tab(
    tmp_path, monkeypatch
):
    from test_owned_viewer_save import fixture, target

    context, page, capture, commands = fixture(tmp_path, [target("user", "user-page")])
    capture.close = lambda **kwargs: None
    monkeypatch.setattr(viewer, "CdpDownloadCapture", lambda *args: capture)
    diagnostics = []
    assert (
        viewer.trigger_pdf_viewer_save(
            context,
            page,
            doi="10.1000/same",
            expected_title="same.pdf",
            output_dir=tmp_path,
            timeout=0,
            max_bytes=1000,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics == ["NativePdfViewerOwnedTargetNotFound"]
    assert not any(method == "Target.attachToTarget" for method, _ in commands)


def test_native_capture_filters_same_url_downloads_by_owned_frame(tmp_path):
    from test_browser_response import _CdpContext, _WaitPage

    from aletheia_nexus.acquire.access.browser_engine.downloads import (
        CdpDownloadCapture,
    )

    context = _CdpContext()
    capture = CdpDownloadCapture(context, tmp_path)
    session = context.browser.session
    try:
        for identity, frame in [("user", "user-frame"), ("owned", "owned-frame")]:
            (capture.staging_dir / identity).write_bytes(b"%PDF-file")
            session.handlers["Browser.downloadWillBegin"](
                {
                    "guid": identity,
                    "url": _WaitPage.url,
                    "frameId": frame,
                }
            )
            session.handlers["Browser.downloadProgress"](
                {"guid": identity, "state": "completed"}
            )
        result = capture.wait(_WaitPage(), 0, expected_frame_ids={"owned-frame"})
        assert result[0].name == "owned"
        assert capture.wait(_WaitPage(), 0, expected_frame_ids={"missing"}) is None
        assert capture.has_unclaimed_downloads({"owned-frame"})
    finally:
        capture.close()


def test_failed_owned_save_preserves_unclaimed_concurrent_download_file(
    tmp_path, monkeypatch
):
    from test_browser_response import _CdpContext

    from aletheia_nexus.acquire.access.browser_engine.downloads import (
        CdpDownloadCapture,
    )

    context = _CdpContext()
    capture = CdpDownloadCapture(context, tmp_path)
    stage = capture.staging_dir
    user_file = stage / "unrelated-user-guid"
    user_file.write_bytes(b"%PDF-unrelated-user-download")
    capture.session.handlers["Browser.downloadWillBegin"](
        {
            "guid": user_file.name,
            "url": "https://publisher.example/same.pdf",
            "frameId": "user-frame",
        }
    )
    capture.session.handlers["Browser.downloadProgress"](
        {"guid": user_file.name, "state": "completed"}
    )

    class Owner:
        def send(self, method):
            return (
                {"targetInfo": {"targetId": "owned-page"}}
                if method == "Target.getTargetInfo"
                else {"frameTree": {"frame": {"id": "owned-frame"}}}
            )

        def detach(self):
            pass

    context.new_cdp_session = lambda page: Owner()
    original_send = capture.session.send

    def send(method, params=None):
        return (
            {"targetInfos": []}
            if method == "Target.getTargets"
            else original_send(method, params)
        )

    capture.session.send = send
    monkeypatch.setattr(viewer, "CdpDownloadCapture", lambda *args: capture)
    page = type("Page", (), {"url": "https://publisher.example/same.pdf"})()
    assert (
        viewer.trigger_pdf_viewer_save(
            context,
            page,
            doi="10.1000/same",
            output_dir=tmp_path,
            expected_title=None,
            timeout=0,
            max_bytes=1000,
        )
        is None
    )
    assert user_file.read_bytes() == b"%PDF-unrelated-user-download"
    assert capture.session is None  # Only this capture disconnected; file survives.


def test_main_prefers_native_save_before_fetching_a_rendered_pdf_again(
    tmp_path, monkeypatch
):
    from pypdf import PdfWriter
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    page = _RoutePage("https://publisher.example/document.pdf")
    clear = ChallengeReport(ChallengeKind.NONE)
    title = "Electrochemical reduction of carboxylic acids"
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: clear)
    monkeypatch.setattr(
        browser_route, "_resolve_page_challenge", lambda p, **kw: (clear, (), False)
    )
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *args, **kw: None
    )
    monkeypatch.setattr(
        browser_route,
        "_trigger_pdf_viewer_same_origin_fetch",
        lambda *args, **kw: pytest.fail(
            "Native PDF must be saved before another cache-altering fetch"
        ),
    )

    def save(*args, **kwargs):
        stage = tmp_path / "native-stage"
        stage.mkdir()
        path = stage / "native.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata({"/Title": title})
        writer.write(path)
        return path, stage

    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", save)
    outcome = browser_route.attempt_browser_route(
        _RouteContext(page),
        page,
        source=FullTextCandidate(doi="10.1000/example", url=page.url, provenance=()),
        output_dir=tmp_path / "output",
        expected_title=title,
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
        _navigate_source=False,
    )
    assert outcome.status == BrowserAttemptStatus.VERIFIED


@pytest.mark.parametrize("failure", ["no-control", "protocol-error"])
def test_main_pdf_save_failure_is_recorded_without_raw_exception(
    tmp_path, monkeypatch, failure
):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    page = _RoutePage("https://publisher.example/document.pdf")
    unavailable = ChallengeReport(
        ChallengeKind.UNKNOWN, (browser_route._OBSERVATION_UNAVAILABLE,)
    )
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: unavailable)
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda p, **kw: (unavailable, (unavailable,), False),
    )

    def save(*args, diagnostics, **kwargs):
        diagnostics.append("NativePdfViewerOwnedPageActivated")
        diagnostics.append(
            "NativePdfViewerLocalSaveControlUnavailable"
            if failure == "no-control"
            else "NativePdfViewerSaveError:TimeoutError"
        )

    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", save)
    outcome = browser_route.attempt_browser_route(
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
    assert outcome.status != BrowserAttemptStatus.VERIFIED
    assert outcome.file_attempts[-1].method == "browser_viewer_save"
    assert outcome.file_attempts[-1].error.startswith("NativePdfViewer")
    assert not outcome.file_attempts[-1].error.startswith(
        "NativePdfViewerOwnedPageActivated"
    )
    assert "caller-owned Edge PDF page was activated" in outcome.file_attempts[-1].error


def test_default_viewer_protocol_exception_has_only_safe_error_type(
    tmp_path, monkeypatch
):
    from test_owned_viewer_save import fixture

    context, page, capture, _ = fixture(tmp_path, [])
    capture.close = lambda **kwargs: None
    monkeypatch.setattr(viewer, "CdpDownloadCapture", lambda *args: capture)

    def fail(_page):
        raise TimeoutError("ws://127.0.0.1:9222/devtools/secret?token=do-not-record")

    context.new_cdp_session = fail
    diagnostics = []
    assert (
        viewer.trigger_pdf_viewer_save(
            context,
            page,
            doi="10.1000/same",
            output_dir=tmp_path,
            expected_title=None,
            timeout=1,
            max_bytes=1000,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics == ["NativePdfViewerSaveError:TimeoutError"]


@pytest.mark.parametrize(
    "edge,timeout,activated", [(True, 8, True), (False, 8, False), (True, 1, False)]
)
def test_only_scoped_edge_focuses_once_after_ready_timeout_within_original_budget(
    tmp_path, monkeypatch, edge, timeout, activated
):
    from test_owned_viewer_save import fixture, target

    path = "edge_pdf/index.html" if edge else "index.html"
    url = "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/" + path
    context, page, capture, commands = fixture(
        tmp_path,
        [
            target("other", "other-page", url=url),
            target("owned", "owned-page", url=url),
        ],
    )
    clock, focus_times, waits = [0.0], [], []
    monkeypatch.setattr(viewer.time, "monotonic", lambda: clock[0])
    page.wait_for_timeout = lambda milliseconds: clock.__setitem__(
        0, clock[0] + milliseconds / 1000
    )
    page.bring_to_front = lambda: focus_times.append(clock[0])
    monkeypatch.setattr(
        viewer,
        "_target_command",
        lambda *args: (
            {"result": {"value": {"ready": bool(focus_times)}}}
            if args[3] == "Runtime.evaluate"
            else {}
        ),
    )
    saved = tmp_path / "owned.pdf"
    saved.write_bytes(b"%PDF-test")

    def wait(owner, seconds):
        waits.append(seconds)
        return saved, page.url

    diagnostics = []
    result = viewer.trigger_pdf_viewer_save(
        context,
        page,
        doi="10.1000/same",
        output_dir=tmp_path,
        expected_title=None,
        timeout=timeout,
        max_bytes=1000,
        owned_page_only=True,
        native_capture=capture,
        owned_frame_ids=set(),
        download_wait=wait,
        diagnostics=diagnostics,
    )
    assert bool(result) == activated
    if activated:
        assert len(focus_times) == 1 and 3 <= focus_times[0] < 3.2
        assert 0 < waits[0] <= timeout - focus_times[0]
        assert diagnostics == ["NativePdfViewerOwnedPageActivated"]
    else:
        assert not focus_times and not waits
        assert diagnostics == ["NativePdfViewerLocalSaveControlUnavailable"]
    assert [
        p["targetId"] for method, p in commands if method == "Target.attachToTarget"
    ] == ["owned"]


def test_confirmed_native_pdf_is_saved_before_embedded_cache_fetch(
    tmp_path, monkeypatch
):
    import json

    from pypdf import PdfWriter
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    page = _RoutePage("https://publisher.example/document.pdf")
    clear = ChallengeReport(ChallengeKind.NONE)
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: clear)
    monkeypatch.setattr(
        browser_route, "_resolve_page_challenge", lambda p, **kw: (clear, (), False)
    )
    monkeypatch.setattr(browser_route, "native_pdf_url", lambda *a, **kw: page.url)
    monkeypatch.setattr(
        browser_route,
        "_trigger_embedded_pdf_frame_fetch",
        lambda *a, **kw: pytest.fail(
            "A confirmed native PDF must not be re-fetched before Save"
        ),
    )
    monkeypatch.setattr(
        browser_route,
        "_trigger_pdf_viewer_same_origin_fetch",
        lambda *a, **kw: pytest.fail(
            "Do not replace the entitled response before Save"
        ),
    )
    title = "Electrochemical reduction of carboxylic acids"

    def save(*args, diagnostics, **kwargs):
        diagnostics.append("NativePdfViewerOwnedPageActivated")
        stage = tmp_path / "stage"
        stage.mkdir()
        path = stage / "owned.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata({"/Title": title})
        writer.write(path)
        return path, stage

    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", save)
    outcome = browser_route.attempt_browser_route(
        _RouteContext(page),
        page,
        source=FullTextCandidate(doi="10.1000/example", url=page.url, provenance=()),
        output_dir=tmp_path / "output",
        expected_title=title,
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
        _navigate_source=False,
    )
    assert outcome.status == BrowserAttemptStatus.VERIFIED
    source = json.loads(outcome.result.sidecar_path.read_text(encoding="utf-8"))
    assert any(
        "caller-owned built-in Edge" in evidence
        for evidence in source["access"]["evidence"]
    )
