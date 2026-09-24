import base64
import time
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import browser_route
from aletheia_nexus.acquire.access.browser_route import (
    _resolve_page_challenge,
    _wait_until_challenge_changes,
)
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
)


class _Body:
    def __init__(self, page):
        self.page = page

    def inner_text(self, timeout=0):
        return self.page.current[2]


class _Page:
    def __init__(self, states):
        self.states = states
        self.index = 0

    @property
    def current(self):
        return self.states[self.index]

    @property
    def url(self):
        return self.current[1]

    def title(self):
        return self.current[0]

    def locator(self, selector):
        assert selector == "body"
        return _Body(self)

    def content(self):
        return self.current[3]

    def wait_for_timeout(self, milliseconds):
        if self.index + 1 < len(self.states):
            self.index += 1

    def is_closed(self):
        return False


class _ClosingPage(_Page):
    def wait_for_timeout(self, milliseconds):
        raise RuntimeError("TargetClosedError")


def test_thieme_pdf_redirect_to_buy_article_is_entitlement():
    response = SimpleNamespace(
        headers={"content-type": "text/html"},
        url=(
            "https://www.thieme-connect.com/products/ejournals/abstract/"
            "10.1055/a-2508-9744"
        ),
    )
    report = browser_route._challenge_from_non_pdf_response(
        response,
        b"<html><head><title>Article</title></head><body>Buy Article</body></html>",
    )

    assert report.kind == ChallengeKind.ENTITLEMENT


def test_closed_challenge_target_preserves_last_known_challenge(tmp_path):
    page = _ClosingPage(
        [
            (
                "Are you a robot?",
                "https://publisher.example/challenge",
                "Please confirm you are a human by completing the captcha challenge below.",
                '<iframe src="https://challenges.cloudflare.com/turnstile/"></iframe>',
            )
        ]
    )

    report, history, interaction_used = _resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            auto_challenge_grace=0,
            interaction_timeout=1,
            poll_interval=0.001,
        ),
    )

    assert report.kind == ChallengeKind.CAPTCHA
    assert history == (
        ChallengeReport(
            kind=ChallengeKind.CAPTCHA,
            evidence=report.evidence,
        ),
    )
    assert interaction_used is True


def test_browser_native_challenge_can_clear_without_human_interaction(tmp_path):
    page = _Page(
        [
            (
                "Verify you are human",
                "https://publisher.example/challenge",
                "Verify you are human",
                '<div class="g-recaptcha"></div>',
            ),
            (
                "Article",
                "https://publisher.example/article",
                "Article abstract",
                "<main>Article abstract</main>",
            ),
        ]
    )
    report, history, interaction_used = _resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            auto_challenge_grace=0.01,
            interaction_timeout=0,
            poll_interval=0.001,
        ),
    )

    assert report.kind == ChallengeKind.NONE
    assert history[0].kind == ChallengeKind.CAPTCHA
    assert history[-1].kind == ChallengeKind.NONE
    assert interaction_used is False


def test_transient_blank_challenge_page_does_not_count_as_cleared():
    challenge = (
        "Verify you are human",
        "https://pubs.rsc.org/en/content/articlepdf/2026/ta/test",
        "Verify you are human",
        '<div class="cf-turnstile"></div>',
    )
    page = _Page(
        [
            challenge,
            ("", challenge[1], "", "<html></html>"),
            challenge,
            ("Article", "https://pubs.rsc.org/article", "Article text", "<main />"),
        ]
    )
    initial = browser_route._report_for_page(page)
    history = [initial]

    report = _wait_until_challenge_changes(
        page,
        initial=initial,
        seconds=0.05,
        poll_interval=0.001,
        history=history,
    )

    assert report.kind == ChallengeKind.NONE
    assert [item.kind for item in history] == [
        ChallengeKind.CAPTCHA,
        ChallengeKind.NONE,
    ]


