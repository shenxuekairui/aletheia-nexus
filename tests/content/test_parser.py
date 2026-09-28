import json
import shutil
from pathlib import Path

import pytest

from aletheia_nexus.content import (
    NativePdfBackend,
    ParserConfig,
    parse_document,
    validate_parsed_document,
)
from aletheia_nexus.content.evaluation import evaluate_manifest
from aletheia_nexus.content.models import LayoutLine, PageLayout, PipelineContext
from aletheia_nexus.content.pipeline import ParserPipeline
from aletheia_nexus.content.schema import serialize_parsed_document

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "v07_fixtures"


def _parse(name, doi, tmp_path):
    pdf = FIXTURES / name
    sidecar = pdf.with_suffix(".acquisition.json")
    before = sidecar.read_bytes()
    result = parse_document(
        pdf,
        doi,
        sidecar_path=sidecar,
        output_path=tmp_path / f"{name}.parsed.json",
        created_at="2026-09-28T00:00:00+00:00",
    )
    assert sidecar.read_bytes() == before
    return result


def test_native_parser_emits_valid_source_linked_objects(tmp_path):
    result = _parse("native_article.pdf", "10.5555/an.v07.native", tmp_path)
    document = result.document
    validate_parsed_document(document)
    assert result.status == "PARSED"
    assert all(block["anchor_id"] for block in document["blocks"])
    assert all(anchor["bbox"] for anchor in document["anchors"])
    assert [item["label"] for item in document["figures"]] == ["1"]
    assert [item["label"] for item in document["tables"]] == ["1"]
    assert document["figures"][0]["association"] == "caption+single-page-image"
    assert document["figures"][0]["source_objects"][0]["name"] == "Im1"
    assert document["tables"][0]["row_count"] == 2
    assert document["tables"][0]["column_count"] == 3
    assert len(document["tables"][0]["cells"]) == 6
    assert document["references"][0]["cited_by_block_ids"]
    assert any(not item["resolved"] for item in document["references"])
    assert document["quality"]["anchor_coverage"]["ratio"] == 1.0
    assert document["parser"]["pipeline_stages"] == [
        "native-layout-and-block-assembly",
        "sections-references-and-objects",
        "quality-classification",
    ]


def test_two_column_order_and_deterministic_serialization(tmp_path):
    first = _parse("two_column_article.pdf", "10.5555/an.v07.columns", tmp_path)
    second = _parse(
        "two_column_article.pdf", "10.5555/an.v07.columns", tmp_path / "again"
    )
    assert serialize_parsed_document(first.document) == serialize_parsed_document(
        second.document
    )
    texts = [item["text"] for item in first.document["blocks"]]
    assert texts.index("Left column method detail.") < texts.index("3 Results")
    assert "Left column first line. Left column second line." in texts
    assert "Right column first line. Right column second line." in texts
    assert [item["id"] for item in first.document["blocks"]] == [
        item["id"] for item in second.document["blocks"]
    ]


def test_sparse_page_is_explicitly_partial(tmp_path):
    result = _parse("sparse_scan.pdf", "10.5555/an.v07.sparse", tmp_path)
    assert result.status == "PARTIAL"
    assert {item["code"] for item in result.document["warnings"]} == {
        "PAGE_WITHOUT_TEXT",
        "SPARSE_TEXT",
    }


def test_schema_rejects_dangling_anchor(tmp_path):
    result = _parse("native_article.pdf", "10.5555/an.v07.native", tmp_path)
    payload = json.loads(json.dumps(result.document))
    payload["blocks"][0]["anchor_id"] = "missing"
    with pytest.raises(ValueError, match="unknown anchor"):
        validate_parsed_document(payload)


def test_schema_rejects_tampered_provenance_and_quality(tmp_path):
    result = _parse("native_article.pdf", "10.5555/an.v07.native", tmp_path)
    payload = json.loads(json.dumps(result.document))
    payload["parser"]["configuration"]["max_pages"] = 1
    with pytest.raises(ValueError, match="configuration fingerprint"):
        validate_parsed_document(payload)

    payload = json.loads(json.dumps(result.document))
    payload["quality"]["anchor_coverage"]["anchored"] -= 1
    with pytest.raises(ValueError, match="does not match document content"):
        validate_parsed_document(payload)


