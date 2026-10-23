"""Generic regressions for native PDF shells and recoverable purchase pages."""

from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import browser_route
from aletheia_nexus.acquire.access.browser_engine.viewer import (
    is_native_pdf_placeholder,
)
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.discovery.models import FullTextCandidate

SHELL = b"""<!doctype html><html><body><embed name="random-id"
    src="about:blank" type="application/pdf" internalid="random-id"></body></html>"""


def test_native_shell_is_delivery_signal_not_a_corrupt_pdf(tmp_path):
    from test_browser_response import _pdf_bytes, _Response

    assert is_native_pdf_placeholder(SHELL)
    assert is_native_pdf_placeholder(SHELL.replace(b"random-id", b"another-length"))
    assert not is_native_pdf_placeholder(_pdf_bytes())
    assert not is_native_pdf_placeholder(b"<html>Sign in to access</html>")
    assert not is_native_pdf_placeholder(SHELL.replace(b"about:blank", b"/real.pdf"))
    attempt = browser_route._browser_response_to_file_attempt(
        _Response(SHELL),
        parent=FullTextCandidate(
            doi="10.1000/example", url="https://example.org/a", provenance=()
        ),
        source_page_url="https://example.org/a",
        output_dir=tmp_path,
        expected_title="Target article",
        config=BrowserAccessConfig(),
    )
    assert attempt.result is None
    assert attempt.error.startswith("NativePdfViewerPlaceholder:")
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.parametrize("matches", [True, False])
@pytest.mark.parametrize("url_source", ["frame", "plugin"])
def test_generic_pdf_filename_requires_matching_browser_frame(matches, url_source):
    import json

    from aletheia_nexus.acquire.access.browser_engine.viewer import (
        _viewer_for_document_url,
    )

    expected = "https://cdn.example/documents/unique-article/main.pdf?signature=one"
    targets = [
        {
            "targetId": key,
            "type": "webview",
            "title": "main.pdf",
            "url": "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html",
        }
        for key in ("unrelated", "owned")
    ]

    class Session:
        detached = []

        def on(self, event, callback):
            self.callback = callback

        def remove_listener(self, event, callback):
            assert callback is self.callback

        def send(self, method, params):
            if method == "Target.attachToTarget":
                return {"sessionId": params["targetId"]}
            if method == "Target.detachFromTarget":
                self.detached.append(params["sessionId"])
            if method == "Target.sendMessageToTarget":
                command = json.loads(params["message"])
                document = (
                    expected
                    if matches and params["sessionId"] == "owned"
                    else "https://cdn.example/other/main.pdf"
                )
                result = (
                    {"result": {"value": document if url_source == "plugin" else None}}
                    if command["method"] == "Runtime.evaluate"
                    else {
                        "frameTree": {
                            "frame": {"url": targets[0]["url"]},
                            "childFrames": [{"frame": {"url": document}}]
                            if url_source == "frame"
                            else [],
                        }
                    }
                )
                self.callback(
                    {
                        "sessionId": params["sessionId"],
                        "message": json.dumps(
                            {
                                "id": command["id"],
                                "result": result,
                            }
                        ),
                    }
                )

    session = Session()
    page = SimpleNamespace(url=expected)
    result = _viewer_for_document_url(session, page, targets, timeout=1)
    assert result == (targets[1] if matches else None)
    assert session.detached == ["unrelated", "owned"]


class Control:
    def __init__(self, text, href, visible=True):
        self.text, self.href, self.visible = text, href, visible
        self.clicked = False

    def inner_text(self, **kwargs):
        return self.text

    def get_attribute(self, name, **kwargs):
        return self.href if name == "href" else None

    def is_visible(self):
        return self.visible

    def click(self, **kwargs):
        self.clicked = True


class Controls:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class LoginPage:
    url = "https://publisher.example/article"
    frames = []

    def __init__(self, controls):
        self.controls = controls

    def get_by_role(self, role, name):
        return Controls(
            [c for c in self.controls if role == "link" and name.search(c.text)]
        )


