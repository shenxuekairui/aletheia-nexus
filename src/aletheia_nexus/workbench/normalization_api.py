"""Capability-protected preview API over the shared input services.

This module imports without the UI extra. Routes mount on the existing local
app; they never acquire papers, apply a browser draft, or expose filesystem data.
The process-local capability must be copied explicitly by the local user and
sent as a header, including by scripts that have no Origin header.
"""

import asyncio
import hashlib
import json
import math
import secrets
from urllib.parse import urlsplit

from .jobs import safe_data
from .messages import error_record, user_message
from .settings import SECRET_KEY, check_preferences

API_PREFIX = "/an-api/input-normalization"
CAPABILITY_HEADER = "X-AN-Preview-Token"
MAX_BODY_BYTES = 256 * 1024

_RESULT_FIELDS = {
    "schema",
    "id",
    "status",
    "canonical",
    "source_map",
    "preview",
    "warnings",
    "errors",
    "unparsed",
    "usage",
    "calls",
    "model",
    "max_cost",
    "currency",
    "summary",
    "needs_review",
    "cached",
    "cache_status",
    "input_sha256",
    "strategy",
    "request_hash",
    "normalized",
    "items",
    "count",
    "paper_count",
    "ready",
    "conflicts",
    "accounted_cost",
    "known_cost",
    "reserved_cost",
    "billing_uncertain",
    "scope",
    "applied",
}
_PRIVATE_FIELDS = {
    "path",
    "pdf",
    "pdf_path",
    "sidecar",
    "sidecar_path",
    "directory",
    "outputs",
    "manifest",
    "manifest_path",
    "receipt_path",
    "source_record",
    "raw_response",
    "response_body",
    "request_headers",
    "response_headers",
    "headers",
}


def _public(value):
    """Use the existing secret scrubber and omit private transport/file fields."""
    value = safe_data(value)
    if isinstance(value, dict):
        return {
            key: _public(item)
            for key, item in value.items()
            if not SECRET_KEY.search(key) and key not in _PRIVATE_FIELDS
        }
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _public_result(result):
    if not isinstance(result, dict):
        return None
    public = {key: value for key, value in result.items() if key in _RESULT_FIELDS}
    if result.get("diagnostics"):
        diagnostics = result["diagnostics"]
        if not isinstance(diagnostics, list):
            diagnostics = [diagnostics]
        public["diagnostics"] = [
            {"code": record["code"], "message": record["message"]}
            for record in (error_record(value) for value in diagnostics)
        ]
    return _public(public)


def _public_job(job):
    result = {
        "job_id": job["id"],
        "kind": "input_normalization",
        **{
            key: job[key]
            for key in (
                "status",
                "stage",
                "created_at",
                "updated_at",
                "finished_at",
                "current_index",
                "total",
                "billing_uncertain",
            )
            if key in job
        },
    }
    if job.get("error"):
        error = job["error"]
        result["error"] = {
            "code": error.get("code", "FAILED")
            if isinstance(error, dict)
            else "FAILED",
            "message": user_message(error),
        }
    if "result" in job:
        result["result"] = _public_result(job["result"])
    # Checkpoints remain useful after interruption, before a final result exists.
    for key, value in job.items():
        if key in {"usage", "calls"} or key.startswith("normalization_"):
            if not any(
                part in key for part in ("path", "manifest", "directory", "receipt")
            ):
                result[key] = value
    return _public(result)


class NormalizationAPI:
    """A single process-local capability; never saved with task parameters."""

    def __init__(self, context):
        self.context = context
        self._capability = secrets.token_urlsafe(32)

    @property
    def capability(self):
        return self._capability

    @property
    def headers(self):
        return {CAPABILITY_HEADER: self._capability}

    def __repr__(self):
        return "NormalizationAPI(capability=<private>)"

    def lease(self):
        context = self.context
        lease = context.lease() if hasattr(context, "lease") else context
        # Force the established generation check even if a new service attribute
        # is not yet individually listed by ContextLease.
        lease.root
        return lease


