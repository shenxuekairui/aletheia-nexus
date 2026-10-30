"""Selection-based placement editing before the existing acquisition workflow."""

from .acquisition_batch import build_requests
from .ui_common import guard, rows_table
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
        self.client = getattr(grid, "client", None)
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
            f"本批将获取 {sum(bool(r['enabled']) for r in rows)} 篇 · 已选 {len(selected)} 篇用于修改"
        )
        button = getattr(self, "placement_button", None)
        if button is not None:
            button.set_text(f"设置所选 {len(selected)} 篇")
            button.set_enabled(bool(selected))

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

        self.client = self.client or ui.context.client
        ui.label("3 · 核对保存安排").classes("font-semibold text-lg")
        ui.label("表格显示最终目录。勾选后设置所选论文，或双击一篇单独修改。").classes(
            "an-muted text-sm"
        )
        self.count = ui.label().classes("an-info w-full")
        with ui.row().classes("an-toolbar w-full"):
            groups = list(
                dict.fromkeys(
                    row.get("input_group")
                    for row in self.rows
                    if row.get("input_group") not in (None, "", "未分组")
                )
            )
            if len(groups) > 1:
                group = (
                    ui.select(
                        {"": "全部输入分组", **{name: name for name in groups}},
                        value="",
                        label="筛选清单分组",
                    )
                    .props("outlined dense")
                    .classes("min-w-[220px]")
                )

                async def filter_group():
                    current = await self.grid.run_grid_method("getFilterModel") or {}
                    if group.value:
                        current["input_group"] = {
                            "filterType": "text",
                            "type": "equals",
                            "filter": group.value,
                        }
                    else:
                        current.pop("input_group", None)
                    await self.grid.run_grid_method("setFilterModel", current or None)

                group.on_value_change(guard(filter_group))
                ui.label("只筛选显示，不改变保存位置。").classes("an-muted text-xs")
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
                await self.refresh_count()

            ui.button("选择当前筛选", on_click=guard(select_filtered)).props("outline")
            ui.button(
                "取消选择",
                on_click=guard(lambda: self.grid.run_grid_method("deselectAll")),
            ).props("flat")
        with ui.row().classes("an-toolbar w-full"):
            self.placement_button = ui.button(
                "设置所选 0 篇",
                icon="edit_location_alt",
                on_click=guard(self.open_selected),
            ).props("outline")
            self.placement_button.disable()

            async def set_enabled(enabled):
                rows = await read_edited_grid(self.grid)
                selected = {row["id"] for row in await self.grid.get_selected_rows()}
                if not selected:
                    raise ValueError("请先勾选需要修改获取开关的论文")
                for row in rows:
                    if row["id"] in selected:
                        row["enabled"] = enabled
                await self.replace(rows)

            ui.button("启用选中论文", on_click=guard(lambda: set_enabled(True))).props(
                "flat"
            )
            ui.button("停用选中论文", on_click=guard(lambda: set_enabled(False))).props(
                "flat"
            )
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

    async def open_selected(self):
        rows = await read_edited_grid(self.grid)
        ids = [row["id"] for row in await self.grid.get_selected_rows()]
        if not ids:
            raise ValueError("请先勾选需要设置的论文。")
        return self.open_placement(
            ids, rows=rows, title=f"所选 {len(ids)} 篇 · 保存位置与标签"
        )

    def open_placement(self, ids, *, rows=None, title="保存位置与标签"):
        from .ui_acquisition_groups import placement_dialog

        return placement_dialog(self.controller, self, ids, rows=rows, title=title)

    async def open_row(self, row_id=None):
        rows = await read_edited_grid(self.grid)
        if row_id is None:
            selected = await self.grid.get_selected_rows()
            if len(selected) != 1:
                raise ValueError("请选择一篇论文，或双击需要设置的行")
            row_id = selected[0]["id"]
        return self.open_placement([row_id], rows=rows, title="本篇 · 保存位置与标签")

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
