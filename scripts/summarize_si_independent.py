"""Audit real independent-CLI delivery separately from prior diagnostic probes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from benchmark_si_publishers import read, write


def summarize(root, baseline, destination):
    from aletheia_nexus.content.gate import sha256_file
    from aletheia_nexus.workbench.library import LibraryService
    from aletheia_nexus.workbench.standalone_supplements import (
        StandaloneSupplementService,
    )
    from aletheia_nexus.workbench.supplements import _validate_attachment

    manifest = read(root / "manifest.json")
    rows, files = [], []
    for case in manifest["cases"]:
        directory = root / "independent" / case["id"]
        outcome = read(root / "cases" / case["id"] / "result.json")
        summary = outcome.get("si", {})
        result = summary.get("result", {})
        paper = result.get("items", [{}])[0]
        library = LibraryService(directory / "library")
        service = StandaloneSupplementService(library)
        listing = service.list()
        assert not listing["warnings"] and not library.scan()["items"]
        assert result.get("main_status") == "NOT_REQUESTED"
        assert not list(library.root.rglob("*.acquisition.json"))
        assert not list(library.root.rglob("*.part"))
        delivered = []
        for entry in listing["items"]:
            item = service.get(entry["id"])
            receipt, path = item["record"], Path(item["path"])
            assert receipt["doi"] == case["doi"]
            assert receipt["main_pdf"] is None
            assert receipt["association_status"] == "DOI_ONLY"
            assert item["parseable"] is False
            assert sha256_file(path) == item["sha256"]
            validation = _validate_attachment(path, path.suffix)
            evidence = receipt.get("association_evidence") or {}
            expected_md5 = evidence.get("computed_md5")
            with path.open("rb") as handle:
                md5 = hashlib.file_digest(handle, "md5").hexdigest()
            if expected_md5:
                assert md5 == expected_md5
                assert path.stat().st_size == evidence["size_bytes"]
                assert evidence["resource_doi"] == case["doi"]
            delivered.append(
                {
                    "case_id": case["id"],
                    "id": item["id"],
                    "doi": item["doi"],
                    "role": item["role"],
                    "suffix": path.suffix,
                    "size_bytes": path.stat().st_size,
                    "sha256": item["sha256"],
                    "md5": md5,
                    "manifest_md5_checked": bool(expected_md5),
                    "source_record_sha256": item["source_record_sha256"],
                    "association_basis": receipt["association_basis"],
                    "source_url": receipt["source_url"],
                    "validation": validation,
                }
            )
        baseline_path = baseline / "cases" / case["id"] / "result.json"
        old = read(baseline_path) if baseline_path.exists() else {}
        row = {
            "id": case["id"],
            "doi": case["doi"],
            "cohort": case["cohort"],
            "publisher": case["publisher_stratum"],
            "status": result.get("status"),
            "process": outcome.get("si_process"),
            "main_status": result.get("main_status"),
            "old_product_SI": old.get("main", {}).get("integrated_si_status"),
            "old_probe_status": old.get("probe", {}).get("status"),
            "old_probe_SI_delivered": old.get("probe", {}).get("any_SI_delivered"),
            "files": len(delivered),
            "SI_files": sum(item["role"] == "SUPPLEMENT" for item in delivered),
            "suffixes": sorted({item["suffix"] for item in delivered}),
            "errors": paper.get("errors", []),
            "diagnostics": paper.get("diagnostics", []),
            "file_errors": [
                item
                for item in paper.get("items", [])
                if item.get("status") == "FAILED"
            ],
            "cwd": summary.get("cwd"),
            "wall_seconds": summary.get("wall_seconds"),
        }
        rows.append(row)
        files.extend(delivered)
    groups = {}
    for cohort in sorted({row["cohort"] for row in rows}):
        selected = [row for row in rows if row["cohort"] == cohort]
        groups[cohort] = {
            "n": len(selected),
            "statuses": dict(Counter(row["status"] for row in selected)),
            "papers_with_SI": sum(row["SI_files"] > 0 for row in selected),
            "delivered_files": sum(row["files"] for row in selected),
            "new_over_old_probe": [
                row["id"]
                for row in selected
                if row["SI_files"] and row["old_probe_SI_delivered"] is False
            ],
        }
    report = {
        "schema": "aletheia-nexus/si-independent-audit/v1",
        "source_commit": manifest["source_commit"],
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "baseline_manifest_sha256": manifest["baseline_manifest_sha256"],
        "scope": "DOI-only product CLI, public native HTTP, no main PDF, browser, institutional credentials or model calls. Metadata-closed is not an SI-existence gold standard.",
        "groups": groups,
        "file_count": len(files),
        "roles": dict(Counter(item["role"] for item in files)),
        "formats": dict(Counter(item["suffix"] for item in files)),
        "integrity": "All saved file SHA-256, parent DOI, receipt identity and format gates passed; available publisher MD5/size checked. No ARTICLE, acquisition sidecar or leftover partial file.",
        "cases": rows,
        "files": files,
        "raw_root": str(root),
    }
    write(destination.with_suffix(".json"), report)
    columns = [
        "id",
        "doi",
        "cohort",
        "publisher",
        "status",
        "old_product_SI",
        "old_probe_status",
        "old_probe_SI_delivered",
        "files",
        "SI_files",
        "suffixes",
    ]
    with destination.with_suffix(".csv").open(
        "x", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(
        json.dumps(
            {
                key: report[key]
                for key in [
                    "source_commit",
                    "manifest_sha256",
                    "groups",
                    "file_count",
                    "roles",
                    "formats",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.root, args.baseline, args.destination)
