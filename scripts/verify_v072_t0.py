"""Verify an external frozen T0 corpus; never copy answer values into AN output.

The dataset and copyrighted PDFs remain outside the repository. Numeric presence
is a locator check, not a claim that an experimental measurement was interpreted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from decimal import Decimal
from pathlib import Path

from aletheia_nexus.content.corpus import load_corpus, search_corpus
from aletheia_nexus.content.evidence import build_evidence_pack, evidence_markdown
from aletheia_nexus.content.export import write_ai_export
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.query import normalize_search_text


def numeric_presence(text: str, value: object) -> bool:
    expected = Decimal(str(value))
    normalized = normalize_search_text(text)
    for match in re.finditer(
        r"(?<![\d.])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?(?![\d.])", normalized
    ):
        token = match.group()
        if (
            token.startswith("-")
            and match.start()
            and normalized[match.start() - 1].isdigit()
        ):
            token = token[1:]  # Upper endpoint of a written numeric range.
        if Decimal(token) == expected:
            return True
    return False


def verify(dataset: Path, corpus: Path, output: Path) -> dict:
    manifest = json.loads((dataset / "manifest.json").read_text("utf-8"))
    cases = json.loads((dataset / "acceptance_cases.json").read_text("utf-8"))
    loaded = load_corpus(corpus)
    by_hash = {
        entry.document["source"]["pdf_sha256"]: entry for entry in loaded.documents
    }
    output.mkdir(parents=True, exist_ok=True)
    frozen = []
    for document in manifest["documents"]:
        matched = by_hash.get(document["sha256"])
        frozen.append(
            {
                "doc_id": document["doc_id"],
                "source_sha256": document["sha256"],
                "frozen_pdf_unchanged": sha256_file(dataset / document["source_file"])
                == document["sha256"],
                "corpus_pdf_matched": matched is not None,
                "role_matched": matched is not None
                and matched.document["source"]["document_role"] == document["role"],
            }
        )
    query_results = []
    for query in cases["queries"]:
        snapshot = search_corpus(
            loaded,
            " ".join('"' + term + '"' for term in query["query_terms"]),
            limit=10000,
        )
        hits = [
            h
            for h in snapshot["hits"]
            if h["source"]["pdf_sha256"] == query["source_sha256"]
        ]
        anchored = [
            h for h in hits if set(h["pages"]) & set(query["expected_pdf_pages"])
        ]
        picked = (anchored or hits)[:1]
        exported_pages = []
        if picked:
            # The researcher explicitly asks for the dataset's condition pages.
            extras = {picked[0]["id"]: query["context_pages"]}
            pack = build_evidence_pack(
                loaded,
                report=snapshot,
                selectors=[picked[0]["id"]],
                context_pages=0,
                extra_pages=extras,
            )
            pack["corpus_root"] = os.path.relpath(corpus.resolve(), output.resolve())
            exported_pages = pack["included"][0]["pages_requested"]
            write_ai_export(
                output / f"{query['case_id']}-evidence.json",
                json.dumps(pack, ensure_ascii=False, indent=2),
                overwrite=True,
            )
            write_ai_export(
                output / f"{query['case_id']}-evidence.md",
                evidence_markdown(pack),
                overwrite=True,
            )
        snapshot["corpus_root"] = os.path.relpath(corpus.resolve(), output.resolve())
        write_ai_export(
            output / f"{query['case_id']}-results.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            overwrite=True,
        )
        query_results.append(
            {
                "case_id": query["case_id"],
                "question": query["question"],
                "doc_id": query["doc_id"],
                "query_terms": query["query_terms"],
                "anchor_located": bool(anchored),
                "first_anchor_rank": anchored[0]["number"] if anchored else None,
                "first_paper_rank": hits[0]["number"] if hits else None,
                "total_hits": snapshot["total_hits"],
                "equivalent_paper_hit": bool(hits),
                "expected_pdf_pages": query["expected_pdf_pages"],
                "hit_pages": sorted({p for h in hits for p in h["pages"]}),
                "required_context_pages": query["context_pages"],
                "exported_context_pages": exported_pages,
                "context_pages_included": set(query["context_pages"])
                <= set(exported_pages),
                "selected_hit_id": picked[0]["id"] if picked else None,
                "uncertain": picked[0]["uncertain"] if picked else None,
                "avoid_misreading": query["avoid_misreading"],
            }
        )
    numbers = []
    for value in cases["values"]:
        entry = by_hash.get(value["source_sha256"])
        blocks = (
            [b for b in entry.document["blocks"] if b["page"] in value["pdf_pages"]]
            if entry
            else []
        )
        candidates = [b for b in blocks if numeric_presence(b["text"], value["value"])]
        upper = value.get("value_upper")
        upper_present = upper is None or any(
            numeric_presence(b["text"], upper) for b in blocks
        )
        numbers.append(
            {
                "assertion_id": value["assertion_id"],
                "case_id": value["case_id"],
                "doc_id": value["doc_id"],
                "reference_literal": value["literal"],
                "metric": value["metric"],
                "conditions": value["conditions"],
                "note": value["note"],
                "pdf_pages": value["pdf_pages"],
                "numeric_text_present": bool(candidates) and upper_present,
                "candidate_blocks": [
                    {
                        "id": b["id"],
                        "text": b["text"],
                        "uncertain": b["uncertain"],
                        "method": b["extraction_method"],
                        "page": b["page"],
                    }
                    for b in candidates
                ],
                "source_review_required": not candidates
                or any(b["uncertain"] for b in candidates),
                "interpretation": "Presence is a navigation check only; signs, units, metric/row assignment and conditions require comparison with the frozen PDF.",
            }
        )
    report = {
        "dataset_id": manifest["dataset_id"],
        "source_files": frozen,
        "coverage": loaded.coverage,
        "queries": query_results,
        "numeric_checks": numbers,
        "summary": {
            "documents": len(frozen),
            "queries": len(query_results),
            "anchors_located": sum(q["anchor_located"] for q in query_results),
            "condition_pages_included": sum(
                q["context_pages_included"] for q in query_results
            ),
            "numeric_assertions": len(numbers),
            "numeric_text_present": sum(n["numeric_text_present"] for n in numbers),
            "numeric_assertions_requiring_source_review": sum(
                n["source_review_required"] for n in numbers
            ),
        },
        "scientific_validation": "This execution checks retrieval, numeric text presence and source context. It does not automatically verify experimental claims or resolve source contradictions.",
    }
    write_ai_export(
        output / "t0-report.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        overwrite=True,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.dataset, args.corpus, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return (
        0
        if all(
            q["anchor_located"] and q["context_pages_included"]
            for q in report["queries"]
        )
        and all(
            all(
                item[k]
                for k in ("frozen_pdf_unchanged", "corpus_pdf_matched", "role_matched")
            )
            for item in report["source_files"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
