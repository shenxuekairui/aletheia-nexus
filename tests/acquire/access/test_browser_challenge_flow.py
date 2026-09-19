from types import SimpleNamespace

from aletheia_nexus.acquire.access import browser_route
from aletheia_nexus.acquire.access.browser_route import _resolve_page_challenge
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
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


class _RouteContext:
    def __init__(self, page):
        self.pages = [page]


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
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda value: ChallengeReport(kind=ChallengeKind.SSO),
    )

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
    assert page.goto_calls == [
        "https://publisher.example/article",
        "https://publisher.example/article",
    ]
    assert result.status == BrowserAttemptStatus.NO_FILE_CANDIDATES
    assert [report.kind for report in result.challenge_history] == [
        ChallengeKind.SSO,
        ChallengeKind.NONE,
    ]
