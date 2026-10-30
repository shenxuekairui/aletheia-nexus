"""Self-authored fixtures for metadata-only delivery recovery, not science scores."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_workflow import MockProvider, response_for, task_for
from test_workflow import papers as papers

from aletheia_nexus.processing.contracts import response_schema, validate_task
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.materials import build_package, load_source
from aletheia_nexus.processing.provider import (
    CallBudget,
    DeepSeekProvider,
    ProcessingError,
    ProjectedResponse,
    decode_response,
    project_response,
    raw_response_value,
)
from aletheia_nexus.processing.results import (
    check_response,
    make_result,
    revise_result,
    verify_result,
)
from aletheia_nexus.processing.review import (
    apply_revision,
    review_targets,
    revision_schema,
)


def material(papers, tmp_path):
    task = validate_task(task_for(papers[:1]))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    return task, package, response


def test_missing_field_step_links_native_transport_keeps_raw_and_replays(
    papers, tmp_path, monkeypatch
):
    task, package, raw = material(papers, tmp_path)
    del raw["records"][0]["fields"]["method"]["step_ids"]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(raw)}],
                    }
                ],
            },
        )

    adapter = DeepSeekProvider(
        {"name": "deepseek-flash"},
        enabled=True,
        transport=httpx.MockTransport(handler),
    )
    schema = response_schema(task)
    budget = CallBudget(1)
    projected = adapter.generate(
        {"phase": "document_extraction"}, schema, [], budget, 1000
    )
    assert isinstance(projected, ProjectedResponse)
    assert raw_response_value(projected) == raw
    expected = deepcopy(raw)
    expected["records"][0]["fields"]["method"]["step_ids"] = []
    assert projected == expected
    assert projected.metadata["changes"] == [
        {
            "operation": "add",
            "path": ["records", 0, "fields", "method", "step_ids"],
            "value": [],
            "reason": "unprovided_field_step_links",
        }
    ]
    replayed = decode_response(projected.metadata["raw_text"], schema)
    assert replayed == projected and replayed.metadata == projected.metadata
    assert len(budget.calls) == 1
    check_response(projected, task, package)


@pytest.mark.parametrize(
    "fault", ["record_steps", "explicit_null", "scientific_value", "unknown_step"]
)
def test_metadata_recovery_does_not_invent_steps_values_or_fix_bad_links(
    papers, tmp_path, fault
):
    task, package, raw = material(papers, tmp_path)
    if fault == "record_steps":
        del raw["records"][0]["steps"]
    elif fault == "explicit_null":
        raw["records"][0]["fields"]["method"]["step_ids"] = None
    elif fault == "scientific_value":
        del raw["records"][0]["fields"]["method"]["value"]
    else:
        raw["records"][0]["fields"]["method"]["step_ids"] = ["not_a_supplied_step"]
        with pytest.raises(ProcessingError, match="invalid_step_reference"):
            check_response(project_response(raw, response_schema(task)), task, package)
        return
    with pytest.raises(ValueError):
        project_response(raw, response_schema(task))


def test_unlocated_issue_and_unlinked_field_survive_cache_revision_and_exports(
    papers, tmp_path
):
    task = task_for(papers[:1])
    issue = {
        "kind": "source_ambiguous",
        "detail": "Synthetic diagnosis remains unverified.",
        "source_id": "paper0",
        "page": 999,
    }

    def generate(request):
        response = response_for(request)
        del response["records"][0]["fields"]["method"]["step_ids"]
        response["issues"] = [deepcopy(issue)]
        return response

    mock = MockProvider(generate)
    output = tmp_path / "out"
    kwargs = dict(
        base_dir=tmp_path, output_dir=output, allow_remote=True, provider=mock
    )
    first = run_task(task, **kwargs)
    item = first["items"][0]
    assert item["status"] == "PARTIAL" and len(mock.requests) == 1
    run = Path(first["run_directory"])
    result = json.loads((run / item["result"]).read_text("utf-8"))
    verify_result(result)
    assert result["response"]["issues"] == [issue]
    assert result["response"]["records"][0]["fields"]["method"]["step_ids"] == []
    assert (
        result["validation"]["unresolved_issue_locations"]["0"]["reason"]
        == "page_out_of_range"
    )
    assert result["validation"]["record_states"]["r1"] == "review_required"
    metadata = json.loads(
        (run / item["response_metadata"][0]["file"]).read_text("utf-8")
    )
    assert (
        "step_ids"
        not in json.loads(metadata["raw_text"])["records"][0]["fields"]["method"]
    )
    cached = run_task(task, **kwargs)
    assert cached["items"][0]["reused"] and len(mock.requests) == 1
    assert (
        Path(cached["run_directory"]) / item["response_metadata"][0]["file"]
    ).read_bytes() == (run / item["response_metadata"][0]["file"]).read_bytes()
    report = (run / "report.md").read_text("utf-8")
    assert "提示位置未定位" in report and "#page=999" not in report
    exported = json.loads((run / "records.jsonl").read_text("utf-8").splitlines()[0])
    assert exported["unresolved_issues"][0]["issue"] == issue
    assert "999" not in (run / "table.csv").read_text("utf-8")
    corrected = revise_result(
        result,
        {
            "issue_index": 0,
            "replacement": {**issue, "page": 1},
            "authority": "assistant",
            "author": "Synthetic reviewer",
            "at": "2026-10-30",
            "reason": "Corrected only the fixture location",
            "confirm": False,
        },
    )
    verify_result(corrected)
    assert "unresolved_issue_locations" not in corrected["validation"]
    assert corrected["history"][-1]["before"] == issue
    assert result["response"]["issues"] == [issue]


def test_targeted_field_revision_defaults_only_missing_association_metadata(
    papers, tmp_path
):
    task, package, candidate = material(papers, tmp_path)
    tid = "record:0/field:method"
    review = {
        "checks": [
            {
                "target_id": tid,
                "verdict": "revise",
                "detail": "Synthetic metadata revision",
                "citations": [],
            }
        ],
        "issues": [],
        "requests": [],
    }
    field = deepcopy(candidate["records"][0]["fields"]["method"])
    del field["step_ids"]
    raw = {"replacements": {tid: field}, "issues": [], "requests": []}
    projected = project_response(
        raw, revision_schema(task, candidate, review), review_targets(candidate)
    )
    assert projected.metadata["changes"][0]["path"] == ["replacements", tid, "step_ids"]
    assert raw_response_value(projected) == raw
    revised = apply_revision(candidate, projected, task, review)
    assert revised["records"][0]["fields"]["method"]["step_ids"] == []
    assert revised["records"][0]["steps"] == candidate["records"][0]["steps"]
    check_response(revised, task, package)


def test_unknown_issue_source_keeps_original_but_citations_and_requests_still_fail(
    papers, tmp_path
):
    task, package, response = material(papers, tmp_path)
    issue = {
        "kind": "conflict",
        "detail": "Synthetic unresolved warning",
        "source_id": "unknown-paper",
        "page": 1,
    }
    response["issues"] = [issue]
    result = make_result(task, package, {"provider": "mock"}, response)
    verify_result(result)
    assert result["response"]["issues"] == [issue]
    assert (
        result["validation"]["unresolved_issue_locations"]["0"]["reason"]
        == "unknown_source"
    )
    assert result["validation"]["record_states"]["r1"] == "conflict"
    bad = deepcopy(response)
    bad["records"][0]["fields"]["method"]["citations"][0]["source_id"] = "unknown-paper"
    with pytest.raises(ProcessingError, match="invalid_citation"):
        check_response(bad, task, package)
    bad = deepcopy(response)
    bad["requests"] = [
        {"source_id": "paper0", "pages": [999], "reason": "Do not read beyond source"}
    ]
    with pytest.raises(ProcessingError, match="invalid_supplement_request"):
        check_response(bad, task, package)
