from pathlib import Path

import pytest

from aletheia_nexus.storage_paths import PathPreferences, StoragePaths, relocate_path
from aletheia_nexus.workbench.settings import SettingsStore


@pytest.fixture
def preferences(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return PathPreferences()


def test_defaults_do_not_depend_on_launch_directory(preferences, tmp_path, monkeypatch):
    expected = preferences.resolve()
    for name in ("System32", "Desktop", "other-drive"):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.chdir(directory)
        assert preferences.resolve() == expected
        assert not (directory / ".aletheia-nexus").exists()
    assert expected.workspace == Path.home() / ".aletheia-nexus" / "workbench"
    assert expected.library == Path.home() / ".aletheia-nexus" / "library"


def test_explicit_saved_default_priority_and_independent_index(preferences, tmp_path):
    saved = StoragePaths(
        *(tmp_path / name for name in ("library", "index", "workspace"))
    )
    preferences.save(saved)
    assert preferences.resolve() == saved
    assert (
        preferences.resolve(workspace=tmp_path / "explicit").workspace
        == tmp_path / "explicit"
    )
    assert (
        preferences.resolve(
            library_state_dir=tmp_path / "explicit-index"
        ).library_state_dir
        == tmp_path / "explicit-index"
    )
    other = preferences.resolve(library=tmp_path / "other")
    assert other.library == tmp_path / "other"
    assert other.library_state_dir == other.library / ".an-workbench"
    assert preferences.path.parent != saved.workspace


def test_existing_v081_workspace_and_library_are_adopted(
    preferences, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    work = tmp_path / ".aletheia-nexus" / "workbench"
    library = tmp_path / "old-library"
    SettingsStore(work).set("library_root", str(library))
    paths = preferences.resolve()
    assert paths.workspace == work
    assert paths.library == library
    assert paths.library_state_dir == library / ".an-workbench"
    preferences.save(paths)
    monkeypatch.chdir(tmp_path.parent)
    assert preferences.resolve() == paths


def test_relative_paths_are_resolved_and_mapping_is_prefix_scoped(
    preferences, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    paths = preferences.resolve(workspace="custom", library="papers")
    assert paths.workspace == tmp_path / "custom"
    assert paths.library == tmp_path / "papers"
    aliases = {str(tmp_path / "old"): str(tmp_path / "new")}
    assert relocate_path(tmp_path / "old" / "x", aliases) == tmp_path / "new" / "x"
    assert relocate_path(tmp_path / "older" / "x", aliases) == tmp_path / "older" / "x"


def test_nested_relocations_follow_later_independent_index_move(tmp_path):
    old, new, index = (tmp_path / name for name in ("old", "new", "index"))
    aliases = {str(old): str(new), str(new / ".an-workbench"): str(index)}
    assert (
        relocate_path(old / ".an-workbench" / "library.json", aliases)
        == index / "library.json"
    )
    with pytest.raises(ValueError, match="循环"):
        relocate_path(old / "data", {str(old): str(new), str(new): str(old)})


def test_explicit_original_copy_overrides_relocation(preferences, tmp_path):
    old = StoragePaths(
        tmp_path / "old-library", tmp_path / "old-index", tmp_path / "old-work"
    )
    new = StoragePaths(
        tmp_path / "new-library", tmp_path / "new-index", tmp_path / "new-work"
    )
    mappings = {
        str(old.library): str(new.library),
        str(old.workspace): str(new.workspace),
    }
    preferences.save(new, relocations=mappings)
    assert preferences.relocations_for(new) == mappings
    assert preferences.relocations_for(old) == {}
