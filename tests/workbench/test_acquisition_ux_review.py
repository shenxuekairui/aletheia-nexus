"""Independent first-use regressions: local drafts and edits, no GUI or API."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.acquisition_batch import apply_assignment
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.ui_acquisition import AcquisitionPage
from aletheia_nexus.workbench.ui_acquisition_batch import AcquisitionBatchEditor


def _rows(report):
    return [
        {
            "id": entry["id"],
            "enabled": True,
            "doi": entry["request"]["doi"] or "",
            "title": entry["request"]["title"] or "",
            "folder": entry["request"]["folder"] or "",
            "tags": ", ".join(entry["request"]["tags"]),
            "filename": "",
            "input_group": entry.get("group") or "未分组",
            "resolution": "DOI" if entry["request"]["doi"] else "待解析标题",
            **entry["assignment"],
        }
        for entry in report["items"]
        if not entry["duplicate"]
    ]


def test_native_row_update_never_writes_observable_options_and_preserves_scope(
    tmp_path,
):
    class Options(dict):
        def __setitem__(self, key, value):
            raise AssertionError("Writing observable options would destroy the grid")

    library = LibraryService(tmp_path / "library")
    report = AcquisitionService(library.root).preview_inputs(
        "10.9999/first\n10.9999/second"
    )
    rows = _rows(report)
    selected = {rows[0]["id"]}

    class Grid:
        def __init__(self):
            self.options = Options(rowData=deepcopy(rows))
            self.rows = deepcopy(rows)
            self.filter = {"input_group": "甲"}

        async def run_grid_method(self, name, *args):
            if name == "setGridOption":
                assert args[0] == "rowData"
                self.rows = deepcopy(args[1])
            else:
                assert name == "stopEditing"

        async def get_client_data(self):
            return deepcopy(self.rows)

        async def get_selected_rows(self):
            return [row for row in self.rows if row["id"] in selected]

    grid, drafts = Grid(), []
    editor = AcquisitionBatchEditor(
        SimpleNamespace(ctx=SimpleNamespace(library=library)),
        grid,
        report,
        lambda: "默认分类",
        lambda: ["共享标签"],
        lambda value: drafts.append(deepcopy(value)),
    )
    editor.count = SimpleNamespace(set_text=lambda value: None)
    updated = apply_assignment(rows, selected, folder_action="root", tag_action="clear")
    asyncio.run(editor.replace(updated))
    assert editor.rows == grid.rows == drafts[-1]
    assert grid.options["rowData"] == rows
    assert {row["id"] for row in asyncio.run(grid.get_selected_rows())} == selected
    assert grid.filter == {"input_group": "甲"}
    requests = asyncio.run(editor.requests())
    assert requests[0]["folder"] is None and requests[0]["tags"] == []
    assert requests[1]["folder"] == "默认分类" and requests[1]["tags"] == ["共享标签"]
    assert all(row["enabled"] for row in grid.rows)


def _mount_page(
    tmp_path, monkeypatch, text="10.9999/first\n10.9999/second", *, seed=True
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_acquisition_batch

    library = LibraryService(tmp_path / "library")
    acquisition = AcquisitionService(library.root)
    settings = SettingsStore(tmp_path / "workspace")
    report = acquisition.preview_inputs(text)
    if seed:
        settings.set(
            "acquisition_input_draft",
            {
                "library": str(library.root),
                "text": text,
                "preview_text": text,
                "report": report,
                "rows": _rows(report),
                "dirty": False,
                "default_folder": "默认分类",
                "default_tags": ["共享标签"],
            },
        )
    captured, buttons = [], {}

    class Editor(AcquisitionBatchEditor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(self)

    class Controller(AcquisitionPage):
        def title(self, *_):
            pass

        def import_dialog(self):
            pytest.fail("Importing is not part of this offline preview")

        def task_dialog(self):
            pytest.fail("Task history is not part of this offline preview")

    monkeypatch.setattr(ui_acquisition_batch, "AcquisitionBatchEditor", Editor)
    monkeypatch.setattr(
        "aletheia_nexus.workbench.ui_acquisition.guard", lambda callback: callback
    )
    monkeypatch.setattr(
        "aletheia_nexus.workbench.ui_acquisition_batch.guard", lambda callback: callback
    )
    monkeypatch.setattr(ui, "timer", lambda *_args, **_kwargs: None)
    original_button = ui.button

    def capture_button(*args, **kwargs):
        label = args[0] if args else kwargs.get("text", "")
        buttons.setdefault(label, []).append(kwargs.get("on_click"))
        return original_button(*args, **kwargs)

    monkeypatch.setattr(ui, "button", capture_button)
    before = set(ui.context.client.elements)
    controller = Controller()
    controller.ctx = SimpleNamespace(
        library=library,
        settings=settings,
        acquisition=acquisition,
        jobs=SimpleNamespace(list=lambda: []),
    )
    controller.acquisition_page()
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    raw = next(
        element
        for element in elements
        if element.props.get("label") == "粘贴 DOI、标题或分组文献清单"
    )
    return controller, captured[0], buttons, elements, raw, settings


def test_draft_text_changes_save_latest_editor_rows_not_initial_options(
    tmp_path, monkeypatch
):
    _, editor, _, elements, raw, settings = _mount_page(tmp_path, monkeypatch)
    original_text = raw.value
    latest = deepcopy(editor.rows)
    latest[0].update(
        folder_mode="root", folder="", tags_mode="custom", tags="", enabled=False
    )
    latest[1].update(
        folder_mode="custom", folder="单独分类", tags_mode="custom", tags="独立标签"
    )
    editor.rows = latest
    assert editor.grid.options["rowData"][0]["folder_mode"] == "inherit"
    raw.set_value(original_text + "\nnew input")
    draft = settings.get("acquisition_input_draft")
    assert draft["rows"] == latest and draft["dirty"]
    assert draft["preview_text"] == original_text
    raw.set_value(original_text)
    assert not settings.get("acquisition_input_draft")["dirty"]
    checkbox = next(
        element
        for element in elements
        if getattr(element, "text", "") == "入库后自动翻译缺失的英文标题"
    )
    consent = next(
        element
        for element in elements
        if getattr(element, "text", "")
        == "我授权仅将待翻译的英文标题发送给DeepSeek，并接受所示费用上限"
    )
    assert not checkbox.value and not consent.value and not consent.visible
    _, restored, _, _, restored_raw, restored_settings = _mount_page(
        tmp_path, monkeypatch, seed=False
    )
    assert restored_raw.value == original_text
    assert restored.rows[0]["folder_mode"] == "root"
    assert restored.rows[0]["tags_mode"] == "custom" and restored.rows[0]["tags"] == ""
    assert not restored.rows[0]["enabled"]
    assert restored.rows[1]["folder"] == "单独分类"
    assert restored.rows[1]["tags"] == "独立标签"
    assert not restored_settings.get("acquisition_input_draft")["dirty"]


def test_delayed_title_candidate_preserves_other_rows_and_current_placement(
    tmp_path, monkeypatch
):
    pytest.importorskip("nicegui")
    from nicegui import run

    _, editor, buttons, _, _, settings = _mount_page(
        tmp_path, monkeypatch, "Known English title\n10.9999/other"
    )
    client = deepcopy(editor.rows)
    first = client[0]["id"]

    async def grid_method(name, *args):
        if name == "setGridOption":
            assert args[0] == "rowData"
            client[:] = deepcopy(args[1])
        else:
            assert name == "stopEditing"

    async def data():
        return deepcopy(client)

    async def selected():
        return [deepcopy(row) for row in client if row["id"] == first]

    monkeypatch.setattr(editor.grid, "run_grid_method", grid_method)
    monkeypatch.setattr(editor.grid, "get_client_data", data)
    monkeypatch.setattr(editor.grid, "get_selected_rows", selected)

    async def scenario():
        requested, release = asyncio.Event(), asyncio.Event()

        async def metadata_only(function, *_args, **_kwargs):
            assert function.__name__ == "resolve_title"
            requested.set()
            await release.wait()
            return {
                "status": "RESOLVED",
                "request": {"doi": "10.9999/resolved", "title": "Known English title"},
            }

        monkeypatch.setattr(run, "io_bound", metadata_only)

        async def resolve_in_client_context():
            with editor.grid.parent_slot:
                await buttons["解析 / 确认当前选中标题"][-1]()

        task = asyncio.create_task(resolve_in_client_context())
        try:
            await asyncio.wait_for(requested.wait(), timeout=2)
        except TimeoutError:
            if task.done():
                await task
            task.cancel()
            raise
        client[0].update(
            folder_mode="root",
            folder="",
            tags_mode="custom",
            tags="",
            filename="explicit-name",
        )
        client[1].update(
            folder_mode="custom",
            folder="查询期间新分类",
            tags_mode="custom",
            tags="查询期间新增",
            enabled=False,
        )
        release.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    assert client[0]["doi"] == "10.9999/resolved"
    assert client[0]["folder_mode"] == "root" and client[0]["tags"] == ""
    assert client[0]["filename"] == "explicit-name"
    assert (
        client[1]["folder"] == "查询期间新分类" and client[1]["tags"] == "查询期间新增"
    )
    assert not client[1]["enabled"]
    assert settings.get("acquisition_input_draft")["rows"] == client
