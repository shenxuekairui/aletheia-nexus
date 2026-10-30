"""Planning observers bind before HTTP and retain the native ledger on failure."""

import json
from pathlib import Path

import httpx
import pytest
from test_research_app import app as application_fixture
from test_research_planner import draft_for, envelope, setup_request

from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_planner import draft_task

app = application_fixture


@pytest.mark.parametrize("missing_usage", [False, True])
def test_planning_initial_and_final_progress_snapshots_match_the_exact_run(
    app, monkeypatch, missing_usage
):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-planning-key")
    snapshots = []

    def progress(snapshot):
        durable = json.loads(
            Path(snapshot["manifest_file"]).read_text(encoding="utf-8")
        )
        assert snapshot["run_id"] == durable["run_id"]
        assert snapshot["calls"] == durable["calls"]
        assert snapshot["usage"] == durable["usage"]
        snapshots.append(snapshot)

    def request_handler(http_request):
        assert snapshots[0]["calls"] == []  # Published before the first HTTP.
        assert snapshots[-1]["calls"][0]["status"] == "started"
        data = envelope(draft_for(request))
        if missing_usage:
            data["usage"] = {}
        return httpx.Response(200, json=data)

    result = draft_task(
        service,
        request,
        authorization=service.authorize("plan", request),
        transport=httpx.MockTransport(request_handler),
        progress=progress,
    )
    assert snapshots[0]["status"] == "RUNNING" and snapshots[0]["calls"] == []
    assert snapshots[-1]["status"] == "COMPLETED"
    assert snapshots[-1]["task_file"] == result["task_file"]
    assert len({row["run_id"] for row in snapshots}) == 1
    assert snapshots[-1]["usage"]["estimated_cost"] == (None if missing_usage else 0.01)
    assert snapshots[-1]["usage"]["unknown_usage_calls"] == int(missing_usage)
    assert "test-planning-key" not in json.dumps(snapshots)


def test_planning_budget_failure_has_a_known_manifest_without_http(app, monkeypatch):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-planning-key")
    request["planning_budget"]["max_cost"] = 0.001
    snapshots = []
    with pytest.raises(ProcessingError, match="cost_budget_exhausted"):
        draft_task(
            service,
            request,
            authorization=service.authorize("plan", request),
            transport=httpx.MockTransport(lambda _: pytest.fail("No HTTP permitted")),
            progress=snapshots.append,
        )
    assert snapshots[0]["run_id"] == snapshots[-1]["run_id"]
    assert snapshots[-1]["status"] == "FAILED"
    assert snapshots[-1]["usage"]["http_attempts"] == 0
    assert snapshots[-1]["calls"] == []
    assert Path(snapshots[-1]["manifest_file"]).is_file()


def test_unknown_planning_billing_and_retry_are_observed_without_reissuing(
    app, monkeypatch
):
    service, request = setup_request(app)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-planning-key")
    snapshots, requests = [], []

    def timeout(http_request):
        requests.append(http_request)
        assert snapshots[-1]["status"] == "RUNNING"
        raise httpx.ReadTimeout("Synthetic timeout", request=http_request)

    with pytest.raises(ProcessingError, match="timeout"):
        draft_task(
            service,
            request,
            authorization=service.authorize("plan", request),
            transport=httpx.MockTransport(timeout),
            progress=snapshots.append,
        )
    assert len(requests) == request["planning_budget"]["max_calls"] == 2
    assert snapshots[-1]["status"] == "FAILED"
    assert snapshots[-1]["usage"]["estimated_cost"] is None
    assert snapshots[-1]["usage"]["unknown_usage_calls"] == 2
    assert snapshots[-1]["usage"]["reserved_cost"] > 0
    assert snapshots[0]["calls"] == []  # Later checkpoints cannot mutate old snapshots.
