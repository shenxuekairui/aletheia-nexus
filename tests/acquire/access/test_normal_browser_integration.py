"""Opt-in visible browser test; only a fresh, test-owned profile is touched."""

import os
from pathlib import Path

import pytest

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserSession,
    browser_route,
)
from aletheia_nexus.acquire.access.browser_engine.launcher import _active_endpoint
from aletheia_nexus.acquire.access.models import BrowserFileAttempt
from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus

pytestmark = pytest.mark.skipif(
    os.environ.get("AN_RUN_VISIBLE_BROWSER_SMOKE") != "1",
    reason="ordinary-launch test opens a visible, isolated AN browser",
)


def test_normal_browser_downloads_reconnects_and_preserves_session(
    tmp_path, monkeypatch
):
    from playwright.sync_api import sync_playwright

    config = BrowserAccessConfig(
        profile_root=tmp_path / "profiles",
        interactive=False,
        navigation_timeout=15,
        request_timeout=5,
    )
    body = (
        Path(__file__).parents[3] / "benchmarks/v07_fixtures/native_article.pdf"
    ).read_bytes()
    doi = "10.5555/an.v07.native"
    title = "A Self-Authored Study of Traceable Parsing"
    endpoints = []
    profile = None
    downloads = []

    # Enforce the native control path in this fixture; response delivery is
    # valid too, but must not mask regressions in persistent CDP downloads.
    monkeypatch.setattr(
        browser_route,
        "_browser_response_to_file_attempt",
        lambda *args, **kwargs: BrowserFileAttempt(
            candidate=kwargs["parent"], error="Fixture excludes response capture"
        ),
    )
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *args, **kwargs: None
    )

    def respond(route):
        if route.request.url.endswith("/article.pdf"):
            downloads.append(route.request.url)
            route.fulfill(
                content_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=article.pdf"},
                body=body,
            )
        else:
            route.fulfill(
                content_type="text/html",
                body=f"<title>{title}</title><h1>{title}</h1>"
                f"<p>DOI: {doi}</p>"
                "<button onclick=\"location.href='/article.pdf'\">Download PDF</button>",
            )

    try:
        for client_index in range(2):
            with BrowserSession(config) as session:
                profile = session.profile_dir
                context = session._ensure_started()
                endpoints.append(_active_endpoint(profile))
                assert endpoints[-1]
                context.route("https://publisher.example/**", respond)
                if client_index == 0:
                    # Synthetic cookie and in-memory page state, not user credentials.
                    context.add_cookies(
                        [
                            {
                                "name": "an_fixture",
                                "value": "retained",
                                "url": "https://publisher.example",
                            }
                        ]
                    )
                    original = context.pages[0]
                    original.evaluate("window.anFixture = 'retained'")
                else:
                    assert context.pages[0].evaluate("window.anFixture") == "retained"
                    assert any(
                        c["name"] == "an_fixture" and c["value"] == "retained"
                        for c in context.cookies("https://publisher.example")
                    )
                for index in range(2):
                    outcome = session.acquire(
                        doi=doi,
                        expected_title=title,
                        routes=[
                            FullTextCandidate(
                                doi=doi,
                                url="https://publisher.example/article",
                                provenance=(),
                            )
                        ],
                        output_dir=tmp_path / f"out-{client_index}-{index}",
                    )
                    assert outcome.verified_result is not None, outcome
                    assert outcome.verified_result.status == AcquisitionStatus.VERIFIED
                    assert outcome.verified_result.file_path.read_bytes() == body
                    assert any(
                        f.method in {"browser_download", "cdp_browser_download"}
                        and f.result is not None
                        and f.result.status == AcquisitionStatus.VERIFIED
                        for attempt in outcome.attempts
                        for f in attempt.file_attempts
                    ), outcome
                context.unroute("https://publisher.example/**", respond)
            # The client exited, but the very same browser must still be alive.
            assert _active_endpoint(profile) == endpoints[-1]
        assert endpoints[0] == endpoints[1]
        assert len(downloads) == 4
    finally:
        # Close only the fresh browser created by THIS test, never a user's AN window.
        if profile is not None and (endpoint := _active_endpoint(profile)):
            with sync_playwright() as playwright:
                instance = playwright.chromium.connect_over_cdp(endpoint)
                cdp = instance.new_browser_cdp_session()
                cdp.send("Browser.close")
