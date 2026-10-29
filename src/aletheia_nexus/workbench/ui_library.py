"""Library tables and actual, previewed organization operations."""

from __future__ import annotations

from copy import deepcopy
from html import unescape
from pathlib import Path

from .labels import GRID_LOCALE, field_label, value_label
from .messages import user_message
from .ui_common import (
    guard,
    json_view,
    parameter_editor,
    rows_table,
    split_tags,
)
from .ui_grids import read_edited_grid

COLUMNS = {
    "title": "显示标题",
    "title_original": "原题",
    "title_zh": "中文译名",
    "custom_name": "自定义名称",
    "first_author": "第一作者",
    "authors": "作者列表",
    "year": "年份",
    "journal": "期刊",
    "doi": "DOI",
    "tags": "标签",
    "folder": "分类目录",
    "collections": "研究集合",
    "filename": "真实文件名",
    "path": "磁盘路径",
    "size": "大小（字节）",
    "si_count": "SI 数量",
    "integrity": "文件完整性",
    "identity_basis": "来源身份",
    "download_source": "获取来源",
    "download_time": "获取时间",
    "parse_status": "解析状态",
    "ocr_status": "OCR 状态",
    "reading_status": "阅读状态",
    "research_tasks": "科研任务",
}

SELECTION_COLUMN = "__selection__"
INTEGRITY_LABELS = {
    "verified": "文件指纹一致",
    "hash_mismatch": "文件指纹不符",
    "missing": "文件缺失",
}


def library_columns(visible, *, wrap=True):
    """A selection control is independent of every hideable metadata column."""
    columns = [
        {
            "colId": SELECTION_COLUMN,
            "headerName": "选择",
            "pinned": "left",
            "checkboxSelection": True,
            "headerCheckboxSelection": True,
            "headerCheckboxSelectionCurrentPageOnly": True,
            "lockVisible": True,
            "lockPosition": "left",
            "suppressMovable": True,
            "width": 72,
            "minWidth": 72,
            "maxWidth": 72,
            "resizable": False,
            "sortable": False,
        }
    ]
    order = {key: n for n, key in enumerate(visible)}
    data = [
        {
            "field": key,
            "headerName": label,
            "hide": key not in visible,
            "sortable": True,
            "resizable": True,
            "minWidth": 100,
            "width": 380 if key == "title" else 200 if key.startswith("title") else 140,
            **({"pinned": "left"} if key == "title" else {}),
            **(
                {"wrapText": wrap, "autoHeight": wrap}
                if key in {"title", "title_original", "title_zh"}
                else {}
            ),
        }
        for key, label in COLUMNS.items()
    ]
    data.sort(key=lambda col: order.get(col["field"], len(order)))
    return [*columns, *data]


def metadata_column_state(state):
    """Saved layouts cannot hide/reorder the always-visible selection control."""
    return [dict(col) for col in state if col.get("colId") in COLUMNS]


def view_title(row, view, *, default_mode="bilingual"):
    mode = view.get("title_mode", default_mode)
    original = row.get("title_original") or row.get("title", "")
    zh, custom = row.get("title_zh"), row.get("custom_name")
    if mode == "bilingual" and zh and zh != original:
        return zh + "\n" + original
    if mode == "zh":
        return zh or original
    if mode == "custom":
        return custom or zh or original
    return original


def marked_library_ids(selected_rows, visible_rows):
    """Use current stable IDs for a one-step action, without changing the tray."""
    known = {row["id"] for row in visible_rows}
    ids = list(dict.fromkeys(row.get("id") for row in selected_rows))
    if not ids:
        raise ValueError("请先在文献列表左侧勾选要处理的论文。")
    if any(paper_id not in known for paper_id in ids):
        raise ValueError("表格选择已过期，请刷新文献列表后重新勾选。")
    return ids


class _ImportPostprocessContext:
    """A 'skip next file' request must never become a paid title-batch skip."""

    def __init__(self, context):
        self.context = context

    def __getattr__(self, name):
        return getattr(self.context, name)

    def should_skip(self, *_):
        if self.context.should_skip():
            self.context.progress(
                import_skip_notice="导入文件阶段已结束，跳过文件请求未影响后续标题处理或已登记文件。"
            )
        return False


