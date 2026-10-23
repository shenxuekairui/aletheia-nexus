"""CNKI pacing uses a fake clock; tests never sleep or contact a publisher."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import browser
from aletheia_nexus.acquire.access.batch import acquire_full_text_batch_maximized
from aletheia_nexus.acquire.access.cnki_provider import CNKIProvider, _source_candidate
from aletheia_nexus.acquire.access.cnki_runtime import CNKI_RATE_LIMITED
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
)


@pytest.fixture
def pacing(monkeypatch, tmp_path):
    clock = SimpleNamespace(now=100.0, sleeps=[], starts=[], error=None)

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.setattr(
        browser, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep)
    )
    session = browser.BrowserSession(BrowserAccessConfig(profile_root=tmp_path))
    monkeypatch.setattr(
        session,
        "_ensure_started",
        lambda: SimpleNamespace(
            new_page=lambda: SimpleNamespace(
                is_closed=lambda: False, close=lambda: None
            )
        ),
    )
    provider = CNKIProvider()

    def fetch(**kwargs):
        clock.starts.append(clock.now)
        clock.now += 30.0
        if clock.error == "exception":
            raise RuntimeError("fixture failure")
        return BrowserAccessAttempt(
            source_candidate=_source_candidate(kwargs["doi"]),
            final_url=None,
            status=BrowserAttemptStatus.ACCESS_DENIED
            if clock.error
            else BrowserAttemptStatus.NO_FILE_CANDIDATES,
            error=clock.error,
        )

    monkeypatch.setattr(provider, "fetch", fetch)
    return session, provider, clock


@pytest.mark.parametrize("interval", [5.0, 0.0, 8.5])
@pytest.mark.parametrize("elapsed", [0.0, 2.0, 10.0])
def test_cnki_waits_only_for_remaining_time_after_previous_completion(
    pacing, tmp_path, interval, elapsed
):
    session, provider, clock = pacing
    assert session.config.cnki_paper_interval == 5.0
    session.config = replace(session.config, cnki_paper_interval=interval)
    session.acquire_provider(provider, doi="10.1000/first", output_dir=tmp_path)
    assert not clock.sleeps
    clock.now += elapsed
    session.acquire_provider(provider, doi="10.1000/second", output_dir=tmp_path)
    assert clock.sleeps == ([interval - elapsed] if elapsed < interval else [])
    assert clock.starts == [100.0, 130.0 + max(interval, elapsed)]


def test_other_providers_do_not_wait_or_restart_cnki_interval(pacing, tmp_path):
    session, provider, clock = pacing
    session.acquire_provider(provider, doi="10.1000/cnki", output_dir=tmp_path)
    provider.name = "other"
    session.acquire_provider(provider, doi="10.1000/other", output_dir=tmp_path)
    provider.name = "cnki"
    session.acquire_provider(provider, doi="10.1000/next", output_dir=tmp_path)
    assert not clock.sleeps
    assert clock.starts == [100.0, 130.0, 160.0]


def test_failed_cnki_attempt_still_gets_a_quiet_interval(pacing, tmp_path):
    session, provider, clock = pacing
    clock.error = "exception"
    with pytest.raises(RuntimeError, match="fixture failure"):
        session.acquire_provider(provider, doi="10.1000/first", output_dir=tmp_path)
    clock.error = None
    session.acquire_provider(provider, doi="10.1000/second", output_dir=tmp_path)
    assert clock.starts == [100.0, 135.0]


def test_rate_limit_stops_cnki_requests_even_with_interval_disabled(pacing, tmp_path):
    session, provider, clock = pacing
    session.config = replace(session.config, cnki_paper_interval=0)
    clock.error = CNKI_RATE_LIMITED
    first = session.acquire_provider(provider, doi="10.1000/first", output_dir=tmp_path)
    clock.error = None
    paused = session.acquire_provider(
        provider, doi="10.1000/second", output_dir=tmp_path
    )
    assert first.error == paused.error == CNKI_RATE_LIMITED
    assert paused.status == BrowserAttemptStatus.ACCESS_DENIED
    assert paused.source_candidate.doi == "10.1000/second"
    assert not paused.file_attempts and paused.final_url is None
    assert clock.starts == [100.0] and not clock.sleeps
    provider.name = "other"
    session.acquire_provider(provider, doi="10.1000/other", output_dir=tmp_path)
    assert clock.starts == [100.0, 130.0]


def test_local_import_and_checkpoint_reuse_skip_cnki_wait(pacing, tmp_path):
    session, _, clock = pacing
    session._cnki_finished_at = clock.now
    source = Path(__file__).parents[3] / "benchmarks/v07_fixtures/native_article.pdf"
    doi = "10.5555/an.v07.native"
    options = dict(
        output_dir=tmp_path / "papers",
        browser_session=session,
        local_pdfs={doi: source},
        checkpoint_path=tmp_path / "checkpoint.json",
    )
    first = acquire_full_text_batch_maximized([doi], **options)
    resumed = acquire_full_text_batch_maximized([doi], **options)
    assert first.verified_count == 1 and resumed.items[0].resumed
    assert not clock.starts and not clock.sleeps


def test_internal_context_reconnect_also_waits_five_seconds(
    pacing, monkeypatch, tmp_path
):
    session, provider, clock = pacing

    def fetch(**kwargs):
        clock.starts.append(clock.now)
        return BrowserAccessAttempt(
            source_candidate=_source_candidate(kwargs["doi"]),
            final_url=None,
            status=BrowserAttemptStatus.ERROR
            if len(clock.starts) == 1
            else BrowserAttemptStatus.NO_FILE_CANDIDATES,
            evidence=("CNKI browser target closed",) if len(clock.starts) == 1 else (),
        )

    monkeypatch.setattr(provider, "fetch", fetch)
    monkeypatch.setattr(session, "close", lambda: None)
    session.acquire_provider(provider, doi="10.1000/retry", output_dir=tmp_path)
    assert clock.starts == [100.0, 105.0]
    assert clock.sleeps == [5.0]