def test_incomplete_clearance_remains_challenge_after_timeout():
    class _TimedPage(_Page):
        def wait_for_timeout(self, milliseconds):
            time.sleep(milliseconds / 1000)
            super().wait_for_timeout(milliseconds)

    page = _TimedPage(
        [
            (
                "Verify you are human",
                "https://pubs.rsc.org/challenge",
                "Verify you are human",
                "",
            ),
            ("", "https://pubs.rsc.org/challenge", "", "<html></html>"),
        ]
    )
    initial = browser_route._report_for_page(page)
    history = [initial]

    report = _wait_until_challenge_changes(
        page,
        initial=initial,
        seconds=0.006,
        poll_interval=0.003,
        history=history,
    )

    assert report.kind == ChallengeKind.CAPTCHA
    assert [item.kind for item in history] == [ChallengeKind.CAPTCHA]


def test_sso_handoff_calls_user_callback_and_resumes(tmp_path):
    events = []
    page = _Page(
        [
            (
                "Institutional sign in",
                "https://idp.example/login?state=secret",
                "Access through your institution",
                "<main>Access through your institution</main>",
            ),
            (
                "Article",
                "https://publisher.example/article",
                "Article abstract",
                "<main>Article abstract</main>",
            ),
        ]
    )

    report, history, interaction_used = _resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            auto_challenge_grace=0,
            interaction_timeout=0.01,
            poll_interval=0.001,
            interaction_callback=lambda challenge, url: events.append(
                (challenge.kind, url)
            ),
        ),
    )

    assert events == [
        (
            ChallengeKind.SSO,
            "https://idp.example/login?state=%5Bredacted%5D",
        )
    ]
    assert report.kind == ChallengeKind.NONE
    assert history[0].kind == ChallengeKind.SSO
    assert interaction_used is True


class _RoutePage:
    def __init__(self, url):
        self.url = url
        self.goto_calls = []
        self.handlers = {}

    def goto(self, url, **kwargs):
        self.url = url
        self.goto_calls.append(url)
        return None

    def on(self, event, callback):
        self.handlers[event] = callback

    def content(self):
        return "<html><body>Target article</body></html>"

    def is_closed(self):
        return False

    def wait_for_timeout(self, milliseconds):
        return None


class _RouteContext:
    def __init__(self, page):
        self.pages = [page]


def test_rsc_direct_pdf_navigates_before_any_extra_request(monkeypatch, tmp_path):
    pdf_url = "https://pubs.rsc.org/en/content/articlepdf/2026/ta/example"
    page = _RoutePage("about:blank")
    source = FullTextCandidate(
        doi="10.1039/example",
        url=pdf_url,
        provenance=(),
        url_type=CandidateUrlType.PDF,
    )
    request_calls = []

    def request_pdf(*args, **kwargs):
        request_calls.append(kwargs["candidate"].url)
        raise RuntimeError("stop after first fallback request")

    monkeypatch.setattr(browser_route, "_request_pdf_candidate", request_pdf)
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda value: ChallengeReport(kind=ChallengeKind.NONE),
    )
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda value, *, config: (ChallengeReport(kind=ChallengeKind.NONE), (), False),
    )
    monkeypatch.setattr(browser_route, "parse_html", lambda html: object())
    monkeypatch.setattr(
        browser_route,
        "validate_page_identity",
        lambda **kwargs: SimpleNamespace(
            status=SimpleNamespace(value="MATCH"), evidence=()
        ),
    )
    monkeypatch.setattr(
        browser_route, "_runtime_publisher_pdf_candidate", lambda *a: None
    )
    monkeypatch.setattr(browser_route, "derive_pdf_candidates", lambda **kwargs: ())
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *a, **k: None
    )
    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="first fallback"):
        browser_route.attempt_browser_route(
            _RouteContext(page),
            page,
            source=source,
            output_dir=tmp_path,
            expected_title="Article",
            config=BrowserAccessConfig(profile_root=tmp_path),
            session_blocked_urls=[],
            session_pdf_responses=[],
            session_downloads=[],
        )

    assert page.goto_calls == [pdf_url]
    assert request_calls == [pdf_url]


