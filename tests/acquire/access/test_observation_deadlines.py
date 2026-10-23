import asyncio
import os
import time

import pytest

from aletheia_nexus.acquire.access import browser_route
from aletheia_nexus.acquire.access.browser_engine.observation import _with_deadline
from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport


def test_unreadable_page_never_requests_human_login(monkeypatch):
    from aletheia_nexus.acquire.access import BrowserAccessConfig
    from aletheia_nexus.acquire.access.models import BrowserAttemptStatus

    class Page:
        url = "https://publisher.example/article"

        def is_closed(self):
            return False

        def wait_for_timeout(self, ms):
            time.sleep(ms / 1000)

    unavailable = ChallengeReport(
        ChallengeKind.UNKNOWN, (browser_route._OBSERVATION_UNAVAILABLE,)
    )
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: unavailable)
    notices = []
    report, history, used = browser_route._resolve_page_challenge(
        Page(),
        config=BrowserAccessConfig(
            interactive=True,
            wait_for_interaction=True,
            auto_challenge_grace=0.03,
            poll_interval=0.01,
            interaction_callback=lambda *args: notices.append(args),
        ),
    )
    assert report == unavailable
    assert history and not used and not notices
    assert (
        browser_route._status_from_challenge(report)
        == BrowserAttemptStatus.RETRIEVAL_FAILED
    )


@pytest.mark.parametrize("pdf", [True, False])
def test_browser_mime_distinguishes_native_pdf_from_html_gate(
    browser_page, monkeypatch, pdf
):
    from io import BytesIO

    from pypdf import PdfWriter

    page = browser_page
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    data = BytesIO()
    writer.write(data)
    page.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="application/pdf" if pdf else "text/html",
            body=data.getvalue()
            if pdf
            else '<title>Log In</title><p>Please log in to access this article</p><label>Username</label><input><label>Password</label><input type="password">',
        ),
    )
    page.goto("https://publisher.example/article.pdf", wait_until="commit")
    if not pdf:
        page.wait_for_load_state("domcontentloaded")
    if pdf:
        # Reproduce an unusable JS execution context while protocol metadata
        # still identifies the browser's native document.
        monkeypatch.setattr(
            browser_route, "_SNAPSHOT_SCRIPT", "() => new Promise(() => {})"
        )
        monkeypatch.setattr(browser_route, "_OBSERVATION_TIMEOUT", 0.2)
    report = browser_route._report_for_page(page)
    if not pdf:
        assert report.kind == ChallengeKind.AUTHENTICATION
        return
    assert report.kind == ChallengeKind.NONE
    assert browser_route._NATIVE_PDF in report.evidence


def test_native_pdf_is_not_blocked_by_stale_child_frame(browser_page, monkeypatch):
    from io import BytesIO

    from pypdf import PdfWriter

    page = browser_page
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    data = BytesIO()
    writer.write(data)
    page.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="application/pdf", body=data.getvalue()
        ),
    )
    page.goto("https://publisher.example/document.pdf", wait_until="commit")
    monkeypatch.setattr(
        type(page), "frames", property(lambda p: [p.main_frame, object()])
    )
    result = browser_route._report_for_page(page)
    assert result.kind == ChallengeKind.NONE
    history = []
    report = browser_route._wait_until_challenge_changes(
        page,
        initial=ChallengeReport(ChallengeKind.CAPTCHA),
        seconds=3,
        poll_interval=0.01,
        history=history,
    )
    assert report.kind == ChallengeKind.NONE
    assert browser_route._NATIVE_PDF in report.evidence


