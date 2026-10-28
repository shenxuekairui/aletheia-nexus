"""Task controls name and consume only the worker stage visible to the user."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.ui_tasks import continue_label, skip_control


@pytest.mark.parametrize("kind", ["acquisition", "acquire"])
def test_skip_does_not_pass_from_acquisition_into_parse_or_translation(kind):
    row = {"kind": kind, "status": "RUNNING"}
    assert skip_control(row) == ("跳过下一篇论文", True)
    row["task_phase"] = "postprocess"
    assert skip_control(row) == ("此阶段不支持跳过", False)


def test_interaction_at_paper_boundary_continues_later_papers_not_verification():
    job = {
        "kind": "acquisition",
        "status": "INTERACTION_REQUIRED",
        "interaction": {
            "stage": "paper_boundary",
            "resume_instruction": "本篇未成功；继续仅调度下一篇。",
        },
    }
    assert continue_label(job) == "继续后续论文"
    assert not skip_control(job)[1]
    job["interaction"]["stage"] = "browser_wait"
    assert continue_label(job) == "验证后继续"
    assert skip_control(job) == ("跳过当前论文", True)


@pytest.mark.parametrize(
    "kind,label",
    [
        ("parse", "跳过下一份文件"),
        ("translation", "跳过下一批标题"),
        ("import", "跳过下一份文件"),
    ],
)
def test_supported_work_stages_keep_specific_skip_units(kind, label):
    assert skip_control({"kind": kind, "status": "RUNNING"}) == (label, True)
    assert not skip_control({"kind": kind, "status": "CANCEL_REQUESTED"})[1]


def render_job(job, monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_tasks

    calls, notices = [], []
    manager = SimpleNamespace(
        list=lambda: [deepcopy(job)],
        get=lambda _: deepcopy(job),
        control=lambda *args: calls.append(args),
    )
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            jobs=manager,
            library=SimpleNamespace(operations=lambda: []),
            research=SimpleNamespace(history=lambda: []),
        ),
        output_links=lambda result: None,
    )
    monkeypatch.setattr(ui_tasks, "guard", lambda callback: callback)
    monkeypatch.setattr(
        ui, "timer", lambda *_args, **_kwargs: SimpleNamespace(active=True)
    )
    monkeypatch.setattr(ui, "notify", lambda text, **kwargs: notices.append(text))
    before = set(ui.context.client.elements)
    ui_tasks.render_task_dialog(controller)
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    card = next(element for element in elements if "an-job-card" in element.classes)
    card.set_value(True)
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    return elements, calls, notices


@pytest.mark.parametrize("boundary", [False, True])
def test_real_task_dialog_has_truthful_continue_and_skip_controls(
    monkeypatch, boundary
):
    job = {
        "id": "test",
        "label": "获取测试",
        "kind": "acquisition",
        "status": "INTERACTION_REQUIRED",
        "total": 2,
        "current_index": 1,
        "records": [],
        "interaction": {
            "stage": "paper_boundary" if boundary else "browser_wait",
            "resume_instruction": "本篇已结束，继续后续论文。",
        },
    }
    elements, calls, _ = render_job(job, monkeypatch)
    text = "继续后续论文" if boundary else "验证后继续"
    button = next(
        element for element in elements if getattr(element, "text", "") == text
    )
    assert button.enabled
    if boundary:
        assert any(
            getattr(element, "text", "") == job["interaction"]["resume_instruction"]
            for element in elements
        )
        disabled = next(
            element
            for element in elements
            if getattr(element, "text", "") == "此阶段不支持跳过"
        )
        assert not disabled.enabled
    callback = next(
        listener.handler
        for listener in button._event_listeners.values()
        if listener.type == "click"
    )
    callback(None)
    assert calls == [("test", "continue")]


def test_old_skip_button_rechecks_phase_before_sending_control(monkeypatch):
    job = {
        "id": "test",
        "label": "获取测试",
        "kind": "acquisition",
        "status": "RUNNING",
        "total": 2,
        "current_index": 1,
        "records": [],
    }
    elements, calls, notices = render_job(job, monkeypatch)
    button = next(
        element
        for element in elements
        if getattr(element, "text", "") == "跳过下一篇论文"
    )
    assert button.enabled
    callback = next(
        listener.handler
        for listener in button._event_listeners.values()
        if listener.type == "click"
    )
    job["task_phase"] = "postprocess"
    callback(None)
    assert calls == [] and "不支持跳过" in notices[-1]
