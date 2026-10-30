"""Read a local library from provenance sidecars, without a separate stale index."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from aletheia_nexus.acquire.fulltext.storage import is_verified_record
from aletheia_nexus.content.gate import validate_parser_input
from aletheia_nexus.core.artifact_paths import (
    acquisition_sidecar_path,
    find_json_path,
    json_output_path,
)
from aletheia_nexus.core.organization import normalize_folder

_LABEL_SCHEMA = "aletheia-nexus/library-labels/v1"


def _labels(pdf: Path, sha256: str, initial: list[str]) -> list[str]:
    path = find_json_path(pdf.with_suffix(".library.json"))
    if not isinstance(initial, list) or any(not isinstance(t, str) for t in initial):
        raise ValueError("Invalid initial library labels")
    if path.is_symlink():
        raise ValueError("Library labels must not be symbolic links")
    if not path.exists():
        return initial
    record = json.loads(path.read_text(encoding="utf-8"))
    tags = record.get("tags")
    if (
        record.get("schema") != _LABEL_SCHEMA
        or record.get("pdf_sha256") != sha256
        or not isinstance(tags, list)
        or any(not isinstance(t, str) or not t.strip() for t in tags)
    ):
        raise ValueError("Invalid or stale library labels")
    return tags


def update_tags(pdf: str | Path, *, add=(), remove=()) -> list[str]:
    """Edit only mutable labels; preserve acquisition/parsed evidence byte-for-byte."""
    pdf = Path(pdf).resolve()
    if pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        raise ValueError("Provide an existing PDF")
    payload = json.loads(acquisition_sidecar_path(pdf).read_text(encoding="utf-8"))
    if not is_verified_record(payload):
        if payload.get("schema") != "aletheia-nexus/local-document/v1":
            raise ValueError(
                "Labels require a verified acquisition or registered local record"
            )
        validate_parser_input(pdf)
    with pdf.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != payload.get("retrieval", {}).get("sha256"):
        raise ValueError("PDF hash does not match its acquisition record")
    for tag in (*add, *remove):
        if (
            not isinstance(tag, str)
            or not tag.strip()
            or len(tag) > 80
            or any(ord(c) < 32 for c in tag)
        ):
            raise ValueError("Tags must be non-empty labels of at most 80 characters")
    tags = _labels(pdf, digest, (payload.get("organization") or {}).get("tags", []))
    removed = {t.strip() for t in remove}
    tags = list(
        dict.fromkeys(t for t in [*tags, *(t.strip() for t in add)] if t not in removed)
    )
    path = json_output_path(pdf.with_suffix(".library.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".part")
    try:
        temporary.write_text(
            json.dumps(
                {"schema": _LABEL_SCHEMA, "pdf_sha256": digest, "tags": tags},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return tags


def scan_library(
    root: str | Path, *, folder=None, tag=None, query=None, path_guard=None
) -> dict:
    """Read native records, optionally enforcing the host's read boundary per path."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Library directory does not exist")
    folder = normalize_folder(folder)
    items, warnings = [], []
    for sidecar in sorted(root.rglob("*.acquisition.json")):
        if path_guard is not None:
            path_guard(sidecar)
        try:
            if not sidecar.resolve().is_relative_to(root):
                continue
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Invalid library record")
            local = payload.get("schema") == "aletheia-nexus/local-document/v1"
            if payload.get("status") != ("REGISTERED" if local else "VERIFIED"):
                continue
            if not local and not is_verified_record(payload):
                raise ValueError("Incomplete acquisition evidence")
            pdf = sidecar.with_name(
                sidecar.name.removesuffix(".acquisition.json") + ".pdf"
            )
            if sidecar.parent.name == "json" and not pdf.is_file():
                pdf = sidecar.parent.parent / pdf.name
            if sidecar != acquisition_sidecar_path(pdf):
                continue
            if path_guard is not None:
                path_guard(pdf)
                path_guard(find_json_path(pdf.with_suffix(".library.json")))
            if not pdf.resolve().is_relative_to(root):
                continue
            if local:
                validate_parser_input(pdf, sidecar_path=sidecar)
            relative_folder = pdf.parent.relative_to(root).as_posix()
            relative_folder = "" if relative_folder == "." else relative_folder
            organization = payload.get("organization") or {}
            title = (
                organization.get("title")
                or payload.get("target", {}).get("expected_title")
                or payload.get("target", {}).get("title")
                or ""
            )
            doi = payload.get("target", {}).get("doi")
            tags = organization.get("tags", [])
            if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                raise ValueError("invalid tags")
            try:
                tags = _labels(pdf, payload["retrieval"]["sha256"], tags)
            except (OSError, ValueError, TypeError, AttributeError):
                # Optional mutable labels must not hide valid scientific evidence.
                warnings.append(
                    {
                        "sidecar": str(sidecar.relative_to(root)),
                        "error": "Unreadable library labels; acquisition labels retained",
                    }
                )
            if folder and not (
                relative_folder == folder or relative_folder.startswith(folder + "/")
            ):
                continue
            if tag and tag not in tags:
                continue
            if (
                query
                and query.casefold()
                not in " ".join(
                    [str(title), str(doi or ""), pdf.name, *tags]
                ).casefold()
            ):
                continue
            integrity = "missing"
            if pdf.is_file():
                with pdf.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                integrity = (
                    "verified"
                    if digest == payload.get("retrieval", {}).get("sha256")
                    else "hash_mismatch"
                )
            items.append(
                {
                    "doi": doi,
                    "title": title,
                    "folder": relative_folder,
                    "tags": tags,
                    "pdf_path": str(pdf),
                    "sidecar_path": str(sidecar),
                    "integrity": integrity,
                    "document_role": payload.get("identity_validation", {}).get(
                        "document_role", "ARTICLE"
                    ),
                    "identity_basis": "local_declared"
                    if local
                    else "acquisition_verified",
                    "parent": payload.get("parent"),
                }
            )
        except (OSError, ValueError, TypeError, AttributeError):
            warnings.append(
                {
                    "sidecar": str(sidecar.relative_to(root)),
                    "error": "Unreadable library record",
                }
            )
    return {"root": str(root), "items": items, "warnings": warnings}
