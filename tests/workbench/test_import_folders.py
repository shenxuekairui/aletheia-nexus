"""Source browsing is explicit, bounded, read-only, and never starts an import."""

import asyncio
import ctypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from aletheia_nexus.workbench import ui_import_folders as picker


def test_single_level_pagination_does_not_read_files_or_enter_children(
    tmp_path, monkeypatch
):
    for index in range(205):
        (tmp_path / f"文件夹-{index:03d}").mkdir()
    (tmp_path / "文件夹-000" / "不会递归进入").mkdir()
    (tmp_path / "article.pdf").write_bytes(b"not opened by folder selection")
    original_scan = picker.os.scandir
    scanned = []

    def scan(path):
        scanned.append(Path(path))
        assert Path(path) == tmp_path
        return original_scan(path)

    monkeypatch.setattr(picker.os, "scandir", scan)
    monkeypatch.setattr(
        Path, "open", lambda *a, **k: pytest.fail("must not open file content")
    )
    found, offset = [], 0
    while True:
        report = picker.list_import_folders(tmp_path, offset=offset)
        assert len(report["items"]) <= 200
        found.extend(item["name"] for item in report["items"])
        if not report["has_more"]:
            break
        assert report["next_offset"] > offset
        offset = report["next_offset"]
    assert len(found) == len(set(found)) == 205
    assert len(scanned) == 2 and "不会递归进入" not in found


def test_entry_budget_can_continue_through_file_only_pages(tmp_path):
    for index in range(7):
        (tmp_path / f"file-{index}.txt").touch()
    (tmp_path / "实际文件夹").mkdir()
    offset, found = 0, []
    while True:
        report = picker.list_import_folders(tmp_path, offset=offset, max_entries=2)
        assert report["examined"] <= 2
        found.extend(item["name"] for item in report["items"])
        if not report["has_more"]:
            break
        offset = report["next_offset"]
    assert found == ["实际文件夹"]


def test_initial_handles_explorer_quotes_and_file_parent_without_reading(tmp_path):
    file = tmp_path / "已有论文.pdf"
    file.touch()
    assert picker.initial_import_folder(f' "{tmp_path}" ') == {
        "path": str(tmp_path),
        "warning": "",
    }
    assert picker.initial_import_folder(f"'{file}'") == {
        "path": str(tmp_path),
        "warning": "",
    }
    with pytest.raises(ValueError, match="不是文件夹"):
        picker.resolve_import_folder(file)


def test_invalid_initial_falls_back_visibly_and_does_not_create_missing_folder(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    missing = tmp_path / "不存在"
    report = picker.initial_import_folder(missing)
    assert report["path"] == str(tmp_path) and report["warning"]
    assert not missing.exists()
    for value in ("", "  ", '""', "relative-folder"):
        with pytest.raises(ValueError):
            picker.resolve_import_folder(value)


def test_reparse_directory_and_its_ancestors_are_not_used(tmp_path, monkeypatch):
    junction = tmp_path / "模拟联接"
    junction.mkdir()
    (junction / "nested").mkdir()
    original = picker._is_reparse_point
    monkeypatch.setattr(
        picker, "_is_reparse_point", lambda path: path == junction or original(path)
    )
    report = picker.list_import_folders(tmp_path)
    assert report["items"] == [] and report["skipped"] == 1
    with pytest.raises(ValueError, match="目录联接"):
        picker.resolve_import_folder(junction / "nested")


def test_missing_and_permission_failures_are_chinese(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="已不存在"):
        picker.resolve_import_folder(tmp_path / "missing")

    def denied(path):
        raise PermissionError("not exposed as ordinary English")

    monkeypatch.setattr(picker.os, "scandir", denied)
    with pytest.raises(ValueError, match="没有读取.*权限"):
        picker.list_import_folders(tmp_path)


def test_windows_drive_inventory_never_probes_26_paths(monkeypatch):
    monkeypatch.setattr(
        picker.os, "listdrives", lambda: ["C:\\", "F:\\", "Z:\\"], raising=False
    )
    monkeypatch.setattr(
        Path,
        "stat",
        lambda *a, **k: pytest.fail("drive inventory must not stat mapped drives"),
    )
    assert picker._windows_drives() == ["C:\\", "F:\\", "Z:\\"]


def test_python311_windows_fallback_uses_logical_drive_bitmask(monkeypatch):
    monkeypatch.delattr(picker.os, "listdrives", raising=False)
    call = Mock(return_value=(1 << 2) | (1 << 5))
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(GetLogicalDrives=call)),
        raising=False,
    )
    assert picker._windows_drives() == ["C:\\", "F:\\"]
    call.assert_called_once_with()


