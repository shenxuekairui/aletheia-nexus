"""Selection-based placement editing before the existing acquisition workflow."""

from .acquisition_batch import apply_assignment, build_requests
from .ui_common import guard, rows_table, split_tags
from .ui_grids import read_edited_grid

FOLDER_MODES = {"inherit": "跟随批次默认", "custom": "指定分类", "root": "文库根目录"}
TAG_MODES = {"inherit": "跟随批次默认", "custom": "单独设置（可为空）"}


class AcquisitionBatchEditor:
    def __init__(
        self, controller, grid, report, default_folder, default_tags, save_draft=None
    ):
        self.controller = controller
        self.grid = grid
        self.report = report
        self.default_folder = default_folder
        self.default_tags = default_tags
        self.save_draft = save_draft
        self.rows = [dict(row) for row in grid.options["rowData"]]
        self.originals = {
            entry["id"]: entry["request"]
            for entry in report["items"]
            if not entry["duplicate"]
        }

    def decorate(self, rows):
        from .ui_folders import resolve_library_folder

        result = [dict(row) for row in rows]
        for row in result:
            try:
                probe = {**row, "enabled": True}
                request = build_requests(
                    [probe],
                    {row["id"]: self.originals[row["id"]]},
                    self.default_folder(),
                    self.default_tags(),
                )[0]
                location = resolve_library_folder(
                    self.controller.ctx.library,
                    request.get("folder") or "",
                    must_exist=False,
                )
                # Directory metadata only: never load PDF contents for a preview.
                row.update(
                    effective_folder=request.get("folder") or "文库根目录",
                    effective_tags=", ".join(request.get("tags") or []) or "无标签",
                    placement_state="已有目录" if location["exists"] else "下载时新建",
                    placement_error="",
                )
            except (ValueError, TypeError, OSError) as exc:
                row.update(
                    effective_folder="需修正",
                    effective_tags="需修正",
                    placement_state="设置无效",
                    placement_error=str(exc),
                )
        return result

    async def replace(self, rows):
        rows = self.decorate(rows)
        self.rows = rows
        await self.grid.run_grid_method("setGridOption", "rowData", rows)
        if self.save_draft:
            self.save_draft(rows)
        await self.refresh_count()

    async def refresh(self):
        await self.replace(await read_edited_grid(self.grid))

    async def refresh_count(self):
        selected = await self.grid.get_selected_rows()
        rows = await read_edited_grid(self.grid)
        self.count.set_text(
            f"已选中 {len(selected)} 行用于编辑 · 将获取 {sum(bool(r['enabled']) for r in rows)} 篇 / 共 {len(rows)} 篇"
        )

    async def requests(self):
        from .ui_folders import resolve_library_folder

        rows = await read_edited_grid(self.grid)
        if self.save_draft:
            self.save_draft(rows)
        requests = build_requests(
            rows, self.originals, self.default_folder(), self.default_tags()
        )
        if not requests:
            raise ValueError("没有启用的论文，请先启用需要获取的项目")
        for row in rows:
            if (
                row.get("enabled")
                and not row.get("doi")
                and row.get("resolution") == "待解析标题"
            ):
                raise ValueError("请先解析并确认无 DOI 标题，避免错误关联")
        # Include manually typed paths in the same checks as the directory picker.
        for request in requests:
            resolve_library_folder(
                self.controller.ctx.library,
                request.get("folder") or "",
                must_exist=False,
            )
        return requests

    def render_tools(self):
        from nicegui import ui

        from .ui_folders import choose_library_folder

        ui.label("3 · 逐篇安排目录与标签").classes("font-semibold text-lg")
        ui.label(
            "左侧复选框选择要编辑的行；启用 / 停用决定是否下载。双击目录或标签，可选择已有目录、新建子目录和设置标签。"
        ).classes("an-muted text-sm")
        self.count = ui.label().classes("an-info w-full")
        with ui.row().classes("an-toolbar w-full"):
            groups = list(
                dict.fromkeys(
                    r.get("input_group", "未分组") for r in self.grid.options["rowData"]
                )
            )
            group = (
                ui.select(
                    {"": "全部分组", **{g: g for g in groups}},
                    value="",
                    label="按输入分组查看",
                )
                .props("outlined dense")
                .classes("min-w-[220px]")
            )

            async def filter_group():
                await self.grid.run_grid_method(
                    "setFilterModel",
                    {
                        "input_group": {
                            "filterType": "text",
                            "type": "equals",
                            "filter": group.value,
                        }
                    }
                    if group.value
                    else None,
                )

            group.on_value_change(guard(filter_group))
            search = (
                ui.input("在本批查找 DOI、标题或标签")
                .props("outlined dense clearable")
                .classes("grow")
            )
            search.on_value_change(
                guard(
                    lambda: self.grid.run_grid_method(
                        "setGridOption", "quickFilterText", search.value or ""
                    )
                )
            )

            async def select_filtered():
                await self.grid.run_grid_method("deselectAll")
                await self.grid.run_grid_method("selectAll", "filtered")

            ui.button("选择当前筛选", on_click=guard(select_filtered)).props("outline")
            ui.button(
                "取消选择",
                on_click=guard(lambda: self.grid.run_grid_method("deselectAll")),
            ).props("flat")

        with ui.card().classes("an-card w-full"):
            ui.label("批量应用到选中行").classes("font-semibold")
            with ui.row().classes("an-toolbar w-full"):
                folder_action = (
                    ui.select(
                        {
                            "keep": "保持各篇目录",
                            "set": "指定已有 / 新目录",
                            "inherit": "跟随批次默认目录",
                            "root": "文库根目录",
                        },
                        value="keep",
                        label="目录操作",
                    )
                    .props("outlined dense")
                    .classes("min-w-[210px]")
                )
                folder = (
                    ui.input("批量目标分类（相对文库）")
                    .props("outlined dense")
                    .classes("grow")
                )
                folder.on_value_change(
                    lambda: folder_action.set_value("set") if folder.value else None
                )

                def chosen(relative):
                    folder.set_value(relative)
                    folder_action.set_value("set" if relative else "root")

                ui.button(
                    "选已有 / 新建目录",
                    icon="create_new_folder",
                    on_click=guard(
                        lambda: choose_library_folder(
                            self.controller.ctx.library,
                            chosen,
                            initial=folder.value or "",
                        )
                    ),
                ).props("outline")
            with ui.row().classes("an-toolbar w-full"):
                tag_action = (
                    ui.select(
                        {
                            "keep": "保持各篇标签",
                            "replace": "替换为这些标签",
                            "add": "追加标签",
                            "remove": "移除这些标签",
                            "clear": "明确无标签",
                            "inherit": "跟随批次默认标签",
                        },
                        value="keep",
                        label="标签操作",
                    )
                    .props("outlined dense")
                    .classes("min-w-[210px]")
                )
                tags = (
                    ui.input("批量标签（逗号分隔）")
                    .props("outlined dense")
                    .classes("grow")
                )
                tags.on_value_change(
                    lambda: (
                        tag_action.set_value("add")
                        if tags.value and tag_action.value == "keep"
                        else None
                    )
                )

                async def apply():
                    rows = await read_edited_grid(self.grid)
                    selected = [r["id"] for r in await self.grid.get_selected_rows()]
                    if not selected:
                        raise ValueError("请先勾选需要编辑的论文；不会默认修改整批")
                    updated = apply_assignment(
                        rows,
                        selected,
                        folder_action=folder_action.value,
                        folder=folder.value,
                        tag_action=tag_action.value,
                        tags=split_tags(tags.value),
                        default_folder=self.default_folder(),
                        default_tags=self.default_tags(),
                    )
                    await self.replace(updated)
                    folder.set_value("")
                    tags.set_value("")
                    folder_action.set_value("keep")
                    tag_action.set_value("keep")
                    ui.notify(f"已更新选中的 {len(selected)} 篇；尚未开始下载")

                ui.button("应用到选中行", icon="done_all", on_click=guard(apply)).props(
                    "outline"
                )
            with ui.row().classes("an-toolbar w-full"):

                async def set_enabled(enabled):
                    rows = await read_edited_grid(self.grid)
                    selected = {r["id"] for r in await self.grid.get_selected_rows()}
                    if not selected:
                        raise ValueError("请先勾选需要修改获取开关的论文")
                    for row in rows:
                        if row["id"] in selected:
                            row["enabled"] = enabled
                    await self.replace(rows)

                ui.button(
                    "启用选中论文", on_click=guard(lambda: set_enabled(True))
                ).props("flat")
                ui.button(
                    "停用选中论文", on_click=guard(lambda: set_enabled(False))
                ).props("flat")
                ui.button(
                    "单篇目录 / 标签", icon="edit", on_click=guard(self.open_row)
                ).props("flat")
                ui.button(
                    "刷新最终目录与标签", icon="refresh", on_click=guard(self.refresh)
                ).props("flat")
        self.grid.on("selectionChanged", guard(self.refresh_count))
        self.grid.on("cellValueChanged", guard(self.refresh))
        with ui.expansion("逐篇命名与诊断（高级）", icon="tune").classes("w-full"):
            details = ui.checkbox("显示单篇文件名、身份阶段和设置诊断列", value=False)
            ui.label(
                "展开列后可直接编辑单篇文件基础名；留空使用上方统一命名模板。"
            ).classes("an-muted text-sm")
            details.on_value_change(
                guard(
                    lambda: self.grid.run_grid_method(
                        "setColumnsVisible",
                        ["filename", "resolution", "placement_error"],
                        bool(details.value),
                    )
                )
            )

    async def open_row(self, row_id=None):
        from nicegui import ui

        from .ui_folders import choose_library_folder

        rows = await read_edited_grid(self.grid)
        if row_id is None:
            selected = await self.grid.get_selected_rows()
            if len(selected) != 1:
                raise ValueError("请选择一篇论文，或双击需要设置的行")
            row_id = selected[0]["id"]
        row = next(r for r in rows if r["id"] == row_id)
        with ui.dialog() as dialog, ui.card().classes("an-card w-[760px] max-w-[95vw]"):
            ui.label("本篇保存目录与标签").classes("text-xl font-semibold")
            ui.label(row.get("title") or row.get("doi") or "未命名论文").classes(
                "break-all"
            )
            mode = ui.select(
                FOLDER_MODES, value=row["folder_mode"], label="目录方式"
            ).classes("w-full")
            folder = ui.input(
                "本篇分类（相对文库根目录）", value=row.get("folder") or ""
            ).classes("w-full")

            def chosen(relative):
                folder.set_value(relative)
                mode.set_value("custom" if relative else "root")

            ui.button(
                "选已有目录 / 新建子目录",
                icon="create_new_folder",
                on_click=guard(
                    lambda: choose_library_folder(
                        self.controller.ctx.library, chosen, initial=folder.value or ""
                    )
                ),
            ).props("outline")
            tag_mode = ui.select(
                TAG_MODES, value=row["tags_mode"], label="标签方式"
            ).classes("w-full")
            tags = self.controller.tag_input(
                "本篇标签（回车添加；自定义可留空）", split_tags(row.get("tags"))
            )
            ui.label(
                "目录和标签均可明确独立设置；无标签不会重新套用批次默认标签。"
            ).classes("an-muted text-sm")

            async def save():
                current = await read_edited_grid(self.grid)
                updated = apply_assignment(
                    current,
                    [row_id],
                    folder_action={
                        "inherit": "inherit",
                        "root": "root",
                        "custom": "set",
                    }[mode.value],
                    folder=folder.value,
                    tag_action="inherit" if tag_mode.value == "inherit" else "replace",
                    tags=split_tags(tags.value),
                    default_folder=self.default_folder(),
                    default_tags=self.default_tags(),
                )
                await self.replace(updated)
                dialog.close()

            with ui.row().classes("an-toolbar"):
                ui.button("保存本篇设置", on_click=guard(save))
                ui.button("取消", on_click=dialog.close).props("flat")
        dialog.open()

    def confirm(self, requests, on_confirm, *, include_si):
        from nicegui import ui

        from .ui_folders import resolve_library_folder

        rows = []
        for i, request in enumerate(requests):
            target = resolve_library_folder(
                self.controller.ctx.library,
                request.get("folder") or "",
                must_exist=False,
            )
            rows.append(
                {
                    "id": str(i),
                    "doi": request.get("doi") or "",
                    "title": request.get("title") or "",
                    "folder": request.get("folder") or "文库根目录",
                    "full_path": str(target["path"]),
                    "status": "已有目录" if target["exists"] else "下载时新建",
                    "tags": ", ".join(request.get("tags") or []) or "无标签",
                    "si_folder": "/".join(filter(None, (request.get("folder"), "SI")))
                    if include_si
                    else "本次不获取 SI",
                    "full_si_path": str(target["path"] / "SI")
                    if include_si
                    else "本次不获取 SI",
                }
            )
        with (
            ui.dialog() as dialog,
            ui.card().classes("an-card w-[1450px] max-w-[96vw]"),
        ):
            ui.label(f"确认本批保存安排 · {len(rows)} 篇论文").classes(
                "text-xl font-semibold"
            )
            ui.label(
                "正文放各自目标目录根部；SI 共用对应分类的 SI/。请核对逐篇目录和标签，再开始获取。"
            ).classes("an-info")
            ui.label(f"文库：{self.controller.ctx.library.root}").classes(
                "an-muted text-sm break-all"
            )
            if self.report.get("errors"):
                ui.label(
                    f"原输入有 {len(self.report['errors'])} 项错误未纳入本批，请返回修正或明确只获取下列有效条目。"
                ).classes("text-orange-9")
            rows_table(
                rows,
                columns=[
                    {
                        "name": k,
                        "field": k,
                        "label": label,
                        "align": "left",
                        "sortable": True,
                        "style": "white-space:pre-wrap;min-width:140px;max-width:400px;overflow-wrap:anywhere",
                    }
                    for k, label in (
                        ("doi", "DOI"),
                        ("title", "标题"),
                        ("folder", "正文保存目录"),
                        ("status", "目录状态"),
                        ("tags", "实际标签"),
                        ("si_folder", "统一 SI 目录"),
                    )
                    if k != "title" or any(r["title"] for r in rows)
                ],
            )
            with ui.expansion("查看完整保存路径", icon="folder_open").classes("w-full"):
                rows_table(
                    rows,
                    columns=[
                        {
                            "name": k,
                            "field": k,
                            "label": label,
                            "style": "white-space:pre-wrap;max-width:600px;overflow-wrap:anywhere",
                        }
                        for k, label in (
                            ("doi", "DOI"),
                            ("full_path", "正文完整目录"),
                            ("full_si_path", "SI 完整目录"),
                        )
                    ],
                )
            submitted = False

            def submit():
                nonlocal submitted
                if submitted:
                    return
                on_confirm()
                submitted = True
                dialog.close()

            with ui.row().classes("an-toolbar"):
                ui.button(
                    f"确认并获取 {len(rows)} 篇",
                    icon="download",
                    on_click=guard(submit),
                )
                ui.button("返回修改", on_click=dialog.close).props("flat")
        dialog.open()
