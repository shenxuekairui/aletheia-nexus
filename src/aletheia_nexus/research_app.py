"""Local application boundary shared by the natural-language CLI and MCP.

This module orchestrates existing services; scientific extraction stays in run_task.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from threading import Lock
from uuid import uuid4

from pypdf import PdfReader

from aletheia_nexus.content.errors import ParserInputError
from aletheia_nexus.content.gate import (
    ACQUISITION_SCHEMAS,
    sha256_file,
    validate_parser_input,
)
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.parser import ParserConfig
from aletheia_nexus.content.service import parse_document
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.processing.contracts import digest, validate_task
from aletheia_nexus.processing.engine import run_task, write_json
from aletheia_nexus.processing.materials import load_source
from aletheia_nexus.processing.native_table import (
    NATIVE_TABLE_VERSION,
    NativeTableLimitError,
    native_table_notes,
    read_native_xlsx,
)
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.readings import readings_identity
from aletheia_nexus.processing.results import (
    export_results,
    revise_result,
    verify_result,
)

NATIVE_TABLE_LIMITS = {
    "max_cells": 10000,
    "max_uncompressed_bytes": 64 * 1024 * 1024,
    "max_chars": 200000,
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _parsed_candidates(pdf: Path) -> list[Path]:
    # Preserve the old preparation filename while making new artifacts discoverable
    # by the v0.7 corpus reader (which searches for *.parsed.json).
    return list(
        dict.fromkeys(
            [
                pdf.with_suffix(".parsed.json"),
                *sorted(pdf.parent.glob("*.parsed.json")),
                *sorted(pdf.parent.glob("parsed-*.json")),
            ]
        )
    )


def _lock_job_owner(path: Path, *, create=False):
    """Keep job ownership visible across CLI/MCP processes, including crashes."""
    handle = path.open("a+b" if create else "r+b")
    if create and handle.seek(0, 2) == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


class ResearchApplication:
    """Explicit read roots, one output workspace, and no implicit remote permission.

    Grants are minted only by the local CLI, never by an MCP tool. Their directory
    cannot be read or written through application paths, even inside the workspace.
    The OS user/host that launches the server is trusted; arbitrary MCP arguments
    are not. This is not a sandbox against other programs running as that OS user.
    """

    def __init__(
        self,
        roots: list[str | Path],
        workspace: str | Path,
        *,
        remote=False,
        network=False,
    ):
        self.roots = tuple(Path(p).resolve(strict=True) for p in roots)
        if not self.roots or any(not p.is_dir() for p in self.roots):
            raise ValueError("at least one existing document directory is required")
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.private = self.workspace / ".authorizations"
        self.remote = remote
        self.network = network
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="an-research")
        self._jobs: dict = {}
        self._lock = Lock()

    def path(self, path: str | Path, *, write=False) -> Path:
        path = Path(path)
        target = (path if path.is_absolute() else self.workspace / path).resolve()
        if target.is_relative_to(self.private.resolve()):
            raise ProcessingError("authorization_directory_private")
        roots = (self.workspace,) if write else (*self.roots, self.workspace)
        if not any(target.is_relative_to(root) for root in roots):
            raise ProcessingError("path_outside_allowed_directories")
        return target

    def _copy_source_file(self, original: Path, target: Path) -> Path:
        original, target = self.path(original), self.path(target, write=True)
        fingerprint = sha256_file(original)
        if target.exists():
            if sha256_file(target) != fingerprint:
                raise ProcessingError("workspace_source_hash_mismatch")
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (uuid4().hex + ".part")
        try:
            shutil.copyfile(original, temporary)
            if sha256_file(temporary) != fingerprint:
                raise ProcessingError("source_changed_while_copying")
            # The workspace copy is immutable too: a concurrent existing copy must
            # match, never replace a different file.
            with target.open("xb") as output, temporary.open("rb") as source:
                shutil.copyfileobj(source, output)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def import_local_document(
        self, pdf: str, title: str, *, doi: str | None = None
    ) -> dict:
        """Declare a main article locally; never mint a verified identity or SI link."""
        original = self.path(pdf)
        if original.suffix.lower() != ".pdf" or not title.strip():
            raise ValueError("select a PDF and supply its title")
        sidecar = self.path(acquisition_sidecar_path(original))
        if sidecar.exists():
            # Do not replace an acquired/registered identity with model metadata,
            # particularly an independently established supplement relationship.
            raise ProcessingError("source_already_registered_use_prepare_documents")
        destination = self.path(
            self.workspace / "materials" / ("import-" + uuid4().hex), write=True
        )
        copied = self._copy_source_file(original, destination / "paper.pdf")
        registered = register_local_pdf(
            copied, output_dir=destination, title=title, doi=doi
        )
        document = {
            "id": "paper_" + sha256_file(registered)[:16],
            "pdf": str(registered),
            "sidecar": str(acquisition_sidecar_path(registered)),
        }
        source = self.check_document(document, "direct")
        receipt = {
            "document": document,
            "source": source.identity,
            "original_pdf": str(original),
            "original_filename": original.name,
            "status": "REGISTERED",
            "warnings": [
                "标题和DOI由调用者声明，未经来源验证；仅登记为独立主文，不绑定SI。"
            ],
            "network_access": False,
        }
        path = self.path(destination / "import.json", write=True)
        write_json(path, receipt)
        return {**receipt, "import_file": str(path)}

    def parse_document(
        self, document: dict, *, ocr=False, ocr_languages="eng", max_pages=2000
    ) -> dict:
        """Explicitly create a new parse; old native/OCR artifacts stay untouched."""
        config = ParserConfig(max_pages=max_pages)
        if type(ocr) is not bool or not re.fullmatch(
            r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", ocr_languages
        ):
            raise ValueError("invalid local OCR options")
        source = self.check_document(document, "direct")
        destination = self.path(
            self.workspace / "materials" / source.identity["pdf_sha256"], write=True
        )
        pdf = self._copy_source_file(source.pdf, destination / "paper.pdf")
        # Distinct declarations of the same bytes may have different identities.
        # Keep every source record, and bind its exact copy in the new artifact.
        sidecar = self._copy_source_file(
            source.sidecar,
            destination
            / "json"
            / (source.identity["acquisition_sidecar_sha256"] + ".acquisition.json"),
        )
        backend = None
        if ocr:
            from aletheia_nexus.content.backends import (
                AdaptiveOcrBackend,
                TesseractOcrBackend,
                TesseractOcrConfig,
            )

            backend = AdaptiveOcrBackend(
                ocr_backends=(
                    TesseractOcrBackend(TesseractOcrConfig(languages=ocr_languages)),
                )
            )
        artifact = self.path(
            destination / ("parsed-" + uuid4().hex + ".parsed.json"), write=True
        )
        result = parse_document(
            pdf,
            sidecar_path=sidecar,
            output_path=artifact,
            config=config,
            backend=backend,
        )
        source.verify()
        updated = {
            **deepcopy(document),
            "pdf": str(pdf),
            "sidecar": str(sidecar),
            "artifact": str(artifact),
        }
        return {
            "document": updated,
            "status": result.status,
            "parser": result.document["parser"],
            "quality": result.document["quality"],
            "warnings": result.document["warnings"],
            "errors": result.document["errors"],
            "options": {
                "ocr": ocr,
                "ocr_languages": ocr_languages,
                "max_pages": max_pages,
            },
            "original_pdf": str(source.pdf),
            "original_filename": source.pdf.name,
            "previous_artifact": document.get("artifact"),
            "network_access": False,
        }

    def list_documents(self, directory: str, *, recursive=False) -> dict:
        root = self.path(directory)
        if not root.is_dir():
            raise ValueError("document directory does not exist")
        files = root.rglob("*") if recursive else root.iterdir()
        rows = []
        for candidate in sorted(files):
            if candidate.suffix.lower() != ".pdf":
                continue
            row = {"path": str(candidate), "warnings": []}
            try:
                pdf = self.path(candidate)
                reader = PdfReader(pdf, strict=False)
                if reader.is_encrypted and not reader.decrypt(""):
                    raise ValueError("encrypted_pdf")
                row.update(pages=len(reader.pages), sha256=sha256_file(pdf))
                row["title"] = str((reader.metadata or {}).get("/Title") or pdf.stem)
                row["status"] = "UNREGISTERED"
                row["role"] = "UNCONFIRMED"
                sidecar = acquisition_sidecar_path(pdf)
                if sidecar.exists():
                    self.path(sidecar)
                    source = validate_parser_input(pdf, sidecar_path=sidecar)
                    row.update(
                        title=source.title,
                        doi=source.doi,
                        role=source.document_role,
                        identity_basis=source.identity_basis,
                        status="SOURCE_AVAILABLE",
                    )
                else:
                    row["warnings"].append(
                        "标题/DOI/文献角色尚未核实；不会自动绑定SI。"
                    )
                row["parsed_artifact"] = None
                row["parsed_artifacts"] = []
                for parsed in _parsed_candidates(pdf):
                    if not parsed.is_file():
                        continue
                    try:
                        parsed_source = self.check_document(
                            {"id": "check", "pdf": str(pdf), "artifact": str(parsed)},
                            "parsed",
                        )
                    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                        continue
                    row["parsed_artifacts"].append(str(parsed))
                    if row["status"] == "UNREGISTERED":
                        row.update(
                            title=parsed_source.identity["title"],
                            doi=parsed_source.identity["doi"],
                            role=parsed_source.identity["document_role"],
                            identity_basis=parsed_source.identity["identity_basis"],
                            status="SOURCE_AVAILABLE",
                        )
                        row["warnings"] = []
                if row["parsed_artifacts"]:
                    row["parsed_artifact"] = row["parsed_artifacts"][0]
            except Exception as exc:
                row.update(status="UNAVAILABLE", error=self.error_code(exc))
            rows.append(row)
        return {
            "directory": str(root),
            "documents": rows,
            "network_access": False,
            "new_files": False,
        }

    @staticmethod
    def error_code(exc: Exception) -> str:
        return exc.code if isinstance(exc, ProcessingError) else type(exc).__name__

    def get_acquisition_status(
        self,
        sidecar: str,
        *,
        pdf: str | None = None,
        expected_doi: str | None = None,
    ) -> dict:
        """Read a saved acquisition outcome and optionally recheck selected bytes.

        Record paths/URLs are never followed. A past VERIFIED outcome is not a
        current integrity check, and a local declaration is not verified identity.
        """
        record_path = self.path(sidecar)
        pdf_path = self.path(pdf) if pdf is not None else None
        if expected_doi is not None and pdf_path is None:
            raise ValueError("expected_doi requires an explicitly selected PDF")
        record = read_json(record_path)
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("schema"), str)
            or record["schema"] not in ACQUISITION_SCHEMAS
        ):
            raise ProcessingError("unsupported_acquisition_record")
        target = record.get("target") or {}
        identity = record.get("identity_validation") or {}
        validation = record.get("pdf_validation") or {}
        retrieval = record.get("retrieval") or {}
        report = {
            "sidecar": str(record_path),
            "schema": record["schema"],
            "recorded_status": record.get("status"),
            "target": {
                key: target.get(key)
                for key in ("doi", "title", "expected_title", "article_id")
            },
            "recorded_identity_status": identity.get("status"),
            "recorded_document_role": identity.get("document_role"),
            "recorded_valid_pdf": validation.get("valid_pdf"),
            "recorded_page_count": validation.get("page_count"),
            "recorded_pdf_sha256": retrieval.get("sha256"),
            "attempts": record.get("attempts"),
            "elapsed_seconds": record.get("elapsed_seconds"),
            "current_check": {"status": "NOT_CHECKED", "reason": "pdf_not_supplied"},
            "network_access": False,
            "new_files": False,
        }
        if pdf_path is not None:
            try:
                source = validate_parser_input(
                    pdf_path, requested_doi=expected_doi, sidecar_path=record_path
                )
            except ParserInputError as exc:
                report["current_check"] = {"status": "FAILED", "error": exc.code.value}
            except OSError as exc:
                report["current_check"] = {
                    "status": "FAILED",
                    "error": type(exc).__name__,
                }
            else:
                report["current_check"] = {
                    "status": "PASSED",
                    "pdf": str(source.pdf_path),
                    "pdf_sha256": source.pdf_sha256,
                    "sidecar_sha256": source.sidecar_sha256,
                    "page_count": source.page_count,
                    "doi": source.doi,
                    "document_role": source.document_role,
                    "identity_basis": source.identity_basis,
                    "identity_verified": source.identity_basis
                    == "acquisition_verified",
                }
        return report

    def check_document(self, config: dict, mode: str):
        """Check explicit paths AND parsed-artifact locators before loading sources."""
        config = deepcopy(config)
        for key in ("artifact", "pdf", "sidecar"):
            if config.get(key):
                config[key] = str(self.path(config[key]))
        locators = {}
        if config.get("artifact") and not (mode == "direct" and config.get("pdf")):
            artifact_path = self.path(config["artifact"])
            artifact = read_json(artifact_path)
            locators = artifact.get("source", {}).get("locators", {})
            for locator in locators.values():
                self.path(artifact_path.parent / locator)
            for key, locator in (("pdf", "pdf"), ("sidecar", "acquisition_sidecar")):
                if not config.get(key) and locators.get(locator):
                    config[key] = str(
                        self.path(artifact_path.parent / locators[locator])
                    )
        if config.get("pdf") and not config.get("sidecar"):
            config["sidecar"] = str(self.path(acquisition_sidecar_path(config["pdf"])))
        source = load_source(config, self.workspace, mode)
        for path in (source.pdf, source.sidecar):
            self.path(path)
        return source

    def _preparation_paths(self, paths: list[str]) -> list[Path]:
        if not paths:
            raise ValueError("select unique PDF paths")
        selected = [self.path(p) for p in paths]
        if len(selected) != len(set(selected)):
            raise ValueError("select unique PDF paths")
        for original in selected:
            self.path(acquisition_sidecar_path(original))
        return selected

    def prepare_documents(self, paths: list[str], *, progress=None) -> dict:
        """Prepare only selected PDFs, preserving existing trusted source records.

        Unregistered files are declared as individual articles with explicit identity
        uncertainty. A new SI relationship is never inferred from filenames/model input.
        Use the existing local import command to declare a supplement and its parent.
        """
        documents, failures, warnings = [], [], []
        # Validate every selected boundary before writing anything.
        selected = self._preparation_paths(paths)
        for index, original in enumerate(selected, 1):
            item = {"path": str(original), "completed": index, "total": len(selected)}
            try:
                if original.suffix.lower() != ".pdf":
                    raise ValueError("PDF required")
                fingerprint = sha256_file(original)
                destination = self.path(
                    self.workspace / "materials" / fingerprint, write=True
                )
                destination.mkdir(parents=True, exist_ok=True)
                # Poppler on Windows may reject long PDF paths even though Python
                # can parse them. Preserve the original name in metadata, and use
                # a short content-addressed workspace copy for native page reading.
                pdf = self.path(destination / "paper.pdf", write=True)
                if not pdf.exists():
                    temporary = destination / (uuid4().hex + ".part")
                    try:
                        shutil.copyfile(original, temporary)
                        if sha256_file(temporary) != fingerprint:
                            raise ProcessingError("source_changed_while_copying")
                        os.replace(temporary, pdf)
                    finally:
                        temporary.unlink(missing_ok=True)
                if sha256_file(pdf) != fingerprint:
                    raise ProcessingError("workspace_pdf_hash_mismatch")
                sidecar = acquisition_sidecar_path(original)
                notes = []
                if sidecar.exists():
                    self.path(sidecar)
                    validate_parser_input(original, sidecar_path=sidecar)
                    sidecar = self._copy_source_file(
                        sidecar, destination / "json" / "paper.acquisition.json"
                    )
                else:
                    notes = [
                        "本地文件，标题采用文件名；DOI和文献角色未经核实。"
                        "按独立主文登记，不代表已确认其角色；可能的SI未绑定。"
                    ]
                    pdf = register_local_pdf(
                        pdf, output_dir=destination, title=original.stem
                    )
                    sidecar = acquisition_sidecar_path(pdf)
                config = {
                    "id": "paper_" + fingerprint[:16],
                    "pdf": str(pdf),
                    "sidecar": str(sidecar),
                    "notes": notes,
                }
                candidates = [
                    original.with_suffix(".parsed.json"),
                    *_parsed_candidates(pdf),
                ]
                artifact = None
                for candidate in candidates:
                    if not candidate.is_file():
                        continue
                    try:
                        self.check_document(
                            {**config, "artifact": str(candidate)}, "parsed"
                        )
                    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                        continue
                    artifact = candidate
                    break
                reused = artifact is not None
                if artifact is None:
                    artifact = destination / ("parsed-" + uuid4().hex + ".parsed.json")
                    parse_document(pdf, sidecar_path=sidecar, output_path=artifact)
                config["artifact"] = str(artifact)
                source = self.check_document(config, "parsed")
                documents.append(config)
                warnings.extend(notes)
                item.update(
                    status="PREPARED",
                    document=deepcopy(config),
                    reused=reused,
                    parse_status=source.artifact.document["status"],
                )
            except Exception as exc:
                failure = {"path": str(original), "error": self.error_code(exc)}
                failures.append(failure)
                item.update(status="FAILED", error=failure["error"])
            if progress is not None:
                progress(item)
        receipt = {
            "schema": "aletheia-nexus/document-preparation/v1",
            "documents": documents,
            "failures": failures,
            "warnings": warnings,
            "network_access": False,
            "workspace": str(self.workspace),
        }
        path = self.workspace / "preparations" / (uuid4().hex + ".json")
        write_json(self.path(path, write=True), receipt)
        return {**receipt, "preparation_file": str(path)}

    def prepare_documents_job(self, paths: list[str], *, background=True) -> dict:
        """Prepare selected PDFs through the existing local workflow and job owner.

        Repeating the same selection starts a new history entry and reuses valid
        parses. It does not replace or silently resume the previous job.
        """
        selected = [str(p) for p in self._preparation_paths(paths)]
        job_id = uuid4().hex
        directory = self.path(self.workspace / "jobs" / job_id, write=True)
        write_json(directory / "preparation-request.json", {"paths": selected})
        receipt = {
            "job_id": job_id,
            "kind": "preparation",
            "status": "QUEUED",
            "directory": str(directory),
            "error": None,
            "completed": 0,
            "total": len(selected),
            "items": [],
            "model_calls": 0,
            "network_access": False,
        }

        def progress(row):
            receipt["items"].append(deepcopy(row))
            receipt["completed"] = row["completed"]
            self._progress(receipt, row)

        def execute():
            receipt["status"] = "RUNNING"
            self._save_job(receipt)
            try:
                prepared = self.prepare_documents(selected, progress=progress)
                receipt.update(prepared)
                partial = prepared["failures"] or any(
                    item.get("parse_status") == "PARTIAL" for item in receipt["items"]
                )
                receipt["status"] = (
                    "FAILED"
                    if not prepared["documents"]
                    else "PARTIAL"
                    if partial
                    else "COMPLETED"
                )
            except Exception as exc:
                receipt.update(status="FAILED", error=self.error_code(exc))
            self._save_job(receipt)
            return deepcopy(receipt)

        return self._start_job(receipt, execute, background=background)

    def validate_research_task(self, payload: dict) -> dict:
        task = validate_task(payload)
        sources = [self.check_document(d, task["mode"]) for d in task["documents"]]
        return {
            "task": task,
            "task_fingerprint": digest(task),
            "documents": [
                {
                    "id": s.config["id"],
                    **s.identity,
                    "parsed_artifact_id": s.artifact.document["artifact_id"]
                    if s.artifact
                    else None,
                }
                for s in sources
            ],
            "plan": self.plan(task, sources),
            "remote_enabled": self.remote,
        }

    @staticmethod
    def plan(task: dict, sources: list) -> str:
        lines = [f"研究目标：{task['objective']}", "文献："]
        for index, source in enumerate(sources):
            lines.append(
                f"  {source.config['id']} · {source.identity['title']} "
                f"({source.identity['document_role']})"
            )
            notes = source.config.get("notes", [])
            visible_chars = hidden_count = hidden_chars = 0
            for note in notes:
                if len(note) <= 400 and visible_chars + len(note) <= 1000:
                    lines.append("  注意：" + note)
                    visible_chars += len(note)
                else:
                    hidden_count += 1
                    hidden_chars += len(note)
            if hidden_count:
                lines.append(
                    f"  补充材料/备注：另有{hidden_count}条，共{hidden_chars}字符，计划不展开。"
                    f"完整内容见保存任务的 documents[{index}].notes；"
                    "自然语言入口会显示任务文件路径，MCP校验返回的task也包含全文。"
                )
            if notes:
                lines.append(
                    "  备注/补充材料全文将在确认后随所选文献发送给模型（含未展开部分）。"
                    if task["mode"] != "local"
                    else "  备注/补充材料全文保留在任务与本地材料中；本地模式不发送给远程模型。"
                )
        lines.append("提取信息：")
        lines.extend(
            f"  {f.get('label', f['id'])}：{f['description']}" for f in task["fields"]
        )
        lines += [
            f"实验步骤：{'是' if task.get('include_steps') else '否'}；"
            f"跨文献比较：{'是' if task['synthesize'] else '否'}",
            f"模式：{task['mode']}；原页图片："
            + str({d["id"]: d.get("image_pages", []) for d in task["documents"]}),
            "SI只使用上述已关联来源；额外SI不会自动下载或绑定。",
            "模型：" + task.get("model", {}).get("name", "本地，无模型"),
            "提取策略："
            + (
                "每篇1次首读，按原字段分配保留读法笔记，不作第二次科学改写；"
                "每篇仅一条笔记记录，读法与关系未经科学确认。"
                + ("另有原引擎跨篇综合调用及费用。" if task["synthesize"] else "")
                if task.get("source_assembly") == "preserve_readings"
                and task["mode"] != "local"
                else "先读原文证据，再组装字段；每份材料至少2次模型调用，"
                "补材料会再执行两阶段；共用下列调用及费用上限，不自动加预算。"
                if task.get("extraction_strategy") == "source_first"
                and task["mode"] != "local"
                else "直接提取（本地模式不调用模型）。"
            ),
            f"上限：{task['budget']['max_calls']} 次HTTP；"
            f"{task['budget'].get('max_cost', '未设置')} "
            + task.get("model", {}).get("currency", "CNY"),
            "输出："
            + ", ".join(task.get("export_formats", ["markdown", "csv", "jsonl"])),
            "定位不等于科学支持；AI结果不会标为人工确认。",
        ]
        if task.get("material_presentation") == "compact":
            lines.append("材料呈现：精简（compact）；按当前材料范围和预算执行。")
        if task.get("source_assembly") == "preserve_readings":
            lines.append(
                "交付形式：每篇一条原读法笔记；字段未获条目不等于原文未报告。"
                "不生成多阶段实验记录或人工确认；本地模式仅准备材料，不执行首读。"
            )
        return "\n".join(lines)

    def binding(self, scope: str, payload: dict) -> str:
        if scope == "execute":
            validated = self.validate_research_task(payload)
            payload = {
                "task": validated["task"],
                "sources": validated["documents"],
                **readings_identity(validated["task"]),
            }
        elif scope == "acquire":
            from .research_acquisition import public_acquisition_plan

            payload = public_acquisition_plan(self, payload)["binding"]
        elif scope != "plan":
            raise ValueError("unknown authorization scope")
        return digest(
            {
                "scope": scope,
                "payload": payload,
                "roots": [str(p) for p in self.roots],
                "workspace": str(self.workspace),
            }
        )

    def authorization_request(self, scope: str, payload: dict) -> dict:
        """Save a reviewable challenge, not permission to call an API."""
        binding = self.binding(scope, payload)
        request = {
            "schema": "aletheia-nexus/local-authorization-request/v1",
            "scope": scope,
            "payload": payload,
            "binding": binding,
            "roots": [str(p) for p in self.roots],
            "workspace": str(self.workspace),
        }
        path = self.path(self.workspace / "requests" / (binding + ".json"), write=True)
        if not path.exists():
            write_json(path, request)
        return {
            "authorization_request": str(path),
            "instruction": "在本机终端运行 research authorize 并核对计划；MCP参数不能代替批准。",
        }

    def authorize(self, scope: str, payload: dict, *, lifetime_seconds=3600) -> str:
        """Trusted local CLI only. No corresponding MCP method is exposed."""
        binding = self.binding(scope, payload)
        token = secrets.token_hex(32)
        self.private.mkdir(parents=True, exist_ok=True)
        write_json(
            self.private / (digest(token) + ".json"),
            {"binding": binding, "expires": time.time() + lifetime_seconds},
        )
        return token

    def consume(self, token: str | None, scope: str, payload: dict) -> None:
        if scope == "acquire" and not self.network:
            raise ProcessingError("network_disabled")
        if scope != "acquire" and not self.remote:
            raise ProcessingError("remote_disabled")
        if not isinstance(token, str) or not re.fullmatch("[0-9a-f]{64}", token):
            raise ProcessingError("local_authorization_required")
        path = self.private / (digest(token) + ".json")
        binding = self.binding(scope, payload)
        try:
            record = read_json(path)
            if record["binding"] != binding or record["expires"] <= time.time():
                raise ProcessingError("authorization_expired_or_changed")
            # Atomic one-use claim; another process cannot consume the same grant.
            os.rename(path, path.with_suffix(".used"))
        except FileNotFoundError:
            raise ProcessingError("authorization_missing_or_used") from None

    def execute_research_task(
        self, payload: dict, *, authorization=None, background=True, provider=None
    ) -> dict:
        checked = self.validate_research_task(payload)
        task = checked["task"]
        if task["mode"] != "local":
            if not task["allow_remote"] or "max_cost" not in task["budget"]:
                raise ProcessingError("remote_requires_task_permission_and_cost_limit")
            self.consume(authorization, "execute", task)
        approved_binding = self.binding("execute", task)
        job_id = uuid4().hex
        directory = self.path(self.workspace / "jobs" / job_id, write=True)
        write_json(directory / "task.json", task)
        receipt = {
            "job_id": job_id,
            "status": "QUEUED",
            "task_fingerprint": digest(task),
            "directory": str(directory),
            "error": None,
        }

        def execute():
            receipt["status"] = "RUNNING"
            self._save_job(receipt)
            try:
                if self.binding("execute", task) != approved_binding:
                    raise ProcessingError("source_changed_after_authorization")
                manifest = run_task(
                    task,
                    base_dir=self.workspace,
                    output_dir=self.workspace / "research",
                    allow_remote=task["mode"] != "local",
                    provider=provider,
                    progress=lambda row: self._progress(receipt, row),
                )
                receipt.update(
                    status=manifest["status"],
                    run_directory=manifest["run_directory"],
                    usage=manifest["usage"],
                    outputs=manifest["outputs"],
                )
            except Exception as exc:
                receipt.update(status="FAILED", error=self.error_code(exc))
            self._save_job(receipt)
            return deepcopy(receipt)

        return self._start_job(receipt, execute, background=background)

    def acquire_documents(
        self, payload: dict, *, authorization=None, background=True
    ) -> dict:
        """Explicitly authorized public DOI batch, using existing acquisition/checkpoint services."""
        from .research_acquisition import (
            acquire_public_documents,
            public_acquisition_plan,
        )

        if not self.network:
            raise ProcessingError("network_disabled")
        plan = public_acquisition_plan(self, payload)
        payload = plan["payload"]
        if authorization is None:
            return {
                "status": "AUTHORIZATION_REQUIRED",
                "plan": plan["plan"],
                "network_access": False,
                **self.authorization_request("acquire", payload),
            }
        self.consume(authorization, "acquire", payload)
        job_id = uuid4().hex
        directory = self.path(self.workspace / "jobs" / job_id, write=True)
        write_json(directory / "acquisition-request.json", payload)
        receipt = {
            "job_id": job_id,
            "kind": "acquisition",
            "status": "QUEUED",
            "directory": str(directory),
            "error": None,
            "model_calls": 0,
            "resume_of": payload.get("resume_job_id"),
        }

        def progress(row):
            receipt.update(row)
            self._save_job(receipt)

        def execute():
            receipt["status"] = "RUNNING"
            self._save_job(receipt)
            try:
                receipt.update(
                    acquire_public_documents(self, plan, directory, progress)
                )
            except Exception as exc:
                receipt.update(status="FAILED", error=self.error_code(exc))
            self._save_job(receipt)
            return deepcopy(receipt)

        return self._start_job(receipt, execute, background=background)

    def _start_job(self, receipt: dict, execute, *, background: bool) -> dict:
        """Use one process-ownership and status mechanism for both application jobs."""
        self._save_job(receipt)
        owner = _lock_job_owner(
            self.path(Path(receipt["directory"]) / ".owner", write=True), create=True
        )
        if owner is None:
            receipt.update(status="FAILED", error="job_owner_unavailable")
            self._save_job(receipt)
            raise ProcessingError("job_owner_unavailable")

        def owned_execute():
            try:
                return execute()
            finally:
                owner.close()

        if not background:
            return owned_execute()
        try:
            with self._lock:
                self._jobs[receipt["job_id"]] = self._pool.submit(owned_execute)
        except RuntimeError:
            owner.close()
            raise
        return deepcopy(receipt)

    def _save_job(self, receipt):
        path = self.path(
            self.workspace / "jobs" / receipt["job_id"] / "status.json", write=True
        )
        write_json(path, receipt, overwrite=True)

    def _progress(self, receipt, row):
        receipt["latest_document"] = row
        self._save_job(receipt)

    def get_run_status(self, job_id: str, *, include_manifest=True) -> dict:
        if not re.fullmatch("[0-9a-f]{32}", job_id):
            raise ValueError("invalid job ID")
        status_path = self.path(self.workspace / "jobs" / job_id / "status.json")
        receipt = read_json(status_path)
        if receipt["status"] in {"QUEUED", "RUNNING"}:
            ownership = self.path(self.workspace / "jobs" / job_id / ".owner")
            if ownership.exists():
                probe = _lock_job_owner(ownership)
                if probe is not None:
                    try:
                        # A worker can save its final state and release the lock
                        # after our first read. Only the fresh state can show an
                        # interruption once ownership is available.
                        receipt = read_json(status_path)
                    finally:
                        probe.close()
                    if receipt["status"] in {"QUEUED", "RUNNING"}:
                        receipt["status"] = "INTERRUPTED"
                        receipt["recovery"] = (
                            "原进程已退出，不自动重发；检查原清单后经新授权恢复。"
                        )
            elif job_id not in self._jobs:
                receipt["owner_state"] = "legacy_unrecorded; process ownership unknown"
        if include_manifest and receipt.get("run_directory"):
            run = self.path(receipt["run_directory"])
            receipt["manifest"] = read_json(self.path(run / "manifest.json"))
        return receipt

    def export_research_results(
        self, results: list[str], name: str, formats: list[str] | None = None
    ) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("export name must be a simple identifier")
        values = [read_json(self.path(p)) for p in results]
        if not values:
            raise ValueError("select results")
        for value in values:
            for document in value.get("package", {}).get("documents", []):
                for locator in document.get("locators", {}).values():
                    if locator is not None:
                        self.path(locator)
            verify_result(value)
        task = deepcopy(values[0]["task"])
        keys = ("type", "objective", "fields", "rules")
        if any(any(v["task"].get(k) != task.get(k) for k in keys) for v in values):
            raise ValueError("incompatible research questions or fields")
        if formats:
            task["export_formats"] = formats
        directory = self.path(
            self.workspace / "exports" / (name + "-" + uuid4().hex[:8]), write=True
        )
        outputs = export_results(values, task, directory)
        return {
            "directory": str(directory),
            "outputs": outputs,
            "network_access": False,
        }

    def close(self):
        self._pool.shutdown(wait=True)

    def _document_corpus(self, document: dict):
        """Adapt explicitly selected, source-checked documents to v0.7 readers.

        Constructing a Corpus does not scan its root. Only this selected entry is
        supplied, so a common ancestor never widens filesystem authorization.
        """
        from aletheia_nexus.content.corpus import Corpus, CorpusDocument

        source = self.check_document(document, "parsed")
        try:
            root = Path(
                os.path.commonpath([source.pdf.parent, source.artifact.path.parent])
            )
        except ValueError:
            raise ProcessingError(
                "cross_volume_corpus_requires_local_preparation"
            ) from None
        entry = CorpusDocument(
            source.artifact.path, source.pdf, source.artifact, source.artifact.document
        )
        return source, Corpus(root, [entry], [], [])

    def search_documents(
        self, documents: list[dict], query: str, *, limit=10, mode="and"
    ) -> dict:
        """Reuse native table/figure-aware search; never turn no match into absence."""
        from aletheia_nexus.content.corpus import search_corpus

        if not documents or not 1 <= limit <= 50:
            raise ValueError("select documents and a limit between1and50")
        hits, coverage, failures = [], [], []
        for document in documents:
            try:
                source, corpus = self._document_corpus(document)
                report = search_corpus(corpus, query, limit=limit, mode=mode)
                source.verify()
                hits.extend(
                    {
                        **hit,
                        "document_id": document["id"],
                        "artifact": str(source.artifact.path),
                        "pdf": str(source.pdf),
                    }
                    for hit in report["hits"]
                )
                coverage.append(
                    {"document_id": document["id"], "coverage": report["coverage"]}
                )
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                failures.append(
                    {"document_id": document.get("id"), "error": self.error_code(exc)}
                )
        hits.sort(
            key=lambda h: (
                h.get("reading_role") == "alternative",
                -h["score"],
                h["document_id"],
                h["id"],
            )
        )
        return {
            "query": query,
            "hits": [{**h, "number": n} for n, h in enumerate(hits[:limit], 1)],
            "coverage": coverage,
            "unsearched": failures,
            "network_access": False,
            "interpretation": "字面检索；未命中不代表原文没有报告。可继续读取完整上下文与原页。",
        }

    def read_native_table(self, path: str, sheets: list[str] | None = None) -> dict:
        """Read selected native XLSX cells locally; never assert an SI identity."""
        source = self.path(path)
        if source.suffix.lower() != ".xlsx":
            raise ProcessingError("native_table_format_unsupported")
        try:
            view = read_native_xlsx(
                source,
                sheets=sheets,
                max_cells=NATIVE_TABLE_LIMITS["max_cells"],
                max_uncompressed_bytes=NATIVE_TABLE_LIMITS["max_uncompressed_bytes"],
            )
            notes = native_table_notes(view, max_chars=NATIVE_TABLE_LIMITS["max_chars"])
        except ValueError as exc:
            failure = {
                "ok": False,
                "error": "native_table_resource_limit"
                if isinstance(exc, NativeTableLimitError)
                else "invalid_native_table",
                "detail": str(exc),
                "limits": dict(NATIVE_TABLE_LIMITS),
                "network_access": False,
                "new_files": False,
            }
            if isinstance(exc, NativeTableLimitError) and exc.available_sheets:
                failure["available_sheets"] = exc.available_sheets
            return failure
        if sha256_file(source) != view["source_workbook_sha256"]:
            raise ProcessingError("native_table_source_changed")
        return {
            "ok": True,
            "source": {
                "path": str(source),
                "sha256": view["source_workbook_sha256"],
                "format": "xlsx",
                "identity_verified": False,
                "parent_document_assigned": False,
            },
            "reader_version": NATIVE_TABLE_VERSION,
            "sheet_count": len(view["sheets"]),
            "cell_count": view["populated_cells"],
            "selected_sheets": [
                {"name": s["sheet"], "cells": s["populated_cells"], "state": s["state"]}
                for s in view["sheets"]
            ],
            "unselected_sheets": view["unselected_sheets"],
            "table_notes": notes,
            "complete_selected_sheet_cell_view": True,
            "limits": dict(NATIVE_TABLE_LIMITS),
            "scope": [
                "完整返回选定工作表的原始单元格坐标和值；不是图表或版面视觉理解。",
                "公式仅保留原式、声明和已有缓存，不重算，也不证明缓存或科学内容正确。",
                "此工具不核验来源身份或自动绑定主文/SI；确认关系后可将table_notes追加到document.notes数组。",
                "原始rPr/XML保留在本地原工作簿；返回投影只含必要文字和上/下标等语义属性。",
                "内容会返回MCP客户端，其模型和隐私设置由客户端管理；AN不调用模型或网络。",
            ],
            "warnings": view["warnings"],
            "network_access": False,
            "new_files": False,
        }

    def read_document_context(
        self,
        document: dict,
        *,
        pages: list[int] | None = None,
        block_ids: list[str] | None = None,
        context_pages=1,
        max_characters=60000,
    ) -> dict:
        """Keep complete native page context, tables, captions and source locations."""
        from aletheia_nexus.content.evidence import build_evidence_pack

        if not 0 <= context_pages <= 3 or not 1 <= max_characters <= 500000:
            raise ValueError("context/resource limit out of range")
        source, corpus = self._document_corpus(document)
        wanted = set(pages or [])
        wanted.update(source.artifact.locate(bid)["page"] for bid in block_ids or [])
        if not wanted or any(
            type(p) is not int or not 1 <= p <= source.identity["page_count"]
            for p in wanted
        ):
            raise ValueError("select existing pages or block IDs")
        expanded = sorted(
            {
                p
                for page in wanted
                for p in range(
                    max(1, page - context_pages),
                    min(source.identity["page_count"], page + context_pages) + 1,
                )
            }
        )
        pack = build_evidence_pack(
            corpus,
            document_pages={source.artifact.document["artifact_id"]: expanded},
            context_pages=0,
            max_characters=max_characters,
        )
        source.verify()
        return {
            "document_id": document["id"],
            "artifact": str(source.artifact.path),
            "pdf": str(source.pdf),
            "source_root": str(corpus.root),
            "evidence": pack,
            "network_access": False,
        }

    def get_parse_diagnostics(self, document: dict) -> dict:
        from aletheia_nexus.content.artifact import ParsedArtifact
        from aletheia_nexus.content.parser import PARSER_VERSION

        artifact = ParsedArtifact.load(self.path(document["artifact"]))
        data = artifact.document
        try:
            self.check_document(document, "parsed").verify()
            source_check = {"ok": True}
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            source_check = {"ok": False, "error": self.error_code(exc)}
        return {
            "artifact_id": data["artifact_id"],
            "status": data["status"],
            "parser": data["parser"],
            "current_parser_version": PARSER_VERSION,
            "quality": data["quality"],
            "warnings": data["warnings"],
            "errors": data["errors"],
            "source_check": source_check,
            "network_access": False,
        }

    def read_original_page(
        self, document: dict, page: int, *, region: list[float] | None = None
    ) -> tuple[dict, bytes]:
        from aletheia_nexus.processing.materials import render_page, render_page_region

        source = self.check_document(document, "direct")
        if type(page) is not int or not 1 <= page <= source.identity["page_count"]:
            raise ProcessingError("page_out_of_bounds")
        view = (
            render_page_region(source.pdf, page, region) if region is not None else None
        )
        png = view["bytes"] if view else render_page(source.pdf, page)
        source.verify()
        metadata = {
            "document_id": document["id"],
            "page": page,
            "source": source.identity,
            "reading": "original_page_not_scientifically_verified",
            "network_access": False,
        }
        if view:
            metadata["reading"] = "original_page_region_not_scientifically_verified"
            metadata["source_view"] = {k: v for k, v in view.items() if k != "bytes"}
            metadata["image_sha256"] = hashlib.sha256(png).hexdigest()
            metadata["context"] = (
                "Only the selected region is shown; read the full page when more context is needed."
            )
        return metadata, png

    def read_original_page_text(
        self, document: dict, page: int, max_characters: int = 40000
    ) -> dict:
        """Expose one PDF text layer with layout, separately from canonical parsing."""
        source = self.check_document(document, "direct")
        if type(page) is not int or not 1 <= page <= source.identity["page_count"]:
            raise ProcessingError("page_out_of_bounds")
        if type(max_characters) is not int or not 1 <= max_characters <= 200000:
            raise ValueError("max_characters must be between 1 and 200000")
        with source.pdf.open("rb") as stream:
            text = (
                PdfReader(stream)
                .pages[page - 1]
                .extract_text(extraction_mode="layout", layout_mode_strip_rotated=False)
            )
        source.verify()
        delivered = text[:max_characters]
        extraction = {"engine": "pypdf", "version": version("pypdf"), "mode": "layout"}
        text_sha = hashlib.sha256(delivered.encode("utf-8")).hexdigest()
        return {
            "artifact_id": "an:page-native-layout:sha256:"
            + digest(
                {
                    "pdf_sha256": source.identity["pdf_sha256"],
                    "page": page,
                    "extraction": extraction,
                    "text_sha256": text_sha,
                }
            ),
            "document_id": document["id"],
            "page": page,
            "source": source.identity,
            "reading": "derived_native_layout_not_scientifically_verified",
            "extraction": extraction,
            "text": delivered,
            "text_sha256": text_sha,
            "total_characters": len(text),
            "text_truncated": len(delivered) < len(text),
            "has_native_text": bool(text.strip()),
            "limitations": [
                "Text-layer extraction may contain encoding, ordering or layout errors.",
                "Raster images and graph curves are not read; rotated text is best effort.",
                "An empty or incomplete text layer does not establish scientific absence.",
            ],
            "network_access": False,
        }

    def revise_research_result(
        self, result: str, revision: dict, *, client_identity: str
    ) -> dict:
        """Create an assistant-only child using the existing revision contract.

        The transport supplies client_identity for attribution, not permission.
        Neither tool arguments nor a client's advertised name can confirm science.
        """
        targets = {"record_id", "claim_index", "issue_index"} & revision.keys()
        if (
            len(targets) != 1
            or revision.keys() != targets | {"replacement", "reason"}
            or not isinstance(revision["reason"], str)
            or not revision["reason"].strip()
            or not isinstance(client_identity, str)
            or not client_identity.strip()
        ):
            raise ValueError("revision requires one target, replacement and reason")
        parent_path = self.path(result)
        parent = read_json(parent_path)
        # Check all saved source paths before any source verification/export reads.
        for document in parent.get("task", {}).get("documents", []):
            for key in ("pdf", "sidecar", "artifact"):
                if document.get(key):
                    self.path(document[key])
        documents = parent.get("package", {}).get("documents", [])
        for document in documents:
            for locator in document.get("locators", {}).values():
                if locator is not None:
                    self.path(locator)
        verify_result(parent)
        for document in documents:
            config = {"id": document["id"], **document["locators"]}
            config = {key: value for key, value in config.items() if value is not None}
            source = self.check_document(
                config, "parsed" if config.get("artifact") else "direct"
            )
            if any(
                source.identity.get(key) != value
                for key, value in document["source"].items()
            ) or (
                source.artifact is not None
                and source.artifact.document["artifact_id"]
                != document.get("parsed_artifact_id")
            ):
                raise ProcessingError("source_identity_mismatch")
        child = revise_result(
            parent,
            {
                **deepcopy(revision),
                "author": client_identity,
                "at": datetime.now(timezone.utc).isoformat(),
                "authority": "assistant",
                "confirm": False,
            },
        )
        verify_result(child)
        directory = self.path(self.workspace / "revisions" / uuid4().hex, write=True)
        result_path = directory / "result.json"
        write_json(result_path, child)
        outputs = export_results([child], child["task"], directory)
        return {
            "directory": str(directory),
            "result": str(result_path),
            "artifact_id": child["artifact_id"],
            "parent_result_id": parent["artifact_id"],
            "authority": "assistant",
            "confirmed": False,
            "validation": child["validation"],
            "history_length": len(child["history"]),
            "outputs": [str(result_path), *(str(directory / name) for name in outputs)],
            "network_access": False,
        }

    def read_research_result(self, result: str) -> dict:
        value = read_json(self.path(result))
        # Historical records remain readable after PDFs move or leave the
        # allowed roots. Do not dereference any stored source path here.
        # Re-export and actual document reads apply their own path boundary.
        verify_result(value)
        return {
            "artifact_id": value["artifact_id"],
            "task": value["task"],
            "response": value["response"],
            "validation": value["validation"],
            "history": value["history"],
            "provider": value["provider"],
            "sources": [
                {
                    "id": d["id"],
                    "identity": d["source"],
                    "parsed_artifact_id": d["parsed_artifact_id"],
                }
                for d in value["package"]["documents"]
            ],
            "source_byte_verification": "historical; use document source checks for current bytes",
            "network_access": False,
        }

    def list_research_runs(self, *, limit=20, directory: str | None = None) -> dict:
        """Discover known local history layouts without following saved locators."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between1and100")
        selected = self.workspace if directory is None else self.path(directory)
        if not selected.is_dir():
            raise ValueError("history directory must exist")
        roots = list(dict.fromkeys([self.workspace, selected]))
        jobs, unavailable, groups = [], [], {}
        ignored_views = 0

        def local_file(run, value):
            # Manifest filenames are data, never new filesystem authorization.
            if not isinstance(value, str) or Path(value).is_absolute():
                return None
            try:
                path = self.path(run / value)
                return (
                    str(path) if path.is_relative_to(run) and path.is_file() else None
                )
            except (OSError, ValueError, ProcessingError):
                return None

        for candidate in (self.workspace / "jobs").glob("*/status.json"):
            try:
                path = self.path(candidate)
                if not path.is_relative_to(self.workspace):
                    raise ProcessingError("path_outside_allowed_directories")
                receipt = self.get_run_status(path.parent.name, include_manifest=False)
                row = {
                    "kind": receipt.get("kind", "research"),
                    **{
                        k: receipt.get(k)
                        for k in (
                            "job_id",
                            "status",
                            "task_fingerprint",
                            "run_directory",
                            "error",
                            "usage",
                        )
                    },
                    "history_kind": "application_job",
                    "status_file": str(path),
                    "_mtime": path.stat().st_mtime,
                }
                # Only associate this locator with an independently discovered
                # manifest below. Never open a path supplied by the receipt.
                row["run_directory"] = (
                    str(self.path(receipt["run_directory"]))
                    if receipt.get("run_directory")
                    else None
                )
                jobs.append(row)
            except (OSError, ValueError, KeyError, TypeError, ProcessingError) as exc:
                unavailable.append(
                    {"path": str(candidate), "error": self.error_code(exc)}
                )

        patterns = (
            "manifest.json",
            "planning/*/manifest.json",
            "runs/*/manifest.json",
            "research/runs/*/manifest.json",
        )
        candidates = set(
            p for root in roots for pattern in patterns for p in root.glob(pattern)
        )
        for candidate in candidates:
            try:
                path = self.path(candidate)
                if not any(path.is_relative_to(root) for root in roots):
                    raise ProcessingError("path_outside_allowed_directories")
                manifest = read_json(path)
                if manifest.get("schema") != "aletheia-nexus/research-run/v1":
                    raise ValueError("not a research run manifest")
                if manifest.get("view_kind"):
                    ignored_views += 1
                    continue
                run_id, status = manifest["run_id"], manifest["status"]
                if (
                    not isinstance(run_id, str)
                    or not run_id
                    or not isinstance(status, str)
                ):
                    raise ValueError("invalid run identity/status")
                planning = manifest.get("phase") == "task_planning"
                run = path.parent
                result_files = [
                    item.get("result") for item in manifest.get("items", [])
                ]
                if manifest.get("comparison", {}).get("result"):
                    result_files.append(manifest["comparison"]["result"])
                row = {
                    "kind": "planning" if planning else "research",
                    "history_kind": "task_planning" if planning else "research_run",
                    "job_id": None,
                    "run_id": run_id,
                    "status": status,
                    "task_fingerprint": manifest.get("task_fingerprint"),
                    "request_fingerprint": manifest.get("request_fingerprint"),
                    "run_directory": str(run),
                    "manifest_file": str(path),
                    "task_file": local_file(
                        run, manifest.get("task_file", "task.json")
                    ),
                    "request_file": local_file(run, "request.json")
                    if planning
                    else None,
                    "results": list(
                        dict.fromkeys(
                            p for value in result_files if (p := local_file(run, value))
                        )
                    ),
                    "outputs": list(
                        dict.fromkeys(
                            p
                            for value in manifest.get("outputs", [])
                            if (p := local_file(run, value))
                        )
                    ),
                    "usage": manifest.get("usage"),
                    "error": manifest.get("error"),
                    "errors": [
                        {k: item.get(k) for k in ("id", "status", "error")}
                        for item in manifest.get("items", [])
                        if item.get("error")
                    ],
                    "_mtime": path.stat().st_mtime,
                }
                identity = (
                    row["history_kind"],
                    run_id,
                    row["task_fingerprint"] or row["request_fingerprint"],
                )
                groups.setdefault(identity, []).append(row)
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                ProcessingError,
            ) as exc:
                unavailable.append(
                    {"path": str(candidate), "error": self.error_code(exc)}
                )

        rows, consumed_jobs = [], set()
        for copies in groups.values():
            linked = [
                j
                for j in jobs
                if any(j["run_directory"] == c["run_directory"] for c in copies)
            ]
            # Prefer the actual application-owned run over a copied manifest.
            row = max(
                copies,
                key=lambda c: (
                    any(j["run_directory"] == c["run_directory"] for j in linked),
                    bool(c["results"]),
                    bool(c["task_file"]),
                    c["_mtime"],
                ),
            )
            row["manifest_files"] = sorted({c["manifest_file"] for c in copies})
            if linked:
                job = max(linked, key=lambda j: j["_mtime"])
                row.update(
                    {k: job[k] for k in ("kind", "job_id", "status", "status_file")}
                )
                row["history_kind"] = "application_job"
                row["job_ids"] = [j["job_id"] for j in linked]
                row["_mtime"] = max(row["_mtime"], job["_mtime"])
                consumed_jobs.update(j["job_id"] for j in linked)
            rows.append(row)
        rows.extend(j for j in jobs if j["job_id"] not in consumed_jobs)
        rows.sort(key=lambda row: row["_mtime"], reverse=True)
        for row in rows:
            row.pop("_mtime")
        return {
            "runs": rows[:limit],
            "unavailable": unavailable,
            "ignored_views": ignored_views,
            "directories": [str(root) for root in roots],
            "discovery_layouts": ["jobs/*/status.json (workspace only)", *patterns],
            "usage_aggregated": False,
            "network_access": False,
        }
