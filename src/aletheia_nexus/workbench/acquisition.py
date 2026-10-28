"""Local UI acquisition adapter over AN's existing trusted access engine.

The engine owns retrieval, identity verification, retries and checkpoints. This
adapter adds input preview, conservative title resolution and scheduling at paper
boundaries. It never invokes the CLI or converts an unverified PDF to VERIFIED.
"""

from __future__ import annotations

import csv
import inspect
import io
import json
import math
import re
import time
from dataclasses import asdict, fields, replace
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from aletheia_nexus.acquire.access.batch import acquire_full_text_batch_maximized
from aletheia_nexus.acquire.access.browser import BrowserSession
from aletheia_nexus.acquire.access.models import BrowserAccessConfig
from aletheia_nexus.acquire.access.service import acquire_full_text_maximized
from aletheia_nexus.acquire.metadata.crossref import CROSSREF_API, parse_crossref_work
from aletheia_nexus.acquire.metadata.exceptions import MetadataParseError
from aletheia_nexus.acquire.metadata.titles import contains_cjk
from aletheia_nexus.acquire.metadata.transport import get_json
from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.identifiers.doi import extract_dois, normalize_doi
from aletheia_nexus.core.organization import destination
from aletheia_nexus.core.paper_request import PaperRequest, compact_bibliography
from aletheia_nexus.core.urls import redact_url_for_record

_INPUT_FIELDS = {f.name for f in fields(PaperRequest)}
_PRIVATE_OPTIONS = {
    "doi",
    "output_dir",
    "browser_config",
    "browser_session",
    "elsevier_config",
    "expected_title",
    "local_pdf_path",
    "unpaywall_email",
    "openalex_api_key",
    "metadata_mailto",
}
_ACCESS_DEFAULTS = {
    name: parameter.default
    for name, parameter in inspect.signature(
        acquire_full_text_maximized
    ).parameters.items()
    if name not in _PRIVATE_OPTIONS and parameter.default is not inspect.Parameter.empty
}
_BROWSER_DEFAULTS = {
    f.name: getattr(BrowserAccessConfig(), f.name)
    for f in fields(BrowserAccessConfig)
    if f.name
    not in {"interaction_callback", "interaction_timeout", "wait_for_interaction"}
}
_EXTRA_DEFAULTS = {
    "browser_enabled": False,
    "include_si": True,
    "bulk_interval": 0.0,
    "max_item_attempts": 1,
    "retry_backoff": 1.0,
    "interaction_policy": "pause",
    "interaction_timeout": 180.0,
    "resume": True,
    "max_si_files": 20,
    "si_max_bytes": 100 * 1024 * 1024,
}


def get_acquisition_defaults() -> dict:
    """Actual supported engine parameters; credentials remain environment-only."""
    return {
        **_ACCESS_DEFAULTS,
        **_EXTRA_DEFAULTS,
        "public_only": True,
        "auto_official_api": False,
        "browser": dict(_BROWSER_DEFAULTS),
    }


def normalize_request(value) -> PaperRequest:
    if isinstance(value, PaperRequest):
        return value
    if isinstance(value, str):
        value = value.strip()
        try:
            return PaperRequest(doi=normalize_doi(value))
        except (ValueError, TypeError):
            return PaperRequest(title=value)
    if not isinstance(value, dict) or value.keys() - _INPUT_FIELDS:
        raise ValueError("paper fields: " + ", ".join(sorted(_INPUT_FIELDS)))
    payload = {k: v for k, v in value.items() if v is not None and v != ""}
    for key in ("authors", "tags"):
        if isinstance(payload.get(key), str):
            payload[key] = tuple(
                p.strip() for p in payload[key].split(";") if p.strip()
            )
        elif key in payload:
            payload[key] = tuple(payload[key])
    if isinstance(payload.get("year"), str):
        payload["year"] = int(payload["year"])
    return PaperRequest(**payload)