def test_pdf_challenge_reappearing_after_one_retry_stops_route(monkeypatch, tmp_path):
    article_url = "https://publisher.example/article"
    pdf_url = "https://publisher.example/article.pdf"
    page = _RoutePage(article_url)
    context = _RouteContext(page)
    source = FullTextCandidate(
        doi="10.1000/challenge-retry",
        url=article_url,
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    pdf = FullTextCandidate(
        doi=source.doi,
        url=pdf_url,
        provenance=(),
        url_type=CandidateUrlType.PDF,
    )
    challenge = ChallengeReport(kind=ChallengeKind.CAPTCHA)
    request_urls = []

    def request_pdf(context_value, *, candidate, **kwargs):
        request_urls.append(candidate.url)
        return BrowserFileAttempt(candidate=candidate, error="Challenge"), challenge

    monkeypatch.setattr(browser_route, "_request_pdf_candidate", request_pdf)
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda value: ChallengeReport(kind=ChallengeKind.NONE),
    )
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda value, *, config: (ChallengeReport(kind=ChallengeKind.NONE), (), True),
    )
    monkeypatch.setattr(browser_route, "parse_html", lambda html: object())
    monkeypatch.setattr(
        browser_route,
        "validate_page_identity",
        lambda **kwargs: SimpleNamespace(
            status=SimpleNamespace(value="MATCH"), evidence=()
        ),
    )
    monkeypatch.setattr(
        browser_route, "_runtime_publisher_pdf_candidate", lambda *a: None
    )
    monkeypatch.setattr(
        browser_route,
        "derive_pdf_candidates",
        lambda **kwargs: (SimpleNamespace(candidate=pdf),),
    )
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *a, **k: None
    )
    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", lambda *a, **k: None)

    result = browser_route.attempt_browser_route(
        context,
        page,
        source=source,
        output_dir=tmp_path,
        expected_title="Article",
        config=BrowserAccessConfig(profile_root=tmp_path),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
    )

    assert request_urls == [pdf_url, pdf_url]
    assert page.goto_calls == [article_url, pdf_url]
    assert result.status == BrowserAttemptStatus.INTERACTION_REQUIRED
    assert result.challenge_history[-1].kind == ChallengeKind.CAPTCHA


def test_article_route_automatically_enters_institutional_sso(
    monkeypatch,
    tmp_path,
):
    page = _RoutePage("https://publisher.example/article")
    context = _RouteContext(page)
    handoff_calls = []

    monkeypatch.setattr(
        browser_route,
        "validate_browser_network_url",
        lambda value: value,
    )
    report_calls = 0

    def page_report(value):
        nonlocal report_calls
        report_calls += 1
        return ChallengeReport(
            kind=ChallengeKind.SSO if report_calls == 1 else ChallengeKind.NONE
        )

    monkeypatch.setattr(browser_route, "_report_for_page", page_report)

    def handoff(context_value, page_value, *, config):
        handoff_calls.append((context_value, page_value))
        return (
            True,
            (
                ChallengeReport(kind=ChallengeKind.SSO),
                ChallengeReport(kind=ChallengeKind.NONE),
            ),
            False,
            ChallengeReport(kind=ChallengeKind.NONE),
        )

    monkeypatch.setattr(browser_route, "_run_institution_handoff", handoff)
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda page_value, *, config: (
            ChallengeReport(kind=ChallengeKind.NONE),
            (ChallengeReport(kind=ChallengeKind.NONE),),
            False,
        ),
    )
    monkeypatch.setattr(
        browser_route,
        "parse_html",
        lambda html: object(),
    )
    monkeypatch.setattr(
        browser_route,
        "validate_page_identity",
        lambda **kwargs: SimpleNamespace(
            status=SimpleNamespace(value="MATCH"),
            evidence=(),
        ),
    )
    monkeypatch.setattr(browser_route, "derive_pdf_candidates", lambda **kwargs: ())
    monkeypatch.setattr(
        browser_route,
        "_click_semantic_pdf_control",
        lambda page: False,
    )

    candidate = FullTextCandidate(
        doi="10.1000/institution-route",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    result = browser_route.attempt_browser_route(
        context,
        page,
        source=candidate,
        output_dir=tmp_path,
        expected_title="Target article",
        config=BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            interactive=False,
            auto_challenge_grace=0,
            interaction_timeout=0,
        ),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
    )

    assert handoff_calls == [(context, page)]
    assert page.goto_calls == ["https://publisher.example/article"]
    assert result.status == BrowserAttemptStatus.NO_FILE_CANDIDATES
    assert result.evidence[0] == (
        "Institutional access handoff completed; current browser page resumed"
    )
    assert [report.kind for report in result.challenge_history] == [
        ChallengeKind.SSO,
        ChallengeKind.NONE,
    ]


