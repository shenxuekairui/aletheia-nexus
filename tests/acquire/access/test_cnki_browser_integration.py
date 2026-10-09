"""Real Chromium against routed fixtures; no requests reach CNKI or a login."""

import os
from io import BytesIO
from types import SimpleNamespace
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


@pytest.fixture(autouse=True)
def forbid_unmocked_api_transport(monkeypatch):
    # BrowserContext.route does not intercept APIRequestContext. A fixture
    # must explicitly replace that transport instead of hitting live CNKI.
    from playwright.sync_api import APIRequestContext

    def reject(*args, **kwargs):
        pytest.fail("Unmocked API request escaped the CNKI browser fixture")

    monkeypatch.setattr(APIRequestContext, "get", reject)


def _pdf_bytes(title=_TITLE, doi=_DOI, text=""):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    buffer = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    lines = (("DOI: " + doi + "\n") if doi else "") + text
    commands = " ".join("(" + line + ") Tj 0 -16 Td" for line in lines.splitlines())
    stream.set_data(f"BT /F1 12 Tf 50 700 Td {commands} ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": title})
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "popup,attachment,use_session,doi_less",
    [
        (False, False, False, False),
        (False, True, False, False),
        (True, True, False, False),
        (True, True, True, False),
        (True, True, True, True),
    ],
)
def test_cnki_delayed_search_and_pdf_delivery(
    tmp_path, popup, attachment, use_session, doi_less, monkeypatch
):
    from playwright.sync_api import sync_playwright

    title = (
        "Accurate scientific document identification without digital identifiers"
        if doi_less
        else _TITLE
    )
    doi = "" if doi_less else _DOI
    body = _pdf_bytes(
        title,
        doi,
        (title + "\nAlice Chen\nJournal of Testing 2024\nAbstract") if doi_less else "",
    )
    search = f"""<!doctype html><html><body><div id='controls'></div><main></main>
    <script>
    setTimeout(() => {{
        document.querySelector('#controls').innerHTML =
            '<input id="txt_SearchText"><button class="search-btn">检索</button>';
        document.querySelector('button').onclick = () => setTimeout(() => {{
            document.querySelector('main').innerHTML =
              '<table class="result-table-list"><tbody><tr><td>' +
              '<a class="fz14" target="_blank" href="/detail">{title}</a>' +
              '</td></tr></tbody></table>';
        }}, 250);
    }}, 250);
    </script></body></html>"""
    target = 'target="_blank"' if popup else ""
    detail = f"""<!doctype html><html><head>
    <meta name="citation_title" content="{title}">
    <meta name="citation_author" content="Alice Chen">
    <meta name="citation_journal_title" content="Journal of Testing">
    <meta name="citation_publication_date" content="2024">
    <meta name="citation_doi" content="{doi}"></head><body><h1>{title}</h1>
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
        cnki_context_request=not attachment,
    )
    if use_session:
        from aletheia_nexus.acquire.access import BrowserSession, acquire_cnki_pdf

        with BrowserSession(config) as session:
            context = session._ensure_started()
            context.route("**/*", route_request)
            result = acquire_cnki_pdf(
                doi=doi or None,
                title=title,
                output_dir=tmp_path,
                browser_session=session,
            )
            assert session.active
            assert not session._pdf_responses and not session._downloads
        assert result.status == BrowserAttemptStatus.VERIFIED, result
        assert result.result.file_path.read_bytes() == body
        assert result.source_candidate.doi == doi
        if doi_less:
            assert result.source_candidate.article_id.startswith("bibliographic:")
        return

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        context.route("**/*", route_request)
        if not attachment:
            # context.route cannot intercept APIRequestContext. Isolate this
            # transport too; no fixture request may reach the real CNKI host.
            def get_pdf(url, **kwargs):
                assert url == "https://kns.cnki.net/article.pdf"
                return SimpleNamespace(
                    url=url,
                    status=200,
                    headers={"content-type": "application/pdf"},
                    body=lambda: body,
                    dispose=lambda: None,
                )

            monkeypatch.setattr(context.request, "get", get_pdf)
        page = context.new_page()
        page.set_default_timeout(5000)
        result = CNKIProvider().fetch(
            doi=doi,
            expected_title=title,
            context=context,
            page=page,
            output_dir=tmp_path,
            config=config,
        )
        browser.close()

    assert result.status == BrowserAttemptStatus.VERIFIED, (
        result.error,
        result.evidence,
        [(f.result.status, f.result.error) for f in result.file_attempts if f.result],
    )
    assert result.source_candidate.doi == _DOI
    if not attachment:
        assert result.file_attempts[0].method == "cnki_pdf_control_request"
    assert result.result.file_path.read_bytes() == body
    assert result.result.sidecar_path.exists()


@pytest.mark.parametrize(
    "bilingual,pdf_matches", [(False, True), (True, True), (True, False)]
)
def test_cnki_title_menu_quoted_formula_and_bilingual_identity(
    tmp_path, bilingual, pdf_matches
):
    import json

    from playwright.sync_api import sync_playwright

    title = (
        "In situ Electrochemical Characterization Techniques for Active Hydrogen in Electrocatalytic Nitrate Reduction to Ammonia"
        if bilingual
        else "Mo-Cu共掺RuO2电催化剂的制备及酸性析氧性能研究"
    )
    displayed = (
        "电催化硝酸盐还原合成氨过程中活性氢的原位电化学表征技术（英文）"
        if bilingual
        else title
    )
    body = BytesIO(
        _pdf_bytes(
            title if pdf_matches else "An unrelated scientific article",
            _DOI if pdf_matches else "10.1000/wrong",
        )
    )
    search = f"""<html><body>
      <div class='sort'><div class='sort-default' onclick="document.querySelector('.sort-list').style.display='block'">主题</div>
      <input id='selectfield' type='hidden' value='SU'>
      <div class='sort-list' style='display:none'><li data-val='TI'><a onclick="document.querySelector('#selectfield').value='TI';this.parentElement.parentElement.style.display='none'">篇名</a></li></div></div>
      <input id='txt_SearchText' maxlength='100'><button class='search-btn'>检索</button><main></main>
      <script>document.querySelector('button').onclick = () => {{
        const q = document.querySelector('#txt_SearchText').value;
        const good = ({str(bilingual).lower()} || document.querySelector('#selectfield').value === 'TI') && q.length <= 100 &&
          ({str(bilingual).lower()} || q === {json.dumps("'" + title + "'", ensure_ascii=False)});
        document.querySelector('main').innerHTML = good ?
          '<table class="result-table-list"><tbody><tr><td><a class="fz14" target="_blank" href="/detail">{displayed}</a></td></tr></tbody></table>' : '<div class="no-result">无结果</div>';
      }};</script></body></html>"""
    detail = f"""<html><body><h1>{displayed}</h1><a id='pdfDown' href='/article.pdf'>PDF下载</a></body></html>"""

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
            route.fulfill(
                status=200,
                content_type="application/pdf",
                body=body.getvalue(),
                headers={"Content-Disposition": "attachment; filename=article.pdf"},
            )
        else:
            route.fulfill(status=404)

    config = BrowserAccessConfig(
        headless=True,
        interactive=False,
        navigation_timeout=5,
        keep_unverified=True,
        cnki_context_request=False,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        context.route("**/*", route_request)
        result = CNKIProvider().fetch(
            doi=_DOI,
            expected_title=title,
            page=context.new_page(),
            context=context,
            output_dir=tmp_path,
            config=config,
        )
        browser.close()
    expected = (
        BrowserAttemptStatus.VERIFIED
        if pdf_matches
        else BrowserAttemptStatus.RETRIEVED_UNVERIFIED
    )
    assert result.status == expected, result
    if not bilingual:
        assert "CNKI search field: article title (TI)" in result.evidence


def test_cnki_manual_popup_close_resumes_real_browser_without_second_pdf_click(
    tmp_path,
):
    """A routed fixture simulates human completion; never authenticate on CNKI."""
    from playwright.sync_api import sync_playwright

    search = f"""<html><body><input id='txt_search'>
    <button class='search-btn'>检索</button><main></main>
    <script>document.querySelector('button').onclick = () => {{
        document.querySelector('main').innerHTML =
        `<table class="result-table-list"><tbody><tr><td><a class="fz14"
        target="_blank" href="/detail">{_TITLE}</a></td></tr></tbody></table>`;
    }};</script></body></html>"""
    detail = f"""<html><head><meta name='citation_doi' content='{_DOI}'></head><body>
    <h1>{_TITLE}</h1><a id='pdfDown' href='/verify/home?captchaType=fixture'
    target='_blank' rel='opener'>PDF下载</a></body></html>"""
    pdf_clicks = []
    notices = []

    def route_request(route):
        path = urlsplit(route.request.url).path
        if path == "/kns8s/":
            route.fulfill(content_type="text/html; charset=utf-8", body=search)
        elif path == "/detail":
            route.fulfill(content_type="text/html; charset=utf-8", body=detail)
        elif path == "/verify/home":
            pdf_clicks.append(True)
            route.fulfill(
                content_type="text/html",
                body="<html><body>Fixture verification</body></html>",
            )
        elif path == "/article.pdf":
            route.fulfill(content_type="application/pdf", body=_pdf_bytes())
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        context.route("**/*", route_request)

        def simulate_human_completion(report, url):
            notices.append(report.kind)
            popup = next(p for p in context.pages if "/verify/" in p.url)
            # This code runs only on the intercepted fixture, not a live gate.
            popup.evaluate(
                "() => setTimeout(() => { "
                "window.opener.fetch('/article.pdf'); window.close(); }, 50)"
            )

        # Interactive gates are permitted here only for the fake fixture. The
        # real browser is headless so the test can run in CI without a desktop.
        config = BrowserAccessConfig(
            interactive=True,
            poll_interval=0.05,
            navigation_timeout=5,
            interaction_callback=simulate_human_completion,
        )
        result = CNKIProvider().fetch(
            doi=_DOI,
            expected_title=_TITLE,
            context=context,
            page=context.new_page(),
            output_dir=tmp_path,
            config=config,
        )
        browser.close()
    assert result.status == BrowserAttemptStatus.VERIFIED, result
    assert result.interaction_used and result.download_started
    assert len(notices) == 1 and len(pdf_clicks) == 1


def test_cnki_order_link_uses_browser_javascript_before_download(tmp_path):
    """The explicit native strategy preserves the order link's page JS."""
    from playwright.sync_api import sync_playwright

    search = f"""<html><body><input id='txt_SearchText'><button class='search-btn'
    onclick="document.querySelector('main').innerHTML = document.querySelector('template').innerHTML">检索</button>
    <main></main><template><table class='result-table-list'><tbody><tr><td>
    <a class='fz14' target='_blank' href='/detail'>{_TITLE}</a>
    </td></tr></tbody></table></template></body></html>"""
    detail = f"""<html><head><meta name='citation_doi' content='{_DOI}'></head><body>
    <h1>{_TITLE}</h1><a id='pdfDown' href='https://bar.cnki.net/bar/download/order?id=fixture'
    onclick="document.cookie='fixture_initialized=yes;path=/'">PDF下载</a></body></html>"""
    requests = []

    def route_request(route):
        path = urlsplit(route.request.url).path
        if path == "/kns8s/":
            route.fulfill(content_type="text/html; charset=utf-8", body=search)
        elif path == "/detail":
            route.fulfill(content_type="text/html; charset=utf-8", body=detail)
        elif path == "/bar/download/order":
            requests.append(route.request.url)
            route.fulfill(
                content_type="application/pdf",
                body=_pdf_bytes(),
                headers={"Content-Disposition": "attachment; filename=article.pdf"},
            )
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        context.route("**/*", route_request)
        result = CNKIProvider().fetch(
            doi=_DOI,
            expected_title=_TITLE,
            context=context,
            page=context.new_page(),
            output_dir=tmp_path,
            config=BrowserAccessConfig(
                headless=True,
                interactive=False,
                navigation_timeout=5,
                poll_interval=0.05,
                cnki_context_request=False,
            ),
        )
        assert any(
            cookie["name"] == "fixture_initialized" for cookie in context.cookies()
        )
        browser.close()
    assert result.status == BrowserAttemptStatus.VERIFIED, result
    assert len(requests) == 1 and not result.interaction_used


