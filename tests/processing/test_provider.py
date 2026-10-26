import json
from copy import deepcopy

import httpx
import pytest

from aletheia_nexus.processing.contracts import TEXT, obj
from aletheia_nexus.processing.provider import (
    CallBudget,
    DeepSeekProvider,
    ProcessingError,
    ProjectedResponse,
    accounted_cost,
    project_response,
)


def test_known_usage_settles_reservation_but_unknown_failure_keeps_it():
    budget = CallBudget(4, max_cost=1)
    first = budget.reserve(0.8)
    first.update(status="invalid_model_output", estimated_cost=0.1)
    second = budget.reserve(0.8)
    second["status"] = "timeout"
    assert accounted_cost(first) == 0.1
    assert first["reserved_cost"] == 0.8
    assert accounted_cost(second) == 0.8
    with pytest.raises(ProcessingError, match="cost_budget_exhausted"):
        budget.reserve(0.2)
    first["estimated_cost"] = 0
    assert accounted_cost(first) == 0
    second["reserved_cost"] = None
    with pytest.raises(ProcessingError, match="cost_estimate_unavailable"):
        budget.reserve(0.1)


@pytest.mark.parametrize("bad_cost", [-1, float("nan"), float("inf"), True, "0.1"])
def test_ledger_rejects_invalid_cost(bad_cost):
    with pytest.raises(ValueError, match="invalid cost"):
        accounted_cost({"estimated_cost": bad_cost, "reserved_cost": 1})


@pytest.mark.parametrize("cached_tokens", [None, 80, 101])
def test_cache_price_uses_returned_usage_and_rejects_impossible_count(
    monkeypatch, cached_tokens
):
    usage = {"input_tokens": 100, "output_tokens": 10}
    if cached_tokens is not None:
        usage["input_tokens_details"] = {"cached_tokens": cached_tokens}
    body = {
        "status": "completed",
        "usage": usage,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"value":"ok"}'}],
            }
        ],
    }
    adapter = provider(monkeypatch, lambda request: httpx.Response(200, json=body))
    adapter.config.update(
        input_cost_per_million=2,
        cached_input_cost_per_million=0.04,
        output_cost_per_million=8,
    )
    budget = CallBudget(1, max_cost=1)
    if cached_tokens == 101:
        with pytest.raises(ProcessingError, match="invalid_model_output"):
            adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
        assert budget.calls[0]["estimated_cost"] is None
        assert accounted_cost(budget.calls[0]) == budget.calls[0]["reserved_cost"]
    else:
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
        expected = (20 * 2 + 80 * 0.04 + 10 * 8) / 1e6 if cached_tokens else 280 / 1e6
        assert budget.calls[0]["estimated_cost"] == pytest.approx(expected)
        assert budget.calls[0]["started_at"].endswith("+00:00")


def test_call_reservation_is_durable_before_network(monkeypatch):
    saved = []
    budget = CallBudget(2)
    budget.checkpoint = lambda: saved.append(json.loads(json.dumps(budget.calls)))

    def handler(request):
        assert saved[-1][0]["status"] == "started"
        assert saved[-1][0]["currency"] == "CNY"
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 100,
                    "output_tokens_details": {"reasoning_tokens": 90},
                },
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"value":'}],
                    }
                ],
            },
        )

    adapter = provider(monkeypatch, handler)
    with pytest.raises(ProcessingError) as caught:
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
    assert caught.value.code == "model_incomplete"
    assert caught.value.diagnostics["candidate_text"] == '{"value":'
    assert saved[-1][0]["status"] == "model_incomplete"
    assert saved[-1][0]["usage"]["reasoning_tokens"] == 90


def provider(monkeypatch, handler, retries=2):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-key")
    monkeypatch.setattr(
        "aletheia_nexus.processing.provider.time.sleep", lambda seconds: None
    )
    return DeepSeekProvider(
        {"name": "deepseek-flash", "max_retries": retries, "min_interval_seconds": 0},
        enabled=True,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "status,body,code,calls",
    [
        (401, {}, "authentication_failed", 1),
        (402, {}, "quota_exhausted", 1),
        (403, {}, "permission_denied", 1),
        (429, {}, "rate_limited", 3),
        (429, {"error": {"code": "insufficient_quota"}}, "quota_exhausted", 1),
        (500, {}, "service_error", 3),
        (400, {}, "request_error", 1),
        (302, {}, "request_error", 1),
    ],
)
def test_error_classification_and_bounded_retry(monkeypatch, status, body, code, calls):
    adapter = provider(monkeypatch, lambda r: httpx.Response(status, json=body))
    budget = CallBudget(5)
    with pytest.raises(ProcessingError, match=code):
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
    assert len(budget.calls) == calls
    assert all(call["http_status"] == status for call in budget.calls)
    assert "secret-test-key" not in json.dumps(budget.calls)


