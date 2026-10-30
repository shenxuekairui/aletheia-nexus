"""Organization previews change only explicit stable membership/metadata."""

import asyncio
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_organization import collection_change


@pytest.mark.parametrize(
    "action,expected",
    [("replace", ["b", "c"]), ("add", ["a", "b", "c"]), ("remove", ["a"])],
)
def test_collection_changes_use_stable_ids_and_report_real_differences(
    action, expected
):
    original = ["a", "b"]
    result = collection_change(original, ["b", "c", "c"], action)
    assert result["after"] == expected and original == ["a", "b"]
    assert result["added"] == [key for key in expected if key not in original]
    assert result["removed"] == [key for key in original if key not in expected]


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import run, ui

    from aletheia_nexus.workbench import ui_organization
    from aletheia_nexus.workbench.ui_library import LibraryPage

    library = LibraryService(tmp_path / "library")
    papers = []
    for index in range(3):
        incoming = tmp_path / f"fixture-{index}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200 + index, height=200)
        writer.write(incoming)
        papers.append(library.import_pdf(incoming, title=f"合成文献{index + 1}"))
    ids = [row["id"] for row in papers]
    library.save_collection("固定集合", [ids[0], ids[2]])
    library.save_filter("保存筛选", {"collection": "固定集合", "tags": ["催化"]})
    library.save_tag_group("研究对象", ["催化"])
    library.set_selection([ids[2]])
    baseline = {
        str(path): sha256(path.read_bytes()).hexdigest()
        for path in library.root.rglob("*")
        if path.is_file() and not path.is_relative_to(library.state_dir)
    }
    history = tmp_path / "historical.result.json"
    history.write_text('{"original":"immutable fixture"}', encoding="utf-8")
    before_history = history.read_bytes()
    callbacks, notices, changes, applied = {}, [], [], []
    original_button = ui.button

    def capture(*args, **kwargs):
        element = original_button(*args, **kwargs)
        callbacks[args[0] if args else kwargs.get("text")] = kwargs.get("on_click")
        return element

    async def io_bound(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    monkeypatch.setattr(ui, "button", capture)
    monkeypatch.setattr(ui, "notify", lambda text, **_: notices.append(text))
    monkeypatch.setattr(ui_organization, "guard", lambda callback: callback)
    monkeypatch.setattr(run, "io_bound", io_bound)
    controller = LibraryPage()
    controller.ctx = SimpleNamespace(library=library)
    before = set(ui.context.client.elements)
    client = ui.context.client

    async def open_dialog():
        with client.layout:
            return await ui_organization.render_organization_dialog(
                controller,
                marked_ids=[ids[1]],
                current_filters={"tags": ["新条件"], "tag_mode": "AND"},
                on_updated=changes.append,
                apply_filter=applied.append,
            )

    asyncio.run(open_dialog())

    def elements():
        return [
            element
            for key, element in ui.context.client.elements.items()
            if key not in before and not element.is_deleted
        ]

    def control(label):
        return next(
            element
            for element in elements()
            if getattr(element, "label", None) == label
        )

    def confirm():
        next(
            element
            for element in elements()
            if getattr(element, "text", "")
            == "我已核对以上范围和变化，确认执行本次修改"
        ).set_value(True)

    yield SimpleNamespace(
        library=library,
        ids=ids,
        callbacks=callbacks,
        controls=control,
        elements=elements,
        confirm=confirm,
        changes=changes,
        applied=applied,
    )
    assert history.read_bytes() == before_history
    assert {
        str(path): sha256(path.read_bytes()).hexdigest()
        for path in library.root.rglob("*")
        if path.is_file() and not path.is_relative_to(library.state_dir)
    } == baseline


def test_actual_member_preview_requires_confirmation_and_preserves_tray_and_files(
    mounted,
):
    fixture = mounted
    fixture.controls("成员操作").set_value("replace")
    fixture.callbacks["预览成员变更"]()
    assert any(
        "原成员 2 篇 → 新成员 1 篇；新增 1 篇，移除 2 篇。" == getattr(e, "text", "")
        for e in fixture.elements()
    )
    assert fixture.library.collections()["固定集合"] == [fixture.ids[0], fixture.ids[2]]
    with pytest.raises(ValueError, match="明确确认"):
        asyncio.run(fixture.callbacks["确认执行本次修改"]())
    fixture.confirm()
    asyncio.run(fixture.callbacks["确认执行本次修改"]())
    assert fixture.library.collections()["固定集合"] == [fixture.ids[1]]
    assert fixture.library.selection() == [fixture.ids[2]]
    assert fixture.changes[-1]["added"] == [fixture.ids[1]]


def test_actual_rename_updates_dependent_filter_and_referenced_delete_is_refused(
    mounted,
):
    fixture = mounted
    fixture.controls("新名称（仅改组织名称）").set_value("新集合名称")
    fixture.callbacks["预览重命名"]()
    fixture.confirm()
    asyncio.run(fixture.callbacks["确认执行本次修改"]())
    assert "固定集合" not in fixture.library.collections()
    assert fixture.library.filters()["保存筛选"]["collection"] == "新集合名称"
    with pytest.raises(ValueError, match="仍被以下保存筛选使用"):
        fixture.callbacks["预览删除"]()
    assert "新集合名称" in fixture.library.collections()


def test_actual_filter_update_run_rename_delete_and_tag_group_edit(mounted):
    fixture = mounted
    fixture.controls("管理哪类对象").set_value("filters")
    fixture.callbacks["预览更新为当前文库筛选条件"]()
    fixture.confirm()
    asyncio.run(fixture.callbacks["确认执行本次修改"]())
    assert fixture.library.filters()["保存筛选"] == {
        "tags": ["新条件"],
        "tag_mode": "AND",
    }
    fixture.callbacks["在文库中运行此筛选"]()
    assert fixture.applied == [{"tags": ["新条件"], "tag_mode": "AND"}]
    fixture.controls("新名称（仅改组织名称）").set_value("改名筛选")
    fixture.callbacks["预览重命名"]()
    fixture.confirm()
    asyncio.run(fixture.callbacks["确认执行本次修改"]())
    fixture.callbacks["预览删除"]()
    fixture.confirm()
    asyncio.run(fixture.callbacks["确认执行本次修改"]())
    assert fixture.library.filters() == {}
    fixture.controls("管理哪类对象").set_value("tag_groups")
    fixture.controls("修改组内标签（输入可查找，回车新建）").set_value(["催化", "产物"])
    fixture.callbacks["预览分组标签修改"]()
    fixture.confirm()
    asyncio.run(fixture.callbacks["确认执行本次修改"]())
    assert fixture.library.tag_groups()["研究对象"] == ["催化", "产物"]


def test_stale_preview_cannot_overwrite_a_later_membership_change(mounted):
    fixture = mounted
    fixture.callbacks["预览成员变更"]()
    fixture.confirm()
    fixture.library.save_collection("固定集合", [fixture.ids[0]])
    with pytest.raises(ValueError, match="其它窗口修改"):
        asyncio.run(fixture.callbacks["确认执行本次修改"]())
    assert fixture.library.collections()["固定集合"] == [fixture.ids[0]]


def test_editing_action_after_confirmation_invalidates_the_old_preview(mounted):
    fixture = mounted
    fixture.callbacks["预览成员变更"]()
    fixture.confirm()
    stale = fixture.callbacks["确认执行本次修改"]
    before = deepcopy(fixture.library.collections())
    fixture.controls("成员操作").set_value("replace")
    with pytest.raises(ValueError, match="明确确认"):
        asyncio.run(stale())
    assert fixture.library.collections() == before


def test_library_management_entry_refreshes_selectors_without_recreating_the_grid(
    monkeypatch,
):
    from test_library_quick_actions import library_callback

    from aletheia_nexus.workbench import ui_organization
    from aletheia_nexus.workbench.ui_library import marked_library_ids

    opened, refreshed = [], []

    class Select:
        def __init__(self, value):
            self.value = value
            self.options = []

        def set_options(self, options, *, value):
            self.options, self.value = options, value

    collection, saved = Select("旧集合"), Select("旧筛选")

    async def get_selected_rows():
        return [{"id": "paper1"}]

    async def open_dialog(controller, **kwargs):
        opened.append(kwargs)

    async def refresh():
        refreshed.append(True)

    def no_page_recreation():
        pytest.fail(
            "An organization update must retain the native grid and its selected IDs"
        )

    monkeypatch.setattr(ui_organization, "render_organization_dialog", open_dialog)
    controller = SimpleNamespace(
        library_rows=[{"id": "paper1"}],
        ctx=SimpleNamespace(
            library=SimpleNamespace(
                collections=lambda: {"新集合": ["paper1"]}, filters=lambda: {"筛选": {}}
            )
        ),
        page_content=SimpleNamespace(refresh=no_page_recreation),
    )
    callback = library_callback(
        "manage_organization",
        {
            "__name__": "aletheia_nexus.workbench.ui_library",
            "__package__": "aletheia_nexus.workbench",
            "self": controller,
            "grid": SimpleNamespace(get_selected_rows=get_selected_rows),
            "marked_library_ids": marked_library_ids,
            "filters": lambda: {"collection": "旧集合"},
            "collection": collection,
            "saved": saved,
            "refresh": refresh,
        },
    )
    asyncio.run(callback())
    assert opened[0]["marked_ids"] == ["paper1"]
    assert opened[0]["current_filters"] == {"collection": "旧集合"}
    asyncio.run(
        opened[0]["on_updated"](
            {"section": "collections", "name": "旧集合", "new_name": "新集合"}
        )
    )
    assert collection.value == "新集合" and collection.options == ["", "新集合"]
    assert saved.value == "" and refreshed == [True]
