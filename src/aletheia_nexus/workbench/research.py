"""Local workbench adapters for existing parsing, search and research services.

The UI works with library IDs. Research artifacts always bind immutable copies,
so reorganizing a library cannot silently change a historical research input.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, local
from uuid import uuid4

from aletheia_nexus.content.backends import (
    AdaptiveOcrBackend,
    TesseractOcrBackend,
    TesseractOcrConfig,
)
from aletheia_nexus.content.corpus import Corpus, CorpusDocument, search_corpus
from aletheia_nexus.content.evidence import build_evidence_pack, evidence_markdown
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.parser import ParserConfig
from aletheia_nexus.content.service import parse_document
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.processing.contracts import TASK_SCHEMA, validate_task
from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import (
    export_results,
    revise_result,
    verify_result,
)
from aletheia_nexus.research_app import ResearchApplication, read_json
from aletheia_nexus.research_planner import (
    DEFAULT_MODEL,
    draft_task,
    planning_request,
)

from .research_live import LiveResearchRuns, material_groups


class _WorkbenchApplication(ResearchApplication):
    """Forward native, per-document progress without changing engine semantics."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current = local()

    def _start_job(self, receipt, execute, *, background):
        callback = getattr(self.current, "on_start", None)
        if callback is not None:
            callback(receipt)
        return super()._start_job(receipt, execute, background=background)

    def _progress(self, receipt, row):
        super()._progress(receipt, row)
        context = getattr(self.current, "context", None)
        if context is not None:
            context.record(
                row.get("document_id", row.get("id", "research")),
                row.get("status", "RUNNING"),
                native=row,
            )
            self.current.progress_count = getattr(self.current, "progress_count", 0) + 1
            context.progress(
                self.current.progress_count,
                self.current.progress_total,
                stage="research",
                native_job_id=receipt["job_id"],
                native=row,
            )
            # The native engine reaches this callback after a paper completes.
            # A charged/in-flight request is never represented as cancelled.
            from .jobs import TaskCancelled

            try:
                context.checkpoint()
            except TaskCancelled:
                self.current.cancelled_at_boundary = True
                raise


