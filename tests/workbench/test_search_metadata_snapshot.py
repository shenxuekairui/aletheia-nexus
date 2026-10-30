"""Bounded search reuse retains fresh byte, path and scope verification."""

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

    service, ids, _ = workspace
    baseline = service.search("needle", ids, limit=4)
    calls, registry_reads = Counter(), []
    read, registry_read = Path.read_bytes, library_module._read

    def observed(path):
        calls[str(path)] += 1
        return read(path)

    def registry_observed(path):
        if path == service.library.state_path:
            registry_reads.append(path)
        return registry_read(path)

    monkeypatch.setattr(Path, "read_bytes", observed)
    monkeypatch.setattr(library_module, "_read", registry_observed)
    monkeypatch.setattr(
        service.library,
        "get",
        lambda _: pytest.fail("Search must not reread the entire registry per paper"),
    )
    first = service.search("needle", ids, limit=4)
    second = service.search("needle", ids, limit=4, offset=4)
    # Each page reads the actual metadata bytes before and after matching, not
    # an index/registry per paper. No structural source gate is replayed.
    assert calls[str(service.index_path)] == 4
    assert calls[str(service.active_path)] == 4
    assert len(registry_reads) == 4
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
    assert calls["direct"] == len(ids)
    assert calls["parsed"] == len(ids)


def test_reply_mutation_does_not_alias_retained_corpus_and_new_keywords_reuse_it(
    workspace, monkeypatch
):
    service, ids, _ = workspace
    first = service.search("needle", ids, limit=4)
    assert service._search_session is not None
    first["hits"][0]["source"]["title"] = "Caller changed title"
    first["hits"][0]["evidence"][0]["page"] = 999
    first["hits"][0]["document"]["pdf"] = "caller-changed.pdf"
    monkeypatch.setattr(
        service.app,
        "check_document",
        lambda *_: pytest.fail("A verified corpus should not reparse the same bytes"),
    )
    second = service.search("needle", ids, limit=4)
    assert second["hits"][0]["source"]["title"] != "Caller changed title"
    assert second["hits"][0]["evidence"][0]["page"] == 1
    assert second["hits"][0]["document"]["pdf"] != "caller-changed.pdf"
    assert service.search("sample", ids)["hits"]


@pytest.mark.parametrize(
    "changed",
    ["library_pdf", "library_sidecar", "snapshot_pdf", "snapshot_sidecar", "artifact"],
)
def test_cached_page_hashes_all_original_and_snapshot_files_even_if_stat_is_unchanged(
    workspace, changed
):
    import os

    service, ids, parsed = workspace
    first = service.search("needle", ids)
    assert first["hits"] and service._search_session is not None
    paper = service.library.get(ids[0])
    document = next(
        row["document"] for row in parsed["items"] if row["paper_id"] == ids[0]
    )
    assert paper["pdf_path"] != document["pdf"]
    path = Path(
        {
            "library_pdf": paper["pdf_path"],
            "library_sidecar": paper["sidecar_path"],
            "snapshot_pdf": document["pdf"],
            "snapshot_sidecar": document["sidecar"],
            "artifact": document["artifact"],
        }[changed]
    )
    before = path.stat()
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 1
    path.write_bytes(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ProcessingError, match="source_changed|parsed_artifact_changed"):
        service.search("needle", ids, offset=4)
    assert service._search_session is None


def test_cache_is_one_scope_and_memory_limit_prevents_retention(workspace, monkeypatch):
    service, ids, _ = workspace
    service.search("needle", ids)
    assert service._search_session is not None
    first = service._search_session
    service.search("needle", ids[:1])
    assert service._search_session is not first
    assert service._search_session["key"] == (tuple(ids[:1]), True)
    service._search_cache_max_bytes = 1
    service._search_session = None
    service.search("needle", ids)
    assert service._search_session is None
    service.close()
    assert service._search_session is None


def test_version_snapshot_cannot_select_b_and_publish_it_under_a_signature(
    workspace, monkeypatch
):
    service, ids, parsed = workspace
    paper_id = ids[0]
    original_artifact = next(
        row["document"]["artifact"]
        for row in parsed["items"]
        if row["paper_id"] == paper_id
    )
    replacement = service.parse([paper_id], {"new_version": True})["items"][0][
        "document"
    ]["artifact"]
    service.select_version(paper_id, original_artifact)
    key = next(
        k
        for k, versions in service._index().items()
        if versions[0]["document"]["id"] == paper_id
    )
    original_build = service._build_search_session

    def a_b_a(*args, **kwargs):
        original = service.active_path.read_bytes()
        active_b = json.loads(original)
        active_b[key] = replacement
        write_json(service.active_path, active_b, overwrite=True)
        try:
            return original_build(*args, **kwargs)
        finally:
            service.active_path.write_bytes(original)

    monkeypatch.setattr(service, "_build_search_session", a_b_a)
    result = service.search("needle", [paper_id])
    assert result["hits"][0]["artifact"] == original_artifact


