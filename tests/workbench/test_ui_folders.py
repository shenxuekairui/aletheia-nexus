"""Category chooser security and real directory behavior; no live library/GUI."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_folders import (
    _is_reparse_point,
    choose_library_folder,
    create_library_subfolder,
    resolve_library_folder,
    scan_library_folders,
)


@pytest.fixture
def library(tmp_path):
    return LibraryService(tmp_path / "library")


def test_tree_includes_empty_folders_without_reading_pdf_or_internal_data(
    library, monkeypatch
):
    root = library.root
    for name in (
        "电合成/空分类",
        "表征",
        "SI/附件",
        "json/解析",
        ".hidden/private",
        "_tmp/中转",
    ):
        (root / name).mkdir(parents=True)
    (root / "paper.pdf").write_bytes(b"Not a parsed PDF; must never be opened")
    monkeypatch.setattr(library, "scan", lambda: pytest.fail("Do not scan papers"))
    with monkeypatch.context() as guard:
        guard.setattr(
            Path, "read_bytes", lambda *_: pytest.fail("Do not open file bytes")
        )
        guard.setattr(
            Path,
            "read_text",
            lambda *_args, **_kwargs: pytest.fail("Do not read JSON/PDF"),
        )
        report = scan_library_folders(library)
    assert {row["relative"] for row in report["items"]} == {
        "",
        "电合成",
        "电合成/空分类",
        "表征",
    }
    assert not report["truncated"]
    assert report["skipped"]["internal_or_invalid"] >= 4


def test_resolution_distinguishes_root_missing_and_file_without_creating(library):
    assert resolve_library_folder(library, "") == {
        "relative": "",
        "path": library.root,
        "exists": True,
    }
    assert resolve_library_folder(library, None)["relative"] == ""
    future = resolve_library_folder(library, "尚未创建/子类", must_exist=False)
    assert not future["exists"] and not future["path"].exists()
    with pytest.raises(ValueError, match="尚不存在"):
        resolve_library_folder(library, "尚未创建/子类")
    (library.root / "same-name").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="已有文件"):
        resolve_library_folder(library, "same-name", must_exist=False)


@pytest.mark.parametrize(
    "relative",
    [
        "../outside",
        "/outside",
        r"C:\outside",
        "SI/child",
        "json",
        ".an-workbench",
        "a/.private",
        "a/../b",
    ],
)
def test_path_boundaries_and_reserved_directories_cannot_be_selected(library, relative):
    with pytest.raises(ValueError):
        resolve_library_folder(library, relative, must_exist=False)


def test_custom_metadata_directory_is_not_a_category(tmp_path):
    root = tmp_path / "library"
    library = LibraryService(root, root / "private-state")
    assert "private-state" not in {
        row["relative"] for row in scan_library_folders(library)["items"]
    }
    with pytest.raises(ValueError, match="内部数据"):
        resolve_library_folder(library, "private-state")


def test_explicit_creation_makes_only_one_child_and_never_overwrites(library):
    parent = library.root / "电合成"
    parent.mkdir()
    result = create_library_subfolder(library, "电合成", "羧酸还原")
    assert result["created"] and result["relative"] == "电合成/羧酸还原"
    assert result["path"].is_dir() and not list(result["path"].iterdir())
    with pytest.raises(ValueError, match="已经存在"):
        create_library_subfolder(library, "电合成", "羧酸还原")
    original = parent / "keep.txt"
    original.write_bytes(b"immutable existing content")
    with pytest.raises(ValueError, match="已有文件"):
        create_library_subfolder(library, "电合成", "keep.txt")
    assert original.read_bytes() == b"immutable existing content"
    for invalid in ("../escape", "new/child", "SI", "json", "", "CON"):
        with pytest.raises(ValueError):
            create_library_subfolder(library, "电合成", invalid)
    with pytest.raises(ValueError, match="尚不存在"):
        create_library_subfolder(library, "missing-parent", "child")
    assert not (library.root / "missing-parent").exists()


def test_scan_directory_entry_and_depth_limits_are_explicit(library):
    for index in range(7):
        (library.root / f"category-{index}" / "deep").mkdir(parents=True)
    limited = scan_library_folders(library, max_directories=3)
    assert limited["count"] == 3 and limited["truncated"]
    assert any("目录数量上限" in warning for warning in limited["warnings"])
    shallow = scan_library_folders(library, max_depth=1)
    assert shallow["truncated"]
    assert not any("/deep" in row["relative"] for row in shallow["items"])
    assert any("深度上限" in warning for warning in shallow["warnings"])
    entries = scan_library_folders(library, max_entries=2)
    assert entries["entries_examined"] == 2 and entries["truncated"]
    assert any("目录项检查上限" in warning for warning in entries["warnings"])


def test_python311_reparse_attribute_and_link_defense(library, monkeypatch):
    fake_junction = SimpleNamespace(
        is_symlink=lambda: False,
        lstat=lambda: SimpleNamespace(st_file_attributes=0x400),
    )
    assert _is_reparse_point(fake_junction)
    junction = library.root / "junction"
    junction.mkdir()
    from aletheia_nexus.workbench import ui_folders

    original = ui_folders._is_reparse_point
    monkeypatch.setattr(
        ui_folders, "_is_reparse_point", lambda path: path == junction or original(path)
    )
    assert scan_library_folders(library)["skipped"]["links"] == 1
    with pytest.raises(ValueError, match="目录联接"):
        resolve_library_folder(library, "junction")
    with pytest.raises(ValueError, match="目录联接"):
        create_library_subfolder(library, "junction", "no-write")
    assert not (junction / "no-write").exists()


def test_actual_symlink_is_never_traversed_or_used(library, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private-child").mkdir()
    link = library.root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks requires Windows privilege")
    report = scan_library_folders(library)
    assert report["skipped"]["links"] == 1
    assert not any("linked" in row["relative"] for row in report["items"])
    with pytest.raises(ValueError):
        create_library_subfolder(library, "linked", "blocked")
    assert not (outside / "blocked").exists()


@pytest.mark.parametrize("choice", ["existing-empty", ""])
def test_dialog_opens_without_creation_and_scans_through_background_io(
    library, monkeypatch, choice
):
    pytest.importorskip("nicegui")
    from nicegui import run, ui

    scheduled, calls, selected, buttons = [], [], [], {}
    original_button = ui.button

    def capture_button(text="", **kwargs):
        buttons[text] = kwargs.get("on_click")
        return original_button(text, **kwargs)

    monkeypatch.setattr(ui, "button", capture_button)
    monkeypatch.setattr(
        ui, "timer", lambda _interval, callback, **_kwargs: scheduled.append(callback)
    )

    async def io_bound(function, *args, **kwargs):
        calls.append(function.__name__)
        return function(*args, **kwargs)

    monkeypatch.setattr(run, "io_bound", io_bound)
    (library.root / "existing-empty").mkdir()
    before = set(ui.context.client.elements)
    dialog = choose_library_folder(library, selected.append, initial="new-category")
    assert dialog is not None and len(scheduled) == 1
    assert not (library.root / "new-category").exists() and not selected
    asyncio.run(scheduled[0]())
    assert "scan_library_folders" in calls and "resolve_library_folder" in calls
    assert not (library.root / "new-category").exists() and not selected
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    tree = next(element for element in elements if element.tag == "q-tree")
    assert tree.props["nodes"][0]["children"][0]["label"] == "existing-empty"
    relative = next(
        element
        for element in elements
        if element.props.get("label") == "当前目录相对路径（留空为文库根目录）"
    )
    relative.set_value(choice)
    asyncio.run(buttons["使用选中目录"]())
    assert selected == [choice]
    assert not (library.root / "new-category").exists()
