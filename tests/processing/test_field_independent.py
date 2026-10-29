"""Optional independent fields use self-authored material and native execution."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_workflow import papers as papers
from test_workflow import response_for, task_for

from aletheia_nexus.processing.contracts import digest, validate_task
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.provider import DeepSeekProvider, ProcessingError
from aletheia_nexus.processing.results import verify_result


def independent_task(papers, *, compare=False):
    task = task_for(papers, kind="compare" if compare else "organize")
    task.update(
        extraction_strategy="field_independent",
        include_steps=False,
        include_claims=False,
    )
    task["budget"].update(
        max_review_rounds=0, max_repair_rounds=0, max_supplement_rounds=0
    )
    task["fields"] += [
        {
            "id": "evidence",
            "type": "string_list",
            "description": "Preserve the observations and qualifications",
        }
    ]
    return task


def wire_response(request):
    response = response_for(request)
    record = response["records"][0]
    record["id"] = request["record_context"][0]["id"]
    record.pop("subject")
    record.pop("stage")
    record.pop("steps")
    for definition in request["fields"]:
        field = record["fields"][definition["id"]]
        field["step_ids"] = []
        if definition["type"] == "string_list":
            field["value"] = [field["value"], field["value"]]
        elif definition["type"] == "number":
            field.update(value=6.0, raw_value="6 h", unit="h")
        elif definition["type"] == "boolean":
            field.update(value=False, raw_value="not measured")
    return response


class FieldProvider:
    identity = {"provider": "self-authored-field-mock", "version": "1"}

    def __init__(self, *, fail_field_once=None, metadata=False):
        self.fail_field_once = fail_field_once
        self.metadata = metadata
        self.requests = []
        self.outputs = []

    def generate(self, request, schema, images, budget, max_output_tokens):
        call = budget.reserve(None)
        self.requests.append(deepcopy(request))
        if request["phase"] == "cross_document_synthesis":
            response = {
                "claims": [
                    {
                        "text": "Synthetic cross-paper comparison",
                        "nature": "ai_synthesis",
                        "citations": [],
                    }
                ],
                "issues": [],
            }
        else:
            fid = request["fields"][0]["id"]
            if fid == self.fail_field_once:
                self.fail_field_once = None
                call["status"] = "network_error"
                budget.checkpoint()
                raise ProcessingError("network_error")
            response = wire_response(request)
            if self.metadata and fid == "method":
                del response["records"][0]["fields"][fid]["step_ids"]
                response["debug_extension"] = None
        call.update(status="completed", usage={"input_tokens": 10, "output_tokens": 10})
        budget.checkpoint()
        self.outputs.append(deepcopy(response))
        return response


def result_for(run):
    result = json.loads(
        (Path(run["run_directory"]) / run["items"][0]["result"]).read_text("utf-8")
    )
    verify_result(result)
    return result


def test_independent_typed_fields_exact_archive_and_zero_call_resume(papers, tmp_path):
    task = independent_task(papers[:1])
    task["fields"] += [
        {
            "id": "duration",
            "type": "number",
            "description": "Duration and original unit",
        },
        {"id": "measured", "type": "boolean", "description": "Whether measured"},
    ]
    provider = FieldProvider()
    kwargs = dict(
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    first = run_task(task, **kwargs)
    result = result_for(first)
    record = result["response"]["records"][0]
    assert record["id"] == "paper0" and record["stage"] == "document"
    assert record["steps"] == result["response"]["claims"] == []
    assert len(provider.requests) == 4
    for request, output in zip(provider.requests, provider.outputs):
        fid = request["fields"][0]["id"]
        assert record["fields"][fid] == output["records"][0]["fields"][fid]
        assert len(request["fields"]) == 1 and "ai_reading_draft" not in request
        assert request["material"] == provider.requests[0]["material"]
    assert record["fields"]["measured"]["value"] is False
    assert record["fields"]["duration"]["unit"] == "h"
    assert len(record["fields"]["evidence"]["value"]) == 2
    resumed = run_task(task, **kwargs)
    assert resumed["items"][0]["reused"] and len(provider.requests) == 4
    assert all(s["reused"] for s in resumed["items"][0]["field_stages"])
    assert len(resumed["calls"]) == 0
    assert result_for(resumed)["artifact_id"] == result["artifact_id"]
    assert (Path(resumed["run_directory"]) / "records.jsonl").is_file()


def test_successful_field_is_retained_after_later_technical_failure(papers, tmp_path):
    task = independent_task(papers[:1])
    provider = FieldProvider(fail_field_once="evidence", metadata=True)
    kwargs = dict(
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    failed = run_task(task, **kwargs)
    assert failed["items"][0]["status"] == "FAILED"
    assert len(failed["calls"]) == 2 and not list(
        Path(failed["run_directory"]).glob("*.result.json")
    )
    assert failed["items"][0]["field_stages"][0]["status"] == "COMPLETED"
    resumed = run_task(task, **kwargs)
    assert resumed["items"][0]["status"] == "COMPLETED"
    assert [r["fields"][0]["id"] for r in provider.requests] == [
        "method",
        "evidence",
        "evidence",
    ]
    stages = resumed["items"][0]["field_stages"]
    assert stages[0]["reused"] and not stages[1]["reused"]
    assert stages[0]["usage_owner_run"] == failed["run_directory"]
    assert len(resumed["calls"]) == 1
    first_proof = failed["items"][0]["response_metadata"][0]["file"]
    assert (Path(failed["run_directory"]) / first_proof).read_bytes() == (
        Path(resumed["run_directory"]) / first_proof
    ).read_bytes()
    result_for(resumed)


@pytest.mark.parametrize(
    "option,value",
    [
        ("include_steps", True),
        ("include_claims", True),
        ("type", "procedure"),
        ("source_assembly", "model"),
        ("max_review_rounds", 1),
    ],
)
def test_incompatible_scope_is_explicitly_rejected(papers, option, value):
    task = independent_task(papers[:1])
    if option == "max_review_rounds":
        task["budget"][option] = value
    else:
        task[option] = value
    with pytest.raises(ValueError, match="field_independent"):
        validate_task(task)


def test_task_change_invalidates_field_cache_and_unrecoverable_success_is_not_repaid(
    papers, tmp_path
):
    task = independent_task(papers[:1])
    provider = FieldProvider()
    kwargs = dict(
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    first = run_task(task, **kwargs)
    assert len(provider.requests) == 2
    # Keep the successful owner and pending proof but corrupt a stage cache.
    cache = next(
        p
        for p in (tmp_path / "out/cache").glob("field-*.json")
        if not p.name.endswith(".pending.json")
    )
    artifact = json.loads(cache.read_text("utf-8"))
    artifact["field_raw_response"]["records"][0]["fields"][
        artifact["result"]["task"]["fields"][0]["id"]
    ]["value"] = "Changed source reading"
    artifact["field_artifact_id"] = "an:field-stage:sha256:" + digest(
        {k: v for k, v in artifact.items() if k != "field_artifact_id"}
    )
    cache.write_text(json.dumps(artifact), "utf-8")
    blocked = run_task(task, **kwargs)
    assert blocked["items"][0]["error"] == "field_stage_recovery_required"
    assert len(provider.requests) == 2 and len(blocked["calls"]) == 0
    changed = deepcopy(task)
    changed["fields"][0]["description"] += "; retain context"
    new = run_task(changed, **kwargs)
    assert new["items"][0]["status"] == "COMPLETED" and len(provider.requests) == 4
    assert not new["items"][0]["reused"]
    assert first["provider"] == new["provider"]


def test_multiple_papers_keep_native_cross_document_comparison(papers, tmp_path):
    task = independent_task(papers, compare=True)
    provider = FieldProvider()
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    assert run["comparison"]["status"] == "COMPLETED"
    assert len(provider.requests) == 5 and len(run["items"]) == 2
    assert provider.requests[-1]["phase"] == "cross_document_synthesis"
    assert all(
        len(
            json.loads((Path(run["run_directory"]) / row["result"]).read_text("utf-8"))[
                "response"
            ]["records"]
        )
        == 1
        for row in run["items"]
    )


def test_local_mode_never_calls_field_provider(papers, tmp_path):
    task = independent_task(papers[:1])
    task["mode"] = "local"
    provider = FieldProvider()
    run_task(task, base_dir=tmp_path, output_dir=tmp_path / "out", provider=provider)
    assert provider.requests == []


def test_shared_call_budget_does_not_expand_and_resume_uses_completed_field(
    papers, tmp_path
):
    task = independent_task(papers[:1])
    task["budget"]["max_calls"] = 1
    provider = FieldProvider()
    kwargs = dict(
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    failed = run_task(task, **kwargs)
    assert failed["items"][0]["status"] == "FAILED" and len(failed["calls"]) == 1
    assert len(provider.requests) == 1
    completed = run_task(task, **kwargs)
    assert completed["items"][0]["status"] == "COMPLETED"
    assert len(completed["calls"]) == 1 and len(provider.requests) == 2
    assert completed["items"][0]["field_stages"][0]["reused"]


def test_native_serializer_uses_independent_field_schemas_and_identical_images(
    papers, tmp_path, monkeypatch
):
    task = independent_task(papers[:1])
    task["mode"] = "hybrid"
    task["documents"][0]["image_pages"] = [1]
    task["model"] = {
        "name": "deepseek-flash",
        "max_retries": 0,
        "min_interval_seconds": 0,
    }
    monkeypatch.setenv("DEEPSEEK_API_KEY", "self-authored-mock-key")
    captures = []

    def handler(http_request):
        payload = json.loads(http_request.content)
        request = json.loads(payload["input"][0]["content"][0]["text"])
        row = payload["text"]["format"]["schema"]["properties"]["records"]["items"]
        assert set(row["properties"]) == {"id", "fields"}
        assert (
            len(request["fields"]) == 1
            and request["include_steps"] is False
            and request["include_claims"] is False
        )
        captures.append(payload)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(wire_response(request)),
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    provider = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    assert run["items"][0]["status"] == "COMPLETED" and len(captures) == 2
    image_payloads = [
        [c for c in p["input"][0]["content"] if c["type"] == "input_image"]
        for p in captures
    ]
    assert image_payloads[0] == image_payloads[1] and len(image_payloads[0]) == 1
    assert all(c["prompt_version"] == "literature-extraction/13" for c in run["calls"])
    result_for(run)
