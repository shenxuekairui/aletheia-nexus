"""Sequential title requests share the native budget and durable reservations."""

import json
from copy import deepcopy

import httpx
import pytest

from aletheia_nexus.workbench.translation import TranslationService


class Library:
    def __init__(self):
        self.items = {key: {"title": f"Scientific title {key}"} for key in "abc"}

    def get(self, key):
        return deepcopy(self.items[key])

    def update_metadata(self, key, **fields):
        self.items[key].update(fields)


def response(request):
    payload = json.loads(json.loads(request.content)["input"][0]["content"][0]["text"])
    values = [
        {"id": row["id"], "title": "译名" + row["id"]} for row in payload["titles"]
    ]
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 60},
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"translations": values}),
                        }
                    ],
                }
            ],
        },
    )


def options(**updates):
    return {"model": {"min_interval_seconds": 0}, **updates}


def test_shared_call_limit_and_local_receipt_slices_are_not_duplicated(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-shared-translation-key")
    calls = []
    ledger = None

    def handle(request):
        calls.append(request)
        saved = json.loads(ledger.read_text(encoding="utf-8"))
        assert saved["calls"][-1]["status"] == "started"
        assert saved["billing_uncertain"]
        return response(request)

    service = TranslationService(
        Library(), tmp_path, transport=httpx.MockTransport(handle)
    )
    configuration = options(max_calls=1)
    budget, ledger = service.create_budget(configuration)
    first = service.translate(["a"], configuration, consent=True, budget=budget)
    second = service.translate(["b"], configuration, consent=True, budget=budget)
    assert len(calls) == len(budget.calls) == len(first["calls"]) == 1
    assert second["calls"] == []
    assert first["shared_call_offset"] == 0 and second["shared_call_offset"] == 1
    assert second["items"][0]["error"] == "call_budget_exhausted"
    assert first["accounted_cost"] == pytest.approx(0.00068)
    assert second["accounted_cost"] == 0
    assert (
        json.loads(ledger.read_text(encoding="utf-8"))["accounted_cost"]
        == first["accounted_cost"]
    )
    assert "title_zh" not in service.library.items["b"]
    assert "fake-shared-translation-key" not in "".join(
        p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.json")
    )


def test_shared_cost_limit_is_not_reset_for_each_title(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    calls = []
    service = TranslationService(
        Library(),
        tmp_path,
        transport=httpx.MockTransport(lambda r: calls.append(r) or response(r)),
    )
    configuration = options(
        model={
            "min_interval_seconds": 0,
            "input_cost_per_million": 0,
            "output_cost_per_million": 1,
        },
        max_cost=0.00016,
        max_output_tokens=128,
    )
    budget, _ = service.create_budget(configuration)
    first = service.translate(["a"], configuration, consent=True, budget=budget)
    second = service.translate(["b"], configuration, consent=True, budget=budget)
    assert len(calls) == 1 and first["status"] == "COMPLETED"
    assert second["items"][0]["error"] == "cost_budget_exhausted"
    assert (
        first["accounted_cost"] + second["accounted_cost"] <= configuration["max_cost"]
    )


def test_unknown_charge_stops_new_http_but_keeps_cache_available(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) > 1:
            raise httpx.ReadTimeout("unknown charge")
        return response(request)

    service = TranslationService(
        Library(), tmp_path, transport=httpx.MockTransport(handle)
    )
    configuration = options()
    service.translate(["b"], configuration, consent=True)  # Prime an independent cache.
    budget, ledger = service.create_budget(configuration)
    failed = service.translate(["a"], configuration, consent=True, budget=budget)
    cached = service.translate(["b"], configuration, budget=budget)
    blocked = service.translate(["c"], configuration, consent=True, budget=budget)
    assert len(calls) == 2 and len(budget.calls) == 1
    assert failed["billing_uncertain"] and blocked["billing_uncertain"]
    assert cached["items"][0]["status"] == "CACHED" and cached["calls"] == []
    assert blocked["items"][0]["error"] == "previous_call_requires_review"
    assert blocked["calls"] == []
    assert json.loads(ledger.read_text(encoding="utf-8"))["billing_uncertain"]


def test_shared_provider_preserves_selected_interval_and_rejects_currency_change(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    from aletheia_nexus.processing import provider

    sleeps = []
    monkeypatch.setattr(provider.time, "monotonic", lambda: 100)
    monkeypatch.setattr(provider.time, "sleep", sleeps.append)
    service = TranslationService(
        Library(), tmp_path, transport=httpx.MockTransport(response)
    )
    configuration = options(model={"min_interval_seconds": 5})
    budget, _ = service.create_budget(configuration)
    service.translate(["a"], configuration, consent=True, budget=budget)
    service.translate(["b"], configuration, consent=True, budget=budget)
    assert sleeps == [0, 5]
    changed = {**configuration, "model": {**configuration["model"], "currency": "USD"}}
    with pytest.raises(ValueError, match="币种"):
        service.translate(["c"], changed, consent=True, budget=budget)


def test_created_budget_binds_model_before_first_call(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    service = TranslationService(
        Library(),
        tmp_path,
        transport=httpx.MockTransport(
            lambda _: pytest.fail("Changed model must not be sent")
        ),
    )
    configuration = options()
    budget, _ = service.create_budget(configuration)
    changed = options(model={"min_interval_seconds": 0, "currency": "USD"})
    with pytest.raises(ValueError, match="币种"):
        service.translate(["a"], changed, consent=True, budget=budget)
    assert budget.calls == []
