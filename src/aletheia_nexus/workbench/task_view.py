"""Read-only, ordinary-user projections of durable native task receipts."""

from __future__ import annotations

import math
import re
from pathlib import Path
from urllib.parse import urlsplit

from .labels import status_label, value_label
from .messages import user_message

_CONNECTION_SCHEMA = "aletheia-nexus/browser-connection-diagnostic/v1"
_CONNECTION_CODES = {
    "browser_cdp_attach_timeout": "浏览器连接超时",
    "browser_cdp_attach_failed": "浏览器连接未完成",
    "browser_context_setup_failed": "浏览器安全初始化未完成",
}
_SI_INCOMPLETE = {
    "FAILED",
    "PARTIAL",
    "INTERACTION_REQUIRED",
    "AUTH_REQUIRED",
    "NOT_FOUND",
    "NOT_SUPPORTED",
    "NOT_ATTEMPTED",
}


def _connection_diagnostics(item):
    """Read only the known diagnostic locations, never recursive raw payloads."""
    supplements = item.get("supplements")
    supplements = supplements if isinstance(supplements, dict) else {}
    candidates = [item.get("browser_connection")]
    diagnostics = item.get("diagnostics")
    candidates.extend(diagnostics if isinstance(diagnostics, list) else [])
    diagnostics = supplements.get("diagnostics")
    candidates.extend(diagnostics if isinstance(diagnostics, list) else [])
    attachments = supplements.get("items")
    for attachment in attachments if isinstance(attachments, list) else []:
        if isinstance(attachment, dict):
            diagnostics = attachment.get("diagnostics")
            candidates.extend(diagnostics if isinstance(diagnostics, list) else [])
    return [
        value
        for value in candidates
        if isinstance(value, dict)
        and value.get("schema") == _CONNECTION_SCHEMA
        and isinstance(value.get("code"), str)
        and value.get("code") in _CONNECTION_CODES
    ]


def _connection_items(job):
    result = job.get("result")
    result = result if isinstance(result, dict) else {}
    items = result.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    # No final result yet: retain only each paper's latest native acquisition
    # event. Parse/translation records must not create more affected papers.
    latest = {}
    records = job.get("records")
    for event in [
        *(records if isinstance(records, list) else []),
        job.get("current_item"),
    ]:
        if not isinstance(event, dict):
            continue
        native = event.get("native")
        item = {**event, **(native if isinstance(native, dict) else {})}
        request = item.get("request")
        if not isinstance(request, dict):
            continue
        key = (
            item.get("id")
            or item.get("item_id")
            or request.get("doi")
            or request.get("title")
        )
        if isinstance(key, (str, int)):
            latest[str(key)] = item
    return list(latest.values())


