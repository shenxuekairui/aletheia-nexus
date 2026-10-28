"""Reviewed retry scopes, bound to current acquisition evidence, without network."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path

from .acquisition import _options, normalize_request
from .settings import atomic_json

CHECKPOINT_SCHEMA = "aletheia-nexus/access-batch-checkpoint/v1"


def recovery_preview(job, service):
    """Read current bytes, never trust a previous VERIFIED display by itself."""
    if job.get("kind") not in {"acquisition", "acquire"}:
        raise ValueError("此入口只重试论文获取任务。")
    if job.get("status") not in {
        "COMPLETED",
        "PARTIAL",
        "FAILED",
        "CANCELLED",
        "INTERRUPTED",
    }:
        raise ValueError(
            "原获取任务尚未结束，请先等待完成或在安全边界取消，避免重复调度。"
        )
    parameters = job.get("parameters") or {}
    root = service.root.resolve()
    if parameters.get("library") and Path(parameters["library"]).resolve() != root:
        raise ValueError("原获取任务属于另一文库，请切回原文库后重试。")
    requests = [normalize_request(r) for r in parameters.get("requests", [])]
    if not requests:
        raise ValueError("此任务没有可恢复的原始获取参数，请从获取页新建任务。")
    if len({r.key for r in requests}) != len(requests):
        raise ValueError(
            "历史批次包含重复论文身份，请先在获取页核对并只保留一份保存安排。"
        )
    options = _options(parameters.get("options", {}))
    result = job.get("result") or {}
    raw_checkpoint = result.get("checkpoint") or job.get("checkpoint")
    checkpoint, checkpoint_hash, records, warnings = None, None, {}, []
    if raw_checkpoint:
        path = Path(raw_checkpoint).resolve()
        if not path.is_relative_to(service.state_dir.resolve()):
            raise ValueError("检查点不在当前工作区的获取目录内，不能用于恢复。")
        if path.is_file():
            raw = path.read_bytes()
            before = sha256(raw).hexdigest()
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or payload.get("schema") != CHECKPOINT_SCHEMA
                or not isinstance(payload.get("records"), dict)
                or sha256_file(path) != before
            ):
                raise ValueError(
                    "获取检查点格式无效或读取期间发生变化，请先核对原任务。"
                )
            checkpoint, checkpoint_hash, records = str(path), before, payload["records"]
        else:
            warnings.append("原检查点已缺失；旧成功标记不能代替当前来源与可复用依据。")
    else:
        warnings.append(
            "历史任务未记录检查点；不会仅凭旧成功状态重新下载已存在的正文。"
        )
    delivered = {}
    for item in [*job.get("records", []), *result.get("items", [])]:
        if isinstance(item.get("request"), dict):
            delivered[normalize_request(item["request"]).key] = item
    catalog = None

    def current_source(request, record):
        nonlocal catalog
        old = record.get("verified_path")
        if record.get("status") != "VERIFIED" or not isinstance(old, str):
            return None
        original = Path(old).resolve()
        if not original.is_relative_to(root):
            raise ValueError("检查点记录的正文位于当前文库之外，不能恢复。")
        candidates = [original]
        if not original.is_file() and service.library is not None:
            if catalog is None:
                catalog = service.library.scan()["items"]
            candidates = [
                Path(row["pdf_path"]).resolve()
                for row in catalog
                if row.get("pdf_sha256") == record.get("sha256")
            ]
        matched = []
        for path in candidates:
            if not path.is_relative_to(root) or not acquisition_sidecar_path(
                path
            ).resolve().is_relative_to(root):
                continue
            try:
                checked = validate_parser_input(path, requested_doi=request.doi)
                if (
                    checked.document_role == "ARTICLE"
                    and checked.identity_basis == "acquisition_verified"
                    and checked.pdf_sha256 == record.get("sha256")
                    and checked.sidecar_sha256 == record.get("sidecar_sha256")
                ):
                    matched.append(checked)
            except (OSError, ValueError):
                continue
        return matched[0] if len(matched) == 1 else None

    rows = []
    for request in requests:
        item = delivered.get(request.key, {})
        record = records.get(request.batch_key, {})
        if not isinstance(record, dict):
            raise ValueError("检查点包含无效逐篇记录，请先核对原任务。")
        source = current_source(request, record)
        main_status = item.get("main_status") or item.get("status") or "NOT_ATTEMPTED"
        si_status = item.get("si_status") or "NOT_ATTEMPTED"
        if source:
            complete_si = not options["include_si"] or (
                si_status == "COMPLETED"
                and not (item.get("supplements") or {}).get("truncated")
            )
            if complete_si and options["include_si"]:
                saved = (item.get("supplements") or {}).get("items") or []
                complete_si = bool(saved) and all(
                    a.get("status") in {"SAVED", "REUSED"}
                    and isinstance(a.get("path"), str)
                    and Path(a["path"]).resolve().is_relative_to(root)
                    and Path(a["path"]).is_file()
                    and sha256_file(Path(a["path"])) == a.get("sha256")
                    for a in saved
                )
            category = "COMPLETE" if complete_si else "SI_INCOMPLETE"
            reason = (
                "正文来源与检查点当前有效，完整完成项不重复调度。"
                if complete_si
                else "复用已验证正文，仅继续发现或获取未完整取得的 SI；已有附件仍由原服务检查后复用。"
            )
            can_retry = not complete_si
            folder = source.pdf_path.parent.relative_to(root).as_posix()
            main_status = "VERIFIED"
        elif main_status == "VERIFIED":
            category, can_retry = "NEEDS_REVIEW", False
            reason = "旧记录称正文成功，但当前缺少唯一、有效的检查点与来源绑定；请先检查文件和原任务，避免重复下载。"
            folder = request.folder or ""
        else:
            category = (
                "NOT_STARTED"
                if main_status in {"NOT_ATTEMPTED", "DEFERRED", "SKIPPED", "CANCELLED"}
                else "MAIN_FAILED"
            )
            can_retry = True
            folder = request.folder or ""
            reason = (
                "此前尚未完成获取，将按保留的逐篇参数开始。"
                if category == "NOT_STARTED"
                else "正文未通过当前来源核验，将重新尝试原获取路线；不会把旧状态当作成功。"
            )
        rows.append(
            {
                "id": request.batch_key,
                "request": asdict(request),
                "title": request.title or request.doi or request.cnki_id,
                "category": category,
                "main_status": main_status,
                "main_verified": source is not None,
                "si_status": si_status if options["include_si"] else "NOT_REQUESTED",
                "folder": "" if folder == "." else folder,
                "tags": list(request.tags),
                "pdf": str(source.pdf_path) if source else None,
                "can_retry": can_retry,
                "selected": can_retry,
                "reason": reason,
            }
        )
    return {
        "rows": rows,
        "options": options,
        "checkpoint": checkpoint,
        "checkpoint_sha256": checkpoint_hash,
        "warnings": warnings,
        "library": str(root),
    }


def recovery_requests(preview, selected_ids):
    """Validate the exact chosen scope; never silently include the full batch."""
    ids = list(selected_ids)
    rows = {row["id"]: row for row in preview["rows"]}
    if not ids or len(set(ids)) != len(ids) or set(ids) - rows.keys():
        raise ValueError("请明确选择至少一篇可重试论文，不能使用重复或已失效的范围。")
    if any(not rows[key]["can_retry"] for key in ids):
        raise ValueError("所选项包含已完整完成或需先核对来源的论文，请只选择可重试项。")
    chosen = set(ids)
    return [deepcopy(row["request"]) for row in preview["rows"] if row["id"] in chosen]


def recovery_checkpoint(preview, service):
    """Use a new checkpoint per retry; preserve the original receipt bytes."""
    target = service.state_dir / (uuid4().hex + ".retry.checkpoint.json")
    source = preview.get("checkpoint")
    if source:
        path = Path(source).resolve()
        if not path.is_relative_to(service.state_dir.resolve()):
            raise ValueError("恢复检查点不在当前工作区内。")
        raw = path.read_bytes()
        before = sha256(raw).hexdigest()
        payload = json.loads(raw)
        if (
            before != preview["checkpoint_sha256"]
            or sha256_file(path) != before
            or not isinstance(payload, dict)
            or payload.get("schema") != CHECKPOINT_SCHEMA
            or not isinstance(payload.get("records"), dict)
        ):
            raise ValueError("检查点在预览后发生变化，请重新打开重试预览。")
    else:
        payload = {"schema": CHECKPOINT_SCHEMA, "records": {}}
    atomic_json(target, payload)
    return str(target)
