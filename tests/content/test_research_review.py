"""Research-facing failures found during the 0.7.2 quantitative review."""

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from aletheia_nexus.content import parse_document
from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.corpus import load_corpus, search_corpus
from aletheia_nexus.content.evidence import build_evidence_pack, evidence_markdown
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.query import match_score, query_terms
from aletheia_nexus.content.schema import compute_parsed_artifact_id

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "v07_fixtures"


@pytest.mark.parametrize(
    "text,query,expected",
    [
        ("188.4%", "88.4", False),
        ("87.33%", "7.3", False),
        ("0.15 A cm-2", "5", False),
        ("-1.4 V", "1.4", True),
        ("+1.4 V", "1.4", True),
        ("-1.4 V", "+1.4", False),
        ("1.4 V", "-1.4", False),
        ("1.40 V", "1.4", False),
        ("1.4e-3 V", "1.4", False),
        ("1.4e-3 V", "3", False),
        ("1.4e-3 V", "-3", False),
        ("80-85%", "-85", False),
        ("80-85%", "85", True),
        ("80–85%", "80 85", True),
        ("− 1.4 V", "-1.4", True),
        ("1.4e-3 V", "1.4e-3", True),
        ("1.40 V", "1.40", True),
        ("88.4 %", "88.4%", True),
        ("产率为８８.４％", "88.4", True),
        ("0.15 A cm−2", "0.15", True),
        ("Cu-PTFE 88.4%", "Cu-PTFE 88.4", True),
    ],
)
def test_numeric_search_preserves_whole_values_and_signs(text, query, expected):
    assert (match_score(text, query_terms(query)) is not None) == expected


def research_corpus(tmp_path):
    main = register_local_pdf(
        FIXTURES / "native_article.pdf", output_dir=tmp_path, title="Main article"
    )
    parse_document(main)
    si = register_local_pdf(
        FIXTURES / "two_column_article.pdf",
        output_dir=tmp_path,
        title="Supporting information",
        role="SUPPLEMENT",
        parent_pdf=main,
    )
    parse_document(si)
    return main


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "Wrong paper"),
        ("article_id", "doi:10.5555/wrong"),
        ("identity_basis", "acquisition_verified"),
    ],
)
def test_parsed_identity_must_agree_with_original_record(tmp_path, field, value):
    main = research_corpus(tmp_path)
    path = main.with_suffix(".parsed.json")
    doc = json.loads(path.read_text("utf-8"))
    doc["source"][field] = value
    doc["artifact_id"] = compute_parsed_artifact_id(doc)
    path.write_text(json.dumps(doc), "utf-8")
    corpus = load_corpus(tmp_path)
    assert len(corpus.documents) == 1
    assert "identity disagrees" in corpus.unsearched[0]["reason"]


def test_filtered_search_and_selected_export_account_for_other_documents(tmp_path):
    research_corpus(tmp_path)
    result = search_corpus(tmp_path, "column", role="SUPPLEMENT")
    assert result["coverage"]["searched_documents"] == 2
    assert result["search_scope"]["searched_documents"] == 1
    assert len(result["search_scope"]["excluded_documents"]) == 1
    selected = build_evidence_pack(tmp_path, report=result, selectors=["1"])
    assert len(selected["included"]) == len(selected["skipped"]) == 1
    assert selected["skipped"][0]["reason"] == "not selected"
    assert len(build_evidence_pack(tmp_path)["included"]) == 2


