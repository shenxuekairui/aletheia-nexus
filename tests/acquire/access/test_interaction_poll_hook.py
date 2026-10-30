"""A cooperative hook observes existing clearance rules without replacing them."""

import threading
import time

import pytest

from aletheia_nexus.acquire.access import browser_route, cnki_runtime
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    ChallengeKind,
    ChallengeReport,
)


class Skip(BaseException):
    pass


class Cancel(BaseException):
    pass


class Page:
    def __init__(self, states):
        self.states = states
        self.index = 0
        self.waits = []

    @property
    def url(self):
        return self.states[self.index][0]

    def is_closed(self):
        return False

    def opener(self):
        return None

    def wait_for_timeout(self, delay):
        self.waits.append(delay)
        self.index = min(self.index + 1, len(self.states) - 1)


def observe(monkeypatch, page):
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda p: ChallengeReport(p.states[p.index][1]),
    )
    monkeypatch.setattr(
        browser_route,
        "_page_snapshot",
        lambda p: (
            "Usable article",
            p.url,
            "Visible article content",
            "<p>Article</p>",
        ),
    )


def test_generic_hook_waits_for_four_stable_observations_and_preserves_callback(
    monkeypatch,
):
    page = Page(
        [
            (
                "https://publisher.example/check?token=private-secret",
                ChallengeKind.CAPTCHA,
            ),
            ("https://publisher.example/article", ChallengeKind.NONE),
        ]
    )
    observe(monkeypatch, page)
    events, notices = [], []
    owner = threading.get_ident()

    def hook(event, report, url):
        assert threading.get_ident() == owner
        assert "private-secret" not in url
        events.append((event, report.kind, len(page.waits)))

    result, history, used = browser_route._resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            auto_challenge_grace=0,
            wait_for_interaction=True,
            poll_interval=0.001,
            interaction_callback=lambda report, url: notices.append((report.kind, url)),
            interaction_poll_callback=hook,
        ),
    )
    assert result.kind == ChallengeKind.NONE and used
    assert len(notices) == 1 and notices[0][0] == ChallengeKind.CAPTCHA
    assert events[-1] == ("resolved", ChallengeKind.NONE, 4)
    assert sum(event[0] == "resolved" for event in events) == 1
    assert history[-1].kind == ChallengeKind.NONE


def test_generic_verified_delivery_uses_existing_completion_check(monkeypatch):
    page = Page([("https://publisher.example/check", ChallengeKind.CAPTCHA)])
    observe(monkeypatch, page)
    events = []
    result = browser_route._wait_until_challenge_changes(
        page,
        initial=ChallengeReport(ChallengeKind.CAPTCHA),
        seconds=1,
        poll_interval=0.001,
        history=[],
        completion_check=lambda: len(page.waits) == 2,
        interaction_poll_callback=lambda event, report, url: events.append(
            (event, report.kind)
        ),
    )
    assert result.kind == ChallengeKind.NONE
    assert "Verified target article delivered" in result.evidence[0]
    assert events[-1] == ("resolved", ChallengeKind.NONE) and len(page.waits) == 2


@pytest.mark.parametrize("signal", [Skip, Cancel])
@pytest.mark.parametrize("waiter", ["generic", "institution", "cnki"])
def test_control_baseexceptions_escape_all_waiters_without_false_resolution(
    monkeypatch, signal, waiter
):
    page = Page(
        [("https://identity.example/login?token=private-secret", ChallengeKind.SSO)]
    )
    events = []

    def hook(event, report, url):
        events.append(event)
        if event == "poll":
            raise signal("user control")

    config = BrowserAccessConfig(
        auto_challenge_grace=0,
        wait_for_interaction=True,
        interaction_poll_callback=hook,
    )
    observe(monkeypatch, page)
    monkeypatch.setattr(
        cnki_runtime,
        "challenge_for_page",
        lambda p: ChallengeReport(ChallengeKind.CAPTCHA),
    )
    with pytest.raises(signal):
        if waiter == "generic":
            browser_route._resolve_page_challenge(page, config=config)
        elif waiter == "institution":
            browser_route._resolve_external_auth_page(
                page, source_host="publisher.example", config=config
            )
        else:
            cnki_runtime.CNKIGate(config).check(page)
    assert events == ["poll"]


def test_poll_error_is_not_swallowed_as_a_page_read_failure(monkeypatch):
    page = Page([("https://publisher.example/check", ChallengeKind.CAPTCHA)])
    observe(monkeypatch, page)

    def failed(event, report, url):
        raise RuntimeError("cooperative control failed")

    with pytest.raises(RuntimeError, match="cooperative control failed"):
        browser_route._resolve_page_challenge(
            page,
            config=BrowserAccessConfig(
                auto_challenge_grace=0, interaction_poll_callback=failed
            ),
        )


