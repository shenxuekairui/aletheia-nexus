import pytest

pytest.importorskip("nicegui")

from aletheia_nexus.workbench.ui_common import parameter_editor


def test_preset_roundtrip_preserves_nested_types_and_native_bytes():
    form = parameter_editor(
        {
            "max_calls": 10,
            "max_bytes": 1048576,
            "browser": {"use_system_proxy": None, "headless": False},
            "rules": ["保留原文"],
        }
    )
    form.apply(
        {
            "max_calls": 3,
            "max_bytes": 5242880,
            "browser": {"use_system_proxy": False},
            "rules": ["限制阶段", "保留单位"],
        }
    )
    assert form() == {
        "max_calls": 3,
        "max_bytes": 5242880,
        "browser": {"use_system_proxy": False, "headless": False},
        "rules": ["限制阶段", "保留单位"],
    }
    before = form()
    with pytest.raises(ValueError, match="预设值类型"):
        form.apply({"max_calls": 8, "browser": {"headless": "false"}})
    assert form() == before


def test_preset_rejects_unknown_or_retired_options_before_mutation():
    form = parameter_editor({"target_language": "zh-CN", "max_calls": 2})
    with pytest.raises(ValueError, match="不受支持"):
        form.apply({"max_calls": 9, "target_language": "en"})
    assert form()["max_calls"] == 2
    with pytest.raises(ValueError, match="不支持的参数"):
        form.apply({"api_key": "not-allowed"})
