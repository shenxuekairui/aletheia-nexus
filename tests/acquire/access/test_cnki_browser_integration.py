"""Real Chromium against routed fixtures; no requests reach CNKI or a login."""

import os
from io import BytesIO
from urllib.parse import urlsplit

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access.cnki_provider import CNKIProvider
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="real Chromium smoke is enabled only in the browser-extra CI job",
)

_TITLE = "银修饰铜纳米阵列用于电催化还原CO2"
_DOI = "10.1000/cnki-browser-fixture"


def _pdf_bytes():
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": _TITLE})
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "popup,attachment,use_session",
    [
        (False, False, False),
        (False, True, False),
        (True, True, False),
        (True, True, True),
    ],
)
def test_cnki_delayed_search_and_pdf_delivery(tmp_path, popup, attachment, use_session):
    from playwright.sync_api import sync_playwright

    body = _pdf_bytes()
    search = f"""<!doctype html><html><body><div id='controls'></div><main></main>
    <script>
    setTimeout(() => {{
        document.querySelector('#controls').innerHTML =
            '<input id="txt_SearchText"><button class="search-btn">检索</button>';
        document.querySelector('button').onclick = () => setTimeout(() => {{
            document.querySelector('main').innerHTML =
              '<table class="result-table-list"><tbody><tr><td>' +
              '<a class="fz14" target="_blank" href="/detail">{_TITLE}</a>' +
              '</td></tr></tbody></table>';
        }}, 250);
    }}, 250);
    </script></body></html>"""
    target = 'target="_blank"' if popup else ""
    detail = f"""<!doctype html><html><head>
    <meta name="citation_title" content="{_TITLE}">
    <meta name="citation_doi" content="{_DOI}"></head><body><h1>{_TITLE}</h1>
    <a id="pdfDown" href="/article.pdf" {target}>PDF下载</a></body></html>"""

    def route_request(route):
        path = urlsplit(route.request.url).path
        if path == "/kns8s/":
            route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=search
            )
        elif path == "/detail":
            route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=detail
            )
        elif path == "/article.pdf":
            headers = {"Content-Length": str(len(body))}
            if attachment:
                headers["Content-Disposition"] = 'attachment; filename="article.pdf"'
            route.fulfill(
                status=200, content_type="application/pdf", headers=headers, body=body
            )
        else:
            route.fulfill(status=404, body="Fixture route not found")

    config = BrowserAccessConfig(
        headless=True,
        interactive=False,
        navigation_timeout=5,
        poll_interval=0.05,
        profile_root=tmp_path / "profiles",
    )
    if use_session:
        from aletheia_nexus.acquire.access import BrowserSession, acquire_cnki_pdf

        with BrowserSession(config) as session:
            context = session._ensure_started()
            context.route("**/*", route_request)
            result = acquire_cnki_pdf(
                title=_TITLE, output_dir=tmp_path, browser_session=session
            )
            assert session.active
            assert not session._pdf_responses and not session._downloads
        assert result.status == BrowserAttemptStatus.VERIFIED, result
        assert result.result.file_path.read_bytes() == body
        return

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        context.route("**/*", route_request)
        page = context.new_page()
        page.set_default_timeout(5000)
        result = CNKIProvider().fetch(
            doi="",
            expected_title=_TITLE,
            context=context,
            page=page,
            output_dir=tmp_path,
            config=config,
        )
        browser.close()

    assert result.status == BrowserAttemptStatus.VERIFIED, result
    assert result.source_candidate.doi == _DOI
    assert result.result.file_path.read_bytes() == body
    assert result.result.sidecar_path.exists()
