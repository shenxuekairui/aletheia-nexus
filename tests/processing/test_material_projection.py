"""Model-facing compression preserves source readings and their uncertainty."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest

from aletheia_nexus.content import parse_document
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.processing import materials
from aletheia_nexus.processing.contracts import TASK_SCHEMA
from aletheia_nexus.processing.engine import _request, run_task


@pytest.fixture
def package():
    def block(bid, page, text, **extra):
        return {
            "id": bid,
            "page": page,
            "text": text,
            "kind": "paragraph",
            "uncertain": False,
            "content_region": "body",
            **extra,
        }

    return {
        "artifact_id": "package-original",
        "mode": "hybrid",
        "images": [{"source_id": "paper", "page": 2, "sha256": "page-two"}],
        "documents": [
            {
                "id": "paper",
                "source": {"title": "Self-authored", "page_count": 3},
                "pages_requested": [1, 2],
                "omitted_pages": [3],
                "pages": [{"page": 2, "coordinate_system": "fixture-coordinates"}],
                "blocks": [
                    block("b1", 1, "An unrelated preceding page."),
                    block(
                        "b2",
                        2,
                        "Fig. 1 Measurements at",
                        kind="caption",
                        object_ref="f1",
                        evidence={
                            "bbox": [0.1, 0.2, 0.9, 0.3],
                            "coordinate_system": "fixture-coordinates",
                        },
                    ),
                    block("b3", 2, "25 °C; blank control; ratio 1:2.", uncertain=True),
                    block("b4", 2, "0.25 mA", content_region="figure"),
                    block("b5", 2, "A separate discussion paragraph."),
                ],
                "figures": [
                    {
                        "id": "f1",
                        "caption": "Fig. 1 Measurements at",
                        "caption_block_id": "b2",
                        "interpretation_status": "not-interpreted",
                        "association": "caption+positioned-page-images",
                        "object_block_ids": [],
                        "source_objects": [
                            {
                                "page": 2,
                                "bbox": [0.1, 0.3, 0.9, 0.8],
                                "annotation_block_ids": ["b4"],
                            }
                        ],
                    }
                ],
                "tables": [
                    {
                        "id": "t1",
                        "cells": [{"row": 0, "column": 0, "text": "1:2"}],
                        "complete_context": True,
                    }
                ],
                "warnings": [
                    {
                        "code": "VECTOR_TEXT_UNVERIFIED",
                        "detail": "Check values against the image.",
                        "page": 2,
                        "source_object": f"vector-{i}",
                    }
                    for i in range(80)
                ],
                "notes": ["User note remains separate."],
                "corrections": [],
            }
        ],
    }


def test_model_request_keeps_all_readings_and_local_diagnostics(package):
    original = deepcopy(package)
    request = _request(
        {"objective": "Read evidence", "type": "extract", "fields": [], "rules": []},
        package,
    )
    projected = request["material"]
    document = projected["documents"][0]
    assert package == original
    assert [(b["id"], b["text"]) for b in document["blocks"]] == [
        (b["id"], b["text"]) for b in package["documents"][0]["blocks"]
    ]
    assert document["blocks"][2]["uncertain"] is True
    assert document["tables"] == package["documents"][0]["tables"]
    assert document["notes"] == package["documents"][0]["notes"]
    assert document["warnings"] == [
        {
            "code": "VECTOR_TEXT_UNVERIFIED",
            "detail": "Check values against the image.",
            "pages": [2],
            "count": 80,
        }
    ]
    assert document["image_pages"] == [2]
    guidance = " ".join(projected["reading_guidance"])
    assert (
        "not-interpreted" in guidance and "Inspect the actual page images" in guidance
    )
    assert "does not establish legibility" in guidance
    assert projected["projection_version"] == materials.MODEL_PROJECTION_VERSION
    assert len(package["documents"][0]["warnings"]) == 80


def test_warning_grouping_preserves_scope_and_distinct_numeric_details(package):
    document = package["documents"][0]
    document["warnings"] = [
        {"code": "GLYPH", "detail": "page 1: ambiguous glyph", "page": 1},
        {"code": "GLYPH", "detail": "page 2:  ambiguous  glyph", "page": 2},
        {"code": "GLYPH", "detail": "page 2: 2 unmapped symbols", "page": 2},
        {"code": "GLYPH", "detail": "page 2: 3 unmapped symbols", "page": 2},
        {"code": "OTHER", "detail": "ambiguous glyph", "page": 2},
        {"code": "GLOBAL", "detail": "Document-wide uncertainty", "page": None},
        {"code": "OMITTED", "detail": "Outside selected pages", "page": 3},
    ]
    warnings = materials.model_material(package)["documents"][0]["warnings"]
    assert warnings[0] == {
        "code": "GLYPH",
        "detail": "ambiguous glyph",
        "pages": [1, 2],
        "count": 2,
    }
    assert [w["detail"] for w in warnings[1:3]] == [
        "2 unmapped symbols",
        "3 unmapped symbols",
    ]
    assert warnings[3]["code"] == "OTHER"
    assert warnings[4]["pages"] == [None]
    assert len(warnings) == 5


def test_figure_context_keeps_known_links_without_inventing_caption_extension(package):
    original = deepcopy(package)
    figure = materials.model_material(package)["documents"][0]["figures"][0]
    assert figure["caption"] == "Fig. 1 Measurements at"
    assert figure["pages"] == [2]
    assert figure["caption_location"]["page"] == 2
    assert figure["linked_block_ids"] == ["b2", "b4"]
    assert figure["adjacent_block_ids"] == ["b3"]  # Not b1 on the preceding page.
    assert figure["source_regions"] == [
        {
            "page": 2,
            "bbox": [0.1, 0.3, 0.9, 0.8],
            "coordinate_system": "fixture-coordinates",
        }
    ]
    assert package == original

    # An image-only page can retain a figure region without its caption block.
    package["documents"][0]["blocks"] = []
    package["images"] = []
    document = materials.model_material(package)["documents"][0]
    assert document["image_pages"] == []
    assert document["figures"][0]["adjacent_block_ids"] == []
    assert document["figures"][0]["linked_block_ids"] == []
    assert "caption_location" not in document["figures"][0]
    assert document["figures"][0]["pages"] == [2]


def test_package_version_invalidates_cached_model_result(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    write_pdf = runpy.run_path(str(root / "scripts/generate_v07_fixtures.py"))[
        "_write_pdf"
    ]
    original = tmp_path / "original.pdf"
    write_pdf(
        original,
        [[(50, 680, 12, "The sample was tested at 25 C.")]],
        title="Self-authored projection test",
    )
    pdf = register_local_pdf(original, output_dir=tmp_path / "library", title="Example")
    parse_document(pdf)
    task = {
        "schema": TASK_SCHEMA,
        "id": "projection-cache",
        "type": "extract",
        "objective": "Extract the reported conditions.",
        "documents": [
            {"id": "paper", "artifact": str(pdf.with_suffix(".parsed.json"))}
        ],
        "fields": [{"id": "conditions", "type": "string", "description": "Conditions"}],
        "mode": "parsed",
        "allow_remote": True,
        "budget": {"max_review_rounds": 0},
    }

    class MockProvider:
        identity = {"provider": "mock-projection"}

        def __init__(self):
            self.requests = []

        def generate(self, request, schema, images, budget, max_output_tokens):
            self.requests.append(deepcopy(request))
            row = budget.reserve(None)
            row.update(status="completed", usage={})
            block = request["material"]["documents"][0]["blocks"][0]
            return {
                "records": [
                    {
                        "id": "r1",
                        "subject": "sample",
                        "stage": "testing",
                        "fields": {
                            "conditions": {
                                "value": block["text"],
                                "raw_value": block["text"],
                                "unit": None,
                                "status": "reported",
                                "nature": "reported",
                                "context": "Testing",
                                "step_ids": [],
                                "citations": [
                                    {
                                        "source_id": "paper",
                                        "page": block["page"],
                                        "block_id": block["id"],
                                        "quote": block["text"],
                                    }
                                ],
                            }
                        },
                        "steps": [],
                    }
                ],
                "claims": [],
                "issues": [],
                "requests": [],
            }

    provider = MockProvider()

    def run():
        return run_task(
            task,
            base_dir=tmp_path,
            output_dir=tmp_path / "out",
            allow_remote=True,
            provider=provider,
        )

    current = materials.BUILDER_VERSION
    monkeypatch.setattr(materials, "BUILDER_VERSION", "previous-projection")
    first = run()
    monkeypatch.setattr(materials, "BUILDER_VERSION", current)
    second = run()
    third = run()
    assert all(run["status"] == "COMPLETED" for run in (first, second, third))
    assert len(provider.requests) == 2
    assert not second["items"][0].get("reused")
    assert third["items"][0]["reused"] is True
    for request in provider.requests:
        material = request["material"]
        assert material["projection_version"] == materials.MODEL_PROJECTION_VERSION
        assert material["documents"][0]["image_pages"] == []
    result = json.loads(
        (Path(second["run_directory"]) / "paper.result.json").read_text("utf-8")
    )
    assert result["package"]["builder_version"] == current
