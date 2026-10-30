"""One validated local snapshot keeps all source/role/correction gates intact."""

import json
import runpy
from pathlib import Path

import pytest

from aletheia_nexus.content.artifact import ParsedArtifact
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.schema import compute_parsed_artifact_id
from aletheia_nexus.content.service import parse_document
from aletheia_nexus.processing.materials import load_source
from aletheia_nexus.processing.provider import ProcessingError


@pytest.fixture
def documents(tmp_path):
    writer = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    paths = []
    for name in ("main", "supplement"):
        path = tmp_path / f"{name}.pdf"
        writer(
            path,
            [[(50, 730, 14, f"Synthetic {name}"), (50, 650, 12, "Measured 5 units.")]],
            title=name,
        )
        paths.append(path)
    main = register_local_pdf(
        paths[0], output_dir=tmp_path / "library", title="Declared main"
    )
    si = register_local_pdf(
        paths[1],
        output_dir=tmp_path / "library/SI",
        title="Declared supplement",
        role="SUPPLEMENT",
        parent_pdf=main,
    )
    configs = []
    for pdf in (main, si):
        artifact = pdf.with_suffix(".parsed.json")
        parse_document(pdf, output_path=artifact)
        configs.append({"id": pdf.stem, "artifact": str(artifact)})
    return tmp_path, configs


def test_load_source_reads_one_validated_snapshot_for_each_article_and_si(
    documents, monkeypatch
):
    base, configs = documents
    original = ParsedArtifact.document.fget
    reads = []

    def observed(self):
        reads.append(self.path)
        return original(self)

    monkeypatch.setattr(ParsedArtifact, "document", property(observed))
    article = load_source(configs[0], base, "parsed")
    supplement = load_source(configs[1], base, "parsed")
    assert len(reads) == 2
    assert article.identity["document_role"] == "ARTICLE"
    assert supplement.identity["document_role"] == "SUPPLEMENT"
    assert supplement.identity["parent"]["pdf_sha256"] == article.identity["pdf_sha256"]


@pytest.mark.parametrize("field", ["role", "parent", "title"])
def test_valid_but_wrong_parsed_source_declaration_is_still_rejected(documents, field):
    base, configs = documents
    artifact = Path(configs[1]["artifact"])
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    if field == "role":
        payload["source"].update(document_role="ARTICLE", parent=None)
    elif field == "parent":
        payload["source"]["parent"]["article_id"] = "different-parent"
    else:
        payload["source"]["title"] = "Different declared title"
    payload["artifact_id"] = compute_parsed_artifact_id(payload)
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProcessingError, match="source_identity_mismatch"):
        load_source(configs[1], base, "parsed")


def test_correction_original_text_and_page_bounds_are_still_checked(documents):
    base, configs = documents
    source = load_source(configs[0], base, "parsed")
    block = source.artifact.document["blocks"][0]
    correction = {
        "block_id": block["id"],
        "original": block["text"],
        "replacement": "Reviewed text",
    }
    assert load_source({**configs[0], "corrections": [correction]}, base, "parsed")
    with pytest.raises(ValueError, match="exact original"):
        load_source(
            {**configs[0], "corrections": [{**correction, "original": "wrong text"}]},
            base,
            "parsed",
        )
    with pytest.raises(ValueError, match="one correction"):
        load_source(
            {**configs[0], "corrections": [correction, correction]}, base, "parsed"
        )
    with pytest.raises(ProcessingError, match="page_out_of_bounds"):
        load_source({**configs[0], "pages": [2]}, base, "parsed")


@pytest.mark.parametrize("mutation", ["schema", "content", "pdf"])
def test_source_bytes_schema_and_canonical_content_tamper_still_fail(
    documents, mutation
):
    base, configs = documents
    artifact = Path(configs[0]["artifact"])
    if mutation == "pdf":
        source = load_source(configs[0], base, "parsed")
        source.pdf.write_bytes(source.pdf.read_bytes() + b" changed")
    else:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if mutation == "schema":
            payload["schema"] = "invalid/schema"
        else:
            payload["blocks"][0]["text"] = "Unbound new content"
        artifact.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        load_source(configs[0], base, "parsed")
