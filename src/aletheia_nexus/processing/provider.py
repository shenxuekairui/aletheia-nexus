"""One explicit Responses API adapter, with injectable HTTP transport."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

import httpx

from .contracts import MODEL, PROMPT, PROMPT_VERSION, digest, validate


class ProcessingError(RuntimeError):
    """Persist only this bounded category, never raw provider bodies or secrets."""

    def __init__(self, code: str, diagnostics: dict | None = None):
        self.code = code
        self.diagnostics = diagnostics
        super().__init__(code)


def accounted_cost(call: dict) -> float | None:
    """Settle known usage; keep the full reservation for unknown billing."""
    for key in ("estimated_cost", "reserved_cost"):
        value = call.get(key)
        if value is not None:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("invalid cost in call ledger")
            return value
    return None


@dataclass
class CallBudget:
    max_calls: int
    max_cost: float | None = None
    calls: list[dict] = field(default_factory=list)
    checkpoint: Callable[[], None] = field(default=lambda: None, repr=False)

    def reserve(self, estimated_max: float | None) -> dict:
        if len(self.calls) >= self.max_calls:
            raise ProcessingError("call_budget_exhausted")
        if self.max_cost is not None:
            if estimated_max is None:
                raise ProcessingError("cost_estimate_unavailable")
            prior_costs = [accounted_cost(c) for c in self.calls]
            if any(value is None for value in prior_costs):
                raise ProcessingError("cost_estimate_unavailable")
            if sum(prior_costs) + estimated_max > self.max_cost:
                raise ProcessingError("cost_budget_exhausted")
        row = {
            "status": "started",
            "usage": None,
            "estimated_cost": None,
            "reserved_cost": estimated_max,
        }
        self.calls.append(row)
        return row


class Provider(Protocol):
    @property
    def identity(self) -> dict: ...

    def generate(
        self,
        request: dict,
        schema: dict,
        images: list[dict],
        budget: CallBudget,
        max_output_tokens: int,
    ) -> dict: ...


class DeepSeekProvider:
    """No implicit activation, key persistence, tools, redirects, or model routing."""

    def __init__(
        self,
        config: dict,
        *,
        enabled: bool = False,
        transport: httpx.BaseTransport | None = None,
    ):
        if not enabled:
            raise ProcessingError("remote_disabled")
        validate(config, MODEL, "provider_config")
        self.config = dict(config)
        self._key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not self._key:
            raise ProcessingError("missing_api_key")
        self._transport = transport
        self._last_call = 0.0

    @property
    def identity(self) -> dict:
        return {
            "provider": "deepseek-responses",
            "adapter_version": "2",
            "temperature": 0,
            "model": self.config["name"],
            "config": self.config,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": digest(PROMPT),
        }

    def generate(
        self,
        request: dict,
        schema: dict,
        images: list[dict],
        budget: CallBudget,
        max_output_tokens: int,
    ) -> dict:
        serialized = json.dumps(request, ensure_ascii=False, allow_nan=False)
        content = [{"type": "input_text", "text": serialized}]
        for item in images:
            content.extend(
                [
                    {
                        "type": "input_text",
                        "text": f"Source {item['source_id']}, PDF page {item['page']}",
                    },
                    {
                        "type": "input_image",
                        "detail": "high",
                        "image_url": "data:image/png;base64,"
                        + base64.b64encode(item["bytes"]).decode("ascii"),
                    },
                ]
            )
        payload = {
            "model": self.config["name"],
            "store": False,
            "reasoning": {"effort": self.config.get("reasoning_effort", "none")},
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "instructions": PROMPT
            + "\nThe exact top-level output keys for this call are: "
            + ", ".join(schema["properties"])
            + ". Return no other top-level keys.\n"
            + "\nOutput JSON schema:\n"
            + json.dumps(schema, ensure_ascii=False),
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "research_result",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        input_price = self.config.get("input_cost_per_million")
        cached_price = self.config.get("cached_input_cost_per_million", input_price)
        output_price = self.config.get("output_cost_per_million")
        # Conservative reservation: UTF-8 bytes plus a bounded image allowance.
        # Model-specific image accounting can differ; this is not a billing guarantee.
        estimate = None
        if input_price is not None and output_price is not None:
            estimate = (
                (
                    len((serialized + PROMPT + json.dumps(schema) * 2).encode("utf-8"))
                    + len(images) * 20000
                )
                * max(input_price, cached_price)
                + max_output_tokens * output_price
            ) / 1_000_000
        attempts = self.config.get("max_retries", 2) + 1
        for attempt in range(attempts):
            row = budget.reserve(estimate)
            row.update(
                {
                    "model": self.config["name"],
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "attempt": attempt + 1,
                    "currency": self.config.get("currency", "CNY"),
                    "input_sha256": digest(request),
                    "input_images": [
                        {
                            "source_id": image["source_id"],
                            "page": image["page"],
                            "sha256": hashlib.sha256(image["bytes"]).hexdigest(),
                        }
                        for image in images
                    ],
                    "prompt_version": PROMPT_VERSION,
                }
            )
            budget.checkpoint()
            time.sleep(
                max(
                    0,
                    self.config.get("min_interval_seconds", 1)
                    - (time.monotonic() - self._last_call),
                )
            )
            start = time.monotonic()
            self._last_call = start
            retry = False
            retry_after = 0.0
            diagnostics = None
            raw = ""
            try:
                with httpx.Client(
                    transport=self._transport,
                    timeout=self.config.get("timeout_seconds", 90),
                    follow_redirects=False,
                ) as client:
                    response = client.post(
                        "https://api.deepseek.com/responses",
                        headers={"Authorization": f"Bearer {self._key}"},
                        json=payload,
                    )
                row["http_status"] = response.status_code
                if response.status_code != 200:
                    code = {
                        401: "authentication_failed",
                        402: "quota_exhausted",
                        403: "permission_denied",
                        408: "timeout",
                        429: "rate_limited",
                    }.get(
                        response.status_code,
                        "service_error"
                        if response.status_code >= 500
                        else "request_error",
                    )
                    if response.status_code == 429:
                        try:
                            if (
                                response.json().get("error", {}).get("code")
                                == "insufficient_quota"
                            ):
                                code = "quota_exhausted"
                        except (ValueError, AttributeError):
                            pass
                    retry = code in {"rate_limited", "timeout", "service_error"}
                    try:
                        retry_after = min(
                            30, max(0, float(response.headers.get("retry-after", "0")))
                        )
                    except ValueError:
                        pass
                    raise ProcessingError(code)
                try:
                    data = response.json()
                    # A malicious or faulty endpoint must not echo a key into artifacts.
                    data = json.loads(json.dumps(data).replace(self._key, "[REDACTED]"))
                    row["response_id"] = data.get("id")
                    row["returned_model"] = data.get("model")
                    usage = data.get("usage")
                    if isinstance(usage, dict):
                        row["usage"] = {
                            k: usage[k]
                            for k in ("input_tokens", "output_tokens", "total_tokens")
                            if type(usage.get(k)) is int and usage[k] >= 0
                        }
                        for container, key, label in (
                            (
                                "input_tokens_details",
                                "cached_tokens",
                                "cached_input_tokens",
                            ),
                            (
                                "output_tokens_details",
                                "reasoning_tokens",
                                "reasoning_tokens",
                            ),
                        ):
                            detail = usage.get(container)
                            if (
                                isinstance(detail, dict)
                                and type(detail.get(key)) is int
                                and detail[key] >= 0
                            ):
                                row["usage"][label] = detail[key]
                        if (
                            input_price is not None
                            and output_price is not None
                            and all(
                                k in row["usage"]
                                for k in ("input_tokens", "output_tokens")
                            )
                        ):
                            cached_tokens = row["usage"].get("cached_input_tokens", 0)
                            if cached_tokens > row["usage"]["input_tokens"]:
                                raise ValueError(
                                    "cached input tokens exceed total input"
                                )
                            row["estimated_cost"] = (
                                (row["usage"]["input_tokens"] - cached_tokens)
                                * input_price
                                + cached_tokens * cached_price
                                + row["usage"]["output_tokens"] * output_price
                            ) / 1_000_000
                    parts = [
                        c
                        for item in data.get("output", [])
                        if item.get("type") == "message"
                        for c in item.get("content", [])
                    ]
                    if any(p.get("type") == "refusal" for p in parts):
                        raise ProcessingError("model_refusal")
                    raw = "".join(
                        p["text"] for p in parts if p.get("type") == "output_text"
                    )
                    if data.get("status") != "completed":
                        details = data.get("incomplete_details")
                        reason = (
                            details.get("reason") if isinstance(details, dict) else None
                        )
                        row["incomplete_reason"] = (
                            reason
                            if reason in {"max_output_tokens", "content_filter"}
                            else "unspecified"
                        )
                        raise ProcessingError(
                            "model_incomplete",
                            {
                                "candidate_text": raw[:1_000_000],
                                "validation": row["incomplete_reason"],
                                "unvalidated": True,
                            },
                        )
                    result = json.loads(raw)
                    validate(result, schema, "response")
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    raise ProcessingError(
                        "invalid_model_output",
                        {
                            "candidate_text": raw[:1_000_000],
                            "validation": str(exc).replace(self._key, "[REDACTED]"),
                            "unvalidated": True,
                        },
                    ) from None
                row["status"] = "completed"
                return result
            except httpx.TimeoutException:
                row["status"] = "timeout"
                retry = True
            except httpx.RequestError:
                row["status"] = "network_error"
                retry = True
            except ProcessingError as exc:
                row["status"] = exc.code
                diagnostics = exc.diagnostics
            finally:
                row["elapsed_seconds"] = round(time.monotonic() - start, 4)
                budget.checkpoint()
            if not retry or attempt + 1 == attempts:
                raise ProcessingError(row["status"], diagnostics) from None
            time.sleep(max(retry_after, min(2**attempt, 8)))
        raise ProcessingError("service_error")
