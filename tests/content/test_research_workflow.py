import json
import shutil
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from aletheia_nexus.content import ParsedArtifact, parse_document, write_ai_export
from aletheia_nexus.content.batch import parse_batch
from aletheia_nexus.content.corpus import content_units, load_corpus, search_corpus
from aletheia_nexus.content.evidence import build_evidence_pack, evidence_markdown
from aletheia_nexus.content.gate import validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.parser import ParserConfig
from aletheia_nexus.content.query import match_score, normalize_search_text, query_terms
from aletheia_nexus.content.schema import compute_parsed_artifact_id
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "v07_fixtures"


def paper(tmp_path, name="paper"):
    root = tmp_path / name
    return register_local_pdf(
        FIXTURES / "native_article.pdf", output_dir=root, title="Local research paper"
    )


def corpus(tmp_path):
    pdf = paper(tmp_path)
    parse_document(pdf)
    return pdf.parent


def test_no_doi_and_supplement_keep_independent_identity_and_pages(tmp_path):
    pdf = paper(tmp_path)
    main = parse_document(pdf)
    si = register_local_pdf(
        FIXTURES / "two_column_article.pdf",
        output_dir=pdf.parent,
        title="Supporting information",
        role="SUPPLEMENT",
        parent_pdf=pdf,
    )
    supplement = parse_document(si)
    source = supplement.document["source"]
    assert source["doi"] is None
    assert source["identity_basis"] == "local_declared"
    assert source["parent"]["pdf_sha256"] == main.source.pdf_sha256
    assert source["document_role"] == "SUPPLEMENT"
    assert min(b["page"] for b in supplement.document["blocks"]) == 1
    with pytest.raises(ValueError, match="distinct main"):
        register_local_pdf(
            pdf,
            output_dir=tmp_path / "bad",
            title="same bytes",
            role="SUPPLEMENT",
            parent_pdf=pdf,
        )
    with pytest.raises(ValueError, match="DOI_MISMATCH"):
        validate_parser_input(pdf, "10.5555/invented")
    before = acquisition_sidecar_path(pdf).read_bytes()
    with pytest.raises(FileExistsError):
        register_local_pdf(pdf, output_dir=pdf.parent, title="different identity")
    assert acquisition_sidecar_path(pdf).read_bytes() == before


def test_query_semantics_chinese_and_or_phrase_and_numeric_typography():
    terms = query_terms('乙醇酸 "法拉第效率"')
    assert match_score("乙 醇 酸的法 拉 第 效 率为80.90%", terms) is not None
    assert match_score("乙醇酸", terms) is None
    assert match_score("乙醇酸", terms, mode="or") is not None
    assert (
        match_score("Faradaic high efficiency", query_terms('"Faradaic efficiency"'))
        is None
    )
    assert (
        match_score("Faradaic efficiency", query_terms('"Faradaic efficiency"'))
        is not None
    )
    assert normalize_search_text("８３∙６％ −1.4 V 80⎯85%") == "83.6% -1.4 v 80-85%"
    assert match_score("1.4 V", query_terms("−1.4")) is None
    with pytest.raises(ValueError, match="unclosed"):
        query_terms('"unfinished')


def test_corpus_deduplicates_bytes_and_reports_missing_or_changed_sources(tmp_path):
    root = corpus(tmp_path)
    first = search_corpus(root, "source-linked blocks")
    shutil.copy2(root / "native_article.pdf", root / "duplicate.pdf")
    second = search_corpus(root, "source-linked blocks")
    assert first["hits"] == second["hits"]
    assert len(second["coverage"]["duplicates"]) == 1
    shutil.copy2(FIXTURES / "two_column_article.pdf", root / "unparsed.pdf")
    assert search_corpus(root, "neverappears")["coverage"]["complete"] is False
    sidecar = acquisition_sidecar_path(root / "native_article.pdf")
    payload = json.loads(sidecar.read_text("utf-8"))
    payload["identity_validation"]["document_role"] = "SUPPLEMENT"
    sidecar.write_text(json.dumps(payload), "utf-8")
    changed = search_corpus(root, "source-linked")
    assert not changed["hits"]
    assert any(
        "identity/role" in item["reason"] for item in changed["coverage"]["unsearched"]
    )


def test_corpus_preserves_different_versions_with_same_doi(tmp_path):
    for filename in ("native_article.pdf", "two_column_article.pdf"):
        pdf = register_local_pdf(
            FIXTURES / filename,
            output_dir=tmp_path,
            title="Two versions",
            doi="10.5555/versions",
        )
        parse_document(pdf)
    loaded = load_corpus(tmp_path)
    assert len(loaded.documents) == 2
    assert not loaded.duplicates


def test_selected_export_ids_budget_and_folder_relocation(tmp_path):
    root = corpus(tmp_path)
    results = search_corpus(root, "source-linked")
    by_number = build_evidence_pack(root, report=results, selectors=["1"])
    by_id = build_evidence_pack(
        root, report=results, selectors=[results["hits"][0]["id"]]
    )
    assert by_number == by_id
    assert "PDF p. 1" in evidence_markdown(by_id)
    assert by_id["included"][0]["source"]["doi"] is None
    small = build_evidence_pack(root, report=results, selectors=["1"], max_characters=1)
    assert not small["included"] and small["skipped"]
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    assert build_evidence_pack(moved, report=results, selectors=["1"]) == by_id
    # Export reconstructs evidence, instead of trusting editable result excerpts.
    results["hits"][0]["text"] = "invented measurement"
    assert build_evidence_pack(root, report=results, selectors=["1"]) == by_id
    parse_document(
        root / "native_article.pdf",
        config=ParserConfig(merge_paragraph_lines=False),
        overwrite=True,
    )
    with pytest.raises(ValueError, match="stale"):
        build_evidence_pack(root, report=results, selectors=["1"])


