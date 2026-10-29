"""A single placement editor changes precisely the explicitly selected papers."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_acquisition_batch import AcquisitionBatchEditor
from aletheia_nexus.workbench.ui_acquisition_groups import AcquisitionGroupPanel

ui = pytest.importorskip("nicegui.ui")


class Grid:
    def __init__(self, rows):
        self.options = {"rowData": deepcopy(rows)}
        self.rows = deepcopy(rows)
        self.selected = set()
        self.filters = {
            "doi": {"filterType": "text", "type": "contains", "filter": "10."}
        }
        self.events = {}
        self.columns = None

    def on(self, name, callback):
        self.events[name] = callback

    async def get_client_data(self):
        return deepcopy(self.rows)

    async def get_selected_rows(self):
        return [deepcopy(row) for row in self.rows if row["id"] in self.selected]

    async def run_grid_method(self, method, *args):
        if method == "stopEditing":
            return
        if method == "setGridOption":
            if args[0] == "rowData":
                self.rows = deepcopy(args[1])
            return
        if method == "getFilterModel":
            return deepcopy(self.filters)
        if method == "setFilterModel":
            self.filters = deepcopy(args[0] or {})
        elif method == "deselectAll":
            self.selected.clear()
        elif method == "selectAll":
            assert args == ("filtered",)
            group = self.filters.get("input_group", {}).get("filter")
            self.selected = {
                r["id"] for r in self.rows if not group or r["input_group"] == group
            }
        elif method == "setColumnsVisible":
            self.columns = args
        else:
            raise AssertionError(method)


def mount(tmp_path, monkeypatch, groups=None):
    from aletheia_nexus.workbench import ui_acquisition_batch, ui_acquisition_groups

    monkeypatch.setattr(ui_acquisition_batch, "guard", lambda f: f)
    monkeypatch.setattr(ui_acquisition_groups, "guard", lambda f: f)
    callbacks = {}
    button = ui.button

    def capture(text, **kwargs):
        callbacks.setdefault(text, []).append(kwargs.get("on_click"))
        return button(text, **kwargs)

    monkeypatch.setattr(ui, "button", capture)
    library = LibraryService(tmp_path / "library")
    report = AcquisitionService(library.root).preview_inputs(
        "\n".join(f"10.9999/item-{i}" for i in range(9))
    )
    rows = [
        {
            "id": e["id"],
            "doi": e["request"]["doi"],
            "title": "",
            "enabled": True,
            "input_group": (groups or ["未分组"] * 9)[i],
            "folder_mode": "inherit",
            "folder": "",
            "tags_mode": "inherit",
            "tags": "",
            "filename": f"name-{i}",
        }
        for i, e in enumerate(report["items"])
    ]
    grid, saved = Grid(rows), []
    controller = SimpleNamespace(
        ctx=SimpleNamespace(library=library),
        tag_input=lambda label, values: ui.input(label, value=", ".join(values)),
    )
    editor = AcquisitionBatchEditor(
        controller,
        grid,
        report,
        lambda: "默认分类",
        lambda: ["默认标签"],
        lambda data: saved.append(deepcopy(data)),
    )
    before = set(ui.context.client.elements)
    editor.render_tools()
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    return editor, grid, saved, callbacks, elements


def test_nine_ungrouped_papers_have_compact_tools_not_duplicate_placement_forms(
    tmp_path, monkeypatch
):
    editor, grid, _, _, elements = mount(tmp_path, monkeypatch)
    labels = [e.props.get("label") for e in elements]
    assert "筛选清单分组" not in labels and "按输入分组查看" not in labels
    assert "批量目标分类（相对文库）" not in labels and "目录操作" not in labels
    assert not any(e.props.get("label") in {"保存目录", "标签处理"} for e in elements)
    grid.selected = {row["id"] for row in grid.rows}
    asyncio.run(editor.refresh_count())
    assert editor.placement_button.text == "设置所选 9 篇"
    assert editor.count.text == "本批将获取 9 篇 · 已选 9 篇用于修改"


@pytest.mark.parametrize(
    "groups,visible",
    [
        (["A"] * 9, False),
        (["A"] * 8 + ["未分组"], False),
        (["A"] * 4 + ["B"] * 5, True),
    ],
)
def test_group_filter_exists_only_for_multiple_real_input_groups(
    tmp_path, monkeypatch, groups, visible
):
    _, _, _, _, elements = mount(tmp_path, monkeypatch, groups)
    assert any(e.props.get("label") == "筛选清单分组" for e in elements) is visible


def test_paper_selected_and_group_actions_share_the_same_placement_form(
    tmp_path, monkeypatch
):
    from aletheia_nexus.workbench import ui_acquisition_groups

    editor, grid, _, _, _ = mount(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(
        ui_acquisition_groups,
        "placement_dialog",
        lambda *args, **kwargs: opened.append((args[2], kwargs)),
    )
    first, second = [r["id"] for r in grid.rows[:2]]
    grid.selected = {first, second}
    asyncio.run(editor.open_selected())
    asyncio.run(editor.open_row(second))
    panel = AcquisitionGroupPanel.__new__(AcquisitionGroupPanel)
    panel.controller, panel._snapshot = editor.controller, None
    panel.container = SimpleNamespace(client=editor.client)
    panel.get_batch, panel.refresh = lambda: editor, lambda: None
    panel.edit_group(editor, {"ids": [first, second], "name": "A", "count": 2})
    assert set(opened[0][0]) == {first, second}
    assert opened[1][0] == [second] and opened[2][0] == [first, second]
    assert all("保存位置与标签" in value[1]["title"] for value in opened)


def test_selected_dialog_preserves_other_rows_enable_filename_and_current_edits(
    tmp_path, monkeypatch
):
    editor, grid, saved, buttons, _ = mount(tmp_path, monkeypatch)
    first = grid.rows[0]["id"]
    grid.selected = {first}
    grid.rows[0].update(
        enabled=False,
        folder_mode="custom",
        folder="旧分类",
        tags_mode="custom",
        tags="旧标签",
    )
    before = set(ui.context.client.elements)
    asyncio.run(editor.open_selected())
    controls = {
        e.props.get("label"): e
        for key, e in ui.context.client.elements.items()
        if key not in before and e.props.get("label")
    }
    controls["保存目录"].set_value("root")
    controls["标签处理"].set_value("clear")
    grid.rows[0]["filename"] = "刚修改的文件名"
    grid.rows[1]["title"] = "未选论文的最新原题"
    second = deepcopy(grid.rows[1])
    asyncio.run(buttons["保存设置"][-1]())
    assert grid.rows[0]["folder_mode"] == "root"
    assert grid.rows[0]["tags_mode"] == "custom" and not grid.rows[0]["tags"]
    assert grid.rows[0]["filename"] == "刚修改的文件名" and not grid.rows[0]["enabled"]
    assert all(grid.rows[1][key] == value for key, value in second.items())
    assert saved[-1] == grid.rows


def test_empty_selection_never_implies_editing_the_whole_batch(tmp_path, monkeypatch):
    editor, _, _, _, _ = mount(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="先勾选"):
        asyncio.run(editor.open_selected())


def test_group_filter_preserves_other_filters_and_filtered_selection_and_filename_toggle(
    tmp_path, monkeypatch
):
    from nicegui import core

    editor, grid, _, buttons, elements = mount(
        tmp_path, monkeypatch, ["A"] * 4 + ["B"] * 5
    )
    selector = next(e for e in elements if e.props.get("label") == "筛选清单分组")
    details = next(
        e
        for e in elements
        if getattr(e, "text", "") == "显示单篇文件名、身份阶段和设置诊断列"
    )

    async def exercise():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        selector.set_value("B")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert "doi" in grid.filters and grid.filters["input_group"]["filter"] == "B"
        await buttons["选择当前筛选"][0]()
        assert grid.selected == {r["id"] for r in grid.rows if r["input_group"] == "B"}
        assert editor.placement_button.text == "设置所选 5 篇"
        details.set_value(True)
        selector.set_value("")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert list(grid.filters) == ["doi"]
        assert grid.columns == (["filename", "resolution", "placement_error"], True)

    asyncio.run(exercise())


def test_old_preview_dialog_cannot_save_after_grid_was_replaced(tmp_path, monkeypatch):
    editor, grid, saved, buttons, _ = mount(tmp_path, monkeypatch)
    grid.selected = {grid.rows[0]["id"]}
    asyncio.run(editor.open_selected())
    grid.is_deleted = True
    with pytest.raises(ValueError, match="预览已更新"):
        asyncio.run(buttons["保存设置"][-1]())
    assert not saved
