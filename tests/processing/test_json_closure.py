"""Closing-only recovery uses synthetic content and actual native adapter/cache paths."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_source_first import inventory_for, source_task
from test_workflow import papers as papers
from test_workflow import response_for

from aletheia_nexus.processing.contracts import TEXT, digest, obj
from aletheia_nexus.processing.engine import _verify_inventory_artifact, run_task
from aletheia_nexus.processing.provider import (
    CallBudget,
    DeepSeekProvider,
    ProcessingError,
    ProjectedResponse,
    decode_response,
    project_response,
    raw_response_value,
)
from aletheia_nexus.processing.results import verify_result
from aletheia_nexus.processing.source_first import INVENTORY_PHASE, inventory_schema


def body(raw, status="completed", **extra):
    return {
        "status": status,
        "usage": {"input_tokens": 5, "output_tokens": 3},
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": raw}]}
        ],
        **extra,
    }


def adapter(monkeypatch, response):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key")
    return DeepSeekProvider(
        {"name": "deepseek-flash", "max_retries": 0, "min_interval_seconds": 0},
        enabled=True,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        ),
    )


def test_completed_native_response_keeps_original_raw_and_reversible_closure(
    monkeypatch,
):
    schema = obj(
        {
            "sample": obj({"literal": TEXT, "value": {"type": "number"}}),
            "notes": {"type": "array", "items": TEXT},
        }
    )
    expected = {
        "sample": {"literal": '合成 AB7C² H₂O µM " } ]', "value": 0},
        "notes": [],
    }
    valid = json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
    pos = valid.index('},"notes"')
    raw = valid[:pos] + valid[pos + 1 :]
    delegate = adapter(monkeypatch, body(raw, model="synthetic-served-model"))
    budget = CallBudget(1)
    answer = delegate.generate({}, schema, [], budget, 1000)
    assert answer == expected and isinstance(answer, ProjectedResponse)
    assert answer.metadata["raw_text"] == raw
    closure = answer.metadata["json_closure"]
    assert closure["version"] == "closing-only-json/1" and closure["completed_response"]
    edit = closure["selected"]["insertion"]
    assert edit["characters"] in ("}", "]")
    assert raw_response_value(answer) == expected
    assert decode_response(raw, schema).metadata == answer.metadata
    assert len(budget.calls) == 1 and budget.calls[0]["status"] == "completed"
    assert budget.calls[0]["response_status"] == "completed"
    assert budget.calls[0]["returned_model"] == "synthetic-served-model"
    assert budget.calls[0]["model"] == "deepseek-flash"
    assert delegate.identity["adapter_version"] == "8"


@pytest.mark.parametrize(
    "response",
    [
        body(
            '{"value":"read"',
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
        ),
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "declined"}],
                }
            ],
        },
    ],
)
def test_incomplete_and_refused_responses_never_enter_closure(monkeypatch, response):
    delegate = adapter(monkeypatch, response)
    budget = CallBudget(1)
    with pytest.raises(ProcessingError, match="model_incomplete|model_refusal"):
        delegate.generate({}, obj({"value": TEXT}), [], budget, 1000)
    assert budget.calls[0]["response_status"] == response["status"]
    assert budget.calls[0]["status"] in {"model_incomplete", "model_refusal"}


@pytest.mark.parametrize(
    "extra",
    [
        {"finish_reason": "length"},
        {"incomplete_details": {"reason": "max_output_tokens"}},
    ],
)
def test_completed_label_with_truncation_signal_does_not_enable_recovery(
    monkeypatch, extra
):
    with pytest.raises(ProcessingError, match="invalid_model_output"):
        adapter(monkeypatch, body('{"value":"read"', **extra)).generate(
            {}, obj({"value": TEXT}), [], CallBudget(1), 1000
        )


@pytest.mark.parametrize(
    "raw",
    [
        '{"value":',
        '{"value":"unterminated',
        '{"value":"a" "other":"b"}',
        '{"value":false',
        '{"value":"a","value":"b"',
    ],
)
def test_closing_never_invents_values_quotes_commas_or_hides_type_errors(
    monkeypatch, raw
):
    with pytest.raises(ProcessingError, match="invalid_model_output"):
        adapter(monkeypatch, body(raw)).generate(
            {}, obj({"value": TEXT}), [], CallBudget(1), 1000
        )


def test_different_schema_interpretations_rejected_and_EOF_closure_is_bounded():
    optional = {
        "type": "object",
        "properties": {
            "a": {
                "type": "object",
                "properties": {"b": {"type": "number"}, "c": {"type": "number"}},
                "required": ["b"],
                "additionalProperties": False,
            },
            "c": {"type": "number"},
        },
        "required": ["a"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match="ambiguous"):
        decode_response('{"a":{"b":1,"c":2}', optional)
    nested = obj({"a": obj({"b": {"type": "number"}})})
    answer = decode_response('{"a":{"b":2', nested)
    assert answer == {"a": {"b": 2}}
    assert (
        answer.metadata["json_closure"]["selected"]["insertion"]["characters"] == "}}"
    )
    with pytest.raises(ValueError, match="resource limit"):
        decode_response(" " * 65537, nested)


def test_normal_valid_JSON_and_projection_metadata_remain_unchanged(monkeypatch):
    schema = obj({"value": TEXT})
    raw = '{"value":"unchanged"}'
    delegate = adapter(monkeypatch, body(raw))
    answer = delegate.generate({}, schema, [], CallBudget(1), 1000)
    assert answer == {"value": "unchanged"} and not isinstance(
        answer, ProjectedResponse
    )
    raw = '{"value":"unchanged","empty_extension":null}'
    assert (
        decode_response(raw, schema).metadata
        == project_response(json.loads(raw), schema, raw_text=raw).metadata
    )


def test_native_source_first_closures_survive_cache_and_trace_tampering(
    papers, tmp_path, monkeypatch
):
    task = source_task(papers)
    task["model"] = {
        "name": "deepseek-flash",
        "max_retries": 0,
        "min_interval_seconds": 0,
    }
    seen = []

    def handler(request):
        req = json.loads(json.loads(request.content)["input"][0]["content"][0]["text"])
        seen.append(req)
        answer = (
            inventory_for(req) if req["phase"] == INVENTORY_PHASE else response_for(req)
        )
        return httpx.Response(200, json=body(json.dumps(answer)[:-1]))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key")
    delegate = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    output = tmp_path / "output"
    args = dict(
        base_dir=tmp_path, output_dir=output, allow_remote=True, provider=delegate
    )
    first = run_task(task, **args)
    assert first["status"] == "COMPLETED" and len(seen) == 2
    row = first["items"][0]
    directory = Path(first["run_directory"])
    result = json.loads((directory / row["result"]).read_text("utf-8"))
    verify_result(result)
    assert len(row["response_metadata"]) == 2
    for entry in row["response_metadata"]:
        proof = json.loads((directory / entry["file"]).read_text("utf-8"))
        assert proof["json_closure"]["completed_response"]
        assert (
            decode_response(
                proof["raw_text"], proof["schema"], proof["targets"]
            ).metadata
            == proof
        )
    cached = run_task(task, **args)
    assert cached["items"][0]["reused"] and len(seen) == 2
    cache_file = next((output / "cache").glob("*.json"))
    envelope = json.loads(cache_file.read_text("utf-8"))
    entry = envelope["response_metadata"][-1]
    proof = envelope["metadata_artifacts"][entry["file"]]
    proof["json_closure"]["selected"]["insertion"]["characters"] = "]"
    entry["sha256"] = digest(proof)
    cache_file.write_text(json.dumps(envelope), "utf-8")
    rebuilt = run_task(task, **args)
    assert not rebuilt["items"][0]["reused"] and len(seen) > 2


def test_repaired_inventory_is_reused_after_assembly_failure_and_location_still_checked(
    papers, tmp_path, monkeypatch
):
    task = source_task(papers)
    task["model"] = {
        "name": "deepseek-flash",
        "max_retries": 0,
        "min_interval_seconds": 0,
    }
    phases, reject_assembly = [], [True]

    def handler(request):
        req = json.loads(json.loads(request.content)["input"][0]["content"][0]["text"])
        phases.append(req["phase"])
        if req["phase"] == INVENTORY_PHASE:
            raw = json.dumps(inventory_for(req))[:-1]
        elif reject_assembly[0]:
            raw = '{"records":'
        else:
            raw = json.dumps(response_for(req))[:-1]
        return httpx.Response(200, json=body(raw))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-key")
    delegate = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    args = dict(
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=delegate,
    )
    first = run_task(task, **args)
    assert first["status"] == "FAILED" and phases == [
        INVENTORY_PHASE,
        "document_extraction",
    ]
    reject_assembly[0] = False
    second = run_task(task, **args)
    assert second["status"] == "COMPLETED"
    assert phases == [INVENTORY_PHASE, "document_extraction", "document_extraction"]

    # Standalone cache restores its own raw/trace without another inventory call.
    row = second["items"][0]
    cached = json.loads(
        next((tmp_path / "out/cache").glob("source-inventory-*.json")).read_text(
            "utf-8"
        )
    )
    metadata_file = (
        Path(second["run_directory"]) / "paper0.0.source-inventory.metadata.json"
    )
    assert json.loads(metadata_file.read_text("utf-8")) == cached["response_metadata"]
    assert row["source_inventories"][0]["usage_owner_run"] == first["run_directory"]
    assert len(second["calls"]) == 1 and row["source_inventories"][0]["reused"]

    # Syntax recovery does not make an invented source page valid.
    from aletheia_nexus.processing.contracts import response_schema, validate_task
    from aletheia_nexus.processing.engine import _request
    from aletheia_nexus.processing.materials import build_package, load_source
    from aletheia_nexus.processing.results import check_response

    config = validate_task(task)
    package, _ = build_package(
        config, [load_source(d, tmp_path, config["mode"]) for d in config["documents"]]
    )
    _verify_inventory_artifact(cached, config, package)

    def rehash(artifact):
        artifact.pop("artifact_id", None)
        artifact["artifact_id"] = "an:source-inventory:sha256:" + digest(artifact)
        return artifact

    tampered = deepcopy(cached)
    tampered["response_metadata"]["json_closure"]["selected"]["insertion"][
        "characters"
    ] = "]"
    with pytest.raises(ValueError, match="metadata does not replay"):
        _verify_inventory_artifact(rehash(tampered), config, package)
    for raw_change in ("new_observation", "raw_only_empty_extension"):
        different_raw = deepcopy(cached["raw_response"])
        if raw_change == "new_observation":
            different_raw["items"][0]["observation"] += " Another reading."
        else:
            different_raw["empty_extension"] = None
        other_proof = decode_response(
            json.dumps(different_raw)[:-1], inventory_schema(config, package)
        ).metadata
        borrowed = {**cached, "response_metadata": other_proof}
        with pytest.raises(ValueError, match="belongs to another response"):
            _verify_inventory_artifact(rehash(borrowed), config, package)
    altered_contract = deepcopy(cached)
    altered_contract["response_metadata"]["targets"] = [
        {"target_id": "not-an-inventory-target"}
    ]
    with pytest.raises(ValueError, match="contract changed"):
        _verify_inventory_artifact(rehash(altered_contract), config, package)
    legacy = {k: v for k, v in cached.items() if k != "response_metadata"}
    _verify_inventory_artifact(rehash(legacy), config, package)
    req = _request(config, package)
    invalid = response_for(req)
    invalid["records"][0]["fields"]["method"]["citations"][0]["page"] = 999
    response = decode_response(json.dumps(invalid)[:-1], response_schema(config))
    with pytest.raises(ProcessingError, match="invalid_citation"):
        check_response(response, config, package)
