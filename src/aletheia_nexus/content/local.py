"""Register researcher-supplied PDFs without claiming acquisition verification."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.identifiers.doi import normalize_doi

LOCAL_DOCUMENT_SCHEMA = "aletheia-nexus/local-document/v1"


def register_local_pdf(
    pdf_path: str | Path,
    *,
    output_dir: str | Path,
    title: str,
    doi: str | None = None,
    role: str = "ARTICLE",
    parent_pdf: str | Path | None = None,
    parent_sidecar: str | Path | None = None,
) -> Path:
    """Copy a local PDF and record explicit bibliographic/parent declarations.

    No network access or inferred DOI. REGISTERED/DECLARED is deliberately
    distinct from an acquisition record's VERIFIED/MATCH assertion.
    """
    source = Path(pdf_path).resolve()
    if not title.strip():
        raise ValueError("a local document requires a title")
    if role not in {"ARTICLE", "SUPPLEMENT"}:
        raise ValueError("role must be ARTICLE or SUPPLEMENT")
    if (role == "SUPPLEMENT") != (parent_pdf is not None):
        raise ValueError("a supplement requires --parent; an article has no parent")
    try:
        reader = PdfReader(source, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("local PDF requires a password")
        page_count = len(reader.pages)
    except PyPdfError as exc:
        raise ValueError(f"local PDF is unreadable: {exc}") from exc
    if not page_count:
        raise ValueError("local PDF contains no pages")
    digest = sha256_file(source)
    parent = None
    if parent_pdf is not None:
        main = validate_parser_input(parent_pdf, sidecar_path=parent_sidecar)
        if main.document_role != "ARTICLE" or main.pdf_sha256 == digest:
            raise ValueError("the parent must be a distinct main article")
        parent = {
            "article_id": main.article_id,
            "pdf_sha256": main.pdf_sha256,
            "doi": main.doi,
            "title": main.title,
        }
    normalized_doi = normalize_doi(doi) if doi else None
    if role == "SUPPLEMENT" and normalized_doi:
        raise ValueError("a supplement inherits its parent's citation; omit --doi")
    payload = {
        "schema": LOCAL_DOCUMENT_SCHEMA,
        "status": "REGISTERED",
        "target": {
            "title": title.strip(),
            "doi": normalized_doi,
            "article_id": "doi:" + normalized_doi
            if normalized_doi
            else f"an:source:sha256:{digest}",
        },
        "retrieval": {"sha256": digest, "transport": "user_selected_local_file"},
        "pdf_validation": {"valid_pdf": True, "page_count": page_count},
        "identity_validation": {"status": "DECLARED", "document_role": role},
        "parent": parent,
    }
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    pdf = destination / source.name
    sidecar = acquisition_sidecar_path(pdf)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    if pdf.exists() and sha256_file(pdf) != digest:
        raise FileExistsError(f"a different PDF already exists: {pdf}")
    if sidecar.exists():
        if json.loads(sidecar.read_text(encoding="utf-8")) != payload:
            raise FileExistsError(
                f"a different source record already exists: {sidecar}"
            )
        if pdf.is_file():
            return pdf
    temporary = destination / f".{source.name}.{uuid4().hex}.part"
    try:
        if not pdf.exists():
            shutil.copyfile(source, temporary)
            if sha256_file(temporary) != digest:
                raise ValueError("PDF changed while copying")
            os.replace(temporary, pdf)
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, sidecar)
    finally:
        temporary.unlink(missing_ok=True)
    return pdf