def test_parser_config_rejects_nonsensical_layout_thresholds():
    with pytest.raises(ValueError, match="heading_font_ratio"):
        ParserConfig(heading_font_ratio=1)
    with pytest.raises(ValueError, match="column_split_ratio"):
        ParserConfig(column_split_ratio=0.9)
    with pytest.raises(ValueError, match="positive integer"):
        ParserConfig(max_pages=True)
    with pytest.raises(ValueError, match="must be a number"):
        ParserConfig(heading_font_ratio="large")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be a boolean"):
        ParserConfig(merge_paragraph_lines=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be finite"):
        ParserConfig(heading_font_ratio=float("nan"))


def test_relative_output_cannot_overwrite_source_artifacts(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    sidecar = tmp_path / "paper.acquisition.json"
    shutil.copy2(FIXTURES / "native_article.pdf", pdf)
    shutil.copy2(FIXTURES / "native_article.acquisition.json", sidecar)
    original_pdf = pdf.read_bytes()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must not overwrite"):
        parse_document(
            "paper.pdf",
            "10.5555/an.v07.native",
            output_path="paper.pdf",
        )

    assert pdf.read_bytes() == original_pdf


def test_resource_budget_yields_explicit_partial_artifact(tmp_path):
    pdf = FIXTURES / "native_article.pdf"
    result = parse_document(
        pdf,
        "10.5555/an.v07.native",
        output_path=tmp_path / "limited.parsed.json",
        config=ParserConfig(max_pages=1),
    )
    assert result.status == "PARTIAL"
    assert {item["code"] for item in result.document["warnings"]} >= {
        "PAGE_LIMIT_REACHED"
    }
    assert result.document["quality"]["page_coverage"] == {
        "parsed": 1,
        "total": 2,
        "ratio": 0.5,
    }


def test_custom_backend_is_recorded_and_consumed(tmp_path):
    class Backend:
        name = "test-layout"
        version = "9"

        def extract_page(self, page, page_number):
            del page
            return PageLayout(
                page=page_number,
                width=612,
                height=792,
                lines=(LayoutLine("Methods", 54, 700, 120, 714, 14),),
            )

    result = parse_document(
        FIXTURES / "sparse_scan.pdf",
        "10.5555/an.v07.sparse",
        output_path=tmp_path / "custom.parsed.json",
        backend=Backend(),
    )
    assert result.document["parser"]["backend"] == {
        "name": "test-layout",
        "version": "9",
    }
    assert result.document["sections"][0]["semantic_type"] == "methods"


def test_pipeline_rejects_duplicate_stage_names():
    class Stage:
        name = "duplicate"

        def run(self, context: PipelineContext):
            del context

    with pytest.raises(ValueError, match="unique"):
        ParserPipeline((Stage(), Stage()))


def test_native_backend_is_public():
    assert NativePdfBackend.name == "pypdf-native-layout"


def test_sidecar_change_during_parse_fails_without_output(tmp_path):
    from aletheia_nexus.content import ParserInputError, ParserInputErrorCode

    source_pdf = FIXTURES / "sparse_scan.pdf"
    source_sidecar = source_pdf.with_suffix(".acquisition.json")
    pdf = tmp_path / source_pdf.name
    sidecar = tmp_path / source_sidecar.name
    shutil.copy2(source_pdf, pdf)
    shutil.copy2(source_sidecar, sidecar)
    output = tmp_path / "must-not-exist.parsed.json"

    class MutatingBackend:
        name = "mutation-test"
        version = "1"

        def extract_page(self, page, page_number):
            sidecar.write_text(sidecar.read_text() + " ", encoding="utf-8")
            return NativePdfBackend().extract_page(page, page_number)

    with pytest.raises(ParserInputError) as exc:
        parse_document(
            pdf,
            "10.5555/an.v07.sparse",
            sidecar_path=sidecar,
            output_path=output,
            backend=MutatingBackend(),
        )
    assert exc.value.code == ParserInputErrorCode.SIDECAR_CHANGED
    assert not output.exists()


def test_frozen_public_evaluation_gate_is_green():
    report = evaluate_manifest(FIXTURES / "manifest.json")
    for key, metric in report["metrics"].items():
        if key == "anchored_block_coverage" or not isinstance(metric, dict):
            continue
        assert metric["correct"] == metric["total"], key
    coverage = report["metrics"]["anchored_block_coverage"]
    assert coverage["correct"] == coverage["total"]
    assert coverage["total"] > 0
    assert report["metrics"]["table_figure_link_omissions"] == 0
    assert report["metrics"]["table_figure_false_associations"] == 0


def test_public_fixtures_contain_no_authenticated_or_publisher_material():
    forbidden = (b"cookie", b"authorization:", b"signed_url", b"publisher.com")
    for path in FIXTURES.iterdir():
        if path.is_file():
            lowered = path.read_bytes().lower()
            assert not any(marker in lowered for marker in forbidden), path.name
