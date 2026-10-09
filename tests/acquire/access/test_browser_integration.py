import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserSession,
    browser,
    browser_route,
)
from aletheia_nexus.acquire.access.browser_engine import viewer
from aletheia_nexus.acquire.access.models import (
    BrowserAttemptStatus,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.access.publisher_adapters import adapter_for_url
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="real Chromium smoke is enabled only in the browser-extra CI job",
)


@pytest.fixture
def control_browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.mark.parametrize("kind", ["pdf", "institution"])
def test_hidden_duplicate_controls_do_not_delay_visible_entry(control_browser, kind):
    page = control_browser.new_page()
    label = "Download PDF" if kind == "pdf" else "Access through your institution"
    click = (
        browser_route._click_semantic_pdf_control
        if kind == "pdf"
        else browser_route._click_semantic_institution_control
    )
    try:
        page.set_content(
            f'<button style="display:none">{label}</button>' * 100
            + f'<button onclick="window.selected=true">{label}</button>'
        )
        started = time.monotonic()
        assert click(page)
        assert page.evaluate("window.selected") is True
        assert time.monotonic() - started < 5
    finally:
        page.close()


@pytest.mark.parametrize("kind", ["pdf", "institution"])
def test_removed_controls_do_not_wait_for_stale_count(
    control_browser, monkeypatch, kind
):
    page = control_browser.new_page()
    label = "Download PDF" if kind == "pdf" else "Access through your institution"
    try:
        page.set_content(f"<button>{label}</button>" * 25)
        locator = page.locator("button")

        class DisappearingControls:
            def count(self):
                count = locator.count()
                page.evaluate(
                    "document.querySelectorAll('button').forEach(el=>el.remove())"
                )
                return count

            def nth(self, index):
                return locator.nth(index)

        monkeypatch.setattr(
            browser_route, "_semantic_controls", lambda *args: DisappearingControls()
        )
        click = (
            browser_route._click_semantic_pdf_control
            if kind == "pdf"
            else browser_route._click_semantic_institution_control
        )
        started = time.monotonic()
        assert click(page) is False
        assert time.monotonic() - started < 5
    finally:
        page.close()


@pytest.mark.parametrize(
    "control",
    [
        '<a href="/doi/pdf/10.1126/test">Download PDF</a>',
        '<a href="/doi/pdf/10.1021/test">View PDF</a>',
        '<a href="/doi/epdf/10.1002/test">PDF</a>',
        '<a href="/doi/pdfdirect/10.1002/test">PDF</a>',
        '<a href="/en/content/articlepdf/2026/test">PDF</a>',
        '<a href="/science/article/pii/test/pdfft">Download PDF</a>',
        '<a href="/stamp/stamp.jsp?tp=&arnumber=123" aria-label="View PDF"></a>',
        '<a href="/articles/test.pdf">Download PDF</a>',
        '<a href="/test/pdf">PDF</a>',
        '<a href="/products/ejournals/pdf/test.pdf">PDF</a>',
        '<button onclick="window.clicked=true">Download PDF</button>',
        '<button aria-label="Download PDF"></button>',
        '<button title="View PDF"></button>',
        '<div role="button">View PDF</div>',
    ],
    ids=[
        "science",
        "acs",
        "wiley-epdf",
        "wiley-pdfdirect",
        "rsc",
        "elsevier",
        "ieee",
        "nature",
        "mdpi",
        "thieme",
        "javascript",
        "aria",
        "title",
        "role",
    ],
)
def test_real_browser_finds_late_pdf_controls(control_browser, control):
    page = control_browser.new_page()
    try:
        citations = '<a href="#reference">Reference</a>' * 608
        page.set_content(
            "<style>a {display:inline-block; min-width:20px; min-height:20px}</style>"
            + citations
            + '<dialog open><a href="/doi/pdf/other">View PDF</a></dialog>'
            + '<a href="/doi/pdf/supplement">Supporting information PDF</a>'
            + '<a href="/doi/suppl/10.1126/test/suppl_file/test_sm.pdf">Download PDF</a>'
            + '<a href="/suppinfo/test_si.pdf">Download PDF</a>'
            + '<a href="/cms/asset/test/mmc1.pdf">Download PDF</a>'
            + control
        )
        # Mark only the final article control, suppressing all navigation so the
        # fixture exercises actual DOM ordering, CSS and click handling offline.
        page.locator(browser_route._INTERACTIVE_CONTROL_SELECTOR).last.evaluate(
            "el => el.setAttribute('id', 'article-pdf')"
        )
        page.evaluate("""() => {
            document.querySelector('dialog').close();
            document.addEventListener('click', event => {
                event.preventDefault();
                window.clickedId = event.target.id;
            }, true);
        }""")
        assert browser_route._click_semantic_pdf_control(page) is True
        assert page.evaluate("window.clickedId") == "article-pdf"
    finally:
        page.close()