def _options(value: dict | None) -> dict:
    if value is not None and not isinstance(value, dict):
        raise ValueError("acquisition options must be an object")
    supplied = value or {}
    defaults = get_acquisition_defaults()
    if supplied.keys() - defaults.keys():
        raise ValueError(
            "unsupported acquisition options: "
            + ", ".join(sorted(supplied.keys() - defaults.keys()))
        )
    result = {**defaults, **supplied}
    browser = supplied.get("browser", {})
    if not isinstance(browser, dict) or browser.keys() - _BROWSER_DEFAULTS.keys():
        raise ValueError("unsupported browser options")
    result["browser"] = {**_BROWSER_DEFAULTS, **browser}
    if result["interaction_policy"] not in {"wait", "skip", "pause"}:
        raise ValueError("interaction_policy must be wait, skip or pause")
    if result["source_preference"] not in {"auto", "cnki", "exclude_cnki"}:
        raise ValueError("source_preference must be auto, cnki or exclude_cnki")
    for name, default in defaults.items():
        actual = result[name]
        if isinstance(default, bool) and type(actual) is not bool:
            raise ValueError(name + " must be boolean")
        if isinstance(default, (float, int)) and not isinstance(default, bool):
            if (
                isinstance(actual, bool)
                or not isinstance(actual, (int, float))
                or not math.isfinite(actual)
                or actual < 0
            ):
                raise ValueError(name + " must be a finite non-negative number")
            if isinstance(default, int) and type(actual) is not int:
                raise ValueError(name + " must be an integer")
    if (
        result["max_item_attempts"] < 1
        or result["max_si_files"] < 1
        or result["si_max_bytes"] < 1
    ):
        raise ValueError("item attempts and SI limits must be positive")
    if not result["browser_enabled"] and not result["public_only"]:
        raise ValueError(
            "disable public_only only after explicitly enabling browser access"
        )
    if result["public_only"] and result["source_preference"] == "cnki":
        raise ValueError(
            "CNKI requires the explicitly enabled institutional browser strategy"
        )
    if result["public_only"] and result["auto_official_api"]:
        raise ValueError(
            "official authenticated APIs require the full access strategy; public_only disables them"
        )
    return result


