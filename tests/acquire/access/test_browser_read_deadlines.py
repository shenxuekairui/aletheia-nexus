"""DOM timeouts preserve native delivery and never imply successful clearance."""

from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import browser_route, cnki_runtime
from aletheia_nexus.acquire.access.browser_engine import viewer
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.discovery.models import FullTextCandidate


@pytest.mark.parametrize("matching_file", [None, False, True])
def test_timed_out_main_content_uses_native_identity_gate(
    tmp_path, monkeypatch, matching_file
):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    page = _RoutePage("https://publisher.example/target.pdf")
    clear = ChallengeReport(ChallengeKind.NONE)
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: clear)
    monkeypatch.setattr(
        browser_route, "_resolve_page_challenge", lambda p, **kw: (clear, (), False)
    )

    def read(p, method, *, timeout):
        assert p is page and method == "content" and 0 < timeout <= 2
        raise TimeoutError("Synthetic stalled PDF content")

    monkeypatch.setattr(browser_route, "bounded_read", read)
    title = "Electrochemical reduction of carboxylic acids"

    def native(*args, **kwargs):
        if matching_file is None:
            return None
        stage = tmp_path / "native-stage"
        stage.mkdir()
        path = stage / "native.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata(
            {"/Title": title if matching_file else "An unrelated cosmology study"}
        )
        writer.write(path)
        return path, stage

    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", native)
    result = browser_route.attempt_browser_route(
        _RouteContext(page),
        page,
        source=FullTextCandidate(doi="10.1000/target", url=page.url, provenance=()),
        output_dir=tmp_path / "output",
        expected_title=title,
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=[],
        session_downloads=[],
        _navigate_source=False,
    )
    assert (result.status == BrowserAttemptStatus.VERIFIED) == (matching_file is True)
    assert browser_route._OBSERVATION_UNAVAILABLE in result.evidence
    assert result.error == "TimeoutError"  # Retain the observation failure.
    assert page.goto_calls == []


def test_popup_content_timeout_keeps_its_native_viewer_available(monkeypatch):
    from test_browser_challenge_flow import _RoutePage

    original = _RoutePage("https://publisher.example/article")
    popup = _RoutePage("https://publisher.example/target.pdf")
    closed = []
    popup.close = lambda: closed.append(True)
    popup.wait_for_load_state = lambda *a, **kw: None
    clear = ChallengeReport(ChallengeKind.NONE)
    monkeypatch.setattr(
        browser_route, "_resolve_page_challenge", lambda p, **kw: (clear, (), False)
    )
    calls = []

    def read(page, method, *, timeout):
        calls.append((page, method, timeout))
        raise TimeoutError()

    monkeypatch.setattr(browser_route, "bounded_read", read)
    candidates, reports, _ = browser_route._observe_pdf_popups(
        SimpleNamespace(pages=[original, popup]),
        original_page=original,
        existing_page_ids={id(original)},
        source=FullTextCandidate(doi="10.1000/target", url=original.url, provenance=()),
        expected_title="Target",
        config=BrowserAccessConfig(),
    )
    assert calls == [(popup, "content", 2.0)] and not closed and not reports
    assert candidates[0].url == popup.url


@pytest.mark.parametrize("embedded", [False, True])
def test_pdf_fetch_script_has_an_outer_deadline_even_before_its_js_timer_starts(
    monkeypatch, embedded
):
    page = SimpleNamespace(url="https://publisher.example/target.pdf")
    page.frames = [SimpleNamespace(url=page.url)]
    calls = []

    def read(target, method, *args, timeout):
        assert target is page and method == "evaluate" and 0 < timeout <= 0.05
        calls.append(timeout)
        raise TimeoutError("The JS execution context never started the script")

    monkeypatch.setattr(viewer, "bounded_read", read)
    function = (
        viewer.trigger_embedded_pdf_frame_fetch
        if embedded
        else viewer.trigger_pdf_viewer_same_origin_fetch
    )
    assert not function(
        page, max_bytes=1000, validate_url=lambda value: value, timeout=0.05
    )
    assert len(calls) == 1


def test_cnki_control_scan_shares_deadline_across_all_selectors(monkeypatch):
    clock, budgets = [0.0], []
    monkeypatch.setattr(cnki_runtime.time, "monotonic", lambda: clock[0])
    surface = SimpleNamespace(locator=lambda selector: object())

    def stalled(target, method, *, timeout):
        assert method == "count"
        budgets.append(timeout)
        clock[0] += timeout
        raise TimeoutError()

    monkeypatch.setattr(cnki_runtime, "bounded_read", stalled)
    assert cnki_runtime.first_visible(surface, ["input"] * 100) is None
    assert len(budgets) == 4 and sum(budgets) == pytest.approx(2)


def test_cnki_unreadable_readiness_is_false_and_title_timeout_does_not_erase_rate_limit(
    monkeypatch,
):
    page = SimpleNamespace(
        is_closed=lambda: False,
        url="https://kns.cnki.net/article",
        locator=lambda selector: SimpleNamespace(
            inner_text=lambda **kw: "访问过于频繁，请稍后再试"
        ),
    )
    calls = []

    def stalled(target, method, *args, timeout):
        calls.append(method)
        assert timeout == 0.5
        raise TimeoutError()

    monkeypatch.setattr(cnki_runtime, "first_visible", lambda *args: None)
    monkeypatch.setattr(cnki_runtime, "bounded_read", stalled)
    report = cnki_runtime.challenge_for_page(page)
    assert cnki_runtime.CNKI_RATE_LIMITED in report.evidence
    assert cnki_runtime._resume_ready(page) is False
    assert calls == ["title", "evaluate"]


def test_readiness_cancellation_signal_is_not_converted_to_clearance(monkeypatch):
    class Cancel(BaseException):
        pass

    monkeypatch.setattr(cnki_runtime, "first_visible", lambda *args: None)

    def cancel(*args, **kwargs):
        raise Cancel()

    monkeypatch.setattr(cnki_runtime, "bounded_read", cancel)
    with pytest.raises(Cancel):
        cnki_runtime._resume_ready(object())
