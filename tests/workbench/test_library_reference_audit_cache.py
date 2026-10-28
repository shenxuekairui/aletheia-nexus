"""Repeated provenance strings share resolution, without omitting any path form."""

import json
from pathlib import Path

import pytest

from aletheia_nexus.workbench.library import LibraryService


def environment(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    library = LibraryService(tmp_path / "library", reference_roots=[workspace])
    source = library.root / "分类" / "原始正文.pdf"
    source.parent.mkdir()
    source.write_bytes(b"immutable-source")
    return library, workspace, source


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_repeated_full_candidates_resolve_once_per_audit(tmp_path, monkeypatch):
    library, workspace, source = environment(tmp_path)
    first = write(workspace / "runs/task-a.json", {"blocks": ["reported"] * 3000})
    second = write(workspace / "runs/task-b.json", {"blocks": ["reported"] * 3000})
    original = Path.resolve
    calls = []

    def resolve(path, *args, **kwargs):
        if path.name == "reported":
            calls.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    assert library._reference_risks([source]) == []
    assert sorted(calls) == sorted(
        [str(first.parent / "reported"), str(workspace / "reported")]
    )
    # A separate preview/execution must resolve afresh; no global stale cache.
    assert library._reference_risks([source]) == []
    assert len(calls) == 4
    assert first.exists() and second.exists()


@pytest.mark.parametrize("form", ["absolute", "record-relative", "root-relative"])
def test_all_reference_bases_and_parent_segments_still_block_move(tmp_path, form):
    library, workspace, source = environment(tmp_path)
    (workspace / "runs").mkdir()
    forms = {
        "absolute": str(source),
        "record-relative": "../../library/分类/原始正文.pdf",
        "root-relative": "../library/分类/原始正文.pdf",
    }
    record = write(
        workspace / "runs/task.json",
        {"metadata": ["reported"] * 100, "pdf": forms[form]},
    )
    before = record.read_bytes(), source.read_bytes()
    assert library._reference_risks([source]) == [str(record)]
    assert (record.read_bytes(), source.read_bytes()) == before


def test_different_alias_name_still_resolves_and_rechecks_between_audits(
    tmp_path, monkeypatch
):
    library, workspace, source = environment(tmp_path)
    # Model OS symlink resolution directly so this safety assertion also runs on
    # Windows CI hosts that cannot create symbolic links without elevated rights.
    alias = workspace / "unrelated-name.bin"
    alias.write_bytes(b"alias-fixture")
    record = write(workspace / "task.json", {"pdf": str(alias)})
    original = Path.resolve
    target = [source]

    def resolve(path, *args, **kwargs):
        return target[0] if path == alias else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    assert library._reference_risks([source]) == [str(record)]
    target[0] = workspace / "different.pdf"
    assert library._reference_risks([source]) == []
    target[0] = source
    assert library._reference_risks([source]) == [str(record)]


def test_actual_symbolic_link_reference_is_not_pruned_by_name(tmp_path):
    library, workspace, source = environment(tmp_path)
    alias = workspace / "unrelated-alias.bin"
    try:
        alias.symlink_to(source)
    except OSError:
        pytest.skip("This host does not permit creating symbolic links")
    record = write(workspace / "task.json", {"pdf": str(alias)})
    assert library._reference_risks([source]) == [str(record)]