@pytest.mark.parametrize("region", ["ocr-alternative", "native-alternative"])
def test_repeated_readings_do_not_crowd_search_but_unique_recovery_is_searchable(
    tmp_path, region
):
    from copy import deepcopy

    research_corpus(tmp_path)
    loaded = load_corpus(tmp_path)
    entry = loaded.documents[0]
    doc = entry.document
    template = deepcopy(doc["blocks"][0])
    anchor_template = deepcopy(doc["anchors"][0])
    doc["tables"] = []
    doc["sections"] = []
    doc["blocks"] = []
    doc["anchors"] = []
    samples = [
        (
            "primary",
            "catalyst with a reported yield of 75% after electrolysis",
            "body",
            [0.1, 0.5, 0.8, 0.7],
        ),
        ("alternative", "catalyst 75% recovered", region, [0.2, 0.55, 0.7, 0.6]),
        (
            "separate",
            "catalyst has another measured result in the selected conditions",
            "body",
            [0.1, 0.2, 0.8, 0.3],
        ),
        ("unique", "catalyst on an isolated image", region, [0.1, 0.8, 0.8, 0.9]),
    ]
    for i, (name, text, content_region, bbox) in enumerate(samples):
        anchor_id = "a-" + name
        doc["blocks"].append(
            {
                **template,
                "id": name,
                "text": text,
                "content_region": content_region,
                "anchor_id": anchor_id,
                "order": i,
            }
        )
        doc["anchors"].append(
            {**anchor_template, "id": anchor_id, "page": template["page"], "bbox": bbox}
        )
    hits = search_corpus(loaded, "catalyst")["hits"]
    selected = [h for h in hits if h["parsed_artifact_id"] == doc["artifact_id"]]
    assert len(selected) == 4
    assert selected[-1]["unit_id"] == "alternative"
    assert selected[0]["unit_id"] == "unique"
    recovered = search_corpus(loaded, "recovered")["hits"]
    assert recovered[0]["unit_id"] == "alternative"
    pack = build_evidence_pack(
        loaded,
        report=search_corpus(loaded, "catalyst"),
        selectors=[str(selected[0]["number"])],
        context_pages=0,
    )
    assert {b["text"] for b in pack["included"][0]["blocks"]} == {s[1] for s in samples}
    rendered = evidence_markdown(pack)
    assert "alternative readings at this source location" in rendered
    for name, text, _, _ in samples:
        assert text in rendered
        assert rendered.count(f", {name}; bbox=") == 1
    grouped = pack["included"][0]["review_locations"]
    assert any(g["block_ids"] == ["primary", "alternative"] for g in grouped)


def test_exported_tables_keep_uncertainty_and_canonical_text(tmp_path):
    main = research_corpus(tmp_path)
    canonical = json.loads(main.with_suffix(".parsed.json").read_text("utf-8"))
    before = {b["id"]: b for b in canonical["blocks"]}
    result = build_evidence_pack(tmp_path)
    item = next(i for i in result["included"] if i["pdf"] == main.name)
    assert item["tables"]
    table = item["tables"][0]
    assert table["uncertain"] and table["complete_context"]
    original_table = next(t for t in canonical["tables"] if t["id"] == table["id"])
    assert table["cells"] == original_table["cells"]
    assert (table["row_count"], table["column_count"]) == (
        original_table["row_count"],
        original_table["column_count"],
    )
    for block in item["blocks"]:
        assert block["text"] == before[block["id"]]["text"]
        assert block["source_uncertain"] == before[block["id"]]["uncertain"]
        if block["id"] in table["block_ids"]:
            assert block["uncertain"] and table["id"] in block["table_ids"]
    assert "row/column meaning not interpreted" in evidence_markdown(result)
    rendered = evidence_markdown(result)
    assert "| Observed row |" in rendered
    assert "Table text and alternative readings" not in rendered
    for block in item["blocks"]:
        if block["id"] in table["block_ids"] and not block.get(
            "content_region", ""
        ).endswith("alternative"):
            # Main text has not been put inside a collapsed details element.
            pos = rendered.index(f", {block['id']}; bbox=")
            prefix = rendered[:pos]
            assert prefix.count("<details>") == prefix.count("</details>")
    assert item["figures"]
    assert item["figures"][0]["image_text_completeness"] == "not-verified"
    assert "figure/axis text not guaranteed transcribed" in evidence_markdown(result)
    assert json.loads(main.with_suffix(".parsed.json").read_text("utf-8")) == canonical


def test_sidebar_does_not_capture_unit_superscripts_or_interleave_subscripts():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 9 Tf 1 0 0 1 30 703 Tm (Available online) Tj ET\n"
        b"BT /F1 10 Tf 1 0 0 1 300 700 Tm (h) Tj ET\n"
        b"BT /F1 6 Tf 1 0 0 1 306 704 Tm (-1) Tj ET\n"
        b"BT /F1 10 Tf 1 0 0 1 322 700 Tm (mg) Tj ET\n"
        b"BT /F1 6 Tf 1 0 0 1 336 698 Tm (cat) Tj ET\n"
        b"BT /F1 6 Tf 1 0 0 1 336 704 Tm (-1) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    lines = LayoutPdfBackend().extract_page(page, 1).lines
    units = " ".join(line.text for line in lines if line.x0 > 250)
    assert "h-1" in units
    assert "mgcat-1" in units.replace(" ", "")
    assert next(line.text for line in lines if line.x0 < 100) == "Available online"