def install_normalization_api(context, app=None):
    """Mount once and return the capability for explicit local script access.

    POST /manual: {"text": "..."}; no network or remote consent needed.
    POST /preview: {"text": "...", "consent": true, "options": {
        "max_cost": 0.1, "model": {"currency": "CNY"}, ...}}; queues a job.
    GET /{job_id}: only normalization jobs, with sanitized previews and ledger.

    All routes require X-AN-Preview-Token and same-origin loopback access. There
    is no unauthenticated token endpoint, query token, CORS grant, or new server.
    """
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse

    if app is None:
        from nicegui import app

    previous = getattr(app.state, "an_input_normalization_api", None)
    if previous is not None:
        if previous.context is not context:
            raise ValueError("同一个本地服务不能重复绑定不同的规范化工作区")
        return previous
    api = NormalizationAPI(context)

    def response(payload, status=200):
        return JSONResponse(
            payload,
            status_code=status,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    def authorize(request):
        host = request.headers.get("host", "").lower()
        origin = request.headers.get("origin")
        try:
            authority = urlsplit("http://" + host)
            host_ok = (
                authority.hostname in {"127.0.0.1", "localhost"}
                and authority.username is None
                and authority.password is None
                and not authority.path
                and not authority.query
                and not authority.fragment
                and (authority.port is None or 1 <= authority.port <= 65535)
            )
            origin_ok = True
            if origin is not None:
                parsed = urlsplit(origin)
                origin_ok = (
                    parsed.scheme == "http"
                    and parsed.netloc.lower() == host
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                )
        except ValueError:
            host_ok = origin_ok = False
        token = request.headers.get(CAPABILITY_HEADER, "")
        if (
            not host_ok
            or not origin_ok
            or request.headers.get("sec-fetch-site") == "cross-site"
            or not secrets.compare_digest(
                token.encode("utf-8"), api.capability.encode("ascii")
            )
        ):
            raise HTTPException(403, "本地预览接口需要同源访问和有效的临时能力令牌")

    async def body(request, allowed):
        authorize(request)
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(415, "请使用 application/json 提交规范化预览")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY_BYTES:
                raise HTTPException(413, "规范化请求超过 256 KiB，请分批输入")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(422, "规范化请求不是有效的 JSON 对象") from None
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise HTTPException(422, "规范化请求包含未支持的字段，请核对接口契约")
        text = payload.get("text")
        # Keep these limits in sync with the shared normalization service. A
        # manual preview has the same boundary and cannot read a passed Path.
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise HTTPException(422, "请输入非空的论文清单文本")
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError:
            raise HTTPException(
                422, "论文清单包含无效的 Unicode 字符，请修正输入"
            ) from None
        if len(text) > 50000 or len(encoded) > 200000:
            raise HTTPException(
                413, "论文清单最多 50000 个字符、200000 个 UTF-8 字节，请分批输入"
            )
        return payload

    @app.post(API_PREFIX + "/manual", name="an_input_normalization_manual")
    async def manual(request: Request):
        payload = await body(request, {"text"})
        try:
            lease = api.lease()
            preview = await asyncio.to_thread(
                lease.acquisition.preview_inputs, payload["text"]
            )
        except (ValueError, TypeError, FileNotFoundError) as exc:
            raise HTTPException(422, user_message(exc)) from None
        return response(
            {"mode": "manual", "preview": _public(preview), "downloads_started": False}
        )

    @app.post(API_PREFIX + "/preview", name="an_input_normalization_preview")
    async def preview(request: Request):
        payload = await body(request, {"text", "options", "consent"})
        if payload.get("consent") is not True:
            raise HTTPException(422, "模型规范化需要本次明确授权发送这份输入文本")
        options = payload.get("options")
        if not isinstance(options, dict):
            raise HTTPException(422, "模型规范化需要明确的模型参数和本次费用上限")
        cost = options.get("max_cost")
        model = options.get("model")
        if (
            type(cost) not in (int, float)
            or not math.isfinite(cost)
            or cost <= 0
            or not isinstance(model, dict)
            or not isinstance(model.get("currency"), str)
            or model["currency"] not in {"CNY", "USD"}
        ):
            raise HTTPException(
                422, "请明确提供正数费用上限 max_cost 和币种 model.currency"
            )
        from .input_normalization import (
            input_normalization_options,
            validate_input_text,
        )

        try:
            check_preferences(options)
            options = input_normalization_options(options)
            validate_input_text(payload["text"])
            lease = api.lease()
            service = lease.input_normalization
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, user_message(exc)) from None
        text = payload["text"]
        identity = hashlib.sha256(text.encode("utf-8")).hexdigest()

        def worker(task_context):
            lease.root
            return service.normalize(
                text, options=options, consent=True, context=task_context
            )

        receipt = lease.jobs.submit(
            "input_normalization",
            "模型规范化论文清单",
            [identity],
            worker,
            parameters={
                "options": options,
                "input_sha256": identity,
                "input_characters": len(text),
            },
        )
        return response(
            {
                "job_id": receipt["id"],
                "kind": "input_normalization",
                "status": receipt["status"],
                "downloads_started": False,
                "status_url": API_PREFIX + "/" + receipt["id"],
            },
            status=202,
        )

    @app.get(API_PREFIX + "/{job_id}", name="an_input_normalization_status")
    async def status(job_id: str, request: Request):
        authorize(request)
        try:
            job = context.jobs.get(job_id)
        except KeyError:
            raise HTTPException(404, "未找到这项输入规范化任务") from None
        if job.get("kind") != "input_normalization":
            raise HTTPException(404, "未找到这项输入规范化任务")
        return response(_public_job(job))

    app.state.an_input_normalization_api = api
    return api
