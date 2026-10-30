"""No network/model calls: exercise the mounted API and actual durable jobs."""

import asyncio
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI

from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.normalization_api import (
    API_PREFIX,
    CAPABILITY_HEADER,
    MAX_BODY_BYTES,
    install_normalization_api,
)
from aletheia_nexus.workbench.security import LoopbackGuard


class FakeNormalization:
    def __init__(self):
        self.calls = []
        self.response = None

    def normalize(self, text, options=None, consent=False, context=None):
        self.calls.append((text, deepcopy(options), consent, context.job_id))
        if self.response is not None:
            return deepcopy(self.response)
        return {
            "status": "COMPLETED",
            "canonical": {"papers": [{"doi": "10.1000/example"}]},
            "preview": {"items": [{"request": {"doi": "10.1000/example"}}]},
            "source_map": [{"id": "line-1", "line": 1}],
            "usage": {"known_cost": 0.01, "currency": "CNY"},
            "calls": [{"status": "COMPLETED", "cost": 0.01}],
            "raw_response": "private-provider-body",
            "api_key": "private-provider-key",
            "manifest": "C:/private/state/receipt.json",
        }


class Lease:
    def __init__(self, context):
        self._context, self._generation = context, context.generation

    def __getattr__(self, key):
        if self._context.generation != self._generation:
            raise ValueError("文库已切换，请刷新后重新预览")
        return getattr(self._context, key)


@pytest.fixture
def mounted(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    context = SimpleNamespace(
        root=root,
        generation=1,
        jobs=TaskManager(tmp_path / "workspace", max_workers=1),
        acquisition=AcquisitionService(root),
        input_normalization=FakeNormalization(),
    )
    context.lease = lambda: Lease(context)
    app = FastAPI()
    app.add_middleware(LoopbackGuard, port=8765)
    api = install_normalization_api(context, app=app)

    def request(method, path="/manual", *, authorized=True, **kwargs):
        headers = dict(api.headers if authorized else {})
        headers.update(kwargs.pop("headers", {}))

        async def perform():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
            ) as client:
                return await client.request(
                    method, API_PREFIX + path, headers=headers, **kwargs
                )

        return asyncio.run(perform())

    yield context, api, request
    context.jobs.close(wait=True)


def model_payload(**changes):
    return {
        "text": "1. 10.1000/example",
        "consent": True,
        "options": {"max_cost": 0.2, "model": {"currency": "CNY"}},
        **changes,
    }


