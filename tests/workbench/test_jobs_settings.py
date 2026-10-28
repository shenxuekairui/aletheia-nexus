import json
import time
from threading import Event

import pytest

from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.settings import SettingsStore, atomic_json


def wait_for(manager, job_id, states, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        receipt = manager.get(job_id)
        if receipt["status"] in states:
            return receipt
        time.sleep(0.01)
    raise AssertionError(manager.get(job_id))


def test_control_waits_for_real_safe_boundary_and_persists_results(tmp_path):
    manager = TaskManager(tmp_path)
    started, release = Event(), Event()

    def work(context):
        started.set()
        assert release.wait(3)
        context.record("one", "COMPLETED", path="first.pdf")
        context.checkpoint()
        context.record("two", "COMPLETED")
        return {"complete": 2}

    job = manager.submit("parse", "parse", ["one", "two"], work)
    assert started.wait(2)
    manager.control(job["id"], "pause")
    assert manager.get(job["id"])["status"] == "PAUSE_REQUESTED"
    release.set()
    receipt = wait_for(manager, job["id"], {"PAUSED"})
    assert len(receipt["records"]) == 1
    manager.control(job["id"], "resume")
    assert wait_for(manager, job["id"], {"COMPLETED"})["result"] == {"complete": 2}
    manager.close(wait=True)
    reopened = TaskManager(tmp_path)
    assert reopened.get(job["id"])["status"] == "COMPLETED"
    reopened.close(wait=True)


def test_interaction_skip_and_cancel_are_real_controls(tmp_path):
    manager = TaskManager(tmp_path)

    def work(context):
        decision = context.wait_interaction({"paper": "one", "source": "institution"})
        context.record("one", "SKIPPED" if decision == "skip" else "COMPLETED")

    job = manager.submit("acquire", "login", ["one"], work)
    wait_for(manager, job["id"], {"INTERACTION_REQUIRED"})
    manager.control(job["id"], "skip")
    assert (
        wait_for(manager, job["id"], {"PARTIAL"})["records"][0]["status"] == "SKIPPED"
    )
    job2 = manager.submit("acquire", "login", ["two"], work)
    wait_for(manager, job2["id"], {"INTERACTION_REQUIRED"})
    manager.control(job2["id"], "cancel")
    wait_for(manager, job2["id"], {"CANCELLED"})
    manager.close(wait=True)


def test_crashed_tasks_are_interrupted_without_automatic_reexecution(tmp_path):
    directory = tmp_path / "tasks"
    atomic_json(
        directory / "old.json",
        {
            "schema": "aletheia-nexus/workbench-task/v1",
            "id": "old",
            "kind": "translation",
            "status": "RUNNING",
            "events": [],
            "created_at": "2020",
        },
    )
    manager = TaskManager(tmp_path)
    assert manager.get("old")["status"] == "INTERRUPTED"
    assert manager.get("old")["billing_uncertain"]
    with pytest.raises(ValueError, match="finished task"):
        manager.control("old", "resume")
    with pytest.raises(RuntimeError, match="active task manager"):
        TaskManager(tmp_path)
    manager.close(wait=True)


def test_settings_presets_and_job_redaction(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path)
    store.set("translation", {"enabled": False, "max_cost": 1})
    store.save_preset("acquisition", "机构", {"timeout": 30})
    assert SettingsStore(tmp_path).load_preset("acquisition", "机构") == {"timeout": 30}
    with pytest.raises(ValueError, match="API keys"):
        store.set("provider", {"api_key": "private"})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-test-value")
    manager = TaskManager(tmp_path)
    job = manager.submit(
        "test",
        "test",
        [],
        lambda c: {
            "error": "prefix private-test-value",
            "api_key": "private-test-value",
        },
    )
    wait_for(manager, job["id"], {"COMPLETED"})
    manager.close(wait=True)
    text = (tmp_path / "tasks" / (job["id"] + ".json")).read_text()
    assert "private-test-value" not in text
    assert json.loads(text)["result"]["api_key"] == "[REDACTED]"


def test_cancel_wins_over_simultaneous_interaction_continue(tmp_path):
    manager = TaskManager(tmp_path)
    job = manager.submit(
        "acquisition",
        "interaction",
        ["one"],
        lambda c: c.wait_interaction({"paper": "one"}),
    )
    wait_for(manager, job["id"], {"INTERACTION_REQUIRED"})
    with manager._condition:
        manager.control(job["id"], "cancel")
        manager.control(job["id"], "continue")
    wait_for(manager, job["id"], {"CANCELLED"})
    manager.close(wait=True)


@pytest.mark.parametrize(
    "kind,result_status,expected,recovery",
    [
        ("rename", "ROLLED_BACK", "FAILED", False),
        ("rename", "ROLLBACK_REQUIRED", "FAILED", True),
        ("rollback", "ROLLED_BACK", "COMPLETED", False),
    ],
)
def test_file_operation_failure_cannot_appear_completed(
    tmp_path, kind, result_status, expected, recovery
):
    manager = TaskManager(tmp_path)
    job = manager.submit(kind, "organize", ["one"], lambda c: {"status": result_status})
    result = wait_for(manager, job["id"], {expected})
    assert result.get("needs_recovery", False) == recovery
    manager.close(wait=True)


@pytest.mark.parametrize(
    "kind,parameters",
    [
        ("import", {"title_translation": {"enabled": True}}),
        ("acquisition", {"postprocess": {"title_translation": {"enabled": True}}}),
    ],
)
def test_interrupted_ingestion_keeps_translation_billing_uncertainty(
    tmp_path, kind, parameters
):
    atomic_json(
        tmp_path / "tasks" / "old.json",
        {
            "schema": "aletheia-nexus/workbench-task/v1",
            "id": "old",
            "kind": kind,
            "parameters": parameters,
            "status": "RUNNING",
            "events": [],
            "created_at": "2020",
        },
    )
    manager = TaskManager(tmp_path)
    assert manager.get("old")["billing_uncertain"]
    manager.close(wait=True)
