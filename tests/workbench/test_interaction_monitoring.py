"""Non-blocking browser cooperation cannot infer verification or override controls."""

import time
from threading import Event, Thread, get_ident

import pytest

from aletheia_nexus.workbench.jobs import TERMINAL, TaskManager
from aletheia_nexus.workbench.settings import atomic_json


def wait_for(manager, job_id, states, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        receipt = manager.get(job_id)
        if receipt["status"] in states:
            return receipt
        time.sleep(0.005)
    raise AssertionError(manager.get(job_id))


@pytest.fixture
def manager(tmp_path):
    value = TaskManager(tmp_path)
    try:
        yield value
    finally:
        value.close(wait=True)


def test_pending_polls_do_not_complete_and_only_core_resolution_finishes_wait(manager):
    pending, core_resolved = Event(), Event()

    def worker(context):
        context.begin_interaction({"auto_monitoring": True, "source": "local-fixture"})
        for _ in range(3):
            assert context.poll_interaction() is None
            assert manager.get(context.job_id)["status"] == "INTERACTION_REQUIRED"
        pending.set()
        assert core_resolved.wait(2)
        context.finish_interaction("core_resolved")
        return {"core_resolved": True}

    job = manager.submit("fixture", "cooperative wait", [], worker)
    assert pending.wait(2)
    before = manager.get(job["id"])
    assert before["interaction"]["auto_monitoring"]
    assert before["interaction_resolution"] is None
    core_resolved.set()  # No UI continue is sent.
    result = wait_for(manager, job["id"], {"COMPLETED"})
    assert result["interaction"] is None
    assert result["last_interaction"]["resolution"] == "core_resolved"
    assert not any(event.get("action") == "continue" for event in result["events"])


def test_continue_requests_recheck_and_keeps_wait_active_until_core_resolution(manager):
    started, rechecked, resolve = Event(), Event(), Event()

    def worker(context):
        context.begin_interaction({"auto_monitoring": True, "source": "fixture"})
        started.set()
        deadline = time.monotonic() + 2
        while context.poll_interaction() != "continue":
            assert time.monotonic() < deadline
            time.sleep(0.005)
        rechecked.set()
        assert resolve.wait(2)
        context.finish_interaction("core_resolved")
        return {}

    job = manager.submit("fixture", "recheck", [], worker)
    assert started.wait(2)
    manager.control(job["id"], "continue")
    assert rechecked.wait(2)
    receipt = manager.get(job["id"])
    assert receipt["status"] == "INTERACTION_REQUIRED" and receipt["interaction"]
    assert receipt["interaction_resolution"] == "recheck_requested"
    resolve.set()
    result = wait_for(manager, job["id"], {"COMPLETED"})
    assert result["last_interaction"]["requested_action"] == "continue"
    assert result["interaction"] is None


def test_poll_consumes_skip_before_continue_and_never_leaves_it_for_the_next_paper(
    manager,
):
    def worker(context):
        context.begin_interaction({"auto_monitoring": True})
        with manager._condition:
            manager.control(context.job_id, "continue")
            manager.control(context.job_id, "skip")
        decision = context.poll_interaction()
        assert not context.should_skip()
        return {"decision": decision, "status": "PARTIAL"}

    job = manager.submit("fixture", "skip", [], worker)
    result = wait_for(manager, job["id"], {"PARTIAL"})
    assert result["result"]["decision"] == "skip"
    assert result["interaction"] is None
    assert result["last_interaction"]["requested_action"] == "skip"
    assert result["last_interaction"]["resolution"] == "skip"


def test_cancel_wins_over_simultaneous_skip_and_continue_during_poll(manager):
    def worker(context):
        context.begin_interaction({"auto_monitoring": True})
        with manager._condition:
            for action in ("continue", "skip", "cancel"):
                manager.control(context.job_id, action)
        context.poll_interaction()
        pytest.fail("Cancellation must not become a recheck or a completed source")

    job = manager.submit("fixture", "cancel", [], worker)
    result = wait_for(manager, job["id"], {"CANCELLED"})
    assert result["interaction"] is None
    assert result["last_interaction"]["resolution"] == "cancelled"


def test_finish_after_core_delivery_preserves_late_cancel_and_records_delivered_item(
    manager,
):
    def worker(context):
        context.begin_interaction({"auto_monitoring": True})
        manager.control(context.job_id, "skip")
        manager.control(context.job_id, "cancel")
        context.finish_interaction("core_resolved")
        assert manager.get(context.job_id)["status"] == "CANCEL_REQUESTED"
        assert not context.should_skip()
        context.record("actual-delivered-item", "COMPLETED")
        context.checkpoint()

    job = manager.submit("fixture", "delivery then cancel", [], worker)
    result = wait_for(manager, job["id"], {"CANCELLED"})
    assert result["records"][0]["status"] == "COMPLETED"
    assert result["last_interaction"]["resolution"] == "core_resolved"
    assert result["last_interaction"]["requested_action"] == "skip"
    assert result["interaction"] is None


def test_finish_does_not_release_pause_and_preserves_a_later_skip_without_active_wait(
    manager,
):
    def worker(context):
        context.begin_interaction({"auto_monitoring": True})
        manager.control(context.job_id, "pause")
        context.finish_interaction("core_resolved")
        assert manager.get(context.job_id)["status"] == "PAUSE_REQUESTED"
        context.record("delivered-before-pause", "COMPLETED")
        context.checkpoint()
        manager.control(context.job_id, "skip")
        context.finish_interaction("duplicate_resolved_notification")
        assert context.should_skip(), "No-active finish must preserve 'skip next paper'"
        return {}

    job = manager.submit("fixture", "resolved then paused", [], worker)
    paused = wait_for(manager, job["id"], {"PAUSED"})
    assert paused["interaction"] is None and len(paused["records"]) == 1
    manager.control(job["id"], "resume")
    result = wait_for(manager, job["id"], {"COMPLETED"})
    assert result["last_interaction"]["resolution"] == "core_resolved"


@pytest.mark.parametrize("manual", [False, True])
def test_pause_resume_returns_to_active_wait_without_requiring_continue_to_unpause(
    manager, manual
):
    started = Event()

    def worker(context):
        if manual:
            started.set()
            return {"decision": context.wait_interaction({"stage": "manual_wait"})}
        context.begin_interaction({"auto_monitoring": True})
        started.set()
        while True:
            decision = context.poll_interaction()
            if decision == "continue":
                context.finish_interaction("core_resolved")
                return {"decision": decision}
            time.sleep(0.005)

    job = manager.submit("fixture", "pause and resume wait", [], worker)
    assert started.wait(2)
    wait_for(manager, job["id"], {"INTERACTION_REQUIRED"})
    manager.control(job["id"], "pause")
    wait_for(manager, job["id"], {"PAUSED"})
    manager.control(job["id"], "resume")
    resumed = wait_for(manager, job["id"], {"INTERACTION_REQUIRED"})
    assert resumed["interaction"] is not None
    manager.control(job["id"], "continue")
    result = wait_for(manager, job["id"], {"COMPLETED"})
    assert result["result"]["decision"] == "continue" and result["interaction"] is None


def test_new_wait_clears_old_resolution_and_error_but_archives_source(manager):
    def worker(context):
        context.begin_interaction({"source": "old source"})
        manager._update(context.job_id, interaction_error_type="OldError")
        context.finish_interaction("old_failure")
        previous = manager.get(context.job_id)["last_interaction"]
        assert (
            previous["source"] == "old source" and previous["error_type"] == "OldError"
        )
        context.begin_interaction({"source": "new source", "auto_monitoring": True})
        current = manager.get(context.job_id)
        assert current["interaction_resolution"] is None
        assert current["interaction_error_type"] is None
        assert current["interaction_recheck_requested_at"] is None
        context.finish_interaction("core_resolved")
        return {}

    job = manager.submit("fixture", "new wait", [], worker)
    result = wait_for(manager, job["id"], {"COMPLETED"})
    assert result["last_interaction"]["source"] == "new source"


def test_repeated_begin_does_not_discard_a_pending_recheck(manager):
    def worker(context):
        details = {"source": "same fixture source", "auto_monitoring": True}
        context.begin_interaction(details)
        manager.control(context.job_id, "continue")
        context.begin_interaction(details)
        assert context.poll_interaction() == "continue"
        assert manager.get(context.job_id)["interaction"] == details
        context.finish_interaction("core_resolved")
        return {}

    job = manager.submit("fixture", "repeated notification", [], worker)
    result = wait_for(manager, job["id"], {"COMPLETED"})
    assert result["last_interaction"]["requested_action"] == "continue"


def test_poll_pause_pump_stays_on_worker_and_does_not_hold_control_lock(manager):
    def worker(context):
        owner = get_ident()
        context.begin_interaction({"auto_monitoring": True})
        manager.control(context.job_id, "pause")

        def pump(_seconds):
            assert get_ident() == owner
            resumed = Event()

            def ui_resume():
                manager.control(context.job_id, "resume")
                resumed.set()

            thread = Thread(target=ui_resume)
            thread.start()
            assert resumed.wait(1), (
                "The browser event pump must not hold the control lock"
            )
            thread.join()

        assert context.poll_interaction(pump=pump) is None
        assert manager.get(context.job_id)["status"] == "INTERACTION_REQUIRED"
        context.finish_interaction("core_resolved")
        return {}

    job = manager.submit("fixture", "paused event processing", [], worker)
    assert wait_for(manager, job["id"], {"COMPLETED"})["interaction"] is None


@pytest.mark.parametrize("terminal", ["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"])
def test_early_terminal_return_clears_active_wait_in_the_same_persisted_update(
    manager, terminal
):
    def worker(context):
        context.begin_interaction(
            {"source": "unfinished core boundary", "auto_monitoring": True}
        )
        return {"status": terminal}

    job = manager.submit("fixture", "terminal cleanup", [], worker)
    receipt = wait_for(manager, job["id"], TERMINAL)
    assert receipt["status"] == terminal and receipt["interaction"] is None
    assert receipt["last_interaction"]["resolution"] == terminal.lower()


def test_interrupted_process_archives_pending_wait_without_automatic_reexecution(
    tmp_path,
):
    atomic_json(
        tmp_path / "tasks/old-wait.json",
        {
            "schema": "aletheia-nexus/workbench-task/v1",
            "id": "old-wait",
            "kind": "acquisition",
            "status": "INTERACTION_REQUIRED",
            "created_at": "2026-01-01",
            "events": [],
            "interaction": {"source": "fixture", "auto_monitoring": True},
        },
    )
    manager = TaskManager(tmp_path)
    try:
        receipt = manager.get("old-wait")
        assert receipt["status"] == "INTERRUPTED" and receipt["interaction"] is None
        assert receipt["last_interaction"]["resolution"] == "interrupted"
        assert receipt["last_interaction"]["source"] == "fixture"
    finally:
        manager.close(wait=True)