@pytest.mark.parametrize(
    "method,path", [("POST", "/manual"), ("POST", "/preview"), ("GET", "/unknown")]
)
def test_all_routes_require_non_public_header_capability_even_without_origin(
    mounted, method, path
):
    context, api, request = mounted
    response = request(method, path, authorized=False, json={"text": "10.1000/example"})
    assert response.status_code == 403
    wrong = request(
        method, path, headers={CAPABILITY_HEADER: "wrong"}, json={"text": "x"}
    )
    assert wrong.status_code == 403
    assert not context.input_normalization.calls and not context.jobs.list()
    assert api.capability not in repr(api)


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://external.invalid"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:9999"},
        {"Host": "external.invalid"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_capability_does_not_override_existing_origin_host_boundary(mounted, headers):
    context, _, request = mounted
    response = request("POST", "/preview", json=model_payload(), headers=headers)
    assert response.status_code == 403
    assert not context.jobs.list() and not context.input_normalization.calls


def test_manual_preview_is_shared_parser_no_model_and_never_creates_directories(
    mounted,
):
    context, _, request = mounted
    original_paths = set(context.root.rglob("*"))
    response = request(
        "POST", json={"text": "A. 新分类 | 标签=催化\n1. 10.1000/example"}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == "manual" and not result["downloads_started"]
    paper = result["preview"]["items"][0]["request"]
    assert paper["doi"] == "10.1000/example" and paper["folder"] == "新分类"
    assert paper["tags"] == ["催化"]
    assert set(context.root.rglob("*")) == original_paths
    assert not context.input_normalization.calls and not context.jobs.list()
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "payload",
    [
        model_payload(consent=False),
        model_payload(consent="true"),
        model_payload(consent=None),
        model_payload(options={}),
        model_payload(options={"max_cost": 0.1}),
        model_payload(options={"max_cost": 0, "model": {"currency": "CNY"}}),
        model_payload(options={"max_cost": True, "model": {"currency": "CNY"}}),
        model_payload(options={"max_cost": -1, "model": {"currency": "CNY"}}),
        model_payload(options={"max_cost": 1, "model": {"currency": "EURO"}}),
        model_payload(
            options={"max_cost": 1, "model": {"currency": "CNY", "api_key": "secret"}}
        ),
    ],
)
def test_no_implicit_consent_budget_or_secret_options_can_queue_paid_work(
    mounted, payload
):
    context, _, request = mounted
    response = request("POST", "/preview", json=payload)
    assert response.status_code == 422
    assert not context.jobs.list() and not context.input_normalization.calls


def test_model_job_uses_shared_service_once_and_returns_only_preview_not_private_receipt(
    mounted,
):
    context, api, request = mounted
    created = request("POST", "/preview", json=model_payload())
    assert created.status_code == 202
    receipt = created.json()
    assert not receipt["downloads_started"]
    assert receipt["kind"] == "input_normalization"
    job_id = receipt["job_id"]
    context.jobs._futures[job_id].result(timeout=3)
    for _ in range(2):
        response = request("GET", "/" + job_id)
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"
        assert (
            response.json()["result"]["canonical"]["papers"][0]["doi"]
            == "10.1000/example"
        )
        assert response.json()["result"]["usage"]["known_cost"] == 0.01
        assert "api_key" not in response.text and "private-" not in response.text
        assert "C:/private" not in response.text
    assert len(context.input_normalization.calls) == 1
    text, options, consent, recorded_id = context.input_normalization.calls[0]
    assert text == model_payload()["text"] and consent is True and recorded_id == job_id
    assert options["max_cost"] == 0.2 and options["max_calls"] == 1
    persisted = context.jobs.get(job_id)
    assert api.capability not in json.dumps(persisted)
    assert "text" not in persisted["parameters"]


def test_status_cannot_read_other_kinds_or_unknown_jobs(mounted):
    context, _, request = mounted
    job = context.jobs.submit(
        "research", "private", [], lambda ctx: {"private": "PDF contents"}
    )
    context.jobs._futures[job["id"]].result(timeout=3)
    for job_id in (job["id"], "unknown"):
        response = request("GET", "/" + job_id)
        assert response.status_code == 404 and "PDF contents" not in response.text


def test_failed_receipt_preserves_unknown_billing_and_readable_diagnostics(mounted):
    context, _, request = mounted
    context.input_normalization.response = {
        "status": "FAILED",
        "canonical": None,
        "calls": [{"status": "FAILED", "estimated_cost": None, "reserved_cost": 0.15}],
        "accounted_cost": 0.15,
        "known_cost": 0,
        "reserved_cost": 0.15,
        "billing_uncertain": True,
        "diagnostics": [{"code": "timeout", "message": "请求超时，费用可能已产生"}],
        "receipt": "C:/private/normalization.json",
        "unvalidated_candidate_text": "private-provider-candidate",
    }
    created = request("POST", "/preview", json=model_payload()).json()
    context.jobs._futures[created["job_id"]].result(timeout=3)
    response = request("GET", "/" + created["job_id"])
    result = response.json()["result"]
    assert response.json()["status"] == "FAILED"
    assert result["billing_uncertain"] is True and result["accounted_cost"] == 0.15
    assert result["known_cost"] == 0 and result["reserved_cost"] == 0.15
    assert result["diagnostics"][0]["code"] == "timeout"
    assert "计费" in result["diagnostics"][0]["message"]
    assert "private" not in response.text and "receipt" not in response.text
    assert len(context.input_normalization.calls) == 1


def test_checkpoint_cost_is_visible_if_worker_fails_without_final_result(mounted):
    context, _, request = mounted

    def fails(text, options=None, consent=False, context=None):
        context.progress(
            normalization_receipt="C:/private/receipt.json",
            normalization_accounted_cost=0.15,
            normalization_call_count=1,
            billing_uncertain=True,
        )
        raise ValueError("输入整理已中断，请先核对账本再决定是否重试")

    context.input_normalization.normalize = fails
    created = request("POST", "/preview", json=model_payload()).json()
    context.jobs._futures[created["job_id"]].result(timeout=3)
    response = request("GET", "/" + created["job_id"])
    result = response.json()
    assert result["status"] == "FAILED" and result["billing_uncertain"] is True
    assert result["normalization_accounted_cost"] == 0.15
    assert result["normalization_call_count"] == 1
    assert "private" not in response.text and "receipt" not in response.text


def test_explicit_consent_cannot_send_environment_credentials(mounted, monkeypatch):
    context, _, request = mounted
    secret = "current-environment-test-key"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    response = request("POST", "/preview", json=model_payload(text="文献 " + secret))
    assert response.status_code == 422 and secret not in response.text
    assert not context.jobs.list() and not context.input_normalization.calls


def test_queued_task_retains_old_root_lease_and_refuses_changed_library(mounted):
    context, _, request = mounted
    blocker = Event()
    try:
        blocked = context.jobs.submit(
            "blocking", "wait", [], lambda ctx: blocker.wait(4)
        )
        created = request("POST", "/preview", json=model_payload()).json()
        context.generation += 1
        blocker.set()
        context.jobs._futures[blocked["id"]].result(timeout=3)
        context.jobs._futures[created["job_id"]].result(timeout=3)
        response = request("GET", "/" + created["job_id"])
        assert response.json()["status"] == "FAILED"
        assert "文库已切换" in response.json()["error"]["message"]
        assert not context.input_normalization.calls
    finally:
        blocker.set()


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "x", "path": "C:/private/file.txt"},
        {"text": "x", "format": "path"},
        {"text": ""},
        {"text": 3},
        {"text": "\x00"},
        {"text": "\ud800"},
    ],
)
def test_manual_rejects_file_read_options_and_invalid_text(mounted, payload):
    _, _, request = mounted
    assert (
        request(
            "POST",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )


def test_http_body_type_and_size_are_bounded(mounted):
    _, _, request = mounted
    assert request("POST", content="plain text").status_code == 415
    assert (
        request(
            "POST", content="{", headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    assert request("POST", json={"text": "x" * 50001}).status_code == 413
    assert (
        request(
            "POST",
            content=b"x" * (MAX_BODY_BYTES + 1),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_install_is_idempotent_only_for_same_context(mounted):
    context, api, _ = mounted
    app = FastAPI()
    first = install_normalization_api(context, app)
    assert install_normalization_api(context, app) is first
    assert first.capability != api.capability
    with pytest.raises(ValueError, match="不同"):
        install_normalization_api(SimpleNamespace(), app)


def test_core_import_does_not_load_nicegui_or_fastapi():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import aletheia_nexus.workbench.normalization_api; assert 'nicegui' not in sys.modules; assert 'fastapi' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_model_options_use_real_shared_validator():
    # Guard the public budget contract against later backend default changes.
    from aletheia_nexus.workbench.input_normalization import input_normalization_options

    options = input_normalization_options(model_payload()["options"])
    assert options["max_calls"] == 1 and options["model"]["max_retries"] == 0
    assert importlib.util.find_spec("aletheia_nexus.workbench.normalization_api")
