"""Visible group placement controls over the existing ID-based batch editor."""

import inspect
from collections import Counter
from copy import deepcopy

from .acquisition_batch import apply_assignment
from .ui_common import guard, split_tags
from .ui_grids import read_edited_grid


def summarize_input_groups(rows, default_folder=""):
    """Summarize actual destinations, keeping disabled papers visible for edits."""
    groups = {}
    for row in rows:
        name = row.get("input_group") or "未分组"
        group = groups.setdefault(
            name, {"name": name, "ids": [], "enabled": 0, "folders": Counter()}
        )
        group["ids"].append(row["id"])
        group["enabled"] += bool(row.get("enabled"))
        mode = row.get("folder_mode", "inherit")
        if mode == "inherit":
            folder = default_folder or "文库根目录"
        elif mode == "root":
            folder = "文库根目录"
        elif mode == "custom" and row.get("folder"):
            folder = row["folder"]
        else:
            folder = "需修正目录"
        group["folders"][folder] += 1
    return [
        {**group, "count": len(group["ids"]), "folders": dict(group["folders"])}
        for group in groups.values()
    ]


def placement_dialog(
    controller,
    batch,
    ids,
    *,
    rows=None,
    title="保存位置与标签",
    description="",
    is_current=None,
    on_saved=None,
    client=None,
):
    """One placement form for a paper, the selected rows, or an input group."""
    from nicegui import ui

    from .ui_folders import choose_library_folder, resolve_library_folder

    client = (
        client
        or getattr(batch, "client", None)
        or getattr(batch.grid, "client", None)
        or ui.context.client
    )
    ids = list(dict.fromkeys(ids))
    rows = batch.rows if rows is None else rows
    selected = [row for row in rows if row["id"] in ids]
    if not ids or len(selected) != len(ids):
        raise ValueError("选择已变化，请重新勾选需要设置的论文。")
    single = selected[0] if len(selected) == 1 else None
    initial_folder_action = (
        {"inherit": "inherit", "custom": "set", "root": "root"}.get(
            single.get("folder_mode"), "keep"
        )
        if single
        else "keep"
    )
    initial_tag_action = (
        (
            "inherit"
            if single.get("tags_mode") == "inherit"
            else "replace"
            if split_tags(single.get("tags"))
            else "clear"
        )
        if single
        else "keep"
    )
    # The sidebar can refresh while saving. Keep the dialog's lifecycle canary
    # in the stable client layout rather than the disappearing entry button.
    with (
        client.layout,
        ui.dialog() as dialog,
        ui.card().classes("an-card w-[720px] max-w-[95vw]"),
    ):
        ui.label(title).classes("text-xl font-semibold")
        ui.label(description or f"仅修改这 {len(ids)} 篇，不改变是否获取。").classes(
            "an-muted text-sm"
        )
        if single:
            ui.label(single.get("title") or single.get("doi") or "未命名论文").classes(
                "text-sm break-all"
            )
        folder_action = (
            ui.select(
                {
                    "keep": "保持各篇目录",
                    "set": "指定已有 / 新目录",
                    "inherit": "跟随批次默认目录",
                    "root": "文库根目录",
                },
                value=initial_folder_action,
                label="保存目录",
            )
            .props("outlined")
            .classes("w-full")
        )
        folder = (
            ui.input(
                "分类位置（相对文库）",
                value=single.get("folder") or "" if single else "",
            )
            .props("outlined")
            .classes("w-full")
        )
        folder.on_value_change(
            lambda: folder_action.set_value("set") if folder.value else None
        )

        def chosen(relative):
            folder.set_value(relative)
            folder_action.set_value("set" if relative else "root")

        ui.button(
            "选择已有目录 / 新建子目录",
            icon="create_new_folder",
            on_click=guard(
                lambda: choose_library_folder(
                    controller.ctx.library,
                    chosen,
                    initial=folder.value or batch.default_folder() or "",
                )
            ),
        ).props("outline")
        tag_action = (
            ui.select(
                {
                    "keep": "保持各篇标签",
                    "inherit": "跟随批次默认标签",
                    "add": "添加标签",
                    "remove": "移除标签",
                    "replace": "替换为下列标签",
                    "clear": "明确无标签",
                },
                value=initial_tag_action,
                label="标签处理",
            )
            .props("outlined")
            .classes("w-full")
        )
        tags = controller.tag_input(
            "标签（回车添加）", split_tags(single.get("tags")) if single else []
        )
        tags.on_value_change(
            lambda: (
                tag_action.set_value("add")
                if tags.value and tag_action.value == "keep"
                else None
            )
        )
        ui.label(
            "保持各篇设置不会合并目录或标签。根目录和明确无标签是独立设置；跟随默认值会随上方默认改变。"
        ).classes("an-muted text-sm")

        async def save():
            if (is_current and not is_current()) or getattr(
                batch.grid, "is_deleted", False
            ):
                raise ValueError("预览已更新，请重新打开设置后再保存。")
            current = await read_edited_grid(batch.grid)
            if is_current and not is_current():
                raise ValueError("预览已更新，请重新打开设置后再保存。")
            if folder_action.value in {"set", "root"}:
                resolve_library_folder(
                    controller.ctx.library,
                    folder.value if folder_action.value == "set" else "",
                    must_exist=False,
                )
            updated = apply_assignment(
                current,
                ids,
                folder_action=folder_action.value,
                folder=folder.value,
                tag_action=tag_action.value,
                tags=split_tags(tags.value),
                default_folder=batch.default_folder(),
                default_tags=batch.default_tags(),
            )
            await batch.replace(updated)
            if on_saved:
                result = on_saved()
                if inspect.isawaitable(result):
                    await result
            dialog.close()
            with client.layout:
                ui.notify(f"已更新 {len(ids)} 篇的保存设置")

        with ui.row().classes("an-toolbar"):
            ui.button("保存设置", icon="check", on_click=guard(save))
            ui.button("取消", on_click=dialog.close).props("flat")
    dialog.open()
    return dialog


