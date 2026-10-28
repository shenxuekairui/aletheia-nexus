"""A search reuses only per-request metadata; immutable source gates stay live."""

import json
import runpy
from collections import Counter
from pathlib import Path

import pytest

from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.parser import ParserConfig
from aletheia_nexus.content.service import parse_document
from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.research import WorkbenchResearch


@pytest.fixture
def workspace(tmp_path):
    writer = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    root = tmp_path / "library"
    for number in range(4):
        incoming = tmp_path / f"fixture-{number}.pdf"
        writer(
            incoming,
            [
                [
                    (50, 730, 15, f"Synthetic document {number}"),
                    (50, 650, 12, "A needle sample was measured."),
                ]
            ],
            title=f"Synthetic document {number}",
        )
        register_local_pdf(
            incoming, output_dir=root, title=f"Synthetic document {number}"
        )
    library = LibraryService(root)
    ids = [row["id"] for row in library.scan()["items"]]
    service = WorkbenchResearch(library, tmp_path / "workspace")
    parsed = service.parse(ids)
    assert all(item["status"] == "PARSED" for item in parsed["items"])
    yield service, ids, parsed
    service.close()


def test_full_metadata_indexes_read_once_per_search_and_scope_is_unchanged(
    workspace, monkeypatch
):
    from aletheia_nexus.workbench import library as library_module
    from aletheia_nexus.workbench import research as module

    service, ids, _ = workspace
    baseline = service.search("needle", ids, limit=4)
    calls, registry_reads = Counter(), []
    read, registry_read = module.read_json, library_module._read

    def observed(path):
        calls[str(path)] += 1
        return read(path)

    def registry_observed(path):
        if path == service.library.state_path:
            registry_reads.append(path)
        return registry_read(path)

    monkeypatch.setattr(module, "read_json", observed)
    monkeypatch.setattr(library_module, "_read", registry_observed)
    monkeypatch.setattr(
        service.library,
        "get",
        lambda _: pytest.fail("Search must not reread the entire registry per paper"),
    )
    first = service.search("needle", ids, limit=4)
    second = service.search("needle", ids, limit=4, offset=4)
    assert calls[str(service.index_path)] == 2
    assert calls[str(service.active_path)] == 2
    assert len(registry_reads) == 2
    assert first["coverage"] == baseline["coverage"]
    assert first["total_hits"] == baseline["total_hits"] >= 4
    assert first["hits"] == baseline["hits"]
    assert {hit["paper_id"] for hit in first["hits"] + second["hits"]} == set(ids)
    assert not (
        {hit["id"] for hit in first["hits"]} & {hit["id"] for hit in second["hits"]}
    )


def test_next_search_sees_new_active_version_not_previous_request_snapshot(workspace):
    service, ids, parsed = workspace
    paper_id = ids[0]
    old = next(
        row["document"]["artifact"]
        for row in parsed["items"]
        if row["paper_id"] == paper_id
    )
    first = service.search("needle", [paper_id])
    assert first["hits"][0]["artifact"] == old
    new = service.parse([paper_id], {"new_version": True})["items"][0]["document"][
        "artifact"
    ]
    assert new != old
    assert service.search("needle", [paper_id])["hits"][0]["artifact"] == new
    service.select_version(paper_id, old)
    assert service.search("needle", [paper_id])["hits"][0]["artifact"] == old


@pytest.mark.parametrize("changed", ["pdf", "sidecar", "artifact", "artifact_bytes"])
def test_concurrent_source_or_artifact_mutation_still_fails_final_verification(
    workspace, monkeypatch, changed
):
    from aletheia_nexus.workbench import research as module

    service, ids, parsed = workspace
    document = parsed["items"][0]["document"]
    original = module.search_corpus

    def mutate_after_match(*args, **kwargs):
        result = original(*args, **kwargs)
        path = Path(document["artifact" if changed == "artifact_bytes" else changed])
        if changed == "artifact":
            path.write_text('{"corrupt":true}', encoding="utf-8")
        elif changed == "artifact_bytes":
            path.write_bytes(path.read_bytes() + b"\n")
        else:
            path.write_bytes(path.read_bytes() + b" changed during search")
        return result

    monkeypatch.setattr(module, "search_corpus", mutate_after_match)
    expected = (
        "parsed_artifact_changed"
        if changed.startswith("artifact")
        else "source_changed"
    )
    with pytest.raises(ProcessingError, match=expected):
        service.search("needle", ids)