def test_batch_interrupt_resume_and_config_change(tmp_path):
    for filename in ("native_article.pdf", "two_column_article.pdf"):
        register_local_pdf(FIXTURES / filename, output_dir=tmp_path, title=filename)

    def interrupt(row):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        parse_batch(tmp_path, progress=interrupt)
    checkpoint = json.loads((tmp_path / "parse-report.json").read_text("utf-8"))
    assert checkpoint["interrupted"]
    assert checkpoint["counts"]["PENDING"] == 1
    result = parse_batch(tmp_path)
    assert result["items"][0]["resumed"] is True
    assert result["items"][1]["resumed"] is False
    assert all(row["resumed"] for row in parse_batch(tmp_path)["items"])
    assert not any(
        row["resumed"]
        for row in parse_batch(
            tmp_path, config=ParserConfig(merge_paragraph_lines=False)
        )["items"]
    )


def test_v2_remains_readable_exportable_and_protected(tmp_path):
    root = corpus(tmp_path)
    path = root / "native_article.parsed.json"
    doc = json.loads(path.read_text("utf-8"))
    doc["schema"] = "aletheia-nexus/parsed-document/v2"
    doc["source"]["doi"] = "10.5555/legacy"
    for key in ("title", "article_id", "document_role", "identity_basis", "parent"):
        doc["source"].pop(key)
    doc["artifact_id"] = compute_parsed_artifact_id(doc)
    path.write_text(json.dumps(doc), "utf-8")
    assert ParsedArtifact.load(path).search("source-linked")
    with pytest.raises(ValueError, match="must not overwrite"):
        write_ai_export(path, "export", overwrite=True)


def test_table_unit_retains_footnote_without_claiming_interpretation():
    blocks = [
        {
            "id": "b1",
            "order": 1,
            "page": 1,
            "kind": "caption",
            "text": "Table 1. Yields",
        },
        {"id": "b2", "order": 2, "page": 1, "kind": "paragraph", "text": "Entry 1: 93"},
        {
            "id": "b3",
            "order": 3,
            "page": 1,
            "kind": "paragraph",
            "text": "aReaction condition: 70 C, 3 h.",
        },
        {
            "id": "b4",
            "order": 4,
            "page": 1,
            "kind": "paragraph",
            "text": "bNMR yield using an internal standard.",
        },
        {"id": "b5", "order": 5, "page": 1, "kind": "heading", "text": "Discussion"},
    ]
    units = content_units(
        {
            "blocks": blocks,
            "tables": [
                {"id": "t1", "caption_block_id": "b1", "object_block_ids": ["b2"]}
            ],
        }
    )
    table = next(u for u in units if u["kind"] == "table")
    assert match_score(table["text"], query_terms("93 NMR"))
    assert "Discussion" not in table["text"]


def test_external_pdf_link_is_reported_in_batch_and_search(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    link = root / "linked.pdf"
    try:
        link.symlink_to(FIXTURES / "native_article.pdf")
    except OSError:
        pytest.skip("creating symbolic links is unavailable on this host")
    report = parse_batch(root)
    assert report["counts"] == {"FAILED": 1}
    assert "outside" in report["items"][0]["error"]
    coverage = search_corpus(root, "source-linked")["coverage"]
    assert not coverage["complete"]
    assert len(coverage["unsearched"]) == 1
    assert "outside" in coverage["unsearched"][0]["reason"]


def test_legacy_and_current_artifacts_of_same_source_deduplicate(tmp_path):
    pdf = register_local_pdf(
        FIXTURES / "native_article.pdf",
        output_dir=tmp_path,
        title="Legacy and current",
        doi="10.5555/legacy",
    )
    parse_document(pdf)
    path = pdf.with_suffix(".parsed.json")
    legacy = json.loads(path.read_text("utf-8"))
    legacy["schema"] = "aletheia-nexus/parsed-document/v2"
    for key in ("title", "article_id", "document_role", "identity_basis", "parent"):
        legacy["source"].pop(key)
    legacy["artifact_id"] = compute_parsed_artifact_id(legacy)
    (tmp_path / "legacy.parsed.json").write_text(json.dumps(legacy), "utf-8")
    loaded = load_corpus(tmp_path)
    assert len(loaded.documents) == 1
    assert not loaded.unsearched
    assert len(loaded.duplicates) == 1
    assert search_corpus(loaded, "source-linked")["hits"]


def test_glyph_layout_keeps_superscript_and_column_separation(tmp_path):
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
        b"BT /F1 10 Tf 1 0 0 1 30 700 Tm (Current density -100.2 mA cm) Tj /F1 6 Tf 1 0 0 1 158 704 Tm (-2) Tj ET\nBT /F1 10 Tf 1 0 0 1 320 700 Tm (Other column 91.7 percent) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    pdf = tmp_path / "science.pdf"
    writer.write(pdf)
    register_local_pdf(pdf, output_dir=tmp_path, title="Scientific layout")
    result = parse_document(pdf)
    texts = [b["text"] for b in result.document["blocks"]]
    left = next(t for t in texts if "-100.2" in t)
    assert "-2" in left
    assert "91.7" not in left
    assert any("91.7" in text for text in texts)
