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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("headless", 1),
        ("interactive", "yes"),
        ("wait_for_interaction", "yes"),
        ("keep_unverified", 0),
    ],
)
def test_browser_boolean_options_require_real_bools(tmp_path, field, value):
    kwargs = {
        "profile_name": "typed-config",
        "profile_root": tmp_path,
        field: value,
    }
    config = BrowserAccessConfig(**kwargs)

    with pytest.raises(TypeError, match=field):
        browser_profile_dir(config)


def test_browser_channel_rejects_blank_or_non_string_values(tmp_path):
    with pytest.raises(ValueError, match="channel"):
        browser_profile_dir(
            BrowserAccessConfig(
                profile_root=tmp_path,
                channel="   ",
            )
        )

    with pytest.raises(TypeError, match="channel"):
        browser_profile_dir(
            BrowserAccessConfig(
                profile_root=tmp_path,
                channel=123,
            )
        )


def test_browser_profile_name_type_error_is_explicit(tmp_path):
    config = BrowserAccessConfig(
        profile_name=123,
        profile_root=tmp_path,
    )

    with pytest.raises(TypeError, match="profile_name"):
        browser_profile_dir(config)


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "ws://127.0.0.1:9222",
        "http://192.168.1.10:9222",
        "http://user:pass@127.0.0.1:9222",
    ],
)
def test_browser_cdp_endpoint_must_be_safe_loopback_http(tmp_path, endpoint):
    config = BrowserAccessConfig(
        profile_root=tmp_path,
        cdp_endpoint=endpoint,
    )

    with pytest.raises((TypeError, ValueError), match="cdp_endpoint"):
        browser_profile_dir(config)


def test_browser_cdp_endpoint_accepts_loopback_http(tmp_path):
    config = BrowserAccessConfig(
        profile_root=tmp_path,
        cdp_endpoint="http://127.0.0.1:9222",
    )

    assert browser_profile_dir(config) == tmp_path / "default"