class _InstitutionControl:
    def __init__(self, text="", *, aria_label=None, title=None, href=None):
        self.text = text
        self.attributes = {
            "aria-label": aria_label,
            "title": title,
            "href": href,
        }
        self.clicked = False

    def inner_text(self):
        return self.text

    def get_attribute(self, name):
        return self.attributes.get(name)

    def click(self, timeout=0):
        self.clicked = True

    def is_visible(self):
        return True


class _InstitutionLocator:
    def __init__(self, control):
        self.control = control

    def count(self):
        return 1

    def nth(self, index):
        assert index == 0
        return self.control


class _InstitutionPage:
    def __init__(self, text="", **attributes):
        self.control = _InstitutionControl(text, **attributes)

    def locator(self, selector):
        assert selector == "a, button, [role='button'], [role='link']"
        return _InstitutionLocator(self.control)


def test_standard_federated_login_controls_are_clicked():
    for text in ("Sign in with Shibboleth", "Access via OpenAthens"):
        page = _InstitutionPage(text)

        assert browser_route._click_semantic_institution_control(page) is True
        assert page.control.clicked is True


def test_accessible_organization_control_is_clicked_without_visible_text():
    page = _InstitutionPage(aria_label="Access through your organization")

    assert browser_route._click_semantic_institution_control(page) is True
    assert page.control.clicked is True


def test_ieee_access_through_university_control_is_clicked():
    page = _InstitutionPage("Access Through University of Chinese Academy")

    assert browser_route._click_semantic_institution_control(page) is True
    assert page.control.clicked is True


def test_ieee_remembered_institution_is_distinguished_from_chooser():
    class Modal:
        def __init__(self, label):
            self.control = _InstitutionControl(label)

        def is_visible(self):
            return True

        def locator(self, selector):
            assert selector == browser_route._INTERACTIVE_CONTROL_SELECTOR
            return _InstitutionLocator(self.control)

    class Dialogs:
        def __init__(self, label):
            self.modal = Modal(label)

        def filter(self, *, has_text):
            assert has_text == "Full text access may be available"
            return self

        def count(self):
            return 1

        def nth(self, index):
            assert index == 0
            return self.modal

    class Page:
        url = "https://ieeexplore.ieee.org/document/5366888/"

        def __init__(self, label):
            self.dialogs = Dialogs(label)

        def locator(self, selector):
            assert selector == "dialog, [role='dialog'], .js-react-modal"
            return self.dialogs

    assert browser_route._ieee_selected_institution_available(
        Page("Access Through University of Chinese Academy")
    )
    assert not browser_route._ieee_selected_institution_available(
        Page("Access Through Your Institution")
    )