class AcquisitionGroupPanel:
    def __init__(self, controller, get_batch, ensure_preview):
        from nicegui import ui

        self.controller, self.get_batch, self.ensure_preview = (
            controller,
            get_batch,
            ensure_preview,
        )
        self._snapshot = None

        with ui.column().classes("w-full gap-3") as container:
            self.render()
        self.container = container

    def refresh(self, rows=None):
        """Can receive freshly read draft rows without rebuilding the main grid."""
        self._snapshot = (
            (self.get_batch(), deepcopy(rows)) if rows is not None else None
        )
        self.container.clear()
        with self.container:
            self.render()

    def rows(self, batch):
        if self._snapshot is not None and self._snapshot[0] is batch:
            return self._snapshot[1]
        return batch.rows

    async def preview(self):
        result = self.ensure_preview()
        if inspect.isawaitable(result):
            await result
        self.refresh()

    async def apply_group(
        self, batch, ids, *, folder_action="keep", folder="", tag_action="keep", tags=()
    ):
        if self.get_batch() is not batch:
            raise ValueError("预览已更新，请重新打开本组设置后再保存")
        current = await read_edited_grid(batch.grid)
        updated = apply_assignment(
            current,
            ids,
            folder_action=folder_action,
            folder=folder,
            tag_action=tag_action,
            tags=tags,
            default_folder=batch.default_folder(),
            default_tags=batch.default_tags(),
        )
        await batch.replace(updated)
        self.refresh()

    def edit_group(self, batch, group):
        return placement_dialog(
            self.controller,
            batch,
            group["ids"],
            rows=self.rows(batch),
            title=f"分组「{group['name']}」· 保存位置与标签",
            description=f"修改本组 {group['count']} 篇，包含停用论文；不改变是否获取。",
            is_current=lambda: self.get_batch() is batch,
            on_saved=self.refresh,
            client=self.container.client,
        )

    def render(self):
        from nicegui import ui

        ui.label("本批多个目录").classes("font-semibold text-lg")
        batch = self.get_batch()
        if batch is None:
            ui.label("先整理清单，再为不同分组分别选择目录与标签。").classes(
                "an-muted text-sm"
            )
            ui.button(
                "整理清单并设置多个目录",
                icon="account_tree",
                on_click=guard(self.preview),
            ).props("outline").classes("w-full")
            return
        rows = self.rows(batch)
        groups = summarize_input_groups(rows, batch.default_folder())
        if not groups:
            ui.label("清单中尚无可设置的论文，请检查输入。").classes("an-muted text-sm")
            return
        for group in groups:
            with ui.card().classes("an-card w-full p-3 gap-2"):
                ui.label(group["name"]).classes("font-semibold break-all")
                ui.label(
                    f"共 {group['count']} 篇 · 将获取 {group['enabled']} 篇"
                ).classes("an-muted text-sm")
                for folder, count in group["folders"].items():
                    ui.label(f"{folder} · {count} 篇").classes("text-sm break-all")
                ui.button(
                    "设置目录与标签",
                    icon="folder_open",
                    on_click=guard(lambda g=group: self.edit_group(batch, g)),
                ).props("outline dense").classes("w-full")
        with ui.expansion("单篇目录与标签", icon="description").classes("w-full"):
            paper = (
                ui.select(
                    {
                        row["id"]: row.get("title") or row.get("doi") or "未命名论文"
                        for row in rows
                    },
                    value=rows[0]["id"],
                    label="选择本批论文",
                    with_input=True,
                )
                .props("outlined")
                .classes("w-full")
            )
            ui.button(
                "设置本篇", on_click=guard(lambda: batch.open_row(paper.value))
            ).props("outline")


def render_acquisition_groups(controller, get_batch, ensure_preview):
    """Render in the acquisition side card and return refresh(rows=None)."""
    return AcquisitionGroupPanel(controller, get_batch, ensure_preview).refresh
