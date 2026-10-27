"""Local application boundary shared by the natural-language CLI and MCP.

This module orchestrates existing services; scientific extraction stays in run_task.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Lock
from uuid import uuid4

from pypdf import PdfReader

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.service import parse_document
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.processing.contracts import digest, validate_task
from aletheia_nexus.processing.engine import run_task, write_json
from aletheia_nexus.processing.materials import load_source
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import export_results, verify_result


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class ResearchApplication:
    """Explicit read roots, one output workspace, and no implicit remote permission.

    Grants are minted only by the local CLI, never by an MCP tool. Their directory
    cannot be read or written through application paths, even inside the workspace.
    The OS user/host that launches the server is trusted; arbitrary MCP arguments
    are not. This is not a sandbox against other programs running as that OS user.
    """

    def __init__(self, roots: list[str | Path], workspace: str | Path, *, remote=False):
        self.roots = tuple(Path(p).resolve(strict=True) for p in roots)
        if not self.roots or any(not p.is_dir() for p in self.roots):
            raise ValueError("at least one existing document directory is required")
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.private = self.workspace / ".authorizations"
        self.remote = remote
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
                parsed = pdf.with_suffix(".parsed.json")
                row["parsed_artifact"] = None
                if parsed.is_file():
                    self.check_document(
                        {"id": "check", "pdf": str(pdf), "artifact": str(parsed)},
                        "parsed",
                    )
                    row["parsed_artifact"] = str(parsed)
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

    def prepare_documents(self, paths: list[str]) -> dict:
        """Prepare only selected PDFs, preserving existing trusted source records.

        Unregistered files are declared as individual articles with explicit identity
        uncertainty. A new SI relationship is never inferred from filenames/model input.
        Use the existing local import command to declare a supplement and its parent.
        """
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("select unique PDF paths")
        documents, failures, warnings = [], [], []
        # Validate every selected boundary before writing anything.
        selected = [self.path(p) for p in paths]
        for original in selected:
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
                    *sorted(destination.glob("parsed-*.json")),
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
                if artifact is None:
                    artifact = destination / ("parsed-" + uuid4().hex + ".json")
                    parse_document(pdf, sidecar_path=sidecar, output_path=artifact)
                config["artifact"] = str(artifact)
                self.check_document(config, "parsed")
                documents.append(config)
                warnings.extend(notes)
            except Exception as exc:
                failures.append({"path": str(original), "error": self.error_code(exc)})
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
        for source in sources:
            lines.append(
                f"  {source.config['id']} · {source.identity['title']} "
                f"({source.identity['document_role']})"
            )
            lines.extend("  注意：" + note for note in source.config.get("notes", []))
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
            f"上限：{task['budget']['max_calls']} 次HTTP；"
            f"{task['budget'].get('max_cost', '未设置')} "
            + task.get("model", {}).get("currency", "CNY"),
            "输出："
            + ", ".join(task.get("export_formats", ["markdown", "csv", "jsonl"])),
            "定位不等于科学支持；AI结果不会标为人工确认。",
        ]
        return "\n".join(lines)

    def binding(self, scope: str, payload: dict) -> str:
        if scope == "execute":
            validated = self.validate_research_task(payload)
            payload = {"task": validated["task"], "sources": validated["documents"]}
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
        if not self.remote:
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
        self._save_job(receipt)

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

        if not background:
            return execute()
        with self._lock:
            self._jobs[job_id] = self._pool.submit(execute)
        return deepcopy(receipt)

    def _save_job(self, receipt):
        path = self.path(
            self.workspace / "jobs" / receipt["job_id"] / "status.json", write=True
        )
        write_json(path, receipt, overwrite=True)

    def _progress(self, receipt, row):
        receipt["latest_document"] = row
        self._save_job(receipt)

    def get_run_status(self, job_id: str) -> dict:
        if not re.fullmatch("[0-9a-f]{32}", job_id):
            raise ValueError("invalid job ID")
        receipt = read_json(self.path(self.workspace / "jobs" / job_id / "status.json"))
        if receipt["status"] in {"QUEUED", "RUNNING"} and job_id not in self._jobs:
            receipt["status"] = "INTERRUPTED"
            receipt["recovery"] = (
                "服务重启后不自动重发；重新校验授权并执行，复用引擎缓存。"
            )
        if receipt.get("run_directory"):
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
