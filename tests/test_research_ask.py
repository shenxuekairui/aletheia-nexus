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


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_invalid_character_limit_rejected_before_preparation_or_planning(
    tmp_path, monkeypatch, limit
):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid limits must not prepare files or pay for a planner")

    monkeypatch.setattr("aletheia_nexus.research_ask.ResearchApplication", unexpected)
    with pytest.raises(SystemExit) as stopped:
        main(
            [
                "ask",
                "整理这些论文",
                "--papers",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "output"),
                "--max-input-characters",
                limit,
                "--allow-planning",
            ]
        )
    assert stopped.value.code == 2
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    ("strategy", "presentation"),
    [
        ("direct", None),
        ("source_first", None),
        (None, "compact"),
        ("source_first", "compact"),
    ],
)
def test_cli_strategy_applied_to_new_draft_without_extra_planning(
    app, monkeypatch, capsys, strategy, presentation
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
    selected_args = []
    if strategy:
        selected_args += ["--extraction-strategy", strategy]
    if presentation:
        selected_args += ["--material-presentation", presentation]
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
                *selected_args,
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
    if strategy:
        assert task["extraction_strategy"] == strategy
    else:
        assert "extraction_strategy" not in task
    if presentation:
        assert task["material_presentation"] == presentation
    else:
        assert "material_presentation" not in task
    original = json.loads(
        (service.workspace / "planning/mock/task.json").read_text(encoding="utf-8")
    )
    assert "extraction_strategy" not in original
    assert "material_presentation" not in original
    output = capsys.readouterr().out
    assert service.binding("execute", task) in output
    if strategy == "source_first":
        assert "至少2次模型调用" in output
    assert ("材料呈现：精简（compact）" in output) == (presentation == "compact")
    assert not (service.workspace / "research").exists()


@pytest.mark.parametrize(
    ("option", "value"),
    [("extraction_strategy", "source_first"), ("material_presentation", "compact")],
)
def test_cli_strategy_loaded_task_requires_new_confirmation_and_executes_saved_selection(
    app, monkeypatch, capsys, option, value
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
        "--" + option.replace("_", "-"),
        value,
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
    assert selected[option] == value
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
    output = capsys.readouterr().out
    assert (
        "至少2次模型调用"
        if option == "extraction_strategy"
        else "材料呈现：精简（compact）"
    ) in output


def test_cli_strategy_new_copy_preserves_user_edit_under_same_digest_name(app):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    original = service.workspace / "original-task.json"
    task = task_for(documents, mode="parsed")
    write_json(original, task)
    arguments = [
        "ask",
        "--papers",
        str(pdf.parent),
        "--output-dir",
        str(service.workspace),
        "--task",
        str(original),
        "--extraction-strategy",
        "source_first",
        "--non-interactive",
        "--save-only",
    ]
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
    assert (
        json.loads(second.read_text(encoding="utf-8"))["objective"] == task["objective"]
    )


@pytest.mark.parametrize("presentation", [None, "compact"])
def test_cli_local_saved_plan_execution_without_key(app, monkeypatch, presentation):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = service.validate_research_task(task_for(documents))["task"]
    path = service.workspace / "local-task.json"
    write_json(path, task)
    expected = {
        **task,
        **({"material_presentation": presentation} if presentation else {}),
    }
    original = path.read_bytes()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(
        "aletheia_nexus.processing.engine.DeepSeekProvider",
        lambda *args, **kwargs: pytest.fail(
            "local mode must not create a remote provider"
        ),
    )
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
                *(["--material-presentation", presentation] if presentation else []),
                "--non-interactive",
                "--execute",
                "--confirm-plan",
                service.binding("execute", expected),
            ]
        )
        == 0
    )
    assert path.read_bytes() == original
    if presentation:
        saved = list((service.workspace / "tasks").glob("*.json"))
        assert len(saved) == 1
        assert (
            json.loads(saved[0].read_text(encoding="utf-8"))["material_presentation"]
            == presentation
        )
    else:
        assert "material_presentation" not in json.loads(
            path.read_text(encoding="utf-8")
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


def test_cli_rejects_legacy_strategy_before_planning_or_execution(
    app, monkeypatch, capsys
):
    service, pdf = app
    task = task_for(
        [{"id": "unread", "artifact": str(pdf.parent / "missing.parsed.json")}]
    )
    task.update(
        extraction_strategy="field_independent",
        include_steps=False,
        include_claims=False,
    )
    path = service.workspace / "legacy-task.json"
    write_json(path, task)
    original = path.read_bytes()
    monkeypatch.setattr(
        "aletheia_nexus.research_ask.draft_task",
        lambda *a, **k: pytest.fail("must not plan"),
    )
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
    assert (
        "field_independent_retired_use_source_first_or_direct_and_preview_again"
        in capsys.readouterr().err
    )
    assert path.read_bytes() == original
    assert not (service.workspace / "jobs").exists()
    assert not (service.workspace / "research").exists()
    with pytest.raises(SystemExit) as error:
        main(["ask", "--extraction-strategy", "field_independent"])
    assert error.value.code == 2


@pytest.mark.parametrize("status", ["FAILED", "PARTIAL"])
def test_cli_explains_saved_document_and_comparison_errors_locally(
    app, monkeypatch, capsys, status
):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = service.validate_research_task(task_for(documents))["task"]
    task_file = service.workspace / "local-error-task.json"
    write_json(task_file, task)

    def failed_run(payload, *, output_dir, **kwargs):
        directory = Path(output_dir) / "runs" / "synthetic-failure"
        manifest = {
            "status": status,
            "run_directory": str(directory),
            "usage": {"http_attempts": 0},
            "outputs": [],
            "items": [
                {
                    "id": documents[0]["id"],
                    "source": {"title": "自编方法论文"},
                    "error": "input_budget_exceeded",
                }
            ],
            "comparison": {"error": "cost_budget_exhausted"},
        }
        write_json(directory / "manifest.json", manifest)
        return manifest

    monkeypatch.setattr("aletheia_nexus.research_app.run_task", failed_run)
    assert main(
        [
            "ask",
            "--papers",
            str(pdf.parent),
            "--output-dir",
            str(service.workspace),
            "--task",
            str(task_file),
            "--non-interactive",
            "--execute",
            "--confirm-plan",
            service.binding("execute", task),
        ]
    ) == (1 if status == "FAILED" else 0)
    output = capsys.readouterr().out
    assert "自编方法论文 · input_budget_exceeded" in output
    assert "超出字符预算" in output and "请求未发送" in output
    assert "跨文献综合 · cost_budget_exhausted" in output and "费用上限" in output
    assert "--max-input-characters" in output


def test_cli_saved_task_input_limit_requires_new_preview_and_confirmation(
    app, monkeypatch, capsys
):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = service.validate_research_task(task_for(documents, mode="parsed"))["task"]
    path = service.workspace / "original-limit.json"
    write_json(path, task)
    original = path.read_bytes()
    arguments = [
        "ask",
        "--papers",
        str(pdf.parent),
        "--output-dir",
        str(service.workspace),
        "--task",
        str(path),
        "--max-input-characters",
        "200000",
        "--non-interactive",
        "--execute",
        "--allow-remote",
        "--confirm-plan",
    ]
    assert main([*arguments, service.binding("execute", task)]) == 2
    saved = next((service.workspace / "tasks").glob("*.json"))
    selected = json.loads(saved.read_text("utf8"))
    assert selected["budget"] == {**task["budget"], "max_input_characters": 200000}
    assert selected["documents"] == task["documents"] and path.read_bytes() == original
    executed = []

    def execute(application, payload, *, authorization, background):
        application.consume(authorization, "execute", payload)
        executed.append(deepcopy(payload))
        return {"status": "COMPLETED", "directory": str(application.workspace)}

    monkeypatch.setattr(
        "aletheia_nexus.research_app.ResearchApplication.execute_research_task", execute
    )
    assert main([*arguments, service.binding("execute", selected)]) == 0
    assert executed == [selected] and path.read_bytes() == original
    assert "输入字符上限：200000" in capsys.readouterr().out


def test_cli_new_natural_language_plan_applies_explicit_input_limit_once(
    app, monkeypatch
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
                "整理研究目标和条件",
                "--papers",
                str(pdf.parent),
                "--output-dir",
                str(service.workspace),
                "--allow-planning",
                "--max-input-characters",
                "200000",
                "--non-interactive",
                "--save-only",
            ]
        )
        == 0
    )
    assert len(planning_calls) == 1
    selected = json.loads(
        next((service.workspace / "tasks").glob("*.json")).read_text("utf8")
    )
    assert selected["budget"] == {
        **planning_calls[0]["research_budget"],
        "max_input_characters": 200000,
    }
    original = json.loads(
        (service.workspace / "planning/mock/task.json").read_text("utf8")
    )
    assert original["budget"]["max_input_characters"] == 100000
    assert selected["documents"] == original["documents"]
