"""One explicit Responses API adapter, with injectable HTTP transport."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

import httpx

from .contracts import MODEL, PROMPT, PROMPT_VERSION, digest, validate
from .json_closure import apply_closure, recover_closure
from .review import REVIEW_PROMPT, REVIEW_VERSION, REVISION_PROMPT
from .source_first import (
    ASSEMBLY_PROMPT,
    INVENTORY_PHASE,
    INVENTORY_PROMPT,
    SOURCE_FIRST_VERSION,
    is_assembly_request,
)

MAX_INLINE_REQUEST_BYTES = 48 * 1024 * 1024
# DeepSeek's documented per-image maximum, checked 2026-10-26:
# https://api-docs.deepseek.com/zh-cn/guides/vision/
MAX_IMAGE_INPUT_TOKENS = 1024


class ProjectedResponse(dict):
    """A normal response mapping with separately persisted, replayable provenance."""

    def __init__(self, response: dict, metadata: dict):
        super().__init__(response)
        self.metadata = metadata


def project_response(
    response: dict,
    schema: dict,
    targets: list | None = None,
    *,
    raw_text: str | None = None,
) -> dict:
    """Project empty extensions and known metadata with replayable raw provenance."""
    projected = deepcopy(response)
    targets = targets or []
    by_target = {target["target_id"]: target for target in targets}
    changes = []

    def visit(value, contract, path):
        if isinstance(value, dict):
            properties = contract.get("properties", {})
            removable = {
                key: (
                    "null_unknown_property_extension"
                    if child is None
                    else "empty_unknown_array_extension"
                )
                for key, child in value.items()
                if "properties" in contract
                and key not in properties
                and (
                    child == []
                    or (child is None and contract.get("additionalProperties") is False)
                )
            }
            is_step = (
                len(path) == 4
                and path[2] == "steps"
                and (
                    path[0] == "records"
                    or (path[0] == "replacements" and path[1].endswith("/steps"))
                )
            )
            is_claim = len(path) == 2 and (
                path[0] == "claims"
                or (path[0] == "replacements" and path[1].startswith("claim:"))
            )
            is_field = (
                len(path) == 4 and path[0] == "records" and path[2] == "fields"
            ) or (
                len(path) == 2
                and path[0] == "replacements"
                and by_target.get(path[1], {}).get("kind") == "field"
            )
            if is_step and value.get("citations_note") in (None, "", "not_a_field"):
                removable["citations_note"] = "empty_or_placeholder_step_note"
            if is_claim and value.get("citations_note") in (None, "", "not_a_field"):
                removable["citations_note"] = "empty_or_placeholder_claim_note"
            if is_claim and value.get("step_ids") == []:
                removable["step_ids"] = "empty_claim_step_ids"
            if len(path) == 2 and path[0] == "checks":
                target = by_target.get(value.get("target_id"), {})
                for key in ("kind", "record_id", "field_id"):
                    if key in target and value.get(key) == target[key]:
                        removable[key] = "echoed_review_target"
            for key, reason in removable.items():
                if key in value and key not in properties:
                    changes.append(
                        {
                            "path": [*path, key],
                            "value": value.pop(key),
                            "reason": reason,
                        }
                    )
            for key in ("steps", "step_ids"):
                child = properties.get(key, {})
                if (
                    key not in value
                    and key in contract.get("required", [])
                    and child.get("type") == "array"
                    and child.get("minItems", 0) == 0
                    and (child.get("maxItems") == 0 or (is_field and key == "step_ids"))
                ):
                    value[key] = []
                    changes.append(
                        {
                            "operation": "add",
                            "path": [*path, key],
                            "value": [],
                            "reason": (
                                "disabled_steps_require_empty_array"
                                if child.get("maxItems") == 0
                                else "unprovided_field_step_links"
                            ),
                        }
                    )
            for key in value:
                if key in properties:
                    if value[key] is None and _empty_object_schema(properties[key]):
                        value[key] = {}
                        changes.append(
                            {
                                "operation": "replace",
                                "path": [*path, key],
                                "before": None,
                                "value": {},
                                "reason": "wire_placeholder_for_empty_object",
                            }
                        )
                    visit(value[key], properties[key], [*path, key])
        elif isinstance(value, list) and "items" in contract:
            for index, item in enumerate(value):
                visit(item, contract["items"], [*path, index])

    visit(projected, schema, [])
    validate(projected, schema, "response")
    if not changes:
        return projected
    return ProjectedResponse(
        projected,
        {
            "version": 1,
            "raw_text": raw_text
            if raw_text is not None
            else json.dumps(response, ensure_ascii=False, allow_nan=False),
            "schema": deepcopy(schema),
            "targets": deepcopy(targets),
            "changes": changes,
            "output_sha256": digest(projected),
        },
    )


def decode_response(
    raw: str, schema: dict, targets: list | None = None, *, allow_closure: bool = True
) -> dict:
    """Decode a completed response, retaining reversible syntax and projection proof."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        if not allow_closure:
            raise
        parsed, closure = recover_closure(
            raw, lambda value: project_response(value, schema, targets)
        )
        response = project_response(parsed, schema, targets)
        metadata = (
            deepcopy(response.metadata)
            if isinstance(response, ProjectedResponse)
            else {
                "version": 1,
                "schema": deepcopy(schema),
                "targets": deepcopy(targets or []),
                "changes": [],
                "output_sha256": digest(response),
            }
        )
        metadata.update(raw_text=raw, json_closure=closure)
        return ProjectedResponse(dict(response), metadata)
    return project_response(parsed, schema, targets, raw_text=raw)


