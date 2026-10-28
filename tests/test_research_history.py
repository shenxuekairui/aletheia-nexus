"""Bounded history discovery reuses saved runs without any model access."""

from pathlib import Path

import pytest
from test_research_app import app as app
from test_research_app import task_for

from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import read_json


def planning_history(workspace, name, status, task=None):
    directory = workspace / "planning" / name
    write_json(directory / "request.json", {"goal": "整理文献", "metadata": []})
    if task is not None:
        write_json(directory / "task.json", task)
    write_json(
        directory / "manifest.json",
        {
            "schema": "aletheia-nexus/research-run/v1",
            "phase": "task_planning",
            "run_id": name,
            "status": status,
            "request_fingerprint": name,
            "run_directory": "ignored-untrusted-locator",
            "items": [],
            "outputs": [],
            "usage": {"http_attempts": 1, "estimated_cost": 0.01},
            "error": "invalid_planning_output" if status == "FAILED" else None,
        },
    )
    return directory


def test_history_discovers_jobs_planning_native_and_deduplicates_copies(
    app, monkeypatch
):
    import httpx

    service, pdf = app
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setattr(
        httpx.Client, "request", lambda *a, **k: pytest.fail("network call")
    )
    docs = service.prepare_documents([str(pdf)])["documents"]
    task = task_for(docs)
    job = service.execute_research_task(task, background=False)
    run = Path(job["run_directory"])
    manifest = read_json(run / "manifest.json")
    write_json(service.workspace / "runs/copy/manifest.json", manifest)
    view = {
        **manifest,
        "run_id": "retained-view",
        "view_kind": "offline_exact_retained_result_not_new_execution",
    }
    write_json(service.workspace / "runs/view/manifest.json", view)
    success = planning_history(service.workspace, "plan-ok", "COMPLETED", task)
    planning_history(service.workspace, "plan-failed", "FAILED")
    bad = service.workspace / "planning/bad/manifest.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("not JSON", encoding="utf-8")
    # This is deliberately outside the advertised fixed directory layouts.
    write_json(
        service.workspace / "arbitrary/deep/runs/hidden/manifest.json",
        {**manifest, "run_id": "hidden"},
    )

    history = service.list_research_runs()
    assert history["network_access"] is False and history["usage_aggregated"] is False
    assert len(history["runs"]) == 3
    current = next(row for row in history["runs"] if row["job_id"] == job["job_id"])
    assert current["status"] == job["status"] == "PREPARED"
    assert current["manifest_file"] == str(run / "manifest.json")
    assert current["task_file"] == str(run / "task.json")
    assert len(current["manifest_files"]) == 2
    assert current["usage"]["http_attempts"] == 0
    plans = {r["status"]: r for r in history["runs"] if r["kind"] == "planning"}
    assert plans["COMPLETED"]["task_file"] == str(success / "task.json")
    assert plans["FAILED"]["task_file"] is None
    assert plans["FAILED"]["error"] == "invalid_planning_output"
    assert history["ignored_views"] == 1 and len(history["unavailable"]) == 1
    assert len(service.list_research_runs(limit=1)["runs"]) == 1


def test_history_directory_and_saved_filenames_do_not_widen_scope(app, monkeypatch):
    import aletheia_nexus.research_app as module

    service, pdf = app
    root = pdf.parent / "已有输出"
    directory = root / "runs/native"
    write_json(directory / "safe.result.json", {"fixture": True})
    write_json(
        directory / "manifest.json",
        {
            "schema": "aletheia-nexus/research-run/v1",
            "run_id": "native",
            "status": "PARTIAL",
            "task_fingerprint": "fixed-task",
            "run_directory": str(pdf.parent.parent / "outside"),
            "task_file": "../../private-task.json",
            "items": [
                {"result": "safe.result.json"},
                {"result": "../../secret.json"},
                {"result": str(pdf.parent.parent / "outside.json")},
            ],
            "outputs": ["safe.result.json", "../../secret.json"],
            "usage": {"http_attempts": 0, "estimated_cost": 0},
        },
    )
    read_paths = []
    original_read = module.read_json
    monkeypatch.setattr(
        module, "read_json", lambda p: (read_paths.append(Path(p)), original_read(p))[1]
    )
    assert service.list_research_runs()["runs"] == []
    found = service.list_research_runs(directory=str(root))
    (row,) = found["runs"]
    assert row["run_directory"] == str(directory)
    assert row["task_file"] is None
    assert row["results"] == row["outputs"] == [str(directory / "safe.result.json")]
    assert read_paths == [directory / "manifest.json"]
    assert (
        service.list_research_runs(directory=str(directory))["runs"][0]["run_id"]
        == "native"
    )
    with pytest.raises(ProcessingError, match="path_outside"):
        service.list_research_runs(directory=str(pdf.parent.parent / "outside"))
    with pytest.raises(ProcessingError, match="authorization_directory_private"):
        service.list_research_runs(directory=str(service.private))
    with pytest.raises(ValueError, match="must exist"):
        service.list_research_runs(directory=str(root / "missing"))


def test_history_does_not_follow_job_run_locator_or_broken_job(app, monkeypatch):
    import aletheia_nexus.research_app as module

    service, pdf = app
    job_id = "a" * 32
    write_json(
        service.workspace / "jobs" / job_id / "status.json",
        {
            "job_id": job_id,
            "status": "FAILED",
            "run_directory": str(pdf.parent.parent / "private"),
        },
    )
    broken = service.workspace / "jobs" / ("b" * 32) / "status.json"
    write_json(broken, {"job_id": "b" * 32})
    paths = []
    original = module.read_json
    monkeypatch.setattr(
        module, "read_json", lambda p: (paths.append(Path(p)), original(p))[1]
    )
    history = service.list_research_runs()
    assert history["runs"] == [] and len(history["unavailable"]) == 2
    assert all(p.name == "status.json" for p in paths)
