"""Fetch and qualify the hash-frozen public OA v0.7 layout set."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from aletheia_nexus.content import parse_document

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks" / "v07_public_oa" / "manifest.json"
FIXED_TIME = "2026-09-28T00:00:00+00:00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar(entry: dict[str, object], pdf: Path) -> Path:
    payload = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "acquired_at": FIXED_TIME,
        "status": "VERIFIED",
        "target": {"doi": entry["doi"], "expected_title": entry["title"]},
        "retrieval": {"sha256": entry["sha256"]},
        "pdf_validation": {"valid_pdf": True, "page_count": entry["page_count"]},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
    }
    path = pdf.with_suffix(".acquisition.json")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def qualify(manifest_path: Path) -> dict[str, object]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    records: list[dict[str, object]] = []
    with TemporaryDirectory(prefix="an-v07-public-oa-") as directory:
        root = Path(directory)
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            for entry in manifest["entries"]:
                pdf = root / f"{entry['id']}.pdf"
                response = client.get(entry["url"])
                response.raise_for_status()
                pdf.write_bytes(response.content)
                actual_hash = _sha256(pdf)
                if actual_hash != entry["sha256"]:
                    raise ValueError(
                        f"{entry['id']}: expected {entry['sha256']}, got {actual_hash}"
                    )
                sidecar = _sidecar(entry, pdf)
                result = parse_document(
                    pdf,
                    str(entry["doi"]),
                    sidecar_path=sidecar,
                    output_path=root / f"{entry['id']}.parsed.json",
                    created_at=FIXED_TIME,
                )
                document = result.document
                normalized_text = " ".join(
                    str(block["text"]) for block in document["blocks"]
                ).casefold()
                gold = entry["gold"]
                checks = {
                    "status_parsed": result.status == "PARSED",
                    "page_count": document["source"]["page_count"]
                    == entry["page_count"],
                    "anchor_coverage": document["quality"]["anchor_coverage"]["ratio"]
                    == 1.0,
                    "required_text": all(
                        str(value).casefold() in normalized_text
                        for value in gold["required_text"]
                    ),
                    "references": len(document["references"])
                    >= gold["minimum_references"],
                    "figures": len(document["figures"]) >= gold["minimum_figures"],
                    "tables": len(document["tables"]) >= gold["minimum_tables"],
                }
                records.append(
                    {
                        "id": entry["id"],
                        "doi": entry["doi"],
                        "license": entry["license"],
                        "pdf_sha256": actual_hash,
                        "parsed_artifact_id": document["artifact_id"],
                        "checks": checks,
                        "passed": all(checks.values()),
                        "counts": {
                            "pages": document["source"]["page_count"],
                            "blocks": len(document["blocks"]),
                            "references": len(document["references"]),
                            "figures": len(document["figures"]),
                            "tables": len(document["tables"]),
                        },
                    }
                )
    return {
        "schema": "aletheia-nexus/public-oa-qualification-report/v1",
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "passed": all(record["passed"] for record in records),
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = qualify(args.manifest)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
