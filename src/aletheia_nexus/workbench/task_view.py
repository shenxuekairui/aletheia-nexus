"""Read-only, ordinary-user projections of durable native task receipts."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from .labels import status_label, value_label
from .messages import user_message


def _reason(value) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return "；".join(dict.fromkeys(_reason(v) for v in value if v))
    if isinstance(value, dict):
        reason = user_message(
            value.get("error") or value.get("message") or value.get("status") or value
        )
        page = value.get("page")
        if isinstance(page, str) and (host := urlsplit(page).hostname):
            return host + "：" + reason
        return reason
    return user_message(value)


def task_rows(job: dict) -> list[dict]:
    if "planning_max_cost" in (job.get("parameters") or {}):
        return []
    result = job.get("result") or {}
    items = result.get("items")
    if not isinstance(items, list) and result.get("native_runs"):
        items = [item for run in result["native_runs"] for item in run.get("items", [])]
    if job.get("kind") == "input_normalization":
        items = [
            {
                "id": item["id"],
                "request": item["request"],
                "status": "PREPARED",
                "phase": "输入已整理，尚未获取",
                "folder": item["request"].get("folder") or "默认 / 根目录",
            }
            for item in (result.get("preview") or {}).get("items", [])
            if not item.get("duplicate")
        ]
    if not isinstance(items, list) and isinstance(result.get("preview"), dict):
        items = []
        for item in result["preview"].get("items", []):
            skipped = item.get("status") != "READY"
            state = "SKIPPED" if skipped else result.get("status", job["status"])
            if job.get("kind") == "rollback" and state == "ROLLED_BACK":
                state = "RESTORED"
            location = (
                item.get("old_path")
                if skipped or state in {"ROLLED_BACK", "RESTORED"}
                else item.get("new_path")
                if state == "COMPLETED"
                else ""
            )
            items.append(
                {
                    **item,
                    "status": state,
                    "new_path": location,
                    "folder": str(Path(location).parent)
                    if location
                    else "待核对事务日志",
                    "phase": "验证回滚"
                    if job.get("kind") == "rollback"
                    else "文件整理",
                }
            )
    if not isinstance(items, list):
        # Progress is an append-only event stream. Show each item's latest state,
        # retaining the complete event history in the expert receipt.
        latest = {}
        for event in job.get("records", []):
            native = event.get("native") or {}
            latest[event.get("item_id", len(latest))] = {**event, **native}
        items = list(latest.values())
    rows = []
    for index, item in enumerate(items, 1):
        request = item.get("request") or {}
        source = item.get("source") or {}
        identity = source if isinstance(source, dict) else {}
        document = item.get("document") or {}
        path = (
            item.get("new_path")
            or item.get("pdf")
            or document.get("pdf")
            or item.get("path")
            or ""
        )
        title = (
            item.get("title_original")
            or item.get("title")
            or request.get("title")
            or identity.get("title")
            or (Path(path).name if path else "")
            or request.get("doi")
            or "文献 " + str(index)
        )
        rows.append(
            {
                "id": str(item.get("id") or item.get("item_id") or index),
                "title": title,
                "document_role": item.get("document_role")
                or identity.get("document_role", "ARTICLE"),
                "status": item.get("main_status") or item.get("status", "UNKNOWN"),
                "si_status": item.get("si_status", "NOT_REQUESTED"),
                "phase": item.get("phase") or value_label(job.get("kind")),
                "source": source
                if isinstance(source, str)
                else item.get("source_kind", ""),
                "attempts": item.get("attempts"),
                "folder": item.get("folder")
                or (str(Path(path).parent) if path else ""),
                "reason": item.get("reason")
                or _reason(item.get("error") or item.get("errors")),
                "resumed": bool(item.get("resumed")),
            }
        )
    return rows


def attachment_rows(job: dict) -> list[dict]:
    rows = []
    for paper_index, paper in enumerate((job.get("result") or {}).get("items", []), 1):
        supplements = paper.get("supplements") or {}
        title = (
            (paper.get("request") or {}).get("title")
            or (paper.get("request") or {}).get("doi")
            or f"文献 {paper_index}"
        )
        for index, item in enumerate(supplements.get("items", []), 1):
            path = item.get("path") or urlsplit(item.get("url") or "").path
            rows.append(
                {
                    "id": f"{paper_index}:{index}",
                    "title": title,
                    "filename": Path(path).name,
                    "role": item.get("role", "SUPPLEMENT"),
                    "status": item.get("status", "UNKNOWN"),
                    "reason": _reason(item.get("error") or item.get("errors")),
                    "path": item.get("path", ""),
                }
            )
        if supplements.get("truncated") or supplements.get("errors"):
            rows.append(
                {
                    "id": f"{paper_index}:coverage",
                    "title": title,
                    "filename": "附件覆盖范围",
                    "role": "SUPPLEMENT",
                    "status": "PARTIAL",
                    "reason": "达到附件数量限制，尚有附件未尝试。"
                    if supplements.get("truncated")
                    else _reason(supplements.get("errors")),
                    "path": "",
                }
            )
    return rows


def task_costs(job: dict) -> list[dict]:
    result = job.get("result") or {}
    summaries = []
    label = (
        "AI 整理输入"
        if job.get("kind") == "input_normalization"
        else "标题翻译"
        if job.get("kind") == "translation"
        else "科研模型"
    )
    reports = [(label, result)]
    if isinstance(job.get("planning_calls"), list):
        reports.append(
            (
                "自然语言规划",
                {
                    "calls": job["planning_calls"],
                    "usage": job.get("planning_usage"),
                },
            )
        )
    if not isinstance(result.get("usage"), dict):
        reports.extend(("科研模型", run) for run in result.get("native_runs", []))
    if isinstance(result.get("translation"), dict):
        reports.append(("标题翻译", result["translation"]))
    for label, report in reports:
        calls = report.get("calls")
        usage = report.get("usage")
        if isinstance(calls, list):
            unknown = [c for c in calls if c.get("estimated_cost") is None]
            known = [
                c["estimated_cost"]
                for c in calls
                if c.get("estimated_cost") is not None
            ]
            model = (report.get("options") or {}).get("model") or {}
            summaries.append(
                {
                    "label": "标题翻译"
                    if report.get("options") and label == "科研模型"
                    else label,
                    "calls": len(calls),
                    "currency": (usage or {}).get("currency")
                    or model.get("currency", "CNY"),
                    "known_cost": sum(known) if known or not unknown else None,
                    "reserved_cost": sum(c.get("reserved_cost") or 0 for c in unknown),
                    "unknown_calls": len(unknown),
                }
            )
        elif isinstance(usage, dict) and usage.get("http_attempts") is not None:
            summaries.append(
                {
                    "label": label,
                    "calls": usage["http_attempts"],
                    "currency": usage.get("currency", "CNY"),
                    "known_cost": usage.get("estimated_cost"),
                    "reserved_cost": None,
                    "unknown_calls": max(
                        usage.get("unknown_cost_calls", 0),
                        usage.get("unknown_usage_calls", 0),
                    ),
                }
            )
    return summaries


def task_counts(rows: list[dict]) -> dict:
    success = {
        "COMPLETED",
        "VERIFIED",
        "PARSED",
        "REGISTERED",
        "REUSED",
        "CACHED",
        "TRANSLATED",
        "PRESERVED_MANUAL",
        "ALREADY_PRESENT",
        "PREPARED",
        "RESTORED",
    }
    failed = {
        "FAILED",
        "EXHAUSTED",
        "NOT_FOUND",
        "ACCESS_DENIED",
        "ERROR",
        "RUNNER_ERROR",
        "INVALID_DOI",
        "BROWSER_UNAVAILABLE",
        "UNSAFE_URL",
        "MISMATCH",
        "INVALID_PDF",
        "RETRIEVED_UNVERIFIED",
        "ENTITLEMENT_REQUIRED",
        "ACCESS_BLOCKED",
        "TOO_LARGE",
        "REDIRECT_ERROR",
        "REQUEST_ERROR",
        "NETWORK_ERROR",
        "RATE_LIMITED",
        "SERVICE_ERROR",
        "AMBIGUOUS",
        "ROLLED_BACK",
        "ROLLBACK_REQUIRED",
    }
    groups = {
        "success": success,
        "failed": failed,
        "interaction": {"INTERACTION_REQUIRED", "AUTH_REQUIRED"},
        "partial": {"PARTIAL"},
        "skipped": {"SKIP", "SKIPPED", "CANCELLED"},
    }
    counts = {
        key: sum(r["status"] in states for r in rows) for key, states in groups.items()
    }
    return {"total": len(rows), **counts, "pending": len(rows) - sum(counts.values())}


def state_color(state):
    if state in {"COMPLETED", "VERIFIED", "PARSED", "PREPARED"}:
        return "teal-7"
    if state in {"FAILED", "ROLLBACK_REQUIRED"}:
        return "red-7"
    if state in {"PARTIAL", "INTERACTION_REQUIRED", "AUTH_REQUIRED", "INTERRUPTED"}:
        return "orange-8"
    return "blue-grey-6"


def task_state_text(job):
    return status_label(job.get("status", "UNKNOWN"))
