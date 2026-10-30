"""Configured official endpoints reach both real transports without secrets."""

import json

import httpx
import pytest
from test_research_planner import app as application_fixture
from test_research_planner import draft_for, envelope, setup_request

from aletheia_nexus.processing.api_config import (
    resolve_deepseek_endpoint,
    validate_deepseek_base_url,
)
from aletheia_nexus.processing.contracts import TEXT, obj
from aletheia_nexus.processing.provider import CallBudget, DeepSeekProvider
from aletheia_nexus.research_planner import draft_task

app = application_fixture


@pytest.mark.parametrize("environment", [None, "", "   ", "https://api.deepseek.com/"])
def test_default_and_blank_environment_use_official_root(monkeypatch, environment):
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    if environment is not None:
        monkeypatch.setenv("DEEPSEEK_BASE_URL", environment)
    assert resolve_deepseek_endpoint("models") == "https://api.deepseek.com/models"
    with pytest.raises(ValueError):
        validate_deepseek_base_url("")


@pytest.mark.parametrize(
    "base", ["https://api.deepseek.com", "https://api.deepseek.com/v1"]
)
def test_provider_freezes_configured_official_endpoint(monkeypatch, base):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "endpoint-test-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", base)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=envelope({"value": "ok"}))

    provider = DeepSeekProvider(
        {"name": "deepseek-flash", "min_interval_seconds": 0},
        enabled=True,
        transport=httpx.MockTransport(handle),
    )
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://untrusted.invalid")
    assert provider.generate({}, obj({"value": TEXT}), [], CallBudget(1), 100) == {
        "value": "ok"
    }
    assert str(requests[0].url) == base + "/responses"
    assert requests[0].headers["authorization"] == "Bearer endpoint-test-secret"
    assert "endpoint-test-secret" not in json.dumps(provider.identity)


def test_planner_repairs_stay_on_initial_endpoint(app, monkeypatch):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "endpoint-plan-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    requests = []

    def handle(http_request):
        requests.append(http_request)
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://untrusted.invalid")
        return httpx.Response(
            200,
            json=envelope(
                {"invalid": True} if len(requests) == 1 else draft_for(request)
            ),
        )

    result = draft_task(
        service,
        request,
        authorization=service.authorize("plan", request),
        transport=httpx.MockTransport(handle),
    )
    assert result["task"]["documents"] == request["documents"]
    assert [str(item.url) for item in requests] == [
        "https://api.deepseek.com/v1/responses"
    ] * 2
    for path in service.workspace.rglob("*.json"):
        assert "endpoint-plan-secret" not in path.read_text(encoding="utf-8")


def test_invalid_endpoint_stops_provider_before_any_http(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "endpoint-test-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://user:secret@api.deepseek.com")
    calls = []
    with pytest.raises(ValueError):
        DeepSeekProvider(
            {"name": "deepseek-flash"},
            enabled=True,
            transport=httpx.MockTransport(lambda request: calls.append(request)),
        )
    assert not calls