@pytest.mark.parametrize(
    "label", ["Publisher Library login", "Sign in with your account", "读者登录"]
)
def test_branded_login_at_purchase_boundary_is_recoverable(monkeypatch, label):
    control = Control(label, "https://publisher.example/signin")
    page = LoginPage([control])
    monkeypatch.setattr(
        browser_route,
        "_page_snapshot",
        lambda p: (
            "Target article",
            p.url,
            "Purchase this article Login",
            "<main>Access options</main>",
        ),
    )
    report = browser_route._report_for_page(page)
    assert report.kind == ChallengeKind.AUTHENTICATION
    assert browser_route._PURCHASE_LOGIN_OPTION in report.evidence
    assert not control.clicked
    assert browser_route._click_reader_login_link(page)
    assert control.clicked


@pytest.mark.parametrize(
    "text,visible,label,href,expected",
    [
        ("Article abstract", True, "Publisher login", "/login", ChallengeKind.NONE),
        (
            "Purchase this article",
            False,
            "Publisher login",
            "/login",
            ChallengeKind.ENTITLEMENT,
        ),
        (
            "Purchase this article",
            True,
            "Sign in or purchase",
            "/purchase",
            ChallengeKind.ENTITLEMENT,
        ),
        (
            "Your institution does not have access. Purchase this article",
            True,
            "Publisher login",
            "/login",
            ChallengeKind.ENTITLEMENT,
        ),
        (
            "Purchase this article",
            True,
            "Publisher login",
            "javascript:openLogin()",
            ChallengeKind.ENTITLEMENT,
        ),
        (
            "Verify you are human. Purchase this article",
            True,
            "Publisher login",
            "/login",
            ChallengeKind.CAPTCHA,
        ),
    ],
)
def test_login_rule_requires_recoverable_boundary_and_visible_safe_action(
    monkeypatch, text, visible, label, href, expected
):
    control = Control(label, href, visible)
    page = LoginPage([control])
    monkeypatch.setattr(
        browser_route, "_page_snapshot", lambda p: ("Article", p.url, text, "<main/>")
    )
    assert browser_route._report_for_page(page).kind == expected
    assert not control.clicked


def test_purchase_login_is_followed_before_waiting(monkeypatch, tmp_path):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    page = _RoutePage("https://publisher.example/article")
    context = _RouteContext(page)
    boundary = ChallengeReport(
        ChallengeKind.AUTHENTICATION, (browser_route._PURCHASE_LOGIN_OPTION,)
    )
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: boundary)
    monkeypatch.setattr(
        browser_route, "_click_semantic_institution_control", lambda p: False
    )
    clicks = []
    monkeypatch.setattr(
        browser_route, "_click_reader_login_link", lambda p: clicks.append(p) or True
    )

    def wait(p, **kwargs):
        assert clicks == [page]
        return boundary, (boundary,), True

    monkeypatch.setattr(browser_route, "_resolve_external_auth_page", wait)
    result = browser_route._run_institution_handoff(
        context, page, config=BrowserAccessConfig()
    )
    assert result[0] and result[2] and result[3] == boundary


@pytest.mark.parametrize(
    "matching_article,pdf_visible", [(True, True), (False, True), (True, False)]
)
@pytest.mark.parametrize("same_query", [True, False])
def test_existing_article_tab_can_complete_login_but_unrelated_tab_cannot(
    monkeypatch, tmp_path, matching_article, pdf_visible, same_query
):
    from test_browser_challenge_flow import _RoutePage

    auth = _RoutePage("https://idp.example/login")
    article = _RoutePage(
        "https://publisher.example/article/"
        + ("target" if matching_article else "other")
        + ("?article=one" if same_query else "?article=other")
    )
    context = SimpleNamespace(pages=[auth, article])
    gate = ChallengeReport(ChallengeKind.AUTHENTICATION)
    clear = ChallengeReport(ChallengeKind.NONE)
    monkeypatch.setattr(
        browser_route, "_report_for_page", lambda p: gate if p is auth else clear
    )
    monkeypatch.setattr(
        browser_route, "_has_visible_pdf_control", lambda p: pdf_visible
    )
    returned = []
    result, _, _ = browser_route._resolve_external_auth_page(
        auth,
        source_host="publisher.example",
        context=context,
        existing_page_ids={id(auth), id(article)},
        origin_url="https://publisher.example/article/target/pdf?article=one",
        config=BrowserAccessConfig(interactive=False),
        returned_pages=returned,
    )
    if matching_article and pdf_visible and same_query:
        assert result.kind == ChallengeKind.NONE
        assert returned == [article]
    else:
        assert result.kind != ChallengeKind.NONE
        assert returned == []


