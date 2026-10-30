"""Paper totals and automatic interaction controls survive file postprocessing."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.ui_acquisition_progress import (
    AcquisitionProgressPanel,
    acquisition_count_summary,
    acquisition_progress,
    acquisition_stage_summary,
)


def job_fixture(delivered=3):
    requests = [{"doi": f"10.1000/phase-{index}"} for index in range(3)]
    return {
        "id": "fixture-phase",
        "kind": "acquisition",
        "label": "合成阶段测试",
        "status": "RUNNING",
        "stage": "解析 PDF",
        "task_phase": "postprocess",
        "parameters": {"requests": requests},
        "total": 26,
        "current_index": 8,
        "records": [
            *[
                {"request": request, "status": "VERIFIED", "si_status": "COMPLETED"}
                for request in requests[:delivered]
            ],
            *[{"item_id": f"parse-{index}", "status": "PARSED"} for index in range(8)],
        ],
        "current_item": "分类/SI/当前附件.pdf",
    }


def test_complete_download_stage_explains_remaining_file_work_without_inflated_papers():
    job = job_fixture()
    progress = acquisition_progress(job)
    assert progress["counts"]["total"] == progress["download_completed"] == 3
    assert progress["download_remaining"] == 0
    assert acquisition_count_summary(progress).endswith("共 3 篇")
    summary = acquisition_stage_summary(job, progress)
    assert "下载阶段已完成" in summary and "文件 8/26" in summary
    assert "整个任务将在后续处理结束后完成" in summary
    assert "26 篇" not in summary


def test_per_paper_postprocessing_does_not_claim_whole_batch_is_downloaded():
    job = job_fixture(delivered=1)
    summary = acquisition_stage_summary(job)
    assert "当前篇正在" in summary and "之后继续余下获取" in summary
    assert "尚有 2 篇未完成获取" in summary and "文件 8/26" in summary
    assert "下载阶段已完成" not in summary
    job.update(stage="翻译缺失标题", current_index=0, total=1)
    assert "标题 0/1" in acquisition_stage_summary(job)
    job.update(status="PARTIAL")
    assert acquisition_stage_summary(job) == ""


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_acquisition_progress as module

    job, controls, tables = job_fixture(), [], []
    job["parameters"]["library"] = str(tmp_path)
    manager = SimpleNamespace(
        list=lambda: [deepcopy(job)],
        get=lambda _: deepcopy(job),
        control=lambda *args: controls.append(args),
    )
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            jobs=manager,
            library=SimpleNamespace(root=tmp_path),
            settings=SettingsStore(tmp_path / "state"),
        ),
        task_dialog=lambda: None,
    )
    monkeypatch.setattr(
        ui,
        "timer",
        lambda *a, **k: SimpleNamespace(activate=lambda: None, deactivate=lambda: None),
    )
    monkeypatch.setattr(module, "guard", lambda callback: callback)
    original_table = module.rows_table

    def rows_table(rows, **kwargs):
        tables.append(deepcopy(rows))
        return original_table(rows, **kwargs)

    monkeypatch.setattr(module, "rows_table", rows_table)
    before = set(ui.context.client.elements)
    with ui.column():
        panel = AcquisitionProgressPanel(controller)

    def elements():
        return [
            value
            for key, value in ui.context.client.elements.items()
            if key not in before and not value.is_deleted
        ]

    return SimpleNamespace(
        job=job, panel=panel, controls=controls, tables=tables, elements=elements
    )


def test_inline_phase_refreshes_without_records_but_stable_ticks_do_not_rebuild_table(
    mounted,
):
    view = mounted
    assert len(view.tables) == 1 and len(view.tables[0]) == 3
    view.panel.refresh()
    assert len(view.tables) == 1
    view.job.update(updated_at="only-a-timestamp")
    view.panel.refresh()
    assert len(view.tables) == 1
    view.job.update(task_phase="acquisition", stage="acquisition")
    view.panel.refresh()
    assert len(view.tables) == 2
    assert not any(
        "下载阶段已完成" in getattr(element, "text", "") for element in view.elements()
    )


def test_inline_auto_recheck_and_legacy_boundary_use_shared_safe_controls(mounted):
    view = mounted
    view.job.update(
        status="INTERACTION_REQUIRED",
        task_phase="acquisition",
        interaction={
            "stage": "browser_wait",
            "auto_monitoring": True,
            "source": "合成来源",
        },
    )
    view.panel.refresh()
    assert any(
        "程序会自动复查并继续" in getattr(element, "text", "")
        for element in view.elements()
    )
    button = next(
        element
        for element in view.elements()
        if getattr(element, "text", "") == "立即重新检查"
    )
    next(
        event.handler
        for event in button._event_listeners.values()
        if event.type == "click"
    )(None)
    assert view.controls == [(view.job["id"], "continue")]
    view.job.update(status="RUNNING", interaction={"stage": "paper_boundary"})
    view.panel.refresh()
    button = next(
        element
        for element in view.elements()
        if getattr(element, "text", "") == "跳过下一篇论文"
    )
    assert button.enabled
    next(
        event.handler
        for event in button._event_listeners.values()
        if event.type == "click"
    )(None)
    assert view.controls[-1] == (view.job["id"], "skip")


def test_task_center_shares_paper_total_and_refreshes_snapshot_on_phase_change(
    monkeypatch,
):
    pytest.importorskip("nicegui")
    from test_ui_interaction_monitoring import mount

    job = job_fixture()
    view = mount(job, monkeypatch)
    assert any("共 3 篇" in getattr(element, "text", "") for element in view.elements())
    assert any(
        "文件 8/26" in getattr(element, "text", "") for element in view.elements()
    )
    assert not any(
        "已交付 11 项" in getattr(element, "text", "") for element in view.elements()
    )
    assert len(view.snapshots) == 1
    stable_elements = {element.id for element in view.elements()}
    view.tick()
    assert len(view.snapshots) == 1
    assert {element.id for element in view.elements()} == stable_elements
    job.update(task_phase="acquisition", stage="acquisition")
    view.tick()
    assert len(view.snapshots) == 2
