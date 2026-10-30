"""Opt-in isolated Chromium: every article/DOI/PDF response is local fixture data."""

import io
import json
import os
from dataclasses import replace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser
from aletheia_nexus.workbench.supplements import _validate_attachment
from aletheia_nexus.workbench.supplements_browser import (
    SupplementBrowserError,
    SupplementBrowserTransport,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="SI owned article smoke uses fresh profiles and locally fulfilled responses",
)

DOI = "10.1021/ja0659323"
PAGE = "https://pubs.acs.org/jacsat/article/128/51/16414/3525402/Local"
OTHER = "https://pubs.acs.org/user-tab"
FILE = "https://pubs.acs.org/jacsat/article-supplement/3525402/pdf/ja0659323_si_001/"
PDF_SOURCE = "https://pubs.acs.org/doi/pdf/" + DOI
RESOLVER = "https://doi.org/" + DOI
HTML = f'<title>Local parent</title><h1>Local parent</h1><meta name="citation_doi" content="{DOI}"><a href="{FILE}">suppl-mat1</a>'


def config(tmp_path, *, grace=0):
    return BrowserAccessConfig(
        profile_root=tmp_path / "isolated-owned-article-profile",
        profile_name="local-si-article-only",
        executable_path=os.environ.get("AN_TEST_BROWSER_EXECUTABLE")
        or fixed_portable_browser(),
        launch_mode="managed",
        headless=True,
        interactive=False,
        navigation_timeout=10,
        auto_challenge_grace=grace,
        poll_interval=0.025,
        interaction_callback=lambda *a: pytest.fail("SI must not enter main wait"),
        interaction_poll_callback=lambda *a: pytest.fail("SI must not emit main poll"),
    )


@pytest.mark.parametrize(
    "source", [PAGE, PDF_SOURCE], ids=["closed-main-page", "pdf-source-via-doi"]
)
def test_owned_article_survives_until_real_pdf_fetch_and_preserves_user_tab(
    tmp_path, source
):
    pytest.importorskip("playwright.sync_api")
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=123, height=100)
    writer.write(buffer)
    body = buffer.getvalue()
    requests, unexpected = [], []
    with BrowserSession(config(tmp_path)) as session:
        context = session._ensure_started()
        # Browser routing may not intercept the remaining hops of a fulfilled
        # HTTP redirect. Offline mode is the outer guarantee against any real
        # publisher request; this fixture uses a routed new document navigation.
        context.set_offline(True)

        def fixture(route):
            url = route.request.url
            requests.append(url)
            if url == RESOLVER:
                route.fulfill(
                    content_type="text/html",
                    body=f"<script>location.replace('{PAGE}')</script>",
                )
            elif url == PAGE:
                route.fulfill(content_type="text/html", body=HTML)
            elif url == FILE:
                route.fulfill(content_type="application/pdf", body=body)
            elif url == OTHER:
                route.fulfill(
                    content_type="text/html",
                    body="<title>User-owned local fixture</title><h1>Preserve this tab</h1>",
                )
            else:
                unexpected.append(url)
                route.abort()

        context.route("**/*", fixture)
        old_main = context.new_page()
        old_main.goto(PAGE)
        old_main.close()  # Match the established successful-main cleanup.
        user = context.new_page()
        user.goto(OTHER)
        user.evaluate("window.fixtureMarker='original'")
        baseline = set(context.pages)
        adapter = SupplementBrowserTransport(session, doi=DOI)
        page = adapter.page_fetch(source, timeout=10)
        assert page.transport == "browser_owned_article_DOM" and page.final_url == PAGE
        owned = adapter.pages[PAGE]
        assert owned not in baseline and not owned.is_closed()
        resource = adapter.file_fetch(
            FILE,
            source_page=page.final_url,
            extension=".pdf",
            output_dir=tmp_path / "files",
            max_bytes=1024 * 1024,
            timeout=10,
        )
        assert resource.local_path.read_bytes() == body
        assert _validate_attachment(resource.local_path, ".pdf")["parseable"]
        adapter.close()
        assert owned.is_closed() and all(not p.is_closed() for p in baseline)
        assert user.url == OTHER and user.evaluate("window.fixtureMarker") == "original"
        assert FILE in requests and PDF_SOURCE not in requests
        assert (RESOLVER in requests) == (source == PDF_SOURCE)
        assert not unexpected