def test_handoff_resumes_observed_article_instead_of_stale_login_tab(monkeypatch):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    page = _RoutePage("https://publisher.example/article/target/pdf")
    article = _RoutePage("https://publisher.example/article/target")
    context = _RouteContext(page)
    context.pages.append(article)
    boundary = ChallengeReport(
        ChallengeKind.AUTHENTICATION, (browser_route._PURCHASE_LOGIN_OPTION,)
    )
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: boundary)
    monkeypatch.setattr(
        browser_route, "_click_semantic_institution_control", lambda p: False
    )

    def click(p):
        p.url = "https://idp.example/login"
        return True

    monkeypatch.setattr(browser_route, "_click_reader_login_link", click)

    def resolve(p, returned_pages, **kwargs):
        returned_pages.append(article)
        return ChallengeReport(ChallengeKind.NONE), (), True

    monkeypatch.setattr(browser_route, "_resolve_external_auth_page", resolve)
    result = browser_route._run_institution_handoff(
        context, page, config=BrowserAccessConfig()
    )
    assert result[3].kind == ChallengeKind.NONE
    assert page.goto_calls == [article.url]


@pytest.mark.parametrize("popup_mode", [False, True])
@pytest.mark.parametrize(
    "gate", [ChallengeKind.NONE, ChallengeKind.CAPTCHA, ChallengeKind.ENTITLEMENT]
)
def test_post_click_viewer_is_saved_before_closing_but_access_gate_is_preserved(
    monkeypatch, tmp_path, popup_mode, gate
):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    title = "Electrochemical reduction of carboxylic acids"
    page = _RoutePage("https://publisher.example/article")
    popup = _RoutePage("https://cdn.example/target.pdf")
    closed = []
    popup.close = lambda: closed.append(True)
    popup.is_closed = lambda: bool(closed)
    context = _RouteContext(page)
    clicked = []
    clear = ChallengeReport(ChallengeKind.NONE)

    def report(p):
        return (
            ChallengeReport(gate)
            if clicked and (not popup_mode or p is popup)
            else clear
        )

    monkeypatch.setattr(browser_route, "_report_for_page", report)
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda p, **k: (report(p), (report(p),), False),
    )
    monkeypatch.setattr(browser_route, "_auth_wait_report", lambda p, r, **k: r)
    monkeypatch.setattr(
        browser_route,
        "_observe_pdf_popups",
        lambda *a, **k: ((), (ChallengeReport(gate),), False),
    )
    monkeypatch.setattr(browser_route, "parse_html", lambda h: object())
    monkeypatch.setattr(
        browser_route,
        "validate_page_identity",
        lambda **k: SimpleNamespace(status=SimpleNamespace(value="MATCH"), evidence=()),
    )
    monkeypatch.setattr(browser_route, "derive_pdf_candidates", lambda **k: ())
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *a, **k: None
    )
    monkeypatch.setattr(
        browser_route, "_trigger_pdf_viewer_same_origin_fetch", lambda *a, **k: False
    )
    monkeypatch.setattr(
        browser_route, "_runtime_publisher_pdf_candidate", lambda *a: None
    )
    monkeypatch.setattr(
        browser_route,
        "_run_institution_handoff",
        lambda *a, **k: (False, (), False, clear),
    )

    def click(p):
        clicked.append(True)
        if popup_mode:
            context.pages.append(popup)
        else:
            page.url = "https://cdn.example/target.pdf"
        return True

    monkeypatch.setattr(browser_route, "_click_semantic_pdf_control", click)
    saved = []

    def save(c, p, **k):
        if not clicked or popup_mode and p is page:
            return None
        assert gate == ChallengeKind.NONE
        assert not closed
        saved.append(p)
        stage = tmp_path / "stage"
        stage.mkdir()
        path = stage / "native.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_metadata({"/Title": title})
        writer.write(path)
        return path, stage

    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", save)
    result = browser_route.attempt_browser_route(
        context,
        page,
        source=FullTextCandidate(doi="10.1000/example", url=page.url, provenance=()),
        output_dir=tmp_path / "output",
        expected_title=title,
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
        _navigate_source=False,
    )
    assert (result.status == BrowserAttemptStatus.VERIFIED) == (
        gate == ChallengeKind.NONE
    )
    assert len(saved) == (1 if gate == ChallengeKind.NONE else 0)
    if popup_mode:
        assert bool(closed) == (gate == ChallengeKind.NONE)
