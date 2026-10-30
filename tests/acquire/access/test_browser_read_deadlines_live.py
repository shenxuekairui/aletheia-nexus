"""Real renderer stalls cannot bypass outer content/fetch/control deadlines."""

import io
import json
import os
import time

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserSession,
    cnki_runtime,
)
from aletheia_nexus.acquire.access.browser_engine import viewer
from aletheia_nexus.acquire.access.browser_engine.observation import bounded_read
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="read-deadline smoke uses only a stalled synthetic PDF in an isolated browser",
)


@pytest.mark.parametrize("channel", [None, "msedge"])
def test_stalled_pdf_content_fetch_and_controls_end_with_unknown_not_success(
    tmp_path, channel
):
    pytest.importorskip("playwright.sync_api")
    if channel == "msedge" and os.name != "nt":
        pytest.skip("real Edge renderer-stall check requires Windows Edge")
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)
    config = BrowserAccessConfig(
        profile_root=tmp_path / "isolated",
        profile_name="read-deadlines",
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
        url = "https://publisher.example/local.pdf"
        context.route(
            "**/*",
            lambda r: (
                r.fulfill(content_type="application/pdf", body=buffer.getvalue())
                if r.request.url == url
                else r.abort()
            ),
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        control = context.new_cdp_session(page)
        try:
            page.evaluate("() => {setTimeout(() => {while(true){}}, 50); return true}")
            time.sleep(0.1)
            began = time.monotonic()
            with pytest.raises(TimeoutError):
                bounded_read(page, "content", timeout=0.1)
            content_elapsed = time.monotonic() - began
            began = time.monotonic()
            assert (
                viewer.trigger_pdf_viewer_same_origin_fetch(
                    page, max_bytes=1000, validate_url=lambda value: value, timeout=0.1
                )
                is False
            )
            fetch_elapsed = time.monotonic() - began
            began = time.monotonic()
            assert cnki_runtime.first_visible(page, ["input"] * 20) is None
            controls_elapsed = time.monotonic() - began
            assert content_elapsed < 1 and fetch_elapsed < 1 and controls_elapsed < 3
            assert not page.is_closed() and page.url == url
            print(
                json.dumps(
                    {
                        "fixture": "stalled_pdf_outer_content_evaluate_control_deadlines",
                        "channel": channel or "chromium",
                        "network": "offline local fulfillment only",
                        "content_timeout_seconds": content_elapsed,
                        "fetch_failed_seconds": fetch_elapsed,
                        "controls_unknown_seconds": controls_elapsed,
                        "original_page_retained": True,
                    }
                )
            )
        finally:
            control.send("Runtime.terminateExecution")
            control.detach()
