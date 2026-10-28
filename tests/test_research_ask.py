"""CLI consent and saved-plan execution without paid requests."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_research_app import app as application_fixture
from test_research_app import task_for

from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing_cli import main
from aletheia_nexus.research_planner import planning_request

app = application_fixture


@pytest.mark.parametrize("strategy", ["direct", "source_first"])
def test_cli_strategy_applied_to_new_draft_without_extra_planning(
    app, monkeypatch, capsys, strategy
):
    service, pdf = app
    planning_calls = []

    def draft(application, request, *, authorization):
        application.consume(authorization, "plan", request)
        planning_calls.append(deepcopy(request))
        task = task_for(request["documents"], mode="parsed")
        task["budget"] = request["research_budget"]
        checked = application.validate_research_task(task)
        original = application.workspace / "planning" / "mock" / "task.json"
        write_json(original, checked["task"])
        return {**checked, "task_file": str(original)}

    monkeypatch.setattr("aletheia_nexus.research_ask.draft_task", draft)
    assert (
        main(
            [
                "ask",
                "整理方法和条件",
                "--papers",
                str(pdf.parent),
                "--output-dir",
                str(service.workspace),
                "--allow-planning",
                "--extraction-strategy",
                strategy,
                "--non-interactive",
                "--save-only",
            ]
        )
        == 0
    )
    assert len(planning_calls) == 1
    saved = list((service.workspace / "tasks").glob("*.json"))
    assert len(saved) == 1
    task = json.loads(saved[0].read_text(encoding="utf-8"))
    assert task["extraction_strategy"] == strategy
    original = json.loads(
        (service.workspace / "planning/mock/task.json").read_text(encoding="utf-8")
    )
    assert "extraction_strategy" not in original
    output = capsys.readouterr().out
    assert service.binding("execute", task) in output
    if strategy == "source_first":
        assert "至少2次模型调用" in output
    assert not (service.workspace / "research").exists()


def test_cli_strategy_loaded_task_requires_new_confirmation_and_executes_saved_selection(
    app, monkeypatch, capsys
):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = service.validate_research_task(task_for(documents, mode="parsed"))["task"]
    path = service.workspace / "user-original-task.json"
    write_json(path, task)
    original = path.read_bytes()
    old_binding = service.binding("execute", task)
    arguments = [
        "ask",
        "--papers",
        str(pdf.parent),
        "--output-dir",
        str(service.workspace),
        "--task",
        str(path),
        "--extraction-strategy",
        "source_first",
        "--non-interactive",
        "--execute",
        "--allow-remote",
        "--confirm-plan",
    ]
    assert main([*arguments, old_binding]) == 2
    assert path.read_bytes() == original
    assert not (service.workspace / "research").exists()
    saved = list((service.workspace / "tasks").glob("*.json"))
    assert len(saved) == 1
    selected = json.loads(saved[0].read_text(encoding="utf-8"))
    assert selected["extraction_strategy"] == "source_first"
    binding = service.binding("execute", selected)
    assert binding != old_binding
    executed = []

    def execute(application, payload, *, authorization, background):
        assert background is False
        application.consume(authorization, "execute", payload)
        executed.append(deepcopy(payload))
        return {"status": "COMPLETED", "directory": str(application.workspace)}

    monkeypatch.setattr(
        "aletheia_nexus.research_app.ResearchApplication.execute_research_task", execute
    )
    assert main([*arguments, binding]) == 0
    assert executed == [selected]
    assert path.read_bytes() == original
    assert "至少2次模型调用" in capsys.readouterr().out


def test_cli_strategy_new_copy_preserves_user_edit_under_same_digest_name(app):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    original = service.workspace / "original-task.json"
    task = task_for(documents, mode="parsed")
    write_json(original, task)
    arguments = ["ask", "--papers", str(pdf.parent), "--output-dir", str(service.workspace),
                 "--task", str(original), "--extraction-strategy", "source_first",
                 "--non-interactive", "--save-only"]
    assert main(arguments) == 0
    first = next((service.workspace / "tasks").glob("*.json"))
    edited = json.loads(first.read_text(encoding="utf-8"))
    edited["objective"] = "用户手工修订的研究目标"
    write_json(first, edited, overwrite=True)
    retained = first.read_bytes()
    assert main(arguments) == 0
    saved = list((service.workspace / "tasks").glob("*.json"))
    assert len(saved) == 2
    assert first.read_bytes() == retained
    second = next(path for path in saved if path != first)
    assert second.name.split("-", 1)[0] == first.name.split("-", 1)[0]
    assert json.loads(second.read_text(encoding="utf-8"))["objective"] == task["objective"]


def test_cli_local_saved_plan_execution_without_key(app, monkeypatch):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = service.validate_research_task(task_for(documents))["task"]
    path = service.workspace / "local-task.json"
    write_json(path, task)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert (
        main(
            [
                "ask",
                "--papers",
                str(pdf.parent),
                "--output-dir",
                str(service.workspace),
                "--task",
                str(path),
                "--non-interactive",
                "--execute",
                "--confirm-plan",
            service.binding("execute", task),
            ]
        )
        == 0
    )


def test_cli_noninteractive_does_not_accept_model_plan_as_user_consent(app):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = task_for(documents, mode="parsed")
    path = service.workspace / "task.json"
    write_json(path, task)
    assert (
        main(
            [
                "ask",
                "--papers",
                str(pdf.parent),
                "--output-dir",
                str(service.workspace),
                "--task",
                str(path),
                "--non-interactive",
                "--execute",
                "--allow-remote",
            ]
        )
        == 2
    )
    assert not (service.workspace / "research").exists()


def test_cli_first_metadata_upload_requires_explicit_consent(app, monkeypatch):
    service, pdf = app
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-call")
    assert (
        main(
            [
                "ask",
                "提取方法",
                "--papers",
                str(pdf.parent),
                "--output-dir",
                str(service.workspace),
                "--non-interactive",
            ]
        )
        == 2
    )
    assert not (service.workspace / "planning").exists()


def test_old_confirmation_rejected_when_parsed_artifact_changes(app):
    from aletheia_nexus.content.parser import ParserConfig
    from aletheia_nexus.content.service import parse_document
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = service.validate_research_task(task_for(documents))["task"]
    binding = service.binding("execute", task)
    path = service.workspace / "task.json"
    write_json(path, task)
    replacement = service.workspace / "new-parsed.json"
    parse_document(documents[0]["pdf"], sidecar_path=documents[0]["sidecar"],
                   output_path=replacement, config=ParserConfig(merge_paragraph_lines=False))
    Path(documents[0]["artifact"]).write_bytes(replacement.read_bytes())
    assert service.binding("execute", task) != binding
    assert main(["ask", "--papers", str(pdf.parent), "--output-dir", str(service.workspace),
                 "--task", str(path), "--non-interactive", "--execute", "--confirm-plan", binding]) == 2
    assert not (service.workspace / "research").exists()


def test_authorize_requires_review_and_prints_one_use_token(app, capsys):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    request = planning_request(service, "整理方法", documents)
    challenge = service.authorization_request("plan", request)
    path = Path(challenge["authorization_request"])
    assert main(["authorize", str(path)]) == 2
    binding = json.loads(path.read_text(encoding="utf-8"))["binding"]
    assert main(["authorize", str(path), "--approve-fingerprint", binding]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    assert len(token) == 64
    service.consume(token, "plan", request)
