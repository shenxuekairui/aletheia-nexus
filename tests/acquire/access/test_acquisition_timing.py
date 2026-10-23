import json
import os
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access.timing import AcquisitionTimer, install


def test_nested_times_and_interaction_are_not_double_counted(tmp_path):
    now = [0.0]
    timer = AcquisitionTimer(tmp_path / "events.jsonl", clock=lambda: now[0])
    try:
        with timer.span("paper", "paper", paper="10.1/example"):
            now[0] = 1
            with timer.span("gate", "access_gate"):
                now[0] = 2
                timer.notice("CAPTCHA")
                with timer.span("nested gate", "access_gate"):
                    now[0] = 3
                    timer.notice("SSO")
                    now[0] = 4
                now[0] = 5
            now[0] = 7
        report = timer.summary()["papers"][0]
        assert report["seconds"] == 7
        assert report["exclusive_categories"] == {"paper": 3, "access_gate": 4}
        assert report["accounting_delta"] == 0
        assert report["timing_valid"]
        assert report["interaction_window_seconds"] == 3
        assert report["outside_interaction_seconds"] == 4
    finally:
        timer.close()


def test_failure_and_pending_call_are_visible_without_arguments(tmp_path):
    timer = AcquisitionTimer(tmp_path / "events.jsonl")
    secret = "password=secret&captcha=1234"

    def failing(argument):
        timer.heartbeat()
        raise ValueError(argument)

    try:
        with pytest.raises(ValueError, match="password"):
            with timer.span("paper", "paper", paper="10.1/test"):
                timer.wrap(failing, "click")(secret)
        events = timer.path.read_text()
        assert secret not in events
        assert '"error_type": "ValueError"' in events
        heartbeat = next(
            json.loads(line)
            for line in events.splitlines()
            if json.loads(line)["event"] == "heartbeat"
        )
        assert heartbeat["pending"][0]["name"].endswith("failing")
        assert timer.summary()["incomplete_spans"] == []
    finally:
        timer.close()


def test_installer_covers_import_aliases_and_restores_them(tmp_path):
    SyncBase = pytest.importorskip(
        "playwright._impl._sync_base", reason="requires the optional browser extra"
    ).SyncBase

    from aletheia_nexus.acquire.access import artifact, browser_route
    from aletheia_nexus.acquire.fulltext import validation

    original = validation.inspect_pdf
    sync = SyncBase._sync
    timer = AcquisitionTimer(tmp_path / "events.jsonl")
    try:
        install(timer)
        assert artifact.inspect_pdf is validation.inspect_pdf
        assert validation.inspect_pdf is not original
        assert (
            browser_route.finalize_browser_resource
            is artifact.finalize_browser_resource
        )
    finally:
        timer.close()
    assert artifact.inspect_pdf is validation.inspect_pdf is original
    assert SyncBase._sync is sync


def test_interleaved_greenlets_do_not_corrupt_acquisition_stack(tmp_path):
    greenlets = pytest.importorskip(
        "greenlet", reason="requires the optional browser extra"
    )
    getcurrent, greenlet = greenlets.getcurrent, greenlets.greenlet

    now = [0.0]
    timer = AcquisitionTimer(tmp_path / "events.jsonl", clock=lambda: now[0])
    main = getcurrent()

    def callback():
        with timer.span("callback", "callback"):
            now[0] = 2
            main.switch()
            now[0] = 4

    try:
        with timer.span("paper", "paper", paper="10.1/test"):
            with timer.span("browser", "browser_evaluate"):
                now[0] = 1
                event = greenlet(callback)
                event.switch()
                now[0] = 3
            event.switch()
            now[0] = 5
        paper = timer.summary()["papers"][0]
        assert paper["exclusive_categories"] == {"paper": 2, "browser_evaluate": 3}
        assert paper["accounting_delta"] == 0
        assert all(s["name"] != "callback" for s in paper["spans"])
    finally:
        timer.close()


@pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="real Chromium smoke is enabled only in the browser-extra CI job",
)
def test_real_browser_calls_are_nested_and_do_not_record_page_content(tmp_path):
    from playwright.sync_api import sync_playwright

    from aletheia_nexus import cli
    from aletheia_nexus.acquire.access import browser_route
    from aletheia_nexus.acquire.access.models import ChallengeKind

    timer = AcquisitionTimer(tmp_path / "events.jsonl")
    try:
        install(timer)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                with timer.span("fixture", "paper", paper="10.1/fixture"):
                    # Exercise Playwright's separate callback greenlet.
                    page.route(
                        "https://example.test/**",
                        lambda route: route.fulfill(body="<p>ok</p>"),
                    )
                    page.goto("https://example.test/article")
                    page.set_content(
                        "<button onclick=\"this.textContent='done'\">secret-token</button>"
                    )
                    page.locator("button").click()
                    assert page.locator("button").inner_text() == "done"
                    browser_route._report_for_page(page)
                    with timer.span("test gate", "access_gate"):
                        cli._interaction_notice(
                            SimpleNamespace(kind=ChallengeKind.CAPTCHA),
                            "https://example.test/secret",
                        )
                        page.wait_for_timeout(20)
                    with pytest.raises(Exception):
                        page.locator("missing-secret-element").click(timeout=30)
            finally:
                browser.close()
        summary = timer.summary()["papers"][0]
        assert abs(summary["accounting_delta"]) < 1e-8
        assert summary["timing_valid"]
        assert summary["exclusive_categories"]["click"] > 0
        assert summary["interaction_window_seconds"] >= 0.02
        assert all(s["exclusive_seconds"] >= -1e-8 for s in summary["spans"])
        text = timer.path.read_text()
        assert "secret-token" not in text
        assert "missing-secret-element" not in text
        assert "https://example.test/secret" not in text
        assert '"error_type": "TimeoutError"' in text
    finally:
        timer.close()
