"""Read-only artifact audit for the bounded real-paper workbench acceptance.

Does not import/instantiate application services, repair locators, refresh a
library, call a model or modify evidence. Only --report is written. Source PDFs
are fingerprinted, not scientifically reinterpreted or downloaded again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def audit(base, *, expected_papers=3):
    base = Path(base).resolve(strict=True)
    library, workspace = base / "library", base / "workspace"
    registry_path = library / ".an-workbench/library.json"
    registry_bytes = registry_path.read_bytes()
    registry = json.loads(registry_bytes)
    report = {
        "schema": "aletheia-nexus/independent-library-check/v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read-only artifacts; no new source acquisition or scientific-quality assessment",
        "services_instantiated": False,
        "model_calls_issued": 0,
        "root": str(base),
        "checks": [],
        "papers": [],
        "attachments": [],
    }
    hashes = {}

    def inside(value):
        path = Path(value)
        path = path if path.is_absolute() else library / path
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in (path, *path.parents)
        ):
            raise ValueError("audit refuses symbolic links/junctions")
        path = path.resolve(strict=True)
        if not path.is_relative_to(library):
            raise ValueError("artifact resolves outside acceptance library")
        return path

    def fingerprint(path):
        path = Path(path)
        if path not in hashes:
            with path.open("rb") as handle:
                hashes[path] = hashlib.file_digest(handle, "sha256").hexdigest()
        return hashes[path]

    def check(name, passed, **details):
        report["checks"].append({"name": name, "passed": bool(passed), **details})

    check(
        "expected_paper_count",
        len(registry["papers"]) == expected_papers,
        actual=len(registry["papers"]),
    )
    sources = {}
    for paper_id, paper in registry["papers"].items():
        pdf, sidecar = inside(paper["pdf"]), inside(paper["sidecar"])
        source = read_json(sidecar)
        pdf_hash, sidecar_hash = fingerprint(pdf), fingerprint(sidecar)
        target = source.get("target", {})
        original = target.get("expected_title") or target.get("title")
        article_id = target.get("article_id") or (
            "doi:" + target["doi"]
            if target.get("doi")
            else "an:source:sha256:" + pdf_hash
        )
        expected_id = (
            "paper_"
            + hashlib.sha256((pdf_hash + ":" + sidecar_hash).encode()).hexdigest()[:24]
        )
        check(
            "paper_identity_and_content",
            paper_id == expected_id and pdf_hash == source["retrieval"]["sha256"],
            paper_id=paper_id,
        )
        check(
            "main_keeps_verified_article_record",
            source.get("status") == "VERIFIED"
            and source.get("identity_validation", {}).get("status") == "MATCH"
            and source.get("identity_validation", {}).get("document_role") == "ARTICLE",
            paper_id=paper_id,
        )
        check(
            "main_pdf_is_category_flat",
            pdf.parent.name != "SI" and pdf.suffix.lower() == ".pdf",
            paper_id=paper_id,
            category=pdf.parent.relative_to(library).as_posix(),
        )
        translation = paper.get("metadata", {}).get("translation", {})
        title_zh = paper.get("metadata", {}).get("title_zh")
        check(
            "original_and_translation_are_separate",
            bool(title_zh)
            and original == translation.get("original")
            and title_zh != original,
            paper_id=paper_id,
        )
        check(
            "model_title_not_human_confirmed",
            translation.get("source") == "model"
            and translation.get("confirmed") is False,
            paper_id=paper_id,
        )
        sources[paper_id] = {
            "pdf": pdf,
            "sha256": pdf_hash,
            "sidecar_sha256": sidecar_hash,
            "article_id": article_id,
            "doi": target.get("doi"),
        }
        report["papers"].append(
            {
                "id": paper_id,
                "pdf": str(pdf),
                "sidecar": str(sidecar),
                "pdf_sha256": pdf_hash,
                "sidecar_sha256": sidecar_hash,
                "doi": target.get("doi"),
                "title_original": original,
                "title_zh": title_zh,
                "translation_source": translation.get("source"),
                "translation_confirmed": translation.get("confirmed"),
            }
        )

    roles = Counter()
    for attachment_id, attachment in registry["attachments"].items():
        parent = sources[attachment["parent_id"]]
        path, receipt_path = inside(attachment["path"]), inside(attachment["source"])
        receipt = read_json(receipt_path)
        digest, role = fingerprint(path), attachment["role"]
        roles[role] += 1
        check(
            "attachment_registry_receipt_and_bytes_agree",
            digest == attachment["sha256"] == receipt["sha256"]
            and role == receipt["role"],
            attachment_id=attachment_id,
        )
        check(
            "explicit_attachment_parent_identity",
            attachment["parent_sha256"]
            == parent["sha256"]
            == receipt["parent"]["pdf_sha256"]
            and receipt["parent"]["sidecar_sha256"] == parent["sidecar_sha256"]
            and receipt["parent"]["article_id"] == parent["article_id"],
            attachment_id=attachment_id,
        )
        check(
            "shared_category_si_and_base_name",
            path.parent == parent["pdf"].parent / "SI"
            and path.name.startswith(parent["pdf"].stem + "__"),
            attachment_id=attachment_id,
        )
        if role == "SUPPLEMENT":
            sidecar = inside(attachment["sidecar"])
            declaration = read_json(sidecar)
            check(
                "si_is_declared_supplement_not_verified_main",
                declaration.get("status") == "REGISTERED"
                and declaration.get("identity_validation", {}).get("status")
                == "DECLARED"
                and declaration.get("identity_validation", {}).get("document_role")
                == "SUPPLEMENT"
                and declaration["parent"]["pdf_sha256"] == parent["sha256"]
                and declaration["parent"]["article_id"] == parent["article_id"]
                and declaration["retrieval"]["sha256"] == digest,
                attachment_id=attachment_id,
            )
        else:
            check(
                "other_role_not_parser_registered_si",
                attachment.get("sidecar") is None,
                attachment_id=attachment_id,
                role=role,
                format_validation_parseable=receipt["validation"].get("parseable"),
                note="A structurally readable PeerReview PDF is not registered/admitted as SUPPLEMENT; role and sidecar control research inputs.",
            )
        if role == "SOURCE_DATA" and path.suffix.lower() == ".xlsx":
            with zipfile.ZipFile(path) as archive:
                members = set(archive.namelist())
            check(
                "source_data_xlsx_structure",
                {"xl/workbook.xml", "[Content_Types].xml"} <= members,
                attachment_id=attachment_id,
            )
        report["attachments"].append(
            {
                "id": attachment_id,
                "parent_id": attachment["parent_id"],
                "path": str(path),
                "sha256": digest,
                "role": role,
                "source_receipt": str(receipt_path),
                "source_receipt_sha256": fingerprint(receipt_path),
            }
        )
    report["role_counts"] = dict(roles)
    check(
        "expected_distinct_attachment_roles",
        roles == Counter({"SUPPLEMENT": 3, "PEER_REVIEW": 1, "SOURCE_DATA": 1}),
        actual=dict(roles),
    )
    check(
        "each_paper_has_one_actual_si",
        all(
            sum(
                a["parent_id"] == paper_id and a["role"] == "SUPPLEMENT"
                for a in registry["attachments"].values()
            )
            == 1
            for paper_id in sources
        ),
    )

    current_by_hash = {}
    for path in library.rglob("*"):
        if path.is_file() and not path.is_relative_to(library / ".an-workbench"):
            safe = inside(path)
            current_by_hash.setdefault(fingerprint(safe), []).append(str(safe))
    baseline = read_json(base / "baseline-files.json")
    report["baseline_comparison"] = [
        {
            "original_path": item["path"],
            "sha256": item["sha256"],
            "current_matches": current_by_hash.get(item["sha256"], []),
            "preserved": bool(current_by_hash.get(item["sha256"])),
        }
        for item in baseline
    ]
    check(
        "all_baseline_original_bytes_preserved",
        all(item["preserved"] for item in report["baseline_comparison"]),
        checked=len(baseline),
    )
    report["baseline_scope_note"] = (
        "The baseline contains 18 files, including 7 PDFs and immutable receipts/sidecars. The XLSX body was not itself listed; its preserved baseline receipt binds its exact current SHA-256."
    )

    report["task_snapshot"] = []
    for path in sorted((workspace / "tasks").glob("*.json")):
        task = read_json(path)
        items = (task.get("result") or {}).get("items", [])
        report["task_snapshot"].append(
            {
                "id": task["id"],
                "kind": task["kind"],
                "status": task["status"],
                "updated_at": task.get("updated_at"),
                "item_statuses": dict(Counter(row.get("status") for row in items)),
            }
        )

    report["model_ledger_snapshot"] = []
    for path in sorted((workspace / "translations").glob("*.json")):
        ledger = read_json(path)
        model = ledger["options"]["model"]
        price_in, price_out = (
            model["input_cost_per_million"],
            model["output_cost_per_million"],
        )
        price_cached = model.get("cached_input_cost_per_million", price_in)
        call_rows = []
        for call in ledger.get("calls", []):
            usage = call.get("usage") or {}
            if "input_tokens" in usage and "output_tokens" in usage:
                cached = usage.get("cached_input_tokens", 0)
                computed = (
                    (usage["input_tokens"] - cached) * price_in
                    + cached * price_cached
                    + usage["output_tokens"] * price_out
                ) / 1_000_000
                check(
                    "translation_cost_matches_configured_prices",
                    math.isclose(computed, call["estimated_cost"], abs_tol=1e-12),
                    receipt=path.name,
                )
            else:
                computed = None
            call_rows.append(
                {
                    "status": call.get("status"),
                    "usage": usage,
                    "estimated_cost": call.get("estimated_cost"),
                    "computed_cost": computed,
                    "reserved_cost": call.get("reserved_cost"),
                    "currency": call.get("currency"),
                }
            )
        report["model_ledger_snapshot"].append(
            {
                "receipt": str(path),
                "phase": "title_translation",
                "model": model["name"],
                "status": ledger.get("status"),
                "calls": call_rows,
                "accounted_cost": ledger.get("accounted_cost"),
                "billing_uncertain": ledger.get("billing_uncertain"),
            }
        )
    report["cost_scope_note"] = (
        "Configured-price estimates from saved ledgers, not provider invoices. No model/network request was issued by this audit; native research ledgers require a later snapshot after the live run."
    )
    report["registry_sha256_at_read"] = hashlib.sha256(registry_bytes).hexdigest()
    report["registry_unchanged_during_audit"] = (
        registry_bytes == registry_path.read_bytes()
    )
    report["read_only_note"] = (
        "Only the designated report is written; library/sidecars/task JSON are not refreshed or modified. Live task/metadata updates may continue in the UI process."
    )
    report["status"] = (
        "PASSED" if all(item["passed"] for item in report["checks"]) else "FAILED"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    output = audit(args.root)
    # This explicit output is the sole mutation; no application service is used.
    args.report.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": output["status"],
                "checks": len(output["checks"]),
                "papers": len(output["papers"]),
                "roles": output["role_counts"],
                "failed": [row for row in output["checks"] if not row["passed"]],
                "report": str(args.report),
            },
            ensure_ascii=False,
        )
    )
