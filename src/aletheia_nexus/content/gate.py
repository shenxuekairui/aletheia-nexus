"""Validation gate from acquisition artifacts into content parsing."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from aletheia_nexus.content.errors import ParserInputError, ParserInputErrorCode
from aletheia_nexus.core.identifiers.doi import normalize_doi

ACQUISITION_SCHEMAS = frozenset(
    {
        "aletheia-nexus/acquisition-record/v1",
        "aletheia-nexus/access-acquisition-record/v1",
    }
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ParserInput:
    pdf_path: Path
    sidecar_path: Path
    doi: str
    pdf_sha256: str
    sidecar_sha256: str
    page_count: int
    acquisition_schema: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error(code: ParserInputErrorCode, detail: str) -> ParserInputError:
    return ParserInputError(code, detail)


def _mapping(payload: object, key: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise _error(
            ParserInputErrorCode.INVALID_SIDECAR,
            "the sidecar root must be a JSON object",
        )
    value = payload.get(key)
    if not isinstance(value, dict):
        raise _error(
            ParserInputErrorCode.INVALID_SIDECAR,
            f"sidecar field {key!r} must be an object",
        )
    return value


def validate_parser_input(
    pdf_path: str | Path,
    requested_doi: str,
    *,
    sidecar_path: str | Path | None = None,
) -> ParserInput:
    """Fail closed unless a PDF still matches its VERIFIED acquisition record."""

    pdf = Path(pdf_path).resolve()
    if not pdf.is_file():
        raise _error(ParserInputErrorCode.PDF_NOT_FOUND, f"not a file: {pdf}")
    if any(part.casefold() == "_unverified" for part in pdf.parts):
        raise _error(
            ParserInputErrorCode.UNVERIFIED_PATH,
            "files under _unverified cannot enter the parser",
        )

    sidecar = (
        Path(sidecar_path).resolve()
        if sidecar_path is not None
        else pdf.with_suffix(".acquisition.json")
    )
    if not sidecar.is_file():
        raise _error(ParserInputErrorCode.SIDECAR_NOT_FOUND, f"not a file: {sidecar}")
    try:
        sidecar_bytes = sidecar.read_bytes()
        payload = json.loads(sidecar_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error(ParserInputErrorCode.INVALID_SIDECAR, str(exc)) from exc
    if not isinstance(payload, dict):
        raise _error(
            ParserInputErrorCode.INVALID_SIDECAR,
            "the sidecar root must be a JSON object",
        )

    schema = payload.get("schema")
    if schema not in ACQUISITION_SCHEMAS:
        raise _error(
            ParserInputErrorCode.UNKNOWN_SIDECAR_SCHEMA,
            f"unsupported acquisition schema: {schema!r}",
        )
    if payload.get("status") != "VERIFIED":
        raise _error(
            ParserInputErrorCode.STATUS_NOT_VERIFIED,
            f"recorded status is {payload.get('status')!r}",
        )

    pdf_validation = _mapping(payload, "pdf_validation")
    if pdf_validation.get("valid_pdf") is not True:
        raise _error(
            ParserInputErrorCode.PDF_VALIDATION_FAILED,
            "pdf_validation.valid_pdf is not true",
        )
    identity = _mapping(payload, "identity_validation")
    if identity.get("status") != "MATCH":
        raise _error(
            ParserInputErrorCode.IDENTITY_NOT_MATCHED,
            f"identity status is {identity.get('status')!r}",
        )
    if identity.get("document_role") != "ARTICLE":
        raise _error(
            ParserInputErrorCode.DOCUMENT_NOT_ARTICLE,
            f"document role is {identity.get('document_role')!r}",
        )

    target = _mapping(payload, "target")
    try:
        expected_doi = normalize_doi(requested_doi)
        recorded_doi = normalize_doi(target.get("doi"))
    except (TypeError, ValueError) as exc:
        raise _error(ParserInputErrorCode.DOI_MISMATCH, str(exc)) from exc
    if expected_doi != recorded_doi:
        raise _error(
            ParserInputErrorCode.DOI_MISMATCH,
            f"requested {expected_doi!r}, sidecar records {recorded_doi!r}",
        )

    retrieval = _mapping(payload, "retrieval")
    recorded_hash = retrieval.get("sha256")
    if not isinstance(recorded_hash, str) or not _SHA256.fullmatch(recorded_hash):
        raise _error(
            ParserInputErrorCode.INVALID_RECORDED_HASH,
            "retrieval.sha256 must be a 64-character hexadecimal digest",
        )
    actual_hash = sha256_file(pdf)
    if actual_hash != recorded_hash.lower():
        raise _error(
            ParserInputErrorCode.PDF_HASH_MISMATCH,
            f"recorded {recorded_hash.lower()}, actual {actual_hash}",
        )

    recorded_pages = pdf_validation.get("page_count")
    if isinstance(recorded_pages, bool) or not isinstance(recorded_pages, int):
        raise _error(
            ParserInputErrorCode.INVALID_SIDECAR,
            "pdf_validation.page_count must be an integer",
        )
    try:
        reader = PdfReader(pdf, strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:
                raise _error(
                    ParserInputErrorCode.PDF_UNREADABLE,
                    "encrypted PDF could not be opened without a password",
                ) from exc
            if unlocked == 0:
                raise _error(
                    ParserInputErrorCode.PDF_UNREADABLE,
                    "encrypted PDF could not be opened without a password",
                )
        actual_pages = len(reader.pages)
    except ParserInputError:
        raise
    except Exception as exc:
        raise _error(ParserInputErrorCode.PDF_UNREADABLE, str(exc)) from exc
    if actual_pages != recorded_pages:
        raise _error(
            ParserInputErrorCode.PAGE_COUNT_MISMATCH,
            f"recorded {recorded_pages}, actual {actual_pages}",
        )

    return ParserInput(
        pdf_path=pdf,
        sidecar_path=sidecar,
        doi=expected_doi,
        pdf_sha256=actual_hash,
        sidecar_sha256=hashlib.sha256(sidecar_bytes).hexdigest(),
        page_count=actual_pages,
        acquisition_schema=str(schema),
    )
