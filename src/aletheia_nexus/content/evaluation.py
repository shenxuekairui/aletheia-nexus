"""Offline evaluation over a frozen, rights-cleared parser fixture manifest."""

from __future__ import annotations

import hashlib
import json
import platform
import time
import tracemalloc
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from tempfile import TemporaryDirectory

from aletheia_nexus.content.errors import ParserInputError
from aletheia_nexus.content.service import parse_document


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contains_in_order(values: list[str], needles: list[str]) -> bool:
    cursor = 0
    for needle in needles:
        while cursor < len(values) and needle not in values[cursor]:
            cursor += 1
        if cursor == len(values):
            return False
        cursor += 1
    return True


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _text_edit_counts(expected: str, actual: str) -> dict[str, int]:
    """Return auditable character deletion/insertion/substitution counts."""

    expected = _normalized_text(expected)
    actual = _normalized_text(actual)
    deletions = insertions = substitutions = 0
    for tag, expected_start, expected_end, actual_start, actual_end in SequenceMatcher(
        None, expected, actual, autojunk=False
    ).get_opcodes():
        expected_length = expected_end - expected_start
        actual_length = actual_end - actual_start
        if tag == "delete":
            deletions += expected_length
        elif tag == "insert":
            insertions += actual_length
        elif tag == "replace":
            substitutions += min(expected_length, actual_length)
            deletions += max(0, expected_length - actual_length)
            insertions += max(0, actual_length - expected_length)
    return {
        "expected_characters": len(expected),
        "actual_characters": len(actual),
        "deletions": deletions,
        "insertions": insertions,
        "substitutions": substitutions,
    }


def _duplicate_block_characters(blocks: list[dict[str, object]]) -> int:
    normalized = [_normalized_text(str(item["text"])).casefold() for item in blocks]
    counts = Counter(value for value in normalized if value)
    return sum(len(value) * (count - 1) for value, count in counts.items() if count > 1)


