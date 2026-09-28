import json
from pathlib import Path

from aletheia_nexus.content import (
    ParsedArtifact,
    load_parsed_document,
    parse_document,
)

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "v07_fixtures"


def _artifact(tmp_path):
    output = tmp_path / "native.parsed.json"
    parse_document(
        FIXTURES / "native_article.pdf",
        "10.5555/an.v07.native",
        output_path=output,
    )
    return load_parsed_document(output)


def test_search_returns_source_anchor_and_section(tmp_path):
    artifact = _artifact(tmp_path)
    hits = artifact.search("source-linked blocks")
    assert hits[0].page == 1
    assert hits[0].section_heading == "1 Introduction"
    assert hits[0].bbox is not None
    assert artifact.locate(hits[0].block_id)["text_evidence"] == hits[0].text


def test_search_can_filter_semantic_section_and_read_section_text(tmp_path):
    artifact = _artifact(tmp_path)
    hits = artifact.search("score", section_type="methods")
    assert len(hits) == 1
    section_id = hits[0].section_id
    assert section_id is not None
    text = artifact.section_text(section_id)
    assert "2 Methods" in text
    assert "S = correct / total" in text


def test_artifact_rechecks_local_source_hashes(tmp_path):
    artifact = _artifact(tmp_path)
    assert artifact.verify_local_sources() == {
        "pdf": True,
        "acquisition_sidecar": True,
    }

    payload = json.loads(json.dumps(artifact.document))
    payload["source"]["pdf_path"] = str(tmp_path / "missing.pdf")
    assert ParsedArtifact(payload).verify_local_sources()["pdf"] is False


def test_search_validates_query_and_limit(tmp_path):
    artifact = _artifact(tmp_path)
    for query, limit in (("", 20), ("valid", 0)):
        try:
            artifact.search(query, limit=limit)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid search input must fail")
