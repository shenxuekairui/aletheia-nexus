"""Validation and deterministic persistence for parsed-document v2."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from aletheia_nexus.content.geometry import CANONICAL_COORDINATE_SYSTEM

PARSED_DOCUMENT_SCHEMA = "aletheia-nexus/parsed-document/v2"
PARSED_STATUSES = frozenset({"PARSED", "PARTIAL", "FAILED"})
BLOCK_KINDS = frozenset(
    {"paragraph", "heading", "caption", "equation", "reference", "other"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID = re.compile(r"^an:(?:source|parsed):(?:v2:)?sha256:[0-9a-f]{64}$")


def _is_safe_relative_locator(value: str) -> bool:
    if "://" in value:
        return False
    posix = PurePosixPath(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        return False
    return ".." not in posix.parts and ".." not in windows.parts


def compute_parsed_artifact_id(document: dict[str, object]) -> str:
    """Return a path- and timestamp-independent content identity."""

    payload = json.loads(json.dumps(document, allow_nan=False))
    payload.pop("artifact_id", None)
    payload.pop("created_at", None)
    source = payload.get("source")
    if isinstance(source, dict):
        source.pop("locators", None)
    return f"an:parsed:v2:sha256:{_fingerprint(payload)}"


def validate_parsed_document(document: object) -> None:
    """Validate required v2 fields and all internal identifiers/references."""

    if not isinstance(document, dict):
        raise ValueError("parsed document must be an object")
    if document.get("schema") != PARSED_DOCUMENT_SCHEMA:
        raise ValueError("unsupported parsed-document schema")
    if document.get("status") not in PARSED_STATUSES:
        raise ValueError("status must be PARSED, PARTIAL, or FAILED")
    created_at = document.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("created_at must be an ISO-8601 timestamp string")
    try:
        parsed_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at must be an ISO-8601 timestamp string") from exc
    if parsed_time.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    artifact_id = document.get("artifact_id")
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        raise ValueError("artifact_id must be a canonical parsed SHA-256 identity")
    parser = document.get("parser")
    if not isinstance(parser, dict) or not all(
        isinstance(parser.get(key), str) and parser.get(key)
        for key in ("name", "version", "configuration_fingerprint")
    ):
        raise ValueError("parser identity and configuration fingerprint are required")
    configuration = parser.get("configuration")
    if not isinstance(configuration, dict):
        raise ValueError("parser.configuration must be an object")
    if not _SHA256.fullmatch(str(parser["configuration_fingerprint"])):
        raise ValueError("parser configuration fingerprint must be a lowercase SHA-256")
    expected_configuration_fingerprint = _fingerprint(configuration)
    if parser["configuration_fingerprint"] != expected_configuration_fingerprint:
        raise ValueError(
            "parser configuration fingerprint does not match configuration"
        )
    if not _SHA256.fullmatch(str(parser.get("execution_fingerprint"))):
        raise ValueError("parser execution fingerprint must be a lowercase SHA-256")
    backend = parser.get("backend")
    if not isinstance(backend, dict) or not all(
        isinstance(backend.get(key), str) and backend.get(key)
        for key in ("name", "version")
    ):
        raise ValueError("parser.backend needs name and version")
    stages = parser.get("pipeline_stages")
    if (
        not isinstance(stages, list)
        or not stages
        or any(not isinstance(item, str) or not item for item in stages)
        or len(stages) != len(set(stages))
    ):
        raise ValueError("parser.pipeline_stages must contain unique stage names")
    execution_payload = {
        "backend": backend,
        "configuration": configuration,
        "parser": {"name": parser["name"], "version": parser["version"]},
        "stages": stages,
    }
    if parser["execution_fingerprint"] != _fingerprint(execution_payload):
        raise ValueError("parser execution fingerprint does not match pipeline")
    source = document.get("source")
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    for key in (
        "doi",
        "pdf_sha256",
        "acquisition_sidecar_sha256",
        "page_count",
        "acquisition_schema",
        "artifact_id",
        "locators",
    ):
        if key not in source:
            raise ValueError(f"source is missing {key}")
    if not isinstance(source["doi"], str) or not source["doi"]:
        raise ValueError("source.doi must be a non-empty string")
    for key in ("acquisition_schema", "artifact_id"):
        if not isinstance(source[key], str) or not source[key]:
            raise ValueError(f"source.{key} must be a non-empty string")
    if (
        isinstance(source["page_count"], bool)
        or not isinstance(source["page_count"], int)
        or source["page_count"] < 1
    ):
        raise ValueError("source.page_count must be a positive integer")
    for key in ("pdf_sha256", "acquisition_sidecar_sha256"):
        if not isinstance(source[key], str) or not _SHA256.fullmatch(source[key]):
            raise ValueError(f"source.{key} must be a lowercase SHA-256")
    if source["artifact_id"] != f"an:source:sha256:{source['pdf_sha256']}":
        raise ValueError("source.artifact_id does not match source.pdf_sha256")
    locators = source["locators"]
    if not isinstance(locators, dict):
        raise ValueError("source.locators must be an object")
    if not set(locators) <= {"pdf", "acquisition_sidecar"}:
        raise ValueError("source.locators contains an unsupported locator")
    for key in ("pdf", "acquisition_sidecar"):
        value = locators.get(key)
        if value is not None and (
            not isinstance(value, str)
            or not value
            or not _is_safe_relative_locator(value)
        ):
            raise ValueError(f"source.locators.{key} must be a relative local path")
    for key in ("warnings", "errors", "sections", "blocks", "anchors"):
        if not isinstance(document.get(key), list):
            raise ValueError(f"{key} must be a list")
    for key in ("references", "figures", "tables"):
        if not isinstance(document.get(key), list):
            raise ValueError(f"{key} must be a list")
    pages = document.get("pages")
    if not isinstance(pages, list):
        raise ValueError("pages must be a list")
    page_metadata: dict[int, dict[str, object]] = {}
    for index, page_item in enumerate(pages):
        if not isinstance(page_item, dict):
            raise ValueError(f"pages[{index}] must be an object")
        page_number = page_item.get("page")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= source["page_count"]
            or page_number in page_metadata
        ):
            raise ValueError(f"pages[{index}].page is invalid or duplicated")
        dimensions = (page_item.get("width"), page_item.get("height"))
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
            for value in dimensions
        ):
            raise ValueError(f"pages[{index}] has invalid dimensions")
        if page_item.get("rotation") not in {0, 90, 180, 270}:
            raise ValueError(f"pages[{index}] has invalid rotation")
        if page_item.get("coordinate_system") != CANONICAL_COORDINATE_SYSTEM:
            raise ValueError(f"pages[{index}] has an unsupported coordinate system")
        for box_name in ("media_box", "crop_box"):
            box = page_item.get(box_name)
            if box is not None and (
                not isinstance(box, list)
                or len(box) != 4
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in box
                )
                or box[2] <= box[0]
                or box[3] <= box[1]
            ):
                raise ValueError(f"pages[{index}].{box_name} is invalid")
        page_metadata[page_number] = page_item
    for label in ("warnings", "errors"):
        for index, message in enumerate(document[label]):
            if not isinstance(message, dict) or not all(
                isinstance(message.get(key), str) and message.get(key)
                for key in ("code", "detail")
            ):
                raise ValueError(f"{label}[{index}] needs code and detail strings")
            if "page" in message and (
                isinstance(message["page"], bool)
                or not isinstance(message["page"], int)
                or not 1 <= message["page"] <= source["page_count"]
            ):
                raise ValueError(f"{label}[{index}].page is out of range")
            for key in ("stage", "backend"):
                if key in message and (
                    not isinstance(message[key], str) or not message[key]
                ):
                    raise ValueError(f"{label}[{index}].{key} must be a string")
            if "degraded" in message and not isinstance(message["degraded"], bool):
                raise ValueError(f"{label}[{index}].degraded must be a boolean")
            if "reason" in message and (
                not isinstance(message["reason"], str) or not message["reason"]
            ):
                raise ValueError(f"{label}[{index}].reason must be a string")
    quality = document.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("quality must be an object")
    _validate_coverage(
        quality.get("page_coverage"),
        label="quality.page_coverage",
        numerator="parsed",
        expected_total=source["page_count"],
        expected_numerator=len(pages),
    )

    blocks = document["blocks"]
    anchors = document["anchors"]
    block_ids = _unique_ids(blocks, "blocks")
    anchor_ids = _unique_ids(anchors, "anchors")
    section_ids = _unique_ids(document["sections"], "sections")
    _unique_ids(document["references"], "references")
    figure_ids = _unique_ids(document["figures"], "figures")
    table_ids = _unique_ids(document["tables"], "tables")
    object_ids = figure_ids | table_ids
    block_orders: set[int] = set()

    for index, block in enumerate(blocks):
        if block.get("kind") not in BLOCK_KINDS:
            raise ValueError(f"blocks[{index}] has unsupported kind")
        if not isinstance(block.get("text"), str):
            raise ValueError(f"blocks[{index}].text must be a string")
        if (
            isinstance(block.get("page"), bool)
            or not isinstance(block.get("page"), int)
            or not 1 <= block["page"] <= source["page_count"]
        ):
            raise ValueError(f"blocks[{index}].page is out of range")
        if not isinstance(block.get("line_count"), int) or block["line_count"] < 1:
            raise ValueError(f"blocks[{index}].line_count must be positive")
        if not isinstance(block.get("uncertain"), bool):
            raise ValueError(f"blocks[{index}].uncertain must be a boolean")
        if not isinstance(block.get("extraction_method"), str):
            raise ValueError(f"blocks[{index}] needs an extraction method")
        confidence = block.get("extraction_confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= confidence <= 1
        ):
            raise ValueError(f"blocks[{index}] has invalid extraction confidence")
        agreement = block.get("engine_agreement")
        if agreement is not None and (
            isinstance(agreement, bool)
            or not isinstance(agreement, (int, float))
            or not math.isfinite(float(agreement))
            or not 0 <= agreement <= 1
        ):
            raise ValueError(f"blocks[{index}] has invalid engine agreement")
        engines = block.get("source_engines")
        if engines is not None and (
            not isinstance(engines, list)
            or any(not isinstance(item, str) or not item for item in engines)
            or len(engines) != len(set(engines))
        ):
            raise ValueError(f"blocks[{index}] has invalid source engines")
        region = block.get("content_region")
        if region is not None and (not isinstance(region, str) or not region):
            raise ValueError(f"blocks[{index}] has invalid content region")
        order = block.get("order")
        if (
            isinstance(order, bool)
            or not isinstance(order, int)
            or order < 1
            or order in block_orders
        ):
            raise ValueError(f"blocks[{index}].order must be unique and positive")
        block_orders.add(order)
        anchor_id = block.get("anchor_id")
        if anchor_id not in anchor_ids:
            raise ValueError(f"blocks[{index}] references unknown anchor")
        object_ref = block.get("object_ref")
        if object_ref is not None and object_ref not in object_ids:
            raise ValueError(f"blocks[{index}] references unknown object")
    if block_orders != set(range(1, len(blocks) + 1)):
        raise ValueError("block order must be contiguous from 1")
    anchor_by_block: dict[str, dict[str, object]] = {}
    anchor_by_id: dict[str, dict[str, object]] = {}
    for index, anchor in enumerate(anchors):
        page = anchor.get("page")
        if (
            isinstance(page, bool)
            or not isinstance(page, int)
            or not 1 <= page <= source["page_count"]
        ):
            raise ValueError(f"anchors[{index}].page is out of range")
        bbox = anchor.get("bbox")
        if bbox is not None and (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in bbox
            )
            or not 0 <= bbox[0] < bbox[2] <= 1
            or not 0 <= bbox[1] < bbox[3] <= 1
        ):
            raise ValueError(f"anchors[{index}].bbox must be four 0..1 numbers")
        if anchor.get("block_id") not in block_ids:
            raise ValueError(f"anchors[{index}] references unknown block")
        block_id = str(anchor["block_id"])
        if block_id in anchor_by_block:
            raise ValueError(f"anchors[{index}] duplicates block evidence")
        anchor_by_block[block_id] = anchor
        anchor_by_id[str(anchor["id"])] = anchor
        anchored = anchor.get("anchored")
        if not isinstance(anchored, bool) or anchored != (bbox is not None):
            raise ValueError(f"anchors[{index}].anchored conflicts with bbox")
        evidence = anchor.get("text_evidence")
        span = anchor.get("span")
        if not isinstance(evidence, str) or not isinstance(span, dict):
            raise ValueError(f"anchors[{index}] needs text/span evidence")
        start, end = span.get("start"), span.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start <= end <= len(evidence)
        ):
            raise ValueError(f"anchors[{index}].span is out of range")
        page_item = page_metadata.get(page)
        if page_item is None:
            raise ValueError(f"anchors[{index}] references missing page metadata")
        if anchor.get("coordinate_system") != page_item["coordinate_system"]:
            raise ValueError(f"anchors[{index}] coordinate system conflicts with page")
    if set(anchor_by_block) != block_ids or len(anchors) != len(blocks):
        raise ValueError("every block must have exactly one anchor")
    for index, block in enumerate(blocks):
        anchor = anchor_by_id[str(block["anchor_id"])]
        if anchor["block_id"] != block["id"]:
            raise ValueError(f"blocks[{index}] does not own its referenced anchor")
        if anchor["page"] != block["page"]:
            raise ValueError(
                f"blocks[{index}].page conflicts with its referenced anchor page"
            )
    for index, section in enumerate(document["sections"]):
        parent_id = section.get("parent_id")
        if parent_id is not None and parent_id not in section_ids:
            raise ValueError(f"sections[{index}] references unknown parent")
        section_blocks = section.get("block_ids")
        if not isinstance(section_blocks, list) or any(
            item not in block_ids for item in section_blocks
        ):
            raise ValueError(f"sections[{index}] references unknown block")
        if section.get("heading_block_id") not in block_ids:
            raise ValueError(f"sections[{index}] references unknown heading block")
    for label in ("figures", "tables"):
        for index, item in enumerate(document[label]):
            if item.get("caption_block_id") not in block_ids:
                raise ValueError(f"{label}[{index}] references unknown caption block")
            if item.get("anchor_id") not in anchor_ids:
                raise ValueError(f"{label}[{index}] references unknown anchor")
            object_blocks = item.get("object_block_ids")
            if not isinstance(object_blocks, list) or any(
                block_id not in block_ids for block_id in object_blocks
            ):
                raise ValueError(f"{label}[{index}] references unknown object block")
            if not isinstance(item.get("uncertain"), bool) or not isinstance(
                item.get("association"), str
            ):
                raise ValueError(f"{label}[{index}] needs association/uncertainty")
            if item.get("interpretation_status") != "not-interpreted":
                raise ValueError(
                    f"{label}[{index}] must not claim semantic interpretation"
                )
            if item.get("evidence_status") not in {
                "caption-observed",
                "caption-and-region-observed",
                "caption-and-cell-evidence-observed",
            }:
                raise ValueError(f"{label}[{index}] has invalid evidence status")
            if label == "figures":
                source_objects = item.get("source_objects")
                if not isinstance(source_objects, list):
                    raise ValueError(f"figures[{index}].source_objects must be a list")
                for object_index, source_object in enumerate(source_objects):
                    if (
                        not isinstance(source_object, dict)
                        or isinstance(source_object.get("page"), bool)
                        or not isinstance(source_object.get("page"), int)
                        or not 1 <= source_object["page"] <= source["page_count"]
                        or not isinstance(source_object.get("name"), str)
                        or not source_object["name"]
                    ):
                        raise ValueError(
                            f"figures[{index}].source_objects[{object_index}] is invalid"
                        )
                    object_bbox = source_object.get("bbox")
                    if object_bbox is not None and (
                        not isinstance(object_bbox, list)
                        or len(object_bbox) != 4
                        or any(
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or not math.isfinite(float(value))
                            for value in object_bbox
                        )
                        or not 0 <= object_bbox[0] < object_bbox[2] <= 1
                        or not 0 <= object_bbox[1] < object_bbox[3] <= 1
                    ):
                        raise ValueError(
                            f"figures[{index}].source_objects[{object_index}].bbox is invalid"
                        )
                    for dimension in ("width", "height"):
                        value = source_object.get(dimension)
                        if value is not None and (
                            isinstance(value, bool)
                            or not isinstance(value, int)
                            or value < 1
                        ):
                            raise ValueError(
                                f"figures[{index}].source_objects[{object_index}].{dimension} is invalid"
                            )
            if label == "tables":
                cells = item.get("cells")
                if not isinstance(cells, list):
                    raise ValueError(f"tables[{index}].cells must be a list")
                row_count = item.get("row_count")
                column_count = item.get("column_count")
                if (
                    isinstance(row_count, bool)
                    or isinstance(column_count, bool)
                    or not isinstance(row_count, int)
                    or not isinstance(column_count, int)
                    or row_count < 0
                    or column_count < 0
                ):
                    raise ValueError(f"tables[{index}] has invalid dimensions")
                for cell_index, cell in enumerate(cells):
                    if not isinstance(cell, dict):
                        raise ValueError(
                            f"tables[{index}].cells[{cell_index}] must be an object"
                        )
                    if cell.get("block_id") not in block_ids:
                        raise ValueError(
                            f"tables[{index}].cells[{cell_index}] has unknown block"
                        )
                    if cell.get("anchor_id") not in anchor_ids:
                        raise ValueError(
                            f"tables[{index}].cells[{cell_index}] has unknown anchor"
                        )
                    if (
                        isinstance(cell.get("row"), bool)
                        or isinstance(cell.get("column"), bool)
                        or not isinstance(cell.get("row"), int)
                        or not 1 <= cell["row"] <= row_count
                        or not isinstance(cell.get("column"), int)
                        or not 1 <= cell["column"] <= column_count
                        or not isinstance(cell.get("text"), str)
                    ):
                        raise ValueError(
                            f"tables[{index}].cells[{cell_index}] is out of range"
                        )
    for index, item in enumerate(document["references"]):
        resolved = item.get("resolved")
        if not isinstance(resolved, bool):
            raise ValueError(f"references[{index}].resolved must be a boolean")
        if resolved:
            if item.get("block_id") not in block_ids:
                raise ValueError(f"references[{index}] references unknown block")
            if item.get("anchor_id") not in anchor_ids:
                raise ValueError(f"references[{index}] references unknown anchor")
        elif item.get("block_id") is not None or item.get("anchor_id") is not None:
            raise ValueError(f"references[{index}] has ambiguous unresolved evidence")
        cited_by = item.get("cited_by_block_ids")
        if not isinstance(cited_by, list) or any(
            block_id not in block_ids for block_id in cited_by
        ):
            raise ValueError(f"references[{index}] has unknown citing block")
        candidates = item.get("doi_candidates")
        if not isinstance(candidates, list) or any(
            not isinstance(candidate, str) for candidate in candidates
        ):
            raise ValueError(f"references[{index}].doi_candidates must be strings")
        if item.get("doi") is not None and item["doi"] not in candidates:
            raise ValueError(f"references[{index}].doi must be one of its candidates")
        if not isinstance(item.get("ambiguous"), bool):
            raise ValueError(f"references[{index}].ambiguous must be a boolean")

    anchored = sum(bool(item["anchored"]) for item in anchors)
    _validate_coverage(
        quality.get("anchor_coverage"),
        label="quality.anchor_coverage",
        numerator="anchored",
        expected_numerator=anchored,
        expected_total=len(blocks),
    )
    expected_counts = {
        "text_characters": sum(len(str(block["text"])) for block in blocks),
        "section_count": len(document["sections"]),
        "reference_count": len(document["references"]),
        "unresolved_reference_count": sum(
            not bool(item["resolved"]) for item in document["references"]
        ),
        "figure_count": len(document["figures"]),
        "figures_with_region_evidence": sum(
            item.get("evidence_status") == "caption-and-region-observed"
            for item in document["figures"]
        ),
        "table_count": len(document["tables"]),
        "tables_with_cells": sum(bool(item["cells"]) for item in document["tables"]),
    }
    for key, expected in expected_counts.items():
        value = quality.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise ValueError(f"quality.{key} does not match document content")
    ocr_blocks = [
        block
        for block in blocks
        if "ocr" in str(block.get("extraction_method", "")).casefold()
        or any(
            "ocr" in str(engine).casefold() or "tesseract" in str(engine).casefold()
            for engine in block.get("source_engines", [])
        )
    ]
    if "ocr_supplemented_blocks" in quality and quality[
        "ocr_supplemented_blocks"
    ] != len(ocr_blocks):
        raise ValueError("quality.ocr_supplemented_blocks does not match blocks")
    consensus_blocks = sum(
        block.get("extraction_method") == "ocr-consensus"
        or len(block.get("source_engines", [])) > 1
        for block in ocr_blocks
    )
    if (
        "ocr_consensus_blocks" in quality
        and quality["ocr_consensus_blocks"] != consensus_blocks
    ):
        raise ValueError("quality.ocr_consensus_blocks does not match blocks")
    mean_confidence = quality.get("mean_extraction_confidence")
    if mean_confidence is not None and (
        isinstance(mean_confidence, bool)
        or not isinstance(mean_confidence, (int, float))
        or not math.isfinite(float(mean_confidence))
        or not 0 <= mean_confidence <= 1
    ):
        raise ValueError("quality.mean_extraction_confidence must be between 0 and 1")
    expected_mean_confidence = (
        round(
            sum(float(block.get("extraction_confidence", 1.0)) for block in blocks)
            / len(blocks),
            6,
        )
        if blocks
        else 0.0
    )
    if mean_confidence != expected_mean_confidence:
        raise ValueError(
            "quality.mean_extraction_confidence does not match document content"
        )
    if "manual_review_required" in quality and not isinstance(
        quality["manual_review_required"], bool
    ):
        raise ValueError("quality.manual_review_required must be a boolean")
    for key in ("suppressed_page_furniture", "unassociated_image_resources"):
        if key not in quality:
            continue
        value = quality.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"quality.{key} must be a non-negative integer")
    if not isinstance(quality.get("stopped_early"), bool):
        raise ValueError("quality.stopped_early must be a boolean")
    informational_warning_codes = {
        "OCR_TRIGGERED",
        "OCR_TEXT_SUPPLEMENTED",
        "OCR_ORIENTATION_CORRECTED",
        "OCR_DESKEW_APPLIED",
    }
    blocking_warnings = [
        item
        for item in document["warnings"]
        if item["code"] not in informational_warning_codes
    ]
    if document["status"] == "PARSED" and (
        blocking_warnings or document["errors"] or quality["stopped_early"]
    ):
        raise ValueError("PARSED status conflicts with warnings, errors, or truncation")
    if artifact_id != compute_parsed_artifact_id(document):
        raise ValueError("artifact_id does not match canonical document content")


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_coverage(
    value: object,
    *,
    label: str,
    numerator: str,
    expected_total: int,
    expected_numerator: int | None = None,
) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    actual_numerator = value.get(numerator)
    total = value.get("total")
    ratio = value.get("ratio")
    if (
        isinstance(actual_numerator, bool)
        or not isinstance(actual_numerator, int)
        or actual_numerator < 0
        or isinstance(total, bool)
        or not isinstance(total, int)
        or total != expected_total
        or actual_numerator > total
        or isinstance(ratio, bool)
        or not isinstance(ratio, (int, float))
    ):
        raise ValueError(f"{label} has invalid counts")
    if expected_numerator is not None and actual_numerator != expected_numerator:
        raise ValueError(f"{label}.{numerator} does not match document content")
    expected_ratio = round(actual_numerator / total, 6) if total else 0.0
    if ratio != expected_ratio:
        raise ValueError(f"{label}.ratio does not match its counts")


def _unique_ids(items: list[object], label: str) -> set[str]:
    identifiers: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{label}[{index}] must be an object")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{label}[{index}] needs a non-empty id")
        if identifier in identifiers:
            raise ValueError(f"duplicate {label} id: {identifier}")
        identifiers.add(identifier)
    return identifiers


def serialize_parsed_document(document: dict[str, object]) -> str:
    validate_parsed_document(document)
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def write_parsed_document(
    path: str | Path,
    document: dict[str, object],
    *,
    overwrite: bool = False,
) -> Path:
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"parsed artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        temporary.write_text(serialize_parsed_document(document), encoding="utf-8")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