@pytest.mark.parametrize(
    "control",
    [
        "<button>Access through your institution</button>",
        '<button aria-label="Sign in through your institution"></button>',
        '<a href="/login" title="Access via OpenAthens"></a>',
    ],
    ids=["text", "aria", "title"],
)
def test_real_browser_finds_late_institution_controls(control_browser, control):
    page = control_browser.new_page()
    try:
        page.set_content(
            "<style>a {display:inline-block; min-width:20px; min-height:20px}</style>"
            + '<a href="#reference">Reference</a>' * 608
            + control
        )
        page.locator(browser_route._INTERACTIVE_CONTROL_SELECTOR).last.evaluate(
            "el => el.setAttribute('id', 'institution-access')"
        )
        page.evaluate("""() => document.addEventListener('click', event => {
            event.preventDefault(); window.clickedId = event.target.id;
        }, true)""")
        assert browser_route._click_semantic_institution_control(page) is True
        assert page.evaluate("window.clickedId") == "institution-access"
    finally:
        page.close()


@pytest.mark.parametrize("accessible", [False, True], ids=["text", "aria"])
def test_real_browser_finds_late_ieee_dialog_access(control_browser, accessible):
    from aletheia_nexus.acquire.access.publisher_adapters.ieee import IeeeAdapter

    page = control_browser.new_page()
    try:
        control = (
            '<button aria-label="Access through Test University"></button>'
            if accessible
            else "<button>Access through Test University</button>"
        )
        page.set_content(
            "<dialog open>Full text access may be available"
            + "<button>Unrelated option</button>" * 80
            + control
            + "</dialog>"
        )
        page.locator("button").last.evaluate(
            "el => el.setAttribute('id', 'institution-access')"
        )
        page.evaluate("""() => document.addEventListener('click', event => {
            event.preventDefault(); window.clickedId = event.target.id;
        }, true)""")
        adapter = IeeeAdapter()
        assert adapter.remembered_institution(page, browser_route._control_semantics)
        assert adapter.click_institution_control(page, browser_route._control_semantics)
        assert page.evaluate("window.clickedId") == "institution-access"
    finally:
        page.close()


@pytest.mark.parametrize("accessible", [False, True], ids=["text", "aria"])
def test_real_browser_finds_late_modal_dismiss_control(control_browser, accessible):
    page = control_browser.new_page()
    try:
        close = '<button aria-label="Close window"' if accessible else "<button"
        close += " onclick=\"this.closest('dialog').close()\">"
        close += "</button>" if accessible else "Close</button>"
        page.set_content(
            "<dialog open><button>View PDF</button>"
            + "<button>Unrelated recommendation</button>" * 80
            + close
            + "</dialog>"
        )
        assert browser_route._dismiss_blocking_modal(page) is True
        assert page.locator("dialog").is_visible() is False
    finally:
        page.close()


def _pdf_bytes(title: str = "Authenticated Browser Integration Article") -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


class _Handler(BaseHTTPRequestHandler):
    pdf_body = _pdf_bytes()
    popup_pdf_body = _pdf_bytes("Popup Browser Integration Article")
    institution_pdf_body = _pdf_bytes("Institutional Access Integration Article")
    accessible_institution_pdf_body = _pdf_bytes(
        "Accessible Institutional Access Integration Article"
    )
    accessible_pdf_body = _pdf_bytes("Accessible PDF Control Integration Article")
    persistent_pdf_body = _pdf_bytes("Persistent Browser Integration Article")
    ieee_pdf_body = _pdf_bytes("IEEE Browser Integration Article")
    pdf_cookie_seen = False
    popup_cookie_seen = False
    institution_cookie_seen = False
    accessible_institution_cookie_seen = False
    persistent_cookie_seen = False

    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/ieee-document":
            body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="IEEE Browser Integration Article">
