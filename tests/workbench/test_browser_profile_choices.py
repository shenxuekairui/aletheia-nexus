"""Profile selection reads directory names, not credentials or login contents."""

from copy import deepcopy
from pathlib import Path

import pytest

from aletheia_nexus.acquire.access.browser import browser_profile_dir
from aletheia_nexus.acquire.access.models import BrowserAccessConfig
from aletheia_nexus.workbench import defaults
from aletheia_nexus.workbench.acquisition import get_acquisition_defaults
from aletheia_nexus.workbench.settings import SettingsStore


def test_fresh_ui_aligns_cli_profile_without_changing_engine_defaults(tmp_path):
    original = get_acquisition_defaults()
    settings = SettingsStore(tmp_path)
    defaults.bootstrap_ui_defaults(settings)
    assert settings.get("acquisition")["browser"]["profile_name"] == "human-handoff"
    assert get_acquisition_defaults() == original
    assert original["browser"]["profile_name"] == "default"
    assert settings.get("acquisition")["browser"]["cdp_endpoint"] is None


def test_saved_profile_defaults_presets_and_settings_bytes_are_not_migrated(tmp_path):
    settings = SettingsStore(tmp_path)
    stored = {
        "browser": {"profile_name": "default", "profile_root": "existing-profiles"}
    }
    settings.set("acquisition", stored)
    settings.set("acquisition_workflow", {"auto_parse": False})
    settings.save_preset("acquisition", "旧机构会话", stored)
    before = settings.path.read_bytes()
    assert defaults.bootstrap_ui_defaults(settings)["initialized"] == []
    assert settings.path.read_bytes() == before
    assert settings.get("acquisition") == stored
    assert settings.load_preset("acquisition", "旧机构会话") == stored


def test_picker_lists_only_safe_first_level_directory_names_and_current_value(
    tmp_path, monkeypatch
):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    for name in [
        "human-handoff",
        "default",
        "institution-chrome",
        "bad name",
        "中文会话",
        ".bad",
    ]:
        (profiles / name).mkdir()
    (profiles / "not-a-directory").write_text("not a profile")
    (profiles / "human-handoff" / "nested-profile").mkdir()
    config = {"profile_root": str(profiles), "profile_name": "new-session"}
    original = deepcopy(config)

    def forbidden(*_, **__):
        pytest.fail("Profile selection must not read file contents or start browsers")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    result = defaults.browser_profile_choices(config)
    assert result["options"] == [
        "default",
        "human-handoff",
        "institution-chrome",
        "new-session",
    ]
    assert result["current"] == "new-session" and result["warnings"] == []
    assert config == original and not (profiles / "new-session").exists()


@pytest.mark.parametrize("kind", ["symlink", "junction"])
def test_picker_excludes_linked_directories_without_traversing_them(
    tmp_path, monkeypatch, kind
):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    linked = profiles / "linked-session"
    linked.mkdir()
    (profiles / "safe-session").mkdir()
    attribute = "is_symlink" if kind == "symlink" else "is_junction"
    original = getattr(Path, attribute, lambda _: False)
    monkeypatch.setattr(
        Path, attribute, lambda path: path == linked or original(path), raising=False
    )
    result = defaults.browser_profile_choices(
        {"profile_root": profiles, "profile_name": "linked-session"}
    )
    assert result["options"] == ["safe-session"]
    assert result["current"] == "linked-session" and result["warnings"]


def test_picker_rejects_linked_root_without_enumerating_any_descendant(
    tmp_path, monkeypatch
):
    profiles = tmp_path / "linked-profiles"
    profiles.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path == profiles or original(path)
    )
    monkeypatch.setattr(
        Path, "iterdir", lambda _: pytest.fail("linked root must not be enumerated")
    )
    result = defaults.browser_profile_choices(
        {"profile_root": profiles, "profile_name": "saved"}
    )
    assert result["options"] == ["saved"] and result["current"] == "saved"
    assert result["warnings"]


def test_picker_preserves_invalid_saved_value_without_listing_it_or_creating_root(
    tmp_path,
):
    root = tmp_path / "absent"
    result = defaults.browser_profile_choices(
        {"profile_root": root, "profile_name": "../outside"}
    )
    assert result["current"] == "../outside" and result["options"] == []
    assert result["warnings"] and not root.exists()


def test_picker_uses_core_default_root_helper_without_creating_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "unused-home")
    expected = browser_profile_dir(
        BrowserAccessConfig(profile_name="human-handoff")
    ).parent
    result = defaults.browser_profile_choices()
    assert result["root"] == str(expected)
    assert result["options"] == ["human-handoff"]
    assert not expected.exists()