class AcquisitionService:
    def __init__(
        self, root: str | Path, state_dir: str | Path | None = None, library=None
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir = (
            Path(state_dir).resolve()
            if state_dir
            else self.root / ".an-workbench" / "acquisition"
        )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.library = library
        if library is not None and hasattr(library, "register_reference_adapter"):
            library.register_reference_adapter(
                self.state_dir, "aletheia-nexus/access-batch-checkpoint/v1"
            )
            library.register_reference_adapter(
                self.state_dir, "aletheia-nexus/acquisition-relocation/v1"
            )

    def _resume_locations(self, checkpoint: Path, prepared: list[PaperRequest]):
        """Rebind missing mutable checkpoint locators, preserving old evidence.

        Only the UI's explicitly registered library locator is consulted. Bytes,
        source-record hash, main role and DOI must all match, and the match must
        be unique. The original checkpoint is retained; a new lineage file holds
        the effective placement and is still revalidated by the core batch.
        """
        if not checkpoint.exists():
            return checkpoint, prepared, []
        payload = json.loads(checkpoint.read_text("utf-8"))
        if payload.get("schema") != "aletheia-nexus/access-batch-checkpoint/v1":
            raise ValueError("unsupported acquisition checkpoint schema")
        records = payload.get("records")
        if not isinstance(records, dict):
            raise ValueError("invalid acquisition checkpoint records")
        if self.library is None:
            return checkpoint, prepared, []
        rows = None
        relocations, effective = [], []
        for request in prepared:
            record = records.get(request.batch_key, {})
            old = record.get("verified_path")
            if record.get("status") != "VERIFIED" or not isinstance(old, str):
                effective.append(request)
                continue
            original = Path(old).resolve()
            if not original.is_relative_to(self.root):
                raise ValueError("checkpoint source outside library")
            if original.is_file():
                effective.append(request)
                continue
            if rows is None:
                rows = self.library.scan()["items"]
            matches = []
            for row in rows:
                if row.get("pdf_sha256") != record.get("sha256"):
                    continue
                target = Path(row["pdf_path"]).resolve()
                if not target.is_relative_to(self.root):
                    continue
                source_record = acquisition_sidecar_path(target).resolve()
                if not source_record.is_relative_to(self.root):
                    continue
                try:
                    checked = validate_parser_input(target, requested_doi=request.doi)
                    if (
                        checked.document_role == "ARTICLE"
                        and checked.identity_basis == "acquisition_verified"
                        and checked.pdf_sha256 == record.get("sha256")
                        and checked.sidecar_sha256 == record.get("sidecar_sha256")
                    ):
                        matches.append(checked)
                except (OSError, ValueError):
                    continue
            if len(matches) != 1:
                raise ValueError(
                    "checkpoint relocation requires one hash-and-source-verified library match"
                )
            checked = matches[0]
            folder = checked.pdf_path.parent.relative_to(self.root).as_posix()
            relocated = replace(request, folder=folder if folder != "." else None)
            updated = {**record, "verified_path": str(checked.pdf_path)}
            records[relocated.batch_key] = updated
            effective.append(relocated)
            relocations.append(
                {
                    "old_path": old,
                    "new_path": str(checked.pdf_path),
                    "pdf_sha256": checked.pdf_sha256,
                    "source_sha256": checked.sidecar_sha256,
                    "original_batch_key": request.batch_key,
                    "effective_batch_key": relocated.batch_key,
                }
            )
        if not relocations:
            return checkpoint, effective, []
        target = self.state_dir / (uuid4().hex + ".relocated.checkpoint.json")
        payload["relocation_source"] = {
            "path": str(checkpoint),
            "sha256": sha256_file(checkpoint),
            "items": relocations,
        }
        receipt = target.with_name(target.stem + ".relocation.json")
        with receipt.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "schema": "aletheia-nexus/acquisition-relocation/v1",
                    "source_checkpoint": str(checkpoint),
                    "source_checkpoint_sha256": sha256_file(checkpoint),
                    "effective_checkpoint": str(target),
                    "items": relocations,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
        payload["relocation_source"]["receipt"] = str(receipt)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return target, effective, relocations

    def _store_bibliography(self, item, source) -> dict | None:
        """Fill absent mutable bibliography using only this engine response.

        This neither changes the original title/DOI nor makes extra metadata
        requests. Existing researcher edits and acquisition evidence are retained.
        Per-field source receipts identify exactly which values were filled.
        """
        metadata = getattr(getattr(item.result, "base_result", None), "metadata", None)
        if metadata is None or self.library is None:
            return None
        if metadata.doi != source.doi:
            return {"status": "NOT_APPLIED", "reason": "metadata_doi_mismatch"}
        try:
            rows = [
                row
                for row in self.library.scan()["items"]
                if row["pdf_sha256"] == source.pdf_sha256
                and row["article_id"] == source.article_id
            ]
            if len(rows) != 1:
                return {
                    "status": "NOT_APPLIED",
                    "reason": "library_identity_not_unique",
                }
            row = rows[0]
            values = {}
            for name in (
                "authors",
                "year",
                "journal",
                "volume",
                "issue",
                "pages",
                "publisher",
                "published_date",
            ):
                value = getattr(metadata, name, None)
                if value and not (row.get(name) or row.get("metadata", {}).get(name)):
                    values[name] = list(value) if name == "authors" else value
            if not values:
                return {"status": "UNCHANGED", "doi": metadata.doi}
            sources = row.get("metadata", {}).get("metadata_source") or {}
            sources = dict(sources) if isinstance(sources, dict) else {}
            for name in values:
                sources[name] = {
                    "kind": "acquisition_engine_metadata",
                    "doi": metadata.doi,
                    "acquisition_sidecar_sha256": source.sidecar_sha256,
                }
            self.library.update_metadata(row["id"], **values, metadata_source=sources)
            return {
                "status": "UPDATED",
                "paper_id": row["id"],
                "fields": list(values),
                "doi": metadata.doi,
                "network_requests": 0,
            }
        except (OSError, ValueError, KeyError) as exc:
            # Bibliographic enrichment cannot demote an independently verified
            # PDF or prevent its SI attempt; the application exposes this error.
            return {"status": "FAILED", "error": type(exc).__name__}

    def preview_inputs(self, value, format: str | None = None) -> dict:
        """Normalize TXT/CSV/JSON or pasted citations; retain invalid-row diagnostics."""
        if isinstance(value, Path):
            format = format or value.suffix.lower().lstrip(".")
            value = value.read_text("utf-8-sig")
        if isinstance(value, str):
            if format == "json" or (
                format is None and value.lstrip().startswith(("[", "{"))
            ):
                value = json.loads(value)
                if isinstance(value, dict):
                    value = value.get("papers", [value])
            elif format == "csv":
                value = list(csv.DictReader(io.StringIO(value.lstrip("\ufeff"))))
            else:
                rows = []
                for line in value.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    dois = extract_dois(line)
                    # A bare list of DOIs can be comma-, tab- or space-separated.
                    if dois and all(
                        not p.strip(" ,;\t")
                        for p in re.split(
                            r"(?:https?://(?:dx\.)?doi\.org/)?10\.\d{4,9}/[^\s,;]+",
                            line,
                            flags=re.I,
                        )
                    ):
                        rows.extend(dois)
                    else:
                        rows.append(line)
                value = rows
        if not isinstance(value, (list, tuple)):
            raise ValueError("provide pasted lines or a TXT, CSV, JSON paper list")
        seen, items, errors = set(), [], []
        for index, row in enumerate(value, 1):
            try:
                request = normalize_request(row)
                duplicate = request.key in seen
                seen.add(request.key)
                items.append(
                    {
                        "id": request.key,
                        "request": asdict(request),
                        "duplicate": duplicate,
                        "line": index,
                    }
                )
            except (ValueError, TypeError) as exc:
                errors.append({"line": index, "error": str(exc)})
        return {"items": items, "errors": errors, "count": len(seen)}

    def resolve_title(self, request, *, limit=8, timeout=20.0, fetch=None) -> dict:
        """Search Crossref; only exact, unique, constraint-consistent titles auto-resolve.

        Similarity ranks candidates for human review, never selects the first hit.
        CJK titles retain AN's existing CNKI bibliographic identity route.
        """
        request = normalize_request(request)
        if request.doi:
            return {"status": "RESOLVED", "request": asdict(request), "candidates": []}
        if contains_cjk(request.title):
            return {
                "status": "CNKI_TITLE",
                "request": asdict(request),
                "candidates": [],
                "source": "CNKI",
            }
        if type(limit) is not int or not 1 <= limit <= 30:
            raise ValueError("title candidate limit must be 1..30")
        data = (fetch or get_json)(
            CROSSREF_API + "/works",
            context="Crossref title search",
            params={"query.title": request.title, "rows": limit},
            timeout=timeout,
        )
        works = data.get("message", {}).get("items")
        if not isinstance(works, list):
            raise ValueError("invalid Crossref title search response")
        candidates, seen = [], set()
        wanted = compact_bibliography(request.title)
        for work in works:
            try:
                metadata = parse_crossref_work(work)
            except (TypeError, ValueError, KeyError, MetadataParseError):
                continue
            if metadata.doi in seen or not metadata.title:
                continue
            seen.add(metadata.doi)
            conflicts = []
            if request.year and request.year != metadata.year:
                conflicts.append("year")
            if request.journal and compact_bibliography(
                request.journal
            ) != compact_bibliography(metadata.journal or ""):
                conflicts.append("journal")
            if request.authors and not all(
                any(
                    compact_bibliography(a) == compact_bibliography(b)
                    for b in metadata.authors
                )
                for a in request.authors
            ):
                conflicts.append("authors")
            observed = compact_bibliography(metadata.title)
            candidate = {
                "doi": metadata.doi,
                "title": metadata.title,
                "authors": list(metadata.authors),
                "year": metadata.year,
                "journal": metadata.journal,
                "source": "Crossref",
                "title_exact": wanted == observed,
                "similarity": round(SequenceMatcher(None, wanted, observed).ratio(), 4),
                "conflicts": conflicts,
            }
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                not item["conflicts"],
                item["title_exact"],
                item["similarity"],
            ),
            reverse=True,
        )
        reliable = [c for c in candidates if c["title_exact"] and not c["conflicts"]]
        # Multiple versions/records with identical titles still require a human.
        resolved = None
        if len(reliable) == 1:
            c = reliable[0]
            resolved = asdict(
                replace(
                    request,
                    doi=c["doi"],
                    title=c["title"],
                    authors=tuple(c["authors"]),
                    year=c["year"],
                    journal=c["journal"],
                )
            )
        return {
            "status": "RESOLVED"
            if resolved
            else "AMBIGUOUS"
            if candidates
            else "NOT_FOUND",
            "request": resolved,
            "candidates": candidates,
            "source": "Crossref",
            "pdf_acquired": False,
        }

    def run(self, requests, options=None, context=None, checkpoint_path=None) -> dict:
        """Run sequentially; UI control is effective at explicit paper boundaries.

        Browser interaction notifications use the task center's human decision.
        No thread is killed during a file transfer; cancellation is checked after
        the engine returns, so persisted files and provenance remain consistent.
        """
        options = _options(options)
        prepared = list(dict.fromkeys(normalize_request(r) for r in requests))
        if not prepared:
            raise ValueError("select at least one paper")
        for request in prepared:
            destination(self.root, request.folder)
            if (
                options["public_only"]
                and not request.doi
                and contains_cjk(request.title)
            ):
                raise ValueError(
                    "title-only CNKI acquisition requires the explicitly enabled institutional browser strategy"
                )
            if not request.doi and not contains_cjk(request.title):
                raise ValueError(
                    "resolve and confirm English title identity before acquisition"
                )
        checkpoint = (
            Path(checkpoint_path).resolve()
            if checkpoint_path
            else self.state_dir / (uuid4().hex + ".checkpoint.json")
        )
        if not checkpoint.is_relative_to(self.state_dir):
            raise ValueError("checkpoint must be inside acquisition state directory")
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint, prepared, relocations = self._resume_locations(checkpoint, prepared)
        if context:
            context.progress(
                0,
                len(prepared),
                stage="acquisition_prepared",
                checkpoint=str(checkpoint),
                relocations=relocations,
            )
        items = []
        current = None
        interaction_skipped = False

        def interaction(challenge, url):
            nonlocal interaction_skipped
            if context is None or options["interaction_policy"] == "skip":
                return
            decision = context.wait_interaction(
                {
                    "paper": asdict(current),
                    "source": redact_url_for_record(url),
                    "challenge": challenge.kind.value,
                    "stage": "browser_interaction",
                },
                timeout=options["interaction_timeout"] or None,
            )
            if decision == "skip":
                interaction_skipped = True
                # Raising leaves the engine's browser attempt through its normal
                # failure path; the adapter checks cancellation at the boundary.
                raise _SkipInteraction("user_skipped_interaction")

        browser_values = dict(options["browser"])
        browser_values.update(
            interaction_callback=interaction,
            interactive=options["interaction_policy"] != "skip"
            and browser_values["interactive"],
            wait_for_interaction=False,
            interaction_timeout=max(1.0, options["interaction_timeout"] or 180.0),
        )
        browser = BrowserAccessConfig(**browser_values)
        engine_options = {name: options[name] for name in _ACCESS_DEFAULTS}
        with BrowserSession(browser) as session:
            for index, current in enumerate(prepared, 1):
                interaction_skipped = False
                if context:
                    context.checkpoint()
                    if context.should_skip(current.key):
                        row = {
                            "id": current.key,
                            "status": "SKIPPED",
                            "request": asdict(current),
                        }
                        items.append(row)
                        context.record(
                            current.key, "SKIPPED", **{"request": asdict(current)}
                        )
                        continue
                    context.progress(
                        index - 1,
                        len(prepared),
                        stage="acquisition",
                        current=asdict(current),
                    )
                if index > 1 and options["bulk_interval"]:
                    deadline = time.monotonic() + options["bulk_interval"]
                    while time.monotonic() < deadline:
                        if context:
                            context.checkpoint()
                        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
                kwargs = {
                    "output_dir": self.root,
                    "checkpoint_path": checkpoint,
                    "resume": options["resume"],
                    "max_item_attempts": options["max_item_attempts"],
                    "retry_backoff": options["retry_backoff"],
                    **engine_options,
                }
                # Public-only ignores browser access exactly as the engine does.
                kwargs["browser_session"] = session
                result = acquire_full_text_batch_maximized([current], **kwargs)
                item = result.items[0]
                row = {
                    "id": current.key,
                    "request": asdict(current),
                    "status": item.status.value,
                    "attempts": item.attempts,
                    "resumed": item.resumed,
                    "elapsed_seconds": item.elapsed_seconds,
                    "error": item.error,
                    "si_status": "NOT_ATTEMPTED"
                    if options["include_si"]
                    else "NOT_REQUESTED",
                }
                if interaction_skipped or (
                    options["interaction_policy"] == "skip"
                    and row["status"] in {"INTERACTION_REQUIRED", "AUTH_REQUIRED"}
                ):
                    row.update(
                        status="SKIPPED",
                        acquisition_status=item.status.value,
                        reason="human_interaction_skipped",
                    )
                if item.verified_path:
                    if not Path(item.verified_path).resolve().is_relative_to(
                        self.root
                    ) or not acquisition_sidecar_path(
                        item.verified_path
                    ).resolve().is_relative_to(self.root):
                        raise ValueError("acquisition output outside library")
                    source = validate_parser_input(
                        item.verified_path, requested_doi=current.doi or item.doi
                    )
                    if (
                        source.document_role != "ARTICLE"
                        or source.identity_basis != "acquisition_verified"
                    ):
                        raise ValueError(
                            "acquisition engine returned an unverified main document"
                        )
                    row.update(
                        pdf=str(source.pdf_path),
                        sidecar=str(source.sidecar_path),
                        pdf_sha256=source.pdf_sha256,
                        identity_verified=True,
                    )
                    bibliography = self._store_bibliography(item, source)
                    if bibliography is not None:
                        row["bibliography"] = bibliography
                    if options["include_si"]:
                        from aletheia_nexus.workbench.supplements import (
                            acquire_supplements,
                        )

                        try:
                            si = acquire_supplements(
                                source.pdf_path,
                                library=self.library,
                                max_files=options["max_si_files"],
                                max_bytes=options["si_max_bytes"],
                                timeout=options["timeout"],
                            )
                            row.update(si_status=si["status"], supplements=si)
                        except Exception as exc:
                            # SI is independent: never rewrite successful main state.
                            row.update(si_status="FAILED", si_error=type(exc).__name__)
                items.append(row)
                if context:
                    context.record(
                        current.key,
                        row["status"],
                        **{k: v for k, v in row.items() if k not in {"id", "status"}},
                    )
                    context.progress(
                        index, len(prepared), item=row, stage="acquisition"
                    )
                    context.checkpoint()
                if row["status"] in {
                    "INTERACTION_REQUIRED",
                    "AUTH_REQUIRED",
                } and options["interaction_policy"] in {"pause", "wait"}:
                    if context:
                        context.wait_interaction(
                            {
                                "paper": asdict(current),
                                "stage": "paper_boundary",
                                "status": row["status"],
                                "resume_instruction": "当前论文未获取，继续只调度后续；可使用相同检查点重试当前项。",
                            },
                            timeout=options["interaction_timeout"] or None,
                        )
                    else:
                        return {
                            "status": "WAITING_INTERACTION",
                            "items": items,
                            "checkpoint": str(checkpoint),
                            "remaining": [asdict(p) for p in prepared[index:]],
                            "relocations": relocations,
                        }
        successes = sum(i["status"] == "VERIFIED" for i in items)
        return {
            "status": "COMPLETED"
            if successes == len(prepared)
            else "PARTIAL"
            if successes
            else "FAILED",
            "items": items,
            "checkpoint": str(checkpoint),
            "total": len(prepared),
            "success": successes,
            "network_access": True,
            "model_calls": 0,
            "relocations": relocations,
        }


class _SkipInteraction(RuntimeError):
    pass