def evaluate_manifest(manifest_path: str | Path) -> dict[str, object]:
    manifest_file = Path(manifest_path)
    root = manifest_file.parent
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if manifest.get("schema") != "aletheia-nexus/parser-fixture-manifest/v1":
        raise ValueError("unsupported fixture manifest schema")
    if not isinstance(entries, list) or not entries:
        raise ValueError("fixture manifest needs a non-empty entries list")

    records: list[dict[str, object]] = []
    anchor_total = anchor_correct = section_total = section_found = 0
    links_expected = links_actual = links_correct = 0
    table_structures_total = table_structures_correct = 0
    figure_objects_total = figure_objects_correct = 0
    references_total = references_correct = 0
    gate_total = gate_correct = 0
    order_total = order_correct = 0
    expected_characters = actual_characters = 0
    deletions = insertions = substitutions = 0
    duplicate_characters = parsed_characters = 0
    started = time.perf_counter()
    tracemalloc.start()
    try:
        with TemporaryDirectory(prefix="an-v07-eval-") as temp_dir:
            output_root = Path(temp_dir)
            for entry in entries:
                pdf = root / entry["pdf"]
                sidecar = root / entry["sidecar"]
                for path, key in ((pdf, "pdf_sha256"), (sidecar, "sidecar_sha256")):
                    if _sha256(path) != entry[key]:
                        raise ValueError(f"frozen hash mismatch for {path.name}")
                if entry.get("gold") is not None:
                    gold_path = root / entry["gold"]
                    if _sha256(gold_path) != entry.get("gold_sha256"):
                        raise ValueError(f"frozen hash mismatch for {gold_path.name}")
                gate_total += 1
                expected_gate = entry["expected_gate"]
                item_started = time.perf_counter()
                try:
                    result = parse_document(
                        pdf,
                        entry["doi"],
                        sidecar_path=sidecar,
                        output_path=output_root / f"{entry['id']}.parsed.json",
                        created_at="2026-09-28T00:00:00+00:00",
                    )
                except ParserInputError as exc:
                    passed = exc.code.value == expected_gate
                    gate_correct += int(passed)
                    records.append(
                        {
                            "id": entry["id"],
                            "gate": exc.code.value,
                            "gate_correct": passed,
                            "runtime_seconds": time.perf_counter() - item_started,
                        }
                    )
                    continue
                gate_passed = expected_gate == "PASS"
                gate_correct += int(gate_passed)
                if not gate_passed:
                    records.append(
                        {
                            "id": entry["id"],
                            "gate": "PASS",
                            "gate_correct": False,
                            "status": result.status,
                            "runtime_seconds": time.perf_counter() - item_started,
                        }
                    )
                    continue
                gold = json.loads((root / entry["gold"]).read_text(encoding="utf-8"))
                document = result.document
                parsed_characters += sum(
                    len(_normalized_text(str(item["text"])))
                    for item in document["blocks"]
                )
                duplicate_characters += _duplicate_block_characters(document["blocks"])
                text_metrics = {
                    "expected_characters": 0,
                    "actual_characters": 0,
                    "deletions": 0,
                    "insertions": 0,
                    "substitutions": 0,
                }
                blocks_by_page: dict[int, list[str]] = {}
                for block in document["blocks"]:
                    blocks_by_page.setdefault(int(block["page"]), []).append(
                        str(block["text"])
                    )
                for expected_page in gold.get("text_pages", []):
                    page_number = int(expected_page["page"])
                    page_metrics = _text_edit_counts(
                        str(expected_page["text"]),
                        " ".join(blocks_by_page.get(page_number, [])),
                    )
                    for key in text_metrics:
                        text_metrics[key] += page_metrics[key]
                expected_characters += text_metrics["expected_characters"]
                actual_characters += text_metrics["actual_characters"]
                deletions += text_metrics["deletions"]
                insertions += text_metrics["insertions"]
                substitutions += text_metrics["substitutions"]
                anchors = document["anchors"]
                for expected in gold.get("selected_anchors", []):
                    anchor_total += 1
                    if any(
                        anchor["page"] == expected["page"]
                        and expected["text"] in anchor["text_evidence"]
                        and anchor["anchored"]
                        for anchor in anchors
                    ):
                        anchor_correct += 1
                actual_sections = [item["heading"] for item in document["sections"]]
                for heading in gold.get("sections", []):
                    section_total += 1
                    section_found += int(heading in actual_sections)
                for key in ("figures", "tables"):
                    actual = document[key]
                    links_actual += len(actual)
                    for expected in gold.get(key, []):
                        links_expected += 1
                        links_correct += int(
                            any(
                                item["label"] == expected["label"]
                                and expected["caption_contains"] in item["caption"]
                                and item["caption_block_id"]
                                and item["anchor_id"]
                                for item in actual
                            )
                        )
                for expected in gold.get("tables", []):
                    if "cells" not in expected:
                        continue
                    table_structures_total += 1
                    actual = next(
                        (
                            item
                            for item in document["tables"]
                            if item["label"] == expected["label"]
                        ),
                        None,
                    )
                    if actual is not None:
                        matrix = [
                            [
                                next(
                                    (
                                        cell["text"]
                                        for cell in actual["cells"]
                                        if cell["row"] == row
                                        and cell["column"] == column
                                    ),
                                    None,
                                )
                                for column in range(1, int(actual["column_count"]) + 1)
                            ]
                            for row in range(1, int(actual["row_count"]) + 1)
                        ]
                        table_structures_correct += int(
                            actual["row_count"] == expected["row_count"]
                            and actual["column_count"] == expected["column_count"]
                            and matrix == expected["cells"]
                        )
                for expected in gold.get("figures", []):
                    if "source_object_count" not in expected:
                        continue
                    figure_objects_total += 1
                    figure_objects_correct += int(
                        any(
                            item["label"] == expected["label"]
                            and item["association"] == expected["association"]
                            and len(item.get("source_objects", []))
                            == expected["source_object_count"]
                            for item in document["figures"]
                        )
                    )
                for expected in gold.get("references", []):
                    references_total += 1
                    references_correct += int(
                        any(
                            item["label"] == expected["label"]
                            and item["resolved"] is expected["resolved"]
                            for item in document["references"]
                        )
                    )
                expected_order = gold.get("reading_order", [])
                if expected_order:
                    order_total += 1
                    order_correct += int(
                        _contains_in_order(
                            [str(item["text"]) for item in document["blocks"]],
                            expected_order,
                        )
                    )
                warning_codes = {item["code"] for item in document["warnings"]}
                expected_warnings = set(gold.get("warning_codes", []))
                records.append(
                    {
                        "id": entry["id"],
                        "gate": "PASS",
                        "gate_correct": gate_passed,
                        "status": result.status,
                        "status_correct": result.status == gold["expected_status"],
                        "warnings_correct": expected_warnings <= warning_codes,
                        "anchored_blocks": sum(
                            bool(item["anchored"]) for item in anchors
                        ),
                        "blocks": len(document["blocks"]),
                        "text_error_counts": text_metrics,
                        "runtime_seconds": time.perf_counter() - item_started,
                    }
                )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    anchored_blocks = sum(int(item.get("anchored_blocks", 0)) for item in records)
    total_blocks = sum(int(item.get("blocks", 0)) for item in records)
    structural_total = (
        section_total
        + links_expected
        + table_structures_total
        + figure_objects_total
        + references_total
        + order_total
    )
    structural_correct = (
        section_found
        + links_correct
        + table_structures_correct
        + figure_objects_correct
        + references_correct
        + order_correct
    )
    information_loss = deletions + substitutions
    total_text_errors = information_loss + insertions
    return {
        "schema": "aletheia-nexus/parser-evaluation/v1",
        "manifest_sha256": _sha256(manifest_file),
        "fixture_count": len(entries),
        "metrics": {
            "doi_hash_gate": {"correct": gate_correct, "total": gate_total},
            "anchored_block_coverage": {
                "correct": anchored_blocks,
                "total": total_blocks,
            },
            "selected_anchor_correctness": {
                "correct": anchor_correct,
                "total": anchor_total,
            },
            "section_recall": {"correct": section_found, "total": section_total},
            "table_figure_link_precision": {
                "correct": links_correct,
                "total": links_actual,
            },
            "table_figure_link_omissions": links_expected - links_correct,
            "table_figure_false_associations": links_actual - links_correct,
            "table_structure_correctness": {
                "correct": table_structures_correct,
                "total": table_structures_total,
            },
            "figure_object_association": {
                "correct": figure_objects_correct,
                "total": figure_objects_total,
            },
            "reference_resolution": {
                "correct": references_correct,
                "total": references_total,
            },
            "reading_order": {"correct": order_correct, "total": order_total},
            "character_accuracy": {
                "expected_characters": expected_characters,
                "actual_characters": actual_characters,
                "deletions": deletions,
                "insertions": insertions,
                "substitutions": substitutions,
                "information_loss_rate": (
                    information_loss / expected_characters
                    if expected_characters
                    else None
                ),
                "character_error_rate": (
                    total_text_errors / expected_characters
                    if expected_characters
                    else None
                ),
            },
            "duplicate_text_rate": {
                "duplicate_characters": duplicate_characters,
                "parsed_characters": parsed_characters,
                "ratio": (
                    duplicate_characters / parsed_characters
                    if parsed_characters
                    else 0.0
                ),
            },
            "structural_recall": {
                "correct": structural_correct,
                "total": structural_total,
                "ratio": (
                    structural_correct / structural_total if structural_total else None
                ),
            },
        },
        "runtime_seconds": time.perf_counter() - started,
        "peak_memory_bytes": peak,
        "platform": platform.platform(),
        "records": records,
    }
