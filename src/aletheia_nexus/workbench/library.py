"""Mutable local library metadata and journalled, identity-preserving file changes.

Acquisition records and parsed artifacts remain immutable.  The registry is a
locator, never an assertion that an unverified file is a verified paper.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from string import Formatter
from threading import RLock
from uuid import uuid4

from aletheia_nexus.acquire.fulltext.storage import is_verified_record
from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import (
    acquisition_sidecar_path,
    find_json_path,
    json_output_path,
)
from aletheia_nexus.core.organization import destination, filename_stem
from aletheia_nexus.library import scan_library, update_tags

SCHEMA = "aletheia-nexus/workbench-library/v1"
TEMPLATES = {
    "原始标题": "{title_original}",
    "中文译名": "{title_zh}",
    "年份-中文译名": "{year}-{title_zh}",
    "年份-期刊-中文译名": "{year}-{journal}-{title_zh}",
    "第一作者-年份-中文译名": "{first_author}-{year}-{title_zh}",
}
FIELDS = frozenset(
    {"year", "journal", "first_author", "title_original", "title_zh", "custom_name"}
)
DEFAULT_VIEWS = {
    "标准文献视图": {
        "columns": [
            "title",
            "title_zh",
            "first_author",
            "year",
            "journal",
            "tags",
            "si_count",
            "parse_status",
        ]
    },
    "文件整理视图": {
        "columns": [
            "title",
            "custom_name",
            "filename",
            "folder",
            "path",
            "size",
            "si_count",
        ]
    },
    "获取管理视图": {
        "columns": [
            "title",
            "doi",
            "integrity",
            "download_source",
            "download_time",
            "si_count",
        ]
    },
    "科研处理视图": {
        "columns": [
            "title",
            "tags",
            "collections",
            "parse_status",
            "reading_status",
            "research_tasks",
        ]
    },
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".part")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".part")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _key(path: Path) -> str:
    # Explicitly case-fold on Linux as well; plans must remain portable to Windows.
    return str(path.absolute()).replace("\\", "/").casefold()


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


class LibraryService:
    """One explicitly selected library root; persistent state is local JSON.

    ``reference_roots`` are additional task/checkpoint directories to audit before
    physical moves. Unknown references outside these roots cannot be audited.
    """

    def __init__(self, root, state_dir=None, *, reference_roots=()):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir = Path(state_dir or self.root / ".an-workbench").resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "library.json"
        self.reference_roots = tuple(Path(p).resolve() for p in reference_roots)
        self._lock = RLock()
        self._catalog = None
        self._catalog_fingerprint = None
        self._source_payloads = {}
        self._file_stats = {}
        self._last_rows = {}
        self._last_row_stats = {}
        self._last_attachments = {}
        if self.state_path.is_symlink() or self.state_dir.is_symlink():
            raise ValueError("library state must not be a symbolic link")

    def path(self, value, *, existing=False):
        candidate = Path(value)
        candidate = candidate if candidate.is_absolute() else self.root / candidate
        # Reject links, including links that resolve back into the permitted root.
        for part in (candidate, *candidate.parents):
            if part.is_symlink() or (
                hasattr(part, "is_junction") and part.is_junction()
            ):
                raise ValueError("symbolic links are not permitted for library files")
            if part == self.root:
                break
        target = candidate.resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("path is outside the selected library")
        if existing and not target.is_file():
            raise FileNotFoundError(target)
        return target

    def _relative(self, value):
        return self.path(value).relative_to(self.root).as_posix()

    def _load(self):
        if not self.state_path.exists():
            return {
                "schema": SCHEMA,
                "papers": {},
                "attachments": {},
                "selection": [],
                "collections": {},
                "filters": {},
                "views": deepcopy(DEFAULT_VIEWS),
                "tag_groups": {},
                "templates": deepcopy(TEMPLATES),
                "reference_adapters": [],
            }
        state = _read(self.state_path)
        if state.get("schema") != SCHEMA:
            raise ValueError("unsupported library registry schema")
        return state

    @contextmanager
    def _locked(self):
        with self._lock:
            lock_path = self.state_dir / "library.lock"
            if lock_path.is_symlink():
                raise ValueError("library lock must not be a symbolic link")
            handle = lock_path.open("a+b")
            try:
                if handle.seek(0, 2) == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
            finally:
                handle.close()

    def _source_payload(self, path):
        path = Path(path)
        stat = self._file_stats.get(str(path))
        if stat is None:
            current = path.stat()
            stat = (current.st_mtime_ns, current.st_size, current.st_ino)
        cached = self._source_payloads.get(str(path))
        if cached is None or cached[0] != stat:
            cached = (stat, _read(path), sha256_file(path))
            self._source_payloads[str(path)] = cached
        return cached[1], cached[2]

    def _id(self, row):
        payload, source_hash = self._source_payload(row["sidecar_path"])
        material = payload["retrieval"]["sha256"] + ":" + source_hash
        return "paper_" + hashlib.sha256(material.encode()).hexdigest()[:24]

    def _source_fingerprint(self):
        """Stat source files; reuse checked rows until file identity/stat changes.

        Mutations and parsing always recheck hashes independently. The cache keeps
        changing metadata or a table selection from rereading hundreds of PDFs.
        """
        entries = []
        for sidecar in sorted(self.root.rglob("*.acquisition.json")):
            if sidecar.is_relative_to(self.state_dir):
                continue
            pdf = sidecar.with_name(
                sidecar.name.removesuffix(".acquisition.json") + ".pdf"
            )
            if sidecar.parent.name == "json" and not pdf.exists():
                pdf = sidecar.parent.parent / pdf.name
            labels = find_json_path(pdf.with_suffix(".library.json"))
            for path in (sidecar, pdf, labels):
                try:
                    stat = path.stat()
                    self._file_stats[str(path)] = (
                        stat.st_mtime_ns,
                        stat.st_size,
                        stat.st_ino,
                    )
                    entries.append(
                        (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino)
                    )
                except OSError:
                    self._file_stats[str(path)] = None
                    entries.append((str(path), None))
        return tuple(entries)

    def scan(
        self,
        *,
        query=None,
        folder=None,
        tags=(),
        tag_mode="AND",
        ids=None,
        parsed=None,
        untranslated=False,
        collection=None,
        refresh=False,
        **_,
    ):
        """Return paper rows; supplements are nested and never counted as papers.

        Existing sidecar scanning is reused and does not load parsed PDF contents.
        Content hashes are checked by the existing scanner; no filename identity.
        """
        with self._locked():
            state = self._load()
            fingerprint = self._source_fingerprint()
            catalog_changed = (
                refresh
                or self._catalog is None
                or fingerprint != self._catalog_fingerprint
            )
            if refresh:
                self._source_payloads.clear()
            if catalog_changed:
                self._catalog = scan_library(self.root)
                self._catalog_fingerprint = fingerprint
            result = deepcopy(self._catalog)
            rows, supplements = [], []
            changed = False
            preferred_locations = {
                paper_id: info.get("pdf") for paper_id, info in state["papers"].items()
            }
            for row in result["items"]:
                try:
                    if catalog_changed:
                        self.path(row["pdf_path"])
                        self.path(row["sidecar_path"], existing=True)
                    if Path(row["pdf_path"]).is_relative_to(self.state_dir):
                        continue
                    if row["document_role"] != "ARTICLE":
                        supplements.append(row)
                        continue
                    paper_id = self._id(row)
                    stored = state["papers"].setdefault(
                        paper_id, {"metadata": {}, "aliases": []}
                    )
                    source, _ = self._source_payload(row["sidecar_path"])
                    meta = stored.get("metadata", {})
                    target = source.get("target", {})
                    org = source.get("organization", {})
                    authors = (
                        meta.get("authors")
                        or target.get("authors")
                        or org.get("authors")
                        or []
                    )
                    if isinstance(authors, str):
                        authors = [authors]
                    first = authors[0] if authors else ""
                    if isinstance(first, dict):
                        first = (
                            first.get("name")
                            or " ".join(
                                str(first.get(k) or "") for k in ("given", "family")
                            ).strip()
                        )
                    path = Path(row["pdf_path"])
                    rows.append(
                        {
                            **row,
                            "id": paper_id,
                            "title_original": row["title"],
                            "title_zh": meta.get("title_zh", ""),
                            "translation": deepcopy(meta.get("translation", {})),
                            "custom_name": meta.get("custom_name", ""),
                            "metadata": deepcopy(meta),
                            "authors": authors,
                            "first_author": first,
                            "year": meta.get("year")
                            or target.get("year")
                            or org.get("year")
                            or "",
                            "journal": meta.get("journal")
                            or target.get("journal")
                            or org.get("journal")
                            or "",
                            "filename": path.name,
                            "path": str(path),
                            "size": path.stat().st_size if path.is_file() else None,
                            "pdf_sha256": source["retrieval"]["sha256"],
                            "article_id": target.get("article_id")
                            or (
                                "doi:" + row["doi"]
                                if row["doi"]
                                else "an:source:sha256:" + source["retrieval"]["sha256"]
                            ),
                            "download_source": source.get("retrieval", {}).get(
                                "final_url"
                            )
                            or source.get("retrieval", {}).get("url")
                            or source.get("retrieval", {}).get("transport", ""),
                            "download_time": source.get("retrieval", {}).get(
                                "retrieved_at"
                            )
                            or source.get("retrieved_at")
                            or source.get("created_at")
                            or "",
                            "parse_status": meta.get("parse_status", "UNPARSED"),
                            "ocr_status": meta.get("ocr_status", "UNKNOWN"),
                            "reading_status": meta.get("reading_status", "未读"),
                            "research_tasks": meta.get("research_tasks", []),
                            "collections": [
                                name
                                for name, members in state["collections"].items()
                                if paper_id in members
                            ],
                            "attachments": [],
                        }
                    )
                except (OSError, ValueError, KeyError) as exc:
                    result["warnings"].append(
                        {"sidecar": row["sidecar_path"], "error": str(exc)}
                    )
            # Byte-identical, identically declared copies have one stable paper
            # identity. Keep a deterministic locator and expose every extra copy
            # instead of giving AG Grid repeated row IDs or double-counting papers.
            grouped = {}
            for row in rows:
                grouped.setdefault(row["id"], []).append(row)
            rows = []
            for paper_id, copies in grouped.items():
                preferred = preferred_locations.get(paper_id)
                chosen = next(
                    (
                        row
                        for row in copies
                        if Path(row["pdf_path"]).relative_to(self.root).as_posix()
                        == preferred
                    ),
                    copies[0],
                )
                chosen["duplicate_paths"] = [
                    row["pdf_path"] for row in copies if row is not chosen
                ]
                if chosen["duplicate_paths"]:
                    result["warnings"].append(
                        {
                            "paper_id": paper_id,
                            "error": "identical source copies share one paper identity",
                            "paths": chosen["duplicate_paths"],
                        }
                    )
                if (
                    state["papers"][paper_id].get("pdf")
                    != Path(chosen["pdf_path"]).relative_to(self.root).as_posix()
                ):
                    changed = True
                state["papers"][paper_id].update(
                    pdf=Path(chosen["pdf_path"]).relative_to(self.root).as_posix(),
                    sidecar=Path(chosen["sidecar_path"])
                    .relative_to(self.root)
                    .as_posix(),
                )
                rows.append(chosen)
            # Explicit registry ownership has priority across the entire library,
            # not merely within the row being rendered. A legacy parent record
            # lacks the main sidecar hash and cannot distinguish two declarations
            # of identical PDF bytes. Never infer which declaration owns its SI.
            explicit_paths = {
                _key(self.path(info["path"])) for info in state["attachments"].values()
            }
            legacy_by_parent = {row["id"]: [] for row in rows}
            for supplement in supplements:
                if _key(Path(supplement["pdf_path"])) in explicit_paths:
                    continue
                parent = supplement.get("parent") or {}
                matches = [
                    row["id"]
                    for row in rows
                    if parent.get("pdf_sha256") == row["pdf_sha256"]
                    and parent.get("article_id") == row["article_id"]
                ]
                if len(matches) == 1:
                    legacy_by_parent[matches[0]].append(supplement)
                else:
                    result["warnings"].append(
                        {
                            "sidecar": supplement["sidecar_path"],
                            "attachment_path": supplement["pdf_path"],
                            "candidate_ids": matches,
                            "error": "旧 SI 父文身份存在歧义，未自动关联；请从正确正文详情明确登记此附件。"
                            if matches
                            else "旧 SI 在当前文库中找不到对应父文，未自动关联；请恢复正文或明确检查父文身份。",
                        }
                    )
            for row in rows:
                attached = {}
                for attachment_id, info in state["attachments"].items():
                    if info.get("parent_id") == row["id"]:
                        item = deepcopy(info)
                        item["id"] = attachment_id
                        item["path"] = str(self.path(info["path"]))
                        item["pdf_path"] = (
                            item["path"]
                            if Path(item["path"]).suffix.lower() == ".pdf"
                            else None
                        )
                        if item.get("sidecar"):
                            item["sidecar_path"] = str(self.path(item["sidecar"]))
                        item["exists"] = Path(item["path"]).is_file()
                        if isinstance(info.get("source"), str):
                            try:
                                source_receipt = self.path(info["source"])
                                item["source_status"] = (
                                    "PRESENT" if source_receipt.is_file() else "MISSING"
                                )
                            except ValueError:
                                item["source_status"] = "UNSAFE"
                            if item["source_status"] != "PRESENT":
                                result["warnings"].append(
                                    {
                                        "sidecar": info["source"],
                                        "paper_id": row["id"],
                                        "attachment_path": item["path"],
                                        "error": "附件的独立来源记录缺失或路径不安全。请恢复原始来源记录；正文状态保持独立，不会因此降级或伪造附件来源。",
                                    }
                                )
                        attached[info["sha256"] + ":" + info["role"]] = item
                for supplement in legacy_by_parent[row["id"]]:
                    path = Path(supplement["pdf_path"])
                    supplement_source, _ = self._source_payload(
                        supplement["sidecar_path"]
                    )
                    digest = supplement_source["retrieval"]["sha256"]
                    attached.setdefault(
                        digest + ":SUPPLEMENT",
                        {
                            "id": "attachment_" + digest[:24],
                            "path": str(path),
                            "pdf_path": str(path),
                            "sidecar_path": supplement["sidecar_path"],
                            "role": "SUPPLEMENT",
                            "sha256": digest,
                            "exists": path.is_file(),
                            "identity_basis": "local_declared",
                        },
                    )
                row["attachments"] = list(attached.values())
                row["si_count"] = sum(
                    a["role"] == "SUPPLEMENT" for a in attached.values()
                )
            if changed:
                _write(self.state_path, state)
            self._last_rows = {row["id"]: deepcopy(row) for row in rows}
            self._last_row_stats = {
                row["id"]: {
                    path: self._file_stats.get(path)
                    for path in (
                        row["pdf_path"],
                        row["sidecar_path"],
                        str(
                            find_json_path(
                                Path(row["pdf_path"]).with_suffix(".library.json")
                            )
                        ),
                    )
                }
                for row in rows
            }
            self._last_attachments = deepcopy(state["attachments"])
            filtered = []
            selected_ids = set(ids) if ids is not None else None
            if collection:
                members = set(state["collections"].get(collection, []))
                selected_ids = (
                    members if selected_ids is None else selected_ids & members
                )
            for row in rows:
                if selected_ids is not None and row["id"] not in selected_ids:
                    continue
                if folder and not (
                    row["folder"] == folder or row["folder"].startswith(folder + "/")
                ):
                    continue
                if tags:
                    checks = [tag in row["tags"] for tag in tags]
                    if not (all(checks) if tag_mode.upper() == "AND" else any(checks)):
                        continue
                if parsed is not None:
                    if type(parsed) is bool:
                        if (row["parse_status"] in {"PARSED", "PARTIAL"}) != parsed:
                            continue
                    elif parsed in {"PARSED", "PARTIAL", "FAILED", "UNPARSED"}:
                        if row["parse_status"] != parsed:
                            continue
                    else:
                        raise ValueError(
                            "解析状态筛选无效，请选择完成、部分、失败或尚未解析"
                        )
                if untranslated and row["title_zh"]:
                    continue
                if (
                    query
                    and query.casefold()
                    not in " ".join(
                        str(row.get(k) or "")
                        for k in (
                            "title",
                            "title_zh",
                            "custom_name",
                            "doi",
                            "filename",
                            "tags",
                        )
                    ).casefold()
                ):
                    continue
                filtered.append(row)
            return {
                "root": str(self.root),
                "items": filtered,
                "warnings": result["warnings"],
                "total": len(rows),
                "filtered": len(filtered),
            }

    def get(self, paper_id):
        # Per-title translation and selection actions must not rescan every PDF.
        # A row cache only serves metadata; file mutations and research material
        # loading always perform their own full source/hash validation.
        with self._locked():
            state = self._load()
            cached = self._last_rows.get(paper_id)
            stored = state["papers"].get(paper_id)
            valid = bool(cached and stored)
            if valid:
                valid = (
                    str(self.root / stored["pdf"]) == cached["pdf_path"]
                    and state["attachments"] == self._last_attachments
                )
            if valid:
                for path, expected in self._last_row_stats.get(paper_id, {}).items():
                    try:
                        stat = Path(path).stat()
                        actual = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
                    except OSError:
                        actual = None
                    if actual != expected:
                        valid = False
                        break
            if valid:
                row = deepcopy(cached)
                meta = deepcopy(stored.get("metadata", {}))
                source, _ = self._source_payload(row["sidecar_path"])
                target, org = source.get("target", {}), source.get("organization", {})
                authors = (
                    meta.get("authors")
                    or target.get("authors")
                    or org.get("authors")
                    or []
                )
                if isinstance(authors, str):
                    authors = [authors]
                first = authors[0] if authors else ""
                if isinstance(first, dict):
                    first = (
                        first.get("name")
                        or " ".join(
                            str(first.get(k) or "") for k in ("given", "family")
                        ).strip()
                    )
                row.update(
                    metadata=meta,
                    title_zh=meta.get("title_zh", ""),
                    translation=deepcopy(meta.get("translation", {})),
                    custom_name=meta.get("custom_name", ""),
                    authors=authors,
                    first_author=first,
                    year=meta.get("year")
                    or target.get("year")
                    or org.get("year")
                    or "",
                    journal=meta.get("journal")
                    or target.get("journal")
                    or org.get("journal")
                    or "",
                    parse_status=meta.get("parse_status", "UNPARSED"),
                    ocr_status=meta.get("ocr_status", "UNKNOWN"),
                    reading_status=meta.get("reading_status", "未读"),
                    research_tasks=deepcopy(meta.get("research_tasks", [])),
                    collections=[
                        name
                        for name, members in state["collections"].items()
                        if paper_id in members
                    ],
                )
                for attachment in row["attachments"]:
                    attachment["exists"] = Path(attachment["path"]).is_file()
                return row
        return next((r for r in self.scan()["items"] if r["id"] == paper_id), None)

    def update_metadata(self, paper_id, **fields):
        if any(
            k in fields
            for k in ("title", "title_original", "doi", "pdf_sha256", "article_id")
        ):
            raise ValueError("original bibliographic identity is immutable")
        json.dumps(fields, allow_nan=False)
        with self._locked():
            state = self._load()
            if paper_id not in state["papers"]:
                raise KeyError(paper_id)
            meta = state["papers"][paper_id]["metadata"]
            old_translation = meta.get("translation") or {}
            new_translation = fields.get("translation") or {}
            if (
                (
                    old_translation.get("confirmed")
                    or old_translation.get("source") == "manual"
                )
                and "title_zh" in fields
                and fields["title_zh"] != meta.get("title_zh")
            ):
                if (
                    not new_translation.get("confirmed")
                    and new_translation.get("source") != "manual"
                ):
                    raise ValueError(
                        "a confirmed/manual translation requires explicit manual replacement"
                    )
            meta.update(deepcopy(fields))
            meta["updated_at"] = _now()
            _write(self.state_path, state)
            return deepcopy(meta)

    def update_tags(self, ids, *, add=(), remove=()):
        result = {}
        by_id = {r["id"]: r for r in self.scan()["items"]}
        for paper_id in dict.fromkeys(ids):
            row = by_id.get(paper_id)
            if row is None:
                raise KeyError(paper_id)
            result[paper_id] = update_tags(
                self.path(row["pdf_path"], existing=True), add=add, remove=remove
            )
        return result

    @staticmethod
    def _tag(value):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > 80
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("tags must be non-empty labels of at most 80 characters")
        return value.strip()

    def rename_tag(self, old, new):
        """Rename a free tag everywhere in mutable library organization only."""
        return self._change_tag(self._tag(old), self._tag(new))

    def delete_tag(self, tag):
        """Remove a tag from papers, optional groups and saved tag filters."""
        return self._change_tag(self._tag(tag), None)

    def _change_tag(self, old, new):
        rows = [row for row in self.scan()["items"] if old in row["tags"]]
        with self._locked():
            state = self._load()
            replacements = []
            groups, filters = [], []
            for row in rows:
                pdf = self.path(row["pdf_path"], existing=True)
                validate_parser_input(pdf, sidecar_path=row["sidecar_path"])
                label = self.path(json_output_path(pdf.with_suffix(".library.json")))
                replacements.append(
                    (pdf, label, label.read_bytes() if label.exists() else None)
                )
            updated = deepcopy(state)
            for name, tags in updated["tag_groups"].items():
                if old in tags:
                    updated["tag_groups"][name] = list(
                        dict.fromkeys(
                            (new if t == old else t)
                            for t in tags
                            if t != old or new is not None
                        )
                    )
                    groups.append(name)
            for name, rules in updated["filters"].items():
                if old in rules.get("tags", []):
                    rules["tags"] = list(
                        dict.fromkeys(
                            (new if t == old else t)
                            for t in rules["tags"]
                            if t != old or new is not None
                        )
                    )
                    filters.append(name)
            try:
                for pdf, _, _ in replacements:
                    update_tags(
                        pdf,
                        add=[new] if new and new != old else [],
                        remove=[old] if new != old else [],
                    )
                _write(self.state_path, updated)
            except Exception:
                for _, label, content in replacements:
                    if content is None:
                        label.unlink(missing_ok=True)
                    else:
                        _write_bytes(label, content)
                raise
        return {
            "status": "COMPLETED",
            "operation": "rename_tag" if new else "delete_tag",
            "old": old,
            "new": new,
            "papers": [row["id"] for row in rows],
            "paper_count": len(rows),
            "groups_changed": groups,
            "filters_changed": filters,
            "warning": "Deleting a tag condition may broaden a saved filter; historical research tasks retain their original snapshots."
            if new is None and filters
            else None,
        }

    def import_pdf(self, path, *, title=None, folder="", doi=None, tags=()):
        supplied = Path(path).expanduser()
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in (supplied, *supplied.parents)
        ):
            raise ValueError("source PDF must not be a symbolic link")
        source = supplied.resolve(strict=True)
        if source.suffix.lower() != ".pdf":
            raise ValueError("select a PDF")
        tags = [self._tag(tag) for tag in tags]
        source_sidecar = acquisition_sidecar_path(source)
        gated = None
        import_warnings = []
        if source_sidecar.exists() or source_sidecar.is_symlink():
            if source_sidecar.is_symlink():
                raise ValueError("source records must not be symbolic links")
            gated = validate_parser_input(
                source, requested_doi=doi, sidecar_path=source_sidecar
            )
            if (
                gated.identity_basis == "acquisition_verified"
                and not is_verified_record(_read(source_sidecar))
            ):
                raise ValueError(
                    "existing acquisition evidence is incomplete; import cannot promote or replace it"
                )
            if gated.document_role != "ARTICLE":
                raise ValueError(
                    "known SUPPLEMENT cannot be imported as an ARTICLE; use import_attachment(parent_id, path) to associate it explicitly"
                )
            if title and title.strip() != gated.title:
                import_warnings.append(
                    "Existing source title retained; the supplied title was not used to overwrite bibliographic evidence. Edit the custom display name after import."
                )
        target_dir = destination(self.root, folder or None)
        self.path(target_dir)
        digest = sha256_file(source)
        for row in self.scan()["items"]:
            same_identity = (
                gated
                and row["id"]
                == "paper_"
                + hashlib.sha256(
                    (digest + ":" + gated.sidecar_sha256).encode()
                ).hexdigest()[:24]
            ) or (
                not gated
                and row["pdf_sha256"] == digest
                and row["title_original"] == (title or source.stem)
            )
            if same_identity:
                if tags:
                    self.update_tags([row["id"]], add=tags)
                return {
                    **self.get(row["id"]),
                    "import_status": "ALREADY_PRESENT",
                    "import_warnings": import_warnings,
                }
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = filename_stem(source.stem)
        target = target_dir / (stem + ".pdf")
        # Same bytes with a new declaration must not overwrite a prior identity.
        if target.exists() and (
            sha256_file(target) != digest or acquisition_sidecar_path(target).exists()
        ):
            identity_suffix = (
                gated.sidecar_sha256
                if gated
                else hashlib.sha256((title or source.stem).encode()).hexdigest()
            )[:8]
            target = target_dir / (stem + "--" + digest[:10] + identity_suffix + ".pdf")
        if target.exists() or acquisition_sidecar_path(target).exists():
            for row in self.scan()["items"]:
                if row["pdf_sha256"] == digest and row["pdf_path"] == str(target):
                    return row
            raise FileExistsError(target)
        # register_local_pdf preserves the input name, so prepare a bounded staging name.
        staging = self.state_dir / "imports" / uuid4().hex
        staging.mkdir(parents=True)
        prepared = staging / target.name
        try:
            shutil.copyfile(source, prepared)
            if sha256_file(prepared) != digest:
                raise ValueError("PDF changed while copying")
            if gated:
                staged_record = json_output_path(
                    prepared.with_suffix(".acquisition.json")
                )
                staged_record.parent.mkdir(parents=True)
                shutil.copyfile(source_sidecar, staged_record)
                if sha256_file(staged_record) != gated.sidecar_sha256:
                    raise ValueError("source record changed while copying")
                pairs = [
                    (prepared, target),
                    (
                        staged_record,
                        json_output_path(target.with_suffix(".acquisition.json")),
                    ),
                ]
                old_labels = find_json_path(source.with_suffix(".library.json"))
                if old_labels.exists():
                    if old_labels.is_symlink():
                        raise ValueError("source labels must not be symbolic links")
                    staged_labels = staging / "labels.json"
                    shutil.copyfile(old_labels, staged_labels)
                    pairs.append(
                        (
                            staged_labels,
                            json_output_path(target.with_suffix(".library.json")),
                        )
                    )
                with self._locked():
                    self._publish_import(pairs)
                registered = target
            else:
                register_local_pdf(
                    prepared, output_dir=staging, title=title or source.stem, doi=doi
                )
                with self._locked():
                    self._publish_import(
                        [
                            (prepared, target),
                            (
                                acquisition_sidecar_path(prepared),
                                json_output_path(
                                    target.with_suffix(".acquisition.json")
                                ),
                            ),
                        ]
                    )
                registered = target
            if tags:
                update_tags(registered, add=tags)
        finally:
            for child in sorted(
                staging.rglob("*"), key=lambda p: len(p.parts), reverse=True
            ):
                if child.is_dir():
                    child.rmdir()
                else:
                    child.unlink(missing_ok=True)
            staging.rmdir()
        result = next(
            row for row in self.scan()["items"] if row["pdf_path"] == str(registered)
        )
        return {**result, "import_warnings": import_warnings}

    def _publish_import(self, pairs):
        """Publish complete staging files exclusively, removing only owned copies on failure."""
        created = []
        try:
            for source, target in pairs:
                source, target = Path(source), self.path(target)
                digest = sha256_file(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or any(
                    _key(p) == _key(target) for p in target.parent.iterdir()
                ):
                    raise FileExistsError(target)
                os.link(source, target)
                created.append((target, digest))
                if sha256_file(target) != digest:
                    raise ValueError("import changed during publication")
            return created
        except Exception:
            for path, digest in reversed(created):
                if path.is_file() and sha256_file(path) == digest:
                    path.unlink()
            raise

    def import_attachment(self, parent_id, path, *, role="SUPPLEMENT", title=None):
        """Explicitly associate a user-selected local file; never infer a parent.

        PDF SI is locally DECLARED, never acquisition VERIFIED. Other attachment
        types are validated and stored without opening, extraction or parsing.
        """
        from .supplements import _SUFFIXES, _validate_attachment

        if role not in {
            "SUPPLEMENT",
            "SOURCE_DATA",
            "REPORTING_SUMMARY",
            "PEER_REVIEW",
            "OTHER",
        }:
            raise ValueError("unsupported attachment role")
        supplied = Path(path).expanduser()
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in (supplied, *supplied.parents)
        ):
            raise ValueError("attachment source must not be a symbolic link")
        source = supplied.resolve(strict=True)
        suffix = source.suffix.lower()
        if suffix not in _SUFFIXES:
            raise ValueError(
                "unsupported local attachment extension; executable and active HTML files are not accepted"
            )
        if source.stat().st_size > 200 * 1024 * 1024:
            raise ValueError("local attachment exceeds the 200 MiB limit")
        parent = self.get(parent_id)
        if not parent:
            raise ValueError("select an existing parent paper")
        main = validate_parser_input(
            parent["pdf_path"], sidecar_path=parent["sidecar_path"]
        )
        validation = _validate_attachment(source, suffix)
        digest = sha256_file(source)
        if digest == main.pdf_sha256:
            raise ValueError(
                "the main article cannot be imported as its own attachment"
            )
        existing_record = acquisition_sidecar_path(source) if suffix == ".pdf" else None
        declared = None
        if existing_record and (
            existing_record.exists() or existing_record.is_symlink()
        ):
            if existing_record.is_symlink():
                raise ValueError("source record must not be a symbolic link")
            declared = validate_parser_input(source, sidecar_path=existing_record)
            if (
                declared.document_role != "SUPPLEMENT"
                or not declared.parent
                or declared.parent.get("pdf_sha256") != main.pdf_sha256
                or declared.parent.get("article_id") != main.article_id
            ):
                raise ValueError(
                    "existing source evidence declares another parent or an ARTICLE; it cannot be relabelled"
                )
        for attachment in parent["attachments"]:
            if attachment["sha256"] == digest and attachment["role"] == role:
                target = self.path(attachment["path"], existing=True)
                if sha256_file(target) != digest:
                    raise ValueError(
                        "existing attachment changed; restore it before reimport"
                    )
                return {**attachment, "import_status": "ALREADY_PRESENT"}
        staging = self.state_dir / "imports" / uuid4().hex
        staging.mkdir(parents=True)
        prepared = staging / ("attachment" + suffix)
        created = []
        try:
            shutil.copyfile(source, prepared)
            if sha256_file(prepared) != digest:
                raise ValueError("attachment source changed while copying")
            if suffix == ".pdf" and (role == "SUPPLEMENT" or declared):
                if declared:
                    sidecar = json_output_path(
                        prepared.with_suffix(".acquisition.json")
                    )
                    sidecar.parent.mkdir()
                    shutil.copyfile(existing_record, sidecar)
                    if sha256_file(sidecar) != declared.sidecar_sha256:
                        raise ValueError(
                            "attachment source evidence changed while copying"
                        )
                else:
                    register_local_pdf(
                        prepared,
                        output_dir=staging,
                        title=title
                        or f"{main.title or main.article_id} — Supplementary Information",
                        role="SUPPLEMENT",
                        parent_pdf=main.pdf_path,
                        parent_sidecar=main.sidecar_path,
                    )
            receipt = {
                "schema": "aletheia-nexus/local-attachment/v1",
                "status": "REGISTERED",
                "created_at": _now(),
                "role": role,
                "sha256": digest,
                "association_basis": "explicit_user_selected_parent",
                "identity_status": "DECLARED",
                "original_filename": source.name,
                "title": title or source.stem,
                "parent": {
                    "paper_id": parent_id,
                    "article_id": main.article_id,
                    "pdf_sha256": main.pdf_sha256,
                    "sidecar_sha256": main.sidecar_sha256,
                },
                "validation": {
                    **validation,
                    "parseable": suffix == ".pdf" and role == "SUPPLEMENT",
                },
                "network_access": False,
            }
            staged_receipt = staging / "receipt.json"
            _write(staged_receipt, receipt)
            with self._locked():
                state = self._load()
                if state["papers"].get(parent_id, {}).get("pdf") != self._relative(
                    main.pdf_path
                ):
                    raise ValueError(
                        "parent moved during attachment preparation; retry with its new location"
                    )
                validate_parser_input(main.pdf_path, sidecar_path=main.sidecar_path)
                directory = self.path(main.pdf_path.parent / "SI")
                directory.mkdir(exist_ok=True)
                label = "SI" if role == "SUPPLEMENT" else role
                number = 1
                while True:
                    prefix = f"{main.pdf_path.stem}__{label}-{number:02d}"
                    target = (
                        directory
                        / f"{main.pdf_path.stem}__{label}-{number:02d}{suffix}"
                    )
                    record = directory / "json" / (target.name + ".attachment.json")
                    sidecar = json_output_path(target.with_suffix(".acquisition.json"))
                    if (
                        not target.exists()
                        and not record.exists()
                        and not sidecar.exists()
                        and not any(
                            p.name.casefold().startswith((prefix + ".").casefold())
                            for p in directory.iterdir()
                        )
                    ):
                        break
                    number += 1
                if len(str(target)) > 240:
                    raise ValueError(
                        "attachment target exceeds the portable 240-character path limit"
                    )
                pairs = [(prepared, target), (staged_receipt, record)]
                staged_sidecar = acquisition_sidecar_path(prepared)
                if staged_sidecar.exists():
                    pairs.append((staged_sidecar, sidecar))
                created = self._publish_import(pairs)
                attachment_id = (
                    "attachment_"
                    + hashlib.sha256(
                        (parent_id + ":" + digest + ":" + role).encode()
                    ).hexdigest()[:24]
                )
                info = {
                    "parent_id": parent_id,
                    "parent_sha256": main.pdf_sha256,
                    "path": self._relative(target),
                    "sha256": digest,
                    "role": role,
                    "sidecar": self._relative(sidecar)
                    if staged_sidecar.exists()
                    else None,
                    "source": str(record),
                    "registered_at": _now(),
                }
                state["attachments"][attachment_id] = info
                _write(self.state_path, state)
            return next(
                a
                for a in self.get(parent_id)["attachments"]
                if a["id"] == attachment_id
            )
        except Exception:
            for owned, expected in reversed(created):
                if owned.is_file() and sha256_file(owned) == expected:
                    owned.unlink()
            raise
        finally:
            for child in sorted(
                staging.rglob("*"), key=lambda p: len(p.parts), reverse=True
            ):
                if child.is_dir():
                    child.rmdir()
                else:
                    child.unlink(missing_ok=True)
            staging.rmdir()

    def register_attachment(
        self, main_pdf, path, *, role="SUPPLEMENT", source_record=None
    ):
        if role not in {
            "SUPPLEMENT",
            "SOURCE_DATA",
            "REPORTING_SUMMARY",
            "PEER_REVIEW",
            "OTHER",
        }:
            raise ValueError("unsupported attachment role")
        main_pdf, path = (
            self.path(main_pdf, existing=True),
            self.path(path, existing=True),
        )
        main = next(
            (r for r in self.scan()["items"] if Path(r["pdf_path"]) == main_pdf), None
        )
        if main is None:
            raise ValueError("attachment parent must be a registered main article")
        if path.parent != main_pdf.parent / "SI":
            raise ValueError(
                "attachments must be in the parent category's shared SI directory"
            )
        if path == main_pdf:
            raise ValueError("an article cannot be its own attachment")
        digest = sha256_file(path)
        sidecar = (
            acquisition_sidecar_path(path) if path.suffix.lower() == ".pdf" else None
        )
        if sidecar and sidecar.exists():
            gated = validate_parser_input(path, sidecar_path=sidecar)
            if (
                gated.document_role != "SUPPLEMENT"
                or not gated.parent
                or gated.parent.get("pdf_sha256") != main["pdf_sha256"]
                or gated.parent.get("article_id") != main["article_id"]
            ):
                raise ValueError(
                    "attachment source record has a different parent or role"
                )
        if isinstance(source_record, (str, Path)):
            source_record = str(self.path(source_record, existing=True))
        identity = main["id"] + ":" + digest + ":" + role
        attachment_id = (
            "attachment_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        )
        with self._locked():
            state = self._load()
            if any(
                _key(self.path(existing["path"])) == _key(path)
                and existing.get("parent_id") != main["id"]
                for existing in state["attachments"].values()
            ):
                raise ValueError(
                    "该附件路径已明确归属另一篇论文，不能重复登记到不同父文；请保留原关联并选择正确附件。"
                )
            info = {
                "parent_id": main["id"],
                "parent_sha256": main["pdf_sha256"],
                "path": self._relative(path),
                "sha256": digest,
                "role": role,
                "sidecar": self._relative(sidecar)
                if sidecar and sidecar.exists()
                else None,
                "source": deepcopy(source_record),
                "registered_at": _now(),
            }
            state["attachments"][attachment_id] = info
            _write(self.state_path, state)
            return {"id": attachment_id, **deepcopy(info)}

    def _section(self, name):
        with self._locked():
            return deepcopy(self._load()[name])

    def selection(self):
        return self._section("selection")

    def set_selection(self, ids, *, mode="replace"):
        known = {r["id"] for r in self.scan()["items"]}
        ids = list(dict.fromkeys(ids))
        if not set(ids) <= known:
            raise ValueError("selection contains unknown paper identities")
        with self._locked():
            state = self._load()
            if mode == "replace":
                state["selection"] = ids
            elif mode == "add":
                state["selection"] = list(dict.fromkeys([*state["selection"], *ids]))
            elif mode == "remove":
                state["selection"] = [i for i in state["selection"] if i not in ids]
            else:
                raise ValueError("invalid selection mode")
            _write(self.state_path, state)
            return deepcopy(state["selection"])

    def _save_named(self, section, name, value):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("provide a name of at most 100 characters")
        json.dumps(value, allow_nan=False)
        with self._locked():
            state = self._load()
            state[section][name.strip()] = deepcopy(value)
            _write(self.state_path, state)
        return deepcopy(value)

    def delete_named(self, section, name):
        if section not in {
            "collections",
            "filters",
            "views",
            "tag_groups",
            "templates",
        }:
            raise ValueError("invalid named library section")
        with self._locked():
            state = self._load()
            state[section].pop(name, None)
            _write(self.state_path, state)

    def collections(self):
        return self._section("collections")

    def save_collection(self, name, ids):
        known = {r["id"] for r in self.scan()["items"]}
        if not set(ids) <= known:
            raise ValueError("collection contains unknown papers")
        return self._save_named("collections", name, list(dict.fromkeys(ids)))

    def filters(self):
        return self._section("filters")

    def save_filter(self, name, rules):
        allowed = {
            "query",
            "folder",
            "tags",
            "tag_mode",
            "ids",
            "parsed",
            "untranslated",
            "collection",
        }
        if not isinstance(rules, dict) or set(rules) - allowed:
            raise ValueError("unsupported filter rules")
        return self._save_named("filters", name, rules)

    def views(self):
        return self._section("views")

    def save_view(self, name, config):
        if not isinstance(config, dict) or not isinstance(config.get("columns"), list):
            raise ValueError("view requires a column list")
        return self._save_named("views", name, config)

    def tag_groups(self):
        return self._section("tag_groups")

    def save_tag_group(self, name, tags):
        if any(not isinstance(t, str) or not t.strip() or len(t) > 80 for t in tags):
            raise ValueError("invalid tag group")
        return self._save_named("tag_groups", name, list(dict.fromkeys(tags)))

    def templates(self):
        return self._section("templates")

    @staticmethod
    def _check_template(template):
        if not isinstance(template, str) or len(template) > 500:
            raise ValueError("invalid filename template")
        used = []
        for _, field, spec, conversion in Formatter().parse(template):
            if field is not None:
                if field not in FIELDS or spec or conversion:
                    raise ValueError("filename template contains an unsupported field")
                used.append(field)
        return used

    def save_template(self, name, template):
        self._check_template(template)
        return self._save_named("templates", name, template)

    def register_reference_adapter(self, directory, schema):
        """Declare a service that revalidates old locators by immutable hashes.

        This is used by the UI acquisition adapter, not a blanket exemption for
        arbitrary CLI task/checkpoint files. Old evidence is never rewritten.
        """
        if schema not in {
            "aletheia-nexus/access-batch-checkpoint/v1",
            "aletheia-nexus/acquisition-relocation/v1",
        }:
            raise ValueError("unsupported reference adapter")
        directory = Path(directory).resolve()
        if not any(
            directory.is_relative_to(root)
            for root in (self.root, self.state_dir, *self.reference_roots)
        ):
            raise ValueError("reference adapter directory is outside authorized roots")
        adapter = {"directory": str(directory), "schema": schema}
        with self._locked():
            state = self._load()
            adapters = state.setdefault("reference_adapters", [])
            if adapter not in adapters:
                adapters.append(adapter)
                _write(self.state_path, state)
        return adapter

    def _reference_risks(self, paths):
        """Existing parsed artifacts relocate by hash; explicit task paths may not.

        This deliberately rejects unsafe legacy references instead of rewriting
        contracts, checkpoints or immutable scientific provenance.
        """
        keys = {_key(Path(p)) for p in paths}
        risks = []
        seen = set()
        adapters = self._load().get("reference_adapters", [])
        for root in (self.root, *self.reference_roots):
            if not root.is_dir():
                continue
            for path in root.rglob("*.json"):
                if (
                    path in seen
                    or path.is_symlink()
                    or path == self.state_path
                    or path.is_relative_to(self.state_dir / "operations")
                ):
                    continue
                seen.add(path)
                if path.name.endswith(
                    (".parsed.json", ".acquisition.json", ".library.json")
                ):
                    continue
                try:
                    if path.stat().st_size > 20 * 1024 * 1024:
                        risks.append(str(path) + ": too large to audit")
                        continue
                    value = _read(path)
                    if (
                        isinstance(value, dict)
                        and value.get("schema") == "aletheia-nexus/workbench-task/v1"
                    ):
                        # UI history paths are diagnostic. Resumable inputs are
                        # stable library IDs or separately audited native tasks;
                        # scientific materials live in immutable workspace copies.
                        continue
                    if isinstance(value, dict) and any(
                        value.get("schema") == adapter["schema"]
                        and path.is_relative_to(Path(adapter["directory"]))
                        for adapter in adapters
                    ):
                        continue
                    for item in _strings(value):
                        if len(item) > 2000 or "\n" in item:
                            continue
                        possible = Path(item)
                        candidates = (
                            [possible]
                            if possible.is_absolute()
                            else [path.parent / possible, root / possible]
                        )
                        if any(_key(p.resolve()) in keys for p in candidates):
                            risks.append(str(path))
                            break
                except (OSError, ValueError):
                    # Unreadable task/checkpoint files may contain needed references.
                    if any(
                        s in path.name.casefold()
                        for s in ("task", "manifest", "checkpoint")
                    ):
                        risks.append(str(path) + ": unreadable reference record")
        return sorted(set(risks))

    def preview_rename(
        self,
        ids,
        template,
        *,
        folder=None,
        overrides=None,
        missing_translation="fallback",
        move_to_root=False,
    ):
        used = self._check_template(template)
        if type(move_to_root) is not bool or (move_to_root and folder):
            raise ValueError(
                "移动目标冲突：请选择文库根目录，或指定一个分类，不要同时设置"
            )
        if missing_translation not in {"fallback", "skip"}:
            raise ValueError("missing translation policy must be fallback or skip")
        overrides = overrides or {}
        by_id = {r["id"]: r for r in self.scan()["items"]}
        rows = []
        for paper_id in dict.fromkeys(ids):
            row = by_id.get(paper_id)
            if row is None:
                rows.append(
                    {
                        "id": paper_id,
                        "status": "SKIP",
                        "errors": ["unknown paper identity"],
                        "moves": [],
                    }
                )
                continue
            target_dir = (
                self.root
                if move_to_root
                else destination(
                    self.root, folder if folder else (row["folder"] or None)
                )
            )
            self.path(target_dir)
            values = {key: str(row.get(key) or "") for key in FIELDS}
            missing = [key for key in used if not values[key]]
            errors, warnings = [], []
            if "title_zh" in missing:
                if missing_translation == "skip" and not overrides.get(paper_id):
                    errors.append(
                        "missing Chinese translation; translate here or choose original-title fallback"
                    )
                else:
                    values["title_zh"] = values["title_original"]
            raw_stem = overrides.get(paper_id) or template.format_map(values)
            stem = filename_stem(raw_stem)
            if stem != raw_stem.strip(" ."):
                warnings.append(
                    "illegal characters, whitespace or long name normalized"
                )
            if not raw_stem.strip(" -_."):
                errors.append("filename has no available metadata")
            translation = row["metadata"].get("translation") or {}
            rows.append(
                {
                    "id": paper_id,
                    "title": row["title"],
                    "old_path": row["pdf_path"],
                    "new_name": stem + ".pdf",
                    "base_name": stem,
                    "target_folder": target_dir.relative_to(self.root).as_posix(),
                    "si_directory": str(target_dir / "SI"),
                    "missing_metadata": missing,
                    "translation_source": "confirmed"
                    if translation.get("confirmed")
                    else translation.get(
                        "source",
                        "cached" if row["title_zh"] else "original_title_fallback",
                    ),
                    "warnings": warnings,
                    "errors": errors,
                    "moves": [],
                    "attachments": deepcopy(row["attachments"]),
                    "status": "READY",
                    "_row": row,
                    "_target": str(target_dir),
                }
            )
        groups = Counter(
            (_key(Path(r["_target"])), r["base_name"].casefold())
            for r in rows
            if "_target" in r
        )
        source_keys = {_key(Path(r["old_path"])) for r in rows if "old_path" in r}
        for item in rows:
            if "_row" not in item:
                continue
            row = item.pop("_row")
            target_dir = Path(item.pop("_target"))
            stem = item["base_name"]
            target = target_dir / (stem + ".pdf")
            existing_names = (
                {_key(p): p for p in target_dir.iterdir()}
                if target_dir.exists()
                else {}
            )
            if groups[(_key(target_dir), stem.casefold())] > 1 or (
                _key(target) in existing_names and _key(target) not in source_keys
            ):
                stem = (
                    filename_stem(stem) + "--" + item["id"].removeprefix("paper_")[:8]
                )
                target = target_dir / (stem + ".pdf")
                item["warnings"].append(
                    "stable identity suffix added to disambiguate filename"
                )
            item.update(base_name=stem, new_name=target.name, new_path=str(target))
            pairs = [(Path(row["pdf_path"]), target, "ARTICLE")]
            for index, attachment in enumerate(row["attachments"], 1):
                original = Path(attachment["path"])
                # Preserve actual suffixes, including .tar.gz, without a fabricated extension.
                suffix = (
                    "".join(original.suffixes[-2:])
                    if original.name.lower().endswith(
                        (".tar.gz", ".tar.bz2", ".tar.xz")
                    )
                    else original.suffix
                )
                role = (
                    "SI" if attachment["role"] == "SUPPLEMENT" else attachment["role"]
                )
                pairs.append(
                    (
                        original,
                        target_dir / "SI" / f"{stem}__{role}-{index:02d}{suffix}",
                        attachment["role"],
                    )
                )
            for original, final, role in pairs:
                if original == final:
                    continue
                try:
                    self.path(original, existing=True)
                    self.path(final)
                    file_hash = sha256_file(original)
                    if role == "ARTICLE" and file_hash != row["pdf_sha256"]:
                        raise ValueError("main PDF hash does not match source evidence")
                    if role != "ARTICLE":
                        expected = next(
                            a["sha256"]
                            for a in row["attachments"]
                            if Path(a["path"]) == original
                        )
                        if file_hash != expected:
                            raise ValueError(
                                "attachment hash does not match its registry"
                            )
                    item["moves"].append(
                        {
                            "source": str(original),
                            "target": str(final),
                            "sha256": file_hash,
                            "role": role,
                        }
                    )
                    if original.suffix.lower() == ".pdf":
                        sidecar = acquisition_sidecar_path(original)
                        if sidecar.exists():
                            validate_parser_input(original, sidecar_path=sidecar)
                            new_sidecar = json_output_path(
                                final.with_suffix(".acquisition.json")
                            )
                            item["moves"].append(
                                {
                                    "source": str(sidecar),
                                    "target": str(new_sidecar),
                                    "sha256": sha256_file(sidecar),
                                    "role": "SOURCE_RECORD",
                                }
                            )
                        labels = find_json_path(original.with_suffix(".library.json"))
                        if labels.exists():
                            item["moves"].append(
                                {
                                    "source": str(labels),
                                    "target": str(
                                        json_output_path(
                                            final.with_suffix(".library.json")
                                        )
                                    ),
                                    "sha256": sha256_file(labels),
                                    "role": "LABELS",
                                }
                            )
                    if len(str(final)) > 240:
                        item["errors"].append(
                            "target path exceeds the portable 240-character limit"
                        )
                except (OSError, ValueError) as exc:
                    item["errors"].append(str(exc))
            if item["moves"]:
                risks = self._reference_risks(
                    [move["source"] for move in item["moves"]]
                )
                if risks:
                    item["errors"].append(
                        "legacy explicit references require review: "
                        + ", ".join(risks[:8])
                    )
                    item["reference_risks"] = risks
            if item["errors"]:
                item["status"] = "SKIP"
        # Do not allow a plan to overwrite a different paper, even if it too moves.
        targets = Counter(
            _key(Path(m["target"]))
            for r in rows
            if r["status"] == "READY"
            for m in r["moves"]
        )
        for item in rows:
            for move in item["moves"]:
                final = Path(move["target"])
                conflict = targets[_key(final)] > 1
                if final.parent.exists():
                    collision = next(
                        (p for p in final.parent.iterdir() if _key(p) == _key(final)),
                        None,
                    )
                    if collision and _key(collision) != _key(Path(move["source"])):
                        conflict = True
                if conflict:
                    item["errors"].append(
                        "target already exists or is duplicated: " + str(final)
                    )
                    item["status"] = "SKIP"
        preview = {
            "schema": "aletheia-nexus/rename-preview/v1",
            "created_at": _now(),
            "root": str(self.root),
            "template": template,
            "move_to_root": move_to_root,
            "items": rows,
            "executable": sum(r["status"] == "READY" for r in rows),
            "skipped": sum(r["status"] != "READY" for r in rows),
            "reference_roots": [str(p) for p in self.reference_roots],
        }
        preview["fingerprint"] = hashlib.sha256(
            json.dumps(preview, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return preview

    def _journal_path(self, operation_id):
        if (
            not isinstance(operation_id, str)
            or not operation_id.startswith("rename_")
            or not operation_id[7:].isalnum()
        ):
            raise ValueError("invalid operation ID")
        return self.state_dir / "operations" / (operation_id + ".json")

    def operations(self):
        directory = self.state_dir / "operations"
        if not directory.exists():
            return []
        with self._locked():
            results = []
            for path in sorted(directory.glob("rename_*.json"), reverse=True):
                journal = _read(path)
                # Acquiring the same OS lock proves no file operation owns it.
                # A durable RUNNING journal therefore came from an interrupted
                # process, and must never keep claiming an active operation.
                if journal.get("status") == "RUNNING":
                    journal["status"] = "ROLLBACK_REQUIRED"
                    journal.setdefault("errors", []).append(
                        "file operation owner exited before completion"
                    )
                    _write(path, journal)
                results.append(journal)
            return sorted(
                results, key=lambda item: item.get("created_at") or "", reverse=True
            )

    def execute_rename(self, preview):
        """Execute an unchanged preflight; stage files and roll back on any failure.

        A journal is fsynced before each move. A killed process leaves a recoverable
        journal; ``rollback`` validates the bytes before restoring every old path.
        """
        if preview.get("root") != str(self.root):
            raise ValueError("rename preview belongs to a different library")
        expected = deepcopy(preview)
        fingerprint = expected.pop("fingerprint", None)
        if (
            hashlib.sha256(
                json.dumps(expected, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            != fingerprint
        ):
            raise ValueError("rename preview changed; generate a new preview")
        selected = [r for r in preview["items"] if r["status"] == "READY"]
        moves = [deepcopy(m) for row in selected for m in row["moves"]]
        operation_id = "rename_" + uuid4().hex
        journal_path = self._journal_path(operation_id)
        with self._locked():
            state = self._load()
            for move in moves:
                source = self.path(move["source"], existing=True)
                target = self.path(move["target"])
                if sha256_file(source) != move["sha256"]:
                    raise ValueError("source changed after preview: " + str(source))
                if target.exists() and _key(source) != _key(target):
                    raise FileExistsError(target)
                if target.parent.exists() and any(
                    _key(p) == _key(target) and _key(p) != _key(source)
                    for p in target.parent.iterdir()
                ):
                    raise FileExistsError("case-insensitive target collision")
                move["stage"] = str(
                    source.parent / (".an-move-" + operation_id + "-" + uuid4().hex)
                )
                move["state"] = "ORIGINAL"
            risks = self._reference_risks([m["source"] for m in moves])
            if risks:
                raise ValueError(
                    "references changed after preview: " + ", ".join(risks[:8])
                )
            journal = {
                "schema": "aletheia-nexus/file-operation/v1",
                "id": operation_id,
                "status": "RUNNING",
                "created_at": _now(),
                "root": str(self.root),
                "preview": deepcopy(preview),
                "moves": moves,
                "metadata_before": deepcopy(state),
                "errors": [],
            }
            _write(journal_path, journal)
            try:
                for move in moves:
                    # "STAGING" permits recovery if termination occurs after os.rename.
                    move["state"] = "STAGING"
                    _write(journal_path, journal)
                    os.rename(move["source"], move["stage"])
                    move["state"] = "STAGED"
                    _write(journal_path, journal)
                for move in moves:
                    target = Path(move["target"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self.path(target)
                    if target.exists():
                        raise FileExistsError(target)
                    move["state"] = "PROMOTING"
                    _write(journal_path, journal)
                    # Hard-link promotion fails closed on collisions on both NTFS
                    # and POSIX; no overwrite-permitting rename semantics.
                    os.link(move["stage"], target)
                    Path(move["stage"]).unlink()
                    if sha256_file(target) != move["sha256"]:
                        raise ValueError("file changed during move")
                    move["state"] = "MOVED"
                    _write(journal_path, journal)
                for item in selected:
                    stored = state["papers"][item["id"]]
                    if item["old_path"] != item["new_path"]:
                        stored.setdefault("aliases", []).append(
                            self._relative(item["old_path"])
                        )
                    stored["pdf"] = self._relative(item["new_path"])
                    stored["sidecar"] = self._relative(
                        json_output_path(
                            Path(item["new_path"]).with_suffix(".acquisition.json")
                        )
                    )
                for attachment in state["attachments"].values():
                    for move in moves:
                        if attachment["path"] == self._relative(move["source"]):
                            attachment["path"] = self._relative(move["target"])
                        if attachment.get("sidecar") == self._relative(move["source"]):
                            attachment["sidecar"] = self._relative(move["target"])
                _write(self.state_path, state)
                journal.update(status="COMPLETED", completed_at=_now())
                _write(journal_path, journal)
            except Exception as exc:
                journal["errors"].append(str(exc))
                journal["status"] = "ROLLBACK_REQUIRED"
                _write(journal_path, journal)
                self._rollback(journal, journal_path)
            return deepcopy(journal)

    def _rollback(self, journal, journal_path):
        try:
            # Preflight the entire rollback before changing any bytes.
            recovery = []
            for move in reversed(journal["moves"]):
                original = self.path(move["source"])
                stage, target = self.path(move["stage"]), self.path(move["target"])
                present = [p for p in (stage, target) if p.exists() and p != original]
                if original.exists():
                    if sha256_file(original) != move["sha256"]:
                        raise ValueError(
                            "rollback would overwrite changed source: " + str(original)
                        )
                    for p in present:
                        if sha256_file(p) != move["sha256"]:
                            raise ValueError("rollback target changed: " + str(p))
                    recovery.append((move, None, present))
                else:
                    if not present or any(
                        sha256_file(p) != move["sha256"] for p in present
                    ):
                        raise ValueError(
                            "rollback file missing or changed: " + str(original)
                        )
                    recovery.append((move, present[0], present[1:]))
            for move, source, redundant in recovery:
                original = Path(move["source"])
                if source:
                    original.parent.mkdir(parents=True, exist_ok=True)
                    os.link(source, original)
                    source.unlink()
                for p in redundant:
                    p.unlink()
                move["state"] = "RESTORED"
                _write(journal_path, journal)
            # Restore only path-related registry state. Keep later user metadata,
            # selections, views and tags saved after the operation.
            state = self._load()
            before = journal["metadata_before"]
            for item in journal["preview"]["items"]:
                if item["status"] != "READY":
                    continue
                old = before["papers"].get(item["id"])
                if old and item["id"] in state["papers"]:
                    for key in ("pdf", "sidecar", "aliases"):
                        state["papers"][item["id"]][key] = deepcopy(old.get(key))
            for attachment_id, old in before["attachments"].items():
                if attachment_id in state["attachments"]:
                    for key in ("path", "sidecar"):
                        state["attachments"][attachment_id][key] = old.get(key)
            _write(self.state_path, state)
            journal.update(status="ROLLED_BACK", rolled_back_at=_now())
        except Exception as exc:
            journal["status"] = "ROLLBACK_REQUIRED"
            journal["errors"].append(str(exc))
        _write(journal_path, journal)
        return deepcopy(journal)

    def rollback(self, operation_id):
        path = self._journal_path(operation_id)
        with self._locked():
            journal = _read(path)
            if journal.get("root") != str(self.root):
                raise ValueError("operation belongs to a different library")
            if journal.get("status") == "ROLLED_BACK":
                return journal
            return self._rollback(journal, path)

    def resolve_document(self, paper_id):
        row = self.get(paper_id)
        if not row:
            raise KeyError(paper_id)
        validate_parser_input(row["pdf_path"], sidecar_path=row["sidecar_path"])
        config = {
            "id": paper_id,
            "pdf": row["pdf_path"],
            "sidecar": row["sidecar_path"],
        }
        if row["metadata"].get("artifact"):
            config["artifact"] = row["metadata"]["artifact"]
        return config
