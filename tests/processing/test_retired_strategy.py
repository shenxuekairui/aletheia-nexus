"""Retired execution rejects early; immutable local history remains reusable."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_workflow import papers as papers
from test_workflow import response_for, task_for

from aletheia_nexus.processing import engine
from aletheia_nexus.processing.contracts import digest, validate_task
from aletheia_nexus.processing.materials import build_package, load_source
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import make_result, verify_result
from aletheia_nexus.processing_cli import main
from aletheia_nexus.research_app import ResearchApplication


def legacy_task(papers, mode="parsed"):
    task = task_for(papers[:1], mode=mode)
    task.update(
        extraction_strategy="field_independent",
        include_steps=False,
        include_claims=False,
    )
    return validate_task(task)


@pytest.mark.parametrize("mode", ["parsed", "local"])
def test_retired_strategy_refuses_before_source_provider_or_writes(
    papers, tmp_path, monkeypatch, mode
):
    task = legacy_task(papers, mode)
    original = deepcopy(task)
    output = tmp_path / "must-not-be-created"

    def unexpected(*args, **kwargs):
        pytest.fail("a retired task must not read sources or instantiate a provider")

    monkeypatch.setattr(engine, "load_source", unexpected)
    monkeypatch.setattr(engine, "DeepSeekProvider", unexpected)
    with pytest.raises(
        ProcessingError,
        match="field_independent_retired.*source_first_or_direct.*preview_again",
    ):
        engine.run_task(task, base_dir=tmp_path, output_dir=output, allow_remote=True)
    assert task == original
    assert not output.exists()
    app = ResearchApplication([tmp_path], tmp_path / "workspace", remote=True)
    try:
        before = {
            str(p.relative_to(app.workspace)): p.read_bytes()
            for p in app.workspace.rglob("*")
            if p.is_file()
        }
        monkeypatch.setattr(app, "check_document", unexpected)
        for action in (
            lambda: app.validate_research_task(task),
            lambda: app.binding("execute", task),
            lambda: app.execute_research_task(task, background=False),
        ):
            with pytest.raises(ProcessingError, match="field_independent_retired"):
                action()
        after = {
            str(p.relative_to(app.workspace)): p.read_bytes()
            for p in app.workspace.rglob("*")
            if p.is_file()
        }
        assert after == before
        assert task == original
    finally:
        app.close()


def test_old_task_result_cache_history_revision_and_export_stay_local(
    papers, tmp_path, monkeypatch
):
    # A sealed historical artifact is constructed without the retired execution module.
    task = legacy_task(papers)
    package, _ = build_package(
        task, [load_source(task["documents"][0], tmp_path, task["mode"])]
    )
    response = response_for(engine._request(task, package))
    record = response["records"][0]
    record.update(id="paper0", stage="document", steps=[])
    for field in record["fields"].values():
        field["step_ids"] = []
    provider = {
        "provider": "historical-self-authored",
        "extraction_strategy": "field_independent",
        "field_independent_version": "field-independent/1",
    }
    result = make_result(task, package, provider, response)
    run = tmp_path / "history" / "runs" / "historical"
    run.mkdir(parents=True)
    result_path, task_path = run / "paper0.result.json", run / "task.json"
    engine.write_json(result_path, result)
    engine.write_json(task_path, task)
    engine.write_json(
        run / "manifest.json",
        {
            "schema": "aletheia-nexus/research-run/v1",
            "run_id": "historical",
            "status": "COMPLETED",
            "task_file": "task.json",
            "task_fingerprint": digest(task),
            "run_directory": str(run),
            "calls": [],
            "items": [
                {
                    "id": "paper0",
                    "status": "COMPLETED",
                    "result": result_path.name,
                    "result_id": result["artifact_id"],
                }
            ],
            "outputs": [result_path.name],
            "provider": provider,
        },
    )
    cache = tmp_path / "history" / "cache" / "field-legacy.json"
    engine.write_json(
        cache,
        {
            "result": result,
            "historical_stage_metadata": {"owner_run": "historical", "reused": True},
        },
    )
    protected = [
        result_path,
        task_path,
        cache,
        run / "manifest.json",
        papers[0],
        papers[0].with_suffix(".parsed.json"),
    ]
    old_bytes = {p: p.read_bytes() for p in protected}
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(
        engine,
        "DeepSeekProvider",
        lambda *a, **k: pytest.fail("history must not call a model"),
    )
    assert validate_task(json.loads(task_path.read_text("utf-8"))) == task
    verify_result(result)
    app = ResearchApplication([tmp_path], tmp_path / "workspace")
    try:
        historical = app.list_research_runs(directory=str(tmp_path / "history"))["runs"]
        assert len(historical) == 1 and historical[0]["status"] == "COMPLETED"
        loaded = app.read_research_result(str(result_path))
        assert (
            loaded["response"] == result["response"] and loaded["provider"] == provider
        )
        exported = app.export_research_results([str(result_path)], "legacy-export")
        assert len(exported["outputs"]) == 3 and not exported["network_access"]
        revised = app.revise_research_result(
            str(result_path),
            {
                "record_id": record["id"],
                "replacement": deepcopy(record),
                "reason": "Re-read the self-authored source; preserve the historical scientific content.",
            },
            client_identity="test-assistant",
        )
        child = json.loads(Path(revised["result"]).read_text("utf-8"))
        verify_result(child)
        assert child["task"] == task and child["provider"] == provider
        assert (
            child["history"][-1]["authority"] == "assistant"
            and not revised["confirmed"]
        )
    finally:
        app.close()
    assert (
        main(["export", str(result_path), "--output-dir", str(tmp_path / "cli-export")])
        == 0
    )
    assert {p: p.read_bytes() for p in protected} == old_bytes