@pytest.mark.parametrize(
    "exception,code",
    [
        (httpx.ReadTimeout, "timeout"),
        (httpx.ConnectError, "network_error"),
        (httpx.RemoteProtocolError, "network_error"),
    ],
)
def test_transport_failures_do_not_leak_request(monkeypatch, exception, code):
    def handler(request):
        raise exception("secret-test-key raw response", request=request)

    adapter = provider(monkeypatch, handler)
    budget = CallBudget(5)
    with pytest.raises(ProcessingError, match=code) as error:
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
    assert len(budget.calls) == 3
    assert "secret-test-key" not in str(error.value)
    assert error.value.diagnostics == {"transport_error_type": exception.__name__}
    assert all(
        call["transport_error_type"] == exception.__name__ for call in budget.calls
    )
    assert "secret-test-key" not in json.dumps([budget.calls, error.value.diagnostics])


@pytest.mark.parametrize(
    "body,code",
    [
        ({"status": "incomplete", "output": []}, "model_incomplete"),
        ({"status": "completed", "output": []}, "invalid_model_output"),
        (
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                ],
            },
            "model_refusal",
        ),
        (
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"extra":1}'}],
                    }
                ],
            },
            "invalid_model_output",
        ),
        ([], "invalid_model_output"),
    ],
)
def test_invalid_and_refused_output_not_blindly_retried(monkeypatch, body, code):
    adapter = provider(monkeypatch, lambda r: httpx.Response(200, json=body))
    budget = CallBudget(5)
    with pytest.raises(ProcessingError, match=code):
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
    assert len(budget.calls) == 1


def test_http_budget_includes_retries(monkeypatch):
    adapter = provider(
        monkeypatch, lambda r: httpx.Response(500, text="secret-test-key")
    )
    budget = CallBudget(1)
    with pytest.raises(ProcessingError, match="call_budget_exhausted"):
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
    assert len(budget.calls) == 1


def test_cost_budget_stops_before_network(monkeypatch):
    def forbidden(request):
        pytest.fail("must reserve cost before sending")

    adapter = provider(monkeypatch, forbidden)
    adapter.config.update(input_cost_per_million=2, output_cost_per_million=8)
    budget = CallBudget(5, max_cost=0.000001)
    with pytest.raises(ProcessingError, match="cost_budget_exhausted"):
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
    assert not budget.calls


def test_page_batch_budget_keeps_images_and_full_thinking_output(monkeypatch):
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["max_output_tokens"] == 65536
        assert payload["reasoning"] == {"effort": "high"}
        images = [
            part
            for part in payload["input"][0]["content"]
            if part["type"] == "input_image"
        ]
        assert len(images) == 10
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 11000, "output_tokens": 1000},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"value":"ok"}'}],
                    }
                ],
            },
        )

    adapter = provider(monkeypatch, handler)
    adapter.config.update(input_cost_per_million=2, output_cost_per_million=8)
    budget = CallBudget(2, max_cost=0.65)
    pages = [
        {"source_id": "paper", "page": page, "bytes": b"mock-page"}
        for page in range(1, 11)
    ]
    # Ten images have a documented maximum of 10,240 input tokens, not 200,000.
    # Settled usage from the first call leaves room for another full-size request.
    for _ in range(2):
        assert adapter.generate({}, obj({"value": TEXT}), pages, budget, 65536) == {
            "value": "ok"
        }
    assert len(seen) == 2
    assert sum(accounted_cost(call) for call in budget.calls) == pytest.approx(0.06)


def test_oversized_inline_payload_fails_before_http_or_cost_reservation(monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.processing.provider.MAX_INLINE_REQUEST_BYTES", 100
    )
    adapter = provider(monkeypatch, lambda r: pytest.fail("oversized request sent"))
    budget = CallBudget(1)
    with pytest.raises(ProcessingError, match="request_body_budget_exceeded"):
        adapter.generate({}, obj({"value": TEXT}), [], budget, 100)
    assert budget.calls == []


