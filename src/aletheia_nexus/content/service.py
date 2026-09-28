"""Public service for parsing a verified paper into a new sidecar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aletheia_nexus.content.backends import ExtractionBackend
from aletheia_nexus.content.errors import ParserInputError, ParserInputErrorCode
from aletheia_nexus.content.gate import (
    ParserInput,
    sha256_file,
    validate_parser_input,
)
from aletheia_nexus.content.parser import ParserConfig, parse_pdf
from aletheia_nexus.content.schema import write_parsed_document


@dataclass(frozen=True)
class ParseResult:
    status: str
    output_path: Path
    document: dict[str, object]
    source: ParserInput


def parse_document(
    pdf_path: str | Path,
    requested_doi: str,
    *,
    sidecar_path: str | Path | None = None,
    output_path: str | Path | None = None,
    config: ParserConfig | None = None,
    backend: ExtractionBackend | None = None,
    created_at: str | None = None,
) -> ParseResult:
    """Parse a VERIFIED main article without changing either input artifact."""

    source = validate_parser_input(pdf_path, requested_doi, sidecar_path=sidecar_path)
    parser_config = config or ParserConfig()
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    document = parse_pdf(
        source,
        created_at=timestamp,
        config=parser_config,
        backend=backend,
    )
    final_pdf_hash = sha256_file(source.pdf_path)
    if final_pdf_hash != source.pdf_sha256:
        raise ParserInputError(
            ParserInputErrorCode.PDF_HASH_MISMATCH,
            "PDF changed while parsing; no parsed artifact was written",
        )
    final_sidecar_hash = sha256_file(source.sidecar_path)
    if final_sidecar_hash != source.sidecar_sha256:
        raise ParserInputError(
            ParserInputErrorCode.SIDECAR_CHANGED,
            "acquisition sidecar changed while parsing; no parsed artifact was written",
        )
    target = (
        Path(output_path).resolve()
        if output_path is not None
        else source.pdf_path.with_suffix(".parsed.json")
    )
    if target in {source.pdf_path, source.sidecar_path}:
        raise ValueError("parsed output must not overwrite an acquisition artifact")
    write_parsed_document(target, document)
    return ParseResult(
        status=str(document["status"]),
        output_path=target,
        document=document,
        source=source,
    )