def test_owned_article_gate_is_retained_for_manual_si_retry_without_main_wait(tmp_path):
    pytest.importorskip("playwright.sync_api")
    requests = []
    with BrowserSession(config(tmp_path)) as session:
        context = session._ensure_started()
        context.set_offline(True)

        def fixture(route):
            requests.append(route.request.url)
            route.fulfill(
                status=403,
                content_type="text/html",
                body="<title>Local verification fixture</title><main>Please verify you are human. CAPTCHA security check.</main>",
            )

        context.route("**/*", fixture)
        baseline = set(context.pages)
        adapter = SupplementBrowserTransport(session, doi=DOI)
        with pytest.raises(
            SupplementBrowserError, match="attachment_interaction_required"
        ):
            adapter.page_fetch(PAGE, timeout=10)
        adapter.close()
        gate = adapter.diagnostics[-1]
        assert gate["stage"] == "si_article_page" and gate["page_retained"]
        assert gate["challenge"] in {"CAPTCHA", "BOT_CHALLENGE"}
        assert requests == [PAGE]
        assert len(context.pages) == len(baseline) + 1
        assert all(not page.is_closed() for page in baseline)
        assert any(page.url == PAGE for page in context.pages)


def test_local_temporary_gate_uses_core_stable_clearance_before_accepting_article(
    tmp_path,
):
    pytest.importorskip("playwright.sync_api")
    requests = []
    with BrowserSession(config(tmp_path, grace=3)) as session:
        context = session._ensure_started()
        context.set_offline(True)

        def fixture(route):
            requests.append(route.request.url)
            # Ordinary local HTML simulates completion; no real challenge widget
            # is loaded or operated by this fixture.
            route.fulfill(
                content_type="text/html",
                body=f"""<title>Local verification fixture</title><main>Please verify you are human. CAPTCHA security check.</main>
                <script>setTimeout(() => {{document.title='Local parent';
                document.body.innerHTML='<h1>Local parent ready</h1>';
                const meta=document.createElement('meta');meta.name='citation_doi';
                meta.content='{DOI}';document.head.appendChild(meta);}}, 300);</script>""",
            )

        context.route("**/*", fixture)
        adapter = SupplementBrowserTransport(session, doi=DOI)
        result = adapter.page_fetch(PAGE, timeout=10)
        assert DOI in result.text and result.transport == "browser_owned_article_DOM"
        gate = next(
            d for d in adapter.diagnostics if d["status"] == "BROWSER_ARTICLE_PAGE"
        )
        assert (
            gate["challenge"] == "NONE" and gate["identity"] == "UNIQUE_DOI_CONFIRMED"
        )
        owned = adapter.pages[PAGE]
        adapter.close()
        assert owned.is_closed() and requests == [PAGE]


def test_real_local_official_refresh_wrapper_follows_article_without_metadata(tmp_path):
    pytest.importorskip("playwright.sync_api")
    doi = "10.1016/j.elecom.2022.107204"
    wrapper = "https://linkinghub.elsevier.com/retrieve/pii/S1388248122000066"
    article = (
        "https://www.sciencedirect.com/science/article/pii/S1388248122000066?via%3Dihub"
    )
    refresh = '<meta http-equiv="refresh" content="2; url=\'/retrieve/articleSelectSinglePerm?Redirect=https%3A%2F%2Fwww.sciencedirect.com%2Fscience%2Farticle%2Fpii%2FS1388248122000066%3Fvia%253Dihub&amp;key=local-fixture-only\'">'
    requests, unexpected = [], []
    with BrowserSession(config(tmp_path)) as session:
        context = session._ensure_started()
        context.set_offline(True)

        def fixture(route):
            url = route.request.url
            requests.append(url)
            if url == wrapper:
                route.fulfill(content_type="text/html", body=refresh)
            elif url == article:
                route.fulfill(
                    content_type="text/html",
                    body=f'<title>Local Elsevier article</title><h1>Local article ready</h1><meta name="citation_doi" content="{doi}">',
                )
            else:
                unexpected.append(url)
                route.abort()

        context.route("**/*", fixture)
        adapter = SupplementBrowserTransport(session, doi=doi)
        result = adapter.page_fetch(wrapper, timeout=10)
        assert result.final_url == article and requests == [wrapper, article]
        assert any(d.get("method") == "REDIRECT_TARGET" for d in adapter.diagnostics)
        adapter.close()
        assert not unexpected


