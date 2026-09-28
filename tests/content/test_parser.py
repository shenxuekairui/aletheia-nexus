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
from aletheia_nexus.content.parser import (
    _caption_match,
    _deduplicate_caption_blocks,
    _kind,
    _mark_bibliography_blocks,
    _reference_segments,
)
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
    assert document["figures"][0]["source_objects"][0]["bbox"] is not None
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


def test_layout_noise_and_scientific_labels_are_disambiguated(tmp_path):
    class Backend:
        name = "classification-test"
        version = "1"

        def extract_page(self, page, page_number):
            del page
            body = (
                LayoutLine("Journal running header", 36, 770, 220, 780, 8),
                LayoutLine("Abstract", 54, 720, 125, 734, 12, bold=True),
                LayoutLine(
                    "Ordinary abstract sentence has enough prose.",
                    54,
                    680,
                    340,
                    692,
                    10,
                ),
                LayoutLine("FIG. 1. Example result.", 54, 640, 220, 652, 9),
                LayoutLine("I. INTRODUCTION", 54, 600, 190, 613, 11, bold=True),
                LayoutLine("E = mc2", 54, 560, 110, 572, 11),
                LayoutLine("12. Liu, Y. et al. Useful study.", 54, 520, 260, 532, 9),
                LayoutLine("2 μϵ MD c", 54, 480, 130, 492, 11),
            )
            if page_number == 2:
                body = (
                    LayoutLine("Journal running header", 36, 770, 220, 780, 8),
                    LayoutLine("References", 54, 720, 140, 734, 12, bold=True),
                    LayoutLine("1 Smith A. First source.", 54, 680, 250, 692, 9),
                    LayoutLine("2 Jones B. Second source.", 54, 640, 260, 652, 9),
                )
            return PageLayout(
                page=page_number,
                width=612,
                height=792,
                lines=body + (LayoutLine(str(page_number), 300, 10, 306, 20, 8),),
            )

    result = parse_document(
        FIXTURES / "native_article.pdf",
        "10.5555/an.v07.native",
        output_path=tmp_path / "classified.parsed.json",
        backend=Backend(),
    )
    document = result.document
    block_by_text = {item["text"]: item for item in document["blocks"]}
    assert "Journal running header" not in block_by_text
    assert "1" not in block_by_text and "2" not in block_by_text
    assert block_by_text["Ordinary abstract sentence has enough prose."]["kind"] == (
        "paragraph"
    )
    assert block_by_text["FIG. 1. Example result."]["kind"] == "caption"
    assert block_by_text["E = mc2"]["kind"] == "equation"
    assert block_by_text["2 μϵ MD c"]["kind"] == "equation"
    assert [item["semantic_type"] for item in document["sections"]] == [
        "abstract",
        "introduction",
        "references",
    ]
    assert block_by_text["12. Liu, Y. et al. Useful study."]["kind"] == "paragraph"
    assert len(document["references"]) == 2
    assert document["quality"]["suppressed_page_furniture"] == 4


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("Fig. 1 Electrocatalytic performance", "1"),
        ("Fig. 1Overview of the workflow", "1"),
        ("FIGURE 2 | Experimental setup", "2"),
        ("Figure 2 continued", "2"),
        ("Table IV. Ablation results", "IV"),
    ],
)
def test_caption_classifier_keeps_real_caption_styles(text, label):
    match = _caption_match(text)
    assert match is not None
    assert match.group("label") == label


@pytest.mark.parametrize(
    "text",
    [
        "Figure 2 shows the resulting distribution.",
        "Fig. 5 (d) [12]. There are two regimes.",
        "Fig. 8 (b) illustrates the measured response.",
        "Figure 2d on the TEM image marks the region.",
        "Figure 2, for both experimental settings.",
        "Table 4 lists all hyperparameters.",
        "Table I. Regarding both time effects, the response changes.",
        "Figure captions are provided below.",
        "Figure Views are available online.",
    ],
)
def test_caption_classifier_rejects_body_mentions_and_partial_roman_words(text):
    assert _caption_match(text) is None


def test_duplicate_caption_layers_keep_one_semantic_object_without_dropping_text():
    blocks = [
        {
            "id": "b1",
            "page": 3,
            "kind": "caption",
            "text": "Figure 1. Structural diagram of the sensor.",
        },
        {
            "id": "b2",
            "page": 3,
            "kind": "caption",
            "text": "Figure 1.Structuraldiagram of the sensor.",
        },
        {
            "id": "b3",
            "page": 4,
            "kind": "caption",
            "text": "Figure 2 continued",
        },
        {
            "id": "b4",
            "page": 4,
            "kind": "caption",
            "text": "Figure 2. Primary result.",
        },
    ]
    original_text = [block["text"] for block in blocks]

    _deduplicate_caption_blocks(blocks)

    assert [block["text"] for block in blocks] == original_text
    assert [block["kind"] for block in blocks[:2]].count("caption") == 1
    assert [block["kind"] for block in blocks[2:]] == ["caption", "caption"]


def test_duplicate_table_mention_prefers_caption_phrase():
    blocks = [
        {
            "id": "b1",
            "page": 2,
            "kind": "caption",
            "text": "Table 2. Result of multiple comparisons.",
        },
        {
            "id": "b2",
            "page": 2,
            "kind": "caption",
            "text": "Table 2 statistically significant differences were observed.",
        },
    ]

    _deduplicate_caption_blocks(blocks)

    assert [block["kind"] for block in blocks] == ["caption", "paragraph"]