def test_institution_hook_resolves_only_after_stable_return_to_same_publisher(
    monkeypatch,
):
    page = Page(
        [
            ("https://identity.example/login", ChallengeKind.SSO),
            ("https://identity.example/complete", ChallengeKind.NONE),
            ("https://publisher.example/article", ChallengeKind.NONE),
        ]
    )
    observe(monkeypatch, page)
    events = []
    result, _, used = browser_route._resolve_external_auth_page(
        page,
        source_host="publisher.example",
        config=BrowserAccessConfig(
            wait_for_interaction=True,
            poll_interval=0.001,
            interaction_poll_callback=lambda event, report, url: events.append(
                (event, report.kind, url)
            ),
        ),
    )
    assert result.kind == ChallengeKind.NONE and used
    assert events[-1] == (
        "resolved",
        ChallengeKind.NONE,
        "https://publisher.example/article",
    )
    assert len(page.waits) >= 5


def test_timeout_resolution_does_not_claim_challenge_cleared(monkeypatch):
    page = Page([("https://publisher.example/check", ChallengeKind.CAPTCHA)])
    observe(monkeypatch, page)
    page.wait_for_timeout = lambda delay: time.sleep(0.001)
    events = []
    report = browser_route._wait_until_challenge_changes(
        page,
        initial=ChallengeReport(ChallengeKind.CAPTCHA),
        seconds=0.003,
        poll_interval=0.001,
        history=[],
        interaction_poll_callback=lambda event, report, url: events.append(
            (event, report.kind)
        ),
    )
    assert report.kind == ChallengeKind.CAPTCHA
    assert events[-1] == ("resolved", ChallengeKind.CAPTCHA)


def test_cnki_hook_requires_its_existing_double_render_ready_rule(monkeypatch):
    page = Page(
        [
            ("https://kns.cnki.net/detail", ChallengeKind.CAPTCHA),
            ("https://kns.cnki.net/detail", ChallengeKind.NONE),
        ]
    )
    sequence = iter([ChallengeKind.CAPTCHA, ChallengeKind.NONE, ChallengeKind.NONE])
    monkeypatch.setattr(
        cnki_runtime, "challenge_for_page", lambda p: ChallengeReport(next(sequence))
    )
    monkeypatch.setattr(cnki_runtime, "_resume_ready", lambda p: True)
    events, notices = [], []
    gate = cnki_runtime.CNKIGate(
        BrowserAccessConfig(
            wait_for_interaction=True,
            poll_interval=0.001,
            interaction_callback=lambda report, url: notices.append(report.kind),
            interaction_poll_callback=lambda event, report, url: events.append(
                (event, report.kind)
            ),
        )
    )
    assert gate.check(page) is True
    assert notices == [ChallengeKind.CAPTCHA]
    assert events == [
        ("poll", ChallengeKind.CAPTCHA),
        ("poll", ChallengeKind.CAPTCHA),
        ("resolved", ChallengeKind.NONE),
    ]


def test_cnki_hard_denial_resolution_preserves_original_failure(monkeypatch):
    page = Page([("https://kns.cnki.net/detail", ChallengeKind.ACCESS_DENIED)])
    monkeypatch.setattr(
        cnki_runtime,
        "challenge_for_page",
        lambda p: ChallengeReport(ChallengeKind.ACCESS_DENIED),
    )
    events = []
    gate = cnki_runtime.CNKIGate(
        BrowserAccessConfig(
            interaction_poll_callback=lambda event, report, url: events.append(
                (event, report.kind)
            )
        )
    )
    with pytest.raises(cnki_runtime.CNKIInteractionRequired) as failure:
        gate.check(page)
    assert failure.value.report.kind == ChallengeKind.ACCESS_DENIED
    assert events == [("resolved", ChallengeKind.ACCESS_DENIED)]


def test_missing_hook_is_legacy_compatible_and_no_hook_field_is_required(monkeypatch):
    config = BrowserAccessConfig(
        auto_challenge_grace=0, wait_for_interaction=True, poll_interval=0.001
    )
    assert config.interaction_poll_callback is None
    page = Page(
        [
            ("https://publisher.example/check", ChallengeKind.CAPTCHA),
            ("https://publisher.example/article", ChallengeKind.NONE),
        ]
    )
    observe(monkeypatch, page)
    result, _, _ = browser_route._resolve_page_challenge(page, config=config)
    assert result.kind == ChallengeKind.NONE
