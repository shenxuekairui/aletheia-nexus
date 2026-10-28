"""Read-only original-layout access must retain scope and honest provenance."""

import hashlib
from contextlib import closing
from copy import deepcopy

import pytest
from test_research_app import write_pdf

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import ResearchApplication


def test_original_text_layout_without_parse_key_or_renderer(tmp_path, monkeypatch):
    papers = tmp_path / "论文"
    papers.mkdir()
    pdf = papers / "条件.PDF"
    write_pdf(
        pdf,
        [
            [
                (50, 700, 12, "Object"),
                (230, 700, 12, "Condition"),
                (50, 680, 12, "Sample A"),
                (230, 680, 12, "12 ms"),
                (50, 660, 12, "Sample B"),
                (230, 660, 12, "7 ms"),
            ]
        ],
        title="Self-authored layout fixture",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "")
    with closing(ResearchApplication([papers], tmp_path / "results")) as app:
        document = app.import_local_document(str(pdf), "Self-authored layout fixture")[
            "document"
        ]
        assert "artifact" not in document
        before = {p: sha256_file(p) for p in papers.rglob("*") if p.is_file()}
        full = app.read_original_page_text(document, 1)
        repeated = app.read_original_page_text(document, 1)
        assert full == repeated
        assert full["source"]["pdf_sha256"] == sha256_file(pdf)
        assert full["reading"] == "derived_native_layout_not_scientifically_verified"
        assert full["network_access"] is full["text_truncated"] is False
        assert full["has_native_text"]
        lines = full["text"].splitlines()
        a = next(line for line in lines if "Sample A" in line)
        b = next(line for line in lines if "Sample B" in line)
        assert "12 ms" in a and "7 ms" not in a
        assert "7 ms" in b and "12 ms" not in b
        assert full["text_sha256"] == hashlib.sha256(full["text"].encode()).hexdigest()
        clipped = app.read_original_page_text(document, 1, 8)
        assert clipped["text_truncated"] and clipped["text"] == full["text"][:8]
        assert clipped["artifact_id"] != full["artifact_id"]
        assert clipped["total_characters"] == len(full["text"])
        assert before == {p: sha256_file(p) for p in papers.rglob("*") if p.is_file()}
        assert not list(app.workspace.rglob("*.parsed.json"))
        for page in (0, 2, True):
            with pytest.raises(ProcessingError, match="page_out_of_bounds"):
                app.read_original_page_text(document, page)
        outside = tmp_path / "private.pdf"
        write_pdf(outside, [[(50, 700, 12, "Private text")]], title="Private")
        escaped = deepcopy(document)
        escaped["pdf"] = str(outside)
        with pytest.raises(ProcessingError, match="path_outside"):
            app.read_original_page_text(escaped, 1)


def test_blank_text_layer_is_not_scientific_absence(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    pdf = papers / "blank.pdf"
    write_pdf(pdf, [[]], title="Blank fixture")
    with closing(ResearchApplication([papers], tmp_path / "results")) as app:
        document = app.import_local_document(str(pdf), "Blank fixture")["document"]
        result = app.read_original_page_text(document, 1)
        assert result["text"] == "" and not result["has_native_text"]
        assert result["text_truncated"] is False
        assert any(
            "does not establish scientific absence" in s for s in result["limitations"]
        )
