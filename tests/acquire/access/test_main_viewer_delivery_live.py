"""Opt-in offline/loopback main PDF recovery in fresh, isolated browsers."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import pytest

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserSession,
    browser_route,
)
from aletheia_nexus.acquire.access import browser as browser_module
from aletheia_nexus.acquire.access.browser_engine.downloads import CdpDownloadCapture
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser
from aletheia_nexus.acquire.access.models import BrowserFileAttempt
from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="main viewer recovery opens only isolated browsers and a test-owned loopback server",
)


@pytest.mark.parametrize("channel", [None, "msedge"])
@pytest.mark.parametrize("popup_mode", [False, True])
def test_main_inline_pdf_native_save_retains_unrelated_same_url_tab(
    tmp_path, monkeypatch, channel, popup_mode
):
    pytest.importorskip("playwright.sync_api")
    if channel == "msedge" and os.name != "nt":
        pytest.skip("real Edge local-toolbar check requires Windows Edge")
    body = (
        Path(__file__).parents[3] / "benchmarks/v07_fixtures/native_article.pdf"
    ).read_bytes()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            mode = self.headers.get("Sec-Fetch-Mode")
            if self.path == "/article":
                status, content, kind = (
                    200,
                    (
                        b"<title>A Self-Authored Study of Traceable Parsing</title>"
                        b'<meta name="citation_doi" content="10.5555/an.v07.native">'
                        b"<button onclick=\"window.open('/short.pdf')\">Open PDF</button>"
                    ),
                    "text/html",
                )
            elif self.path == "/short.pdf" and mode in {"navigate", "no-cors"}:
                status, content, kind = 200, body, "application/pdf"
            else:
                status, content, kind = (
                    403,
                    b"Local fixture HTTP/JS method gate",
                    "text/plain",
                )
            requests.append({"status": status, "mode": mode, "path": self.path})
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            if kind == "application/pdf":
                self.send_header("Content-Disposition", 'inline; filename="short.pdf"')
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/short.pdf"

    def only_test_endpoint(value):
        parsed = urlsplit(value)
        if (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == server.server_port
            and parsed.path in {"/short.pdf", "/article"}
        ):
            return value
        raise ValueError("Local main-viewer fixture refuses every other endpoint")

    monkeypatch.setattr(
        browser_module, "validate_browser_network_url", only_test_endpoint
    )
    monkeypatch.setattr(
        browser_route, "validate_browser_network_url", only_test_endpoint
    )
    # Force the exact reported failure: native document is rendered but SDK
    # response bytes are its shell, and ordinary credentialed HTTP cannot read.
    monkeypatch.setattr(
        browser_route,
        "_browser_response_to_file_attempt",
        lambda *args, **kw: BrowserFileAttempt(
            candidate=kw["parent"],
            error="NativePdfViewerPlaceholder: synthetic unreadable response",
        ),
    )
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *args, **kw: None
    )
    original_wait = CdpDownloadCapture.wait

    def observed_wait(capture, page, timeout, **kwargs):
        result = original_wait(capture, page, timeout, **kwargs)
        if kwargs.get("expected_frame_ids") is not None and result is None:
            print(
                json.dumps(
                    {
                        "capture_failed": True,
                        "owned_frames": len(kwargs["expected_frame_ids"]),
                        "transfers": [
                            {
                                "state": t.state,
                                "owned_frame": t.frame_id
                                in kwargs["expected_frame_ids"],
                                "same_url": t.url == page.url,
                            }
                            for t in capture._transfers.values()
                        ],
                    }
                )
            )
        return result

    monkeypatch.setattr(CdpDownloadCapture, "wait", observed_wait)
    config = BrowserAccessConfig(
        profile_root=tmp_path / "isolated-profile",
        profile_name="local-main-viewer",
        launch_mode="managed",
        channel=channel,
        executable_path=(
            os.environ.get("AN_TEST_BROWSER_EXECUTABLE") or fixed_portable_browser()
        )
        if channel is None
        else None,
        headless=False,
        interactive=False,
        auto_challenge_grace=0,
        request_timeout=15,
        navigation_timeout=10,
    )
    try:
        with BrowserSession(config) as session:
            context = session._ensure_started()
            other = context.new_page()
            other.goto(url, wait_until="domcontentloaded")
            other.evaluate("window.anUnrelatedPdf='preserved'")
            outcome = session.acquire(
                doi="10.5555/an.v07.native",
                expected_title="A Self-Authored Study of Traceable Parsing",
                routes=[
                    FullTextCandidate(
                        doi="10.5555/an.v07.native",
                        url=url.rsplit("/", 1)[0] + "/article" if popup_mode else url,
                        provenance=(),
                    )
                ],
                output_dir=tmp_path / "output",
            )
            if outcome.verified_result is None:
                print(
                    json.dumps(
                        {
                            "channel": channel,
                            "requests": requests,
                            "attempts": [
                                {
                                    "status": a.status.value,
                                    "error": a.error,
                                    "challenge": [
                                        c.kind.value for c in a.challenge_history
                                    ],
                                    "files": [
                                        {
                                            "method": f.method,
                                            "error": f.error,
                                            "status": f.result.status.value
                                            if f.result
                                            else None,
                                        }
                                        for f in a.file_attempts
                                    ],
                                }
                                for a in outcome.attempts
                            ],
                        }
                    )
                )
            assert outcome.verified_result is not None, outcome
            assert outcome.verified_result.status == AcquisitionStatus.VERIFIED
            assert outcome.verified_result.file_path.read_bytes() == body
            assert any(
                f.method == "browser_viewer_save"
                and f.result
                and f.result.status == AcquisitionStatus.VERIFIED
                for a in outcome.attempts
                for f in a.file_attempts
            ), outcome
            assert (
                not other.is_closed()
                and other.evaluate("window.anUnrelatedPdf") == "preserved"
            )
            print(
                json.dumps(
                    {
                        "fixture": "main_placeholder_to_owned_native_save",
                        "channel": channel or "chromium",
                        "popup_mode": popup_mode,
                        "bytes": len(body),
                        "verified": True,
                        "other_same_url_page_unchanged": True,
                        "requests": requests,
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
