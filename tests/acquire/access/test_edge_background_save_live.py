"""Only an exactly owned Edge PDF may be foregrounded to finish local Save."""

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
from aletheia_nexus.acquire.access import browser as core
from aletheia_nexus.acquire.access.browser_engine import viewer
from aletheia_nexus.acquire.access.models import BrowserAttemptStatus
from aletheia_nexus.acquire.discovery.models import FullTextCandidate

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1" or os.name != "nt",
    reason="owned background-PDF native-save smoke requires isolated Windows Edge",
)


def test_edge_background_pdf_finishes_native_save_without_touching_other_pages(
    tmp_path, monkeypatch
):
    pytest.importorskip("playwright.sync_api")
    body = (
        Path(__file__).parents[3] / "benchmarks/v07_fixtures/native_article.pdf"
    ).read_bytes()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            mode = self.headers.get("Sec-Fetch-Mode")
            pdf = self.path == "/same.pdf" and mode in {"navigate", "no-cors"}
            plain = self.path == "/plain"
            status = 200 if pdf or plain else 403
            payload = (
                body
                if pdf
                else b"<title>Unrelated foreground page</title>"
                if plain
                else b"Local fixture cors gate"
            )
            requests.append(
                {"pdf": self.path == "/same.pdf", "mode": mode, "status": status}
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/pdf" if pdf else "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    def local_only(value):
        parsed = urlsplit(value)
        if (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == server.server_port
            and parsed.path in {"/same.pdf", "/plain"}
        ):
            return value
        raise ValueError("Only exact owned local fixture endpoints are allowed")

    monkeypatch.setattr(core, "validate_browser_network_url", local_only)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", local_only)
    config = BrowserAccessConfig(
        profile_root=tmp_path / "isolated",
        profile_name="edge-background",
        channel="msedge",
        launch_mode="managed",
        headless=False,
        interactive=False,
        auto_challenge_grace=0,
        request_timeout=15,
        navigation_timeout=10,
    )
    try:
        with BrowserSession(config) as session:
            context = session._ensure_started()
            owned = context.new_page()
            owned.goto(origin + "/same.pdf", wait_until="domcontentloaded")
            other = context.new_page()
            other.goto(origin + "/same.pdf", wait_until="domcontentloaded")
            other.evaluate("window.anOther='preserved'")
            plain = context.new_page()
            plain.goto(origin + "/plain")
            plain.evaluate("window.anPlain='preserved'")
            plain.bring_to_front()
            baseline = list(context.pages)
            urls = {p: p.url for p in baseline}
            focus = []
            original_read = viewer.bounded_read

            def observe_focus(target, method, *args, **kwargs):
                if method == "bring_to_front":
                    assert target is owned
                    focus.append(True)
                return original_read(target, method, *args, **kwargs)

            monkeypatch.setattr(viewer, "bounded_read", observe_focus)
            before = len(requests)
            outcome = browser_route.attempt_browser_route(
                context,
                owned,
                source=FullTextCandidate(
                    doi="10.5555/an.v07.native", url=owned.url, provenance=()
                ),
                output_dir=tmp_path / "output",
                expected_title="A Self-Authored Study of Traceable Parsing",
                config=config,
                session_blocked_urls=[],
                session_pdf_responses=[],
                session_downloads=[],
                _navigate_source=False,
                _browser_native_only=True,
            )
            assert outcome.status == BrowserAttemptStatus.VERIFIED, outcome
            assert outcome.result.file_path.read_bytes() == body and focus == [True]
            assert all(not p.is_closed() and p.url == urls[p] for p in baseline)
            assert (
                other.evaluate("window.anOther") == "preserved"
                and plain.evaluate("window.anPlain") == "preserved"
            )
            assert len(requests) == before
            receipt = json.loads(
                outcome.result.sidecar_path.read_text(encoding="utf-8")
            )
            assert any(
                "caller-owned built-in Edge" in item
                for item in receipt["access"]["evidence"]
            )
            print(
                json.dumps(
                    {
                        "fixture": "owned_background_edge_pdf_save",
                        "verified": True,
                        "bytes": len(body),
                        "owned_focus_count": len(focus),
                        "other_pages_preserved": True,
                        "new_http_requests": 0,
                        "new_browser_pages": len(context.pages) - len(baseline),
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
