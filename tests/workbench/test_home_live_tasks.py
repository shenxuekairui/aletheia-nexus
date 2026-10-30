"""Home task status refreshes independently of expensive library/source work."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.ui_home import GUIDE, HomePages, home_job_summary

ui = pytest.importorskip("nicegui.ui")


def job(status="RUNNING"):
    return {
        "id": "local-fixture",
        "label": "合成任务",
        "stage": "PDF解析",
        "status": status,
        "current_index": 1,
        "total": 25,
    }


def test_summary_tracks_display_state_but_not_heavy_records_or_unchanged_progress():
    initial = job()
    later = {
        **initial,
        "current_index": 24,
        "records": [{"raw": "retained by task manager"}],
    }
    assert home_job_summary([initial]) == home_job_summary([later])
    assert home_job_summary([job("PARTIAL")])["active_count"] == 0


def test_completed_job_updates_home_without_scanning_library_or_rebuilding_unchanged_ui(
    monkeypatch,
):
    from nicegui import run

    current = [job()]
    listed, rendered = [], []

    def jobs():
        listed.append(True)
        return deepcopy(current)

    async def io(function):
        return function()

    monkeypatch.setattr(run, "io_bound", io)

    class Page(HomePages):
        ctx = SimpleNamespace(
            jobs=SimpleNamespace(list=jobs),
            library=SimpleNamespace(
                scan=lambda: pytest.fail("Task timer must not scan PDFs")
            ),
            research=SimpleNamespace(
                results=lambda: pytest.fail("Task timer must not reload results")
            ),
        )

        def home_recent_jobs(self, rows):
            rendered.append(deepcopy(rows))
            super().home_recent_jobs(rows)

    page = Page()
    label = ui.label("1")
    area = ui.column()
    with area:
        page.home_recent_jobs(current)
    timer = page.watch_home_tasks(current, active_label=label, recent_area=area)
    old_children = list(area.default_slot.children)
    asyncio.run(page._refresh_home_tasks())
    assert area.default_slot.children == old_children and len(rendered) == 1
    current[0]["status"] = "PARTIAL"
    asyncio.run(page._refresh_home_tasks())
    assert label.text == "0" and len(rendered) == 2
    assert rendered[-1][0]["status"] == "PARTIAL"
    assert any(
        getattr(element, "text", "") == "任务已结束，历史已保存"
        and not element.is_deleted
        for element in ui.context.client.elements.values()
    )
    updated_children = list(area.default_slot.children)
    asyncio.run(page._refresh_home_tasks())
    assert area.default_slot.children == updated_children and len(rendered) == 2
    assert len(listed) == 3
    label.delete()
    area.delete()
    asyncio.run(page._refresh_home_tasks())
    assert not timer.active and len(listed) == 3


def test_first_use_task_button_hides_after_terminal_status_without_rebuilding_home(
    monkeypatch,
):
    from nicegui import run

    current = [job()]

    async def io(function):
        return function()

    monkeypatch.setattr(run, "io_bound", io)
    page = HomePages()
    page.ctx = SimpleNamespace(jobs=SimpleNamespace(list=lambda: deepcopy(current)))
    button = ui.button("查看正在处理的 1 个任务")
    timer = page.watch_home_tasks(current, empty_button=button)
    current[0]["status"] = "COMPLETED"
    asyncio.run(page._refresh_home_tasks())
    assert button.text == "查看正在处理的 0 个任务" and not button.visible
    timer.deactivate()


def test_guide_matches_optional_auto_resume_shared_postprocess_and_private_credentials():
    all_text = " ".join(
        paragraph for _, _, paragraphs in GUIDE for paragraph in paragraphs
    )
    for phrase in (
        "人工验证完成后自动检测并继续",
        "仅在等待模式",
        "显式暂停",
        "同正文指纹",
        "按来源逐条查看",
        "本批共享",
        "调用次数",
        "只选这篇",
        "Windows",
        "用户凭据管理器",
        "SI 目前不会实时等待",
    ):
        assert phrase in all_text
    assert "验证后继续才会接着当前尝试" not in all_text
    assert "设置中心只显示是否可用" not in all_text
