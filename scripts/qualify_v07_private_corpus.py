"""Run the canonical parser over a private VERIFIED-PDF directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from aletheia_nexus.content import parse_document
from aletheia_nexus.content.diagnostics import safe_exception_detail

FIXED_TIME = "2026-09-28T00:00:00+00:00"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--cohort",
        type=Path,
        help="Optional frozen cohort JSON; otherwise all top-level PDFs are used.",
    )
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    if args.cohort:
        cohort = json.loads(args.cohort.read_text(encoding="utf-8"))
        inputs = [
            (
                Path(record["pdf"]),
                Path(record["sidecar"]),
                record.get("pdf_sha256"),
                record.get("sidecar_sha256"),
            )
            for record in cohort["records"]
        ]
    else:
        inputs = [
            (pdf, pdf.with_suffix(".acquisition.json"), None, None)
            for pdf in sorted(args.input_dir.glob("*.pdf"))
        ]
    for pdf, sidecar, expected_pdf_hash, expected_sidecar_hash in inputs:
        doi = None
        try:
            for path, expected_hash in (
                (pdf, expected_pdf_hash),
                (sidecar, expected_sidecar_hash),
            ):
                if not path.is_file():
                    raise FileNotFoundError(f"corpus input is missing: {path.name}")
                if (
                    expected_hash
                    and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
                ):
                    raise ValueError(f"frozen cohort hash changed: {path.name}")
            acquisition = json.loads(sidecar.read_text(encoding="utf-8"))
            doi = str(acquisition["target"]["doi"])
            output = args.output_dir / f"{pdf.stem}.parsed.json"
            result = parse_document(
                pdf,
                doi,
                sidecar_path=sidecar,
                output_path=output,
                created_at=FIXED_TIME,
            )
            document = result.document
            records.append(
                {
                    "file": pdf.name,
                    "doi": doi,
                    "status": result.status,
                    "artifact_id": document["artifact_id"],
                    "pages": document["source"]["page_count"],
                    "blocks": len(document["blocks"]),
                    "characters": document["quality"]["text_characters"],
                    "anchor_coverage": document["quality"]["anchor_coverage"],
                    "references": len(document["references"]),
                    "figures": len(document["figures"]),
                    "tables": len(document["tables"]),
                    "warning_codes": sorted(
                        {str(item["code"]) for item in document["warnings"]}
                    ),
                    "error_codes": sorted(
                        {str(item["code"]) for item in document["errors"]}
                    ),
                }
            )
        except Exception as exc:
            records.append(
                {
                    "file": pdf.name,
                    "doi": doi,
                    "status": "RUNNER_ERROR",
                    "error": (f"{type(exc).__name__}: {safe_exception_detail(exc)}"),
                }
            )

    counts = Counter(str(record["status"]) for record in records)
    passed = bool(inputs) and counts.get("PARSED", 0) == len(inputs)
    report = {
        "schema": "aletheia-nexus/private-parser-qualification/v1",
        "scope": (
            "Broader layout/runtime stress evidence only; this report does not "
            "claim semantic accuracy or total visual information recovery."
        ),
        "status_counts": dict(sorted(counts.items())),
        "input_count": len(inputs),
        "passed": passed,
        "totals": {
            "papers": len(records),
            "pages": sum(int(record.get("pages", 0)) for record in records),
            "blocks": sum(int(record.get("blocks", 0)) for record in records),
            "characters": sum(int(record.get("characters", 0)) for record in records),
        },
        "records": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["totals"], sort_keys=True))
    print(json.dumps(report["status_counts"], sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
