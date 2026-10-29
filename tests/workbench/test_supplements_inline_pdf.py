"""Native inline PDFs are files, not evidence of an unfinished download event."""

import base64
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionTooLargeError
from aletheia_nexus.workbench import supplements_browser as module

DOI = "10.1002/cctc.202201687"
PAGE = "https://chemistry-europe.onlinelibrary.wiley.com/doi/" + DOI
FILE = "https://chemistry-europe.onlinelibrary.wiley.com/action/downloadSupplement?doi=10.1002%2Fcctc.202201687&file=local-supplement.pdf"
PDF = b"%PDF-local-fixture-content"
SHELL = b'<html><embed type="application/pdf" src="about:blank" internalid="local-only"></html>'


def native_fixture(
    monkeypatch,
    *,
    body=PDF,
    declared=None,
    frame="owned",
    root=None,
    finished=True,
    viewer=None,
):
    reads, scripts, captures = [], [], []

    class Capture:
        active = True
        staging_dir = None
        _context_params = {}

        def __init__(self, *_):
            self.session = SimpleNamespace(on=lambda *_: None)
            captures.append(self)

        def close(self, *, remove_files):
            self.closed = True

    class Page:
        def __init__(self):
            self.main_frame = object()
            self.url, self.closed, self.handlers = FILE, False, {}

        def route(self, *args):
            pass

        def on(self, event, handler):
            self.handlers[event] = handler

        def goto(self, url, **kwargs):
            request = SimpleNamespace(
                url=root or url,
                redirected_from=None,
                frame=self.main_frame if frame == "owned" else object(),
                timing={"responseEnd": 0 if finished else -1},
            )
            if root:
                request = SimpleNamespace(
                    url=url,
                    redirected_from=request,
                    frame=request.frame,
                    timing=request.timing,
                )
            response = SimpleNamespace(
                url=url,
                request=request,
                status=200,
                headers={
                    "content-type": "application/pdf;charset=UTF-8",
                    "content-length": str(len(body) if declared is None else declared),
                },
                body=lambda: reads.append(True) or body,
            )
            self.handlers["response"](response)
            return response

        def is_closed(self):
            return self.closed

        def close(self):
            self.closed = True

        def wait_for_timeout(self, *_):
            pass

    page = Page()
    context = SimpleNamespace(
        new_page=lambda: page,
        new_cdp_session=lambda _: SimpleNamespace(
            send=lambda method: {"frameTree": {"frame": {"id": "owned-frame"}}},
            on=lambda *_: None,
            detach=lambda: None,
        ),
    )
    session = SimpleNamespace(
        _context=context, config=BrowserAccessConfig(auto_challenge_grace=0)
    )

    def read(target, operation, *args, **kwargs):
        if operation == "body":
            return target.body()
        if operation == "title":
            return ""
        if args[0] == "document.contentType":
            return "application/pdf"
        assert args[0] is module._PDF_FETCH_SCRIPT
        scripts.append(args[1])
        return viewer

    monkeypatch.setattr(module, "CdpDownloadCapture", Capture)
    monkeypatch.setattr(module, "bounded_read", read)
    monkeypatch.setattr(
        module,
        "_resolve_page_challenge",
        lambda *a, **kw: (ChallengeReport(ChallengeKind.NONE), (), False),
    )
    return (
        module.SupplementBrowserTransport(session, doi=DOI),
        page,
        reads,
        scripts,
        captures,
    )


def fetch(adapter, tmp_path, *, max_bytes=100, timeout=0.1):
    return adapter._native_file(
        FILE,
        source_page=PAGE,
        output_dir=tmp_path,
        max_bytes=max_bytes,
        timeout=timeout,
    )


def test_inline_pdf_response_returns_real_bytes_without_download_event(
    tmp_path, monkeypatch
):
    adapter, page, reads, scripts, captures = native_fixture(monkeypatch)
    resource = fetch(adapter, tmp_path)
    assert resource.local_path.read_bytes() == PDF and resource.http_status == 200
    assert reads == [True] and not scripts
    assert page.closed and captures[0].closed
    assert any(
        d["status"] == "BROWSER_NATIVE_PDF_RESPONSE"
        and d["reason"] == "PDF_BYTES_RECEIVED"
        for d in adapter.diagnostics
    )


@pytest.mark.parametrize("case", ["other-frame", "other-root"])
def test_same_url_from_another_frame_or_unrelated_request_is_never_adopted(
    tmp_path, monkeypatch, case
):
    adapter, page, reads, scripts, _ = native_fixture(
        monkeypatch,
        frame="other" if case == "other-frame" else "owned",
        root="https://chemistry-europe.onlinelibrary.wiley.com/unrelated"
        if case == "other-root"
        else None,
    )
    with pytest.raises(
        module.SupplementBrowserError, match="browser_attachment_delivery_not_completed"
    ):
        fetch(adapter, tmp_path, timeout=0.001)
    assert not reads and not scripts and not list(tmp_path.iterdir()) and page.closed