def test_ieee_remembered_institution_waits_then_returns_to_article(
    monkeypatch, tmp_path
):
    class Page:
        url = "https://ieeexplore.ieee.org/document/5366888/"

        def __init__(self):
            self.waits = []

        def wait_for_timeout(self, milliseconds):
            self.waits.append(milliseconds)

        def wait_for_load_state(self, state, timeout):
            assert state == "domcontentloaded"

    page = Page()
    context = SimpleNamespace(pages=[page])
    monkeypatch.setattr(
        browser_route, "_ieee_selected_institution_available", lambda page: True
    )
    monkeypatch.setattr(
        browser_route, "_click_semantic_institution_control", lambda page: True
    )
    monkeypatch.setattr(browser_route, "_dismiss_blocking_modal", lambda page: True)
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda page, *, config: (
            ChallengeReport(kind=ChallengeKind.NONE),
            (ChallengeReport(kind=ChallengeKind.NONE),),
            False,
        ),
    )

    clicked, _, _, report = browser_route._run_institution_handoff(
        context,
        page,
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert clicked is True
    assert report.kind == ChallengeKind.NONE
    assert page.waits == [5000, 350]


def test_visible_institution_text_fallback_clicks_nonsemantic_node():
    class EmptyLocator:
        def count(self):
            return 0

    class TextOnlyPage:
        def __init__(self):
            self.control = _InstitutionControl("Access through your organization")

        def locator(self, selector):
            assert selector == "a, button, [role='button'], [role='link']"
            return EmptyLocator()

        def get_by_text(self, pattern):
            assert pattern is browser_route._SEMANTIC_INSTITUTION_CONTROL
            return _InstitutionLocator(self.control)

    page = TextOnlyPage()

    assert browser_route._click_semantic_institution_control(page) is True
    assert page.control.clicked is True


def test_cross_origin_institution_popup_is_preserved_when_unclassified(
    monkeypatch,
    tmp_path,
):
    class AuthPage:
        url = "https://login.university.example/saml"

        def __init__(self):
            self.closed = False

        def wait_for_load_state(self, state, timeout=0):
            return None

        def is_closed(self):
            return self.closed

        def close(self):
            self.closed = True

    class ArticlePage:
        url = "https://publisher.example/article"

        def wait_for_timeout(self, milliseconds):
            context.pages.append(auth_page)

    article_page = ArticlePage()
    auth_page = AuthPage()
    context = SimpleNamespace(pages=[article_page])
    monkeypatch.setattr(
        browser_route,
        "_click_semantic_institution_control",
        lambda page: True,
    )
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda page, *, config: (
            ChallengeReport(kind=ChallengeKind.NONE),
            (ChallengeReport(kind=ChallengeKind.NONE),),
            False,
        ),
    )

    clicked, history, interaction_used, report = browser_route._run_institution_handoff(
        context,
        article_page,
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert clicked is True
    assert interaction_used is True
    assert report.kind == ChallengeKind.SSO
    assert history[-1] == report
    assert auth_page.closed is False


def test_unbounded_handoff_waits_until_user_clears_challenge(tmp_path):
    events = []
    page = _Page(
        [
            (
                "Verify you are human",
                "https://publisher.example/challenge",
                "Complete the captcha",
                '<div class="g-recaptcha"></div>',
            ),
            (
                "Verify you are human",
                "https://publisher.example/challenge",
                "Complete the captcha",
                '<div class="g-recaptcha"></div>',
            ),
            (
                "Article",
                "https://publisher.example/article",
                "Article abstract",
                "<main>Article abstract</main>",
            ),
        ]
    )

    report, history, interaction_used = _resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            auto_challenge_grace=0,
            interaction_timeout=0,
            wait_for_interaction=True,
            poll_interval=0.001,
            interaction_callback=lambda challenge, url: events.append(
                (challenge.kind, url)
            ),
        ),
    )

    assert events == [(ChallengeKind.CAPTCHA, "https://publisher.example/challenge")]
    assert report.kind == ChallengeKind.NONE
    assert history[0].kind == ChallengeKind.CAPTCHA
    assert history[-1].kind == ChallengeKind.NONE
    assert interaction_used is True


def test_external_idp_transient_plain_page_does_not_finish_handoff(tmp_path):
    events = []
    page = _Page(
        [
            (
                "查找您的组织",
                "https://id.publisher.example/authorization",
                "查找您的组织",
                "<main>查找您的组织</main>",
            ),
            (
                "Redirecting",
                "https://login.university.example/saml",
                "Please wait",
                "<main>Please wait</main>",
            ),
            (
                "Article",
                "https://publisher.example/article",
                "Article abstract",
                "<main>Article abstract</main>",
            ),
        ]
    )

    report, history, interaction_used = browser_route._resolve_external_auth_page(
        page,
        source_host="publisher.example",
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            wait_for_interaction=True,
            poll_interval=0.001,
            interaction_callback=lambda challenge, url: events.append(
                (challenge.kind, url)
            ),
        ),
    )

    assert events == [(ChallengeKind.SSO, "https://id.publisher.example/authorization")]
    assert report.kind == ChallengeKind.NONE
    assert history[0].kind == ChallengeKind.SSO
    assert history[-1].kind == ChallengeKind.NONE
    assert interaction_used is True


