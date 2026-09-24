from aletheia_nexus.acquire.access import browser
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
)


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
    manager = _Manager(context)

    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

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
    assert manager.playwright.chromium.kwargs["service_workers"] == "allow"
    assert manager.playwright.chromium.kwargs["args"] == ["--no-proxy-server"]


def test_browser_session_can_opt_into_system_proxy(monkeypatch, tmp_path):
    context = _Context()
    manager = _Manager(context)
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    with browser.BrowserSession(
        BrowserAccessConfig(profile_root=tmp_path, use_system_proxy=True)
    ) as session:
        session._ensure_started()

    assert manager.playwright.chromium.kwargs["args"] == []


def test_browser_session_stops_after_interaction_required(monkeypatch, tmp_path):
    context = _Context()
    manager = _Manager(context)
    calls = []

    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page, *, source, **kwargs):
        calls.append(source.url)
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.INTERACTION_REQUIRED,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    result = browser.acquire_with_browser(
        doi="10.1000/session-limit",
        routes=[_candidate(1), _candidate(2)],
        output_dir=tmp_path / "downloads",
        config=BrowserAccessConfig(profile_root=tmp_path / "profiles"),
    )

    assert calls == ["https://publisher.example/article/1"]
    assert len(result.attempts) == 1
    assert result.attempts[0].status == BrowserAttemptStatus.INTERACTION_REQUIRED
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


def test_browser_session_reuses_one_live_context_across_dois(monkeypatch, tmp_path):
    context = _Context()
    manager = _Manager(context)
    launches = 0
    calls = []
    original_launch = manager.playwright.chromium.launch_persistent_context

    def launch_once(**kwargs):
        nonlocal launches
        launches += 1
        return original_launch(**kwargs)

    manager.playwright.chromium.launch_persistent_context = launch_once
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page, *, source, **kwargs):
        calls.append((context_value, source.doi))
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(profile_root=tmp_path / "profiles")
    ) as session:
        session.acquire(
            doi="10.1000/first",
            routes=[_candidate(1, doi="10.1000/first")],
            output_dir=tmp_path / "downloads",
        )
        assert session.active is True
        assert context.closed is False

        session.acquire(
            doi="10.1000/second",
            routes=[_candidate(2, doi="10.1000/second")],
            output_dir=tmp_path / "downloads",
        )
        assert context.closed is False

    assert launches == 1
    assert [doi for _, doi in calls] == ["10.1000/first", "10.1000/second"]
    assert all(context_value is context for context_value, _ in calls)
    assert context.closed is True


def test_all_unsafe_routes_return_without_starting_browser(monkeypatch, tmp_path):
    started = False

    def should_not_start():
        nonlocal started
        started = True
        raise AssertionError("browser should not start")

    monkeypatch.setattr(browser, "_load_playwright", should_not_start)
    unsafe = FullTextCandidate(
        doi="10.1000/session-limit",
        url="http://127.0.0.1/private.pdf",
        provenance=(),
    )

    result = browser.acquire_with_browser(
        doi="10.1000/session-limit",
        routes=[unsafe],
        output_dir=tmp_path / "downloads",
        config=BrowserAccessConfig(profile_root=tmp_path / "profiles"),
    )

    assert started is False
    assert len(result.attempts) == 1
    assert result.attempts[0].status == BrowserAttemptStatus.UNSAFE_URL


def test_unsafe_routes_also_consume_source_route_budget(monkeypatch, tmp_path):
    started = False

    def should_not_start():
        nonlocal started
        started = True
        raise AssertionError("browser should not start")

    monkeypatch.setattr(browser, "_load_playwright", should_not_start)
    routes = [
        _candidate(1, url="http://127.0.0.1/a"),
        _candidate(2, url="http://10.0.0.1/b"),
        _candidate(3, url="http://169.254.169.254/c"),
    ]

    result = browser.acquire_with_browser(
        doi="10.1000/session-limit",
        routes=routes,
        output_dir=tmp_path / "downloads",
        config=BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            max_source_routes=2,
        ),
    )

    assert started is False
    assert len(result.attempts) == 2
    assert all(
        attempt.status == BrowserAttemptStatus.UNSAFE_URL for attempt in result.attempts
    )


def test_browser_session_clears_route_event_buffers(monkeypatch, tmp_path):
    context = _Context()
    manager = _Manager(context)
    observed_starts = []

    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page, *, source, **kwargs):
        blocked = kwargs["session_blocked_urls"]
        responses = kwargs["session_pdf_responses"]
        downloads = kwargs["session_downloads"]
        observed_starts.append((len(blocked), len(responses), len(downloads)))
        blocked.append("https://blocked.example/")
        responses.append(object())
        downloads.append(object())
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(profile_root=tmp_path / "profiles")
    ) as session:
        session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1), _candidate(2)],
            output_dir=tmp_path / "downloads",
        )

        assert observed_starts == [(0, 0, 0), (0, 0, 0)]
        assert session._blocked_unsafe_urls == []
        assert session._pdf_responses == []
        assert session._downloads == []


