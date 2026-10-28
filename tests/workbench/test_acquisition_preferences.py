"""Acquisition presets reuse actual controls and never reuse fee authorization."""

from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui")
from nicegui import ui

from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.ui_acquisition import (
    AcquisitionPage,
    acquisition_recipe,
    acquisition_workflow_preferences,
    read_acquisition_preset,
)


def preferences():
    return {
        "template": "{year}-{title_zh}",
        "folder": "电合成/羧酸",
        "tags": ["重点", "待阅读"],
        "collection": "长期研究",
        "auto_parse": True,
        "title_translation": {
            "enabled": True,
            "consent": True,
            "options": {"max_cost": 0.3, "batch_size": 3},
        },
    }


def elements_since(previous):
    return {
        (e._props.get("label") or getattr(e, "text", None)): e
        for key, e in ui.context.client.elements.items()
        if key not in previous and (e._props.get("label") or getattr(e, "text", None))
    }


def test_recipe_and_default_roundtrip_excludes_consent_and_keeps_engine_separate(
    tmp_path,
):
    recipe = acquisition_recipe({"include_si": False, "timeout": 17}, preferences())
    assert "consent" not in str(recipe)
    assert recipe["workflow"]["title_translation"]["enabled"] is True
    assert "template" not in recipe["parameters"]
    settings = SettingsStore(tmp_path)
    settings.set("acquisition", recipe["parameters"])
    settings.set("acquisition_workflow", recipe["workflow"])
    settings.save_preset("acquisition", "中文整理", recipe)
    reopened = SettingsStore(tmp_path)
    assert (
        read_acquisition_preset(reopened.load_preset("acquisition", "中文整理"))
        == recipe
    )
    assert reopened.get("acquisition_workflow") == recipe["workflow"]
    assert "consent" not in settings.path.read_text("utf-8")
    legacy = read_acquisition_preset(
        {"timeout": 9, "include_si": True}, workflow_defaults=recipe["workflow"]
    )
    assert legacy["parameters"]["timeout"] == 9
    assert legacy["workflow"] == recipe["workflow"]


def test_saving_translation_preference_needs_no_consent_but_start_does(tmp_path):
    page = AcquisitionPage()
    page.ctx = SimpleNamespace(settings=SettingsStore(tmp_path))
    prior = set(ui.context.client.elements)
    read = page.title_translation_controls({"max_cost": 0.3}, initial_enabled=True)
    controls = elements_since(prior)
    authorization = controls[
        "我授权仅将待翻译的英文标题发送给DeepSeek，并接受所示费用上限"
    ]
    assert authorization.value is False
    assert read(require_consent=False)["enabled"] is True
    assert "consent" not in read(require_consent=False)
    with pytest.raises(ValueError, match="明确授权"):
        read()
    authorization.set_value(True)
    assert read()["consent"] is True
    read.apply(preferences()["title_translation"])
    assert authorization.value is False
    with pytest.raises(ValueError, match="明确授权"):
        read()


def test_saved_workflow_defaults_populate_actual_acquisition_form(tmp_path):
    settings = SettingsStore(tmp_path / "workspace")
    settings.set("acquisition", {"include_si": False, "timeout": 17})
    settings.set(
        "acquisition_workflow", acquisition_workflow_preferences(preferences())
    )

    class Page(AcquisitionPage):
        def title(self, *args):
            pass

        def import_dialog(self):
            pass

        def task_dialog(self):
            pass

    page = Page()
    page.ctx = SimpleNamespace(
        settings=settings,
        library=LibraryService(tmp_path / "library"),
        jobs=SimpleNamespace(list=lambda: []),
    )
    prior = set(ui.context.client.elements)
    page.acquisition_page()
    controls = elements_since(prior)
    assert controls["批次默认目录（未单独指定时）"].value == "电合成/羧酸"
    assert controls["批次默认标签（逗号分隔）"].value == "重点, 待阅读"
    assert controls["成功论文加入固定研究集合（可选）"].value == "长期研究"
    assert controls["实际模板（可直接修改）"].value == "{year}-{title_zh}"
    assert controls["成功后自动创建本地解析"].value is True
    assert controls["同时尝试获取 SI"].value is False
    assert controls["入库后自动翻译缺失的英文标题"].value is True
    assert (
        controls["我授权仅将待翻译的英文标题发送给DeepSeek，并接受所示费用上限"].value
        is False
    )