def test_external_idp_can_finish_in_new_publisher_tab(tmp_path):
    publisher_page = _Page(
        [
            (
                "Article",
                "https://publisher.example/article",
                "Article abstract",
                "<main>Article abstract</main>",
            )
        ]
    )
    context = SimpleNamespace(pages=[])

    class _AuthPage(_Page):
        def wait_for_timeout(self, milliseconds):
            context.pages.append(publisher_page)

    auth_page = _AuthPage(
        [
            (
                "Institutional sign in",
                "https://id.publisher.example/login",
                "Institutional sign in",
                "<main>Institutional sign in</main>",
            )
        ]
    )
    context.pages.append(auth_page)
    report, history, interaction_used = browser_route._resolve_external_auth_page(
        auth_page,
        source_host="publisher.example",
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            wait_for_interaction=True,
            poll_interval=0.001,
        ),
        context=context,
        existing_page_ids={id(auth_page)},
    )

    assert report.kind == ChallengeKind.NONE
    assert history[-1].kind == ChallengeKind.NONE
    assert interaction_used is True


def test_external_idp_blank_tab_can_return_to_existing_publisher_tab(tmp_path):
    publisher_page = _Page(
        [
            (
                "Article",
                "https://publisher.example/article",
                "Article abstract",
                "<main>Article abstract</main>",
            )
        ]
    )
    auth_page = _Page(
        [
            (
                "Institutional sign in",
                "https://id.publisher.example/login",
                "Institutional sign in",
                "<main>Institutional sign in</main>",
            ),
            ("about:blank", "about:blank", "", "<html></html>"),
        ]
    )
    context = SimpleNamespace(pages=[publisher_page, auth_page])
    report, history, interaction_used = browser_route._resolve_external_auth_page(
        auth_page,
        source_host="publisher.example",
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            wait_for_interaction=True,
            poll_interval=0.001,
        ),
        context=context,
        existing_page_ids={id(publisher_page), id(auth_page)},
    )

    assert report.kind == ChallengeKind.NONE
    assert history[-1].kind == ChallengeKind.NONE
    assert interaction_used is True


def test_unbounded_handoff_stops_at_entitlement_boundary(tmp_path):
    page = _Page(
        [
            (
                "Institutional sign in",
                "https://publisher.example/login",
                "Access through your institution",
                "<main>Institutional sign in</main>",
            ),
            (
                "Purchase article",
                "https://publisher.example/article",
                "Buy this article",
                "<main>Buy this article</main>",
            ),
        ]
    )

    report, history, interaction_used = _resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            auto_challenge_grace=0,
            interaction_timeout=0,
            wait_for_interaction=True,
            poll_interval=0.001,
        ),
    )

    assert report.kind == ChallengeKind.ENTITLEMENT
    assert history[-1].kind == ChallengeKind.ENTITLEMENT
    assert interaction_used is True


def test_accessible_pdf_control_is_clicked_without_visible_text():
    page = _InstitutionPage(aria_label="View PDF")

    assert browser_route._click_semantic_pdf_control(page) is True
    assert page.control.clicked is True


def test_pdf_control_closes_incidental_modal_and_ignores_its_recommendations():
    class ListLocator:
        def __init__(self, items):
            self.items = items

        def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class Control(_InstitutionControl):
        def __init__(self, page, text="", *, inside_modal=False, closes=False):
            super().__init__(text)
            self.page = page
            self.inside_modal = inside_modal
            self.closes = closes

        def evaluate(self, expression):
            return self.inside_modal

        def click(self, timeout=0):
            if self.closes:
                self.page.modal_open = False
                self.clicked = True
                return
            if self.page.modal_open:
                raise TimeoutError("modal intercepts pointer events")
            self.clicked = True

    class Modal:
        def __init__(self, page):
            self.page = page
            self.close = Control(page, "", inside_modal=True, closes=True)
            self.close.attributes["aria-label"] = "close window"

        def is_visible(self):
            return self.page.modal_open

        def locator(self, selector):
            assert selector == browser_route._INTERACTIVE_CONTROL_SELECTOR
            return ListLocator([self.close])

    class Page:
        def __init__(self):
            self.modal_open = True
            self.recommended = Control(self, "View PDF", inside_modal=True)
            self.article = Control(self, "View PDF")
            self.modal = Modal(self)

        def locator(self, selector):
            if selector == browser_route._INTERACTIVE_CONTROL_SELECTOR:
                return ListLocator([self.recommended, self.article])
            assert selector in browser_route._MODAL_SELECTORS
            if selector == ".js-react-modal":
                return ListLocator([self.modal])
            return ListLocator([])

        def wait_for_timeout(self, milliseconds):
            assert milliseconds == 350

    page = Page()

    assert browser_route._click_semantic_pdf_control(page) is True
    assert page.modal.close.clicked is True
    assert page.recommended.clicked is False
    assert page.article.clicked is True


