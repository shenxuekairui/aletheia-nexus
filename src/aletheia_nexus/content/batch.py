"""Resumable, per-file parsing with a durable coverage report."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Callable

from aletheia_nexus.content.artifact import ParsedArtifact
from aletheia_nexus.content.backends import ExtractionBackend, LayoutPdfBackend
from aletheia_nexus.content.export import write_ai_export
from aletheia_nexus.content.gate import validate_parser_input
from aletheia_nexus.content.parser import PARSER_VERSION, ParserConfig
from aletheia_nexus.content.service import parse_document


def parse_batch(
    root: str | Path,
    *,
    config: ParserConfig | None = None,
    backend: ExtractionBackend | None = None,
    resume: bool = True,
    retry_partial: bool = False,
    report_path: str | Path | None = None,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ValueError(f"not a directory: {directory}")
    options = config or ParserConfig()
    engine = backend or LayoutPdfBackend()
    engine_identity = {"name": engine.name, "version": engine.version}
    if hasattr(engine, "execution_identity"):
        engine_identity["components"] = engine.execution_identity
    report = Path(report_path) if report_path else directory / "parse-report.json"
    pdfs = sorted(directory.rglob("*.pdf"))
    rows = [
        {"pdf": p.relative_to(directory).as_posix(), "status": "PENDING"} for p in pdfs
    ]
    result = {
        "schema": "aletheia-nexus/parse-batch/v1",
        "items": rows,
        "interrupted": False,
    }

    def save() -> None:
        result["counts"] = dict(Counter(item["status"] for item in rows))
        result["complete"] = all(item["status"] == "COMPLETED" for item in rows)
        write_ai_export(
            report,
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            overwrite=True,
        )

    save()
    try:
        for pdf, row in zip(pdfs, rows):
            target = pdf.with_suffix(".parsed.json")
            try:
                if not pdf.resolve().is_relative_to(directory):
                    raise ValueError(
                        "PDF link points outside the selected corpus directory"
                    )
                source = validate_parser_input(pdf)
                existing = None
                if resume and target.is_file():
                    try:
                        candidate = ParsedArtifact.load(target).document
                        if (
                            candidate["source"]["pdf_sha256"] == source.pdf_sha256
                            and candidate["source"]["acquisition_sidecar_sha256"]
                            == source.sidecar_sha256
                            and candidate["parser"]["configuration_fingerprint"]
                            == options.fingerprint
                            and candidate["parser"]["version"] == PARSER_VERSION
                            and candidate["parser"]["backend"] == engine_identity
                            and (
                                candidate["status"] == "PARSED"
                                or (
                                    candidate["status"] == "PARTIAL"
                                    and not retry_partial
                                )
                            )
                        ):
                            existing = candidate
                    except (OSError, ValueError):
                        pass
                document = (
                    existing
                    or parse_document(
                        pdf, config=options, backend=engine, overwrite=True
                    ).document
                )
                row.update(
                    {
                        "status": {
                            "PARSED": "COMPLETED",
                            "PARTIAL": "PARTIAL",
                            "FAILED": "FAILED",
                        }[document["status"]],
                        "resumed": existing is not None,
                        "artifact": target.relative_to(directory).as_posix(),
                        "artifact_id": document["artifact_id"],
                        "quality": document["quality"],
                        "warnings": document["warnings"],
                        "errors": document["errors"],
                    }
                )
            except (OSError, ValueError, RuntimeError) as exc:
                row.update(status="FAILED", error=str(exc))
            save()
            if progress:
                progress(row)
    except KeyboardInterrupt:
        result["interrupted"] = True
        save()
        raise
    return result