def test_deadline_does_not_wait_for_stalled_cancellation_cleanup():
    async def scenario():
        cleanup = asyncio.Event()
        cancelled = asyncio.Event()

        async def operation():
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
                await cleanup.wait()

        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await _with_deadline(operation(), 0.05)
        assert time.monotonic() - started < 1
        await asyncio.wait_for(cancelled.wait(), 1)
        cleanup.set()
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_unreadable_observation_preserves_login_until_real_clearance(monkeypatch):
    class Page:
        url = "https://publisher.example/article"
        polls = 0

        def is_closed(self):
            return False

        def wait_for_timeout(self, ms):
            self.polls += 1
            assert self.polls < 10

    page = Page()
    initial = ChallengeReport(ChallengeKind.SSO)
    unavailable = ChallengeReport(
        ChallengeKind.UNKNOWN, (browser_route._OBSERVATION_UNAVAILABLE,)
    )
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda p: unavailable if p.polls <= 2 else ChallengeReport(ChallengeKind.NONE),
    )
    monkeypatch.setattr(
        browser_route,
        "_page_snapshot",
        lambda p: ("Article", p.url, "Article abstract", ""),
    )
    notices = []
    history = []
    report = browser_route._wait_until_challenge_changes(
        page,
        initial=initial,
        seconds=None,
        poll_interval=0.01,
        history=history,
        interaction_callback=lambda *args: notices.append(args),
    )
    assert report.kind == ChallengeKind.NONE
    assert page.polls == 6  # two failed reads, then four stable clear observations
    assert not notices
    assert unavailable in history


def test_failed_clearance_snapshot_can_still_be_cancelled_by_user(monkeypatch):
    class Page:
        url = "https://publisher.example/article"
        polls = 0

        def is_closed(self):
            return self.polls >= 2

        def wait_for_timeout(self, ms):
            self.polls += 1

    def failed_snapshot(page):
        raise TimeoutError()

    monkeypatch.setattr(
        browser_route, "_report_for_page", lambda p: ChallengeReport(ChallengeKind.NONE)
    )
    monkeypatch.setattr(browser_route, "_page_snapshot", failed_snapshot)
    initial = ChallengeReport(ChallengeKind.CAPTCHA)
    report = browser_route._wait_until_challenge_changes(
        Page(),
        initial=initial,
        seconds=None,
        poll_interval=0.01,
        history=[],
    )
    assert report == initial


@pytest.mark.parametrize("external", [False, True])
def test_persistent_read_failure_ends_an_existing_human_wait(monkeypatch, external):
    from aletheia_nexus.acquire.access import BrowserAccessConfig

    class Page:
        url = "https://publisher.example/article"
        polls = 0

        def is_closed(self):
            return False

        def wait_for_timeout(self, ms):
            self.polls += 1
            assert self.polls < 8, "technical failure must not wait indefinitely"

    page = Page()
    unavailable = ChallengeReport(
        ChallengeKind.UNKNOWN, (browser_route._OBSERVATION_UNAVAILABLE,)
    )
    initial = ChallengeReport(ChallengeKind.SSO)
    monkeypatch.setattr(
        browser_route,
        "_report_for_page",
        lambda p: initial if p.polls == 0 else unavailable,
    )
    if external:
        report, _, used = browser_route._resolve_external_auth_page(
            page,
            source_host="publisher.example",
            config=BrowserAccessConfig(interactive=True, wait_for_interaction=True),
        )
        assert used
    else:
        report = browser_route._wait_until_challenge_changes(
            page,
            initial=initial,
            seconds=None,
            poll_interval=0.01,
            history=[],
        )
    assert report == unavailable
    assert page.polls == 3


