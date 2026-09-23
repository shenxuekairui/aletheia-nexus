import os
import threading
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
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="real Chromium smoke is enabled only in the browser-extra CI job",
)


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
