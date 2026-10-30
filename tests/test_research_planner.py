"""Intent API transport and explicit consent; scientific extraction is tested elsewhere."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_research_app import app as application_fixture

from aletheia_nexus.processing.contracts import TASK_SCHEMA
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_planner import bind_draft, draft_task, planning_request

app = application_fixture


def draft_for(request):
    return {
        "schema": TASK_SCHEMA,
        "id": "intent",
        "type": "extract",
        "objective": request["goal"],
        "documents": [{"id": d["id"]} for d in request["documents"]],
        "fields": [
            {
                "id": "method",
                "label": "方法",
                "description": "主实验和对照分别整理",
                "type": "string_list",
                "unit": None,
                "scope": "本论文的主实验和对照",
            }
        ],
        "rules": ["不补写缺失条件"],
        "include_steps": False,
        "include_claims": True,
        "synthesize": False,
        "export_formats": ["markdown", "csv", "jsonl"],
    }


def setup_request(app):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    return service, planning_request(
        service, "提取主实验和对照的方法，生成中文表格", documents
    )


def envelope(draft):
    return {
        "status": "completed",
        "usage": {"input_tokens": 1000, "output_tokens": 1000},
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(draft, ensure_ascii=False),
                    }
                ],
            }
        ],
    }


def test_planning_metadata_only_separate_account_and_no_code_execution(
    app, monkeypatch
):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-never-persist")
    sent = []

    def handle(http_request):
        payload = json.loads(http_request.content)
        sent.append(payload)
        text = json.dumps(payload, ensure_ascii=False)
        assert "25 C" not in text and str(service.workspace) not in text
        assert "materials" not in text
        draft = draft_for(request)
        draft["objective"] += "; $(Remove-Item /)"
        return httpx.Response(200, json=envelope(draft))

    token = service.authorize("plan", request)
    result = draft_task(
        service, request, authorization=token, transport=httpx.MockTransport(handle)
    )
    assert len(sent) == 1
    assert result["task"]["documents"] == request["documents"]
    assert result["task"]["extraction_strategy"] == "source_first"
    assert result["task"]["budget"] == request["research_budget"]
    assert "至少2次模型调用" in result["plan"]
    manifest = json.loads(
        (Path(result["planning_directory"]) / "manifest.json").read_text()
    )
    assert manifest["status"] == "COMPLETED" and len(manifest["calls"]) == 1
    assert manifest["calls"][0]["phase"] == "task_planning"
    assert not (service.workspace / "research").exists()
    assert all(
        "test-key-never-persist" not in p.read_text(encoding="utf-8")
        for p in service.workspace.rglob("*.json")
    )


def test_planner_invalid_json_one_repair_and_scope_cannot_expand(app, monkeypatch):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    sent = []

    def handle(http_request):
        sent.append(json.loads(http_request.content))
        if len(sent) == 1:
            return httpx.Response(200, json=envelope({"not": "a task"}))
        return httpx.Response(200, json=envelope(draft_for(request)))

    result = draft_task(
        service,
        request,
        authorization=service.authorize("plan", request),
        transport=httpx.MockTransport(handle),
    )
    assert len(sent) == 2 and result["task"]["schema"] == TASK_SCHEMA
    changed = draft_for(request)
    changed["documents"].append({"id": "other"})
    with pytest.raises(ValueError):
        bind_draft(changed, request)


@pytest.mark.parametrize(
    "status,expected,attempts",
    [
        (401, "authentication_failed", 1),
        (403, "permission_denied", 1),
        (429, "rate_limited", 2),
        (500, "service_error", 2),
    ],
)
def test_planning_error_classes(app, monkeypatch, status, expected, attempts):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    calls = []

    def handle(http_request):
        calls.append(1)
        return httpx.Response(status, json={"error": "private request body"})

    with pytest.raises(ProcessingError, match=expected):
        draft_task(
            service,
            request,
            authorization=service.authorize("plan", request),
            transport=httpx.MockTransport(handle),
        )
    assert len(calls) == attempts


def test_missing_key_and_unapproved_planner_never_posts(app, monkeypatch):
    service, request = setup_request(app)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ProcessingError, match="local_authorization_required"):
        draft_task(service, request, authorization="true")
    with pytest.raises(ProcessingError, match="missing_api_key"):
        draft_task(service, request, authorization=service.authorize("plan", request))


def test_planning_cost_cap_stops_before_http_and_records_failure(app, monkeypatch):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    request = deepcopy(request)
    request["planning_budget"]["max_cost"] = 0.001
    calls = []
    with pytest.raises(ProcessingError, match="cost_budget_exhausted"):
        draft_task(
            service,
            request,
            authorization=service.authorize("plan", request),
            transport=httpx.MockTransport(lambda r: calls.append(r)),
        )
    assert not calls
    manifests = list((service.workspace / "planning").glob("*/manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["status"] == "FAILED"