def test_bracketed_numbers_require_bibliography_context():
    table_row = LayoutLine("[9] 0.74 0.81", 54, 600, 220, 612, 9)
    assert _kind(table_row, median_font=9, heading_font_ratio=1.35) == "paragraph"

    blocks = [
        {"id": "b1", "page": 1, "kind": "paragraph", "text": "[9] 0.74 0.81"},
        {"id": "b2", "page": 2, "kind": "heading", "text": "References"},
        {
            "id": "b3",
            "page": 2,
            "kind": "paragraph",
            "text": "[1] Smith A. First source.",
        },
        {
            "id": "b4",
            "page": 4,
            "kind": "paragraph",
            "text": "1 Department of Physics, Example University",
        },
    ]
    _mark_bibliography_blocks(blocks)

    assert blocks[0]["kind"] == "paragraph"
    assert blocks[2]["kind"] == "reference"
    assert blocks[3]["kind"] == "paragraph"


def test_post_reference_heading_ends_bibliography_on_the_same_page():
    blocks = [
        {"id": "b1", "page": 1, "kind": "heading", "text": "References"},
        {"id": "b2", "page": 1, "kind": "paragraph", "text": "1 Smith A. Source."},
        {
            "id": "b3",
            "page": 1,
            "kind": "heading",
            "text": "Author contributions",
        },
        {"id": "b4", "page": 1, "kind": "paragraph", "text": "2 Methodology"},
    ]
    _mark_bibliography_blocks(blocks)

    assert blocks[1]["kind"] == "reference"
    assert blocks[2]["kind"] == "heading"
    assert blocks[3]["kind"] == "paragraph"


def test_bibliography_numbering_rejects_volume_and_year_continuations():
    blocks = [
        {"id": "b1", "page": 1, "kind": "heading", "text": "References"},
        {
            "id": "b2",
            "page": 1,
            "kind": "paragraph",
            "text": "1. Smith A. First source.",
        },
        {
            "id": "b3",
            "page": 1,
            "kind": "paragraph",
            "text": "2. Jones B. Second source.",
        },
        {"id": "b4", "page": 1, "kind": "paragraph", "text": "224, 149–159."},
        {
            "id": "b5",
            "page": 1,
            "kind": "paragraph",
            "text": "3. Chen C. Third source.",
        },
        {"id": "b6", "page": 1, "kind": "paragraph", "text": "2. Repeated row."},
    ]
    _mark_bibliography_blocks(blocks)

    assert [block["kind"] for block in blocks[1:]] == [
        "reference",
        "reference",
        "paragraph",
        "reference",
        "paragraph",
    ]


def test_bracketed_bibliography_does_not_accept_plain_numeric_continuations():
    blocks = [
        {"id": "b1", "page": 1, "kind": "heading", "text": "References"},
        {"id": "b2", "page": 1, "kind": "paragraph", "text": "[1] First source."},
        {"id": "b3", "page": 1, "kind": "paragraph", "text": "13 TeV collisions."},
        {"id": "b4", "page": 1, "kind": "paragraph", "text": "[2] Second source."},
    ]
    _mark_bibliography_blocks(blocks)

    assert [block["kind"] for block in blocks[1:]] == [
        "reference",
        "paragraph",
        "reference",
    ]


def test_merged_reference_blocks_are_split_without_volume_false_positives():
    assert _reference_segments(
        "[13] First source.[14] Second source. 2015 volume 92."
    ) == [
        ("13", "[13] First source."),
        ("14", "[14] Second source. 2015 volume 92."),
    ]
    assert _reference_segments(
        "33 Smith A. First source. 60 A. Bordoloi, Second source. 224, 149–159."
    ) == [
        ("33", "33 Smith A. First source."),
        ("60", "60 A. Bordoloi, Second source. 224, 149–159."),
    ]
    assert _reference_segments("continued journal title. [3] Third source.") == [
        ("3", "[3] Third source.")
    ]


def test_end_of_document_bracketed_bibliography_is_inferred_without_heading():
    blocks = [
        {"id": "b1", "page": 2, "kind": "paragraph", "text": "[1] table row"},
        {"id": "b2", "page": 8, "kind": "paragraph", "text": "[1] First source."},
        {"id": "b3", "page": 8, "kind": "paragraph", "text": "[2] Second source."},
        {"id": "b4", "page": 9, "kind": "paragraph", "text": "[3] Third source."},
        {"id": "b5", "page": 10, "kind": "paragraph", "text": "Author biography"},
    ]

    _mark_bibliography_blocks(blocks)

    assert blocks[0]["kind"] == "paragraph"
    assert [block["kind"] for block in blocks[1:4]] == ["reference"] * 3


def test_schema_rejects_invalid_diagnostic_quality_count(tmp_path):
    result = _parse("native_article.pdf", "10.5555/an.v07.native", tmp_path)
    payload = json.loads(json.dumps(result.document))
    payload["quality"]["suppressed_page_furniture"] = -1
    with pytest.raises(ValueError, match="non-negative integer"):
        validate_parsed_document(payload)

    payload = json.loads(json.dumps(result.document))
    del payload["quality"]["suppressed_page_furniture"]
    del payload["quality"]["unassociated_image_resources"]
    validate_parsed_document(payload)


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