class WorkbenchResearch:
    def __init__(self, library, workspace: str | Path):
        self.library = library
        self.workspace = Path(workspace).resolve() / "research-workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.app = _WorkbenchApplication(
            [library.root], self.workspace, remote=True, network=False
        )
        self.live = LiveResearchRuns(self.app)
        self.index_path = self.workspace / "document-index.json"
        self.active_path = self.workspace / "active-parsed-versions.json"
        self._lock = RLock()

    def _index(self) -> dict:
        if not self.index_path.exists():
            return {}
        value = read_json(self.index_path)
        if not isinstance(value, dict):
            raise ValueError("Invalid workbench document index")
        return value

    def _remember(self, key: str, document: dict, *, options=None) -> None:
        with self._lock:
            index = self._index()
            versions = index.setdefault(key, [])
            if not any(v["document"] == document for v in versions):
                versions.append(
                    {
                        "document": document,
                        "options": options or {},
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            write_json(self.index_path, index, overwrite=True)

    def _active_versions(self):
        return read_json(self.active_path) if self.active_path.exists() else {}

    def _activate(self, key, document):
        with self._lock:
            active = self._active_versions()
            active[key] = document["artifact"]
            write_json(self.active_path, active, overwrite=True)

    def library_source_map(self):
        """Resolve frozen sources to current papers by source hashes, never names."""
        result = {}
        try:
            papers = self.library.scan()["items"]
        except (OSError, ValueError, RuntimeError):
            return result
        for paper in papers:
            try:
                entries = [
                    (
                        paper.get("pdf_sha256") or sha256_file(Path(paper["pdf_path"])),
                        paper["sidecar_path"],
                    )
                ]
            except (OSError, ValueError, KeyError):
                continue
            entries.extend(
                (a.get("sha256"), a.get("sidecar_path"))
                for a in paper.get("attachments", [])
            )
            for pdf_hash, sidecar in entries:
                if pdf_hash and sidecar:
                    try:
                        result[(pdf_hash, sha256_file(self.app.path(sidecar)))] = paper[
                            "id"
                        ]
                    except (OSError, ValueError, RuntimeError):
                        continue
        return result

    def _record_research_associations(
        self, checked, receipt, *, allow_extra_pages=False
    ):
        mapping = self.library_source_map()
        paper_ids = {
            mapping.get((d["pdf_sha256"], d["acquisition_sidecar_sha256"]))
            for d in checked["documents"]
        } - {None}
        native = receipt.get("native_receipt") or receipt
        job_id = native.get("job_id")
        if not job_id:
            return receipt
        warnings = []
        for paper_id in paper_ids:
            try:
                paper = self.library.get(paper_id)
                history = deepcopy(
                    (paper.get("metadata") or {}).get("research_tasks", [])
                )
                entry = {
                    "job_id": job_id,
                    "task_id": checked["task"]["id"],
                    "status": receipt["status"],
                    "fingerprint": checked["task_fingerprint"],
                    "run_directory": native.get("run_directory"),
                    "extra_pages_authorized": allow_extra_pages,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                history = [
                    h
                    for h in history
                    if not isinstance(h, dict) or h.get("job_id") != job_id
                ]
                self.library.update_metadata(paper_id, research_tasks=[*history, entry])
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                warnings.append(
                    "研究结果已保存，但当前文库的任务关联未能更新；请查看原生运行历史。"
                )
        if warnings:
            return {**receipt, "library_warnings": warnings}
        return receipt

    def validate_plan(self, task):
        checked = self.app.validate_research_task(task)
        mains = {}
        for source in checked["documents"]:
            if source["document_role"] == "ARTICLE":
                mains.setdefault(source["pdf_sha256"], []).append(source["id"])
        if any(
            source["document_role"] == "SUPPLEMENT"
            and len(mains.get((source.get("parent") or {}).get("pdf_sha256"), [])) > 1
            for source in checked["documents"]
        ):
            raise ProcessingError("supplement_parent_ambiguous_same_pdf_bytes")
        return checked

    def configure_plan(self, task, parameters, *, previous=None):
        if not isinstance(parameters, dict) or set(parameters) - {
            "rules",
            "query",
            "context_pages",
        }:
            raise ValueError("取材参数仅支持研究规则、关键词和上下文页数")
        if "rules" in parameters and (
            not isinstance(parameters["rules"], list)
            or any(not isinstance(rule, str) for rule in parameters["rules"])
        ):
            raise ValueError("研究规则需要逐行文本列表")
        if "query" in parameters and not isinstance(parameters["query"], str):
            raise ValueError("取材关键词需要文本")
        value = deepcopy(task)
        value["rules"] = list(
            dict.fromkeys([*value.get("rules", []), *parameters.get("rules", [])])
        )
        if parameters.get("query", "").strip():
            value["query"] = parameters["query"].strip()
        else:
            value.pop("query", None)
        if "context_pages" in parameters:
            value["context_pages"] = parameters["context_pages"]
        checked = self.validate_plan(value)
        path = (
            self.workspace
            / "preparations"
            / ("configured-plan-" + uuid4().hex + ".json")
        )
        write_json(path, checked["task"])
        return {
            **(previous or {}),
            **checked,
            "task_file": str(path),
            "planner_task_file": (previous or {}).get("task_file"),
        }

    @staticmethod
    def ocr_summary(diagnostics, options):
        count = (diagnostics.get("quality") or {}).get("ocr_supplemented_blocks", 0)
        backend = (diagnostics.get("parser") or {}).get("backend") or {}
        configured = (
            options.get("ocr")
            if "ocr" in options
            else "ocr" in backend.get("name", "").casefold()
        )
        status = "USED" if count else "CONFIGURED" if configured else "NOT_REQUESTED"
        return status, {
            "configured": bool(configured),
            "ocr_text_blocks": count,
            "backend": backend,
            "interpretation": "是否配置及是否产生OCR文本块，不代表OCR识别或科学抽取准确率。",
        }

    def _materials(self, ids, include_si=False, *, errors=None) -> list[dict]:
        materials = []
        seen = set()
        selected_ids = list(dict.fromkeys(ids))
        # A get() per selected row would repeatedly scan/hash the entire library.
        # Resolve this selection once, then validate only its chosen materials.
        by_id = {r["id"]: r for r in self.library.scan()["items"]}
        for paper_id in selected_ids:
            paper = by_id.get(paper_id)
            if paper is None:
                if errors is not None:
                    errors.append(
                        {
                            "id": paper_id,
                            "paper_id": paper_id,
                            "status": "FAILED",
                            "error": "selected_paper_unavailable",
                            "reason": "选中文献已缺失或来源不再有效，请刷新文库",
                        }
                    )
                    continue
                raise ValueError(
                    "Selected paper is unavailable; refresh the library selection"
                )
            entries = [
                {
                    "id": paper_id,
                    "pdf": paper["pdf_path"],
                    "sidecar": paper["sidecar_path"],
                    "paper_id": paper_id,
                }
            ]
            if include_si:
                for attachment in paper.get("attachments", []):
                    path = attachment.get("path", attachment.get("pdf_path"))
                    if (
                        path
                        and Path(path).suffix.lower() == ".pdf"
                        and attachment.get("role", "SUPPLEMENT") in {"SUPPLEMENT", "SI"}
                    ):
                        entries.append(
                            {
                                "id": attachment.get(
                                    "id", "si_" + str(attachment.get("sha256", ""))[:16]
                                ),
                                "pdf": path,
                                "sidecar": attachment.get("sidecar_path")
                                or str(acquisition_sidecar_path(path)),
                                "paper_id": paper_id,
                            }
                        )
            for entry in entries:
                # Source paths are checked before hashes or source records are read.
                try:
                    pdf = self.app.path(entry["pdf"])
                    sidecar = self.app.path(entry["sidecar"])
                    source = self.app.check_document(
                        {"id": entry["id"], "pdf": str(pdf), "sidecar": str(sidecar)},
                        "direct",
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    if errors is None:
                        raise
                    errors.append(
                        {
                            "id": entry["id"],
                            "paper_id": paper_id,
                            "status": "FAILED",
                            "title": paper.get("title_original")
                            or paper.get("title")
                            or "文献来源异常",
                            "document_role": "ARTICLE"
                            if entry["id"] == paper_id
                            else "SUPPLEMENT",
                            "original_pdf": entry["pdf"],
                            "error": self.app.error_code(exc),
                            "reason": str(exc)[:1000],
                        }
                    )
                    continue
                key = (
                    source.identity["pdf_sha256"]
                    + ":"
                    + source.identity["acquisition_sidecar_sha256"]
                )
                if key in seen:
                    continue
                seen.add(key)
                materials.append({**entry, "key": key, "source": source})
        return materials

    def _snapshot(self, material: dict) -> dict:
        source = material["source"]
        destination = self.workspace / "materials" / source.identity["pdf_sha256"]
        pdf = self.app._copy_source_file(source.pdf, destination / "paper.pdf")
        sidecar = self.app._copy_source_file(
            source.sidecar,
            destination
            / "json"
            / (source.identity["acquisition_sidecar_sha256"] + ".acquisition.json"),
        )
        source.verify()
        return {"id": material["id"], "pdf": str(pdf), "sidecar": str(sidecar)}

    @staticmethod
    def parser_options() -> dict:
        return {
            **ParserConfig().as_dict(),
            "ocr": False,
            "ocr_languages": "eng",
            "ocr_dpi": 300,
            "image_ocr": "tesseract",
            "ocr_timeout_seconds": 120,
            "ocr_max_raster_pixels": 50_000_000,
            "new_version": False,
        }

    def _parse_configuration(self, options=None):
        options = {**self.parser_options(), **(options or {})}
        if set(options) - self.parser_options().keys():
            raise ValueError("Unsupported parsing option")
        config = ParserConfig(**{f.name: options[f.name] for f in fields(ParserConfig)})
        if type(options["ocr"]) is not bool or type(options["new_version"]) is not bool:
            raise ValueError("OCR and new_version must be booleans")
        if not re.fullmatch(
            r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", options["ocr_languages"]
        ):
            raise ValueError("Invalid OCR language selection")
        backend = None
        if options["ocr"]:
            backend = AdaptiveOcrBackend(
                ocr_backends=(
                    TesseractOcrBackend(
                        TesseractOcrConfig(
                            languages=options["ocr_languages"],
                            dpi=options["ocr_dpi"],
                            image_ocr=options["image_ocr"],
                            timeout_seconds=options["ocr_timeout_seconds"],
                            max_raster_pixels=options["ocr_max_raster_pixels"],
                        )
                    ),
                )
            )
        return options, config, backend

    def parse(self, ids, options=None, *, context=None, include_si=True) -> dict:
        options, config, backend = self._parse_configuration(options)
        failures = []
        materials = self._materials(ids, include_si, errors=failures)
        rows = list(failures)
        total = len(materials) + len(failures)
        if context:
            for row in failures:
                context.record(
                    row["id"],
                    "FAILED",
                    **{k: v for k, v in row.items() if k not in {"id", "status"}},
                )
        for n, material in enumerate(materials):
            if context:
                context.checkpoint()
                context.progress(
                    n + len(failures), total, item=material["pdf"], stage="parse"
                )
                if context.should_skip(material["id"]):
                    rows.append({"id": material["id"], "status": "SKIPPED"})
                    context.record(
                        material["id"],
                        "SKIPPED",
                        title=material["source"].identity["title"],
                    )
                    continue
            try:
                prior = self.versions_for_key(material["key"])
                # Reuse only a source-checked matching-parameter version. Explicit
                # new_version creates a new immutable file even if options match.
                matched = next(
                    (v for v in reversed(prior) if v["options"] == options), None
                )
                if matched and not options["new_version"]:
                    document = {**matched["document"], "id": material["id"]}
                    self.app.check_document(document, "parsed").verify()
                    diagnostics = self.app.get_parse_diagnostics(document)
                    reused = True
                else:
                    document = self._snapshot(material)
                    path = Path(document["pdf"]).parent / (
                        "parsed-" + uuid4().hex + ".parsed.json"
                    )
                    result = parse_document(
                        document["pdf"],
                        sidecar_path=document["sidecar"],
                        output_path=path,
                        config=config,
                        backend=backend,
                    )
                    document["artifact"] = str(path)
                    material["source"].verify()
                    self._remember(material["key"], document, options=options)
                    diagnostics = {
                        "status": result.status,
                        **self.app.get_parse_diagnostics(document),
                    }
                    reused = False
                row = {
                    "id": material["id"],
                    "paper_id": material["paper_id"],
                    "title": material["source"].identity["title"],
                    "role": material["source"].identity["document_role"],
                    "document_role": material["source"].identity["document_role"],
                    "original_pdf": material["pdf"],
                    "document": document,
                    "reused": reused,
                    **diagnostics,
                }
                if row["status"] in {"PARSED", "PARTIAL"}:
                    self._activate(material["key"], document)
                if material["id"] == material["paper_id"]:
                    ocr_status, ocr_diagnostics = self.ocr_summary(diagnostics, options)
                    self.library.update_metadata(
                        material["paper_id"],
                        parse_status=row["status"],
                        artifact=document["artifact"],
                        parse_options=options,
                        ocr_status=ocr_status,
                        ocr_diagnostics=ocr_diagnostics,
                    )
            except Exception as exc:
                row = {
                    "id": material["id"],
                    "status": "FAILED",
                    "title": material["source"].identity["title"],
                    "document_role": material["source"].identity["document_role"],
                    "original_pdf": material["pdf"],
                    "error": self.app.error_code(exc),
                    "detail": str(exc)[:1000],
                }
            rows.append(row)
            if context:
                context.record(
                    material["id"],
                    row["status"],
                    **{k: v for k, v in row.items() if k not in {"id", "status"}},
                )
        if context:
            context.progress(total, total, stage="PDF 解析结束")
        return {
            "status": "COMPLETED"
            if rows and all(r["status"] == "PARSED" for r in rows)
            else "PARTIAL",
            "items": rows,
            "network_access": False,
        }

    def versions_for_key(self, key):
        return deepcopy(self._index().get(key, []))

    def versions(self, paper_id, *, include_si=False):
        return [
            {
                "id": m["id"],
                "key": m["key"],
                "versions": self.versions_for_key(m["key"]),
                "active_artifact": self._active_versions().get(m["key"]),
            }
            for m in self._materials([paper_id], include_si)
        ]

    def select_version(self, paper_id, artifact, *, material_id=None):
        material_id = material_id or paper_id
        material = next(
            (m for m in self._materials([paper_id], True) if m["id"] == material_id),
            None,
        )
        if material is None:
            raise ValueError("Parsed version is outside this selected paper")
        version = next(
            (
                v
                for v in self.versions_for_key(material["key"])
                if v["document"]["artifact"] == artifact
            ),
            None,
        )
        if version is None:
            raise ValueError(
                "Unknown parsed version; select a recorded immutable artifact"
            )
        document = {**version["document"], "id": material["id"]}
        self.app.check_document(document, "parsed").verify()
        self._activate(material["key"], document)
        diagnostics = self.app.get_parse_diagnostics(document)
        if material_id == paper_id:
            ocr_status, ocr_diagnostics = self.ocr_summary(
                diagnostics, version["options"]
            )
            self.library.update_metadata(
                paper_id,
                parse_status=diagnostics["status"],
                artifact=artifact,
                parse_options=version["options"],
                ocr_status=ocr_status,
                ocr_diagnostics=ocr_diagnostics,
            )
        return {"document": document, "diagnostics": diagnostics}

    def prepare(
        self,
        ids,
        *,
        include_si=False,
        parse_missing=True,
        parse_options=None,
        context=None,
    ) -> dict:
        documents, unparsed = [], []
        # Defaults are captured by the submitting UI. They apply only when no
        # source-checked parsed version exists; preparing never replaces an old
        # artifact merely because a user's current defaults have changed.
        options, config, backend = self._parse_configuration(parse_options)
        materials = self._materials(ids, include_si, errors=unparsed)
        legacy_candidates = None
        for n, material in enumerate(materials):
            if context:
                context.checkpoint()
                context.progress(
                    n, len(materials), stage="准备固定研究材料", item=material["id"]
                )
            versions = self.versions_for_key(material["key"])
            found = None
            found_options = {}
            active = self._active_versions().get(material["key"])
            ordered = sorted(
                reversed(versions), key=lambda v: v["document"]["artifact"] != active
            )
            for version in ordered:
                try:
                    self.app.check_document(version["document"], "parsed").verify()
                except (OSError, ValueError, RuntimeError):
                    continue
                found = {**version["document"], "id": material["id"]}
                found_options = version["options"]
                break
            if found is None:
                # Discover established CLI artifacts without parsing anything.
                # This is done on explicit research/search, never on table render.
                if legacy_candidates is None:
                    from aletheia_nexus.content.artifact import ParsedArtifact

                    legacy_candidates = {}
                    for path in sorted(self.library.root.rglob("*.parsed.json")):
                        try:
                            path = self.app.path(path)
                            artifact = ParsedArtifact.load(path)
                            source = artifact.document["source"]
                            legacy_candidates.setdefault(
                                source["pdf_sha256"], []
                            ).append((artifact.document["created_at"], path))
                        except (OSError, ValueError, RuntimeError, KeyError):
                            continue
                fingerprint = material["source"].identity["pdf_sha256"]
                for _, candidate in sorted(
                    legacy_candidates.get(fingerprint, []), reverse=True
                ):
                    try:
                        config = self._snapshot(material)
                        config["artifact"] = str(candidate)
                        self.app.check_document(config, "parsed").verify()
                        # Preserve legacy parsed bytes too. Explicit PDF/sidecar
                        # locators bind the copy; the legacy source is never edited.
                        copied = self.app._copy_source_file(
                            candidate,
                            Path(config["pdf"]).parent
                            / ("legacy-" + sha256_file(candidate) + ".parsed.json"),
                        )
                        copied_config = {**config, "artifact": str(copied)}
                        try:
                            self.app.check_document(copied_config, "parsed").verify()
                            config = copied_config
                        except (OSError, ValueError, RuntimeError):
                            # Unusual relative locator layouts remain explicit and
                            # checked in-place; unsafe paths never gain permission.
                            pass
                    except (OSError, ValueError, RuntimeError, KeyError):
                        continue
                    found = config
                    self._remember(material["key"], found)
                    self._activate(material["key"], found)
                    break
            if found is None and parse_missing:
                # Workbench IDs include the source declaration, not just PDF
                # bytes. Two declared identities of identical bytes keep distinct
                # sidecars and task IDs without the CLI's paper.pdf-sidecar slot.
                try:
                    found = self._snapshot(material)
                    artifact = Path(found["pdf"]).parent / (
                        "parsed-" + uuid4().hex + ".parsed.json"
                    )
                    parse_document(
                        found["pdf"],
                        sidecar_path=found["sidecar"],
                        output_path=artifact,
                        config=config,
                        backend=backend,
                    )
                    found["artifact"] = str(artifact)
                    self.app.check_document(found, "parsed").verify()
                    self._remember(material["key"], found, options=options)
                    self._activate(material["key"], found)
                    found_options = options
                except (OSError, ValueError, RuntimeError):
                    found = None
            if found is None:
                unparsed.append(
                    {
                        "id": material["id"],
                        "paper_id": material["paper_id"],
                        "reason": "No usable parsed version",
                    }
                )
            else:
                if material["id"] == material["paper_id"]:
                    paper = self.library.get(material["paper_id"])
                    if (paper.get("metadata") or {}).get("artifact") != found[
                        "artifact"
                    ]:
                        diagnostics = self.app.get_parse_diagnostics(found)
                        ocr_status, ocr_diagnostics = self.ocr_summary(
                            diagnostics, found_options
                        )
                        self.library.update_metadata(
                            material["paper_id"],
                            parse_status=diagnostics["status"],
                            artifact=found["artifact"],
                            parse_options=found_options,
                            ocr_status=ocr_status,
                            ocr_diagnostics=ocr_diagnostics,
                        )
                documents.append({**deepcopy(found), "_paper_id": material["paper_id"]})
            if context:
                context.record(
                    material["id"],
                    "PREPARED" if found else "FAILED",
                    document=found,
                    title=material["source"].identity["title"],
                    role=material["source"].identity["document_role"],
                )
        return {"documents": documents, "unparsed": unparsed}

    @staticmethod
    def _clean_documents(documents):
        return [
            {k: v for k, v in d.items() if not k.startswith("_")} for d in documents
        ]

    def search(
        self,
        query,
        ids=None,
        *,
        include_si=True,
        mode="and",
        exact=False,
        role=None,
        section_type=None,
        limit=50,
        offset=0,
    ) -> dict:
        if not 1 <= limit <= 500 or not 0 <= offset <= 100000:
            raise ValueError("Search page size/offset out of range")
        if ids is None:
            ids = [r["id"] for r in self.library.scan()["items"]]
        prepared = self.prepare(ids, include_si=include_si, parse_missing=False)
        sources, entries = [], []
        paper_ids = {}
        configs = {}
        failures = list(prepared["unparsed"])
        for doc in prepared["documents"]:
            try:
                source = self.app.check_document(doc, "parsed")
                sources.append(source)
                entries.append(
                    CorpusDocument(
                        source.artifact.path,
                        source.pdf,
                        source.artifact,
                        source.artifact.document,
                    )
                )
                paper_ids[source.artifact.document["artifact_id"]] = doc["_paper_id"]
                configs[source.artifact.document["artifact_id"]] = (
                    self._clean_documents([doc])[0]
                )
            except (OSError, ValueError, RuntimeError) as exc:
                failures.append({"id": doc["id"], "reason": str(exc)[:500]})
        # Legacy parsed artifacts can remain in the library while source PDFs
        # are snapshotted. A common ancestor supplies display-relative paths only.
        # Each explicit file has already passed the application path gate.
        import os

        corpus_root = (
            Path(
                os.path.commonpath(
                    [
                        str(p.parent)
                        for entry in entries
                        for p in (entry.pdf, entry.path)
                    ]
                )
            )
            if entries
            else self.workspace
        )
        corpus = Corpus(corpus_root, entries, failures, [])
        report = search_corpus(
            corpus,
            query,
            mode=mode,
            exact=exact,
            role=role,
            section_type=section_type,
            limit=offset + limit,
        )
        for source in sources:
            source.verify()
        report["hits"] = [
            {
                **h,
                "paper_id": paper_ids[h["parsed_artifact_id"]],
                "pdf": str(corpus_root / h["pdf"]),
                "artifact": str(corpus_root / h["artifact"]),
                "document": configs[h["parsed_artifact_id"]],
            }
            for h in report["hits"][offset : offset + limit]
        ]
        report["returned_hits"] = len(report["hits"])
        report["offset"] = offset
        report["paper_count"] = len({h["paper_id"] for h in report["hits"]})
        report["network_access"] = False
        report["interpretation"] = (
            "关键词命中只表示字面匹配；未命中不表示未报告，解析状态不表示科学准确率。"
        )
        return report

    def local_plan(
        self,
        goal,
        ids,
        *,
        include_si=False,
        fields=None,
        model=None,
        budget=None,
        mode="local",
        task_type="extract",
        parse_options=None,
        context=None,
    ) -> dict:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("请先输入科研目标")
        prepared = self.prepare(
            ids, include_si=include_si, parse_options=parse_options, context=context
        )
        if prepared["unparsed"] or not prepared["documents"]:
            raise ValueError("Selected materials contain unparsed/failed sources")
        documents = self._clean_documents(prepared["documents"])
        return validate_task(
            {
                "schema": TASK_SCHEMA,
                "id": "ui_" + uuid4().hex[:12],
                "type": task_type,
                "objective": goal,
                "documents": documents,
                "fields": fields
                or [
                    {
                        "id": "finding",
                        "label": "研究内容",
                        "type": "string",
                        "description": goal,
                    }
                ],
                "mode": mode,
                "allow_remote": mode != "local",
                "model": deepcopy(model or DEFAULT_MODEL),
                "budget": {
                    "max_calls": 10,
                    "max_cost": 2,
                    "max_supplement_rounds": 0,
                    **(budget or {}),
                },
            }
        )

    def plan(
        self,
        goal,
        ids,
        *,
        include_si=False,
        consent=False,
        model=None,
        max_cost=2,
        max_calls=10,
        planning_max_cost=0.5,
        budget=None,
        parse_options=None,
        context=None,
        transport=None,
    ) -> dict:
        if not consent:
            raise ProcessingError("explicit_planning_consent_required")
        prepared = self.prepare(
            ids, include_si=include_si, parse_options=parse_options, context=context
        )
        if prepared["unparsed"]:
            raise ValueError("Resolve unavailable selected materials before planning")
        request = planning_request(
            self.app,
            goal,
            self._clean_documents(prepared["documents"]),
            model=model,
            max_cost=max_cost,
            max_calls=max_calls,
            planning_max_cost=planning_max_cost,
        )
        # Planning consent covers metadata only. Extra source pages require a
        # fresh, explicit content authorization in the execution UI.
        request["research_budget"]["max_supplement_rounds"] = 0
        if budget is not None:
            template = validate_task(
                {
                    "schema": TASK_SCHEMA,
                    "id": "planning_limits",
                    "type": "extract",
                    "objective": goal,
                    "documents": request["documents"],
                    "mode": "hybrid",
                    "allow_remote": True,
                    "fields": [
                        {"id": "check", "type": "string", "description": "预算契约检查"}
                    ],
                    "model": request["model"],
                    "budget": {
                        **request["research_budget"],
                        **budget,
                        "max_supplement_rounds": 0,
                    },
                }
            )
            request["research_budget"] = template["budget"]

        def planning_progress(snapshot):
            if context is None:
                return
            calls = snapshot["calls"]
            details = {
                "planning_run_id": snapshot["run_id"],
                "planning_directory": snapshot["run_directory"],
                "planning_manifest": snapshot["manifest_file"],
                "planning_status": snapshot["status"],
                "planning_model": snapshot["model"],
                "planning_calls": calls,
                "planning_usage": snapshot["usage"],
                "planning_budget": snapshot["planning_budget"],
                "planning_task_file": snapshot["task_file"],
                "billing_uncertain": any(
                    c.get("estimated_cost") is None for c in calls
                ),
            }
            context.progress(
                len(calls),
                snapshot["planning_budget"]["max_calls"],
                item="自然语言科研规划（仅文献元数据）",
                stage="自然语言科研规划",
                **details,
            )
            context.record(
                "planning:" + snapshot["run_id"], snapshot["status"], **details
            )
            # A failed call is a safe boundary before any separately charged
            # retry; an in-flight request is never represented as withdrawn.
            if not calls or snapshot["status"] == "FAILED":
                context.checkpoint()

        if context:
            context.checkpoint()
        token = self.app.authorize("plan", request)
        result = draft_task(
            self.app,
            request,
            authorization=token,
            transport=transport,
            progress=planning_progress,
        )
        # A repaired draft can contain a failed, charged call in its ledger.
        # Successful native validation still completes this planning operation.
        return {**result, "status": "COMPLETED"}

    def execute(
        self,
        task,
        *,
        consent=False,
        allow_extra_pages=False,
        context=None,
        provider=None,
    ) -> dict:
        checked = self.validate_plan(task)
        task = checked["task"]
        owners = material_groups(checked["documents"])
        groups_total = len(set(owners.values()))
        material_count = len(checked["documents"])
        if task["mode"] != "local" and not consent:
            raise ProcessingError("explicit_research_consent_required")
        if type(allow_extra_pages) is not bool:
            raise ValueError("额外页授权必须由本次明确勾选")
        if (
            task["mode"] != "local"
            and task["budget"]["max_supplement_rounds"] > 0
            and not allow_extra_pages
        ):
            raise ProcessingError("explicit_supplement_page_consent_required")
        if context:
            context.checkpoint()
            context.progress(
                0,
                material_count if task["mode"] == "local" else groups_total,
                stage="research",
                task_fingerprint=checked["task_fingerprint"],
                material_count=material_count,
                group_count=groups_total,
            )
        token = self.app.authorize("execute", task) if task["mode"] != "local" else None
        self.app.current.context = context
        self.app.current.cancelled_at_boundary = False
        self.app.current.progress_count = 0
        self.app.current.progress_total = groups_total
        before = set((self.workspace / "research" / "runs").glob("*/manifest.json"))

        def started(receipt):
            self.live.register(
                receipt,
                checked,
                before,
                workbench_job_id=getattr(context, "job_id", None) if context else None,
            )
            if context:
                context.progress(
                    0,
                    material_count if task["mode"] == "local" else groups_total,
                    stage="research",
                    native_job_id=receipt["job_id"],
                    material_count=material_count,
                    group_count=groups_total,
                )
                context.checkpoint()

        self.app.current.on_start = started
        try:
            receipt = self.app.execute_research_task(
                task, authorization=token, background=False, provider=provider
            )
            if self.app.current.cancelled_at_boundary:
                # The original app records an exception from its document callback
                # as FAILED. Preserve that diagnostic verbatim while exposing the
                # explicit workbench cancellation at the completed-paper boundary.
                runs = []
                outputs = []
                for path in (
                    set((self.workspace / "research" / "runs").glob("*/manifest.json"))
                    - before
                ):
                    manifest = read_json(path)
                    if manifest.get("task_fingerprint") == checked["task_fingerprint"]:
                        runs.append(
                            {
                                "manifest": str(path),
                                "status": manifest["status"],
                                "usage": manifest.get("usage"),
                                "items": manifest.get("items", []),
                            }
                        )
                        outputs.extend(
                            str(p) for p in path.parent.glob("*.result.json")
                        )
                cancelled = {
                    "status": "CANCELLED",
                    "native_receipt": receipt,
                    "native_runs": runs,
                    "outputs": outputs,
                    "interruption_point": "completed_paper_boundary",
                    "notice": "已完成的调用与结果保留；取消只停止后续调度，不撤回已经完成或可能计费的请求。",
                }
                return self._record_research_associations(
                    checked, cancelled, allow_extra_pages=allow_extra_pages
                )
            return self._record_research_associations(
                checked, receipt, allow_extra_pages=allow_extra_pages
            )
        finally:
            self.app.current.context = None
            self.app.current.on_start = None

    def live_run(self, job_id):
        return self.live.get(job_id)

    def history(self):
        return self.app.list_research_runs(limit=100)["runs"]

    def results(self) -> list[dict]:
        paths = [
            *(self.workspace / "research" / "runs").glob("**/*.result.json"),
            *(self.workspace / "revisions").glob("*/result.json"),
        ]
        rows = []
        for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                value = self.app.read_research_result(str(path))
                rows.append(
                    {
                        "path": str(path),
                        "id": value["artifact_id"],
                        "objective": value["task"]["objective"],
                        "records": len(value["response"].get("records", [])),
                        "revisions": len(value["history"]),
                        "validation": value["validation"],
                    }
                )
            except (OSError, ValueError, RuntimeError):
                continue
        return rows

    def read_result(self, path):
        return self.app.read_research_result(path)

    def result_material_papers(self, result_path):
        value = read_json(self.app.path(result_path))
        verify_result(value)
        current = self.library_source_map()
        return {
            d["id"]: current.get(
                (d["source"]["pdf_sha256"], d["source"]["acquisition_sidecar_sha256"])
            )
            for d in value["package"]["documents"]
        }

    def supplement_task(self, result_path, request_index, *, context=None):
        """Make a new, unapproved plan from a saved material request and current SI.

        The parent result and its fixed sources remain untouched. Only explicitly
        associated current PDF SI can join; no parent is inferred from a filename.
        """
        parent = read_json(self.app.path(result_path))
        verify_result(parent)
        requests = parent["response"].get("requests", [])
        if type(request_index) is not int or not 0 <= request_index < len(requests):
            raise ValueError("请选择当前结果中真实存在的材料请求")
        request = requests[request_index]
        mapping = self.result_material_papers(result_path)
        paper_id = mapping.get(request["source_id"])
        if paper_id is None:
            raise ValueError(
                "请求所属论文不在当前文库，先导入保留原来源的正文后再补充材料"
            )
        prepared = self.prepare([paper_id], include_si=True, context=context)
        if prepared["unparsed"]:
            raise ValueError("关联补充材料未能完成解析，请先在解析窗口处理失败项")
        task = deepcopy(parent["task"])
        task["id"] = "ui_" + uuid4().hex[:12]
        documents = deepcopy(task["documents"])
        existing = {}
        added = 0
        for document in documents:
            source = self.app.check_document(
                document, "parsed" if document.get("artifact") else "direct"
            )
            existing[
                (
                    source.identity["pdf_sha256"],
                    source.identity["acquisition_sidecar_sha256"],
                )
            ] = document
        for candidate in self._clean_documents(prepared["documents"]):
            source = self.app.check_document(candidate, "parsed")
            key = (
                source.identity["pdf_sha256"],
                source.identity["acquisition_sidecar_sha256"],
            )
            if key not in existing and source.identity["document_role"] == "SUPPLEMENT":
                if candidate["id"] in {d["id"] for d in documents}:
                    candidate["id"] += "_" + uuid4().hex[:6]
                documents.append(candidate)
                existing[key] = candidate
                added += 1
        # Requested physical pages become explicit image pages in the new plan.
        # This does not authorize additional adaptive requests beyond those pages.
        target = next(d for d in documents if d["id"] == request["source_id"])
        supplied_images = {
            i["page"]
            for i in parent["package"].get("images", [])
            if i.get("source_id") == request["source_id"]
        }
        if not added and not (set(request.get("pages", [])) - supplied_images):
            raise ValueError(
                "尚无新增的关联PDF SI或未读原页；请先补齐材料，已有结果不会被重复当作材料已补充"
            )
        if request.get("pages"):
            target["image_pages"] = sorted(
                set(target.get("image_pages", [])) | set(request["pages"])
            )
        task.update(documents=documents, mode="hybrid", allow_remote=True)
        task["budget"]["max_supplement_rounds"] = 0
        checked = self.validate_plan(task)
        return {
            "task": checked["task"],
            "plan": checked["plan"],
            "parent_result_id": parent["artifact_id"],
            "request": deepcopy(request),
            "network_access": False,
            "authorization_required": True,
        }

    def citation_document(self, result_path, source_id):
        result = read_json(self.app.path(result_path))
        verify_result(result)
        entry = next(d for d in result["package"]["documents"] if d["id"] == source_id)
        config = {
            "id": source_id,
            **{k: v for k, v in entry["locators"].items() if v is not None},
        }
        source = self.app.check_document(
            config, "parsed" if config.get("artifact") else "direct"
        )
        if source.identity != entry["source"]:
            raise ProcessingError("historical_source_identity_mismatch")
        return config

    def pdf_document(self, paper_id, attachment_id=None):
        material = next(
            m
            for m in self._materials([paper_id], bool(attachment_id))
            if attachment_id is None or m["id"] == attachment_id
        )
        return self._snapshot(material)

    def revise(
        self,
        result_path,
        target: dict,
        replacement: dict,
        *,
        reason,
        author,
        confirm=False,
        human=False,
    ):
        if not human:
            raise ProcessingError("explicit_human_revision_required")
        parent_path = self.app.path(result_path)
        parent = read_json(parent_path)
        for d in parent["package"]["documents"]:
            self.citation_document(result_path, d["id"])
        child = revise_result(
            parent,
            {
                **target,
                "replacement": replacement,
                "reason": reason,
                "author": author,
                "at": datetime.now(timezone.utc).isoformat(),
                "authority": "human",
                "confirm": confirm,
            },
        )
        directory = self.workspace / "revisions" / uuid4().hex
        path = directory / "result.json"
        write_json(path, child)
        outputs = export_results([child], child["task"], directory)
        return {
            "result": str(path),
            "parent_result_id": parent["artifact_id"],
            "authority": "human",
            "confirmed": confirm,
            "outputs": [str(path), *(str(directory / name) for name in outputs)],
        }

    def export(self, paths, *, name="research", formats=None):
        import zipfile

        from aletheia_nexus.processing.contracts import digest

        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("Export display name must contain 1–200 characters")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")
        if slug != name or len(slug) > 64:
            slug = (slug[:40] or "export") + "-" + digest(name)[:12]
        report = self.app.export_research_results(paths, slug, formats)
        directory = Path(report["directory"])
        native_files, exported_results, warnings = [], [], []

        def record_file(path):
            native_files.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )

        for index, selected in enumerate(paths, 1):
            original = self.app.path(selected)
            value = read_json(original)
            verify_result(value)
            target = directory / "native" / f"result-{index:03d}"
            native = self.app._copy_source_file(original, target / "result.json")
            record_file(native)
            for key in ("task", "package", "history"):
                part = target / (key + ".json")
                write_json(part, value[key])
                record_file(part)
            images = []
            for image in value.get("package", {}).get("images", []):
                fingerprint = image.get("sha256", "")
                if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                    raise ValueError("原生结果的原页图像指纹无效")
                candidates = [original.parent / (fingerprint + ".png")]
                candidates.extend(
                    (self.workspace / "research" / "runs").glob(
                        "*/" + fingerprint + ".png"
                    )
                )
                image_source = next(
                    (
                        p
                        for p in candidates
                        if p.is_file() and sha256_file(self.app.path(p)) == fingerprint
                    ),
                    None,
                )
                if image_source is None:
                    warnings.append(
                        f"原生结果保留图像指纹，但原页图像文件缺失：{fingerprint}"
                    )
                    continue
                copied = self.app._copy_source_file(
                    image_source, target / "images" / (fingerprint + ".png")
                )
                if not any(
                    f["path"] == copied.relative_to(directory).as_posix()
                    for f in native_files
                ):
                    record_file(copied)
                images.append(copied.relative_to(directory).as_posix())
            exported_results.append(
                {
                    "artifact_id": value["artifact_id"],
                    "original_result": str(original),
                    "result_file": native.relative_to(directory).as_posix(),
                    "source_locators_preserved": True,
                    "image_files": images,
                }
            )
        manifest = {
            "schema": "aletheia-nexus/native-result-export/v1",
            "status": "PARTIAL" if warnings else "COMPLETED",
            "results": exported_results,
            "files": native_files,
            "warnings": warnings,
            "includes_original_pdfs": False,
            "source_location_policy": "原始来源定位保持不变；本包保留完整结果、材料包、任务、历史和可用图像，原PDF按来源哈希另行备份。",
        }
        manifest_path = directory / "native-manifest.json"
        write_json(manifest_path, manifest)
        bundle = directory / "native-results.zip"
        with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry in native_files:
                selected = directory / entry["path"]
                if sha256_file(selected) != entry["sha256"]:
                    raise ValueError("原生导出文件在打包前发生变化")
                archive.write(selected, arcname=entry["path"])
            archive.write(manifest_path, arcname="native-manifest.json")
        info = {
            "display_name": name,
            "directory_identifier": slug,
            "source_results": list(paths),
        }
        info_path = directory / "export-info.json"
        write_json(info_path, info)
        return {
            **report,
            "display_name": name,
            "native_manifest": str(manifest_path),
            "native_bundle": str(bundle),
            "warnings": warnings,
            "outputs": [
                *(str(Path(report["directory"]) / p) for p in report["outputs"]),
                str(info_path),
                str(manifest_path),
                str(bundle),
            ],
        }

    def export_evidence(self, hits, *, context_pages=1) -> dict:
        entries, selections = {}, {}
        for hit in hits:
            source = self.app.check_document(
                hit.get("document")
                or {"id": "selected", "pdf": hit["pdf"], "artifact": hit["artifact"]},
                "parsed",
            )
            key = source.artifact.document["artifact_id"]
            entries[key] = CorpusDocument(
                source.artifact.path,
                source.pdf,
                source.artifact,
                source.artifact.document,
            )
            selections.setdefault(key, set()).update(hit["pages"])
        if not entries:
            raise ValueError("Select evidence first")
        import os

        corpus_root = Path(
            os.path.commonpath(
                [
                    str(p.parent)
                    for entry in entries.values()
                    for p in (entry.path, entry.pdf)
                ]
            )
        )
        pack = build_evidence_pack(
            Corpus(corpus_root, list(entries.values()), [], []),
            document_pages={k: sorted(v) for k, v in selections.items()},
            context_pages=context_pages,
        )
        for entry in entries.values():
            matching = next(h for h in hits if h["artifact"] == str(entry.path))
            self.app.check_document(
                matching.get("document")
                or {
                    "id": "selected",
                    "pdf": str(entry.pdf),
                    "artifact": str(entry.path),
                },
                "parsed",
            ).verify()
        directory = self.workspace / "exports" / ("evidence-" + uuid4().hex[:12])
        write_json(directory / "evidence.json", pack)
        (directory / "evidence.md").write_text(
            evidence_markdown(pack), encoding="utf-8"
        )
        return {
            "directory": str(directory),
            "outputs": [
                str(directory / "evidence.json"),
                str(directory / "evidence.md"),
            ],
        }

    def close(self):
        self.app.close()