<meta name="citation_doi" content="10.1109/TEST.2026.1234567">
<title>IEEE Browser Integration Article</title>
</head>
<body><button onclick="location.href='/ieee-download'">Download PDF</button></body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/ieee-download":
            body = type(self).ieee_pdf_body
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header(
                "Content-Disposition", 'attachment; filename="ieee-article.pdf"'
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/article":
            body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Authenticated Browser Integration Article">
<meta name="citation_doi" content="10.1000/browser-integration">
<meta name="citation_pdf_url" content="/article.pdf">
<title>Authenticated Browser Integration Article</title>
</head>
<body>Article abstract</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", "an_session=ok; Path=/; SameSite=Lax")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/article.pdf":
            cookie = self.headers.get("Cookie", "")
            type(self).pdf_cookie_seen = "an_session=ok" in cookie
            if not type(self).pdf_cookie_seen:
                body = b"<html><body>Sign in to access</body></html>"
                self.send_response(401)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            body = type(self).pdf_body
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/popup-article":
            body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Popup Browser Integration Article">
<meta name="citation_doi" content="10.1000/browser-popup">
<title>Popup Browser Integration Article</title>
</head>
<body>
<button onclick="window.open('/popup.pdf', '_blank')">View PDF</button>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/popup.pdf":
            type(self).popup_cookie_seen = True
            body = type(self).popup_pdf_body
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/institution-article":
            cookie = self.headers.get("Cookie", "")
            authenticated = "institution_session=ok" in cookie
            if authenticated:
                body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Institutional Access Integration Article">
<meta name="citation_doi" content="10.1000/browser-institution">
<meta name="citation_pdf_url" content="/institution.pdf">
<title>Institutional Access Integration Article</title>
</head>
<body>Authenticated article page</body>
</html>"""
            else:
                body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Institutional Access Integration Article">
<meta name="citation_doi" content="10.1000/browser-institution">
<title>Institutional Access Integration Article</title>
</head>
<body><a href="/institution-login">Access through your institution</a></body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/institution-login":
            self.send_response(302)
            self.send_header("Location", "/institution-article")
            self.send_header(
                "Set-Cookie",
                "institution_session=ok; Path=/; SameSite=Lax",
            )
            self.end_headers()
            return

        if path == "/accessible-institution-article":
            cookie = self.headers.get("Cookie", "")
            authenticated = "accessible_institution_session=ok" in cookie
            if authenticated:
                body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Accessible Institutional Access Integration Article">
<meta name="citation_doi" content="10.1000/browser-accessible-institution">
<meta name="citation_pdf_url" content="/accessible-institution.pdf">
<title>Accessible Institutional Access Integration Article</title>
</head>
<body>Authenticated article page</body>
</html>"""
            else:
                body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Accessible Institutional Access Integration Article">
<meta name="citation_doi" content="10.1000/browser-accessible-institution">
<title>Accessible Institutional Access Integration Article</title>
</head>
<body>
<div role="button" aria-label="Access through your organization"
     style="display:block;width:200px;height:32px"
     onclick="location.href='/accessible-institution-login'"></div>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/accessible-institution-login":
            self.send_response(302)
            self.send_header("Location", "/accessible-institution-article")
            self.send_header(
                "Set-Cookie",
                "accessible_institution_session=ok; Path=/; SameSite=Lax",
            )
            self.end_headers()
            return

        if path == "/accessible-institution.pdf":
            cookie = self.headers.get("Cookie", "")
            type(self).accessible_institution_cookie_seen = (
                "accessible_institution_session=ok" in cookie
            )
            if not type(self).accessible_institution_cookie_seen:
                body = b"<html><body>Sign in to access</body></html>"
                self.send_response(401)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            body = type(self).accessible_institution_pdf_body
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/accessible-pdf-article":
            body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Accessible PDF Control Integration Article">
<meta name="citation_doi" content="10.1000/browser-accessible-pdf">
<title>Accessible PDF Control Integration Article</title>
</head>
<body>
<div role="button" aria-label="View PDF"
     style="display:block;width:120px;height:32px"
     onclick="location.href='/accessible-control.pdf'"></div>
</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/accessible-control.pdf":
            body = type(self).accessible_pdf_body
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/persistent-login":
            body = b"<html><body>Session seeded</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header(
                "Set-Cookie",
                "persistent_session=ok; Max-Age=3600; Path=/; SameSite=Lax",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/persistent-article":
            cookie = self.headers.get("Cookie", "")
            authenticated = "persistent_session=ok" in cookie
            if authenticated:
                body = b"""<!doctype html>
<html>
<head>
<meta name="citation_title" content="Persistent Browser Integration Article">
<meta name="citation_doi" content="10.1000/browser-persistent">
<meta name="citation_pdf_url" content="/persistent.pdf">
<title>Persistent Browser Integration Article</title>
</head>
<body>Persistent authenticated article page</body>
</html>"""
            else:
                body = b"""<!doctype html>
<html>
<head><title>Institutional access</title></head>
<body>Access through your institution</body>
</html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/persistent.pdf":
            cookie = self.headers.get("Cookie", "")
            type(self).persistent_cookie_seen = "persistent_session=ok" in cookie
            if not type(self).persistent_cookie_seen:
                body = b"<html><body>Sign in to access</body></html>"
                self.send_response(401)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            body = type(self).persistent_pdf_body
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/institution.pdf":
            cookie = self.headers.get("Cookie", "")
            type(self).institution_cookie_seen = "institution_session=ok" in cookie
            if not type(self).institution_cookie_seen:
                body = b"<html><body>Sign in to access</body></html>"
                self.send_response(401)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            body = type(self).institution_pdf_body
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()


@pytest.fixture
def local_article_server():
    _Handler.pdf_cookie_seen = False
    _Handler.popup_cookie_seen = False
    _Handler.institution_cookie_seen = False
    _Handler.accessible_institution_cookie_seen = False
    _Handler.persistent_cookie_seen = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_browser_session_shares_cookie_with_authenticated_pdf_request(
    monkeypatch,
    tmp_path,
    local_article_server,
):
    # Production rejects local-network targets. This deterministic integration
    # test intentionally uses localhost, so only the test replaces that policy.
    monkeypatch.setattr(
        browser,
        "validate_browser_network_url",
        lambda url: url,
    )
    monkeypatch.setattr(
        browser_route,
        "validate_browser_network_url",
        lambda url: url,
    )

    candidate = FullTextCandidate(
        doi="10.1000/browser-integration",
        url=f"{local_article_server}/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    config = BrowserAccessConfig(
        profile_name="integration",
        profile_root=tmp_path / "profiles",
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
        interaction_timeout=0,
    )

    with BrowserSession(config) as session:
        result = session.acquire(
            doi=candidate.doi,
            routes=[candidate],
            output_dir=tmp_path / "downloads",
            expected_title="Authenticated Browser Integration Article",
        )

    assert _Handler.pdf_cookie_seen is True
    assert result.verified_result is not None
    assert result.verified_result.status == AcquisitionStatus.VERIFIED
    assert result.verified_result.file_path is not None


def test_real_browser_recovers_pdf_opened_in_new_tab(
    monkeypatch,
    tmp_path,
    local_article_server,
):
    # Production rejects local-network targets. The deterministic integration
    # fixture is intentionally local, so only the test replaces that policy.
    monkeypatch.setattr(browser, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)

    candidate = FullTextCandidate(
        doi="10.1000/browser-popup",
        url=f"{local_article_server}/popup-article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    config = BrowserAccessConfig(
        profile_name="popup-integration",
        profile_root=tmp_path / "profiles",
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
        interaction_timeout=0,
    )

    with BrowserSession(config) as session:
        result = session.acquire(
            doi=candidate.doi,
            routes=[candidate],
            output_dir=tmp_path / "downloads",
            expected_title="Popup Browser Integration Article",
        )

    assert result.verified_result is not None, [
        (
            a.status,
            [
                (f.method, f.error, f.result.status if f.result else None)
                for f in a.file_attempts
            ],
        )
        for a in result.attempts
    ]
    assert result.verified_result.status == AcquisitionStatus.VERIFIED
    assert result.verified_result.file_path is not None


def test_real_browser_clicks_ieee_style_download_control(
    monkeypatch,
    tmp_path,
    local_article_server,
):
    monkeypatch.setattr(browser, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)

    candidate = FullTextCandidate(
        doi="10.1109/test.2026.1234567",
        url=f"{local_article_server}/ieee-document",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    config = BrowserAccessConfig(
        profile_name="ieee-integration",
        profile_root=tmp_path / "profiles",
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
        interaction_timeout=0,
    )

    with BrowserSession(config) as session:
        result = session.acquire(
            doi=candidate.doi,
            routes=[candidate],
            output_dir=tmp_path / "downloads",
            expected_title="IEEE Browser Integration Article",
        )

    assert result.verified_result is not None
    assert result.verified_result.status == AcquisitionStatus.VERIFIED
    assert result.verified_result.file_path is not None


def test_real_browser_recovers_after_institution_access_handoff(
    monkeypatch,
    tmp_path,
    local_article_server,
):
    monkeypatch.setattr(browser, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)

    candidate = FullTextCandidate(
        doi="10.1000/browser-institution",
        url=f"{local_article_server}/institution-article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    config = BrowserAccessConfig(
        profile_name="institution-integration",
        profile_root=tmp_path / "profiles",
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
        interaction_timeout=0,
    )

    with BrowserSession(config) as session:
        result = session.acquire(
            doi=candidate.doi,
            routes=[candidate],
            output_dir=tmp_path / "downloads",
            expected_title="Institutional Access Integration Article",
        )

    assert _Handler.institution_cookie_seen is True
    assert result.verified_result is not None
    assert result.verified_result.status == AcquisitionStatus.VERIFIED
    assert result.attempts[0].interaction_used is False
    assert any(
        "Institutional access handoff completed" in item
        for item in result.attempts[0].evidence
    )


def test_real_browser_clicks_accessibility_named_institution_control(
    monkeypatch,
    tmp_path,
    local_article_server,
):
    monkeypatch.setattr(browser, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)

    candidate = FullTextCandidate(
        doi="10.1000/browser-accessible-institution",
        url=f"{local_article_server}/accessible-institution-article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    config = BrowserAccessConfig(
        profile_name="accessible-institution-integration",
        profile_root=tmp_path / "profiles",
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
        interaction_timeout=0,
    )

    with BrowserSession(config) as session:
        result = session.acquire(
            doi=candidate.doi,
            routes=[candidate],
            output_dir=tmp_path / "downloads",
            expected_title="Accessible Institutional Access Integration Article",
        )

    assert _Handler.accessible_institution_cookie_seen is True
    assert result.verified_result is not None
    assert result.verified_result.status == AcquisitionStatus.VERIFIED


def test_real_browser_clicks_accessibility_named_pdf_control(
    monkeypatch,
    tmp_path,
    local_article_server,
):
    monkeypatch.setattr(browser, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)

    candidate = FullTextCandidate(
        doi="10.1000/browser-accessible-pdf",
        url=f"{local_article_server}/accessible-pdf-article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    config = BrowserAccessConfig(
        profile_name="accessible-pdf-integration",
        profile_root=tmp_path / "profiles",
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
        interaction_timeout=0,
    )

    with BrowserSession(config) as session:
        result = session.acquire(
            doi=candidate.doi,
            routes=[candidate],
            output_dir=tmp_path / "downloads",
            expected_title="Accessible PDF Control Integration Article",
        )

    assert result.verified_result is not None, [
        (
            a.status,
            [
                (f.method, f.error, f.result.status if f.result else None)
                for f in a.file_attempts
            ],
        )
        for a in result.attempts
    ]
    assert result.verified_result.status == AcquisitionStatus.VERIFIED


def test_real_browser_profile_persists_session_across_restarts(
    monkeypatch,
    tmp_path,
    local_article_server,
):
    monkeypatch.setattr(browser, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)

    profile_root = tmp_path / "profiles"
    config = BrowserAccessConfig(
        profile_name="persistent-integration",
        profile_root=profile_root,
        headless=True,
        interactive=False,
        auto_challenge_grace=0,
        interaction_timeout=0,
    )

    seed = FullTextCandidate(
        doi="10.1000/browser-persist-seed",
        url=f"{local_article_server}/persistent-login",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    with BrowserSession(config) as session:
        session.acquire(
            doi=seed.doi,
            routes=[seed],
            output_dir=tmp_path / "seed-downloads",
        )

    article = FullTextCandidate(
        doi="10.1000/browser-persistent",
        url=f"{local_article_server}/persistent-article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    with BrowserSession(config) as session:
        result = session.acquire(
            doi=article.doi,
            routes=[article],
            output_dir=tmp_path / "downloads",
            expected_title="Persistent Browser Integration Article",
        )

    assert _Handler.persistent_cookie_seen is True
    assert result.verified_result is not None
    assert result.verified_result.status == AcquisitionStatus.VERIFIED


@pytest.mark.parametrize(
    "institution", ["Example University", "Another Research Library"]
)
def test_wiley_remembered_entry_activates_and_reuses_session(
    control_browser, tmp_path, institution
):
    context = control_browser.new_context()
    page = context.new_page()
    base = "https://onlinelibrary.wiley.com"
    calls = []
    title = "Remembered Institution Article"
    body = _pdf_bytes(title)

    def serve(route):
        url = route.request.url
        calls.append(url)
        if "/pdfdirect/" in url:
            route.fulfill(content_type="application/pdf", body=body)
        else:
            doi = url.split("/doi/epdf/")[-1]
            route.fulfill(
                content_type="text/html",
                body=f"""<title>{title}</title>
            <meta name="citation_doi" content="{doi}">
            <meta name="citation_title" content="{title}">
            <script>function activate() {{localStorage.setItem('fixture_access','yes');
              document.body.innerHTML='<iframe src="/doi/pdfdirect/{doi}"></iframe>';}}
            </script><body>Institutional Login. You do not have access to this PDF.
            <span onclick="localStorage.setItem('fixture_clicks', Number(localStorage.getItem('fixture_clicks') || 0)+1); activate()">Access through {institution}</span>
            <script>if(localStorage.getItem('fixture_access')) activate();</script></body>""",
            )

    context.route("**/*", serve)
    try:
        for suffix in ("first", "second"):
            doi = f"10.1002/{suffix}"
            outcome = browser_route.attempt_browser_route(
                context,
                page,
                source=FullTextCandidate(
                    doi=doi,
                    url=f"{base}/doi/epdf/{doi}",
                    provenance=(),
                    url_type=CandidateUrlType.PDF,
                ),
                output_dir=tmp_path,
                expected_title=title,
                config=BrowserAccessConfig(
                    interactive=False, auto_challenge_grace=0, request_timeout=2
                ),
                session_blocked_urls=[],
                session_pdf_responses=[],
                session_downloads=[],
            )
            assert outcome.status == BrowserAttemptStatus.VERIFIED
            assert any(
                f.method
                in {
                    "embedded_browser_fetch",
                    "browser_response",
                    "browser_download",
                    "cdp_browser_download",
                }
                and f.result is not None
                and f.result.status == AcquisitionStatus.VERIFIED
                for f in outcome.file_attempts
            )
        assert not any("/doi/pdf/" in url for url in calls)
        assert page.evaluate("localStorage.getItem('fixture_clicks')") == "1"
    finally:
        context.close()


@pytest.mark.parametrize("institution", ["Example University", "Another Academy"])
@pytest.mark.parametrize(
    "link_doi,expected",
    [
        ("10.1080/test", ChallengeKind.ENTITLEMENT),
        ("10.1080/other", ChallengeKind.NONE),
    ],
)
def test_tf_target_denial_does_not_reselect_institution(
    control_browser, institution, link_doi, expected
):
    page = control_browser.new_page()
    page.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html",
            body=f"""
    <title>Target Article</title><meta name="citation_doi" content="10.1080/test">
    <body>Access provided by {institution}. Purchase options. Add to cart.
    <a href="/doi/full/{link_doi}?needAccess=true">Full Article</a>
    <button onclick="window.clicked=true">Access through your institution</button></body>""",
        ),
    )
    try:
        page.goto("https://www.tandfonline.com/doi/abs/10.1080/test")
        report = browser_route._report_for_page(page)
        assert report.kind == expected
        if expected == ChallengeKind.ENTITLEMENT:
            clicked, _, _, final = browser_route._run_institution_handoff(
                page.context, page, config=BrowserAccessConfig()
            )
            assert clicked is False and final.kind == expected
            assert page.evaluate("window.clicked || false") is False
        captcha = ChallengeReport(kind=ChallengeKind.CAPTCHA)
        assert adapter_for_url(page.url).refine_page_challenge(page, captcha) == captcha
    finally:
        page.close()


@pytest.mark.parametrize("mode", ["headers", "body", "oversize", "success"])
def test_pdf_viewer_fetch_has_real_time_and_size_limits(control_browser, mode):
    page = control_browser.new_page()
    page.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html", body="<title>Viewer</title>"
        ),
    )
    try:
        page.goto("https://publisher.example/doi/pdf/10.1000/test")
        page.evaluate(
            """mode => {
            window.fetch = async () => {
                if(mode === 'headers') return new Promise(() => {});
                const stream = new ReadableStream({start(controller) {
                    if(mode === 'body') return;
                    controller.enqueue(new TextEncoder().encode(
                        mode === 'oversize' ? '%PDF-' + 'x'.repeat(1000) : '%PDF-test'));
                    controller.close();
                }});
                return new Response(stream, {status:200});
            };
        }""",
            mode,
        )
        started = time.monotonic()
        result = viewer.trigger_pdf_viewer_same_origin_fetch(
            page, max_bytes=100, validate_url=lambda url: url, timeout=0.15
        )
        assert result is (mode == "success")
        assert time.monotonic() - started < 2
    finally:
        page.close()


def test_real_session_recovers_retained_page_after_user_completion(
    control_browser, tmp_path, monkeypatch, local_article_server
):
    context = control_browser.new_context()
    title = "Authenticated Browser Integration Article"

    def challenge_route(route):
        if "an_session=ok" in route.request.headers.get("cookie", ""):
            route.fulfill(status=302, headers={"Location": "/article"})
            return
        route.fulfill(
            content_type="text/html",
            body="""
        <title>Verify you are human</title><body>Verify you are human
        <button id="complete" onclick="location.href='/article'">
        Complete fixture verification</button></body>""",
        )

    context.route("**/fixture-challenge", challenge_route)
    monkeypatch.setattr(browser, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(
        browser_route, "_install_browser_request_guard", lambda page: []
    )
    session = BrowserSession(
        BrowserAccessConfig(
            interactive=True,
            interaction_timeout=0,
            auto_challenge_grace=0,
            request_timeout=2,
        )
    )
    session._context = context
    browser._install_context_event_capture(
        context,
        pdf_responses=session._pdf_responses,
        downloads=session._downloads,
        snapshot_pdf_responses=True,
        max_bytes=100000,
    )
    source = FullTextCandidate(
        doi="10.1000/browser-integration",
        url=local_article_server + "/fixture-challenge",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    try:
        first = session.acquire(
            doi=source.doi, routes=[source], output_dir=tmp_path, expected_title=title
        )
        assert first.attempts[-1].status == BrowserAttemptStatus.INTERACTION_REQUIRED
        page = session._pending_pages[source.doi]
        assert not page.is_closed()
        page.locator("#complete").click()
        page.wait_for_url("**/article")
        page.evaluate("""() => {const a=document.createElement('a');
            a.href='/article.pdf'; a.textContent='Download PDF'; document.body.append(a);}""")
        assert session.interaction_ready(source.doi)
        recovered = session.acquire(
            doi=source.doi, routes=[source], output_dir=tmp_path, expected_title=title
        )
        assert recovered.verified_result is not None, [
            (
                a.status,
                a.evidence,
                [
                    (f.method, f.error, f.result.status if f.result else None)
                    for f in a.file_attempts
                ],
            )
            for a in recovered.attempts
        ]
        assert recovered.verified_result.status == AcquisitionStatus.VERIFIED
        assert not page.is_closed()
    finally:
        session.close()


@pytest.mark.parametrize(
    "admin_link",
    [
        '<a href="/action/institutionAccessEntitlements">Manage Your Institutional Subscription</a>',
        '<a href="/action/ssostart?redirectUri=%2Faction%2FinstitutionAccessEntitlements">Institutional access</a>',
        "<div onclick=\"document.body.dataset.clicked='admin'\">Log in to manage your institutional subscription</div>",
    ],
)
@pytest.mark.parametrize("has_reader", [False, True])
def test_institution_control_skips_librarian_routes(
    control_browser, admin_link, has_reader
):
    page = control_browser.new_page()
    reader = (
        "<button onclick=\"document.body.dataset.clicked='reader'\">Access through your institution</button>"
        if has_reader
        else ""
    )
    page.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html",
            body=f"<title>Article</title><body><footer>{admin_link}</footer>{reader}</body>",
        ),
    )
    try:
        page.goto("https://www.science.org/doi/10.1126/example")
        clicked = browser_route._click_semantic_institution_control(page)
        assert clicked is has_reader
        assert page.evaluate("document.body.dataset.clicked || ''") == (
            "reader" if has_reader else ""
        )
        assert page.url == "https://www.science.org/doi/10.1126/example"
    finally:
        page.close()


@pytest.mark.parametrize("wait_for_user", [False, True])
@pytest.mark.parametrize("delivery", ["inline", "attachment"])
def test_pdf_endpoint_handoff_uses_visible_wait_then_native_delivery(
    control_browser,
    local_article_server,
    tmp_path,
    monkeypatch,
    wait_for_user,
    delivery,
):
    from aletheia_nexus.acquire.access.models import BrowserFileAttempt

    context = control_browser.new_context()
    responses = []
    downloads = []
    page = context.new_page()
    doi = "10.1000/browser-integration"
    endpoint = local_article_server + "/protected.pdf"
    browser._install_context_event_capture(
        context,
        pdf_responses=responses,
        downloads=downloads,
        snapshot_pdf_responses=True,
        max_bytes=100000,
    )

    def gate(route):
        if "fixture_verified=yes" in route.request.all_headers().get("cookie", ""):
            route.fulfill(
                content_type="application/pdf",
                body=_Handler.pdf_body,
                headers={"Content-Disposition": f"{delivery}; filename=article.pdf"},
            )
        else:
            route.fulfill(
                content_type="text/html",
                body="<title>Verify you are human</title><body>Verify you are human<button id='complete' onclick=\"document.cookie='fixture_verified=yes; path=/';location.reload()\">Complete fixture verification</button></body>",
            )

    context.route("**/protected.pdf", gate)
    monkeypatch.setattr(browser_route, "validate_browser_network_url", lambda url: url)
    monkeypatch.setattr(browser_route, "_install_browser_request_guard", lambda p: [])
    monkeypatch.setattr(browser_route, "derive_pdf_candidates", lambda **k: ())
    wait_budgets = []
    original_wait = browser_route._wait_until_challenge_changes

    def bounded_fixture_wait(p, *, seconds, **kwargs):
        wait_budgets.append(seconds)
        return original_wait(p, seconds=8 if seconds is None else seconds, **kwargs)

    monkeypatch.setattr(
        browser_route, "_wait_until_challenge_changes", bounded_fixture_wait
    )
    api_calls = []

    def api(context, *, candidate, **kwargs):
        api_calls.append(candidate.url)
        return BrowserFileAttempt(
            candidate=candidate, error="HTTP-only challenge"
        ), ChallengeReport(kind=ChallengeKind.CAPTCHA)

    monkeypatch.setattr(browser_route, "_request_pdf_candidate", api)
    notices = []

    def complete(report, url):
        notices.append((report.kind, url))
        assert page.locator("#complete").is_visible()
        page.locator("#complete").click()

    try:
        page.goto(local_article_server + "/article")
        page.evaluate(
            "() => {const b=document.createElement('button');b.textContent='Download PDF';b.onclick=()=>fetch('/protected.pdf');document.body.append(b);}"
        )
        result = browser_route.attempt_browser_route(
            context,
            page,
            source=FullTextCandidate(
                doi=doi, url=local_article_server + "/article", provenance=()
            ),
            output_dir=tmp_path,
            expected_title="Authenticated Browser Integration Article",
            config=BrowserAccessConfig(
                interactive=wait_for_user,
                wait_for_interaction=wait_for_user,
                interaction_timeout=0,
                auto_challenge_grace=0,
                interaction_callback=complete,
                request_timeout=2,
            ),
            session_blocked_urls=[],
            session_pdf_responses=responses,
            session_downloads=downloads,
            _navigate_source=False,
        )
        assert api_calls == [endpoint]
        if wait_for_user:
            assert notices and notices[0][0] == ChallengeKind.CAPTCHA
            assert result.status == BrowserAttemptStatus.VERIFIED, [
                (a.method, a.error, a.result.status if a.result else None)
                for a in result.file_attempts
            ]
            assert result.interaction_used
            assert None in wait_budgets
        else:
            assert not notices
            assert result.status == BrowserAttemptStatus.INTERACTION_REQUIRED
            assert page.url == endpoint and not page.is_closed()
    finally:
        context.close()
