"""Opt-in CDP/default-preservation test in a fresh, test-owned browser only."""

import io
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access.browser_engine.connection import (
    inspect_local_endpoint,
)
from aletheia_nexus.acquire.access.browser_engine.launcher import _active_endpoint
from aletheia_nexus.acquire.access.browser_engine.runtime import fixed_portable_browser
from aletheia_nexus.workbench.supplements_browser import SupplementBrowserTransport

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_BROWSER_SMOKE") != "1",
    reason="CDP preservation smoke launches only a fresh isolated headless browser",
)


def test_public_cdp_no_defaults_keeps_tabs_and_explicit_native_si_delivery(tmp_path):
    pytest.importorskip("playwright.sync_api")
    executable = (
        os.environ.get("AN_TEST_BROWSER_EXECUTABLE") or fixed_portable_browser()
    )
    if executable is None or not Path(executable).is_file():
        pytest.skip("No already installed fixed browser runtime is available")
    profile = tmp_path / "test-owned-browser"
    profile.mkdir()
    process = subprocess.Popen(
        [
            str(executable),
            "--headless=new",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "about:blank",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    endpoint = None
    config = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("The test-owned browser exited before exposing local CDP")
            endpoint = _active_endpoint(profile)
            if endpoint:
                break
            time.sleep(0.1)
        assert endpoint is not None, "The isolated browser did not expose local CDP"
        # Public configuration accepts HTTP origins; this is the endpoint of
        # the Popen above, never a registered user profile or running Edge.
        port = (profile / "DevToolsActivePort").read_text().splitlines()[0]
        config = BrowserAccessConfig(
            cdp_endpoint=f"http://127.0.0.1:{port}",
            profile_root=tmp_path / "test-client",
            interactive=False,
            headless=True,
            navigation_timeout=10,
        )
        doi = "10.1016/j.elecom.2022.107204"
        main = "https://www.sciencedirect.com/science/article/pii/S1388248122000066"
        attachment = (
            "https://ars.els-cdn.com/content/image/1-s2.0-S1388248122000066-mmc1.docx"
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr(
                "word/document.xml", "<document>Local SI fixture</document>"
            )
        body = output.getvalue()
        requests = []
        for attempt in range(2):
            with BrowserSession(config) as session:
                context = session._ensure_started()
                assert session.connection_diagnostic is None
                if attempt == 0:

                    def respond(route):
                        requests.append(route.request.url)
                        if route.request.url == attachment:
                            route.fulfill(
                                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                headers={
                                    "Content-Disposition": "attachment; filename=supplement.docx"
                                },
                                body=body,
                            )
                        else:
                            route.fulfill(
                                content_type="text/html",
                                body=f'<title>Local CDP fixture</title><meta name="citation_doi" content="{doi}">',
                            )

                    context.route("https://www.sciencedirect.com/**", respond)
                    context.route("https://ars.els-cdn.com/**", respond)
                    source = context.new_page()
                    source.goto(main)
                    source.evaluate("window.localFixture = 'preserved'")
                    original_urls = [page.url for page in context.pages]
                    adapter = SupplementBrowserTransport(session, doi=doi)
                    adapter.page_fetch(main)
                    resource = adapter.file_fetch(
                        attachment,
                        source_page=main,
                        extension=".docx",
                        output_dir=tmp_path / "output",
                        max_bytes=1024 * 1024,
                        timeout=10,
                    )
                    assert resource.local_path.read_bytes() == body
                    context.unroute("https://www.sciencedirect.com/**", respond)
                    context.unroute("https://ars.els-cdn.com/**", respond)
                else:
                    source = next(page for page in context.pages if page.url == main)
                assert [page.url for page in context.pages] == original_urls
                assert source.evaluate("window.localFixture") == "preserved"
            # Disconnecting AN leaves the exact owned browser and pages alive.
            assert _active_endpoint(profile) == endpoint
            assert inspect_local_endpoint(endpoint)["page_count"] == len(original_urls)
        assert requests == [main, attachment]
        print(
            json.dumps(
                {
                    "public_no_defaults": True,
                    "native_docx_delivery": True,
                    "reconnected": True,
                    "original_pages_preserved": len(original_urls),
                    "external_http": False,
                    "user_browser_touched": False,
                }
            )
        )
    finally:
        # This PID was created above in a fresh temporary profile. Never match
        # browser processes by executable name or touch any other browser PID.
        if process.poll() is None and config is not None:
            try:
                with BrowserSession(config) as cleanup:
                    cleanup._ensure_started().browser.new_browser_cdp_session().send(
                        "Browser.close"
                    )
            except Exception:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
