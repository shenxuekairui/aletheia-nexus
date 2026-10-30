"""Opt-in real local DOM transition; never a real CAPTCHA or publisher session."""

import os
from threading import get_ident

import pytest

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser
from aletheia_nexus.acquire.access.browser_route import _resolve_page_challenge
from aletheia_nexus.acquire.access.models import ChallengeKind

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="local Chromium observer smoke uses a fresh test-owned profile",
)


def test_real_local_dom_clearance_resumes_without_manual_continue(tmp_path):
    pytest.importorskip("playwright.sync_api")
    owner = get_ident()
    events, notices, requests = [], [], []
    page = None

    def notify(report, url):
        notices.append(report.kind)
        # This is deliberately synthetic ordinary HTML, not operating any
        # verification widget: emulate a person finishing a local form.
        page.evaluate(
            "setTimeout(() => {document.title='Local article ready';document.body.innerHTML='<h1>Local article ready</h1><p>Ordinary content after a local form.</p>';}, 150)"
        )

    def poll(event, report, url):
        assert get_ident() == owner
        events.append((event, report.kind))

    config = BrowserAccessConfig(
        profile_root=tmp_path / "isolated-profile",
        profile_name="auto-resume-fixture",
        launch_mode="managed",
        executable_path=os.environ.get("AN_TEST_BROWSER_EXECUTABLE")
        or fixed_portable_browser(),
        headless=False,
        interactive=True,
        navigation_timeout=10,
        auto_challenge_grace=0,
        wait_for_interaction=False,
        interaction_timeout=3,
        poll_interval=0.025,
        interaction_callback=notify,
        interaction_poll_callback=poll,
    )
    with BrowserSession(config) as session:
        context = session._ensure_started()

        def fixture(route):
            requests.append(route.request.url)
            route.fulfill(
                content_type="text/html",
                body="<title>Local form fixture</title><h1>CAPTCHA verification</h1><p>Please verify you are human.</p>",
            )

        context.route("https://local-interaction.example/**", fixture)
        page = context.new_page()
        page.goto("https://local-interaction.example/form")
        report, history, used = _resolve_page_challenge(page, config=config)
        assert report.kind == ChallengeKind.NONE and used
        assert notices == [ChallengeKind.CAPTCHA]
        assert events[-1] == ("resolved", ChallengeKind.NONE)
        assert sum(event[0] == "poll" for event in events) >= 4
        assert history[-1].kind == ChallengeKind.NONE
        assert requests == ["https://local-interaction.example/form"]
