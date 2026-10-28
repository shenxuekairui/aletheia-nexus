"""Ordinary failure evidence and human controls survive the acquisition adapter."""

import json
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import batch as native_batch
from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport
from aletheia_nexus.workbench import acquisition
from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.jobs import TaskCancelled


class Context:
    def __init__(self, decision="skip", cancel=False):
        self.decision, self.cancel = decision, cancel
        self.gates = 0
        self.records = []

    def checkpoint(self):
        if self.cancel and self.gates:
            raise TaskCancelled("cancelled_during_interaction")

    def progress(self, *args, **kwargs):
        pass

    def should_skip(self, *args):
        return False

    def record(self, *args, **kwargs):
        self.records.append((args, kwargs))

    def wait_interaction(self, details, **kwargs):
        self.gates += 1
        return self.decision


def test_explicit_interaction_skip_never_reenters_native_batch_retries(
    tmp_path, monkeypatch
):
    entered = []

    def fetch(request, *, browser_session, **kwargs):
        entered.append(request.doi)
        browser_session.config.interaction_callback(
            ChallengeReport(ChallengeKind.AUTHENTICATION),
            "https://publisher.example/login?ticket=private-value",
        )
        pytest.fail("a skipped interaction must leave the current engine attempt")

    monkeypatch.setattr(native_batch, "_acquire_item", fetch)
    context = Context()
    report = AcquisitionService(tmp_path).run(
        ["10.1000/one", "10.1000/two"],
        {
            "public_only": False,
            "browser_enabled": True,
            "include_si": False,
            "max_item_attempts": 3,
            "retry_backoff": 0,
        },
        context,
    )
    assert entered == ["10.1000/one", "10.1000/two"]
    assert context.gates == 2
    assert [r["status"] for r in report["items"]] == ["SKIPPED", "SKIPPED"]
    assert all(r["attempts"] is None for r in report["items"])
    assert all("自动重新进入" in r["reason"] for r in report["items"])
    assert "private-value" not in json.dumps(report)


def test_cancellation_wins_over_skip_without_retry_or_later_dispatch(
    tmp_path, monkeypatch
):
    entered = []

    def fetch(request, *, browser_session, **kwargs):
        entered.append(request.doi)
        browser_session.config.interaction_callback(
            ChallengeReport(ChallengeKind.MFA), "https://publisher.example/login"
        )

    monkeypatch.setattr(native_batch, "_acquire_item", fetch)
    context = Context(cancel=True)
    with pytest.raises(TaskCancelled, match="cancelled_during_interaction"):
        AcquisitionService(tmp_path).run(
            ["10.1000/one", "10.1000/two"],
            {
                "public_only": False,
                "browser_enabled": True,
                "include_si": False,
                "max_item_attempts": 3,
                "retry_backoff": 0,
            },
            context,
        )
    assert entered == ["10.1000/one"]
    assert context.records[-1][0][1] == "CANCELLED"


def test_normal_engine_failure_projects_readable_reason_route_and_redacted_trace(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "an-environment-secret-value")
    url = "https://user:password@publisher.example/paper?session=opaque-session&arbitrary=opaque-query"
    route_result = SimpleNamespace(
        status="AUTH_REQUIRED",
        error="Login unavailable at "
        + url
        + " bearer abcdefghijklm\nCookie: private-cookie\napi_key=an-environment-secret-value",
        message=None,
        attempts=2,
        elapsed_seconds=1.2,
    )
    result = SimpleNamespace(
        message="Access needs a legitimate login at " + url,
        base_result=SimpleNamespace(
            status="EXHAUSTED",
            message=None,
            route_attempts=[
                SimpleNamespace(candidate=SimpleNamespace(url=url), result=route_result)
            ],
            file_attempts=[],
        ),
        browser_attempts=[],
        elsevier_attempt=None,
    )

    def batch(requests, **kwargs):
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    requests[0],
                    requests[0].doi,
                    BatchItemStatus.AUTH_REQUIRED,
                    result=result,
                    error=None,
                    attempts=2,
                )
            ]
        )

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    report = AcquisitionService(tmp_path).run(
        ["10.1000/one"], {"interaction_policy": "skip", "include_si": False}
    )
    row = report["items"][0]
    assert row["main_status"] == row["status"] == "SKIPPED"
    assert row["acquisition_status"] == "AUTH_REQUIRED"
    assert row["base_status"] == "EXHAUSTED"
    assert row["source"] == "publisher.example" and row["source_kind"] == "公共来源"
    assert row["diagnostics"][0]["status"] == "AUTH_REQUIRED"
    assert row["retry_count"] == 1 and row["folder"] == str(tmp_path.resolve())
    assert row["checkpoint"] == report["checkpoint"]
    assert row["reason"] and row["message"]
    serialized = json.dumps(report, ensure_ascii=False)
    for secret in (
        "opaque-session",
        "opaque-query",
        "private-cookie",
        "abcdefghijklm",
        "an-environment-secret-value",
        "user:password",
    ):
        assert secret not in serialized
