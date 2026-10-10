import pytest

from aletheia_nexus.acquire.access import browser_route
from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport
from aletheia_nexus.acquire.access.security import redact_url_for_record


class _Page:
    def __init__(self, states):
        self.states = states
        self.index = -1

    @property
    def url(self):
        return self.states[max(self.index, 0)][1]

    def is_closed(self):
        return False

    def wait_for_timeout(self, milliseconds):
        self.index += 1
        assert self.index < len(self.states), "Wait did not finish on stable content"


def _wait(monkeypatch, states, **options):
    page = _Page(states)
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda page: ChallengeReport(kind=page.states[page.index][0]),
    )
    monkeypatch.setattr(
        browser_route,
        "_page_snapshot",
        lambda page: ("Page", page.url, "Page content", "<main />"),
    )
    initial = ChallengeReport(kind=ChallengeKind.CAPTCHA)
    history = [initial]
    notices = []
    report = browser_route._wait_until_challenge_changes(
        page,
        initial=initial,
        seconds=None,
        poll_interval=0.01,
        history=history,
        interaction_callback=lambda report, url: notices.append((report.kind, url)),
        **options,
    )
    return page, report, history, notices


def test_bot_captcha_churn_is_one_notification_gate(monkeypatch):
    url = "https://publisher.example/article"
    states = [
        (kind, url)
        for kind in (
            ChallengeKind.BOT_CHALLENGE,
            ChallengeKind.CAPTCHA,
            ChallengeKind.BOT_CHALLENGE,
            ChallengeKind.CAPTCHA,
            ChallengeKind.SSO,
            ChallengeKind.MFA,
            ChallengeKind.CAPTCHA,
            ChallengeKind.BOT_CHALLENGE,
            *([ChallengeKind.NONE] * 4),
        )
    ]
    _, report, _, notices = _wait(monkeypatch, states)
    assert report.kind == ChallengeKind.NONE
    assert [kind for kind, _ in notices] == [
        ChallengeKind.SSO,
        ChallengeKind.MFA,
        ChallengeKind.CAPTCHA,
    ]


def test_redirect_documents_do_not_count_as_stable_clearance(monkeypatch):
    states = [
        (ChallengeKind.NONE, f"https://publisher.example/redirect/{i}")
        for i in range(4)
    ]
    states += [(ChallengeKind.CAPTCHA, "https://publisher.example/challenge")]
    states += [(ChallengeKind.NONE, "https://publisher.example/article")] * 4
    page, report, _, _ = _wait(monkeypatch, states)
    assert report.kind == ChallengeKind.NONE
    assert page.index == len(states) - 1


def test_pdf_wait_does_not_clear_on_unrecognized_external_login(monkeypatch):
    states = [(ChallengeKind.SSO, "https://publisher.example/action/ssostart")]
    states += [(ChallengeKind.NONE, "https://accounts.example/continue")] * 8
    states += [(ChallengeKind.NONE, "https://publisher.example/article")] * 4
    page, report, history, _ = _wait(
        monkeypatch, states, return_host="publisher.example"
    )
    assert page.index == len(states) - 1
    assert report.kind == ChallengeKind.NONE
    assert all(item.kind != ChallengeKind.NONE for item in history[:-1])


def test_non_auth_pdf_cdn_transition_can_clear_challenge(monkeypatch):
    states = [(ChallengeKind.NONE, "https://cdn.example/paper.pdf")] * 4
    _, report, _, _ = _wait(monkeypatch, states, return_host="publisher.example")
    assert report.kind == ChallengeKind.NONE


def test_authentication_paths_recognize_matrix_parameters_not_article_queries():
    assert browser_route._authentication_navigation(
        "https://idp.example/login;jsessionid=private"
    )
    assert browser_route._authentication_navigation(
        "https://idp.example/SSO;sessionid=private"
    )
    assert not browser_route._authentication_navigation(
        "https://publisher.example/doi/10.1000/test?redirect=/login"
    )


def test_indefinite_wait_history_is_bounded_preserving_first_and_latest():
    first = ChallengeReport(kind=ChallengeKind.SSO)
    history = [first]
    for i in range(1000):
        report = ChallengeReport(kind=ChallengeKind.CAPTCHA, evidence=(str(i),))
        browser_route._append_report(history, report)
    assert len(history) == 64
    assert history[0] == first
    assert history[-1] == report


def test_challenge_path_tickets_are_redacted_without_changing_article_paths():
    url = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/pat/private-ticket?ray=secret"
    safe = redact_url_for_record(url)
    assert (
        safe
        == "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/[redacted]?ray=%5Bredacted%5D"
    )
    assert "private-ticket" not in safe
    article = "https://publisher.example/journal/article.pdf"
    assert redact_url_for_record(article) == article


@pytest.mark.parametrize("mime_type", ["application/pdf", "text/html"])
def test_empty_extensionless_pdf_document_can_finish_wait_but_html_cannot(
    monkeypatch, mime_type
):
    page = _Page(
        [(ChallengeKind.NONE, "https://publisher.example/doi/pdf/10.1/test")] * 5
    )
    monkeypatch.setattr(page, "evaluate", lambda expression: mime_type, raising=False)
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda page: ChallengeReport(kind=ChallengeKind.NONE),
    )
    monkeypatch.setattr(
        browser_route, "_page_snapshot", lambda page: ("", page.url, "", "")
    )
    initial = ChallengeReport(kind=ChallengeKind.CAPTCHA)
    result = browser_route._wait_until_challenge_changes(
        page, initial=initial, seconds=None, poll_interval=0.01, history=[initial]
    )
    assert result.kind == (
        ChallengeKind.NONE if mime_type == "application/pdf" else ChallengeKind.CAPTCHA
    )
    if mime_type == "application/pdf":
        assert page.index == 3
