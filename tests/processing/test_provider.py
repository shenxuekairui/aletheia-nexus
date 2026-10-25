import json

import httpx
import pytest

from aletheia_nexus.processing.contracts import TEXT, obj
from aletheia_nexus.processing.provider import (
    CallBudget,
    DeepSeekProvider,
    ProcessingError,
    accounted_cost,
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
    [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "network_error")],
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
