"""Opt-in real Chromium regression; all HTML and requests are fulfilled locally.

This tests an ordinary button submission, not any publisher's CAPTCHA. Neither
case uses user profiles, credentials, external URLs, nor challenge automation.
"""

import json
import os
import time
from threading import Event

import pytest

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser
from aletheia_nexus.workbench.jobs import TaskManager

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="real Chromium human-wait regression is opt-in; uses only local fixture HTML",
)


@pytest.mark.parametrize("pumped", [False, True], ids=["legacy-blocking", "event-pump"])
def test_ordinary_submit_completes_before_ui_continue_only_with_event_pump(
    tmp_path, pumped
):
    pytest.importorskip("playwright.sync_api")
    manager = TaskManager(tmp_path / "tasks")
    waiting, submitted = Event(), Event()
    observations = []
    fixture_origin = "https://an-interaction.example.test"

    def work(context):
        config = BrowserAccessConfig(
            profile_root=tmp_path / "fresh-profile",
            executable_path=os.environ.get("AN_TEST_BROWSER_EXECUTABLE")
            or fixed_portable_browser(),
            launch_mode="managed",
            headless=True,
            interactive=False,
            navigation_timeout=10,
        )
        with BrowserSession(config) as session:
            browser_context = session._ensure_started()

            def fixture(route):
                path = route.request.url.removeprefix(fixture_origin)
                if path == "/completed":
                    route.fulfill(body="complete", content_type="text/plain")
                    submitted.set()
                elif path == "/submit":
                    assert route.request.method == "POST"
                    route.fulfill(body="accepted", content_type="text/plain")
                else:
                    route.fulfill(
                        content_type="text/html",
                        body="""<!doctype html><title>Local ordinary form fixture</title>
                        <button id="submit">Submit a normal request</button>
                        <script>document.querySelector('#submit').onclick = async () => {
                          await fetch('/submit', {method: 'POST', body: 'fixture'});
                          await fetch('/completed');
                        };</script>""",
                    )

            # This fixture never continues a request to a network. Production URL
            # guards remain installed; only this exact test origin is fulfilled.
            browser_context.route(fixture_origin + "/**", fixture)
            page = browser_context.new_page()
            page.goto(fixture_origin + "/form", wait_until="domcontentloaded")
            page.evaluate(
                "setTimeout(() => document.querySelector('#submit').click(), 200)"
            )
            waiting.set()
            action = context.wait_interaction(
                {"stage": "ordinary_local_form"},
                timeout=6,
                pump=session.pump_events if pumped else None,
            )
            observed = submitted.is_set()
            observations.append(
                {
                    "mode": "event-pump" if pumped else "legacy-blocking",
                    "submitted_before_continue": observed,
                    "browser_version": browser_context.browser.version,
                }
            )
            return {"decision": action, "submitted_before_continue": observed}

    try:
        job = manager.submit("fixture", "local form submission", [], work)
        startup_deadline = time.monotonic() + 20
        while not waiting.wait(0.05):
            receipt = manager.get(job["id"])
            assert receipt["status"] not in {"FAILED", "CANCELLED"}, receipt
            assert time.monotonic() < startup_deadline, receipt
        if pumped:
            assert submitted.wait(4), "the dispatcher stalled during the human wait"
        else:
            assert not submitted.wait(0.75), (
                "legacy blocking unexpectedly serviced events"
            )
        manager.control(job["id"], "continue")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            receipt = manager.get(job["id"])
            if receipt["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.01)
        assert receipt["status"] == "COMPLETED", receipt
        assert receipt["result"]["submitted_before_continue"] is pumped
        assert receipt["result"]["decision"] == "continue"
        print(json.dumps(observations[0], ensure_ascii=False))
    finally:
        manager.close(wait=True)