def test_image_is_inline_and_labelled_with_source_page(monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"value":"ok"}'}],
                    }
                ],
            },
        )

    adapter = provider(monkeypatch, handler)
    budget = CallBudget(1)
    adapter.generate(
        {},
        obj({"value": TEXT}),
        [{"source_id": "si", "page": 3, "bytes": b"test"}],
        budget,
        100,
    )
    parts = seen[0]["input"][0]["content"]
    assert parts[1]["text"] == "Source si, PDF page 3"
    assert parts[2]["image_url"].startswith("data:image/png;base64,")
    assert "tools" not in seen[0]
    assert budget.calls[0]["input_images"] == [
        {
            "source_id": "si",
            "page": 3,
            "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        }
    ]


def test_rejected_candidate_diagnostics_redact_secret(monkeypatch):
    body = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": '{"value":"secret-test-key"'}
                ],
            }
        ],
    }
    adapter = provider(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ProcessingError) as error:
        adapter.generate({}, obj({"value": TEXT}), [], CallBudget(1), 100)
    assert error.value.diagnostics["unvalidated"]
    assert "secret-test-key" not in json.dumps(error.value.diagnostics)
    assert "[REDACTED]" in error.value.diagnostics["candidate_text"]


def test_provider_config_cannot_persist_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    with pytest.raises(ValueError, match="unknown keys"):
        DeepSeekProvider(
            {"name": "deepseek-flash", "api_key": "never-persist"}, enabled=True
        )


@pytest.mark.parametrize(
    "value,valid",
    [
        ({"claim": {"text": "keep"}, "labels": ["one", "two"]}, True),
        ({"claim": None, "labels": None}, True),
        ({"claim": {"text": 42}, "labels": ["one"]}, False),
    ],
)
def test_nullable_container_schema_is_accepted_on_wire_and_validated_locally(
    monkeypatch, value, valid
):
    # Actual Responses rejection: type arrays accept primitives, not object/array.
    # Exercise nested claim deletion and user-defined list fields together.
    schema = obj(
        {
            "results": {
                "type": "array",
                "items": obj(
                    {
                        "claim": {
                            **obj({"text": TEXT}),
                            "type": ["object", "null"],
                        },
                        "labels": {"type": ["array", "null"], "items": TEXT},
                    }
                ),
            }
        }
    )
    original = json.dumps(schema)

    def reject_unsupported(node):
        if isinstance(node, dict):
            kinds = node.get("type")
            if isinstance(kinds, list) and {"object", "array"}.intersection(kinds):
                return True
            return any(reject_unsupported(v) for v in node.values())
        if isinstance(node, list):
            return any(reject_unsupported(v) for v in node)
        return False

    def handler(request):
        payload = json.loads(request.content)
        wire = payload["text"]["format"]["schema"]
        if reject_unsupported(wire):
            return httpx.Response(
                400, json={"error": {"code": "invalid_request_error"}}
            )
        fields = wire["properties"]["results"]["items"]["properties"]
        assert fields["claim"]["anyOf"] == [obj({"text": TEXT}), {"type": "null"}]
        assert fields["labels"]["anyOf"] == [
            {"type": "array", "items": TEXT},
            {"type": "null"},
        ]
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
                                "text": json.dumps({"results": [value]}),
                            }
                        ],
                    }
                ],
            },
        )

    adapter = provider(monkeypatch, handler)
    if valid:
        assert adapter.generate({}, schema, [], CallBudget(1), 100) == {
            "results": [value]
        }
    else:
        with pytest.raises(ProcessingError, match="invalid_model_output"):
            adapter.generate({}, schema, [], CallBudget(1), 100)
    assert json.dumps(schema) == original


