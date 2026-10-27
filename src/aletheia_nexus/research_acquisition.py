"""Public DOI acquisition adapter; existing access batch owns retrieval and resume."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from aletheia_nexus.acquire.access.batch import acquire_full_text_batch_maximized
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.paper_request import PaperRequest
from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing.provider import ProcessingError

POLICY = {
    "public_only": True,
    "auto_official_api": False,
    "source_preference": "exclude_cnki",
    "max_route_attempts": 4,
    "max_file_attempts": 4,
    "discovery_max_attempts": 1,
    "metadata_max_attempts": 1,
    "max_attempts_per_route": 1,
    "max_attempts_per_file": 1,
    "timeout": 30,
    "keep_unverified": False,
}


def public_acquisition_plan(app, payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.keys() - {"papers", "resume_job_id"}:
        raise ValueError("acquisition accepts papers and optional resume_job_id")
    papers = payload.get("papers")
    if not isinstance(papers, list) or not 1 <= len(papers) <= 10:
        raise ValueError("select between1 and10 DOI requests")
    selected = []
    for paper in papers:
        if not isinstance(paper, dict) or paper.keys() - {"doi", "title"}:
            raise ValueError("each paper accepts DOI and optional expected title")
        value = {"doi": normalize_doi(paper.get("doi"))}
        if "title" in paper:
            if not isinstance(paper["title"], str) or not paper["title"].strip():
                raise ValueError("expected title must be nonempty")
            value["title"] = paper["title"].strip()
        if value not in selected:
            selected.append(value)
    normalized = {"papers": selected}
    resume = None
    if "resume_job_id" in payload:
        job_id = payload["resume_job_id"]
        if not isinstance(job_id, str) or not re.fullmatch("[0-9a-f]{32}", job_id):
            raise ValueError("invalid acquisition resume job ID")
        parent = app.path(app.workspace / "jobs" / job_id, write=True)
        saved = json.loads((parent / "acquisition-request.json").read_text("utf-8"))
        if saved["papers"] != selected:
            raise ProcessingError("acquisition_resume_scope_changed")
        state = app.get_run_status(job_id)
        if state.get("kind") != "acquisition":
            raise ProcessingError("not_an_acquisition_job")
        if state["status"] in {"QUEUED", "RUNNING"}:
            raise ProcessingError("acquisition_job_still_running")
        checkpoint = app.path(parent / "acquisition-checkpoint.json", write=True)
        data = (
            json.loads(checkpoint.read_text("utf-8"))
            if checkpoint.exists()
            else {"schema": "aletheia-nexus/access-batch-checkpoint/v1", "records": {}}
        )
        if data.get(
            "schema"
        ) != "aletheia-nexus/access-batch-checkpoint/v1" or not isinstance(
            data.get("records"), dict
        ):
            raise ValueError("invalid acquisition checkpoint")
        downloads = app.path(parent / "downloads", write=True)
        records = {}
        for paper in selected:
            key = PaperRequest(**paper).batch_key
            record = data["records"].get(key)
            if record is None:
                continue
            path = record.get("verified_path")
            if isinstance(path, str):
                target = app.path(path)
                if not target.is_relative_to(downloads):
                    raise ProcessingError("acquisition_checkpoint_path_outside_job")
                if not app.path(acquisition_sidecar_path(target)).is_relative_to(
                    downloads
                ):
                    raise ProcessingError("acquisition_checkpoint_path_outside_job")
            records[key] = record
        resume = {
            "job_id": job_id,
            "checkpoint": checkpoint,
            "sha256": sha256_file(checkpoint) if checkpoint.exists() else None,
            "records": records,
        }
        normalized["resume_job_id"] = job_id
    binding = {
        "request": normalized,
        "policy": POLICY,
        "resume_checkpoint_sha256": resume["sha256"] if resume else None,
    }
    lines = [
        f"公共全文获取：{len(selected)}篇（只接受DOI，可附题名身份约束）",
        *[f"  {p['doi']} · {p.get('title', '按DOI核对身份')}" for p in selected],
        f"新文件仅保存至：{app.workspace / 'jobs'} 下的新任务目录。",
        "将向公共元数据/出版社服务发送上述DOI及可选题名；不发送本地论文内容。",
        "每篇最多4条来源路线、4个文件候选；单次网络超时30秒，各路径/文件最多尝试1次。",
        "不打开浏览器、不使用机构/官方凭据、不调用AI模型；失败不会自动升级访问权限。",
    ]
    if resume:
        lines.append(
            "恢复原任务：只复制并复核所选文献的有效文件，原断点和历史不改；失败项重新获取。"
        )
        if resume["sha256"] is None:
            lines.append(
                "原任务未留下断点文件；本次重新获取所选范围，不自动信任或复用遗留文件。"
            )
    return {
        "payload": normalized,
        "binding": binding,
        "resume": resume,
        "plan": "\n".join(lines),
    }


def _resume_checkpoint(app, plan: dict, directory: Path) -> Path:
    target = app.path(directory / "acquisition-checkpoint.json", write=True)
    resume = plan["resume"]
    if resume is None:
        return target
    current_hash = (
        sha256_file(resume["checkpoint"]) if resume["checkpoint"].exists() else None
    )
    if current_hash != resume["sha256"]:
        raise ProcessingError("acquisition_checkpoint_changed_after_authorization")
    records = deepcopy(resume["records"])
    for record in records.values():
        old = record.get("verified_path")
        copied = False
        if record.get("status") == "VERIFIED" and isinstance(old, str):
            source = app.path(old)
            sidecar = app.path(acquisition_sidecar_path(source))
            if (
                source.is_file()
                and sidecar.is_file()
                and sha256_file(source) == record.get("sha256")
                and sha256_file(sidecar) == record.get("sidecar_sha256")
            ):
                check = app.get_acquisition_status(
                    str(sidecar), pdf=str(source), expected_doi=record["doi"]
                )["current_check"]
                if check.get("identity_verified"):
                    pdf = app._copy_source_file(
                        source, directory / "downloads" / source.name
                    )
                    app._copy_source_file(sidecar, acquisition_sidecar_path(pdf))
                    record["verified_path"] = str(pdf)
                    copied = True
        if not copied:
            record.update(status="ERROR", verified_path=None)
    write_json(
        target,
        {"schema": "aletheia-nexus/access-batch-checkpoint/v1", "records": records},
    )
    write_json(
        directory / "resume-source.json",
        {
            "job_id": resume["job_id"],
            "checkpoint_sha256": resume["sha256"],
            "original_unchanged": True,
        },
    )
    return target


def acquire_public_documents(app, plan: dict, directory: Path, progress) -> dict:
    checkpoint = _resume_checkpoint(app, plan, directory)
    items = []

    def completed(item, index, total):
        row = {
            "doi": item.doi,
            "status": item.status.value,
            "resumed": item.resumed,
            "attempts": item.attempts,
            "elapsed_seconds": item.elapsed_seconds,
        }
        if item.status.value == "RUNNER_ERROR":
            # The existing batch stores exception class names, never messages.
            row["error_type"] = item.error
        if item.result is not None:
            row["public_status"] = item.result.base_result.status.value
        if item.status.value == "VERIFIED" and item.verified_path is None:
            row.update(status="ERROR", error="acquisition_verified_file_missing")
        if item.verified_path is not None:
            pdf = app.path(item.verified_path, write=True)
            if not pdf.is_relative_to(app.path(directory / "downloads", write=True)):
                raise ProcessingError("acquisition_output_path_outside_job")
            sidecar = app.path(acquisition_sidecar_path(pdf), write=True)
            verified = app.get_acquisition_status(
                str(sidecar), pdf=str(pdf), expected_doi=item.doi
            )
            check = verified["current_check"]
            if check.get("status") != "PASSED" or not check.get("identity_verified"):
                row.update(
                    status="ERROR", error="acquisition_source_verification_failed"
                )
            else:
                row.update(
                    pdf=str(pdf),
                    sidecar=str(sidecar),
                    pdf_sha256=check["pdf_sha256"],
                    page_count=check["page_count"],
                    identity_verified=True,
                )
        items.append(row)
        progress(
            {
                "completed": index,
                "total": total,
                "latest": row,
                "items": deepcopy(items),
            }
        )

    result = acquire_full_text_batch_maximized(
        [PaperRequest(**p) for p in plan["payload"]["papers"]],
        output_dir=app.path(directory / "downloads", write=True),
        checkpoint_path=checkpoint,
        resume=True,
        max_item_attempts=1,
        progress_callback=completed,
        **POLICY,
    )
    success = sum(
        row["status"] == "VERIFIED" and row.get("identity_verified") is True
        for row in items
    )
    return {
        "status": "COMPLETED"
        if success == len(items)
        else "PARTIAL"
        if success
        else "FAILED",
        "items": items,
        "checkpoint": str(checkpoint),
        "elapsed_seconds": result.elapsed_seconds,
        "network_access": True,
        "model_calls": 0,
    }