@pytest.mark.parametrize(
    "body,declared,expected_read", [(PDF, 1000, False), (PDF * 10, 1, True)]
)
def test_inline_pdf_byte_cap_applies_before_and_after_body_read(
    tmp_path, monkeypatch, body, declared, expected_read
):
    adapter, page, reads, _, _ = native_fixture(
        monkeypatch, body=body, declared=declared
    )
    with pytest.raises(AcquisitionTooLargeError):
        fetch(adapter, tmp_path, max_bytes=100)
    assert bool(reads) == expected_read and page.closed and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "declared,body,finished",
    [(len(SHELL), SHELL, True), (0, PDF, True), (len(PDF), PDF, False)],
)
def test_pdf_shell_unknown_length_or_loading_response_uses_bounded_owned_viewer(
    tmp_path, monkeypatch, declared, body, finished
):
    viewer = {"url": FILE, "status": 200, "bodyBase64": base64.b64encode(PDF).decode()}
    adapter, page, reads, scripts, _ = native_fixture(
        monkeypatch, body=body, declared=declared, finished=finished, viewer=viewer
    )
    resource = fetch(adapter, tmp_path)
    assert resource.local_path.read_bytes() == PDF and page.closed
    assert (
        scripts[0]["maxBytes"] == 100
        and scripts[0]["returnBody"]
        and scripts[0]["cache"] == "force-cache"
    )
    assert bool(reads) is (declared > 0 and finished)


def test_bounded_viewer_stream_cap_is_not_downgraded_to_an_incomplete_event(
    tmp_path, monkeypatch
):
    adapter, page, _, _, _ = native_fixture(
        monkeypatch, body=SHELL, viewer={"reason": "STREAM_SIZE_LIMIT", "status": 200}
    )
    with pytest.raises(AcquisitionTooLargeError):
        fetch(adapter, tmp_path)
    assert page.closed and not list(tmp_path.iterdir())


def test_bounded_viewer_must_match_the_owned_observed_document_url(
    tmp_path, monkeypatch
):
    adapter, page, _, scripts, _ = native_fixture(monkeypatch)
    page.url = "https://chemistry-europe.onlinelibrary.wiley.com/different-document.pdf"
    assert (
        adapter._inline_pdf_viewer(
            page,
            url=FILE,
            expected_urls={FILE},
            source_page=PAGE,
            output_dir=tmp_path,
            max_bytes=100,
            deadline=module.time.monotonic() + 1,
        )
        is None
    )
    assert not scripts and not list(tmp_path.iterdir())


def test_readable_pdf_response_uses_core_native_save_when_body_is_a_shell(
    tmp_path, monkeypatch
):
    adapter, page, _, scripts, captures = native_fixture(monkeypatch, body=SHELL)
    path = tmp_path / "native-owned.pdf"
    path.write_bytes(PDF)
    calls = []

    def save(context, owner, **options):
        assert owner is page and options["owned_page_only"]
        assert options["native_capture"] is captures[0]
        assert options["owned_frame_ids"] == {"owned-frame"}
        assert callable(options["download_wait"])
        calls.append(True)
        return path, tmp_path

    monkeypatch.setattr(module, "trigger_pdf_viewer_save", save)
    resource = fetch(adapter, tmp_path)
    assert resource.local_path.read_bytes() == PDF and page.closed
    assert calls == [True] and not scripts
    assert any(
        d["status"] == "BROWSER_NATIVE_VIEWER_SAVE"
        and d["reason"] == "PDF_BYTES_RECEIVED"
        for d in adapter.diagnostics
    )


def test_opened_pdf_without_save_capability_is_retained_and_requires_manual_action(
    tmp_path, monkeypatch
):
    adapter, page, reads, _, _ = native_fixture(
        monkeypatch, body=SHELL, viewer={"reason": "HTTP_STATUS", "status": 403}
    )
    monkeypatch.setattr(module, "trigger_pdf_viewer_save", lambda *a, **kw: None)
    with pytest.raises(
        module.SupplementBrowserError, match="attachment_interaction_required"
    ):
        fetch(adapter, tmp_path)
    assert not page.closed and reads == [True] and not list(tmp_path.iterdir())
    diagnostic = adapter.diagnostics[-1]
    assert diagnostic["status"] == "BROWSER_PDF_VIEWER_MANUAL_SAVE_REQUIRED"
    assert diagnostic["page_retained"] and diagnostic["needs_manual_check"]
    assert "尚未取得可验证" in diagnostic["message"]


def test_native_viewer_save_size_failure_is_not_manual_wait_or_success(
    tmp_path, monkeypatch
):
    adapter, page, _, _, _ = native_fixture(monkeypatch, body=SHELL)

    def save(*a, **kw):
        raise module.NativeViewerDownloadError("NativeDownloadSizeLimit", FILE)

    monkeypatch.setattr(module, "trigger_pdf_viewer_save", save)
    with pytest.raises(AcquisitionTooLargeError):
        fetch(adapter, tmp_path)
    assert page.closed and not list(tmp_path.iterdir())