class LibraryPage:
    def import_worker(self, paths, *, title=None, folder="", tags=(), translation=None):
        paths, tags, translation = (
            tuple(paths),
            tuple(tags),
            deepcopy(translation or {}),
        )

        def worker(context):
            rows = []
            for index, incoming in enumerate(paths):
                context.checkpoint()
                context.progress(
                    index,
                    len(paths),
                    item=str(incoming),
                    stage="导入文件",
                    import_phase="files",
                )
                if context.should_skip(str(incoming)):
                    rows.append(
                        {
                            "path": str(incoming),
                            "status": "SKIPPED",
                            "reason": "按用户请求在文件边界跳过，原始文件未改变。",
                        }
                    )
                    context.record(
                        str(incoming), "SKIPPED", reason="按用户请求跳过下一份文件"
                    )
                    continue
                try:
                    row = self.ctx.library.import_pdf(
                        incoming, title=title or None, folder=folder, tags=tags
                    )
                    rows.append(
                        {"path": str(incoming), "status": "REGISTERED", "paper": row}
                    )
                    context.record(str(incoming), "REGISTERED", path=row["pdf_path"])
                except Exception as exc:
                    rows.append(
                        {
                            "path": str(incoming),
                            "status": "FAILED",
                            "error": str(exc)[:500],
                        }
                    )
                    context.record(str(incoming), "FAILED", error=str(exc)[:500])
            unused_skip = context.should_skip()
            context.progress(
                len(paths),
                len(paths),
                stage="导入后处理",
                import_phase="postprocess",
                import_skip_notice="已无待导入文件，跳过请求未撤销已登记文件。"
                if unused_skip
                else None,
            )
            imported = [
                row["paper"]["id"] for row in rows if row["status"] == "REGISTERED"
            ]
            translated = self.translate_missing_english(
                imported, translation, _ImportPostprocessContext(context)
            )
            return {
                "items": rows,
                "translation": translated,
                "status": "COMPLETED"
                if all(row["status"] == "REGISTERED" for row in rows)
                and translated["status"] in {"COMPLETED", "NOT_REQUESTED"}
                else "PARTIAL",
            }

        return worker

    def attachment_import_worker(
        self, parent_id, path, *, role="SUPPLEMENT", title=None
    ):
        def worker(context):
            context.checkpoint()
            context.progress(
                0, 1, item=str(path), stage="导入文件", import_phase="files"
            )
            if context.should_skip(str(path)):
                context.record(str(path), "SKIPPED", reason="按用户请求跳过下一份文件")
                return {
                    "status": "PARTIAL",
                    "items": [
                        {
                            "path": str(path),
                            "status": "SKIPPED",
                            "document_role": role,
                            "paper_id": parent_id,
                        }
                    ],
                }
            attachment = self.ctx.library.import_attachment(
                parent_id, path, role=role, title=title
            )
            context.record(
                str(path), "REGISTERED", path=attachment["path"], paper_id=parent_id
            )
            unused_skip = context.should_skip()
            context.progress(
                1,
                1,
                stage="附件登记完成",
                import_phase="postprocess",
                import_skip_notice="已无待导入文件，跳过请求未撤销已登记附件。"
                if unused_skip
                else None,
            )
            return {
                "status": "COMPLETED",
                "items": [
                    {
                        "path": attachment["path"],
                        "original_path": str(path),
                        "status": "REGISTERED",
                        "document_role": role,
                        "paper_id": parent_id,
                        "attachment": attachment,
                    }
                ],
            }

        return worker

    def tag_input(self, label, value=(), *, allow_new=True):
        from nicegui import ui

        selected = split_tags(value)
        known = sorted(
            {
                *selected,
                *(
                    tag
                    for row in self.ctx.library.scan()["items"]
                    for tag in row["tags"]
                ),
            }
        )
        return (
            ui.select(
                known,
                value=selected,
                multiple=True,
                with_input=True,
                new_value_mode="add-unique" if allow_new else None,
                label=label,
                clearable=True,
            )
            .props("outlined dense use-chips")
            .classes("w-full")
        )

    def library_page(self):
        from nicegui import run, ui

        self.title(
            "文献库", "按目录存放正文，分类内共享 SI；标签、集合与表格视图分别保存。"
        )
        all_rows = self.ctx.library.scan()["items"]
        tags = sorted({t for row in all_rows for t in row.get("tags", [])})
        folders = sorted({row["folder"] for row in all_rows if row["folder"]})
        with ui.row().classes("an-toolbar w-full"):
            query = (
                ui.input(
                    "原题 / 中文译名 / DOI / 文件名",
                    value=self.library_filters.get("query", ""),
                )
                .props("outlined dense clearable")
                .classes("grow min-w-72")
            )
            folder = ui.select(
                ["", *folders],
                value=self.library_filters.get("folder", ""),
                label="分类目录",
                with_input=True,
            ).props("outlined dense clearable")
            tag = ui.select(
                tags,
                value=self.library_filters.get("tags", []),
                label="标签",
                multiple=True,
                with_input=True,
            ).props("outlined dense use-chips clearable")
            tag_mode = (
                ui.select(
                    {"AND": "全部标签", "OR": "任一标签"},
                    value=self.library_filters.get("tag_mode", "AND"),
                    label="标签组合",
                )
                .props("outlined dense")
                .classes("min-w-[140px] w-[160px]")
            )
            untranslated = ui.checkbox(
                "未翻译", value=self.library_filters.get("untranslated", False)
            )
            parsed_value = self.library_filters.get("parsed")
            if type(parsed_value) is bool:
                parsed_value = "ANY_PARSED" if parsed_value else "NOT_PARSED"
            parsed = ui.select(
                {
                    "": "全部解析状态",
                    "PARSED": "解析完成",
                    "PARTIAL": "部分解析",
                    "FAILED": "解析失败",
                    "UNPARSED": "尚未解析",
                    "ANY_PARSED": "已解析（完成或部分）",
                    "NOT_PARSED": "未成功解析",
                },
                value=parsed_value or "",
                label="解析状态",
            ).props("outlined dense")

        with ui.row().classes("an-toolbar w-full"):
            collection = (
                ui.select(
                    ["", *self.ctx.library.collections()],
                    value=self.library_filters.get("collection", ""),
                    label="固定研究集合",
                )
                .props("outlined dense clearable")
                .classes("min-w-[180px] w-[220px]")
            )
            saved = (
                ui.select(["", *self.ctx.library.filters()], value="", label="保存筛选")
                .props("outlined dense clearable")
                .classes("min-w-[180px] w-[220px]")
            )
            view_name = self.ctx.settings.get("active_view", "标准文献视图")
            views = self.ctx.library.views()
            if view_name not in views:
                view_name = next(iter(views))
            view = (
                ui.select(list(views), value=view_name, label="表格视图")
                .props("outlined dense")
                .classes("min-w-[180px] w-[220px]")
            )
            ui.button(
                "导入 PDF / 文件夹",
                icon="upload_file",
                on_click=guard(self.import_dialog),
            ).props("outline")
            ui.button(
                "标签与分组", icon="label", on_click=guard(self.tags_dialog)
            ).props("flat")

        def filters():
            return {
                "query": query.value or None,
                "folder": folder.value or None,
                "tags": tag.value or [],
                "tag_mode": tag_mode.value,
                "untranslated": untranslated.value,
                "collection": collection.value or None,
                "parsed": True
                if parsed.value == "ANY_PARSED"
                else False
                if parsed.value == "NOT_PARSED"
                else parsed.value or None,
            }

        state = views[view_name]
        visible = state.get("columns", list(COLUMNS))
        columns = library_columns(visible, wrap=state.get("wrap", True))

        with ui.row().classes("an-toolbar w-full"):
            count = ui.label("").classes("an-muted grow")
            marked_count = ui.label("表格已勾选 0 篇").classes("an-muted")
            ui.button(
                "刷新 / 应用筛选", icon="refresh", on_click=guard(lambda: refresh())
            ).props("outline")
            ui.button(
                "清除筛选",
                icon="filter_alt_off",
                on_click=guard(lambda: clear_filters()),
            ).props("flat")
            ui.button(
                "保存筛选条件",
                icon="filter_alt",
                on_click=guard(lambda: save_filter_dialog()),
            ).props("flat")
            ui.button(
                "列 / 排序 / 视图",
                icon="view_column",
                on_click=guard(lambda: columns_dialog()),
            ).props("flat")
            ui.button(
                "管理集合 / 筛选 / 分组",
                icon="folder_special",
                on_click=guard(lambda: manage_organization()),
            ).props("flat")

        grid = ui.aggrid(
            {
                "localeText": GRID_LOCALE,
                "columnDefs": columns,
                "rowData": [],
                "rowSelection": "multiple",
                "rowMultiSelectWithClick": False,
                "suppressRowClickSelection": True,
                "pagination": True,
                "paginationPageSize": 50,
                "paginationPageSizeSelector": [20, 50, 100],
                "defaultColDef": {"resizable": True, "sortable": True},
                ":getRowId": "params => params.data.id",
                "animateRows": False,
            },
            theme="quartz",
        ).classes("an-library")
        with ui.expansion("来源、缺失文件与重复副本诊断", icon="fact_check").classes(
            "w-full"
        ):
            diagnostic_area = ui.column().classes("w-full")

        def title_for(row):
            return view_title(
                row,
                state,
                default_mode=self.ctx.settings.get("title_mode", "bilingual"),
            )

        async def refresh():
            requested_filters = filters()
            self.library_filters = requested_filters
            report = await run.io_bound(self.ctx.library.scan, **requested_filters)
            if self.library_filters != requested_filters or getattr(
                grid, "is_deleted", False
            ):
                return
            self.library_rows = report["items"]
            rows = [
                {
                    **r,
                    "title": title_for(r),
                    "journal": unescape(r.get("journal") or ""),
                    "path": r["pdf_path"],
                    "tags": ", ".join(r["tags"]),
                    "authors": "; ".join(str(a) for a in r.get("authors", [])),
                    "collections": ", ".join(r.get("collections", [])),
                    "parse_status": value_label(r.get("parse_status")),
                    "integrity": INTEGRITY_LABELS.get(r.get("integrity"), "尚未核验"),
                    "identity_basis": value_label(r.get("identity_basis")),
                    "ocr_status": {
                        "NOT_REQUESTED": "未启用",
                        "CONFIGURED": "已配置，需核对实际使用",
                        "USED": "实际使用",
                        "UNKNOWN": "未记录",
                    }.get(r.get("ocr_status", "UNKNOWN"), "未记录"),
                    "research_tasks": "；".join(
                        f"{item.get('task_id') or item.get('job_id', '')}（{value_label(item.get('status'))}）"
                        if isinstance(item, dict)
                        else str(item)
                        for item in r.get("research_tasks", [])
                    ),
                }
                for r in self.library_rows
            ]
            # NiceGUI options are observable: even assigning options['rowData']
            # schedules destroy/createGrid. Keep server data in library_rows
            # and use only the client API to retain checks and column layout.
            await grid.run_grid_method("setGridOption", "rowData", rows)
            count.set_text(
                f"{len(self.library_rows)} 篇筛选结果 · 跨页面选择清单 {len(self.ctx.library.selection())} 篇"
            )
            diagnostic_area.clear()
            with diagnostic_area:
                if report["warnings"]:
                    ui.label(
                        f"发现 {len(report['warnings'])} 项诊断。请检查路径、恢复原文件或正确来源记录后刷新；不会自动将异常来源当作成功。"
                    )
                    for warning in report["warnings"][:100]:
                        with ui.card().classes("an-card w-full"):
                            ui.label(
                                str(
                                    warning.get("sidecar")
                                    or warning.get("paper_id")
                                    or warning.get("doi")
                                    or "文库记录"
                                )
                            ).classes("text-xs break-all")
                            reason = (
                                warning.get("error")
                                or warning.get("reason")
                                or "记录未提供具体原因"
                            )
                            ui.label(user_message(reason)).classes("text-sm")
                            if warning.get("paper_ids"):
                                ui.label(
                                    f"涉及 {warning['count']} 个独立文献身份："
                                    + "；".join(warning["paper_ids"])
                                ).classes("text-xs break-all")
                            if warning.get("paths"):
                                ui.label(
                                    "重复副本：" + "；".join(warning["paths"])
                                ).classes("text-xs break-all")
                    if len(report["warnings"]) > 100:
                        ui.label("此处先显示前 100 项；全部诊断保留在下方专家记录。")
                    json_view(report["warnings"], label="全部原始诊断（专家）")
                else:
                    ui.label(
                        "未发现来源记录或重复副本警告。文件操作和科研读取时仍会重新核验实际来源。"
                    ).classes("an-muted")
            if report["warnings"]:
                ui.notify(
                    f"文库有 {len(report['warnings'])} 项来源/文件诊断，请检查详情。",
                    type="warning",
                )
            await show_marked_count()

        async def refresh_metadata():
            if not grid.is_deleted:
                await refresh()

        self._refresh_library_metadata = refresh_metadata

        async def clear_filters():
            for control, value in (
                (query, ""),
                (folder, ""),
                (tag, []),
                (tag_mode, "AND"),
                (untranslated, False),
                (parsed, ""),
                (collection, ""),
                (saved, ""),
            ):
                control.set_value(value)
            await refresh()

        query.on("keydown.enter", guard(refresh))

        async def show_marked_count():
            marked_count.set_text(
                f"表格已勾选 {len(await grid.get_selected_rows())} 篇"
            )

        grid.on("selectionChanged", guard(show_marked_count))

        async def add_marked():
            selected = await grid.get_selected_rows()
            ids = marked_library_ids(selected, self.library_rows)
            self.ctx.library.set_selection(ids, mode="add")
            ui.notify(f"已添加 {len(ids)} 篇；跨页面保留并自动去重。")
            count.set_text(
                f"{len(self.library_rows)} 篇筛选结果 · 跨页面选择清单 {len(self.ctx.library.selection())} 篇"
            )

        def add_all():
            ids = [r["id"] for r in self.library_rows]
            if not ids:
                raise ValueError("当前筛选没有论文，请调整或清除筛选条件。")
            self.ctx.library.set_selection(ids, mode="add")
            ui.notify(f"已将全部 {len(ids)} 篇筛选结果加入清单。")
            count.set_text(
                f"{len(ids)} 篇筛选结果 · 跨页面选择清单 {len(self.ctx.library.selection())} 篇"
            )

        async def parse_marked():
            ids = marked_library_ids(await grid.get_selected_rows(), self.library_rows)
            self.parse_dialog(ids)

        async def search_marked():
            ids = marked_library_ids(await grid.get_selected_rows(), self.library_rows)
            self.search_handoff = {"ids": ids, "label": "文库勾选文献"}
            self.navigate("科研检索")

        async def organize_marked():
            ids = marked_library_ids(await grid.get_selected_rows(), self.library_rows)
            self.organize_dialog(ids)

        async def translate_marked():
            ids = marked_library_ids(await grid.get_selected_rows(), self.library_rows)
            self.title_translation_dialog(ids)

        async def manage_organization():
            from .ui_organization import render_organization_dialog

            selected = await grid.get_selected_rows()
            ids = marked_library_ids(selected, self.library_rows) if selected else []

            async def updated(change):
                collections = self.ctx.library.collections()
                wanted = collection.value
                if change["section"] == "collections" and wanted == change["name"]:
                    wanted = change.get("new_name") or ""
                collection.set_options(
                    ["", *collections], value=wanted if wanted in collections else ""
                )
                # Clearing only the saved-object selector preserves the actual
                # current filter controls and avoids implicitly applying rules.
                saved.set_options(["", *self.ctx.library.filters()], value="")
                await refresh()

            def apply_filter(rules):
                self.library_filters = rules
                self.page_content.refresh()

            await render_organization_dialog(
                self,
                marked_ids=ids,
                current_filters=filters(),
                on_updated=updated,
                apply_filter=apply_filter,
            )

        async def details(event):
            row = event.args.get("data") or {}
            if row.get("id"):
                self.details_dialog(row["id"])

        grid.on("rowDoubleClicked", guard(lambda: None))
        grid.on("cellDoubleClicked", details)

        async def persist_view():
            current = self.ctx.library.views()[view.value]
            current["column_state"] = metadata_column_state(
                await grid.run_grid_method("getColumnState")
            )
            current["columns"] = [
                c["colId"] for c in current["column_state"] if not c.get("hide")
            ]
            self.ctx.library.save_view(view.value, current)
            self.ctx.settings.set("active_view", view.value)

        # Column state contains order, width, visibility, pinned and sorting.
        grid.on("columnResized", guard(persist_view))
        grid.on("columnMoved", guard(persist_view))
        grid.on("sortChanged", guard(persist_view))

        def columns_dialog():
            with ui.dialog() as dialog, ui.card().classes("w-[650px] max-w-[90vw]"):
                ui.label("自定义表格视图").classes("text-lg font-semibold")
                selected = (
                    ui.select(COLUMNS, value=visible, multiple=True, label="显示列")
                    .props("use-chips")
                    .classes("w-full")
                )
                name = ui.input("保存视图名称", value=view.value).classes("w-full")
                wrap = ui.checkbox("长标题换行", value=state.get("wrap", True))
                title_mode = ui.select(
                    {
                        "bilingual": "中英文双行",
                        "zh": "中文优先",
                        "original": "原题优先",
                        "custom": "自定义短名称优先",
                    },
                    value=state.get(
                        "title_mode", self.ctx.settings.get("title_mode", "bilingual")
                    ),
                    label="此视图的标题显示方式",
                ).classes("w-full")
                ui.label(
                    "在表头拖动调整列顺序和宽度；点击表头排序，修改自动保存至当前视图。"
                )

                async def save():
                    if not selected.value:
                        raise ValueError("请至少保留一个文献数据列；选择列会一直显示")
                    columns_state = metadata_column_state(
                        await grid.run_grid_method("getColumnState")
                    )
                    for col in columns_state:
                        col["hide"] = col["colId"] not in selected.value
                    self.ctx.library.save_view(
                        name.value,
                        {
                            "columns": selected.value,
                            "column_state": columns_state,
                            "wrap": wrap.value,
                            "title_mode": title_mode.value,
                        },
                    )
                    self.ctx.settings.set("active_view", name.value)
                    dialog.close()
                    self.page_content.refresh()

                ui.button("保存视图", on_click=guard(save))
                ui.button("关闭", on_click=dialog.close).props("flat")
            dialog.open()

        def save_filter_dialog():
            with ui.dialog() as dialog, ui.card():
                name = ui.input("筛选规则名称")
                ui.label("保存条件，后续按当前文库重新运行；不会改变已有科研任务快照。")
                ui.button(
                    "保存",
                    on_click=guard(
                        lambda: (
                            self.ctx.library.save_filter(name.value, filters()),
                            dialog.close(),
                        )
                    ),
                )
            dialog.open()

        async def restore_columns():
            if state.get("column_state"):
                await grid.run_grid_method(
                    "applyColumnState",
                    {
                        "state": [
                            {
                                "colId": SELECTION_COLUMN,
                                "hide": False,
                                "pinned": "left",
                                "width": 72,
                            },
                            *metadata_column_state(state["column_state"]),
                        ],
                        "applyOrder": True,
                    },
                )

        ui.timer(0.2, guard(restore_columns), once=True)
        view.on_value_change(
            lambda e: (
                self.ctx.settings.set("active_view", e.value),
                self.page_content.refresh(),
            )
        )
        saved.on_value_change(
            lambda e: (
                (
                    setattr(
                        self,
                        "library_filters",
                        self.ctx.library.filters().get(e.value, {}),
                    ),
                    self.page_content.refresh(),
                )
                if e.value
                else None
            )
        )
        with ui.row().classes("an-toolbar w-full"):
            ui.button(
                "补中文标题", icon="translate", on_click=guard(translate_marked)
            ).props("outline")
            ui.button(
                "解析已勾选", icon="document_scanner", on_click=guard(parse_marked)
            )
            ui.button(
                "检索已勾选", icon="manage_search", on_click=guard(search_marked)
            ).props("outline")
            ui.button(
                "加入选择清单", icon="playlist_add", on_click=guard(add_marked)
            ).props("outline")
            ui.button(
                "全选当前页面",
                on_click=guard(
                    lambda: grid.run_grid_method("selectAll", "currentPage")
                ),
            ).props("outline")
            ui.button("加入全部筛选结果", on_click=guard(add_all)).props("outline")
            ui.button(
                "整理已勾选文献",
                icon="drive_file_rename_outline",
                on_click=guard(organize_marked),
            ).props("outline")
            ui.button(
                "选择清单", icon="checklist", on_click=guard(self.selection_dialog)
            ).props("flat")
            ui.label("直接解析/检索只处理表格勾选；选择清单用于跨页面积累。").classes(
                "an-muted text-xs"
            )
            ui.label("双击任意文献查看详情 / PDF").classes("an-muted text-xs")
        ui.timer(0.1, guard(refresh), once=True)

    def title_translation_dialog(self, ids):
        from .ui_title_translation import render_title_translation_dialog

        return render_title_translation_dialog(self, ids)

    def details_dialog(self, paper_id):
        from nicegui import ui

        paper = self.ctx.library.get(paper_id)
        if paper is None:
            raise ValueError("文献已移出当前文库，请刷新。")
        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[1000px] max-w-[95vw] an-card"),
        ):
            ui.label(paper["title_original"]).classes("text-xl font-semibold")
            ui.label(
                f"{paper.get('doi') or '无 DOI'} · {value_label(paper.get('identity_basis'))} · {INTEGRITY_LABELS.get(paper.get('integrity'), '尚未核验')} · {paper['pdf_path']}"
            ).classes("an-muted text-xs break-all")
            custom = ui.input(
                "自定义显示名称", value=paper.get("custom_name") or ""
            ).classes("w-full")
            translated = ui.textarea(
                "中文译名（原题保持不变）", value=paper.get("title_zh") or ""
            ).classes("w-full")
            confirmed = ui.checkbox(
                "人工确认此译名",
                value=(paper.get("translation") or {}).get("confirmed", False),
            )
            tags = self.tag_input("标签（输入可查找，回车新建）", paper["tags"])
            reading = ui.select(
                ["未读", "正在阅读", "已读", "重点"],
                value=paper.get("reading_status") or "未读",
                label="阅读状态",
            )

            def save():
                if translated.value.strip() and (
                    translated.value != (paper.get("title_zh") or "")
                    or confirmed.value
                    != (paper.get("translation") or {}).get("confirmed", False)
                ):
                    self.ctx.translation.edit(
                        paper_id, translated.value, confirmed=confirmed.value
                    )
                self.ctx.library.update_metadata(
                    paper_id, custom_name=custom.value, reading_status=reading.value
                )
                self.ctx.library.update_tags(
                    [paper_id],
                    add=split_tags(tags.value),
                    remove=[
                        t for t in paper["tags"] if t not in split_tags(tags.value)
                    ],
                )
                ui.notify("文献元数据已保存，来源和 PDF 未改变。")

            with ui.row().classes("an-toolbar"):
                ui.button("保存元数据", on_click=guard(save), icon="save")

                def supplement_title():
                    dialog.close()
                    self.title_translation_dialog([paper_id])

                ui.button(
                    "补中文标题", icon="translate", on_click=guard(supplement_title)
                ).props("outline")
                ui.button(
                    "查看主文 PDF",
                    on_click=guard(
                        lambda: self.show_pdf(self.ctx.research.pdf_document(paper_id))
                    ),
                    icon="picture_as_pdf",
                )
                ui.button(
                    "加入选择清单",
                    on_click=guard(
                        lambda: self.ctx.library.set_selection([paper_id], mode="add")
                    ),
                ).props("outline")
                ui.button(
                    "翻译 / 重命名 / 移动",
                    on_click=guard(lambda: self.organize_dialog([paper_id])),
                ).props("outline")
                ui.button(
                    "解析 / 版本", on_click=guard(lambda: self.parse_dialog([paper_id]))
                ).props("outline")
            for attachment in paper.get("attachments", []):
                with ui.row().classes("an-toolbar"):
                    ui.label(
                        f"{value_label(attachment['role'])} · {Path(attachment['path']).name}"
                    )
                    if (
                        Path(attachment["path"]).suffix.lower() == ".pdf"
                        and attachment["role"] == "SUPPLEMENT"
                        and attachment.get("sidecar_path")
                    ):
                        ui.button(
                            "查看",
                            on_click=guard(
                                lambda a=attachment: self.show_pdf(
                                    self.ctx.research.pdf_document(paper_id, a["id"])
                                )
                            ),
                        ).props("flat dense")
                    else:
                        ui.link(
                            "打开 / 下载原始附件",
                            self.files.register(attachment["path"]),
                            new_tab=True,
                        )
            with ui.expansion("添加本地 SI / 其它关联附件", icon="attach_file").classes(
                "w-full"
            ):
                ui.label(
                    "明确关联到当前论文；PDF SI登记为人工声明身份，非PDF附件仅安全保存，不自动解析。"
                )
                attachment_path = ui.input("本地附件绝对路径").classes("w-full")
                attachment_title = ui.input("附件标题（PDF可填）").classes("w-full")
                attachment_role = ui.select(
                    {
                        "SUPPLEMENT": "SI / 补充信息",
                        "SOURCE_DATA": "源数据",
                        "REPORTING_SUMMARY": "研究报告摘要",
                        "PEER_REVIEW": "同行评审材料",
                        "OTHER": "其它",
                    },
                    value="SUPPLEMENT",
                    label="真实附件角色",
                )

                def import_attachment(path=None):
                    incoming, role, supplied_title = (
                        path or attachment_path.value,
                        attachment_role.value,
                        attachment_title.value or None,
                    )
                    self.submit(
                        "import",
                        "添加关联附件 · " + paper["title"][:50],
                        [paper_id],
                        self.attachment_import_worker(
                            paper_id, incoming, role=role, title=supplied_title
                        ),
                        {"parent_id": paper_id, "path": str(incoming), "role": role},
                    )

                async def upload_attachment(event):
                    from uuid import uuid4

                    name = Path(event.file.name)
                    extension = (
                        "".join(name.suffixes[-2:])
                        if name.name.lower().endswith(
                            (".tar.gz", ".tar.bz2", ".tar.xz")
                        )
                        else name.suffix
                    )
                    temporary = (
                        Path(self.ctx.workspace)
                        / "incoming"
                        / (uuid4().hex + extension)
                    )
                    temporary.parent.mkdir(parents=True, exist_ok=True)
                    await event.file.save(temporary)
                    import_attachment(temporary)

                ui.button(
                    "登记到当前论文",
                    icon="attach_file",
                    on_click=guard(import_attachment),
                )
                from .supplements import _SUFFIXES

                ui.upload(
                    label="或上传要关联的本地附件",
                    on_upload=upload_attachment,
                    auto_upload=True,
                    max_file_size=200_000_000,
                ).props('accept="' + ",".join(sorted(_SUFFIXES)) + '"')
            json_view(paper, label="书目、来源、关联附件与诊断")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def import_dialog(self):
        from nicegui import ui

        with ui.dialog() as dialog, ui.card().classes("w-[800px] max-w-[95vw] an-card"):
            ui.label("导入已有 PDF").classes("text-xl font-semibold")
            ui.label(
                "保留原始文件并将副本登记到当前文库。已有AN来源记录保留原状态；未登记PDF采用用户声明身份，不标为VERIFIED。"
            )
            with ui.row().classes("an-toolbar w-full"):
                folder = ui.input("目标分类（留空为文库根目录）", value="").classes(
                    "grow"
                )

                def choose_folder():
                    from .ui_folders import choose_library_folder

                    choose_library_folder(
                        self.ctx.library, folder.set_value, initial=folder.value or ""
                    )

                ui.button(
                    "选已有 / 新建分类",
                    icon="create_new_folder",
                    on_click=guard(choose_folder),
                ).props("outline")
            title = ui.input("原始标题（单篇可填；留空采用文件名）").classes("w-full")
            tags = self.tag_input("标签（输入可查找，回车新建）")
            read_translation = self.title_translation_controls()
            status = ui.label("")

            def import_paths(paths, upload_title=None):
                if not paths:
                    raise ValueError("没有可导入的 PDF")
                folder_value, tag_values, title_value = (
                    folder.value,
                    split_tags(tags.value),
                    title.value or upload_title,
                )
                translation = read_translation()

                worker = self.import_worker(
                    paths,
                    title=title_value,
                    folder=folder_value,
                    tags=tag_values,
                    translation=translation,
                )

                self.submit(
                    "import",
                    f"导入 {len(paths)} 份 PDF",
                    [str(p) for p in paths],
                    worker,
                    {
                        "folder": folder_value,
                        "tags": tag_values,
                        "title_translation": translation,
                    },
                )
                status.set_text(f"已加入任务中心：{len(paths)} 份 PDF")

            def from_path():
                incoming = Path(path.value).expanduser().resolve(strict=True)
                paths = (
                    sorted(
                        p
                        for p in (
                            incoming.rglob("*")
                            if recursive.value
                            else incoming.glob("*")
                        )
                        if p.is_file() and p.suffix.lower() == ".pdf"
                    )
                    if incoming.is_dir()
                    else [incoming]
                )
                import_paths(paths)

            async def upload(event):
                from uuid import uuid4

                from aletheia_nexus.core.organization import filename_stem

                # Upload has no authority over a destination name or source identity.
                target = (
                    Path(self.ctx.workspace)
                    / "incoming"
                    / uuid4().hex
                    / (filename_stem(Path(event.file.name).stem) + ".pdf")
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                await event.file.save(target)
                import_paths([target], upload_title=Path(event.file.name).stem)

            ui.upload(
                label="选择或拖入 PDF（可多选，选择后导入）",
                on_upload=upload,
                multiple=True,
                auto_upload=True,
                max_file_size=200_000_000,
            ).props('accept=".pdf"').classes("w-full")
            with ui.expansion(
                "从本地文件夹或已有AN来源导入", icon="folder_open"
            ).classes("w-full"):
                ui.label(
                    "普通 PDF 可直接在上方选择上传。整批文件夹或已有 AN 文献请按路径导入；"
                    "已有来源 JSON 应保留在原来的旁置位置，系统会核验并保留其来源身份。"
                ).classes("an-muted text-sm")
                path = ui.input("本地 PDF 或文件夹绝对路径").classes("w-full")
                recursive = ui.checkbox("递归导入文件夹", value=False)
                ui.button("按路径导入", on_click=guard(from_path), icon="folder_open")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def tags_dialog(self):
        from nicegui import ui

        ids = self.ctx.library.selection()
        with ui.dialog() as dialog, ui.card().classes("w-[700px] max-w-[95vw]"):
            ui.label(f"标签与可选分组 · 当前选择 {len(ids)} 篇").classes(
                "text-xl font-semibold"
            )
            add = self.tag_input("添加标签（输入可查找，回车新建）")
            remove = self.tag_input("移除现有标签", allow_new=False)
            ui.button(
                "应用到选择清单",
                on_click=guard(
                    lambda: (
                        self.ctx.library.update_tags(
                            ids,
                            add=split_tags(add.value),
                            remove=split_tags(remove.value),
                        ),
                        ui.notify(f"已处理 {len(ids)} 篇"),
                    )
                ),
            )
            group = ui.input("标签分组名称").classes("w-full")
            labels = self.tag_input("组内标签（输入可查找，回车新建）")
            ui.button(
                "保存分组",
                on_click=guard(
                    lambda: self.ctx.library.save_tag_group(
                        group.value, split_tags(labels.value)
                    )
                ),
            )
            json_view(self.ctx.library.tag_groups(), label="已有标签分组")
            with ui.expansion("全库标签重命名 / 删除", icon="edit_note").classes(
                "w-full"
            ):
                all_tags = sorted(
                    {t for r in self.ctx.library.scan()["items"] for t in r["tags"]}
                )
                old = ui.select(
                    all_tags, label="现有标签", value=all_tags[0] if all_tags else None
                )
                new = ui.input("新标签名称")
                ui.label(
                    "同时更新当前文库标签、标签分组和保存筛选；旧科研任务的历史材料快照保持原状。"
                )
                ui.label(
                    "删除保存筛选中的标签条件可能扩大范围，请在操作后重新核对筛选结果。"
                ).classes("an-info w-full")

                def rename():
                    old_value, new_value = old.value, new.value
                    self.submit(
                        "metadata",
                        f"重命名标签 {old_value} → {new_value}",
                        [],
                        lambda c: (
                            c.checkpoint(),
                            self.ctx.library.rename_tag(old_value, new_value),
                        )[1],
                        {"old_tag": old_value, "new_tag": new_value},
                    )

                def delete():
                    old_value = old.value
                    self.submit(
                        "metadata",
                        "从全库移除标签 " + str(old_value),
                        [],
                        lambda c: (
                            c.checkpoint(),
                            self.ctx.library.delete_tag(old_value),
                        )[1],
                        {"deleted_tag": old_value},
                    )

                ui.button("在全库重命名标签", on_click=guard(rename)).props("outline")
                ui.button("在全库删除此标签", on_click=guard(delete)).props("flat")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def organize_dialog(self, ids):
        from nicegui import run, ui

        from .translation import DEFAULT_OPTIONS

        if not ids:
            raise ValueError("请先勾选文献或加入当前选择清单")
        ids = list(dict.fromkeys(ids))
        state = {
            "preview": None,
            "job": None,
            "loaded": False,
            "grid": None,
            "preview_form": None,
        }
        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[1400px] max-w-[97vw] an-card"),
        ):
            ui.label(f"批量翻译、实际重命名与分类移动 · {len(ids)} 篇论文").classes(
                "text-xl font-semibold"
            )
            ui.label(
                "正文保存于分类根部；每篇关联附件迁移至该分类唯一 SI/。执行前逐项校验哈希与历史引用。"
            )
            with ui.row().classes("an-toolbar w-full"):
                template_names = self.ctx.library.templates()
                template_choice = ui.select(
                    list(template_names),
                    value=next(iter(template_names)),
                    label="命名模板",
                )
                template = ui.input(
                    "实际命名模板", value=next(iter(template_names.values()))
                ).classes("grow")
                target_mode = ui.select(
                    {
                        "keep": "保持当前分类",
                        "category": "移动到指定分类",
                        "root": "移到文库根目录",
                    },
                    value="keep",
                    label="分类移动目标",
                ).props("outlined dense")
                folder = ui.input("目标分类（相对文库根目录）")
                folder.set_visibility(False)
                target_mode.on_value_change(
                    lambda e: folder.set_visibility(e.value == "category")
                )

            def target_options():
                if target_mode.value == "root":
                    return {"folder": None, "move_to_root": True}
                if target_mode.value == "category":
                    if not folder.value or not folder.value.strip():
                        raise ValueError("请填写目标分类，或明确选择移到文库根目录")
                    return {"folder": folder.value, "move_to_root": False}
                return {"folder": None, "move_to_root": False}

            template_choice.on_value_change(
                lambda e: template.set_value(template_names[e.value])
            )
            with ui.row().classes("an-toolbar w-full"):
                missing = ui.select(
                    {
                        "fallback": "缺译名时回退原题",
                        "skip": "缺译名时跳过",
                        "translate": "在本流程调用 DeepSeek 补齐",
                    },
                    value="fallback",
                    label="缺失中文译名策略",
                ).classes("min-w-72")
                preset_name = ui.input("模板保存名称")
                ui.button(
                    "保存命名模板",
                    on_click=guard(
                        lambda: self.ctx.library.save_template(
                            preset_name.value, template.value
                        )
                    ),
                ).props("flat")
            with ui.expansion("翻译、费用与重译", icon="translate").classes("w-full"):
                from .ui_presets import preset_controls

                read_translation = parameter_editor(
                    {**DEFAULT_OPTIONS, **self.ctx.settings.get("translation", {})}
                )

                def apply_translation_preset(config):
                    read_translation.apply(config)
                    consent.set_value(False)
                    force.set_value(False)
                    estimate()

                preset_controls(
                    self.ctx.settings,
                    "translation",
                    read_translation,
                    apply_translation_preset,
                    title="标题翻译预设",
                )
                consent = ui.checkbox(
                    "我授权将本批待翻译的原题发送到 DeepSeek，并接受所示费用上限",
                    value=False,
                )
                force = ui.checkbox("重新翻译未人工确认的已有译名", value=False)
                estimate_area = ui.column().classes("w-full")

                def estimate():
                    import math

                    options = read_translation()
                    report = self.ctx.translation.estimate(ids, options)
                    pending = len(report["pending"]) + (
                        len(report["cached"]) if force.value else 0
                    )
                    cached = 0 if force.value else len(report["cached"])
                    estimate_area.clear()
                    with estimate_area:
                        ui.label(
                            f"本批 {report['total']} 篇：保留人工译名 {len(report['confirmed'])} 篇，"
                            f"复用缓存 {cached} 篇，待发送标题 {pending} 篇。"
                        ).classes("an-info w-full")
                        currency = "人民币元" if report["currency"] == "CNY" else "美元"
                        ui.label(
                            f"预计基础请求 {math.ceil(pending / options['batch_size'])} 次；"
                            f"总请求上限 {report['max_calls']} 次；费用上限 {report['max_cost']} {currency}。"
                            "仅发送原题，不发送 PDF 或全文。"
                        )
                        json_view(report, label="标题范围、缓存指纹与预算参数")
                    return pending

                ui.button("查看翻译范围与预算", on_click=guard(estimate)).props(
                    "outline"
                )
                force.on_value_change(guard(estimate))
                estimate()

                def translate_only():
                    options = read_translation()
                    grant, forced = consent.value, force.value
                    if estimate() and not grant:
                        raise ValueError("请明确授权标题外发和费用")
                    self.submit(
                        "translation",
                        f"翻译 {len(ids)} 篇标题",
                        ids,
                        lambda c: self.ctx.translation.translate(
                            ids, options, consent=grant, context=c, force=forced
                        ),
                        options,
                    )

                ui.button(
                    "仅翻译标题", on_click=guard(translate_only), icon="translate"
                )

            with ui.expansion("批量显示名称与标签", icon="edit").classes("w-full"):
                custom = ui.input("统一显示名称（仅变更显示字段）").classes("w-full")
                add = self.tag_input("添加标签（输入可查找，回车新建）")
                remove = self.tag_input("移除现有标签", allow_new=False)

                def metadata():
                    for paper_id in ids:
                        if custom.value:
                            self.ctx.library.update_metadata(
                                paper_id, custom_name=custom.value
                            )
                    self.ctx.library.update_tags(
                        ids, add=split_tags(add.value), remove=split_tags(remove.value)
                    )
                    ui.notify(f"已修改 {len(ids)} 篇的显示元数据")

                ui.button("应用元数据", on_click=guard(metadata))
            preview_area = ui.column().classes("w-full")
            status = ui.label("").classes("an-info w-full")

            def display_preview(preview):
                state["preview"] = preview
                preview_area.clear()
                with preview_area:
                    rows = [
                        {
                            "id": r["id"],
                            "enabled": r["status"] == "READY",
                            "final_stem": r.get("base_name", ""),
                            "old_path": r.get("old_path", ""),
                            "new_path": r.get("new_path", ""),
                            "SI": r.get("si_directory", ""),
                            "translation": {
                                "confirmed": "人工已确认",
                                "cached": "本地缓存",
                                "original_title_fallback": "回退原题",
                            }.get(
                                r.get("translation_source"),
                                value_label(r.get("translation_source")),
                            ),
                            "status": value_label(r["status"]),
                            "errors": "；".join(
                                user_message(e) for e in r.get("errors", [])
                            ),
                            "missing": "、".join(
                                field_label(k) for k in r.get("missing_metadata", [])
                            ),
                        }
                        for r in preview["items"]
                    ]
                    state["grid"] = ui.aggrid(
                        {
                            "localeText": GRID_LOCALE,
                            "stopEditingWhenCellsLoseFocus": True,
                            "columnDefs": [
                                {
                                    "field": "enabled",
                                    "headerName": "执行",
                                    "editable": True,
                                    "width": 85,
                                },
                                {
                                    "field": "final_stem",
                                    "headerName": "最终基础名称（可编辑）",
                                    "editable": True,
                                    "width": 350,
                                },
                                *(
                                    {"field": key, "headerName": label, "width": 250}
                                    for key, label in (
                                        ("old_path", "原主文路径"),
                                        ("new_path", "新主文路径"),
                                        ("SI", "统一 SI/"),
                                        ("translation", "译名来源"),
                                        ("status", "状态"),
                                        ("errors", "冲突/风险"),
                                        ("missing", "缺失元数据"),
                                    )
                                ),
                            ],
                            "rowData": rows,
                            "defaultColDef": {"resizable": True},
                            ":getRowId": "params => params.data.id",
                        },
                        theme="quartz",
                    ).classes("h-72 w-full")
                    moves = [
                        {"paper": r["id"], **m}
                        for r in preview["items"]
                        for m in r.get("moves", [])
                    ]
                    with ui.expansion(
                        "每个主文、SI 与来源记录的完整旧/新路径", icon="compare_arrows"
                    ).classes("w-full"):
                        rows_table(moves, row_key="source")
                    json_view(preview, label="预检、警告与历史引用风险")
                status.set_text(
                    f"可执行 {preview['executable']} 篇 · 跳过 {preview['skipped']} 篇。"
                    "编辑名称或取消项目后，请点击“应用逐篇修改并重做预检”。"
                )

            async def preview():
                template_value, target = template.value, target_options()
                missing_policy = missing.value
                state["preview_form"] = (
                    template.value,
                    target_mode.value,
                    folder.value,
                    missing.value,
                )
                if missing_policy == "translate":
                    options = read_translation()
                    grant = consent.value
                    if not grant:
                        raise ValueError(
                            "请先授权 DeepSeek 标题外发与预算，或选择回退/跳过"
                        )

                    def worker(context):
                        translated = self.ctx.translation.translate(
                            ids, options, consent=grant, context=context
                        )
                        return {
                            "translation": translated,
                            "preview": self.ctx.library.preview_rename(
                                ids,
                                template_value,
                                **target,
                                missing_translation="skip",
                            ),
                        }

                    receipt = self.submit(
                        "translation",
                        f"补齐译名并预览 {len(ids)} 篇命名",
                        ids,
                        worker,
                        options,
                    )
                    state.update(
                        job=receipt.get("job_id", receipt.get("id")), loaded=False
                    )
                    status.set_text(
                        "正在任务中心翻译缺失标题，完成后预览自动出现在此处。"
                    )
                else:
                    status.set_text("正在后台检查来源、附件与历史引用，请稍候。")
                    display_preview(
                        await run.io_bound(
                            self.ctx.library.preview_rename,
                            ids,
                            template_value,
                            **target,
                            missing_translation=missing_policy,
                        )
                    )

            async def regenerate():
                if state["grid"] is None:
                    raise ValueError("请先生成预览")
                changed = await read_edited_grid(state["grid"])
                enabled = [r["id"] for r in changed if r.get("enabled")]
                overrides = {
                    r["id"]: r["final_stem"] for r in changed if r.get("enabled")
                }
                state["preview_form"] = (
                    template.value,
                    target_mode.value,
                    folder.value,
                    missing.value,
                )
                status.set_text("正在后台重新检查逐篇修改与历史引用，请稍候。")
                display_preview(
                    await run.io_bound(
                        self.ctx.library.preview_rename,
                        enabled,
                        template.value,
                        **target_options(),
                        overrides=overrides,
                        missing_translation="skip"
                        if missing.value != "fallback"
                        else "fallback",
                    )
                )

            async def execute():
                preview_value = state["preview"]
                if not preview_value or not preview_value["executable"]:
                    raise ValueError("尚无可安全执行的预览")
                current = await read_edited_grid(state["grid"])
                expected = {r["id"]: r for r in preview_value["items"]}
                changed = any(
                    bool(r.get("enabled")) != (expected[r["id"]]["status"] == "READY")
                    or (
                        r.get("enabled")
                        and r["final_stem"] != expected[r["id"]].get("base_name")
                    )
                    for r in current
                )
                if changed or state["preview_form"] != (
                    template.value,
                    target_mode.value,
                    folder.value,
                    missing.value,
                ):
                    await regenerate()
                    ui.notify(
                        "已按最新逐篇修改重新预检，请核对新路径后再次确认执行。",
                        type="warning",
                    )
                    return
                # The exact original fingerprint is passed; the service rejects
                # edited, stale or conflicting previews before moving any byte.
                receipt = self.submit(
                    "rename",
                    f"重命名/移动 {preview_value['executable']} 篇",
                    ids,
                    lambda c: (
                        c.checkpoint(),
                        self.ctx.library.execute_rename(preview_value),
                    )[1],
                    {"preview": preview_value},
                )
                status.set_text(
                    f"已提交实际文件操作 {receipt.get('job_id', receipt.get('id'))}；恢复记录保存在任务中心。"
                )
                state["preview"] = None

            def load_result():
                if not dialog.value or not state["job"] or state["loaded"]:
                    return
                job = self.ctx.jobs.get(state["job"])
                result = job.get("result") or {}
                if result.get("preview"):
                    state["loaded"] = True
                    display_preview(result["preview"])
                elif job["status"] in {"FAILED", "INTERRUPTED", "CANCELLED"}:
                    state["loaded"] = True
                    status.set_text(
                        f"翻译任务{value_label(job['status'])}，请在任务中心查看具体原因并重新生成预览。"
                    )

            ui.timer(2, guard(load_result))
            with ui.row().classes("an-toolbar"):
                ui.button("生成完整预览", icon="preview", on_click=guard(preview))
                ui.button("应用逐篇修改并重做预检", on_click=guard(regenerate)).props(
                    "outline"
                )
                ui.button(
                    "确认执行磁盘重命名 / 移动",
                    icon="drive_file_rename_outline",
                    on_click=guard(execute),
                ).props("outline")
                ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()