def test_popup_processing_can_defer_close_until_response_body_is_consumed(
    monkeypatch,
    tmp_path,
):
    class Popup:
        url = "about:blank"

        def __init__(self):
            self.closed = False

        def wait_for_load_state(self, state, timeout=0):
            return None

        def content(self):
            raise RuntimeError("no HTML document")

        def is_closed(self):
            return self.closed

        def close(self):
            self.closed = True

    original = object()
    popup = Popup()
    context = SimpleNamespace(pages=[original, popup])
    monkeypatch.setattr(
        browser_route,
        "_resolve_page_challenge",
        lambda page, *, config: (
            ChallengeReport(kind=ChallengeKind.NONE),
            (ChallengeReport(kind=ChallengeKind.NONE),),
            False,
        ),
    )
    source = FullTextCandidate(
        doi="10.1000/defer-popup-close",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    browser_route._process_new_popup_pages(
        context,
        original_page=original,
        existing_page_ids={id(original)},
        source=source,
        output_dir=tmp_path,
        expected_title="Target article",
        config=BrowserAccessConfig(profile_root=tmp_path),
        close_pages=False,
    )

    assert popup.closed is False


def test_pdf_viewer_shell_triggers_bounded_same_origin_fetch():
    class ViewerPage:
        url = "https://cdn.example/article.pdf?signature=secret"

        def __init__(self):
            self.max_bytes = None

        def evaluate(self, script, max_bytes):
            assert "fetch(location.href" in script
            assert "cache: 'no-store'" in script
            self.max_bytes = max_bytes
            return True

    page = ViewerPage()

    assert (
        browser_route._trigger_pdf_viewer_same_origin_fetch(
            page,
            max_bytes=12_345,
        )
        is True
    )
    assert page.max_bytes == 12_345


def test_embedded_pdf_frame_triggers_bounded_same_origin_fetch():
    class Locator:
        def count(self):
            return 1

    class Frame:
        url = "https://publisher.example/doi/pdfdirect/10.1000/target"

        def locator(self, selector):
            assert "application/pdf" in selector
            return Locator()

    class Page:
        url = "https://publisher.example/doi/pdf/10.1000/target"

        def __init__(self, frame):
            self.frames = [frame]
            self.args = None

        def evaluate(self, script, args):
            assert "fetch(url" in script
            assert "cache: 'force-cache'" in script
            self.args = args
            return {
                "url": "https://publisher.example/doi/pdfdirect/10.1000/target",
                "bodyBase64": base64.b64encode(b"%PDF-test").decode("ascii"),
            }

    frame = Frame()
    page = Page(frame)

    assert browser_route._trigger_embedded_pdf_frame_fetch(
        page,
        max_bytes=54_321,
    ) == (
        "https://publisher.example/doi/pdfdirect/10.1000/target",
        b"%PDF-test",
    )
    assert page.args == {
        "url": "https://publisher.example/doi/pdfdirect/10.1000/target",
        "maxBytes": 54_321,
    }


def test_pdfdirect_response_is_captured_with_generic_content_type():
    response = SimpleNamespace(
        url="https://publisher.example/doi/pdfdirect/10.1000/target",
        headers={"content-type": "application/octet-stream"},
    )

    assert browser_route._response_is_pdf_candidate(response) is True


def test_ieee_runtime_document_url_requires_user_operated_access():
    source = FullTextCandidate(
        doi="10.1109/ICEET.2009.450",
        url="https://doi.org/10.1109/ICEET.2009.450",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    candidate = browser_route._runtime_publisher_pdf_candidate(
        source,
        "https://ieeexplore.ieee.org/document/5366888/",
    )

    assert candidate is None


def test_nature_runtime_article_url_yields_matching_pdf_candidate():
    source = FullTextCandidate(
        doi="10.1038/nature02863",
        url="https://doi.org/10.1038/nature02863",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    candidate = browser_route._runtime_publisher_pdf_candidate(
        source, "https://www.nature.com/articles/nature02863"
    )

    assert candidate is not None
    assert candidate.url == "https://www.nature.com/articles/nature02863.pdf"
    assert candidate.url_type == CandidateUrlType.PDF
    assert (
        browser_route._runtime_publisher_pdf_candidate(
            source, "https://www.nature.com/articles/unrelated"
        )
        is None
    )


def test_select_pdf_viewer_target_matches_expected_article_title():
    targets = [
        {
            "type": "webview",
            "title": "Unrelated Paper",
            "url": (
                "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/"
                "edge_pdf/index.html"
            ),
        },
        {
            "type": "webview",
            "title": "Ceramic Fuel Cells",
            "url": (
                "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/"
                "edge_pdf/index.html"
            ),
        },
    ]

    selected = browser_route._select_pdf_viewer_target(
        targets,
        doi="10.1111/j.1151-2916.1993.tb03645.x",
        expected_title="Ceramic Fuel Cells",
        page_title=(
            "Ceramic Fuel Cells - Minh - Journal of the American Ceramic Society"
        ),
        page_url=(
            "https://ceramics.onlinelibrary.wiley.com/doi/pdf/"
            "10.1111/j.1151-2916.1993.tb03645.x"
        ),
    )

    assert selected is targets[1]


def test_select_pdf_viewer_target_rejects_unrelated_webview():
    selected = browser_route._select_pdf_viewer_target(
        [
            {
                "type": "webview",
                "title": "Completely Different Paper",
                "url": (
                    "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/"
                    "edge_pdf/index.html"
                ),
            }
        ],
        doi="10.1111/j.1151-2916.1993.tb03645.x",
        expected_title="Ceramic Fuel Cells",
        page_title="Ceramic Fuel Cells - Wiley Online Library",
        page_url=(
            "https://ceramics.onlinelibrary.wiley.com/doi/pdf/"
            "10.1111/j.1151-2916.1993.tb03645.x"
        ),
    )

    assert selected is None


def test_select_pdf_viewer_target_matches_doi_filename_on_signed_cdn():
    target = {
        "type": "webview",
        "title": "d6ta02244h.pdf",
        "url": (
            "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/edge_pdf/index.html"
        ),
    }

    selected = browser_route._select_pdf_viewer_target(
        [target],
        doi="10.1039/D6TA02244H",
        expected_title=(
            "Capacitive deionization for targeted anion removal: mechanisms, "
            "advances, and future directions"
        ),
        page_title="d6ta02244h.pdf",
        page_url=(
            "https://rsci.silverchair-cdn.com/rsci/content_public/journal/ta/"
            "14/32/10.1039_d6ta02244h/1/d6ta02244h.pdf?signature=redacted"
        ),
    )

    assert selected is target


def test_institution_chooser_is_treated_as_sso_handoff(tmp_path):
    events = []
    page = _Page(
        [
            (
                "Choose your institution",
                "https://publisher.example/institution",
                "Choose your institution",
                "<main>Choose your institution</main>",
            ),
            (
                "Article",
                "https://publisher.example/article",
                "Article abstract",
                "<main>Article abstract</main>",
            ),
        ]
    )

    report, history, interaction_used = _resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            auto_challenge_grace=0,
            interaction_timeout=0.01,
            poll_interval=0.001,
            interaction_callback=lambda challenge, url: events.append(
                (challenge.kind, url)
            ),
        ),
    )

    assert events == [
        (
            ChallengeKind.SSO,
            "https://publisher.example/institution",
        )
    ]
    assert report.kind == ChallengeKind.NONE
    assert history[0].kind == ChallengeKind.SSO
    assert history[-1].kind == ChallengeKind.NONE
    assert interaction_used is True
