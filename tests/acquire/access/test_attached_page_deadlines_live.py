"""A real, stalled old PDF cannot hold attached-page selection indefinitely."""

import io
import json
import os
import time

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access import browser as browser_module
from aletheia_nexus.acquire.access.browser_engine.observation import bounded_read
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="deadline smoke stalls only a synthetic PDF in a fresh, isolated browser",
)


@pytest.mark.parametrize("channel", [None, "msedge"])
def test_stalled_old_pdf_title_is_bounded_and_later_matching_article_survives(
    tmp_path, channel
):
    pytest.importorskip("playwright.sync_api")
    if channel == "msedge" and os.name != "nt":
        pytest.skip("real Edge deadline check requires Windows Edge")
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)
    config = BrowserAccessConfig(
        profile_root=tmp_path / "isolated-profile",
        profile_name="old-pdf-deadline",
        launch_mode="managed",
        channel=channel,
        executable_path=(
            os.environ.get("AN_TEST_BROWSER_EXECUTABLE") or fixed_portable_browser()
        )
        if channel is None
        else None,
        headless=False,
        interactive=False,
    )
    with BrowserSession(config) as session:
        context = session._ensure_started()
        context.set_offline(True)

        def fulfill(route):
            if route.request.url == "https://old.example/stale.pdf":
                route.fulfill(content_type="application/pdf", body=buffer.getvalue())
            elif route.request.url == "https://publisher.example/article":
                route.fulfill(
                    content_type="text/html",
                    body="<title>Exact target title</title><h1>Target article</h1>",
                )
            else:
                route.abort()

        context.route("**/*", fulfill)
        stale = context.new_page()
        stale.goto("https://old.example/stale.pdf", wait_until="domcontentloaded")
        target = context.new_page()
        target.goto("https://publisher.example/article")
        baseline = list(context.pages)
        control = context.new_cdp_session(stale)
        try:
            # Reproduce a renderer that cannot answer title(): no SDK monkey
            # patch, no unrelated browser and no network/authentication page.
            stale.evaluate(
                "() => {setTimeout(() => {while (true) {}}, 0); return true}"
            )
            target.wait_for_timeout(50)
            with pytest.raises(TimeoutError):
                bounded_read(stale, "title", timeout=0.05)
            started = time.monotonic()
            selected = browser_module._select_attached_page(
                context,
                preferred_url="https://publisher.example/doi/10.1000/target",
                expected_title="Exact target title",
                minimum_score=300,
            )
            elapsed = time.monotonic() - started
            assert selected is target and elapsed < 3.5
            assert list(context.pages) == baseline and not stale.is_closed()
            assert target.title() == "Exact target title"
            print(
                json.dumps(
                    {
                        "fixture": "same_profile_stalled_old_pdf_title",
                        "channel": channel or "chromium",
                        "network": "offline local fulfillment only",
                        "real_title_timeout_confirmed": True,
                        "selection_seconds": elapsed,
                        "same_original_title_match": True,
                        "pages_unchanged": True,
                    }
                )
            )
        finally:
            # Interrupt only the loop this test installed, then release only
            # its own temporary managed browser. A user's process is untouched.
            control.send("Runtime.terminateExecution")
            control.detach()
