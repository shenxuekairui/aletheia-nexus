"""Bounded category browsing and explicit creation within an authorized library."""

from __future__ import annotations

import inspect
import os
import stat
from collections import deque
from pathlib import Path

from aletheia_nexus.core.organization import normalize_folder

_INTERNAL = {
    "si",
    "json",
    ".an-workbench",
    ".aletheia-nexus",
    ".git",
    "__pycache__",
    "_unverified",
    "_browser-downloads",
    "_tmp",
}


def _is_reparse_point(path):
    # st_file_attributes also covers Windows junctions on Python 3.11, which
    # does not yet provide Path.is_junction(). Never resolve such a directory.
    return path.is_symlink() or bool(
        getattr(path.lstat(), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _relative(value):
    if value is None or value == "":
        return ""
    return normalize_folder(value)


def resolve_library_folder(library, relative, *, must_exist=True):
    """Return a checked Path and existence; this never creates a directory."""
    relative = _relative(relative)
    parts = relative.split("/") if relative else []
    if any(part.casefold() in _INTERNAL or part.startswith(".") for part in parts):
        raise ValueError("请选择文献分类目录，不能使用 SI、json 或内部目录。")
    root = Path(library.root)
    candidate = root.joinpath(*parts)
    for part in (candidate, *candidate.parents):
        try:
            if _is_reparse_point(part):
                raise ValueError("分类目录不能经过符号链接或 Windows 目录联接。")
        except FileNotFoundError:
            pass
        if part == root:
            break
    target = Path(library.path(candidate))
    if not target.is_relative_to(root):
        raise ValueError("分类目录必须位于当前文库根目录内。")
    state = Path(getattr(library, "state_dir", root / ".an-workbench")).resolve()
    if state != root and target.is_relative_to(state):
        raise ValueError("不能将工作台内部数据目录用作文献分类。")
    exists = target.exists()
    if exists and not target.is_dir():
        raise ValueError("此路径是已有文件，不能用作分类目录。")
    if must_exist and not exists:
        raise ValueError("所选分类目录尚不存在，请选择已有目录或明确新建子目录。")
    return {"relative": relative, "path": target, "exists": exists}


def create_library_subfolder(library, parent, name):
    """Create exactly one child only after explicit user action; never overwrite."""
    checked_parent = resolve_library_folder(library, parent)
    child = normalize_folder(name)
    if child is None or "/" in child:
        raise ValueError("子目录名称请填写一级名称；多层分类可逐级创建。")
    relative = "/".join(filter(None, (checked_parent["relative"], child)))
    target = resolve_library_folder(library, relative, must_exist=False)
    if target["exists"]:
        raise ValueError("该子目录已经存在，请直接选择已有目录。")
    # Revalidate the parent immediately before mkdir. Parents are not created
    # implicitly, and an existing file or directory always raises instead.
    resolve_library_folder(library, checked_parent["relative"])
    target["path"].mkdir(exist_ok=False)
    return {**resolve_library_folder(library, relative), "created": True}


def scan_library_folders(
    library, *, max_directories=1000, max_depth=24, max_entries=20000
):
    """List directory metadata only, including empty categories, with hard bounds."""
    for value, ceiling in (
        (max_directories, 10000),
        (max_depth, 64),
        (max_entries, 100000),
    ):
        if type(value) is not int or not 1 <= value <= ceiling:
            raise ValueError("目录扫描上限必须是允许范围内的正整数。")
    root = resolve_library_folder(library, "")["path"]
    root_node = {
        "id": "dir:",
        "label": "文库根目录",
        "icon": "folder_special",
        "relative": "",
        "children": [],
    }
    report = {
        "root": str(root),
        "nodes": [root_node],
        "items": [{"relative": "", "path": str(root)}],
        "count": 1,
        "entries_examined": 0,
        "truncated": False,
        "warnings": [],
        "skipped": {"links": 0, "internal_or_invalid": 0, "unreadable": 0},
        "limits": {
            "directories": max_directories,
            "depth": max_depth,
            "entries": max_entries,
        },
    }
    pending = deque([(root, root_node, 0)])

    def warning(message):
        if message not in report["warnings"] and len(report["warnings"]) < 20:
            report["warnings"].append(message)

    stopped = False
    while pending and not stopped:
        directory, parent_node, depth = pending.popleft()
        if depth >= max_depth:
            report["truncated"] = True
            warning(
                f"已达到目录深度上限 {max_depth}，更深层尚未检查；可手填已有相对路径。"
            )
            continue
        try:
            # Refuse a directory replaced by a junction after initial discovery.
            resolve_library_folder(library, parent_node["relative"])
            with os.scandir(directory) as entries:
                for entry in entries:
                    if report["entries_examined"] >= max_entries:
                        report["truncated"] = stopped = True
                        warning(
                            f"已达到目录项检查上限 {max_entries}；列表不是完整文库，可手填已有相对路径。"
                        )
                        break
                    report["entries_examined"] += 1
                    path = Path(entry.path)
                    try:
                        if _is_reparse_point(path):
                            report["skipped"]["links"] += 1
                            continue
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        relative = path.relative_to(root).as_posix()
                        try:
                            checked = resolve_library_folder(library, relative)
                        except ValueError:
                            report["skipped"]["internal_or_invalid"] += 1
                            continue
                        if report["count"] >= max_directories:
                            report["truncated"] = stopped = True
                            warning(
                                f"已达到目录数量上限 {max_directories}；列表不是完整文库，可手填已有相对路径。"
                            )
                            break
                        node = {
                            "id": "dir:" + relative,
                            "label": entry.name,
                            "icon": "folder",
                            "relative": relative,
                            "children": [],
                        }
                        parent_node["children"].append(node)
                        report["items"].append(
                            {"relative": relative, "path": str(checked["path"])}
                        )
                        report["count"] += 1
                        pending.append((checked["path"], node, depth + 1))
                    except OSError:
                        report["skipped"]["unreadable"] += 1
        except (OSError, ValueError):
            report["skipped"]["unreadable"] += 1
            warning("部分目录无法读取或已发生变化；未确认的目录不会被当作可用分类。")

    def sort_nodes(node):
        node["children"].sort(key=lambda child: child["label"].casefold())
        for child in node["children"]:
            sort_nodes(child)

    sort_nodes(root_node)
    return report


def choose_library_folder(library, on_choose, initial=""):
    """Open a local folder dialog; callback receives a relative str (root='')."""
    from nicegui import run, ui

    from .messages import user_message
    from .ui_common import guard

    with ui.dialog() as dialog, ui.card().classes("w-[850px] max-w-[96vw] an-card"):
        ui.label("选择或新建分类目录").classes("text-xl font-semibold")
        ui.label(f"当前文库：{library.root}").classes("an-muted text-xs break-all")
        status = ui.label("正在读取现有目录；不会读取 PDF 内容…").classes(
            "an-info w-full"
        )
        search = (
            ui.input("查找已有目录").props("clearable outlined dense").classes("w-full")
        )
        relative = ui.input(
            "分类位置（留空为文库根目录）", value=initial or ""
        ).classes("w-full")
        selected_path = ui.label("").classes("text-sm whitespace-pre-wrap break-all")
        state = {"revision": 0, "busy": False, "loaded": {""}}

        def selected(event):
            if event.value is not None:
                relative.set_value(event.value.removeprefix("dir:"))

        tree = ui.tree([], on_select=selected).classes("w-full max-h-72 overflow-auto")
        tree.bind_filter_from(search, "value")
        search.on_value_change(lambda _: tree.expand())
        with ui.row().classes("an-toolbar"):

            def parent():
                path = _relative(relative.value)
                relative.set_value(path.rsplit("/", 1)[0] if "/" in path else "")

            ui.button(
                "上一级目录", icon="drive_folder_upload", on_click=guard(parent)
            ).props("flat")
            ui.button("文库根目录", on_click=lambda: relative.set_value("")).props(
                "flat"
            )
        child = ui.input("新建子目录名称").classes("w-full")
        new_path = ui.label("").classes(
            "an-muted text-sm whitespace-pre-wrap break-all"
        )

        async def deliver(info):
            result = on_choose(info["relative"])
            if inspect.isawaitable(result):
                await result
            dialog.close()

        async def use_existing():
            info = await run.io_bound(resolve_library_folder, library, relative.value)
            await deliver(info)

        async def create():
            state["busy"] = True
            use_button.disable()
            create_button.disable()
            try:
                info = await run.io_bound(
                    create_library_subfolder, library, relative.value, child.value
                )
                await deliver(info)
            finally:
                state["busy"] = False
                await preview()

        with ui.row().classes("an-toolbar"):
            use_button = ui.button(
                "使用选中目录", icon="folder", on_click=guard(use_existing)
            )
            create_button = ui.button(
                "新建子目录并使用", icon="create_new_folder", on_click=guard(create)
            )
            ui.button("取消", on_click=dialog.close).props("flat")
        use_button.disable()
        create_button.disable()

        async def preview():
            state["revision"] += 1
            revision = state["revision"]
            use_button.disable()
            create_button.disable()
            info = None
            selected_path.set_text("正在校验当前目录…")
            new_path.set_text("")
            try:
                info = await run.io_bound(
                    resolve_library_folder, library, relative.value, must_exist=False
                )
                if revision != state["revision"]:
                    return
                if info["exists"] and info["relative"] in state["loaded"]:
                    tree.select("dir:" + info["relative"])
                    pieces = info["relative"].split("/") if info["relative"] else []
                    tree.expand(
                        [
                            "dir:",
                            *(
                                "dir:" + "/".join(pieces[:i])
                                for i in range(1, len(pieces))
                            ),
                        ]
                    )
                else:
                    tree.deselect()
                selected_path.set_text(
                    f"当前选择：{info['relative'] or '文库根目录'}\n{info['path']}"
                )
                if not info["exists"]:
                    selected_path.set_text(
                        selected_path.text + "\n此目录尚不存在；选择操作不会创建目录。"
                    )
                use_button.set_enabled(info["exists"] and not state["busy"])
                new_path.set_text("")
                if child.value:
                    child_name = normalize_folder(child.value)
                    if "/" in child_name:
                        raise ValueError(
                            "子目录名称请填写一级名称；多层分类可逐级创建。"
                        )
                    new_relative = "/".join(
                        filter(None, (info["relative"], child_name))
                    )
                    future = await run.io_bound(
                        resolve_library_folder, library, new_relative, must_exist=False
                    )
                    if revision != state["revision"]:
                        return
                    new_path.set_text(
                        f"新建后路径：{future['relative']}\n{future['path']}"
                        + (
                            "\n该目录已存在，请直接选择。"
                            if future["exists"]
                            else "\n仅点击“新建子目录并使用”才会创建。"
                        )
                    )
                    create_button.set_enabled(
                        info["exists"] and not future["exists"] and not state["busy"]
                    )
            except (ValueError, OSError) as exc:
                if revision == state["revision"]:
                    if info is None:
                        selected_path.set_text("当前路径不能用作分类目录。")
                    new_path.set_text(user_message(exc))

        async def load():
            report = await run.io_bound(scan_library_folders, library)
            state["loaded"] = {item["relative"] for item in report["items"]}
            tree.props["nodes"] = report["nodes"]
            tree.expand(None if search.value else ["dir:"])
            tree.select("dir:" + (initial or ""))
            status.set_text(
                f"显示 {report['count'] - 1} 个分类（含空目录）。选择一个已有目录，或在其下新建子目录。"
            )
            if report["truncated"] or report["warnings"]:
                status.set_text(status.text + "\n" + "\n".join(report["warnings"]))
            await preview()

        relative.on_value_change(guard(preview))
        child.on_value_change(guard(preview))
        ui.timer(0.01, guard(load), once=True)
    dialog.open()
    return dialog