@pytest.mark.parametrize("existing_invalid", [False, True])
def test_cached_negative_scope_discovers_new_or_repaired_external_cli_artifact(
    workspace, existing_invalid
):
    import os

    service, ids, _ = workspace
    writer = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    incoming = service.library.root.parent / "external.pdf"
    writer(
        incoming,
        [[(50, 730, 14, "An external needle sample")]],
        title="External sample",
    )
    pdf = register_local_pdf(
        incoming, output_dir=service.library.root, title="External sample"
    )
    paper = next(
        row
        for row in service.library.scan()["items"]
        if row["title_original"] == "External sample"
    )
    artifact = service.library.root / "external.parsed.json"
    good = previous_stat = None
    if existing_invalid:
        parse_document(pdf, output_path=artifact)
        good = artifact.read_bytes()
        bad = good.replace(b'"ARTICLE"', b'"INVALID"', 1)
        assert bad != good and len(bad) == len(good)
        artifact.write_bytes(bad)
        previous_stat = artifact.stat()
    scope = [ids[0], paper["id"]]
    result = service.search("needle", scope)
    assert result["coverage"]["searched_documents"] == 1
    assert (
        service._search_session is not None and service._search_session["legacy_scan"]
    )
    unchanged_index = service.index_path.read_bytes()
    if existing_invalid:
        artifact.write_bytes(good)
        os.utime(artifact, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
    else:
        parse_document(pdf, output_path=artifact)
    assert service.index_path.read_bytes() == unchanged_index
    refreshed = service.search("needle", scope)
    assert refreshed["coverage"]["searched_documents"] == 2
    assert paper["id"] in {hit["paper_id"] for hit in refreshed["hits"]}


def test_cached_scope_rechecks_unused_artifact_locator_authorization(
    workspace, monkeypatch
):
    service, ids, parsed = workspace
    artifact = Path(parsed["items"][0]["document"]["artifact"])
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["source"]["locators"]["pdf"] = "unused-missing.pdf"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    service.search("needle", ids)
    assert service._search_session is not None
    original = service.app.path

    def revoked(path, **kwargs):
        if str(path).endswith("unused-missing.pdf"):
            raise ProcessingError("path_outside_allowed_directories")
        return original(path, **kwargs)

    monkeypatch.setattr(service.app, "path", revoked)
    with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
        service.search("needle", ids, offset=4)
    assert service._search_session is None


def test_warm_library_row_cannot_lend_its_native_id_to_another_valid_source_pair(
    workspace,
):
    import os

    service, ids, _ = workspace
    first, second = (service.library.get(paper_id) for paper_id in ids[:2])
    for field in ("pdf_path", "sidecar_path"):
        target, source = Path(first[field]), Path(second[field])
        before = target.stat()
        replacement = source.read_bytes()
        assert len(replacement) == before.st_size
        target.write_bytes(replacement)
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    # Metadata may remain cached under A, but full source validation sees B.
    assert service.library.get(ids[0])["id"] == ids[0]
    result = service.search("needle", [ids[0]])
    assert result["hits"] == [] and result["coverage"]["searched_documents"] == 0
    assert result["coverage"]["unsearched"][0]["error"] == "source_identity_mismatch"


def test_supplement_parent_must_match_the_actually_gated_selected_main(workspace):
    service, ids, _ = workspace
    writer = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    incoming = service.library.root.parent / "wrong-parent-si.pdf"
    writer(incoming, [[(50, 730, 14, "Synthetic supplemental needle")]], title="SI")
    attachment = service.library.import_attachment(ids[0], incoming)
    frozen_rows = {row["id"]: row for row in service.library.scan()["items"]}
    other = frozen_rows[ids[1]]
    sidecar = Path(attachment["sidecar_path"])
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["parent"].update(
        pdf_sha256=other["pdf_sha256"], article_id=other["article_id"]
    )
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    failures = []
    material = service._materials(
        [ids[0]], include_si=True, errors=failures, _papers=frozen_rows
    )
    assert len(material) == 1 and material[0]["id"] == ids[0]
    assert len(failures) == 1 and failures[0]["error"] == "source_identity_mismatch"


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
