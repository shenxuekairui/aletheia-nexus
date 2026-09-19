from aletheia_nexus.acquire.access.browser_route import _resolve_page_challenge
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    ChallengeKind,
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
