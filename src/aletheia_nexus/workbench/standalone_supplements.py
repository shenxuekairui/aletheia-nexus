"""DOI-linked attachments without a fabricated main PDF or parser identity."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aletheia_nexus.acquire.discovery import discover_openalex
from aletheia_nexus.acquire.fulltext.pmc_cloud import _pmc_ids, _version_prefixes
from aletheia_nexus.acquire.metadata import get_metadata
from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.urls import redact_url_for_record

from .supplement_repositories import _title
from .supplements import (
    _retrieve_official_file,
    _write_new_json,
    discover_supplement_candidates,
    validate_downloaded_attachment,
)

SCHEMA = "aletheia-nexus/standalone-attachment-source/v1"
ROOT = Path("SI") / "independent"
ROLES = {"SUPPLEMENT", "SOURCE_DATA", "REPORTING_SUMMARY", "PEER_REVIEW"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(doi, role, source_hash, digest):
    return (
        "si_"
        + hashlib.sha256(f"{doi}:{role}:{source_hash}:{digest}".encode()).hexdigest()[
            :24
        ]
    )


def _redact(value):
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return redact_url_for_record(value)
    return value


class StandaloneSupplementService:
    def __init__(self, library):
        self.library = library

    def _entry(self, record):
        record = self.library.path(record, existing=True)
        base = self.library.path(ROOT)
        if not record.is_relative_to(base):
            raise ValueError("standalone receipt is outside its storage directory")
        data = json.loads(record.read_text("utf-8"))
        if data.get("schema") != SCHEMA or data.get("association_status") != "DOI_ONLY":
            raise ValueError("invalid standalone receipt")
        doi = normalize_doi(data.get("doi"))
        if record.parent.name != hashlib.sha256(doi.encode()).hexdigest()[:16]:
            raise ValueError("standalone receipt DOI directory mismatch")
        name = data.get("file_name")
        if not isinstance(name, str) or Path(name).name != name or "\\" in name:
            raise ValueError("invalid standalone filename")
        path = self.library.path(record.parent / name, existing=True)
        if data.get("role") not in ROLES or sha256_file(path) != data.get("sha256"):
            raise ValueError("standalone file hash or role mismatch")
        expected = _id(doi, data["role"], data["source_url_sha256"], data["sha256"])
        if data.get("id") != expected or record.name != expected + ".standalone.json":
            raise ValueError("standalone receipt identity mismatch")
        return {
            "id": expected,
            "doi": doi,
            "title": data.get("title"),
            "role": data["role"],
            "path": str(path),
            "filename": name,
            "sha256": data["sha256"],
            "source_record": str(record),
            "source_record_sha256": sha256_file(record),
            "association_status": "DOI_ONLY",
            "parseable": False,
            "size_bytes": path.stat().st_size,
            "record": data,
        }

    def list(self, *, pending_only=False):
        base = self.library.path(ROOT)
        items, warnings = [], []
        if not base.exists():
            return {"items": [], "warnings": [], "pending": 0}
        state = self.library._load()
        bindings = {}
        for value in state.get("attachments", {}).values():
            for identifier in value.get("standalone_ids", []):
                bindings.setdefault(identifier, []).append(value["parent_id"])
        for record in sorted(base.glob("*/*.standalone.json")):
            try:
                item = self._entry(record)
                item.pop("record")
                item["bound_paper_ids"] = bindings.get(item["id"], [])
                if not pending_only or not item["bound_paper_ids"]:
                    items.append(item)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(
                    {"source_record": str(record), "error": type(exc).__name__}
                )
        return {
            "items": items,
            "warnings": warnings,
            "pending": sum(not item["bound_paper_ids"] for item in items),
        }

    def get(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(
            r"si_[0-9a-f]{24}", identifier
        ):
            raise ValueError("invalid standalone attachment ID")
        records = list(
            self.library.path(ROOT).glob("*/" + identifier + ".standalone.json")
        )
        if len(records) != 1:
            raise ValueError("standalone attachment is missing or ambiguous")
        return self._entry(records[0])

    def _pmc_prefix(self, doi, timeout):
        ids = _pmc_ids(discover_openalex(doi, timeout=timeout))
        if not ids:
            return None
        if len(ids) != 1:
            raise ValueError("ambiguous PMC identity for independent SI")
        prefixes = _version_prefixes(ids[0], timeout=timeout)
        return max(prefixes, key=lambda prefix: int(prefix.rsplit(".", 1)[1]))

    def acquire(
        self,
        doi,
        *,
        title=None,
        max_files=20,
        max_bytes=100 * 1024**2,
        timeout=30.0,
        include_peer_review=False,
        context=None,
        metadata_lookup=None,
        page_fetch=None,
        file_fetch=None,
        pmc_lookup=None,
    ):
        doi = normalize_doi(doi)
        self.library.path(ROOT)
        if type(max_files) is not int or not 1 <= max_files <= 100:
            raise ValueError("SI file limit must be 1..100")
        if (
            type(max_bytes) is not int
            or max_bytes < 1
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("SI byte limit and timeout must be positive")
        if type(include_peer_review) is not bool:
            raise ValueError("include_peer_review must be boolean")
        diagnostics, metadata, items = [], None, []
        try:
            model = (metadata_lookup or get_metadata)(doi)
            metadata = asdict(model)
            if normalize_doi(model.doi) != doi:
                raise ValueError("DOI metadata identity mismatch")
            if title and model.title and _title(title) != _title(model.title):
                raise ValueError("requested SI title conflicts with DOI metadata")
            title = model.title or title
            metadata = {
                key: metadata.get(key)
                for key in ["doi", "title", "authors", "journal", "year", "publisher"]
            }
        except ValueError:
            raise
        except Exception as exc:
            diagnostics.append(
                {"status": "METADATA_UNAVAILABLE", "error": type(exc).__name__}
            )
        prefix = None
        try:
            prefix = (pmc_lookup or self._pmc_prefix)(doi, timeout)
        except Exception as exc:
            diagnostics.append(
                {"status": "PMC_LOOKUP_UNAVAILABLE", "error": type(exc).__name__}
            )
        discovery = discover_supplement_candidates(
            doi=doi,
            title=title,
            pmc_version_prefix=prefix,
            timeout=timeout,
            max_bytes=max_bytes,
            page_fetch=page_fetch,
        )
        diagnostics.extend(discovery["diagnostics"])
        all_candidates = discovery["items"]
        candidates = [
            item
            for item in all_candidates
            if include_peer_review or item["role"] != "PEER_REVIEW"
        ]
        if len(candidates) != len(all_candidates):
            diagnostics.append(
                {
                    "status": "PEER_REVIEW_EXCLUDED",
                    "count": len(all_candidates) - len(candidates),
                }
            )
        errors = discovery["errors"]
        cached = self.list()
        diagnostics.extend(cached["warnings"])
        by_url = {
            (item["record"]["source_url_sha256"], item["role"]): item
            for row in cached["items"]
            for item in [self.get(row["id"])]
        }
        directory = self.library.path(
            ROOT / hashlib.sha256(doi.encode()).hexdigest()[:16]
        )
        for attachment in candidates[:max_files]:
            if context is not None:
                context.checkpoint()
            source_hash = hashlib.sha256(attachment["url"].encode()).hexdigest()
            previous = by_url.get((source_hash, attachment["role"]))
            if previous:
                if (
                    attachment.get("expected_size") is not None
                    and previous["size_bytes"] != attachment["expected_size"]
                ):
                    previous = None
                elif attachment.get("expected_md5"):
                    with Path(previous["path"]).open("rb") as stream:
                        if (
                            hashlib.file_digest(stream, "md5").hexdigest()
                            != attachment["expected_md5"]
                        ):
                            previous = None
            if previous and previous["doi"] == doi:
                previous.pop("record")
                items.append({**previous, "status": "REUSED"})
                continue
            resource, staged_receipt = None, None
            file_diagnostics = []
            try:
                directory.mkdir(parents=True, exist_ok=True)
                fetch = file_fetch or _retrieve_official_file
                kwargs = dict(
                    output_dir=directory, max_bytes=max_bytes, timeout=timeout
                )
                if file_fetch is None:
                    kwargs.update(
                        source_page=attachment["page"],
                        attachment=attachment,
                        diagnostics=file_diagnostics,
                    )
                resource = fetch(attachment["url"], **kwargs)
                validation = validate_downloaded_attachment(
                    resource,
                    attachment,
                    max_bytes=max_bytes,
                    diagnostics=file_diagnostics,
                )
                if sha256_file(resource.local_path) != resource.sha256:
                    raise ValueError("attachment transport hash mismatch")
                identifier = _id(doi, attachment["role"], source_hash, resource.sha256)
                stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title or doi).strip(" .")[
                    :55
                ]
                name = f"{stem}__{attachment['role']}-{identifier[-8:]}{attachment['extension']}"
                target = self.library.path(directory / name)
                record = self.library.path(
                    directory / (identifier + ".standalone.json")
                )
                if len(str(target)) > 240:
                    raise ValueError("standalone SI path exceeds 240 characters")
                payload = {
                    "schema": SCHEMA,
                    "id": identifier,
                    "doi": doi,
                    "title": title,
                    "association_status": "DOI_ONLY",
                    "main_pdf": None,
                    "role": attachment["role"],
                    "sha256": resource.sha256,
                    "file_name": name,
                    "acquired_at": _now(),
                    "metadata": metadata,
                    "source_page": redact_url_for_record(attachment["page"]),
                    "source_url": redact_url_for_record(attachment["url"]),
                    "source_url_sha256": source_hash,
                    "final_url": redact_url_for_record(resource.final_url),
                    "link_label": attachment.get("label"),
                    "association_basis": attachment.get(
                        "association_basis",
                        "sole_scholarly_DOI_on_official_page_and_explicit_attachment_link",
                    ),
                    "association_evidence": _redact(attachment.get("evidence")),
                    "repository_provenance": discovery["repository_provenance"],
                    "validation": {**validation, "parser_ready": False},
                    "transport": "http",
                    "transport_diagnostics": file_diagnostics,
                    "limits": {"max_bytes": max_bytes},
                }
                staged_receipt = directory / ("." + uuid4().hex + ".receipt.part")
                _write_new_json(staged_receipt, payload)
                with self.library._locked():
                    if record.exists():
                        existing = self._entry(record)
                        existing.pop("record")
                        items.append({**existing, "status": "REUSED"})
                    else:
                        self.library._publish_import(
                            [(resource.local_path, target), (staged_receipt, record)]
                        )
                        saved = self._entry(record)
                        saved.pop("record")
                        items.append({**saved, "status": "SAVED"})
            except Exception as exc:
                items.append(
                    {
                        "status": "FAILED",
                        "role": attachment["role"],
                        "source_url": redact_url_for_record(attachment["url"]),
                        "error": type(exc).__name__,
                        "diagnostics": file_diagnostics,
                    }
                )
            finally:
                if resource is not None:
                    resource.local_path.unlink(missing_ok=True)
                if staged_receipt is not None:
                    staged_receipt.unlink(missing_ok=True)
        saved = sum(item["status"] in {"SAVED", "REUSED"} for item in items)
        truncated = discovery["truncated"] or len(candidates) > max_files
        return {
            "status": "COMPLETED"
            if saved and saved == len(items) and not errors and not truncated
            else "PARTIAL"
            if saved
            else "INTERACTION_REQUIRED"
            if any(error.get("status") == "INTERACTION_REQUIRED" for error in errors)
            else "FAILED"
            if items or errors
            else "NOT_FOUND",
            "doi": doi,
            "title": title,
            "items": items,
            "errors": errors,
            "diagnostics": diagnostics,
            "truncated": truncated,
            "discovered": len(candidates),
            "si_directory": str(directory) if directory.exists() else None,
            "association_status": "DOI_ONLY",
            "main_status": "NOT_REQUESTED",
            "si_count": sum(
                item["status"] in {"SAVED", "REUSED"} and item["role"] == "SUPPLEMENT"
                for item in items
            ),
        }

    def acquire_many(self, requests, *, context=None, **options):
        from .acquisition import normalize_request

        prepared = list(dict.fromkeys(normalize_request(value) for value in requests))
        if not prepared or any(not request.doi for request in prepared):
            raise ValueError("独立获取 SI 需要每篇论文的 DOI；请先核对输入。")
        items = []
        for index, request in enumerate(prepared, 1):
            if context is not None:
                context.checkpoint()
                context.progress(
                    index - 1,
                    len(prepared),
                    stage="单独获取 SI",
                    current={"doi": request.doi},
                )
            try:
                result = self.acquire(
                    request.doi, title=request.title, context=context, **options
                )
            except Exception as exc:
                from .jobs import TaskCancelled

                if isinstance(exc, TaskCancelled):
                    raise
                result = {
                    "status": "FAILED",
                    "doi": request.doi,
                    "items": [],
                    "error": type(exc).__name__,
                }
            result.update(main_status="NOT_REQUESTED", association_status="DOI_ONLY")
            items.append(result)
            if context is not None:
                context.record(request.doi, result["status"], result=result)
                context.progress(index, len(prepared), stage="单独获取 SI", item=result)
        complete = sum(item["status"] == "COMPLETED" for item in items)
        saved = any(
            entry["status"] in {"SAVED", "REUSED"}
            for row in items
            for entry in row["items"]
        )
        return {
            "status": "COMPLETED"
            if complete == len(items)
            else "PARTIAL"
            if saved
            else "FAILED",
            "items": items,
            "main_status": "NOT_REQUESTED",
            "network_access": True,
            "model_calls": 0,
        }

    def bind(self, main_pdf, identifiers=None):
        main_path = self.library.path(main_pdf, existing=True)
        main = validate_parser_input(main_path)
        if main.document_role != "ARTICLE" or not main.doi:
            raise ValueError("select a registered main article with DOI")
        paper = next(
            (
                row
                for row in self.library.scan()["items"]
                if row["pdf_path"] == str(main_path)
            ),
            None,
        )
        if paper is None:
            raise ValueError("main article is not in the selected library")
        entries = (
            [self.get(identifier) for identifier in identifiers]
            if identifiers is not None
            else [
                self.get(item["id"])
                for item in self.list()["items"]
                if item["doi"] == main.doi
            ]
        )
        for entry in entries:
            self.validate_parent(entry, main)
        items = [
            self.library.import_attachment(
                paper["id"],
                entry["path"],
                role=entry["role"],
                title=entry["title"],
                standalone_id=entry["id"],
            )
            for entry in entries
        ]
        return {
            "status": "COMPLETED" if items else "NOT_FOUND",
            "items": items,
            "main_unchanged": True,
        }

    @staticmethod
    def validate_parent(entry, main):
        if entry["doi"] != main.doi or (
            entry.get("title")
            and main.title
            and _title(entry["title"]) != _title(main.title)
        ):
            raise ValueError(
                "standalone attachment DOI/title does not match the selected main article"
            )
