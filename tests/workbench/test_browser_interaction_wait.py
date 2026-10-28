"""Human control waits service an owned event loop without locking UI controls."""

import json
import time
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access.browser import (
    BrowserCapabilityUnavailable,
    BrowserSession,
)
from aletheia_nexus.workbench.jobs import TaskManager


def terminal(manager, job_id):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        receipt = manager.get(job_id)
        if receipt["status"] in {"COMPLETED", "CANCELLED", "FAILED"}:
            return receipt
        time.sleep(0.01)
    raise AssertionError(manager.get(job_id))


def test_event_pump_runs_on_waiting_worker_outside_task_control_lock(tmp_path):
    manager = TaskManager(tmp_path)
    processed = []

    def work(context):
        owner = get_ident()

        def pump(seconds):
            processed.append((get_ident(), seconds))
            completed = Event()

            def continue_from_ui():
                manager.control(context.job_id, "continue")
                completed.set()

            thread = Thread(target=continue_from_ui)
            thread.start()
            assert completed.wait(1), "event pump held the task control lock"
            thread.join()

        action = context.wait_interaction({"stage": "fixture"}, pump=pump)
        assert processed[0][0] == owner
        return {"decision": action}

    try:
        job = manager.submit("fixture", "wait", [], work)
        receipt = terminal(manager, job["id"])
        assert receipt["status"] == "COMPLETED", receipt
        assert receipt["result"]["decision"] == "continue"
        assert processed[0][1] == 0.25
    finally:
        manager.close(wait=True)


@pytest.mark.parametrize("action", ["skip", "cancel", "cancel_and_continue", "timeout"])
def test_pumped_wait_preserves_skip_cancel_timeout_and_cancel_priority(
    tmp_path, action
):
    manager = TaskManager(tmp_path)

    def work(context):
        def pump(seconds):
            if action == "timeout":
                time.sleep(seconds)
            elif action == "cancel_and_continue":
                with manager._condition:
                    manager.control(context.job_id, "cancel")
                    manager.control(context.job_id, "continue")
            else:
                manager.control(context.job_id, action)

        decision = context.wait_interaction(
            {"stage": "fixture"},
            timeout=0.02 if action == "timeout" else None,
            pump=pump,
        )
        return {"decision": decision}

    try:
        job = manager.submit("fixture", "wait", [], work)
        receipt = terminal(manager, job["id"])
        if action.startswith("cancel"):
            assert receipt["status"] == "CANCELLED"
        else:
            assert receipt["result"]["decision"] == "skip"
            assert receipt["interaction_resolution"] == (
                "timeout_skip" if action == "timeout" else "skip"
            )
    finally:
        manager.close(wait=True)


@pytest.mark.parametrize(
    "action,expected", [("resume", "COMPLETED"), ("cancel", "CANCELLED")]
)
def test_pause_after_human_continue_keeps_events_and_controls_responsive(
    tmp_path, action, expected
):
    manager = TaskManager(tmp_path)
    paused_pump = Event()

    def work(context):
        def interact_pump(seconds):
            manager.control(context.job_id, "pause")
            manager.control(context.job_id, "continue")

        assert context.wait_interaction({}, pump=interact_pump) == "continue"

        def pause_pump(seconds):
            paused_pump.set()
            time.sleep(seconds)

        context.checkpoint(pump=pause_pump)
        return {"resumed": True}

    try:
        job = manager.submit("fixture", "wait", [], work)
        assert paused_pump.wait(2)
        assert manager.get(job["id"])["status"] == "PAUSED"
        manager.control(job["id"], action)
        assert terminal(manager, job["id"])["status"] == expected
    finally:
        manager.close(wait=True)


def test_failed_pump_is_a_real_task_failure_without_raw_url_in_diagnostics(tmp_path):
    manager = TaskManager(tmp_path)

    def work(context):
        def pump(seconds):
            raise RuntimeError("https://private:password@example.test/?ticket=secret")

        return context.wait_interaction({}, pump=pump)

    try:
        job = manager.submit("fixture", "wait", [], work)
        receipt = terminal(manager, job["id"])
        assert receipt["status"] == "FAILED"
        assert receipt["interaction_resolution"] == "event_processing_failed"
        assert receipt["interaction_error_type"] == "RuntimeError"
        assert "password" not in json.dumps(receipt)
    finally:
        manager.close(wait=True)


@pytest.mark.parametrize("paused", [False, True])
def test_cancel_wins_over_simultaneous_event_pump_error(tmp_path, paused):
    manager = TaskManager(tmp_path)

    def work(context):
        def pump(seconds):
            manager.control(context.job_id, "cancel")
            raise RuntimeError("browser closed")

        if paused:
            manager.control(context.job_id, "pause")
            context.checkpoint(pump=pump)
        else:
            context.wait_interaction({}, pump=pump)

    try:
        job = manager.submit("fixture", "wait", [], work)
        assert terminal(manager, job["id"])["status"] == "CANCELLED"
    finally:
        manager.close(wait=True)


def test_session_event_pump_only_waits_on_a_live_page_and_checks_owner_thread():
    waits = []
    session = BrowserSession()
    closed = SimpleNamespace(is_closed=lambda: True)
    page = SimpleNamespace(is_closed=lambda: False, wait_for_timeout=waits.append)
    session._context = SimpleNamespace(pages=[closed, page])
    session._event_thread_id = get_ident()
    session.pump_events(0.025)
    assert waits == [25]

    errors = []

    def foreign_thread():
        try:
            session.pump_events(0.01)
        except Exception as exc:
            errors.append(exc)

    worker = Thread(target=foreign_thread)
    worker.start()
    worker.join(1)
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert waits == [25]
    session._context.pages = [closed]
    with pytest.raises(BrowserCapabilityUnavailable, match="no live page"):
        session.pump_events(0.01)


def test_dormant_event_pump_never_starts_a_browser(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "aletheia_nexus.acquire.access.browser.time.sleep", sleeps.append
    )
    session = BrowserSession()
    session.pump_events(0.01)
    assert sleeps == [0.01] and not session.active
    with pytest.raises(ValueError, match="finite"):
        session.pump_events(float("inf"))
