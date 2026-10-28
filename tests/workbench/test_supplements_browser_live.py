"""Opt-in local-response Chromium tests for SI transport, never real auth tabs."""

import io
import json
import os
import zipfile

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser
from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionTooLargeError
from aletheia_nexus.workbench.supplements import _validate_attachment
from aletheia_nexus.workbench.supplements_browser import SupplementBrowserTransport

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="SI browser transport smoke uses isolated headless profiles and locally fulfilled responses",
)


def config(tmp_path):
    return BrowserAccessConfig(
        profile_root=tmp_path / "isolated-browser-profile",
        executable_path=os.environ.get("AN_TEST_BROWSER_EXECUTABLE")
        or fixed_portable_browser(),
        launch_mode="managed",
        headless=True,
        interactive=False,
        navigation_timeout=10,
    )


def test_real_browser_same_origin_bounded_pdf_fetch_keeps_article_tab_unchanged(
    tmp_path,
):
    pytest.importorskip("playwright.sync_api")
    doi = "10.1021/ja0659323"
    page_url = "https://pubs.acs.org/jacsat/article/128/51/16414/3525402/Fixture"
    file_url = (
        "https://pubs.acs.org/jacsat/article-supplement/3525402/pdf/ja0659323_si_001/"
    )
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)
    body = buffer.getvalue()
    requests = []
    with BrowserSession(config(tmp_path)) as session:
        context = session._ensure_started()

        def respond(route):
            requests.append(route.request.url)
            if route.request.url == file_url:
                route.fulfill(content_type="application/pdf", body=body)
            else:
                route.fulfill(
                    content_type="text/html",
                    body=f'<title>Local ACS-style fixture</title><meta name="citation_doi" content="{doi}"><h1>Fixture</h1>',
                )

        context.route("https://pubs.acs.org/**", respond)
        source = context.new_page()
        source.goto(page_url)
        source.evaluate("window.ownedFixture = 'preserved'")
        adapter = SupplementBrowserTransport(session, doi=doi)
        adapter.page_fetch(page_url)
        resource = adapter.file_fetch(
            file_url,
            source_page=page_url,
            extension=".pdf",
            output_dir=tmp_path / "files",
            max_bytes=1024 * 1024,
            timeout=10,
        )
        assert resource.local_path.read_bytes() == body
        assert _validate_attachment(resource.local_path, ".pdf")["parseable"]
        assert (
            source.url == page_url
            and source.evaluate("window.ownedFixture") == "preserved"
        )
        assert requests.count(file_url) == 1
        print(
            json.dumps(
                {
                    "transport": "browser_same_origin_bounded_pdf",
                    "bytes": len(body),
                    "main_tab_unchanged": True,
                    "external_http": False,
                }
            )
        )


@pytest.mark.parametrize(
    "exceeds_limit", [False, True], ids=["docx-delivery", "docx-byte-cap"]
)
def test_real_browser_native_nonpdf_download_is_correlated_and_bounded(
    tmp_path, exceeds_limit
):
    pytest.importorskip("playwright.sync_api")
    doi = "10.1016/j.elecom.2022.107204"
    page_url = "https://www.sciencedirect.com/science/article/pii/S1388248122000066"
    file_url = (
        "https://ars.els-cdn.com/content/image/1-s2.0-S1388248122000066-mmc1.docx"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml", "<document>Fixture supplementary data</document>"
        )
    body = buffer.getvalue()
    with BrowserSession(config(tmp_path)) as session:
        context = session._ensure_started()
        context.route(
            "https://www.sciencedirect.com/**",
            lambda route: route.fulfill(
                content_type="text/html",
                body=f'<title>Local Elsevier-style fixture</title><meta name="citation_doi" content="{doi}"><h2>Supplementary data</h2>',
            ),
        )
        context.route(
            "https://ars.els-cdn.com/**",
            lambda route: route.fulfill(
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": "attachment; filename=supplement.docx"},
                body=body,
            ),
        )
        source = context.new_page()
        source.goto(page_url)
        adapter = SupplementBrowserTransport(session, doi=doi)
        adapter.page_fetch(page_url)
        arguments = dict(
            source_page=page_url,
            extension=".docx",
            output_dir=tmp_path / "files",
            max_bytes=1 if exceeds_limit else 1024 * 1024,
            timeout=10,
        )
        if exceeds_limit:
            with pytest.raises(AcquisitionTooLargeError):
                adapter.file_fetch(file_url, **arguments)
        else:
            resource = adapter.file_fetch(file_url, **arguments)
            assert resource.local_path.read_bytes() == body
            assert _validate_attachment(resource.local_path, ".docx")["type"] == "docx"
        assert source.url == page_url and not source.is_closed()
        print(
            json.dumps(
                {
                    "transport": "browser_native_docx",
                    "exceeds_limit": exceeds_limit,
                    "bytes": len(body),
                    "main_tab_unchanged": True,
                    "external_http": False,
                }
            )
        )