def raw_response_value(response: dict) -> dict:
    """Read pre-projection JSON without discarding its original malformed raw text."""
    if not isinstance(response, ProjectedResponse):
        return deepcopy(response)
    metadata = response.metadata
    raw = metadata["raw_text"]
    if metadata.get("json_closure"):
        raw = apply_closure(raw, metadata["json_closure"]["selected"]["insertion"])
    return json.loads(raw)


def _empty_object_schema(schema: dict) -> bool:
    return schema == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def _wire_schema(schema: dict, *, empty_placeholder: bool = False) -> dict:
    """Adapt container syntax while preserving the locally validated contract.

    DeepSeek rejects empty object schemas. An exactly empty object member has
    one legal value, so use a null wire placeholder and trace its restoration.
    Root schemas, array items and nullable scientific values retain their types.
    """
    if empty_placeholder and _empty_object_schema(schema):
        return {"type": "null"}
    converted = {
        key: {
            name: _wire_schema(child, empty_placeholder=True)
            for name, child in value.items()
        }
        if key == "properties"
        else _wire_schema(value)
        if key == "items"
        else value
        for key, value in schema.items()
    }
    kinds = converted.get("type")
    if isinstance(kinds, list) and {"object", "array"}.intersection(kinds):
        return {
            "anyOf": [
                {"type": "null"} if kind == "null" else {**converted, "type": kind}
                for kind in kinds
            ]
        }
    return converted


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
        instructions: str | None = None,
        prompt_version: str | None = None,
    ):
        if not enabled:
            raise ProcessingError("remote_disabled")
        validate(config, MODEL, "provider_config")
        self.config = dict(config)
        self._key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not self._key:
            raise ProcessingError("missing_api_key")
        from .api_config import resolve_deepseek_endpoint

        self._endpoint = resolve_deepseek_endpoint("responses")
        self._transport = transport
        self._last_call = 0.0
        # Trusted application services may reuse authentication, transport and
        # accounting for a small independent operation (e.g. title translation).
        # Scientific callers retain the exact default prompt and cache identity.
        self._instructions = instructions
        self._prompt_version = prompt_version or PROMPT_VERSION

    @property
    def identity(self) -> dict:
        return {
            "provider": "deepseek-responses",
            "adapter_version": "8",
            "temperature": 0,
            "model": self.config["name"],
            "config": self.config,
            "prompt_version": self._prompt_version,
            "prompt_sha256": digest(self._instructions or PROMPT),
            "review_version": REVIEW_VERSION,
            "review_prompt_sha256": digest([REVIEW_PROMPT, REVISION_PROMPT]),
        }

    def generate(
        self,
        request: dict,
        schema: dict,
        images: list[dict],
        budget: CallBudget,
        max_output_tokens: int,
    ) -> dict:
        phase = request.get("phase")
        assembly = is_assembly_request(request)
        prompt = self._instructions or (
            INVENTORY_PROMPT
            if phase == INVENTORY_PHASE
            else ASSEMBLY_PROMPT
            if assembly
            else REVIEW_PROMPT
            if phase == "evidence_review"
            else PROMPT + REVISION_PROMPT
            if phase == "document_revision"
            else PROMPT
        )
        prompt_version = (
            self._prompt_version
            if self._instructions
            else SOURCE_FIRST_VERSION + (":assembly" if assembly else ":inventory")
            if phase == INVENTORY_PHASE or assembly
            else self._prompt_version
        )
        serialized = json.dumps(request, ensure_ascii=False, allow_nan=False)
        content = [{"type": "input_text", "text": serialized}]
        for item in images:
            content.extend(
                [
                    {
                        "type": "input_text",
                        "text": f"Source {item['source_id']}, PDF page {item['page']}"
                        + (
                            f", {item['view']}, region {item['region']} "
                            "in displayed-page normalized coordinates (top-left origin). "
                            "Overlapping views show the same page, not separate evidence."
                            if "region" in item
                            else ""
                        ),
                    },
                    {
                        "type": "input_image",
                        "detail": "high",
                        "image_url": "data:image/png;base64,"
                        + base64.b64encode(item["bytes"]).decode("ascii"),
                    },
                ]
            )
        wire_schema = _wire_schema(schema)
        payload = {
            "model": self.config["name"],
            "store": False,
            "reasoning": {"effort": self.config.get("reasoning_effort", "high")},
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "instructions": prompt
            + "\nThe exact top-level output keys for this call are: "
            + ", ".join(schema["properties"])
            + ". Return no other top-level keys.\n"
            + "\nOutput JSON schema:\n"
            + json.dumps(wire_schema, ensure_ascii=False),
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "research_result",
                    "strict": True,
                    "schema": wire_schema,
                }
            },
        }
        if (
            len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            > MAX_INLINE_REQUEST_BYTES
        ):
            raise ProcessingError("request_body_budget_exceeded")
        input_price = self.config.get("input_cost_per_million")
        cached_price = self.config.get("cached_input_cost_per_million", input_price)
        output_price = self.config.get("output_cost_per_million")
        # Reserve text bytes, each image's documented maximum and full output.
        # Actual returned usage settles the reservation; this is not a provider bill.
        estimate = None
        if input_price is not None and output_price is not None:
            estimate = (
                (
                    len(
                        (serialized + prompt + json.dumps(wire_schema) * 2).encode(
                            "utf-8"
                        )
                    )
                    + len(images) * MAX_IMAGE_INPUT_TOKENS
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
                            **(
                                {"region": image["region"], "view": image["view"]}
                                if "region" in image
                                else {}
                            ),
                        }
                        for image in images
                    ],
                    "prompt_version": prompt_version,
                    "phase": phase,
                    "effective_prompt_sha256": digest(prompt),
                    "review_version": REVIEW_VERSION
                    if phase in {"evidence_review", "document_revision"}
                    else None,
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
                    timeout=self.config.get("timeout_seconds", 300),
                    follow_redirects=False,
                ) as client:
                    response = client.post(
                        self._endpoint,
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
                    row["response_status"] = data.get("status")
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
                    result = decode_response(
                        raw,
                        schema,
                        request.get("targets"),
                        allow_closure=not data.get("incomplete_details")
                        and all(
                            item.get("finish_reason")
                            not in {"length", "max_output_tokens", "content_filter"}
                            for item in [data, *data.get("output", [])]
                        ),
                    )
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
            except httpx.TimeoutException as exc:
                row["status"] = "timeout"
                row["transport_error_type"] = type(exc).__name__
                diagnostics = {"transport_error_type": row["transport_error_type"]}
                retry = True
            except httpx.RequestError as exc:
                row["status"] = "network_error"
                row["transport_error_type"] = type(exc).__name__
                diagnostics = {"transport_error_type": row["transport_error_type"]}
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