def metadata_example(kind):
    from test_review import revision_example

    from aletheia_nexus.processing.contracts import response_schema
    from aletheia_nexus.processing.review import (
        review_schema,
        review_targets,
        revision_schema,
    )

    task, candidate, review = revision_example()
    if kind == "review":
        targets = review_targets(candidate)
        noisy = deepcopy(review)
        for check, target in zip(noisy["checks"], targets):
            check.update(target)
        return {"targets": targets}, review_schema(), noisy, review
    if kind == "steps":
        for check in review["checks"]:
            if check["target_id"] == "record:0/steps":
                check["verdict"] = "revise"
        expected = {
            "replacements": {
                "record:0/steps": {
                    "steps": candidate["records"][0]["steps"],
                    "field_step_ids": {
                        fid: field["step_ids"]
                        for fid, field in candidate["records"][0]["fields"].items()
                    },
                }
            },
            "issues": [],
            "requests": [],
        }
        noisy = deepcopy(expected)
        noisy["replacements"]["record:0/steps"]["steps"][0]["citations_note"] = (
            "not_a_field"
        )
        return {}, revision_schema(task, candidate, review), noisy, expected
    noisy = deepcopy(candidate)
    noisy["claims"][0]["step_ids"] = []
    return {}, response_schema(task), noisy, candidate


@pytest.mark.parametrize("kind", ["steps", "review", "claims"])
def test_known_metadata_is_projected_once_with_complete_replayable_raw(
    monkeypatch, kind
):
    request, schema, noisy, expected = metadata_example(kind)
    raw = json.dumps(noisy, ensure_ascii=False, indent=2)
    body = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": raw}]}
        ],
    }
    adapter = provider(monkeypatch, lambda req: httpx.Response(200, json=body))
    budget = CallBudget(1)
    result = adapter.generate(request, schema, [], budget, 1000)
    assert result == expected
    assert isinstance(result, ProjectedResponse)
    assert result.metadata["raw_text"] == raw
    assert len(budget.calls) == 1
    assert budget.calls[0]["status"] == "completed"
    replay = project_response(
        json.loads(raw), schema, request.get("targets"), raw_text=raw
    )
    assert replay.metadata == result.metadata
    assert replay == expected
    assert noisy != expected  # Input was not mutated.


@pytest.mark.parametrize(
    "fault", ["scientific_key", "scientific_note", "association", "target"]
)
def test_projection_does_not_discard_unknown_science_or_conflicting_metadata(fault):
    request, schema, noisy, _ = metadata_example(
        "review"
        if fault == "target"
        else "claims"
        if fault == "association"
        else "steps"
    )
    if fault == "target":
        noisy["checks"][1]["record_id"] = "a different experiment"
    elif fault == "association":
        noisy["claims"][0]["step_ids"] = ["s1"]
    else:
        step = noisy["replacements"]["record:0/steps"]["steps"][0]
        step["temperature" if fault == "scientific_key" else "citations_note"] = (
            "Source reports 180 C"
        )
    with pytest.raises(ValueError, match="unknown keys"):
        project_response(noisy, schema, request.get("targets"))


def test_empty_extension_arrays_preserve_response_and_replay_without_model_repair(
    monkeypatch,
):
    request, schema, noisy, expected = metadata_example("claims")
    citation = {"source_id": "p", "block_id": None, "page": 1, "quote": "Synthesize"}
    for response in (noisy, expected):
        response["records"][0]["fields"]["method"]["citations"] = [deepcopy(citation)]
    record = noisy["records"][0]
    record["ordering_hint"] = []
    record["steps"][0]["unconfigured_links"] = []
    record["fields"]["method"]["citations"][0]["annotation_groups"] = []
    original = deepcopy(noisy)
    raw = json.dumps(noisy, ensure_ascii=False, indent=2)
    body = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": raw}]}
        ],
    }
    adapter = provider(monkeypatch, lambda req: httpx.Response(200, json=body))
    budget = CallBudget(1)
    result = adapter.generate(request, schema, [], budget, 1000)
    assert result == expected and noisy == original
    assert len(budget.calls) == 1 and budget.calls[0]["status"] == "completed"
    assert result.metadata["raw_text"] == raw
    assert len(result.metadata["changes"]) == 4
    assert all(change["value"] == [] for change in result.metadata["changes"])
    replay = project_response(json.loads(raw), schema, raw_text=raw)
    assert replay == expected and replay.metadata == result.metadata


@pytest.mark.parametrize("value", [["s1"], None, {}, ""])
def test_empty_extension_projection_does_not_discard_other_unknown_values(value):
    _, schema, noisy, _ = metadata_example("claims")
    noisy["records"][0]["extension"] = value
    with pytest.raises(ValueError, match="unknown keys"):
        project_response(noisy, schema)


