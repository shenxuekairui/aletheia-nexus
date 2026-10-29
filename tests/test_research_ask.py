"""CLI consent and saved-plan execution without paid requests."""

import json
from pathlib import Path

from test_research_app import app as application_fixture
from test_research_app import task_for

from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing_cli import main
from aletheia_nexus.research_planner import planning_request

app = application_fixture


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
    parse_document(
        documents[0]["pdf"],
        sidecar_path=documents[0]["sidecar"],
        output_path=replacement,
        config=ParserConfig(merge_paragraph_lines=False),
    )
    Path(documents[0]["artifact"]).write_bytes(replacement.read_bytes())
    assert service.binding("execute", task) != binding
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
                binding,
            ]
        )
        == 2
    )
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
