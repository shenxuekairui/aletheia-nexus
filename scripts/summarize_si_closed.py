"""Audit closed-paper native benchmark outputs without changing raw results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from aletheia_nexus.acquire.fulltext.resolution.identity import validate_page_identity
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html


def read(path):
    return json.loads(path.read_text("utf-8"))


def digest(path, algorithm="sha256"):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def metrics(rows):
    return {
        "n": len(rows),
        "main_statuses": dict(
            Counter(
                row.get("main", {}).get(
                    "main_status", row.get("main_process", "NOT_RUN")
                )
                for row in rows
            )
        ),
        "integrated_SI_statuses": dict(
            Counter(
                row.get("main", {}).get("integrated_si_status", "NOT_RECORDED")
                for row in rows
            )
        ),
        "probe_statuses": dict(
            Counter(
                row.get("probe", {}).get("status", row.get("probe_process", "NOT_RUN"))
                for row in rows
            )
        ),
        "probe_SI_papers": sum(
            row.get("probe", {}).get("any_SI_delivered", False) for row in rows
        ),
        "probe_any_attachment_papers": sum(
            any(
                item.get("status") == "DELIVERED_UNREGISTERED"
                for item in row.get("probe", {}).get("files", [])
            )
            for row in rows
        ),
        "probe_files": sum(
            item.get("status") == "DELIVERED_UNREGISTERED"
            for row in rows
            for item in row.get("probe", {}).get("files", [])
        ),
        "probe_roles": dict(
            Counter(
                item["role"]
                for row in rows
                for item in row.get("probe", {}).get("files", [])
                if item.get("status") == "DELIVERED_UNREGISTERED"
            )
        ),
        "probe_formats": dict(
            Counter(
                item["suffix"]
                for row in rows
                for item in row.get("probe", {}).get("files", [])
                if item.get("status") == "DELIVERED_UNREGISTERED"
            )
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = read(root / "manifest.json")
    rows, errors, fingerprints = [], [], []
    for case in manifest["cases"]:
        cid = case["id"]
        result = read(root / "cases" / cid / "result.json")
        assert result["doi"] == case["doi"]
        probe = result.get("probe", {})
        if case["cohort"] == "metadata_closed":
            assert case["open_access_snapshot"]["is_oa"] is False
            assert case["open_access_snapshot"]["oa_status"] == "closed"
        for item in probe.get("files", []):
            if item["status"] != "DELIVERED_UNREGISTERED":
                continue
            path = Path(item["path"])
            valid = path.resolve().is_relative_to(root / "probes" / cid)
            valid = (
                valid
                and digest(path) == item["sha256"]
                and digest(path, "md5") == item["md5"]
            )
            valid = (
                valid and item["bytes_match_transport"] and item["registered"] is False
            )
            valid = valid and item["parent_doi"] == case["doi"]
            if item["manifest_md5_checked"]:
                valid = valid and item["evidence"]["computed_md5"] == item["md5"]
                valid = valid and item["evidence"]["resource_doi"] == case["doi"]
            else:
                html = root / "probes" / cid / "article.html"
                identity = validate_page_identity(
                    target_doi=case["doi"],
                    parsed=parse_html(html.read_text("utf-8")),
                    expected_title=case["title"],
                )
                valid = (
                    valid
                    and identity.doi_match
                    and identity.metadata_dois == (case["doi"],)
                )
            if not valid:
                errors.append(
                    {
                        "id": cid,
                        "file": path.name,
                        "kind": "probe_bytes_or_parent_evidence",
                    }
                )
        for item in result.get("main", {}).get("integrated_files", []):
            path = root / "native/cases" / cid / "integrated/SI" / item["filename"]
            if digest(path) != item["sha256"] or not all(item["checks"].values()):
                errors.append(
                    {"id": cid, "file": path.name, "kind": "integrated_bytes_or_parent"}
                )
        rows.append(result)
        for directory in [
            root / "cases" / cid,
            root / "probes" / cid,
            root / "native/cases" / cid,
        ]:
            for path in sorted(directory.glob("*.json")):
                fingerprints.append(
                    {"file": path.relative_to(root).as_posix(), "sha256": digest(path)}
                )
    closed = [row for row in rows if row["cohort"] == "metadata_closed"]
    controls = [row for row in rows if row["cohort"] != "metadata_closed"]
    summary = {
        "schema": "aletheia-nexus/si-closed-observations/v1",
        "source_commit": manifest["source_commit"],
        "raw_root": str(root),
        "manifest_sha256": digest(root / "manifest.json"),
        "execution": read(root / "execution.json"),
        "limits": manifest["limits"],
        "scope": "Public native only. Metadata-closed is not independently audited entitlement. No assumption every paper has SI. Unregistered probe delivery is separate from product success.",
        "closed": metrics(closed),
        "OA_controls": metrics(controls),
        "closed_by_publisher": {
            name: metrics([row for row in closed if row["publisher_stratum"] == name])
            for name, _ in manifest["groups"]
        },
        "integrity_errors": errors,
        "raw_record_fingerprints": fingerprints,
        "cases": rows,
    }
    with (root.parent / "audit-final.json").open(
        "x", encoding="utf-8", newline="\n"
    ) as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    with (root.parent / "cases-final.csv").open(
        "x", encoding="utf-8-sig", newline=""
    ) as stream:
        fields = [
            "id",
            "doi",
            "publisher_stratum",
            "cohort",
            "main_status",
            "integrated_SI_status",
            "probe_status",
            "probe_SI_delivered",
            "probe_delivered_files",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{key: row[key] for key in fields[:4]},
                    "main_status": row.get("main", {}).get(
                        "main_status", row.get("main_process")
                    ),
                    "integrated_SI_status": row.get("main", {}).get(
                        "integrated_si_status"
                    ),
                    "probe_status": row.get("probe", {}).get(
                        "status", row.get("probe_process")
                    ),
                    "probe_SI_delivered": row.get("probe", {}).get(
                        "any_SI_delivered", False
                    ),
                    "probe_delivered_files": sum(
                        item["status"] == "DELIVERED_UNREGISTERED"
                        for item in row.get("probe", {}).get("files", [])
                    ),
                }
            )
    print(
        json.dumps(
            {
                "closed": summary["closed"],
                "controls": summary["OA_controls"],
                "integrity_errors": errors,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
