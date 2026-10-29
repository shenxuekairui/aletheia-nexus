"""Clearing progress containers cannot delete recovery UI or lose an accepted job."""

import asyncio
import gc
from copy import deepcopy
from types import MethodType, SimpleNamespace

import pytest
from test_ui_retry_selection import retry_view as retry_fixture
from test_ui_retry_selection import service as service_fixture

pytest.importorskip("nicegui")

from nicegui import ui

from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.ui import WorkbenchUI
from aletheia_nexus.workbench.ui_common import guard

retry_view = retry_fixture
service = service_fixture


def test_recovery_survives_progress_rebuild_and_notifies_exactly_one_accepted_task(
    retry_view, tmp_path, monkeypatch, caplog
):
    view = retry_view
    manager = TaskManager(tmp_path / "lifecycle-jobs")
    original = manager.submit(
        "acquisition",
        "合成原批次",
        [],
        lambda _: {**view.job["result"], "status": "PARTIAL"},
        parameters=view.job["parameters"],
    )
    manager._futures[original["id"]].result(timeout=3)
    view.job["id"] = original["id"]
    view.page.ctx.settings = SettingsStore(tmp_path / "lifecycle-settings")
    view.page.ctx.jobs = SimpleNamespace(
        get=lambda key: (
            deepcopy(view.job) if key == view.job["id"] else manager.get(key)
        ),
        submit=manager.submit,
    )
    tracked, notified = [], []
    client = view.container.client
    original_notify = ui.notify

    def notify(message, **kwargs):
        assert ui.context.client is client
        assert not ui.context.slot.parent.is_deleted
        notified.append(message)
        original_notify(message, **kwargs)

    def track(receipt):
        tracked.append(receipt)
        view.container.clear()  # The real progress panel does this synchronously.
        gc.collect()

    monkeypatch.setattr(ui, "notify", notify)
    view.page.acquisition_progress_panel = SimpleNamespace(
        root=str(view.page.ctx.library.root),
        body=view.container,
        track=track,
    )
    view.page.submit = MethodType(WorkbenchUI.submit, view.page)
    view.choose_one(view.papers[0])
    start = view.callbacks["开始重试所选论文 / 补 SI"]

    async def exercise():
        # The event runs in a slot beneath the recovery dialog, like a real click.
        with start[1].parent_slot:
            await start[0]()
            await start[0]()

    try:
        asyncio.run(exercise())
        retries = [job for job in manager.list() if job["id"] != original["id"]]
        assert len(retries) == len(tracked) == len(notified) == 1
        receipt = retries[0]
        assert receipt["parameters"]["recovery"]["selected_ids"] == [
            view.papers[0].batch_key
        ]
        manager._futures[receipt["id"]].result(timeout=3)
        assert not start[1].is_deleted  # Dialog is a sibling of refreshed progress.
        assert not any(
            "element has been deleted" in record.message for record in caplog.records
        )
    finally:
        manager.close(wait=True)


def test_guard_reports_original_failure_in_stable_client_after_callback_parent_removed():
    client = ui.context.client
    parent = ui.column()
    with parent:
        child = ui.card()
    slot = child.default_slot

    async def fail_after_refresh():
        await asyncio.sleep(0)
        parent.clear()
        gc.collect()
        raise RuntimeError("fixture original failure after refresh")

    with child:
        callback = guard(fail_after_refresh)
    del child

    async def exercise():
        with slot:
            await callback()

    asyncio.run(exercise())
    assert any(
        "fixture original failure after refresh" in getattr(element, "content", "")
        for element in client.elements.values()
        if isinstance(element, ui.code)
    )


def test_guard_does_not_hide_original_exception_when_client_is_gone(monkeypatch):
    client = ui.context.client
    original = ValueError("fixture original failure without client")

    def fail():
        raise original

    callback = guard(fail)
    monkeypatch.setattr(client, "_deleted", True)
    with pytest.raises(ValueError) as raised:
        asyncio.run(callback())
    assert raised.value is original
