"""Real acquisition widgets persist the reviewed automatic-wait preference."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui")

from nicegui import ui
from nicegui.elements.expansion import Expansion

from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.ui_acquisition import AcquisitionPage

AUTO = "人工验证完成后自动检测并继续"
POLICY = "需要人工操作时"
TIMEOUT = "交互等待（秒；0表示不限时）"
PROFILE = "浏览器登录会话"
SAVE_DEFAULTS = "保存为获取默认设置"
SAVE_PRESET = "保存当前获取预设"


@pytest.fixture
def mount(tmp_path, monkeypatch):
    from aletheia_nexus.workbench import defaults, ui_acquisition

    active, views = [None], []
    native_button = ui.button

    def button(text="", **kwargs):
        value = native_button(text, **kwargs)
        if active[0] is not None:
            active[0].setdefault(text, []).append(kwargs.get("on_click"))
        return value

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui, "timer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui_acquisition, "guard", lambda callback: callback)
    monkeypatch.setattr(
        defaults,
        "browser_profile_choices",
        lambda config: {
            "options": ["test-session", "other-session"],
            "current": config["profile_name"],
            "message": "工程会话夹具；未连接浏览器",
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        defaults,
        "browser_readiness",
        lambda *_: {"message": "工程配置夹具；未启动浏览器"},
    )
    settings = SettingsStore(tmp_path / "settings")
    settings.set(
        "acquisition",
        {
            "public_only": False,
            "browser_enabled": True,
            "interaction_policy": "wait",
            "auto_resume_interaction": True,
            "interaction_timeout": 17.5,
            "timeout": 11,
            "max_route_attempts": 7,
            "browser": {"profile_name": "test-session", "navigation_timeout": 23},
        },
    )
    library = LibraryService(tmp_path / "library")
    service = AcquisitionService(library.root)
    monkeypatch.setattr(
        service,
        "run",
        lambda *_args, **_kwargs: pytest.fail("Settings tests must not acquire papers"),
    )

    class Page(AcquisitionPage):
        def title(self, *_):
            pass

        def import_dialog(self):
            pytest.fail("Settings tests must not import materials")

        def task_dialog(self):
            pytest.fail("Settings tests must not open task history")

    def render():
        previous = set(ui.context.client.elements)
        callbacks = {}
        active[0] = callbacks
        controller = Page()
        controller.ctx = SimpleNamespace(
            settings=SettingsStore(settings.path.parent),
            library=library,
            acquisition=service,
            jobs=SimpleNamespace(list=lambda: []),
        )
        try:
            controller.acquisition_page()
        finally:
            active[0] = None
        elements = [
            element
            for key, element in ui.context.client.elements.items()
            if key not in previous
        ]
        controls = {}
        for element in elements:
            label = element._props.get("label") or getattr(element, "text", None)
            if label:
                controls.setdefault(label, []).append(element)

        def control(label):
            assert len(controls[label]) == 1, f"Expected one control: {label}"
            return controls[label][0]

        def click(label):
            assert len(callbacks[label]) == 1
            return callbacks[label][0]()

        view = SimpleNamespace(
            controller=controller,
            settings=controller.ctx.settings,
            controls=controls,
            elements=elements,
            control=control,
            click=click,
        )
        views.append(view)
        return view

    try:
        yield render
    finally:
        for view in reversed(views):
            for element in reversed(view.elements):
                if not element.is_deleted:
                    element.delete()


def test_login_wait_controls_are_in_the_common_area_not_expansions(mount):
    view = mount()
    for label in (AUTO, POLICY, TIMEOUT, PROFILE):
        control = view.control(label)
        parent_slot = control.parent_slot
        while parent_slot is not None:
            parent = parent_slot.parent
            assert not isinstance(parent, Expansion), (
                f"{label} hidden in advanced settings"
            )
            parent_slot = parent.parent_slot
    assert view.control(AUTO).value is True
    assert view.control(AUTO).enabled
    assert view.control(TIMEOUT).value == 17.5
    assert view.control(PROFILE).value == "test-session"


def test_disabled_switch_generates_false_and_reopened_defaults_keep_false(mount):
    view = mount()
    view.control(AUTO).set_value(False)
    view.control(TIMEOUT).set_value(0)
    view.control(PROFILE).set_value("other-session")
    view.click(SAVE_DEFAULTS)
    options = view.settings.get("acquisition")
    assert options["auto_resume_interaction"] is False
    assert options["interaction_policy"] == "wait"
    assert options["interaction_timeout"] == 0
    assert options["browser"]["profile_name"] == "other-session"
    reopened = mount()
    assert reopened.control(AUTO).value is False
    assert reopened.control(AUTO).enabled
    assert reopened.control(TIMEOUT).value == 0
    assert reopened.control(PROFILE).value == "other-session"


def test_named_preset_load_restores_false_into_actual_controls(mount):
    view = mount()
    view.control(AUTO).set_value(False)
    view.control(TIMEOUT).set_value(0)
    view.control("保存为预设名称").set_value("手动继续夹具")
    view.click(SAVE_PRESET)
    saved = view.settings.load_preset("acquisition", "手动继续夹具")
    assert saved["parameters"]["auto_resume_interaction"] is False
    view.control(AUTO).set_value(True)
    view.control(TIMEOUT).set_value(91)
    view.control("载入预设").set_value("手动继续夹具")
    view.click("载入并显示")
    assert view.control(AUTO).value is False
    assert view.control(AUTO).enabled
    assert view.control(TIMEOUT).value == 0
    assert saved == view.settings.load_preset("acquisition", "手动继续夹具")
    reopened = mount()
    assert (
        reopened.control(AUTO).value is True
    )  # Presets do not change global defaults.
    reopened.control("载入预设").set_value("手动继续夹具")
    reopened.click("载入并显示")
    assert reopened.control(AUTO).value is False
    assert reopened.control(TIMEOUT).value == 0


@pytest.mark.parametrize("policy", ["pause", "skip"])
def test_pause_and_skip_disable_auto_control_without_overwriting_other_values(
    mount, policy
):
    view = mount()
    view.control(AUTO).set_value(False)
    view.click(SAVE_DEFAULTS)
    before = deepcopy(view.settings.get("acquisition"))
    view.control(POLICY).set_value(policy)
    assert not view.control(AUTO).enabled
    assert view.control(AUTO).value is False
    view.click(SAVE_DEFAULTS)
    after = view.settings.get("acquisition")
    assert after["interaction_policy"] == policy
    assert {k: v for k, v in after.items() if k != "interaction_policy"} == {
        k: v for k, v in before.items() if k != "interaction_policy"
    }
    view.control(POLICY).set_value("wait")
    assert view.control(AUTO).enabled and view.control(AUTO).value is False


def test_private_core_callbacks_have_no_controls_and_are_not_persisted(mount):
    view = mount()
    private_fields = ("interaction_callback", "interaction_poll_callback")
    assert not any(
        field in label for label in view.controls for field in private_fields
    )
    view.click(SAVE_DEFAULTS)
    view.control("保存为预设名称").set_value("等待设置夹具")
    view.click(SAVE_PRESET)
    saved = view.settings.path.read_text(encoding="utf-8")
    for field in private_fields:
        assert field not in saved
        assert field not in view.settings.get("acquisition")["browser"]


def test_visible_translation_call_cap_uses_typed_reader_and_reopens(mount):
    view = mount()
    cap = view.control("本批标题翻译调用上限（含重试）")
    cap.set_value(35.0)  # Browser number values may arrive as integral floats.
    view.click(SAVE_DEFAULTS)
    saved = view.settings.get("acquisition_workflow")
    assert saved["title_translation"]["options"]["max_calls"] == 35
    assert type(saved["title_translation"]["options"]["max_calls"]) is int
    reopened = mount()
    assert reopened.control("本批标题翻译调用上限（含重试）").value == 35
    reopened.control("本批标题翻译调用上限（含重试）").set_value(3.5)
    with pytest.raises(ValueError):
        reopened.click(SAVE_DEFAULTS)
    assert view.settings.get("acquisition_workflow") == saved