def test_embedded_native_pdf_with_unreadable_js_does_not_block_article(
    browser_page, monkeypatch
):
    from io import BytesIO

    from pypdf import PdfWriter

    page = browser_page
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    data = BytesIO()
    writer.write(data)

    def respond(route):
        if route.request.url.endswith("document.pdf"):
            route.fulfill(content_type="application/pdf", body=data.getvalue())
        else:
            route.fulfill(
                content_type="text/html",
                body='<title>Article PDF</title><iframe src="/document.pdf"></iframe>',
            )

    page.route("**/*", respond)
    page.goto("https://publisher.example/article")
    frame = next(f for f in page.frames if f.url.endswith("document.pdf"))
    original = frame._impl_obj.evaluate

    async def stalled(*args, **kwargs):
        return await original("() => new Promise(() => {})")

    monkeypatch.setattr(frame._impl_obj, "evaluate", stalled)
    monkeypatch.setattr(browser_route, "_OBSERVATION_TIMEOUT", 0.2)
    assert browser_route._report_for_page(page).kind == ChallengeKind.NONE
    result = browser_route._wait_until_challenge_changes(
        page,
        initial=ChallengeReport(ChallengeKind.SSO),
        seconds=4,
        poll_interval=0.01,
        history=[],
        return_host="publisher.example",
    )
    assert result.kind == ChallengeKind.NONE


@pytest.fixture
def browser_page():
    if os.environ.get("AN_RUN_BROWSER_SMOKE") != "1":
        pytest.skip("requires real Chromium")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        yield page
        browser.close()


def test_real_browser_never_resolving_read_times_out_and_connection_recovers(
    browser_page, monkeypatch
):
    page = browser_page
    page.set_content("<title>Article</title><main>Article abstract</main>")
    with monkeypatch.context() as patch:
        patch.setattr(browser_route, "_SNAPSHOT_SCRIPT", "() => new Promise(() => {})")
        patch.setattr(browser_route, "_OBSERVATION_TIMEOUT", 0.2)
        start = time.monotonic()
        assert browser_route._report_for_page(page).kind == ChallengeKind.UNKNOWN
        assert time.monotonic() - start < 2
    assert browser_route._report_for_page(page).kind == ChallengeKind.NONE
    assert page.title() == "Article"


@pytest.mark.parametrize("stalled_step", ["evaluate", "frame_element"])
def test_real_visible_frame_read_failure_is_bounded_and_does_not_clear_login(
    browser_page, monkeypatch, stalled_step
):
    page = browser_page
    page.set_content(
        '<title>Article</title><p>Article abstract</p><iframe srcdoc="&lt;title&gt;Choose your institution&lt;/title&gt;&lt;p&gt;Choose your institution&lt;/p&gt;"></iframe>'
    )
    frame = page.frames[1]
    original_evaluate = frame._impl_obj.evaluate

    async def stalled(*args, **kwargs):
        # A genuinely unfinished browser protocol operation, not time.sleep.
        return await original_evaluate("() => new Promise(() => {})")

    with monkeypatch.context() as patch:
        patch.setattr(frame._impl_obj, stalled_step, stalled)
        patch.setattr(browser_route, "_OBSERVATION_TIMEOUT", 0.2)
        start = time.monotonic()
        assert browser_route._report_for_page(page).kind == ChallengeKind.UNKNOWN
        assert time.monotonic() - start < 2
    assert browser_route._report_for_page(page).kind == ChallengeKind.SSO
    assert not page.is_closed()


def test_multiple_stalled_frames_share_one_scan_budget(browser_page, monkeypatch):
    page = browser_page
    page.set_content(
        "<title>Article</title><p>Abstract</p>"
        + '<iframe srcdoc="Loading"></iframe>' * 8
    )
    for frame in page.frames[1:]:
        original_evaluate = frame._impl_obj.evaluate

        async def stalled(*args, original=original_evaluate, **kwargs):
            return await original("() => new Promise(() => {})")

        monkeypatch.setattr(frame._impl_obj, "evaluate", stalled)
    monkeypatch.setattr(browser_route, "_OBSERVATION_TIMEOUT", 0.25)
    monkeypatch.setattr(browser_route, "_FRAME_SCAN_TIMEOUT", 0.4)
    start = time.monotonic()
    assert browser_route._report_for_page(page).kind == ChallengeKind.UNKNOWN
    assert time.monotonic() - start < 1.5