@pytest.mark.parametrize(
    "options", [{"limit": 201}, {"offset": -1}, {"max_entries": 0}, {"limit": True}]
)
def test_limits_reject_invalid_values_before_enumeration(tmp_path, options):
    with pytest.raises(ValueError):
        picker.list_import_folders(tmp_path, **options)


def widget(tmp_path, monkeypatch, *, initial=None, io=None):
    ui = pytest.importorskip("nicegui.ui")
    from nicegui import run

    buttons, scheduled, selected = {}, [], []
    original_button = ui.button

    def button(text="", **kwargs):
        value = original_button(text, **kwargs)
        buttons[text] = (value, kwargs.get("on_click"))
        return value

    async def default_io(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(
        ui, "timer", lambda _interval, callback, **kwargs: scheduled.append(callback)
    )
    monkeypatch.setattr(run, "io_bound", io or default_io)
    monkeypatch.setattr(
        picker,
        "import_folder_locations",
        lambda: [{"label": "测试位置", "path": str(tmp_path)}],
    )
    dialog = picker.choose_import_folder(
        selected.append, initial=str(initial or tmp_path)
    )
    assert not selected and len(scheduled) == 1
    return dialog, buttons, scheduled[0], selected


def test_widget_enters_child_and_parent_and_delivers_only_on_explicit_choose(
    tmp_path, monkeypatch
):
    child = tmp_path / "子目录"
    child.mkdir()
    dialog, buttons, start, selected = widget(tmp_path, monkeypatch)
    asyncio.run(start())
    assert selected == [] and buttons["选择当前文件夹"][0].enabled
    asyncio.run(buttons["子目录"][1]())
    assert selected == []
    asyncio.run(buttons["上一级文件夹"][1]())
    asyncio.run(buttons["子目录"][1]())
    asyncio.run(buttons["选择当前文件夹"][1]())
    assert selected == [str(child.resolve())] and not dialog.value


def test_unreadable_child_can_return_to_parent_without_stale_selection(
    tmp_path, monkeypatch
):
    child = tmp_path / "消失目录"
    child.mkdir()
    _, buttons, start, selected = widget(tmp_path, monkeypatch)
    asyncio.run(start())
    child.rmdir()
    asyncio.run(buttons["消失目录"][1]())
    assert not buttons["选择当前文件夹"][0].enabled
    assert buttons["上一级文件夹"][0].enabled
    asyncio.run(buttons["上一级文件夹"][1]())
    assert buttons["选择当前文件夹"][0].enabled and selected == []


def test_hide_invalidates_pending_choose_before_path_delivery(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def io(function, *args, **kwargs):
        if function is picker.resolve_import_folder:
            entered.set()
            await release.wait()
        return function(*args, **kwargs)

    dialog, buttons, start, selected = widget(tmp_path, monkeypatch, io=io)

    async def scenario():
        await start()
        pending = asyncio.create_task(buttons["选择当前文件夹"][1]())
        await entered.wait()
        hide = next(
            listener.handler
            for listener in dialog._event_listeners.values()
            if listener.type == "hide"
        )
        hide(None)
        release.set()
        await pending
        assert selected == []

    asyncio.run(scenario())


def test_slow_initial_location_cannot_overwrite_explicit_user_navigation(
    tmp_path, monkeypatch
):
    old = tmp_path / "旧初始位置"
    old.mkdir()
    entered, release = asyncio.Event(), asyncio.Event()

    async def io(function, *args, **kwargs):
        if function is picker.initial_import_folder:
            entered.set()
            await release.wait()
        return function(*args, **kwargs)

    _, buttons, start, selected = widget(tmp_path, monkeypatch, initial=old, io=io)

    async def scenario():
        pending = asyncio.create_task(start())
        await entered.wait()
        await buttons["测试位置"][1]()
        release.set()
        await pending
        await buttons["选择当前文件夹"][1]()
        assert selected == [str(tmp_path.resolve())]

    asyncio.run(scenario())