def test_parsed_source_checked_once_per_document_per_query_without_public_objects(
    workspace, monkeypatch
):
    service, ids, _ = workspace
    json.dumps(service.prepare(ids))
    original = service.app.check_document
    calls = Counter()

    def counted(document, mode):
        calls[mode] += 1
        return original(document, mode)

    monkeypatch.setattr(service.app, "check_document", counted)
    for _ in range(2):
        result = service.search("needle", ids)
        json.dumps(result)
    assert calls["direct"] == len(ids) * 2
    assert calls["parsed"] == len(ids) * 2


@pytest.mark.parametrize("changed", ["locator", "memory", "scope"])
def test_locator_memory_snapshot_or_authorized_scope_cannot_change_during_search(
    workspace, monkeypatch, changed
):
    from aletheia_nexus.workbench import research as module

    service, ids, parsed = workspace
    artifact = Path(parsed["items"][0]["document"]["artifact"])
    original = module.search_corpus

    def mutate_after_match(corpus, *args, **kwargs):
        result = original(corpus, *args, **kwargs)
        if changed == "locator":
            data = json.loads(artifact.read_text(encoding="utf-8"))
            data["source"]["locators"]["pdf"] = "unexpected-location.pdf"
            artifact.write_text(json.dumps(data), encoding="utf-8")
        elif changed == "memory":
            corpus.documents[0].document["blocks"][0]["text"] = "changed in memory"
        else:
            monkeypatch.setattr(service.app, "roots", ())
            monkeypatch.setattr(
                service.app, "workspace", service.workspace.parent / "revoked"
            )
        return result

    monkeypatch.setattr(module, "search_corpus", mutate_after_match)
    code = (
        "path_outside_allowed_directories"
        if changed == "scope"
        else "parsed_artifact_changed"
    )
    with pytest.raises(ProcessingError, match=code):
        service.search("needle", ids)


def test_wrong_valid_source_in_version_index_cannot_be_relabelled_as_selected_paper(
    workspace,
):
    service, ids, _ = workspace
    index = service._index()
    keys = {value[0]["document"]["id"]: key for key, value in index.items()}
    index[keys[ids[0]]] = index[keys[ids[1]]]
    write_json(service.index_path, index, overwrite=True)
    result = service.search("needle", [ids[0]])
    assert result["hits"] == []
    assert result["coverage"]["searched_documents"] == 0
    assert result["coverage"]["unsearched"][0]["paper_id"] == ids[0]


def test_legacy_discovery_does_not_replace_parser_configuration_for_later_new_material(
    workspace,
):
    service, _, _ = workspace
    writer = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    pdfs = []
    for name in ("legacy", "new"):
        incoming = service.library.root.parent / f"{name}.pdf"
        writer(incoming, [[(50, 730, 14, f"A {name} needle sample")]], title=name)
        pdfs.append(
            register_local_pdf(incoming, output_dir=service.library.root, title=name)
        )
    legacy_artifact = service.library.root / "legacy.parsed.json"
    parse_document(pdfs[0], output_path=legacy_artifact, config=ParserConfig())
    by_name = {
        row["title_original"]: row["id"] for row in service.library.scan()["items"]
    }
    prepared = service.prepare([by_name["legacy"], by_name["new"]])
    assert len(prepared["documents"]) == 2 and not prepared["unparsed"]
    assert legacy_artifact.is_file()