def test_real_local_inline_pdf_after_article_fetch_denial_is_delivered_from_owned_browser(
    tmp_path,
):
    pytest.importorskip("playwright.sync_api")
    doi = "10.1002/cctc.202201687"
    parent = "https://chemistry-europe.onlinelibrary.wiley.com/doi/" + doi
    attachment = "https://chemistry-europe.onlinelibrary.wiley.com/action/downloadSupplement?doi=10.1002%2Fcctc.202201687&file=local-fixture.pdf"
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=123, height=100)
    writer.write(buffer)
    body = buffer.getvalue()
    requests, unexpected = [], []
    # Headful isolated Chromium exercises an inline PDF webview rather than a
    # headless browser's possible forced-download policy. No user profile is used.
    with BrowserSession(replace(config(tmp_path), headless=False)) as session:
        context = session._ensure_started()
        context.set_offline(True)

        def fixture(route):
            request = route.request
            if not request.url.startswith(("http://", "https://")):
                route.continue_()
                return
            if request.url == parent:
                route.fulfill(
                    content_type="text/html",
                    body=f'<title>Local parent</title><h1>Local parent</h1><meta name="citation_doi" content="{doi}">',
                )
            elif request.url == attachment:
                denied = (
                    request.resource_type == "fetch" and request.frame.url == parent
                )
                requests.append((request.resource_type, 403 if denied else 200))
                if denied:
                    route.fulfill(
                        status=403,
                        content_type="text/html",
                        body="<h1>Local request-method gate</h1>",
                    )
                else:
                    route.fulfill(
                        content_type="application/pdf",
                        headers={
                            "content-length": str(len(body)),
                            "content-disposition": 'inline; filename="local-fixture.pdf"',
                        },
                        body=body,
                    )
            else:
                unexpected.append(request.url)
                route.abort()

        context.route("**/*", fixture)
        source = context.new_page()
        source.goto(parent)
        source.evaluate("window.localMarker='untouched'")
        baseline = set(context.pages)
        adapter = SupplementBrowserTransport(session, doi=doi)
        adapter.page_fetch(parent)
        try:
            resource = adapter.file_fetch(
                attachment,
                source_page=parent,
                extension=".pdf",
                output_dir=tmp_path / "files",
                max_bytes=1024 * 1024,
                timeout=15,
            )
        except SupplementBrowserError as exc:
            pytest.fail(f"{exc}; diagnostics={adapter.diagnostics}")
        assert resource.local_path.read_bytes() == body
        assert _validate_attachment(resource.local_path, ".pdf")["parseable"]
        assert ("fetch", 403) in requests and ("document", 200) in requests
        assert any(
            d["status"]
            in {"BROWSER_NATIVE_PDF_RESPONSE", "BROWSER_NATIVE_VIEWER_FETCH"}
            and d.get("reason") == "PDF_BYTES_RECEIVED"
            for d in adapter.diagnostics
        )
        assert (
            source.url == parent
            and source.evaluate("window.localMarker") == "untouched"
        )
        assert (
            all(not page.is_closed() for page in baseline)
            and set(context.pages) == baseline
        )
        assert not unexpected
        adapter.close()
        print(
            json.dumps(
                {
                    "fixture": "inline_pdf_after_article_fetch_denial",
                    "offline": True,
                    "bytes": len(body),
                    "request_types_and_status": requests,
                    "main_tab_unchanged": True,
                    "delivery": [
                        {"status": d["status"], "reason": d.get("reason")}
                        for d in adapter.diagnostics
                        if d["status"]
                        in {
                            "BROWSER_NATIVE_PDF_RESPONSE",
                            "BROWSER_NATIVE_VIEWER_FETCH",
                        }
                    ],
                }
            )
        )
