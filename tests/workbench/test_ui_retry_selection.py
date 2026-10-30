"""Actual retry widgets select an explicit paper scope before safe submission."""

import asyncio
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from test_acquisition_recovery import original_job, verified
from test_acquisition_recovery import service as service_fixture

from aletheia_nexus.core.paper_request import PaperRequest
from aletheia_nexus.workbench.acquisition import normalize_request

service = service_fixture


@pytest.fixture
def retry_view(service, monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import run, ui

    from aletheia_nexus.workbench import defaults
    from aletheia_nexus.workbench import ui as ui_module
    from aletheia_nexus.workbench.ui import WorkbenchUI

    papers = [
        PaperRequest(doi="10.1000/" + name)
        for name in ("failed-a", "si", "failed-b", "pending")
    ]
    _, record = verified(service, papers[1])
    job = original_job(
        service,
        papers,
        {papers[1].batch_key: record},
        [
            {"request": asdict(papers[0]), "status": "EXHAUSTED"},
            {"request": asdict(papers[1]), "status": "VERIFIED", "si_status": "FAILED"},
            {"request": asdict(papers[2]), "status": "BROWSER_UNAVAILABLE"},
        ],
    )
    callbacks, submissions, workers = {}, [], []
    page = WorkbenchUI.__new__(WorkbenchUI)
    page.ctx = SimpleNamespace(
        acquisition=service,
        library=service.library,
        settings=SimpleNamespace(get=lambda *a: {}),
        jobs=SimpleNamespace(get=lambda _: deepcopy(job)),
    )
    page.title_translation_controls = lambda *_: (
        lambda: {"enabled": False, "consent": False}
    )
    page.acquisition_worker = lambda *a, **k: workers.append((a, k)) or (lambda _: {})
    page.submit = lambda *a, **k: submissions.append((a, k))
    original_button = ui.button

    def button(text, **kwargs):
        result = original_button(text, **kwargs)
        callbacks[text] = kwargs.get("on_click"), result
        return result

    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui_module, "guard", lambda callback: callback)
    monkeypatch.setattr(run, "io_bound", immediate)
    monkeypatch.setattr(
        defaults,
        "browser_profile_choices",
        lambda _: {
            "options": ["default"],
            "current": "default",
            "message": "合成会话",
            "warnings": [],
        },
    )
    before = set(ui.context.client.elements)
    container = ui.column()

    async def mount():
        with container:
            await page.recover_acquisition_dialog(job)

    asyncio.run(mount())

    def elements():
        return [
            value
            for key, value in ui.context.client.elements.items()
            if key not in before and not value.is_deleted
        ]

    table = next(value for value in elements() if isinstance(value, ui.table))

    def choose_one(paper):
        listener = next(
            event
            for event in table._event_listeners.values()
            if event.type == "chooseOne"
        )
        listener.handler(SimpleNamespace(args=paper.batch_key))

    return SimpleNamespace(
        page=page,
        job=job,
        papers=papers,
        callbacks=callbacks,
        table=table,
        elements=elements,
        submissions=submissions,
        workers=workers,
        choose_one=choose_one,
        container=container,
    )


def test_shortcuts_and_row_action_only_select_and_display_exact_count(retry_view):
    view = retry_view
    assert len(view.table.selected) == 4
    start = view.callbacks["开始重试所选论文 / 补 SI"][1]
    view.callbacks["取消全选"][0]()
    assert not view.table.selected and not start.enabled
    view.callbacks["仅正文失败"][0]()
    assert {row["id"] for row in view.table.selected} == {
        view.papers[0].batch_key,
        view.papers[2].batch_key,
    }
    view.callbacks["仅补 SI"][0]()
    assert [row["id"] for row in view.table.selected] == [view.papers[1].batch_key]
    view.callbacks["选择全部可重试项"][0]()
    view.choose_one(view.papers[2])
    assert [row["id"] for row in view.table.selected] == [view.papers[2].batch_key]
    assert any(
        "本次将重试 1 篇" in getattr(element, "text", "") for element in view.elements()
    )
    assert start.enabled and not view.submissions and not view.workers
    assert "只选这篇" in view.table.slots["body-cell-choose_one"].template


def test_only_this_verified_main_submits_one_si_retry_and_keeps_name(retry_view):
    view = retry_view
    view.choose_one(view.papers[1])

    async def exercise():
        with view.container:
            await view.callbacks["开始重试所选论文 / 补 SI"][0]()
            await view.callbacks["开始重试所选论文 / 补 SI"][0]()

    asyncio.run(exercise())
    assert len(view.submissions) == len(view.workers) == 1
    args, kwargs = view.submissions[0]
    assert args[4]["requests"] == [asdict(view.papers[1])]
    assert args[4]["recovery"]["selected_ids"] == [view.papers[1].batch_key]
    assert args[4]["postprocess"]["preserve_existing_names_for"] == [
        normalize_request(asdict(view.papers[1])).key
    ]
    assert args[4]["options"]["resume"] is True
    assert view.workers[0][0][0] == [asdict(view.papers[1])]
    assert kwargs["resume_of"] == view.job["id"]


def test_active_original_cannot_be_retried_after_stale_preview(retry_view):
    view = retry_view
    view.choose_one(view.papers[0])
    view.job.update(status="RUNNING", task_phase="postprocess")

    async def exercise():
        with view.container:
            await view.callbacks["开始重试所选论文 / 补 SI"][0]()

    with pytest.raises(ValueError, match="原获取任务尚未结束"):
        asyncio.run(exercise())
    assert not view.submissions and not view.workers
    assert view.callbacks["开始重试所选论文 / 补 SI"][1].enabled


def test_async_revalidation_keeps_clicked_scope_and_rejects_a_second_submit(
    retry_view, monkeypatch
):
    from nicegui import run

    from aletheia_nexus.workbench.acquisition_recovery import recovery_preview

    view = retry_view
    view.choose_one(view.papers[0])

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(function, *args, **kwargs):
            if function is recovery_preview:
                entered.set()
                await release.wait()
            return function(*args, **kwargs)

        monkeypatch.setattr(run, "io_bound", delayed)
        with view.container:
            first = asyncio.create_task(view.callbacks["开始重试所选论文 / 补 SI"][0]())
            await entered.wait()
            view.choose_one(view.papers[2])
            await view.callbacks["开始重试所选论文 / 补 SI"][0]()
            release.set()
            await first

    asyncio.run(exercise())
    assert len(view.submissions) == 1
    assert view.submissions[0][0][4]["requests"] == [asdict(view.papers[0])]
