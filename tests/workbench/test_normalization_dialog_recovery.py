"""A saved failed input draft stays inspectable without another paid request."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.settings import SettingsStore


def test_saved_running_then_failed_preview_restores_controls_and_shows_diagnostic(
    tmp_path, monkeypatch
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_common
    from aletheia_nexus.workbench.ui_input_normalization import normalization_dialog

    monkeypatch.setattr(ui_common, "guard", lambda callback: callback)
    buttons, timers = {}, []
    button = ui.button

    def capture(label, **kwargs):
        element = button(label, **kwargs)
        buttons[label] = (element, kwargs.get("on_click"))
        return element

    class Timer:
        def __init__(self, interval, callback, active=False):
            self.callback, self.active = callback, active
            timers.append(self)

        def activate(self):
            self.active = True

        def deactivate(self):
            self.active = False

    monkeypatch.setattr(ui, "button", capture)
    monkeypatch.setattr(ui, "timer", Timer)
    settings = SettingsStore(tmp_path)
    settings.set("input_normalization_last_job", "saved")
    job = {
        "id": "saved",
        "kind": "input_normalization",
        "status": "RUNNING",
        "updated_at": "first",
        "parameters": {},
    }
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            settings=settings, jobs=SimpleNamespace(get=lambda _: deepcopy(job))
        ),
        submit=lambda *_: pytest.fail(
            "Inspecting saved history must never submit work"
        ),
    )

    async def snapshot():
        return {"text": "10.1000/fixture"}

    with ui.column() as parent:
        normalization_dialog(
            controller,
            snapshot,
            lambda *_: pytest.fail("Failed draft cannot be adopted"),
        )
    asyncio.run(buttons["查看上次整理（不再调用模型）"][1]())
    assert timers[0].active
    assert not buttons["开始 AI 整理"][0].enabled
    job.update(
        status="FAILED",
        updated_at="second",
        result={
            "status": "FAILED",
            "preview": None,
            "canonical": None,
            "calls": [],
            "diagnostics": [
                {"code": "mock_validation", "message": "原文出处校验失败，请核对输入"}
            ],
        },
    )
    asyncio.run(timers[0].callback())
    assert not timers[0].active
    assert buttons["开始 AI 整理"][0].enabled
    assert not buttons["确认采用并预览"][0].visible
    labels = [
        getattr(element, "text", "") for element in parent.client.elements.values()
    ]
    assert any("原文出处校验失败" in text for text in labels)
