"""Explicit local imports and versioned parses preserve sources and old artifacts."""

from pathlib import Path

import pytest
from test_research_app import app as app
from test_research_app import write_pdf

from aletheia_nexus.content.corpus import load_corpus
from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import read_json


def test_declared_import_and_new_parser_version_are_corpus_visible(app, monkeypatch):
    service, original = app
    original_hash = sha256_file(original)
    imported = service.import_local_document(
        str(original), "Explicit local title", doi="10.1234/local-test"
    )
    document = imported["document"]
    assert imported["status"] == "REGISTERED"
    assert imported["source"]["identity_basis"] == "local_declared"
    assert imported["source"]["doi"] == "10.1234/local-test"
    assert imported["original_filename"] == original.name
    assert not acquisition_sidecar_path(original).exists()

    first = service.parse_document(document)
    old = Path(first["document"]["artifact"])
    before = {p: sha256_file(p) for p in (original, old, Path(document["sidecar"]))}
    import aletheia_nexus.content.parser as parser

    monkeypatch.setattr(parser, "PARSER_VERSION", "test-next-parser")
    second = service.parse_document(first["document"])
    new = Path(second["document"]["artifact"])
    assert new != old and new.name.endswith(".parsed.json")
    assert second["previous_artifact"] == str(old)
    assert second["parser"]["version"] == "test-next-parser"
    assert {p: sha256_file(p) for p in before} == before
    assert sha256_file(original) == original_hash
    assert second["network_access"] is False
    assert second["options"]["ocr"] is False
    corpus = load_corpus(service.workspace)
    assert len(corpus.documents) == 1
    assert corpus.documents[0].document["source"]["title"] == "Explicit local title"
    listed = service.list_documents(str(new.parent))["documents"][0]
    assert listed["status"] == "SOURCE_AVAILABLE"
    assert set(listed["parsed_artifacts"]) == {str(old), str(new)}


def test_prepare_reuses_legacy_name_even_when_parser_has_changed(app, monkeypatch):
    service, original = app
    first = service.prepare_documents([str(original)])["documents"][0]
    artifact = Path(first["artifact"])
    legacy = artifact.with_name("parsed-legacy.json")
    artifact.rename(legacy)
    old_hash = sha256_file(legacy)
    import aletheia_nexus.content.parser as parser
    import aletheia_nexus.research_app as module

    monkeypatch.setattr(parser, "PARSER_VERSION", "test-newer-version")
    monkeypatch.setattr(
        module, "parse_document", lambda *a, **k: pytest.fail("reparse")
    )
    reused = service.prepare_documents([str(original)])["documents"][0]
    assert reused["artifact"] == str(legacy)
    assert sha256_file(legacy) == old_hash
    assert service.search_documents([reused], "measured")["hits"]


def test_existing_supplement_identity_preserved_and_no_model_role_parameter(app):
    service, original = app
    main = register_local_pdf(
        original, output_dir=original.parent / "registered", title="Main"
    )
    supplement = original.parent / "support.pdf"
    write_pdf(
        supplement,
        [[(50, 700, 12, "Supplementary experimental context.")]],
        title="Support",
    )
    si = register_local_pdf(
        supplement,
        output_dir=original.parent / "registered-si",
        title="Support",
        role="SUPPLEMENT",
        parent_pdf=main,
    )
    before = {p: sha256_file(p) for p in (si, acquisition_sidecar_path(si))}
    with pytest.raises(ProcessingError, match="already_registered"):
        service.import_local_document(str(si), "Misdeclared main")
    with pytest.raises(TypeError):
        service.import_local_document(
            str(supplement), "SI", role="SUPPLEMENT", confirmed=True
        )
    prepared = service.prepare_documents([str(si)])["documents"][0]
    parsed = service.parse_document(prepared)
    source = validate_parser_input(
        parsed["document"]["pdf"], sidecar_path=parsed["document"]["sidecar"]
    )
    assert source.document_role == "SUPPLEMENT"
    assert source.parent["pdf_sha256"] == sha256_file(main)
    assert {p: sha256_file(p) for p in before} == before
    assert load_corpus(service.workspace).documents


def test_local_boundaries_precede_hash_copy_and_parse(app, tmp_path, monkeypatch):
    service, original = app
    import aletheia_nexus.research_app as module

    monkeypatch.setattr(
        module, "acquisition_sidecar_path", lambda _: tmp_path / "private.json"
    )
    monkeypatch.setattr(
        module, "sha256_file", lambda _: pytest.fail("hashed before path check")
    )
    for invoke in (
        lambda: service.import_local_document(str(original), "Title"),
        lambda: service.prepare_documents([str(original)]),
        lambda: service.parse_document({"id": "p", "pdf": str(original)}),
    ):
        with pytest.raises(ProcessingError, match="path_outside"):
            invoke()
    assert not (service.workspace / "materials").exists()


def test_parse_resource_status_and_prepare_bad_file_isolation(app):
    service, original = app
    two = original.parent / "two.pdf"
    write_pdf(
        two,
        [
            [(50, 700, 12, "First page, complete native experimental description.")],
            [(50, 700, 12, "Second page, further experimental description.")],
        ],
        title="Two pages",
    )
    imported = service.import_local_document(str(two), "Two pages")
    result = service.parse_document(imported["document"], max_pages=1)
    saved = read_json(Path(result["document"]["artifact"]))
    assert result["status"] == saved["status"] == "PARTIAL"
    assert result["warnings"] == saved["warnings"]
    bad = original.parent / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    prepared = service.prepare_documents([str(original), str(bad)])
    assert len(prepared["documents"]) == len(prepared["failures"]) == 1
    assert Path(prepared["documents"][0]["artifact"]).name.endswith(".parsed.json")


def test_optional_ocr_failure_is_visible_and_preserves_native_parse(app, monkeypatch):
    service, original = app
    document = service.prepare_documents([str(original)])["documents"][0]
    old = Path(document["artifact"])
    old_hash = sha256_file(old)
    import aletheia_nexus.content.backends.tesseract as tesseract

    def unavailable(*args, **kwargs):
        raise RuntimeError("OCR executable is unavailable: tesseract")

    # Exercise the actual adaptive backend and parse pipeline without launching OCR.
    monkeypatch.setattr(tesseract, "_run", unavailable)
    result = service.parse_document(document, ocr=True)
    data = read_json(Path(result["document"]["artifact"]))
    assert result["status"] == "PARTIAL"
    assert any(w["code"] == "OPTIONAL_BACKEND_FAILED" for w in result["warnings"])
    assert "measured at 25 C" in " ".join(b["text"] for b in data["blocks"])
    assert result["options"]["ocr"] is True
    assert sha256_file(old) == old_hash
