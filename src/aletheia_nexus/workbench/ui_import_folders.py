"""Read-only, explicitly navigated source-folder selection for local imports."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

from .ui_folders import _is_reparse_point


def _windows_drives():
    """Read the OS drive inventory without probing every possible drive path."""
    listdrives = getattr(os, "listdrives", None)
    if listdrives is not None:
        return list(listdrives())
    import ctypes

    get_drives = ctypes.windll.kernel32.GetLogicalDrives
    get_drives.restype = ctypes.c_uint32
    get_drives.argtypes = []
    mask = get_drives()
    return [f"{chr(65 + index)}:\\" for index in range(26) if mask & (1 << index)]


def import_folder_locations():
    """List shortcut names only; no stat, scan, cookie or file-content reads."""
    home = Path.home()
    places = [
        {"label": "用户主目录", "path": str(home)},
        {"label": "下载文件夹", "path": str(home / "Downloads")},
        {"label": "文档文件夹", "path": str(home / "Documents")},
        {"label": "桌面", "path": str(home / "Desktop")},
    ]
    if os.name == "nt":
        try:
            places.extend(
                {"label": f"磁盘 {drive.rstrip(chr(92))}", "path": drive}
                for drive in _windows_drives()
            )
        except (OSError, AttributeError):
            # The home path is still a usable entry if OS inventory is unavailable.
            pass
    else:
        places.append({"label": "文件系统根目录", "path": "/"})
    return list({item["path"]: item for item in places}.values())


def _existing_import_path(value):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("请选择一个已有的来源文件夹。")
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if not text:
        raise ValueError("请选择一个已有的来源文件夹。")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError("来源位置需要本机绝对路径，请使用常用位置或磁盘按钮选择。")
    try:
        for part in (path, *path.parents):
            if _is_reparse_point(part):
                raise ValueError("来源文件夹不能经过符号链接或 Windows 目录联接。")
        return path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("来源文件夹已不存在，请返回上级或选择其他位置。") from exc
    except PermissionError as exc:
        raise ValueError("没有读取这个文件夹的权限，请选择可访问的位置。") from exc
    except OSError as exc:
        raise ValueError(
            "暂时无法访问这个文件夹，请检查磁盘或网络位置后重试。"
        ) from exc


def resolve_import_folder(value):
    """Check an existing real directory; never create or traverse linked paths."""
    path = _existing_import_path(value)
    if not path.is_dir():
        raise ValueError("所选位置不是文件夹，请选择一个已有目录。")
    return path


def initial_import_folder(initial=""):
    """Use a valid initial directory; unavailable initial paths fall back visibly."""
    warning = ""
    if initial:
        try:
            path = _existing_import_path(initial)
            if path.is_file():
                path = path.parent
            return {"path": str(resolve_import_folder(path)), "warning": warning}
        except ValueError:
            warning = "原来源位置不可用，已改为显示用户主目录或本机根目录。"
    for candidate in (Path.home(), Path(Path.home().anchor)):
        try:
            return {"path": str(resolve_import_folder(candidate)), "warning": warning}
        except ValueError:
            continue
    raise ValueError("无法打开默认位置，请检查本机文件夹访问权限。")


def list_import_folders(value, *, offset=0, limit=200, max_entries=4000):
    """Read one directory segment, without recursion or opening any files.

    offset counts directory entries, including files. A bounded segment with no
    folders can still have a next segment; this avoids unbounded scanning when a
    source contains many thousands of files. Reparse points are never entered.
    """
    if type(offset) is not int or offset < 0:
        raise ValueError("文件夹分页位置必须是非负整数。")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("每页文件夹数量必须是 1 到 200 之间的整数。")
    if type(max_entries) is not int or not 1 <= max_entries <= 10000:
        raise ValueError("单次目录项检查数量必须是 1 到 10000 之间的整数。")
    path = resolve_import_folder(value)
    items, examined, skipped = [], 0, 0
    next_offset = None
    try:
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries):
                if index < offset:
                    continue
                if len(items) >= limit or examined >= max_entries:
                    next_offset = index
                    break
                examined += 1
                try:
                    if entry.is_symlink():
                        skipped += 1
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    candidate = Path(entry.path)
                    if _is_reparse_point(candidate):
                        skipped += 1
                        continue
                    items.append({"name": entry.name, "path": str(candidate)})
                except OSError:
                    skipped += 1
    except PermissionError as exc:
        raise ValueError(
            "没有读取这个文件夹的权限，请返回上级或选择其他位置。"
        ) from exc
    except FileNotFoundError as exc:
        raise ValueError("来源文件夹已消失，请返回上级或重新选择。") from exc
    except OSError as exc:
        raise ValueError(
            "无法列出这个文件夹，请检查磁盘、网络位置或访问权限。"
        ) from exc
    items.sort(key=lambda item: item["name"].casefold())
    return {
        "path": str(path),
        "parent": str(path.parent) if path.parent != path else None,
        "items": items,
        "offset": offset,
        "next_offset": next_offset,
        "has_more": next_offset is not None,
        "examined": examined,
        "skipped": skipped,
    }


def choose_import_folder(on_select, *, initial=""):
    """Open a picker; only an explicit choice delivers an absolute local path."""
    from nicegui import run, ui

    from .ui_common import guard

    if not callable(on_select):
        raise ValueError("选择文件夹后需要一个有效的接收操作。")
    state = {
        "revision": 0,
        "path": "",
        "report": None,
        "history": [],
        "busy": False,
        "closed": False,
        "delivering": False,
    }
    with ui.dialog() as dialog, ui.card().classes("w-[820px] max-w-[96vw] an-card"):
        ui.label("从电脑选择导入来源文件夹").classes("text-xl font-semibold")
        ui.label(
            "点击磁盘或常用位置，进入目标文件夹后，点击“选择当前文件夹”。"
        ).classes("an-muted text-sm")
        with ui.row().classes("an-toolbar w-full flex-wrap"):
            for location in import_folder_locations():
                ui.button(
                    location["label"],
                    icon="folder_open",
                    on_click=guard(lambda p=location["path"]: load(p)),
                ).props("outline dense")
        current = ui.label("正在定位来源文件夹…").classes("text-sm break-all")
        status = ui.label("").classes("an-info w-full text-sm whitespace-pre-wrap")
        with ui.row().classes("an-toolbar"):
            parent = ui.button(
                "上一级文件夹",
                icon="arrow_upward",
                on_click=guard(lambda: load(parent_path())),
            ).props("outline")
            previous = ui.button(
                "上一页",
                icon="chevron_left",
                on_click=guard(
                    lambda: load(
                        state["path"], state["history"][-1], state["history"][:-1]
                    )
                ),
            ).props("flat")
            following = ui.button(
                "更多文件夹",
                icon="chevron_right",
                on_click=guard(
                    lambda: load(
                        state["path"],
                        state["report"]["next_offset"],
                        [*state["history"], state["report"]["offset"]],
                    )
                ),
            ).props("flat")
        folders = ui.column().classes("w-full max-h-80 overflow-auto gap-1")

        def parent_path():
            if state["report"] is not None:
                return state["report"]["parent"]
            if state["path"]:
                path = Path(state["path"])
                return str(path.parent) if path.parent != path else None
            return None

        def controls():
            ready = (
                state["report"] is not None
                and not state["busy"]
                and not state["closed"]
            )
            select.set_enabled(ready and not state["delivering"])
            parent.set_enabled(
                not state["busy"] and not state["closed"] and parent_path() is not None
            )
            previous.set_enabled(ready and bool(state["history"]))
            following.set_enabled(ready and state["report"]["has_more"])

        async def load(path, offset=0, history=None):
            if state["closed"] or not path:
                return
            state["revision"] += 1
            revision = state["revision"]
            state.update(
                busy=True, report=None, path=str(path), history=list(history or [])
            )
            controls()
            current.set_text(f"来源位置：{path}")
            status.set_text("正在读取当前层级的文件夹…")
            folders.clear()
            try:
                report = await run.io_bound(list_import_folders, path, offset=offset)
                if state["closed"] or revision != state["revision"]:
                    return
                state.update(report=report, path=report["path"])
                current.set_text(f"来源位置：{report['path']}")
                status.set_text(
                    f"本页显示 {len(report['items'])} 个文件夹。"
                    + (
                        "还有后续目录项，可点击“更多文件夹”。"
                        if report["has_more"]
                        else ""
                    )
                    + (
                        f"已跳过 {report['skipped']} 个链接或不可读取目录。"
                        if report["skipped"]
                        else ""
                    )
                )
                with folders:
                    if not report["items"]:
                        ui.label(
                            "本页没有子文件夹；可以选择当前文件夹。"
                            if not report["has_more"]
                            else "本页没有子文件夹，可继续查看后续目录项。"
                        ).classes("an-muted")
                    for item in report["items"]:
                        ui.button(
                            item["name"],
                            icon="folder",
                            on_click=guard(lambda p=item["path"]: load(p)),
                        ).props("flat align=left").classes("w-full justify-start")
            except ValueError as exc:
                if not state["closed"] and revision == state["revision"]:
                    status.set_text(str(exc))
            finally:
                if revision == state["revision"]:
                    state["busy"] = False
                    controls()

        async def choose():
            if (
                state["busy"]
                or state["closed"]
                or state["delivering"]
                or state["report"] is None
            ):
                return
            state["delivering"] = True
            revision = state["revision"]
            controls()
            try:
                checked = await run.io_bound(resolve_import_folder, state["path"])
                if state["closed"] or revision != state["revision"]:
                    return
                result = on_select(str(checked))
                if inspect.isawaitable(result):
                    await result
                close()
            finally:
                state["delivering"] = False
                controls()

        def invalidate():
            state["closed"] = True
            state["revision"] += 1
            controls()

        def close():
            invalidate()
            dialog.close()

        with ui.row().classes("an-toolbar w-full justify-end"):
            ui.button("取消", on_click=close).props("flat")
            select = ui.button("选择当前文件夹", icon="check", on_click=guard(choose))
        controls()

        async def start():
            revision = state["revision"]
            info = await run.io_bound(initial_import_folder, initial)
            if state["closed"] or revision != state["revision"]:
                return
            await load(info["path"])
            if (
                info["warning"]
                and not state["closed"]
                and state["revision"] == revision + 1
            ):
                status.set_text(info["warning"] + "\n" + status.text)

        ui.timer(0.01, guard(start), once=True)
        dialog.on("hide", lambda _: invalidate())
    dialog.open()
    return dialog
