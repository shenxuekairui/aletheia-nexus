import json
import shutil
from pathlib import Path

import pytest

from aletheia_nexus.content import (
    ChunkConfig,
    export_jsonl,
    export_markdown,
    load_parsed_document,
    parse_document,
    serialize_chunks,
    structure_aware_chunks,
    write_ai_export,
)

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "v07_fixtures"


def _artifact(tmp_path):
    source_dir = tmp_path / "portable"
    source_dir.mkdir()
    pdf = source_dir / "paper.pdf"
    sidecar = source_dir / "paper.acquisition.json"
    shutil.copy2(FIXTURES / "native_article.pdf", pdf)
    shutil.copy2(FIXTURES / "native_article.acquisition.json", sidecar)
    output = source_dir / "paper.parsed.json"
    parse_document(
        pdf,
        "10.5555/an.v07.native",
        sidecar_path=sidecar,
        output_path=output,
        created_at="2026-09-28T00:00:00+00:00",
    )
    return load_parsed_document(output)


def test_structure_aware_exports_are_deterministic_and_source_linked(tmp_path):
    artifact = _artifact(tmp_path)
    config = ChunkConfig(max_characters=512)

    first = structure_aware_chunks(artifact, config=config)
    second = structure_aware_chunks(artifact, config=config)

    assert first == second
    assert first["source_artifact_id"] == artifact.document["source"]["artifact_id"]
    assert first["parsed_artifact_id"] == artifact.document["artifact_id"]
    assert first["chunks"]
    for chunk in first["chunks"]:
        assert chunk["source_artifact_id"] == first["source_artifact_id"]
        assert chunk["parsed_artifact_id"] == first["parsed_artifact_id"]
        assert chunk["evidence"]
        assert all(
            {"block_id", "anchor_id", "page", "bbox", "coordinate_system"}
            <= evidence.keys()
            for evidence in chunk["evidence"]
        )

    markdown = export_markdown(artifact, config=config)
    assert "source_artifact_id:" in markdown
    assert "## 1 Introduction" in markdown
    assert "<!-- source block=" in markdown
    records = [
        json.loads(line) for line in export_jsonl(artifact, config=config).splitlines()
    ]
    assert records[0]["record_type"] == "manifest"
    assert all(record["record_type"] == "chunk" for record in records[1:])
    assert all(
        record["source_artifact_id"] == first["source_artifact_id"]
        and record["parsed_artifact_id"] == first["parsed_artifact_id"]
        for record in records[1:]
    )
    assert (
        json.loads(serialize_chunks(artifact, config=config))["chunks"]
        == first["chunks"]
    )


def test_export_and_parse_outputs_refuse_silent_overwrite(tmp_path):
    artifact = _artifact(tmp_path)
    output = tmp_path / "chunks.json"
    write_ai_export(output, serialize_chunks(artifact))
    before = output.read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        write_ai_export(output, serialize_chunks(artifact))
    assert output.read_bytes() == before
    write_ai_export(output, serialize_chunks(artifact), overwrite=True)

    protected = [
        artifact.path,
        artifact.path.parent / artifact.document["source"]["locators"]["pdf"],
        artifact.path.parent
        / artifact.document["source"]["locators"]["acquisition_sidecar"],
    ]
    for source in protected:
        source_before = source.read_bytes()
        with pytest.raises(ValueError, match="must not overwrite"):
            write_ai_export(source, export_markdown(artifact), overwrite=True)
        assert source.read_bytes() == source_before

    with pytest.raises(FileExistsError, match="already exists"):
        parse_document(
            FIXTURES / "native_article.pdf",
            "10.5555/an.v07.native",
            output_path=artifact.path,
        )


def test_parse_and_export_leave_other_partial_files_untouched(tmp_path):
    artifact = _artifact(tmp_path)
    output = tmp_path / "new.parsed.json"
    partial = output.with_suffix(output.suffix + ".part")
    partial.write_text("another writer owns this", encoding="utf-8")
    parse_document(
        FIXTURES / "native_article.pdf", "10.5555/an.v07.native", output_path=output
    )
    assert partial.read_text(encoding="utf-8") == "another writer owns this"
    exported = tmp_path / "new.ai.md"
    export_partial = exported.with_suffix(exported.suffix + ".part")
    export_partial.write_text("another export", encoding="utf-8")
    write_ai_export(exported, export_markdown(artifact))
    assert export_partial.read_text(encoding="utf-8") == "another export"


def test_relative_locators_survive_directory_move(tmp_path):
    artifact = _artifact(tmp_path)
    moved = tmp_path / "moved"
    shutil.copytree(artifact.path.parent, moved)
    relocated = load_parsed_document(moved / artifact.path.name)

    assert relocated.verify_local_sources() == {
        "pdf": True,
        "acquisition_sidecar": True,
    }
    assert not any(
        Path(value).is_absolute()
        for value in relocated.document["source"]["locators"].values()
    )


def test_parsed_identity_is_independent_of_timestamp_and_local_location(tmp_path):
    identities = []
    for index, timestamp in enumerate(
        ("2026-09-28T00:00:00+00:00", "2030-01-01T12:30:00+00:00"), start=1
    ):
        source = tmp_path / f"machine-{index}"
        source.mkdir()
        pdf = source / "renamed-paper.pdf"
        sidecar = source / "renamed-paper.acquisition.json"
        shutil.copy2(FIXTURES / "native_article.pdf", pdf)
        shutil.copy2(FIXTURES / "native_article.acquisition.json", sidecar)
        result = parse_document(
            pdf,
            "10.5555/an.v07.native",
            sidecar_path=sidecar,
            output_path=source / "artifact.parsed.json",
            created_at=timestamp,
        )
        identities.append(result.document["artifact_id"])

    assert identities[0] == identities[1]


def test_structure_aware_chunks_keep_table_evidence_separate(tmp_path):
    artifact = _artifact(tmp_path)
    result = structure_aware_chunks(artifact, config=ChunkConfig(max_characters=512))

    table = artifact.document["tables"][0]
    table_block_ids = set(table["object_block_ids"])
    table_chunks = [chunk for chunk in result["chunks"] if chunk["table"] is not None]

    assert table_chunks
    assert {chunk["table"]["id"] for chunk in table_chunks} == {table["id"]}
    observed_table_blocks = set().union(
        *(set(chunk["block_ids"]) for chunk in table_chunks)
    )
    assert observed_table_blocks == table_block_ids
    assert all(
        set(chunk["block_ids"]) <= table_block_ids and chunk["kind"] == "table-content"
        for chunk in table_chunks
    )
