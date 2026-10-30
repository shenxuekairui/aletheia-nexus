"""Automatic monitoring is visible without treating a recheck as success."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.ui_tasks import continue_label, skip_control


def test_legacy_running_boundary_does_not_block_skip_or_claim_an_active_boundary():
    job = {
        "kind": "acquisition",
        "status": "RUNNING",
        "interaction": {"stage": "paper_boundary"},
    }
    assert skip_control(job) == ("跳过下一篇论文", True)
    assert continue_label(job) == "验证后继续"
    job["status"] = "INTERACTION_REQUIRED"
    assert not skip_control(job)[1]
    assert continue_label(job) == "继续后续论文"


def mount(job, monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_tasks

    ticks, controls, snapshots = [], [], []

    def timer(_interval, callback, **_):
        ticks.append(callback)
        return SimpleNamespace(active=True)

    def json_view(value, *, label):
        if label == "完整逐项诊断、调用账本与恢复记录":
            snapshots.append(deepcopy(value))

    monkeypatch.setattr(ui, "timer", timer)
    monkeypatch.setattr(ui_tasks, "guard", lambda callback: callback)
    monkeypatch.setattr(ui_tasks, "json_view", json_view)
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            jobs=SimpleNamespace(
                list=lambda: [deepcopy(job)],
                get=lambda _: deepcopy(job),
                control=lambda *args: controls.append(args),
            ),
            library=SimpleNamespace(operations=lambda: []),
            research=SimpleNamespace(history=lambda: []),
        ),
        output_links=lambda _: None,
    )
    before = set(ui.context.client.elements)
    ui_tasks.render_task_dialog(controller)

    def elements():
        return [
            element
            for key, element in ui.context.client.elements.items()
            if key not in before and not element.is_deleted
        ]

    next(
        element for element in elements() if "an-job-card" in element.classes
    ).set_value(True)
    return SimpleNamespace(
        tick=ticks[0], elements=elements, controls=controls, snapshots=snapshots
    )


def monitored_job():
    return {
        "id": "fixture",
        "kind": "acquisition",
        "label": "合成交互监测",
        "status": "INTERACTION_REQUIRED",
        "total": 2,
        "current_index": 0,
        "records": [],
        "interaction": {
            "auto_monitoring": True,
            "stage": "browser_wait",
            "source": "fixture-source",
            "paper": {"title": "合成论文"},
        },
    }


def test_real_widgets_offer_recheck_and_explain_that_it_is_not_verification(
    monkeypatch,
):
    job = monitored_job()
    view = mount(job, monkeypatch)
    elements = view.elements()
    assert any(
        "程序会自动复查并继续" in getattr(element, "text", "") for element in elements
    )
    assert any(
        "不代表验证通过或论文已经获取" in getattr(element, "text", "")
        for element in elements
    )
    button = next(
        element
        for element in elements
        if getattr(element, "text", "") == "立即重新检查"
    )
    assert button.enabled
    handler = next(
        event.handler
        for event in button._event_listeners.values()
        if event.type == "click"
    )
    handler(None)
    assert view.controls == [("fixture", "continue")]
    assert job["status"] == "INTERACTION_REQUIRED"


def test_snapshot_refreshes_once_on_status_or_active_source_change_without_new_records(
    monkeypatch,
):
    job = monitored_job()
    view = mount(job, monkeypatch)
    assert len(view.snapshots) == 1
    view.tick()
    assert len(view.snapshots) == 1  # Do not redraw the whole table every timer tick.
    job["interaction"]["source"] = "new-fixture-source"
    view.tick()
    assert len(view.snapshots) == 2
    assert view.snapshots[-1]["interaction"]["source"] == "new-fixture-source"
    view.tick()
    assert len(view.snapshots) == 2
    job.update(
        status="RUNNING", interaction=None, interaction_resolution="core_resolved"
    )
    view.tick()
    assert len(view.snapshots) == 3 and view.snapshots[-1]["status"] == "RUNNING"
    assert not any(
        "等待人工处理" in getattr(element, "text", "") for element in view.elements()
    )
    view.tick()
    assert len(view.snapshots) == 3


def test_manual_wait_and_paper_boundary_keep_explicit_human_decision_labels():
    job = monitored_job()
    job["interaction"]["auto_monitoring"] = False
    assert continue_label(job) == "验证后继续"
    job["interaction"].update(stage="paper_boundary", auto_monitoring=True)
    assert continue_label(job) == "继续后续论文"
