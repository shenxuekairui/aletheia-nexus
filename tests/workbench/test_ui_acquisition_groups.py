"""Group placement uses current edited rows and preserves download controls."""

import asyncio
import gc
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.ui_acquisition_groups import (
    AcquisitionGroupPanel,
    summarize_input_groups,
)


def papers():
    return [
        {
            "id": "first",
            "input_group": "A",
            "enabled": True,
            "folder_mode": "inherit",
            "folder": "",
            "tags_mode": "inherit",
            "tags": "",
            "filename": "保留自定义名",
        },
        {
            "id": "second",
            "input_group": "A",
            "enabled": False,
            "folder_mode": "custom",
            "folder": "不同目录",
            "tags_mode": "custom",
            "tags": "原标签",
            "filename": "",
        },
        {
            "id": "third",
            "input_group": "B",
            "enabled": True,
            "folder_mode": "root",
            "folder": "",
            "tags_mode": "custom",
            "tags": "",
            "filename": "第三篇",
        },
    ]


def test_group_summary_shows_real_root_custom_default_and_disabled_counts():
    rows = papers()
    original = deepcopy(rows)
    groups = summarize_input_groups(rows, "批次默认")
    assert groups[0] == {
        "name": "A",
        "ids": ["first", "second"],
        "enabled": 1,
        "count": 2,
        "folders": {"批次默认": 1, "不同目录": 1},
    }
    assert groups[1]["folders"] == {"文库根目录": 1}
    assert rows == original
    assert summarize_input_groups(rows, "新默认")[0]["folders"] == {
        "新默认": 1,
        "不同目录": 1,
    }


class ReadOnlyOptions(dict):
    def __setitem__(self, key, value):
        raise AssertionError("Observable options must never be mutated")


class Grid:
    def __init__(self):
        self.rows = papers()
        self.options = ReadOnlyOptions(rowData=deepcopy(self.rows))
        self.committed = False

    async def run_grid_method(self, method, *args):
        assert method == "stopEditing"
        self.committed = True

    async def get_client_data(self):
        assert self.committed
        return deepcopy(self.rows)


def test_group_edit_reads_latest_grid_changes_and_only_changes_group_ids():
    grid = Grid()
    cached = deepcopy(grid.rows)
    grid.rows[2]["title"] = "此时第三篇已在主表编辑"
    saved = []

    async def replace(rows):
        saved.append(deepcopy(rows))

    batch = SimpleNamespace(
        grid=grid,
        rows=cached,
        default_folder=lambda: "默认",
        default_tags=lambda: ["默认标签"],
        replace=replace,
    )
    panel = AcquisitionGroupPanel.__new__(AcquisitionGroupPanel)
    panel.get_batch = lambda: batch
    panel.refresh = lambda: None
    asyncio.run(
        panel.apply_group(
            batch, ["first", "second"], folder_action="root", tag_action="clear"
        )
    )
    updated = saved[0]
    assert all(
        row["folder_mode"] == "root"
        and row["tags_mode"] == "custom"
        and not row["tags"]
        for row in updated[:2]
    )
    assert updated[1]["enabled"] is False
    assert updated[0]["filename"] == "保留自定义名"
    assert updated[2] == grid.rows[2]
    assert grid.options["rowData"] == cached


def test_group_dialog_cannot_save_into_replaced_preview():
    panel = AcquisitionGroupPanel.__new__(AcquisitionGroupPanel)
    panel.get_batch = lambda: object()
    with pytest.raises(ValueError, match="预览已更新"):
        asyncio.run(
            panel.apply_group(SimpleNamespace(), ["first"], folder_action="root")
        )


def test_visible_panel_has_manual_preview_group_destinations_and_single_paper_entry(
    monkeypatch,
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_acquisition_groups

    monkeypatch.setattr(ui_acquisition_groups, "guard", lambda callback: callback)
    buttons = {}
    original_button = ui.button

    def button(label, **kwargs):
        buttons.setdefault(label, []).append(kwargs.get("on_click"))
        return original_button(label, **kwargs)

    monkeypatch.setattr(ui, "button", button)
    batch = {"current": None}
    opened = []

    async def open_row(paper_id):
        opened.append(paper_id)

    async def ensure_preview():
        batch["current"] = SimpleNamespace(
            rows=papers(), default_folder=lambda: "默认目录", open_row=open_row
        )

    with ui.column() as container:
        panel = AcquisitionGroupPanel(
            SimpleNamespace(), lambda: batch["current"], ensure_preview
        )
    assert "整理清单并设置多个目录" in buttons

    async def exercise():
        from nicegui import core

        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with container:
            await buttons["整理清单并设置多个目录"][0]()
        assert len(buttons["设置目录与标签"]) == 2
        assert "设置本篇" in buttons
        labels = [
            getattr(element, "text", "")
            for element in container.client.elements.values()
        ]
        assert "默认目录 · 1 篇" in labels and "文库根目录 · 1 篇" in labels
        await buttons["设置本篇"][0]()
        assert opened == ["first"]
        current = papers()
        current[0]["folder_mode"], current[0]["folder"] = "custom", "刚编辑的目录"
        with container:
            panel.refresh(current)
        labels = [
            getattr(element, "text", "")
            for element in container.client.elements.values()
        ]
        assert "刚编辑的目录 · 1 篇" in labels

    asyncio.run(exercise())


def test_saving_group_does_not_delete_dialog_when_saved_draft_refreshes_sidebar(
    tmp_path, monkeypatch
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_acquisition_groups
    from aletheia_nexus.workbench.library import LibraryService

    monkeypatch.setattr(ui_acquisition_groups, "guard", lambda callback: callback)
    callbacks, dialogs = {}, []
    button, dialog_class = ui.button, ui.dialog

    def capture_button(label, **kwargs):
        callbacks[label] = kwargs.get("on_click")
        return button(label, **kwargs)

    def capture_dialog(*args, **kwargs):
        dialog = dialog_class(*args, **kwargs)
        dialogs.append(dialog)
        return dialog

    monkeypatch.setattr(ui, "button", capture_button)
    monkeypatch.setattr(ui, "dialog", capture_dialog)
    grid = Grid()
    panel = None

    async def replace(rows):
        batch.rows = deepcopy(rows)
        # This is the actual root save_draft(rows) callback ordering.
        panel.refresh(rows)
        gc.collect()
        assert not dialogs[-1].is_deleted

    batch = SimpleNamespace(
        rows=papers(),
        grid=grid,
        default_folder=lambda: "默认",
        default_tags=lambda: [],
        replace=replace,
        open_row=lambda *_: None,
    )
    controller = SimpleNamespace(
        ctx=SimpleNamespace(library=LibraryService(tmp_path / "library")),
        tag_input=lambda label, values: ui.input(label, value=", ".join(values)),
    )
    with ui.column():
        panel = AcquisitionGroupPanel(controller, lambda: batch, lambda: None)
    # A real click enters the sidebar button context, rather than a stable root.
    with panel.container:
        panel.edit_group(batch, summarize_input_groups(batch.rows)[0])
    assert dialogs[-1].value
    asyncio.run(callbacks["保存设置"]())
    assert not dialogs[-1].is_deleted
    assert dialogs[-1].value is False