@pytest.mark.parametrize("fault", ["missing_required", "wrong_type"])
def test_empty_extension_projection_preserves_required_scientific_validation(fault):
    _, schema, noisy, _ = metadata_example("claims")
    record = noisy["records"][0]
    record["extension"] = []
    if fault == "missing_required":
        del record["fields"]["method"]["value"]
    else:
        record["fields"]["method"]["value"] = {"extension": []}
    with pytest.raises(ValueError):
        project_response(noisy, schema)


def disabled_steps_example():
    from test_review import revision_example

    task, candidate, review = revision_example()
    task["include_steps"] = False
    candidate["records"][0]["steps"] = []
    for value in candidate["records"][0]["fields"].values():
        value["step_ids"] = []
    return task, candidate, review


@pytest.mark.parametrize("revision", [False, True])
def test_disabled_steps_missing_arrays_are_completed_with_replayable_raw(
    monkeypatch, revision
):
    from aletheia_nexus.processing.contracts import response_schema
    from aletheia_nexus.processing.review import revision_schema

    task, expected, review = disabled_steps_example()
    if revision:
        for check in review["checks"]:
            if check["target_id"] == "record:0/field:method":
                check["verdict"] = "revise"
        schema = revision_schema(task, expected, review)
        expected = {
            "replacements": {
                "record:0/field:method": expected["records"][0]["fields"]["method"]
            },
            "issues": [],
            "requests": [],
        }
        noisy = deepcopy(expected)
        del noisy["replacements"]["record:0/field:method"]["step_ids"]
        added_paths = [["replacements", "record:0/field:method", "step_ids"]]
    else:
        schema = response_schema(task)
        noisy = deepcopy(expected)
        del noisy["records"][0]["steps"]
        for value in noisy["records"][0]["fields"].values():
            del value["step_ids"]
        added_paths = [
            ["records", 0, "steps"],
            ["records", 0, "fields", "method", "step_ids"],
            ["records", 0, "fields", "duration", "step_ids"],
        ]
    original = deepcopy(noisy)
    raw = json.dumps(noisy, ensure_ascii=False)
    body = {
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": raw}]}
        ],
    }
    adapter = provider(monkeypatch, lambda req: httpx.Response(200, json=body))
    budget = CallBudget(1)
    response = adapter.generate({}, schema, [], budget, 1000)
    assert response == expected and noisy == original
    assert len(budget.calls) == 1 and budget.calls[0]["status"] == "completed"
    assert response.metadata["raw_text"] == raw
    assert response.metadata["changes"] == [
        {
            "operation": "add",
            "path": path,
            "value": [],
            "reason": "disabled_steps_require_empty_array",
        }
        for path in added_paths
    ]
    replay = project_response(json.loads(raw), schema, raw_text=raw)
    assert replay == response and replay.metadata == response.metadata
    # Already complete empty arrays require no history or model rewrite.
    assert not isinstance(project_response(expected, schema), ProjectedResponse)


@pytest.mark.parametrize(
    "fault",
    [
        "enabled_record_missing",
        "enabled_field_missing",
        "default_field_missing",
        "null_steps",
        "nonempty_step_ids",
        "wrong_type_steps",
        "scientific_key",
        "scientific_value_missing",
    ],
)
def test_disabled_steps_completion_never_erases_or_infers_scientific_content(fault):
    from aletheia_nexus.processing.contracts import response_schema

    task, candidate, _ = disabled_steps_example()
    record = candidate["records"][0]
    field = record["fields"]["method"]
    if fault.startswith("enabled") or fault.startswith("default"):
        task["include_steps"] = True
        if fault.startswith("default"):
            del task["include_steps"]
        if fault == "enabled_record_missing":
            del record["steps"]
        else:
            del field["step_ids"]
    elif fault == "null_steps":
        record["steps"] = None
    elif fault == "nonempty_step_ids":
        field["step_ids"] = ["an unreported step"]
    elif fault == "wrong_type_steps":
        record["steps"] = ""
    else:
        del field["step_ids"]
        if fault == "scientific_key":
            field["temperature"] = "not in the contract"
        else:
            del field["value"]
    original = deepcopy(candidate)
    with pytest.raises(ValueError):
        project_response(candidate, response_schema(task))
    assert candidate == original
