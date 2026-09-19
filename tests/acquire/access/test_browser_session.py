from aletheia_nexus.acquire.access import browser
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
)
from aletheia_nexus.acquire.discovery.models import FullTextCandidate


class _Page:
    def __init__(self):
        self.closed = False

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class _Context:
    def __init__(self):
        self.closed = False

    def set_default_timeout(self, value):
        self.timeout = value

    def new_page(self):
        return _Page()

    def close(self):
        self.closed = True


class _Chromium:
    def __init__(self, context):
        self.context = context

    def launch_persistent_context(self, **kwargs):
        self.kwargs = kwargs
        return self.context


class _Playwright:
    def __init__(self, context):
        self.chromium = _Chromium(context)


class _Manager:
    def __init__(self, context):
        self.playwright = _Playwright(context)

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc, tb):
        return False


def _candidate(index, *, doi="10.1000/session-limit", url=None):
    return FullTextCandidate(
        doi=doi,
        url=url or f"https://publisher.example/article/{index}",
        provenance=(),
    )


def test_browser_session_enforces_source_route_budget(monkeypatch, tmp_path):
    context = _Context()
    calls = []

    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: _Manager(context))

    def attempt(context_value, page, *, source, **kwargs):
        calls.append(source.url)
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    result = browser.acquire_with_browser(
        doi="10.1000/session-limit",
        routes=[_candidate(1), _candidate(2), _candidate(3)],
        output_dir=tmp_path / "downloads",
        config=BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            max_source_routes=2,
        ),
    )

    assert calls == [
        "https://publisher.example/article/1",
        "https://publisher.example/article/2",
    ]
    assert len(result.attempts) == 2
    assert result.verified_result is None
    assert context.closed is True



def test_all_unsafe_routes_do_not_start_browser(monkeypatch, tmp_path):
    def should_not_load_playwright():
        raise AssertionError("unsafe-only recovery must not start Playwright")

    monkeypatch.setattr(browser, "_load_playwright", should_not_load_playwright)

    session = browser.BrowserSession(
        BrowserAccessConfig(profile_root=tmp_path / "profiles")
    )
    result = session.acquire(
        doi="10.1000/session-limit",
        routes=[
            _candidate(
                1,
                url="http://127.0.0.1/private.pdf",
            )
        ],
        output_dir=tmp_path / "downloads",
    )

    assert session.active is False
    assert len(result.attempts) == 1
    assert result.attempts[0].status == BrowserAttemptStatus.UNSAFE_URL
    assert result.verified_result is None