class _FailingManager:
    def __enter__(self):
        raise RuntimeError(
            "failed at C:/Users/private/.aletheia-nexus/profile?token=super-secret"
        )

    def __exit__(self, exc_type, exc, tb):
        return False


def test_browser_startup_error_does_not_persist_raw_exception_text(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        browser,
        "_load_playwright",
        lambda: lambda: _FailingManager(),
    )

    session = browser.BrowserSession(
        BrowserAccessConfig(profile_root=tmp_path / "profiles")
    )

    try:
        session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1)],
            output_dir=tmp_path / "downloads",
        )
    except browser.BrowserCapabilityUnavailable as exc:
        message = str(exc)
    else:
        raise AssertionError("browser startup failure must be explicit")

    assert message == "Playwright could not start: RuntimeError"
    assert "super-secret" not in message
    assert "Users/private" not in message


class _AttachedPage(_Page):
    def __init__(self, url, *, title=""):
        super().__init__()
        self.url = url
        self._title = title

    def title(self):
        return self._title


class _AttachedContext(_Context):
    def __init__(self, page, *additional_pages):
        super().__init__()
        self.pages = [page, *additional_pages]


class _AttachedBrowser:
    def __init__(self, context):
        self.contexts = [context]


class _AttachedChromium(_Chromium):
    def __init__(self, context):
        super().__init__(context)
        self.endpoint = None
        self.browser = _AttachedBrowser(context)

    def connect_over_cdp(self, endpoint, **kwargs):
        self.endpoint = endpoint
        self.connect_kwargs = kwargs
        return self.browser


class _AttachedPlaywright(_Playwright):
    def __init__(self, context):
        self.chromium = _AttachedChromium(context)


class _AttachedManager(_Manager):
    def __init__(self, context):
        self.playwright = _AttachedPlaywright(context)


def test_cdp_attach_reuses_existing_page_without_navigating_or_closing(
    monkeypatch,
    tmp_path,
):
    page = _AttachedPage("https://publisher.example/article/1")
    context = _AttachedContext(page)
    manager = _AttachedManager(context)
    observed = {}

    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page_value, *, source, **kwargs):
        observed["context"] = context_value
        observed["page"] = page_value
        observed["navigate_source"] = kwargs["_navigate_source"]
        observed["blocked_urls"] = kwargs["session_blocked_urls"]
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page_value.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
        )
    ) as session:
        result = session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1)],
            output_dir=tmp_path / "downloads",
        )

        assert session.active is True
        assert result.verified_result is None
        assert observed["context"] is context
        assert observed["page"] is page
        assert observed["navigate_source"] is False
        assert observed["blocked_urls"] is None

    assert manager.playwright.chromium.endpoint == "http://127.0.0.1:9222"
    assert page.closed is False
    assert context.closed is False


def test_cdp_batch_navigation_opens_and_closes_temporary_pages(
    monkeypatch,
    tmp_path,
):
    attached_page = _AttachedPage("https://publisher.example/unrelated")
    context = _AttachedContext(attached_page)
    created_pages = []

    def new_page():
        page = _Page()
        created_pages.append(page)
        return page

    context.new_page = new_page
    manager = _AttachedManager(context)
    observed = []
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page_value, *, source, **kwargs):
        observed.append((context_value, page_value, source.url))
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
            cdp_resume_existing_page=False,
        )
    ) as session:
        session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1), _candidate(2)],
            output_dir=tmp_path / "downloads",
        )

    assert [item[2] for item in observed] == [
        "https://publisher.example/article/1",
        "https://publisher.example/article/2",
    ]
    assert all(item[0] is context for item in observed)
    assert [item[1] for item in observed] == created_pages
    assert all(page.closed for page in created_pages)
    assert attached_page.closed is False
    assert context.closed is False


def test_cdp_batch_navigation_preserves_page_needing_interaction(
    monkeypatch,
    tmp_path,
):
    attached_page = _AttachedPage("https://publisher.example/unrelated")
    context = _AttachedContext(attached_page)
    created_pages = []

    def new_page():
        page = _Page()
        created_pages.append(page)
        return page

    context.new_page = new_page
    manager = _AttachedManager(context)
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)
    monkeypatch.setattr(
        browser,
        "attempt_browser_route",
        lambda context_value, page_value, *, source, **kwargs: BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.INTERACTION_REQUIRED,
        ),
    )

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
            cdp_resume_existing_page=False,
        )
    ) as session:
        result = session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1), _candidate(2)],
            output_dir=tmp_path / "downloads",
        )

    assert len(result.attempts) == 1
    assert len(created_pages) == 1
    assert created_pages[0].closed is False
    assert context.closed is False


