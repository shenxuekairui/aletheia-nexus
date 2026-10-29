"""Attached-tab observation must not block behind an old PDF execution context."""

from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import browser


class Page:
    def __init__(self, url, title=""):
        self.url, self.observed_title = url, title

    def is_closed(self):
        return False

    def title(self):
        pytest.fail("Attached-page selection must use the bounded observation helper")


def test_unreadable_old_pdf_does_not_prevent_later_title_match(monkeypatch):
    stale = Page("https://old.example/legacy.pdf")
    target = Page("https://publisher.example/article", "Exact target title")
    calls = []

    def read(page, method, *, timeout):
        assert method == "title" and 0 < timeout <= 0.5
        calls.append(page)
        if page is stale:
            raise TimeoutError("Unresponsive PDF renderer")
        return page.observed_title

    monkeypatch.setattr(browser, "bounded_read", read)
    selected = browser._select_attached_page(
        SimpleNamespace(pages=[stale, target]),
        preferred_url="https://publisher.example/doi/10.1000/target",
        expected_title=target.observed_title,
        minimum_score=300,
    )
    assert selected is target and calls == [stale, target]


def test_many_stalled_titles_share_one_budget_and_never_lower_identity_threshold(
    monkeypatch,
):
    pages = [Page(f"https://other.example/old-{index}.pdf") for index in range(20)]
    clock, timeouts = [0.0], []
    monkeypatch.setattr(browser.time, "monotonic", lambda: clock[0])

    def stalled(page, method, *, timeout):
        timeouts.append(timeout)
        clock[0] += timeout
        raise TimeoutError()

    monkeypatch.setattr(browser, "bounded_read", stalled)
    assert (
        browser._select_attached_page(
            SimpleNamespace(pages=pages),
            preferred_url="https://publisher.example/article",
            expected_title="Target article",
            minimum_score=300,
        )
        is None
    )
    assert len(timeouts) == 6 and sum(timeouts) == pytest.approx(3)


def test_url_priority_and_original_tie_break_are_preserved_after_title_timeout(
    monkeypatch,
):
    expected = (
        "https://pubs.acs.org/jpccck/article-pdf/128/13/5741/1692021/jp4c00353.pdf"
    )
    older, latest = Page(expected), Page(expected)
    unrelated = Page("https://elsewhere.example/old.pdf")
    calls = []

    def read(page, *args, **kwargs):
        calls.append(page)
        raise TimeoutError()

    monkeypatch.setattr(browser, "bounded_read", read)
    assert (
        browser._select_attached_page(
            SimpleNamespace(pages=[older, latest, unrelated]),
            preferred_url=expected,
            expected_title="Unobservable title",
            minimum_score=300,
        )
        is latest
    )
    assert calls == [latest, older, unrelated]


def test_absent_expected_title_needs_no_remote_title_observation(monkeypatch):
    page = Page("https://publisher.example/target.pdf")
    monkeypatch.setattr(
        browser, "bounded_read", lambda *a, **kw: pytest.fail("No title to compare")
    )
    assert (
        browser._select_attached_page(
            SimpleNamespace(pages=[page]), preferred_url=page.url
        )
        is page
    )


def test_control_signal_is_not_swallowed_while_selecting_a_tab(monkeypatch):
    class Cancel(BaseException):
        pass

    def cancel(*args, **kwargs):
        raise Cancel()

    monkeypatch.setattr(browser, "bounded_read", cancel)
    with pytest.raises(Cancel):
        browser._select_attached_page(
            SimpleNamespace(pages=[Page("https://publisher.example/article")]),
            preferred_url="https://publisher.example/article",
            expected_title="Target",
        )
