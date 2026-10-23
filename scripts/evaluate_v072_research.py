"""Quantify a frozen external research corpus without treating matches as truth.

No third-party PDFs or scientific answer values are included in this script.
Hit@k is a designated-anchor success rate, not precision or exhaustive recall.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from pathlib import Path

from aletheia_nexus.content.corpus import content_units, load_corpus, search_corpus
from aletheia_nexus.content.evidence import build_evidence_pack
from aletheia_nexus.content.export import write_ai_export
from aletheia_nexus.content.gate import sha256_file


def ratio(correct: int, total: int) -> dict:
    return {
        "correct": correct,
        "total": total,
        "fraction": correct / total if total else None,
    }


def latency(seconds: list[float]) -> dict:
    ordered = sorted(seconds)
    return {
        "n": len(seconds),
        "median_seconds": statistics.median(seconds),
        "p95_seconds": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
        "max_seconds": max(seconds),
        "raw_seconds": seconds,
        "percentile_method": "nearest rank",
    }


def evaluate(dataset: Path, corpus: Path, *, repetitions: int = 3) -> dict:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    cases = json.loads((dataset / "acceptance_cases.json").read_text("utf-8"))
    manifest = json.loads((dataset / "manifest.json").read_text("utf-8"))
    first = cases["queries"][0]
    reload_times = []
    for _ in range(repetitions):
        start = time.perf_counter()
        loaded = load_corpus(corpus)
        search_corpus(loaded, " ".join(first["query_terms"]))
        reload_times.append(time.perf_counter() - start)
    entries = {
        entry.document["source"]["pdf_sha256"]: entry for entry in loaded.documents
    }
    query_rows, search_times, export_times = [], [], []
    counters = {
        k: [0, 0]
        for k in (
            "export_source_links",
            "requested_context_pages",
            "canonical_text",
            "uncertainty_propagation",
            "table_disclosures",
            "figure_disclosures",
            "document_accounting",
            "budget_integrity",
        )
    }

    def count(key: str, passed: bool):
        counters[key][0] += int(passed)
        counters[key][1] += 1

    for q in cases["queries"]:
        text = " ".join('"' + term + '"' for term in q["query_terms"])
        for _ in range(repetitions):
            start = time.perf_counter()
            result = search_corpus(loaded, text, limit=10000)
            search_times.append(time.perf_counter() - start)
        relevant = [
            h
            for h in result["hits"]
            if h["source"]["pdf_sha256"] == q["source_sha256"]
            and set(h["pages"]) & set(q["expected_pdf_pages"])
        ]
        rank = relevant[0]["number"] if relevant else None
        query_rows.append(
            {
                "case_id": q["case_id"],
                "query_terms": q["query_terms"],
                "first_anchor_rank": rank,
                "total_hits": result["total_hits"],
            }
        )
        if not relevant:
            count("requested_context_pages", False)
            continue
        hit = relevant[0]
        extras = {hit["id"]: q["context_pages"]}
        start = time.perf_counter()
        pack = build_evidence_pack(
            loaded,
            report=result,
            selectors=[hit["id"]],
            context_pages=0,
            extra_pages=extras,
        )
        export_times.append(time.perf_counter() - start)
        item = pack["included"][0]
        entry = entries[q["source_sha256"]]
        canonical = {b["id"]: b for b in entry.document["blocks"]}
        anchors = {a["id"]: a for a in entry.document["anchors"]}
        for page in q["context_pages"]:
            count("requested_context_pages", page in item["pages_requested"])
        for block in item["blocks"]:
            original = canonical[block["id"]]
            count("canonical_text", block["text"] == original["text"])
            count(
                "export_source_links",
                block["evidence"] == anchors[original["anchor_id"]]
                and block["page"] == original["page"]
                and 1 <= block["page"] <= entry.document["source"]["page_count"],
            )
            if original["uncertain"]:
                count("uncertainty_propagation", block["uncertain"])
        exported_ids = {b["id"] for b in item["blocks"]}
        exported_blocks = {b["id"]: b for b in item["blocks"]}
        table_records = {t["id"]: t for t in item["tables"]}
        for unit in content_units(entry.document):
            present = exported_ids.intersection(unit["block_ids"])
            if unit["kind"] == "table" and present:
                table = table_records.get(unit["id"])
                count(
                    "table_disclosures",
                    bool(
                        table
                        and table["uncertain"]
                        and table["interpretation_status"] == "not-interpreted"
                        and all(exported_blocks[bid]["uncertain"] for bid in present)
                    ),
                )
        figure_records = {f["id"]: f for f in item["figures"]}
        for figure in entry.document["figures"]:
            if figure["caption_block_id"] in exported_ids or any(
                o["page"] in item["pages_requested"] for o in figure["source_objects"]
            ):
                exported = figure_records.get(figure["id"])
                count(
                    "figure_disclosures",
                    bool(
                        exported
                        and exported["source_objects"] == figure["source_objects"]
                        and exported["image_text_completeness"] == "not-verified"
                    ),
                )
        all_ids = {e.document["artifact_id"] for e in loaded.documents}
        included_ids = {i["parsed_artifact_id"] for i in pack["included"]}
        skipped_ids = {i["parsed_artifact_id"] for i in pack["skipped"]}
        count(
            "document_accounting",
            included_ids | skipped_ids == all_ids and not included_ids & skipped_ids,
        )
        for budget in (100, 5000, 25000):
            limited = build_evidence_pack(
                loaded,
                report=result,
                selectors=[hit["id"]],
                context_pages=0,
                extra_pages=extras,
                max_characters=budget,
            )
            count(
                "budget_integrity",
                limited["size"]["text_characters"] <= budget
                and (
                    not limited["included"] or limited["included"] == pack["included"]
                ),
            )
    n = len(query_rows)
    ranks = [q["first_anchor_rank"] for q in query_rows]
    totals = {
        "documents": len(loaded.documents),
        "pages": sum(e.document["source"]["page_count"] for e in loaded.documents),
        "pdf_bytes": sum(e.pdf.stat().st_size for e in loaded.documents),
        "blocks": sum(len(e.document["blocks"]) for e in loaded.documents),
        "text_characters": sum(
            len(b["text"]) for e in loaded.documents for b in e.document["blocks"]
        ),
    }
    return {
        "schema": "aletheia-nexus/research-evaluation/v1",
        "dataset_id": manifest["dataset_id"],
        "platform": platform.platform(),
        "python": platform.python_version(),
        "definitions": {
            "retrieval": "Fixed literal queries; relevant means the designated PDF and at least one specified anchor page. Other relevant locations are not judged, so this is not precision or exhaustive recall.",
            "source_links": "PDF SHA-256/role plus unchanged canonical block text, page and anchor references; does not independently prove bounding-box geometry or scientific truth.",
            "latency": "Synchronous wall time; repeated reads do not flush OS file cache. In-memory search uses an already verified corpus; no persistent index.",
            "numeric_accuracy": "Requires separate source-reviewed records; presence-only checks are not an accuracy score.",
        },
        "corpus": totals,
        "coverage": loaded.coverage,
        "source_integrity": ratio(
            sum(
                sha256_file(dataset / d["source_file"]) == d["sha256"]
                and d["sha256"] in entries
                and entries[d["sha256"]].document["source"]["document_role"]
                == d["role"]
                for d in manifest["documents"]
            ),
            len(manifest["documents"]),
        ),
        "retrieval": {
            **{
                f"hit_at_{k}": ratio(sum(r is not None and r <= k for r in ranks), n)
                for k in (1, 5, 20)
            },
            "mean_reciprocal_rank": sum(1 / r if r else 0 for r in ranks) / n,
            "queries": query_rows,
        },
        "export": {k: ratio(*value) for k, value in counters.items()},
        "performance": {
            "reload_and_first_query": latency(reload_times),
            "in_memory_query": latency(search_times),
            "selected_export_build": latency(export_times),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    report = evaluate(args.dataset, args.corpus, repetitions=args.repetitions)
    write_ai_export(
        args.output,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        overwrite=True,
    )
    print(
        json.dumps(
            {
                "corpus": report["corpus"],
                "retrieval": {
                    k: v for k, v in report["retrieval"].items() if k != "queries"
                },
                "export": report["export"],
                "performance": {
                    k: {a: b for a, b in v.items() if a != "raw_seconds"}
                    for k, v in report["performance"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return (
        0
        if report["source_integrity"]["fraction"] == 1
        and report["retrieval"]["hit_at_20"]["fraction"] == 1
        and all(v["fraction"] in (1, None) for v in report["export"].values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