def test_request_gate_auto_ip_transition_is_not_manual_login(monkeypatch):
    """Only routed fixture pages and fake API responses; no CNKI access."""
    from playwright.sync_api import sync_playwright

    from aletheia_nexus.acquire.access import cnki_provider
    from aletheia_nexus.acquire.access.cnki_runtime import CNKIGate

    responses = [
        SimpleNamespace(
            url="https://login.cnki.net/login/",
            status=200,
            headers={"content-type": "text/html"},
            body=lambda: b"<html><title>Login</title></html>",
            dispose=lambda: None,
        ),
        SimpleNamespace(
            url="https://kns.cnki.net/article.pdf",
            status=200,
            headers={"content-type": "application/pdf"},
            body=_pdf_bytes,
            dispose=lambda: None,
        ),
    ]
    requested = []

    def request(*args, **kwargs):
        requested.append(kwargs["url"])
        return responses.pop(0), ()

    monkeypatch.setattr(cnki_provider, "_safe_context_get", request)

    def route_request(route):
        if urlsplit(route.request.url).path == "/login/":
            route.fulfill(
                content_type="text/html; charset=utf-8",
                body="""<html>
                <title>中国知网-登录</title><body><h1>自动登录</h1><script>
                setTimeout(() => location.href='https://kns.cnki.net/detail', 150);
                </script></body></html>""",
            )
        else:
            route.fulfill(
                content_type="text/html",
                body="<html><body><a id='pdfDown'>PDF</a></body></html>",
            )

    config = BrowserAccessConfig(
        wait_for_interaction=True,
        navigation_timeout=5,
        poll_interval=0.05,
        interaction_callback=lambda *a: pytest.fail("No manual login required"),
    )
    gate = CNKIGate(config)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.route("**/*", route_request)
        page = context.new_page()
        page.goto("https://kns.cnki.net/detail")
        pdf, _ = cnki_provider._recover_pdf_request(
            context,
            page,
            url="https://kns.cnki.net/article.pdf",
            detail_url=page.url,
            gate=gate,
            config=config,
        )
        browser.close()
    assert pdf.body == _pdf_bytes()
    assert len(requested) == 2 and not gate.interaction_used
