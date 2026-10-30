"""Opt-in native PDF Save uses an isolated browser and only our loopback server."""

import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access import browser as browser_module
from aletheia_nexus.acquire.access.browser_engine import viewer
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser
from aletheia_nexus.workbench import supplements_browser as module
from aletheia_nexus.workbench.supplements import _validate_attachment

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="native PDF Save requires isolated Chromium and a test-owned loopback HTTP server",
)


def test_real_native_save_owns_one_of_two_identical_url_pdf_viewers(
    tmp_path, monkeypatch
):
    pytest.importorskip("playwright.sync_api")
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=127, height=100)
    writer.write(buffer)
    body = buffer.getvalue()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/article":
                content, status, kind = (
                    b"<title>Local fixture article</title><h1>Local article</h1>",
                    200,
                    "text/html",
                )
            elif self.path == "/supplement.pdf":
                denied = self.headers.get("Sec-Fetch-Mode") == "cors"
                content, status, kind = (
                    (b"<h1>Local JS method gate</h1>", 403, "text/html")
                    if denied
                    else (body, 200, "application/pdf")
                )
                requests.append(
                    {
                        "status": status,
                        "fetch_mode": self.headers.get("Sec-Fetch-Mode"),
                        "fetch_dest": self.headers.get("Sec-Fetch-Dest"),
                    }
                )
            else:
                content, status, kind = b"", 404, "text/plain"
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            if kind == "application/pdf":
                self.send_header(
                    "Content-Disposition", 'inline; filename="supplement.pdf"'
                )
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    parent, attachment = origin + "/article", origin + "/supplement.pdf"

    def local_only(url):
        parsed = urlsplit(url)
        if (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == server.server_port
            and parsed.path in {"/article", "/supplement.pdf"}
        ):
            return url
        raise ValueError(
            "Synthetic native-save fixture refuses every other network URL"
        )

    # Transport-only fixture: publisher identity/discovery gates are tested
    # separately. Override safety only for this exact private test endpoint;
    # production guards and all other URLs remain rejected.
    monkeypatch.setattr(browser_module, "validate_browser_network_url", local_only)
    monkeypatch.setattr(module, "validate_browser_network_url", local_only)
    monkeypatch.setattr(
        module.SupplementBrowserTransport, "_inline_pdf_response", lambda *a, **kw: None
    )
    config = BrowserAccessConfig(
        profile_root=tmp_path / "isolated-profile",
        profile_name="local-native-save",
        launch_mode="managed",
        executable_path=os.environ.get("AN_TEST_BROWSER_EXECUTABLE")
        or fixed_portable_browser(),
        headless=False,
        interactive=False,
        auto_challenge_grace=0,
        navigation_timeout=10,
    )
    try:
        with BrowserSession(config) as session:
            context = session._ensure_started()
            source = context.new_page()
            source.goto(parent)
            unrelated_pdf = context.new_page()
            unrelated_pdf.goto(attachment, wait_until="domcontentloaded", timeout=10000)
            unrelated_pdf.evaluate("window.localOtherPdf='preserved'")
            baseline = set(context.pages)
            adapter = module.SupplementBrowserTransport(
                session, doi="10.1000/local-fixture"
            )
            adapter.pages[parent] = source
            try:
                resource = adapter.file_fetch(
                    attachment,
                    source_page=parent,
                    extension=".pdf",
                    output_dir=tmp_path / "files",
                    max_bytes=1024 * 1024,
                    timeout=20,
                )
            except module.SupplementBrowserError as exc:
                pytest.fail(
                    f"{exc}; local_requests={requests}; diagnostics={adapter.diagnostics}"
                )
            assert resource.local_path.read_bytes() == body
            assert _validate_attachment(resource.local_path, ".pdf")["parseable"]
            assert any(
                d["status"] == "BROWSER_NATIVE_VIEWER_SAVE"
                and d.get("reason") == "PDF_BYTES_RECEIVED"
                for d in adapter.diagnostics
            )
            assert unrelated_pdf.evaluate("window.localOtherPdf") == "preserved"
            assert set(context.pages) == baseline and all(
                not page.is_closed() for page in baseline
            )
            assert any(item["status"] == 403 for item in requests)
            adapter.close()
            print(
                json.dumps(
                    {
                        "fixture": "native_pdf_save_same_url_other_tab",
                        "network": "test-owned loopback only",
                        "bytes": len(body),
                        "owned_native_save": True,
                        "unrelated_pdf_tab_unchanged": True,
                        "requests": requests,
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_real_dom_local_download_selector_never_clicks_cloud_or_ambiguous_save(
    tmp_path,
):
    pytest.importorskip("playwright.sync_api")
    config = BrowserAccessConfig(
        profile_root=tmp_path / "selector-profile",
        profile_name="isolated-selector",
        launch_mode="managed",
        executable_path=os.environ.get("AN_TEST_BROWSER_EXECUTABLE")
        or fixed_portable_browser(),
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
    )
    with BrowserSession(config) as session:
        context = session._ensure_started()
        context.set_offline(True)
        page = context.new_page()
        page.set_content("""<svg><defs><g id="download"></g></defs></svg>
            <viewer-save-to-drive-controls></viewer-save-to-drive-controls>
            <viewer-download-controls></viewer-download-controls>
            <button id="save" title="Save">Ambiguous save</button>""")
        page.evaluate("""() => {
            window.clicks={cloud:0,download:0,ambiguous:0};
            for(const tag of ['viewer-save-to-drive-controls','viewer-download-controls']){
              const host=document.querySelector(tag);const root=host.attachShadow({mode:'open'});
              const cloud=tag.includes('drive');
              root.innerHTML=`<button id='save' title='${cloud?'保存到 Google 云端硬盘':'下载'}'>button</button>`;
              root.querySelector('button').onclick=()=>window.clicks[cloud?'cloud':'download']++;
            }
            document.querySelector('button#save').onclick=()=>window.clicks.ambiguous++;
        }""")
        assert page.evaluate(viewer._PDF_VIEWER_SAVE_EXPRESSION) == {"clicked": True}
        assert page.evaluate("window.clicks") == {
            "cloud": 0,
            "download": 1,
            "ambiguous": 0,
        }
        page.evaluate("document.querySelector('viewer-download-controls').remove()")
        assert page.evaluate(viewer._PDF_VIEWER_SAVE_EXPRESSION) == {"clicked": False}
        assert page.evaluate("window.clicks") == {
            "cloud": 0,
            "download": 1,
            "ambiguous": 0,
        }
        print(
            json.dumps(
                {
                    "fixture": "local_download_vs_cloud_same_save_id",
                    "offline": True,
                    "cloud_clicks": 0,
                    "ambiguous_save_clicks": 0,
                    "local_download_clicks": 1,
                }
            )
        )
