"""The input page reports real paper progress across postprocessing and reloads."""

from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.ui_acquisition_progress import (
    AcquisitionProgressPanel,
    acquisition_progress,
)


def request(suffix):
    return {"doi": "10.9999/" + suffix, "title": None}


def test_paper_counts_ignore_later_parse_and_translation_file_records():
    first, second, third = [request(s) for s in ("a", "b", "c")]
    delivered = {"request": first, "status": "VERIFIED", "si_status": "FAILED"}
    progress = acquisition_progress(
        {
            "status": "RUNNING",
            "parameters": {"requests": [first, second, third]},
            "total": 11,
            "current_index": 8,
            "records": [delivered, {"status": "PARSED", "item_id": "pdf-si"}],
            "current_item": {"status": "TRANSLATED"},
            "result": {
                "items": [delivered, {"request": second, "status": "EXHAUSTED"}]
            },
        }
    )
    assert progress["counts"] == {
        "total": 3,
        "success": 1,
        "failed": 1,
        "interaction": 0,
        "partial": 0,
        "skipped": 0,
        "pending": 1,
    }
    assert progress["rows"][0]["si_status"] == "FAILED"


def test_current_main_success_is_visible_while_si_is_being_acquired():
    paper = request("a")
    progress = acquisition_progress(
        {
            "status": "RUNNING",
            "parameters": {"requests": [paper]},
            "current": paper,
            "current_item": {
                "request": paper,
                "status": "VERIFIED",
                "si_status": "RUNNING",
            },
        }
    )
    assert progress["counts"]["success"] == 1
    assert progress["rows"][0]["si_status"] == "RUNNING"
    assert progress["attachments"]["running"] == 1


def test_current_interaction_and_unstarted_papers_are_distinct():
    first, second = request("a"), request("b")
    progress = acquisition_progress(
        {
            "status": "INTERACTION_REQUIRED",
            "parameters": {"requests": [first, second]},
            "current": first,
        }
    )
    assert progress["counts"]["interaction"] == 1
    assert progress["counts"]["pending"] == 1
    assert progress["current"] == first["doi"]


def test_si_needing_human_action_does_not_replace_verified_main_status():
    paper = request("a")
    progress = acquisition_progress(
        {
            "status": "PARTIAL",
            "parameters": {"requests": [paper]},
            "result": {
                "items": [
                    {
                        "request": paper,
                        "status": "VERIFIED",
                        "si_status": "INTERACTION_REQUIRED",
                    }
                ]
            },
        }
    )
    assert progress["counts"]["success"] == 1
    assert progress["counts"]["failed"] == progress["counts"]["interaction"] == 0
    assert progress["attachments"]["interaction"] == 1


def test_same_title_with_different_identity_constraints_is_not_collapsed():
    papers = [
        {"title": "Same scientific title", "year": 2025},
        {"title": "Same scientific title", "year": 2026},
    ]
    progress = acquisition_progress(
        {
            "status": "PARTIAL",
            "parameters": {"requests": papers},
            "result": {
                "items": [
                    {"request": papers[0], "status": "VERIFIED"},
                    {"request": papers[1], "status": "EXHAUSTED"},
                ]
            },
        }
    )
    assert progress["counts"]["success"] == progress["counts"]["failed"] == 1


def test_postprocessing_displays_real_file_instead_of_stale_last_paper():
    paper = request("a")
    progress = acquisition_progress(
        {
            "status": "RUNNING",
            "task_phase": "postprocess",
            "parameters": {"requests": [paper]},
            "current": paper,
            "current_item": "category/SI/paper__SI-01.pdf",
        }
    )
    assert progress["current"] == "category/SI/paper__SI-01.pdf"


def test_panel_reopens_saved_receipt_without_submitting_and_scopes_by_library(
    tmp_path,
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    root, workspace = tmp_path / "library", tmp_path / "workspace"
    settings = SettingsStore(workspace)
    manager = TaskManager(workspace)
    paper = request("a")
    try:
        job = manager.submit(
            "acquisition",
            "真实持久化测试",
            [paper["doi"]],
            lambda _: {
                "status": "COMPLETED",
                "items": [{"request": paper, "status": "VERIFIED"}],
            },
            parameters={"library": str(root), "requests": [paper]},
        )
        manager._futures[job["id"]].result(timeout=3)
        settings.set("acquisition_live_task", {"id": job["id"], "library": str(root)})
    finally:
        manager.close(wait=True)
    reopened = TaskManager(workspace)
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            jobs=reopened,
            library=SimpleNamespace(root=root),
            settings=SettingsStore(workspace),
        ),
        task_dialog=lambda: None,
    )
    try:
        with ui.column():
            panel = AcquisitionProgressPanel(controller)
        assert panel.job_id == job["id"]
        assert len(reopened.list()) == 1
        assert reopened.get(panel.job_id)["status"] == "COMPLETED"
        assert not panel.timer.active
        controller.ctx.library.root = tmp_path / "other-library"
        with ui.column():
            other = AcquisitionProgressPanel(controller)
        assert other.job_id is None
        assert not other.choices
    finally:
        reopened.close(wait=True)


@pytest.mark.parametrize("action", ["skip", "continue"])
def test_stale_inline_control_does_not_affect_a_new_phase(
    tmp_path, monkeypatch, action
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_acquisition_progress as module

    job = {
        "id": "stale-control",
        "kind": "acquisition",
        "label": "实时任务",
        "status": "RUNNING" if action == "skip" else "INTERACTION_REQUIRED",
        "parameters": {"library": str(tmp_path)},
    }
    controls, clicked = {}, []
    original_button = ui.button

    def capture(label, **kwargs):
        controls[label] = kwargs.get("on_click")
        return original_button(label, **kwargs)

    monkeypatch.setattr(ui, "button", capture)
    monkeypatch.setattr(module, "guard", lambda callback: callback)
    monkeypatch.setattr(
        ui, "timer", lambda *a, **k: SimpleNamespace(activate=lambda: None)
    )
    manager = SimpleNamespace(
        list=lambda: [job],
        get=lambda _: job,
        control=lambda *args: clicked.append(args),
    )
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            jobs=manager,
            library=SimpleNamespace(root=tmp_path),
            settings=SettingsStore(tmp_path / "workspace"),
        ),
        task_dialog=lambda: None,
    )
    with ui.column():
        AcquisitionProgressPanel(controller)
    job.update(status="RUNNING", task_phase="postprocess")
    label = "跳过下一篇" if action == "skip" else "验证后继续"
    with pytest.raises(ValueError, match="阶段已变化|不再等待"):
        controls[label]()
    assert clicked == []