def test_cdp_batch_navigation_resumes_strong_title_match(
    monkeypatch,
    tmp_path,
):
    title = "Target Fuel Cell Article"
    retained_page = _AttachedPage(
        "https://publisher.example/article/target",
        title=title,
    )
    context = _AttachedContext(retained_page)
    manager = _AttachedManager(context)
    observed = {}
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page_value, *, source, **kwargs):
        observed["page"] = page_value
        observed["navigate_source"] = kwargs["_navigate_source"]
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page_value.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
            cdp_resume_existing_page=False,
        )
    ) as session:
        session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1)],
            output_dir=tmp_path / "downloads",
            expected_title=title,
        )

    assert observed["page"] is retained_page
    assert observed["navigate_source"] is False
    assert retained_page.closed is False
    assert context.closed is False


def test_cdp_batch_navigation_resumes_exact_pdf_url_without_title_match(
    monkeypatch,
    tmp_path,
):
    retained_page = _AttachedPage(
        "https://publisher.example/doi/pdf/10.1000/session-limit",
        title="article.pdf",
    )
    context = _AttachedContext(retained_page)
    manager = _AttachedManager(context)
    observed = {}
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page_value, *, source, **kwargs):
        observed["page"] = page_value
        observed["navigate_source"] = kwargs["_navigate_source"]
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page_value.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
            cdp_resume_existing_page=False,
        )
    ) as session:
        session.acquire(
            doi="10.1000/session-limit",
            routes=[
                _candidate(
                    1,
                    url=("https://publisher.example/doi/pdf/10.1000/session-limit"),
                )
            ],
            output_dir=tmp_path / "downloads",
            expected_title="Target Article",
        )

    assert observed["page"] is retained_page
    assert observed["navigate_source"] is False
    assert retained_page.closed is False


def test_cdp_attach_prefers_title_matching_pdf_tab(monkeypatch, tmp_path):
    title = "Target Catalysis Article"
    article = _AttachedPage(
        "https://publisher.example/article/1",
        title=title,
    )
    unrelated_pdf = _AttachedPage(
        "https://cdn.example/unrelated.pdf",
        title="Unrelated Article",
    )
    target_pdf = _AttachedPage(
        "https://cdn.example/target.pdf?signature=short-lived",
        title=title,
    )
    context = _AttachedContext(article, unrelated_pdf, target_pdf)
    manager = _AttachedManager(context)
    observed = {}

    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page_value, *, source, **kwargs):
        observed["page"] = page_value
        observed["source"] = source
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page_value.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
        )
    ) as session:
        session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1)],
            output_dir=tmp_path / "downloads",
            expected_title=title,
        )

    assert observed["page"] is target_pdf
    assert observed["source"].url == target_pdf.url
    assert observed["source"].url_type.value == "pdf"


def test_cdp_attach_matches_acs_article_code_when_pdf_title_is_blank(
    monkeypatch,
    tmp_path,
):
    unrelated_pdf = _AttachedPage(
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC8000292/pdf/membranes-11-00183.pdf",
        title="",
    )
    target_pdf = _AttachedPage(
        "https://pubs.acs.org/ancac3/article-pdf/19/19/18409/42251451/nn5c01551.pdf",
        title="",
    )
    context = _AttachedContext(target_pdf, unrelated_pdf)
    manager = _AttachedManager(context)
    observed = {}
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page_value, *, source, **kwargs):
        observed["page"] = page_value
        observed["source"] = source
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page_value.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
        )
    ) as session:
        session.acquire(
            doi="10.1021/acsnano.5c01551",
            routes=[
                FullTextCandidate(
                    doi="10.1021/acsnano.5c01551",
                    url="https://doi.org/10.1021/acsnano.5c01551",
                    provenance=(),
                    url_type=CandidateUrlType.LANDING_PAGE,
                )
            ],
            output_dir=tmp_path / "downloads",
            expected_title=(
                "Tunable Hydrated Channels in Covalent Organic Framework "
                "Membrane for Seawater Desalination"
            ),
        )

    assert observed["page"] is target_pdf
    assert observed["source"].url == target_pdf.url


def test_cdp_attach_avoids_expired_signed_pdf_tab(monkeypatch, tmp_path):
    title = "Target Catalysis Article"
    article = _AttachedPage(
        "https://publisher.example/article/1",
        title=title,
    )
    expired_pdf = _AttachedPage(
        "https://cdn.example/target.pdf?"
        "X-Amz-Date=20000101T000000Z&X-Amz-Expires=300&X-Amz-Signature=secret",
        title=title,
    )
    context = _AttachedContext(article, expired_pdf)
    manager = _AttachedManager(context)
    observed = {}

    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(context_value, page_value, *, source, **kwargs):
        observed["page"] = page_value
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page_value.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)

    with browser.BrowserSession(
        BrowserAccessConfig(
            profile_root=tmp_path / "profiles",
            cdp_endpoint="http://127.0.0.1:9222",
        )
    ) as session:
        session.acquire(
            doi="10.1000/session-limit",
            routes=[_candidate(1)],
            output_dir=tmp_path / "downloads",
            expected_title=title,
        )

    assert observed["page"] is article
