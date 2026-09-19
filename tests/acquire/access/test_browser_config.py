from pathlib import Path

import pytest

from aletheia_nexus.acquire.access import BrowserAccessConfig, browser_profile_dir


def test_browser_profile_uses_dedicated_root(tmp_path):
    config = BrowserAccessConfig(
        profile_name="cas-institution",
        profile_root=tmp_path,
    )
    assert browser_profile_dir(config) == tmp_path / "cas-institution"


@pytest.mark.parametrize("name", ["../escape", ".", "..", "bad/name", ""])
def test_browser_profile_name_rejects_unsafe_paths(tmp_path, name):
    config = BrowserAccessConfig(
        profile_name=name,
        profile_root=tmp_path,
    )
    with pytest.raises(ValueError):
        browser_profile_dir(config)


def test_browser_profile_path_is_not_created_by_path_resolution(tmp_path):
    config = BrowserAccessConfig(
        profile_name="clean",
        profile_root=tmp_path,
    )
    path = browser_profile_dir(config)
    assert isinstance(path, Path)
    assert not path.exists()


def test_browser_interaction_callback_must_be_callable(tmp_path):
    config = BrowserAccessConfig(
        profile_name="bad-callback",
        profile_root=tmp_path,
        interaction_callback="not-callable",
    )
    with pytest.raises(TypeError):
        browser_profile_dir(config)


def test_headless_browser_rejects_interactive_handoff(tmp_path):
    config = BrowserAccessConfig(
        profile_name="headless",
        profile_root=tmp_path,
        headless=True,
        interactive=True,
    )
    with pytest.raises(ValueError):
        browser_profile_dir(config)