def browser_connection_summaries(job: dict) -> list[dict]:
    """Safe, grouped recovery cards; no raw messages, actions, URLs or IDs.

    Receipts can contain arbitrary legacy/native fields. Rebuild ordinary-user
    wording from a closed set of codes and typed facts rather than displaying
    the stored SDK error, endpoint, target inventory, or suggested action text.
    """
    if job.get("kind") not in {"acquisition", "acquire"}:
        return []

    def number(value):
        try:
            return (
                value
                if type(value) in {int, float} and math.isfinite(value) and value >= 0
                else None
            )
        except OverflowError:
            return None

    def count(value):
        return value if type(value) is int and 0 <= value < 10**9 else None

    def known_boolean(value):
        return value if type(value) is bool else None

    groups = {}
    for index, item in enumerate(_connection_items(job)):
        state = item.get("main_status") or item.get("status")
        si_only = (
            state == "VERIFIED"
            and isinstance(item.get("si_status"), str)
            and item["si_status"] in _SI_INCOMPLETE
        )
        if state != "BROWSER_UNAVAILABLE" and not si_only:
            continue
        # The same diagnostic occurs both on the paper and on its SI transport.
        # A paper counts once per group, irrespective of the number of copies.
        for diagnostic in _connection_diagnostics(item):
            code = diagnostic["code"]
            facts = {
                "code": code,
                "stage": "context_setup"
                if code == "browser_context_setup_failed"
                else "cdp_attach",
                "timeout_seconds": number(diagnostic.get("timeout_seconds")),
                "websocket_connected": known_boolean(
                    diagnostic.get("websocket_connected")
                ),
                "endpoint_reachable": known_boolean(
                    diagnostic.get("endpoint_reachable")
                ),
                "page_count": count(diagnostic.get("page_count")),
                "pdf_like_page_count": count(diagnostic.get("pdf_like_page_count")),
            }
            key = tuple(facts.values())
            group = groups.setdefault(key, {**facts, "main": set(), "si": set()})
            group["si" if si_only else "main"].add(index)
    summaries = []
    retry_available = job.get("status") in {
        "PARTIAL",
        "FAILED",
        "CANCELLED",
        "INTERRUPTED",
    }
    for group in groups.values():
        main, si = len(group.pop("main")), len(group.pop("si"))
        timeout = group["timeout_seconds"]
        stage = (
            "连接现有浏览器" if group["stage"] == "cdp_attach" else "连接后的安全初始化"
        )
        state_labels = {True: "已连接", False: "未连接", None: "未知"}
        endpoint_labels = {True: "可响应", False: "未确认可响应", None: "未知"}
        facts = [
            f"阶段：{stage}",
            "连接期限：" + (f"{timeout:g} 秒" if timeout is not None else "未记录"),
            "本机控制端点：" + endpoint_labels[group["endpoint_reachable"]],
            "WebSocket：" + state_labels[group["websocket_connected"]],
        ]
        if group["page_count"] is not None:
            facts.append(f"原有标签：{group['page_count']} 个")
        if group["pdf_like_page_count"] is not None:
            facts.append(f"可能的 PDF 标签：{group['pdf_like_page_count']} 个")
        instructions = ["本页不会自动重新连接、关闭浏览器标签或重发模型请求。"]
        if group["pdf_like_page_count"]:
            instructions.append(
                "PDF 标签只是排查线索。先保存阅读进度，再自行决定是否关闭无响应的 PDF 标签后重试，无需关闭整个浏览器。"
            )
        if retry_available:
            instructions.append(
                "使用下方“重试获取失败 / 补取 SI”预览实际范围并检查命名会话；选择其他会话时需另行完成机构登录，不迁移登录资料。"
            )
            if si:
                instructions.append(
                    "正文已验证的论文可仅补取 SI；恢复前仍会核对正文与来源文件，不重新下载有效正文。"
                )
        else:
            instructions.append(
                "任务结束后再核对失败项与恢复范围。"
                if job.get("status") not in {"COMPLETED"}
                else "这是已完成任务的历史诊断，本页不会重新执行。"
            )
        summaries.append(
            {
                **group,
                "heading": _CONNECTION_CODES[group["code"]],
                "affected_count": main + si,
                "main_unavailable_count": main,
                "si_only_count": si,
                "summary": f"同一连接问题影响 {main + si} 篇：{main} 篇正文尚未验证成功，{si} 篇正文已验证、仅 SI 待处理。",
                "observations": " · ".join(facts),
                "instructions": instructions,
                "retry_available": retry_available,
            }
        )
    return summaries


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
        state = item.get("main_status") or item.get("status", "UNKNOWN")
        connection_reason = None
        if _connection_diagnostics(item):
            if state == "BROWSER_UNAVAILABLE":
                connection_reason = "浏览器连接未完成；请查看本批恢复提示。"
            elif (
                state == "VERIFIED"
                and isinstance(item.get("si_status"), str)
                and item["si_status"] in _SI_INCOMPLETE
            ):
                connection_reason = (
                    "正文已验证；SI 浏览器连接未完成，请查看本批恢复提示。"
                )
        rows.append(
            {
                "id": str(item.get("id") or item.get("item_id") or index),
                "title": title,
                "document_role": item.get("document_role")
                or identity.get("document_role", "ARTICLE"),
                "status": state,
                "si_status": item.get("si_status", "NOT_REQUESTED"),
                "phase": item.get("phase") or value_label(job.get("kind")),
                "source": source
                if isinstance(source, str)
                else item.get("source_kind", ""),
                "attempts": item.get("attempts"),
                "folder": item.get("folder")
                or (str(Path(path).parent) if path else ""),
                "reason": connection_reason
                or item.get("reason")
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
                    "reason": "附件浏览器连接未完成；请查看本批恢复提示。"
                    if _connection_diagnostics(item)
                    else _reason(item.get("error") or item.get("errors")),
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


def task_stage_text(job):
    """Describe cancellation from actual task scope, including old receipts."""
    if job.get("status") != "CANCEL_REQUESTED":
        return value_label(job.get("stage") or job.get("kind") or "")
    kind = job.get("kind")
    unit = {
        "acquisition": "论文",
        "acquire": "论文",
        "parse": "文件",
        "import": "文件",
        "translation": "标题批次",
        "research": "研究处理",
        "input_normalization": "模型请求",
    }.get(kind, "处理")
    message = f"正在等待当前操作到达安全边界；不会继续调度后续{unit}。"
    parameters = job.get("parameters") or {}
    parameters = parameters if isinstance(parameters, dict) else {}
    task = parameters.get("task") or {}
    task = task if isinstance(task, dict) else {}
    postprocess = parameters.get("postprocess") or {}
    postprocess = postprocess if isinstance(postprocess, dict) else {}
    translated = (
        parameters.get("title_translation")
        or postprocess.get("title_translation")
        or {}
    )
    translated = translated if isinstance(translated, dict) else {}
    remote = (
        kind in {"translation", "input_normalization"}
        or kind == "research"
        and (
            "planning_max_cost" in parameters
            or task.get("mode", "local") != "local"
            and task.get("allow_remote")
        )
        or translated.get("enabled")
        and translated.get("consent")
        or job.get("billing_uncertain")
    )
    if remote:
        message += "若模型请求已经发送，仍可能已计费，请在任务中心核对调用账本。"
    return message


def acquisition_retry_label(label, count):
    """Collapse only the generated retry prefix, retaining the base display name."""
    base = re.sub(r"^(?:重试\s*[0-9]+\s*篇\s*·\s*)+", "", label)
    return f"重试 {count} 篇 · {base or label}"
