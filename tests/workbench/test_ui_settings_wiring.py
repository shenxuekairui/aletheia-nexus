"""Visible settings save actual defaults, while all remote requests remain opt-in."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui")

from nicegui import ui

from aletheia_nexus.workbench import ui as ui_module
from aletheia_nexus.workbench import ui_research
from aletheia_nexus.workbench.api_settings import ApiSettingsService
from aletheia_nexus.workbench.defaults import bootstrap_ui_defaults
from aletheia_nexus.workbench.labels import PARAMETER_LABELS
from aletheia_nexus.workbench.research import WorkbenchResearch
from aletheia_nexus.workbench.research_defaults import research_defaults
from aletheia_nexus.workbench.settings import SettingsStore


def within(element, parent):
    while element is not None:
        if element is parent:
            return True
        element = element.parent_slot.parent if element.parent_slot else None
    return False


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    callbacks = {}
    original_button = ui.button

    def button(text, **kwargs):
        result = original_button(text, **kwargs)
        callbacks[text] = kwargs.get("on_click"), result
        return result

    settings = SettingsStore(tmp_path / "workspace")
    bootstrap_ui_defaults(settings)
    api = ApiSettingsService(
        settings,
        tmp_path / "workspace",
        can_change=lambda: True,
        credential_backend=None,
        environ={},
    )
    monkeypatch.setattr(
        api,
        "check_connection",
        lambda **_: pytest.fail("Opening settings must not connect"),
    )
    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui, "notify", lambda *a, **k: None)
    monkeypatch.setattr(ui_module, "guard", lambda callback: callback)
    page = ui_module.WorkbenchUI.__new__(ui_module.WorkbenchUI)
    page.ctx = SimpleNamespace(
        library=SimpleNamespace(root=tmp_path / "library"),
        workspace=tmp_path / "workspace",
        settings=settings,
        api_settings=api,
        research=SimpleNamespace(parser_options=WorkbenchResearch.parser_options),
    )
    before = set(ui.context.client.elements)
    page.settings_dialog()
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]

    def section(text):
        parent = next(
            element
            for element in elements
            if isinstance(element, ui.expansion) and element.text == text
        )
        return [element for element in elements if within(element, parent)]

    def control(section_name, key):
        return next(
            element
            for element in section(section_name)
            if getattr(element, "label", None) == PARAMETER_LABELS[key]
        )

    return SimpleNamespace(
        settings=settings,
        callbacks=callbacks,
        elements=elements,
        section=section,
        control=control,
        root=tmp_path,
    )


def test_api_card_is_above_library_controls_and_opening_never_calls_endpoint(mounted):
    elements = mounted.elements
    heading = next(
        element
        for element in elements
        if getattr(element, "text", "") == "DeepSeek API 配置"
    )
    library = next(
        element
        for element in elements
        if getattr(element, "label", "") == "文献库根目录"
    )
    assert elements.index(heading) < elements.index(library)
    assert any(getattr(element, "text", "") == "保存 API 配置" for element in elements)
    assert not any(
        "API密钥从系统环境读取" in getattr(element, "text", "") for element in elements
    )


def test_acquisition_and_workflow_settings_write_keys_read_by_new_task_forms(mounted):
    mounted.control("论文获取常用默认值", "bulk_interval").set_value(2.5)
    mounted.control("论文获取常用默认值", "max_item_attempts").set_value(2)
    mounted.callbacks["保存论文获取默认值"][0]()
    assert mounted.settings.get("acquisition")["bulk_interval"] == 2.5
    assert mounted.settings.get("acquisition")["max_item_attempts"] == 2
    workflow = mounted.section("入库与命名默认值")
    next(
        element
        for element in workflow
        if getattr(element, "label", None) == "正文与 SI 共用命名模板"
    ).set_value("{year}-{journal}-{title_original}")
    next(
        element
        for element in workflow
        if getattr(element, "text", None) == "入库后自动解析"
    ).set_value(False)
    mounted.callbacks["保存入库与命名默认值"][0]()
    saved = mounted.settings.get("acquisition_workflow")
    assert saved["template"] == "{year}-{journal}-{title_original}"
    assert saved["auto_parse"] is False
    assert "consent" not in saved["title_translation"]
    assert not (
        mounted.root / "library"
    ).exists()  # Preferences do not import/create folders.


def test_invalid_defaults_do_not_replace_previous_preferences(mounted):
    before = mounted.settings.path.read_bytes()
    mounted.control("科研模型与预算默认值", "max_cost").set_value(0)
    with pytest.raises(ValueError, match="科研默认设置不符合任务契约"):
        mounted.callbacks["保存科研默认参数"][0]()
    assert mounted.settings.path.read_bytes() == before
    mounted.control("论文获取常用默认值", "bulk_interval").set_value(-1)
    with pytest.raises(ValueError):
        mounted.callbacks["保存论文获取默认值"][0]()
    assert mounted.settings.path.read_bytes() == before


def test_research_defaults_are_saved_and_loaded_by_real_new_research_form(
    mounted, monkeypatch
):
    mounted.control("科研模型与预算默认值", "name").set_value("fixture-model")
    mounted.control("科研模型与预算默认值", "max_cost").set_value(0.75)
    next(
        element
        for element in mounted.section("科研模型与预算默认值")
        if getattr(element, "label", None)
        == "自然语言规划单独费用上限（按模型计费币种）"
    ).set_value(0.12)
    mounted.callbacks["保存科研默认参数"][0]()
    saved = mounted.settings.get("research")
    assert (
        saved["model"]["name"] == "fixture-model"
        and saved["budget"]["max_cost"] == 0.75
    )
    elements, page = new_research_form(mounted.settings, mounted.root, monkeypatch)
    assert (
        next(
            element
            for element in elements
            if getattr(element, "label", None) == PARAMETER_LABELS["name"]
        ).value
        == "fixture-model"
    )
    assert (
        next(
            element
            for element in elements
            if getattr(element, "label", None) == PARAMETER_LABELS["max_cost"]
        ).value
        == 0.75
    )
    assert (
        next(
            element
            for element in elements
            if getattr(element, "label", None)
            == "自然语言规划单独费用上限（按模型计费币种）"
        ).value
        == 0.12
    )
    assert all(
        not element.value
        for element in elements
        if isinstance(element, ui.checkbox) and "授权" in element.text
    )
    assert page.current_task is None


def new_research_form(settings, root, monkeypatch, task=None):
    class Page(ui_research.ResearchPages):
        def title(self, *_):
            pass

        def selection_dialog(self):
            pass

        def task_dialog(self):
            pass

    page = Page()
    page.current_task = task
    page.ctx = SimpleNamespace(
        library=SimpleNamespace(selection=lambda: ["paper1"], root=root),
        settings=settings,
        jobs=SimpleNamespace(list=lambda: []),
        research=SimpleNamespace(
            app=SimpleNamespace(
                check_document=lambda *a: SimpleNamespace(
                    identity={
                        "title": "合成材料",
                        "document_role": "ARTICLE",
                        "page_count": 1,
                        "identity_basis": "declared",
                    }
                )
            )
        ),
    )
    monkeypatch.setattr(ui, "timer", lambda *a, **k: None)
    before = set(ui.context.client.elements)
    page.research_page()
    return [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ], page


def test_loaded_plan_keeps_explicit_model_budget_and_never_inherits_authorization(
    mounted, monkeypatch
):
    mounted.settings.set(
        "research",
        research_defaults(
            {"model": {"name": "new-default"}, "budget": {"max_cost": 0.8}}
        ),
    )
    task = {
        "objective": "历史合成计划",
        "mode": "parsed",
        "type": "extract",
        "model": {**research_defaults()["model"], "name": "historical-model"},
        "budget": {**research_defaults()["budget"], "max_cost": 0.3},
        "fields": [{"id": "data", "description": "合成字段", "type": "string"}],
        "documents": [{"id": "paper1", "artifact": "synthetic.parsed.json"}],
    }
    original = deepcopy(task)
    elements, _ = new_research_form(mounted.settings, mounted.root, monkeypatch, task)
    assert (
        next(
            element
            for element in elements
            if getattr(element, "label", None) == PARAMETER_LABELS["name"]
        ).value
        == "historical-model"
    )
    assert (
        next(
            element
            for element in elements
            if getattr(element, "label", None) == PARAMETER_LABELS["max_cost"]
        ).value
        == 0.3
    )
    assert all(
        not element.value
        for element in elements
        if isinstance(element, ui.checkbox) and "授权" in element.text
    )
    assert task == original
