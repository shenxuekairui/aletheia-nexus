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


class _WorkbenchApplication(ResearchApplication):
    """Forward native, per-document progress without changing engine semantics."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current = local()

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

    def _materials(self, ids, include_si=False) -> list[dict]:
        materials = []
        seen = set()
        selected_ids = list(dict.fromkeys(ids))
        # A get() per selected row would repeatedly scan/hash the entire library.
        # Resolve this selection once, then validate only its chosen materials.
        by_id = {r["id"]: r for r in self.library.scan()["items"]}
        for paper_id in selected_ids:
            paper = by_id.get(paper_id)
            if paper is None:
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
                                    "id", "si_" + sha256_file(Path(path))[:16]
                                ),
                                "pdf": path,
                                "sidecar": attachment.get("sidecar_path")
                                or str(acquisition_sidecar_path(path)),
                                "paper_id": paper_id,
                            }
                        )
            for entry in entries:
                # Source paths are checked before hashes or source records are read.
                pdf = self.app.path(entry["pdf"])
                sidecar = self.app.path(entry["sidecar"])
                source = self.app.check_document(
                    {
                        "id": "paper_" + sha256_file(pdf)[:16],
                        "pdf": str(pdf),
                        "sidecar": str(sidecar),
                    },
                    "direct",
                )
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

    def parse(self, ids, options=None, *, context=None, include_si=True) -> dict:
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
        materials = self._materials(ids, include_si)
        rows = []
        for n, material in enumerate(materials):
            if context:
                context.checkpoint()
                context.progress(n, len(materials), item=material["pdf"], stage="parse")
                if context.should_skip(material["id"]):
                    rows.append({"id": material["id"], "status": "SKIPPED"})
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
                    "document": document,
                    "reused": reused,
                    **diagnostics,
                }
                if row["status"] in {"PARSED", "PARTIAL"}:
                    self._activate(material["key"], document)
                if material["id"] == material["paper_id"]:
                    self.library.update_metadata(
                        material["paper_id"],
                        parse_status=row["status"],
                        artifact=document["artifact"],
                        parse_options=options,
                    )
            except Exception as exc:
                row = {
                    "id": material["id"],
                    "status": "FAILED",
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
            self.library.update_metadata(
                paper_id,
                parse_status=diagnostics["status"],
                artifact=artifact,
                parse_options=version["options"],
            )
        return {"document": document, "diagnostics": diagnostics}

    def prepare(
        self, ids, *, include_si=False, parse_missing=True, context=None
    ) -> dict:
        documents, unparsed = [], []
        materials = self._materials(ids, include_si)
        legacy_candidates = None
        for n, material in enumerate(materials):
            if context:
                context.checkpoint()
                context.progress(
                    n, len(materials), stage="准备固定研究材料", item=material["id"]
                )
            versions = self.versions_for_key(material["key"])
            found = None
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
                    )
                    found["artifact"] = str(artifact)
                    self.app.check_document(found, "parsed").verify()
                    self._remember(material["key"], found)
                    self._activate(material["key"], found)
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
                documents.append({**deepcopy(found), "_paper_id": material["paper_id"]})
            if context:
                context.record(
                    material["id"], "PREPARED" if found else "FAILED", document=found
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
        context=None,
    ) -> dict:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("请先输入科研目标")
        prepared = self.prepare(ids, include_si=include_si, context=context)
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
                "budget": budget or {"max_calls": 10, "max_cost": 2},
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
        transport=None,
    ) -> dict:
        if not consent:
            raise ProcessingError("explicit_planning_consent_required")
        prepared = self.prepare(ids, include_si=include_si)
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
        token = self.app.authorize("plan", request)
        return draft_task(self.app, request, authorization=token, transport=transport)

    def execute(self, task, *, consent=False, context=None, provider=None) -> dict:
        checked = self.app.validate_research_task(task)
        task = checked["task"]
        if task["mode"] != "local" and not consent:
            raise ProcessingError("explicit_research_consent_required")
        if context:
            context.checkpoint()
            context.progress(
                0,
                len(task["documents"]),
                stage="research",
                task_fingerprint=checked["task_fingerprint"],
            )
        token = self.app.authorize("execute", task) if task["mode"] != "local" else None
        self.app.current.context = context
        self.app.current.cancelled_at_boundary = False
        self.app.current.progress_count = 0
        self.app.current.progress_total = len(task["documents"])
        before = set((self.workspace / "research" / "runs").glob("*/manifest.json"))
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
                return {
                    "status": "CANCELLED",
                    "native_receipt": receipt,
                    "native_runs": runs,
                    "outputs": outputs,
                    "interruption_point": "completed_paper_boundary",
                    "notice": "已完成的调用与结果保留；取消只停止后续调度，不撤回已经完成或可能计费的请求。",
                }
            return receipt
        finally:
            self.app.current.context = None

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
        from aletheia_nexus.processing.contracts import digest

        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("Export display name must contain 1–200 characters")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")
        if slug != name or len(slug) > 64:
            slug = (slug[:40] or "export") + "-" + digest(name)[:12]
        report = self.app.export_research_results(paths, slug, formats)
        info = {
            "display_name": name,
            "directory_identifier": slug,
            "source_results": list(paths),
        }
        info_path = Path(report["directory"]) / "export-info.json"
        write_json(info_path, info)
        return {
            **report,
            "display_name": name,
            "outputs": [
                *(str(Path(report["directory"]) / p) for p in report["outputs"]),
                str(info_path),
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
