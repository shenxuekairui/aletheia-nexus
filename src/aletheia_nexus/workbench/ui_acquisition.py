"""Paper acquisition UI; all retrieval routes stay in AN's existing engine."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .labels import GRID_LOCALE, value_label
from .ui_common import guard, json_view, parameter_editor, rows_table, split_tags
from .ui_grids import read_edited_grid


def acquisition_workflow_preferences(value=None, *, translation_defaults=None):
    """Persist a workflow choice, never the permission granted for one request."""
    from aletheia_nexus.core.organization import normalize_folder

    from .library import LibraryService
    from .translation import translation_options

    value = {} if value is None else deepcopy(value)
    if not isinstance(value, dict) or value.keys() - {
        "template",
        "folder",
        "tags",
        "collection",
        "auto_parse",
        "title_translation",
    }:
        raise ValueError("获取工作流偏好包含不支持的设置。")
    template = value.get("template", "{title_original}")
    LibraryService._check_template(template)
    folder = normalize_folder(value.get("folder") or None) or ""
    tags = value.get("tags", [])
    if not isinstance(tags, (list, tuple)) or any(
        not isinstance(t, str)
        or not t.strip()
        or len(t) > 80
        or any(ord(c) < 32 for c in t)
        for t in tags
    ):
        raise ValueError("标签必须是非空文本列表，每个标签最多80个字符。")
    collection = value.get("collection", "")
    if not isinstance(collection, str) or len(collection) > 120:
        raise ValueError("固定研究集合名称必须是最多120个字符的文本。")
    automatic = value.get("auto_parse", False)
    translated = value.get("title_translation", {})
    if translated is None:
        translated = {}
    if not isinstance(translated, dict) or translated.keys() - {
        "enabled",
        "options",
        "consent",
    }:
        raise ValueError("标题翻译偏好包含不支持的设置。")
    enabled = translated.get("enabled", False)
    if type(automatic) is not bool or type(enabled) is not bool:
        raise ValueError("自动解析和自动标题翻译偏好必须为开启或关闭。")
    return {
        "template": template,
        "folder": folder,
        "tags": list(dict.fromkeys(t.strip() for t in tags)),
        "collection": collection.strip(),
        "auto_parse": automatic,
        "title_translation": {
            "enabled": enabled,
            "options": translation_options(
                translated.get("options", translation_defaults)
            ),
        },
    }


def acquisition_recipe(parameters, workflow=None, *, translation_defaults=None):
    from .acquisition import _options

    return {
        "parameters": _options(parameters),
        "workflow": acquisition_workflow_preferences(
            workflow, translation_defaults=translation_defaults
        ),
    }


def read_acquisition_preset(
    value, *, workflow_defaults=None, translation_defaults=None
):
    """Read new recipes and the previous flat engine-only preset format."""
    if not isinstance(value, dict):
        raise ValueError("获取预设必须是一组命名参数。")
    if "parameters" in value or "workflow" in value:
        if value.keys() - {"parameters", "workflow"}:
            raise ValueError("获取预设包含不支持的设置。")
        return acquisition_recipe(
            value.get("parameters", {}),
            value.get("workflow", workflow_defaults),
            translation_defaults=translation_defaults,
        )
    return acquisition_recipe(
        value, workflow_defaults, translation_defaults=translation_defaults
    )


def acquisition_postprocess_snapshot(workflow, parser_defaults, parser_overrides=None):
    """Freeze local parsing scope at submission; keep it outside engine options."""
    result = deepcopy(workflow)
    if result.get("auto_parse"):
        if not isinstance(parser_defaults, dict) or (
            parser_overrides is not None and not isinstance(parser_overrides, dict)
        ):
            raise ValueError("自动解析设置必须是一组命名参数。")
        result["parse_options"] = deepcopy(
            {**parser_defaults, **(parser_overrides or {})}
        )
    return result


class AcquisitionPage:
    def title_translation_controls(
        self, initial_options=None, *, initial_enabled=False
    ):
        from nicegui import ui

        from .translation import translation_options

        current = translation_options(
            initial_options or self.ctx.settings.get("translation", {})
        )
        enabled = ui.checkbox(
            "入库后自动翻译缺失的英文标题", value=bool(initial_enabled)
        )
        cost = ui.number(
            "本批标题翻译费用上限（按模型计费币种）",
            value=current["max_cost"],
            min=0.01,
        ).bind_visibility_from(enabled, "value")
        consent = ui.checkbox(
            "我授权仅将待翻译的英文标题发送给DeepSeek，并接受所示费用上限", value=False
        ).bind_visibility_from(enabled, "value")
        with (
            ui.expansion("标题翻译高级参数", icon="translate")
            .classes("w-full")
            .bind_visibility_from(enabled, "value")
        ):
            read = parameter_editor(
                {k: v for k, v in current.items() if k != "max_cost"}
            )

        def options(require_consent=True):
            if require_consent and enabled.value and not consent.value:
                raise ValueError("请明确授权标题外发与费用，或关闭入库后自动翻译")
            result = {
                "enabled": enabled.value,
                "options": translation_options({**read(), "max_cost": cost.value}),
            }
            if require_consent:
                result["consent"] = bool(consent.value)
            return result

        def validate(configuration):
            configuration = acquisition_workflow_preferences(
                {"title_translation": configuration}
            )["title_translation"]
            read._pending_updates(
                {k: v for k, v in configuration["options"].items() if k != "max_cost"}
            )
            return configuration

        def apply(configuration):
            configuration = validate(configuration)
            read.apply(
                {k: v for k, v in configuration["options"].items() if k != "max_cost"}
            )
            cost.set_value(configuration["options"]["max_cost"])
            enabled.set_value(configuration["enabled"])
            consent.set_value(False)

        options.apply = apply
        options.validate = validate
        options.clear_consent = lambda: consent.set_value(False)

        return options

    def translate_missing_english(self, ids, configuration, context):
        from aletheia_nexus.acquire.metadata.titles import contains_cjk

        if not configuration.get("enabled"):
            return {"status": "NOT_REQUESTED", "calls": []}
        wanted = set(ids)
        pending = [
            r["id"]
            for r in self.ctx.library.scan()["items"]
            if r["id"] in wanted
            and not r.get("title_zh")
            and not contains_cjk(r.get("title_original") or r["title"])
        ]
        if not pending:
            return {"status": "COMPLETED", "items": [], "calls": [], "pending": 0}
        context.checkpoint()
        context.progress(
            0, len(pending), stage="仅翻译缺失英文标题", billing_uncertain=True
        )
        from .jobs import TaskCancelled

        try:
            report = self.ctx.translation.translate(
                pending,
                configuration.get("options"),
                consent=bool(configuration.get("consent")),
                context=context,
            )
        except TaskCancelled:
            raise
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            uncertain = code != "missing_api_key"
            context.record("title_translation", "FAILED", code=code)
            context.progress(
                0,
                len(pending),
                stage="标题翻译失败，已入库文献保留",
                billing_uncertain=uncertain,
            )
            return {
                "status": "FAILED",
                "code": code,
                "billing_uncertain": uncertain,
                "calls": None if uncertain else [],
            }
        context.progress(
            len(pending),
            len(pending),
            stage="标题翻译完成",
            billing_uncertain=report.get("billing_uncertain", False),
        )
        return report

    def acquisition_worker(
        self, requests, options, postprocess, *, checkpoint_path=None
    ):
        """One application path for initial acquisition and reviewed recovery."""
        requests, options, postprocess = (
            deepcopy(requests),
            deepcopy(options),
            deepcopy(postprocess),
        )

        def worker(context):
            report = self.ctx.acquisition.run(
                requests, options, context=context, checkpoint_path=checkpoint_path
            )
            context.progress(
                stage="整理已获取论文",
                task_phase="postprocess",
                current={},
                item="",
            )
            successful = {
                r.get("pdf_path", r.get("pdf")): r
                for r in report["items"]
                if r.get("status") == "VERIFIED"
            }
            papers = [
                r
                for r in self.ctx.library.scan()["items"]
                if r["pdf_path"] in successful
            ]
            paper_ids = [r["id"] for r in papers]
            translated = self.translate_missing_english(
                paper_ids, postprocess.get("title_translation", {}), context
            )
            report["translation"] = translated
            if translated["status"] in {"PARTIAL", "FAILED"}:
                report["status"] = "PARTIAL"
            template = postprocess.get("template")
            if template:
                # The download engine has now resolved real bibliographic metadata.
                # A DOI-only input must never force the DOI itself as the title.
                rename_ids = [
                    r["id"]
                    for r in papers
                    if not (successful[r["pdf_path"]].get("request") or {}).get(
                        "filename"
                    )
                ]
                if rename_ids:
                    context.checkpoint()
                    context.progress(0, len(rename_ids), stage="自动命名正文与关联SI")
                    preview = self.ctx.library.preview_rename(
                        rename_ids, template, missing_translation="fallback"
                    )
                    organized = self.ctx.library.execute_rename(preview)
                    report["organization"] = organized
                    if preview["skipped"] or organized.get("status") != "COMPLETED":
                        report["status"] = "PARTIAL"
                    for paper in papers:
                        current = self.ctx.library.get(paper["id"])
                        if current:
                            row = successful[paper["pdf_path"]]
                            row.update(
                                pdf=current["pdf_path"],
                                sidecar=current["sidecar_path"],
                                folder=str(Path(current["pdf_path"]).parent),
                            )
                            attachments = {
                                (a["sha256"], a["role"]): a
                                for a in current.get("attachments", [])
                            }
                            supplements = row.get("supplements") or {}
                            for attachment in supplements.get("items", []):
                                current_attachment = attachments.get(
                                    (attachment.get("sha256"), attachment.get("role"))
                                )
                                if current_attachment:
                                    attachment["original_retrieval_path"] = (
                                        attachment.get("path")
                                    )
                                    attachment["path"] = current_attachment["path"]
                            if current.get("attachments"):
                                supplements["si_directory"] = str(
                                    Path(current["pdf_path"]).parent / "SI"
                                )
                            # A later parse/cancellation must not leave the
                            # durable item receipt pointing at pre-rename files.
                            context.record(
                                row.get("id", paper["id"]),
                                row["status"],
                                **{
                                    k: v
                                    for k, v in row.items()
                                    if k not in {"id", "status"}
                                },
                            )
            collection_name = postprocess.get("collection")
            if collection_name and paper_ids:
                old = self.ctx.library.collections().get(collection_name, [])
                self.ctx.library.save_collection(
                    collection_name, list(dict.fromkeys([*old, *paper_ids]))
                )
            if postprocess.get("auto_parse") and paper_ids:
                parse_options = deepcopy(postprocess.get("parse_options"))
                if parse_options is None:
                    # Historical trusted callers may lack a snapshot. The UI
                    # recovery dialog creates a reviewed snapshot before submit;
                    # never fetch mutable settings from this worker.
                    report.setdefault("warnings", []).append(
                        "历史任务未记录解析配置；本次仅使用内置解析默认，不读取运行中的全局设置。"
                    )
                parsed = self.ctx.research.parse(
                    paper_ids,
                    options=parse_options,
                    context=context,
                    include_si=options["include_si"],
                )
                report["parsing"] = parsed
                if parsed["status"] != "COMPLETED":
                    report["status"] = "PARTIAL"
            return report

        return worker

    def acquisition_page(self):
        from nicegui import ui

        from .acquisition import _options

        self.title(
            "获取论文",
            "先确认论文身份，再交给现有可信获取引擎；正文与 SI 分别报告结果。",
        )
        from .ui_acquisition_batch import AcquisitionBatchEditor
        from .ui_folders import choose_library_folder

        draft = self.ctx.settings.get("acquisition_input_draft", {}) or {}
        if draft.get("library") != str(self.ctx.library.root):
            draft = {}
        example = getattr(self, "acquisition_example_text", "")
        self.acquisition_example_text = ""
        if example:
            draft = {}
        state = {
            "preview": None,
            "grid": None,
            "batch": None,
            "dirty": draft.get("dirty", False),
            "placement_refresh": lambda *_: None,
        }
        defaults = _options(self.ctx.settings.get("acquisition", {}))
        workflow_defaults = acquisition_workflow_preferences(
            self.ctx.settings.get("acquisition_workflow", {}),
            translation_defaults=self.ctx.settings.get("translation", {}),
        )
        if draft:
            workflow_defaults["folder"] = draft.get(
                "default_folder", workflow_defaults["folder"]
            )
            workflow_defaults["tags"] = draft.get(
                "default_tags", workflow_defaults["tags"]
            )
        with ui.row().classes("w-full an-acquisition-layout"):
            with ui.card().classes("an-card min-w-0 w-full"):
                ui.label("1 · 添加论文").classes("font-semibold text-lg")
                value = (
                    ui.textarea(
                        "粘贴 DOI、标题或分组文献清单",
                        value=example or draft.get("text", ""),
                    )
                    .classes("w-full")
                    .props(
                        'outlined rows=7 placeholder="A. 羧酸电还原\\n1. 10.xxxx/...\\n2. 10.xxxx/... | 标签=草酸,待读\\nB. 催化机理\\n1. 10.xxxx/..."'
                    )
                )
                ui.label(
                    "可直接粘贴编号清单；分组标题作为分类。每行可补充：| 分类=已有或新目录 | 标签=标签1,标签2"
                ).classes("an-muted text-sm")
                input_status = ui.label("").classes("text-orange-9 text-sm")

                def save_draft(rows=None):
                    self.ctx.settings.set(
                        "acquisition_input_draft",
                        {
                            "library": str(self.ctx.library.root),
                            "text": value.value or "",
                            "report": state["preview"],
                            "rows": rows
                            if rows is not None
                            else (state["batch"].rows if state["batch"] else []),
                            "default_folder": folder.value or "",
                            "default_tags": split_tags(tags.value),
                            "dirty": state["dirty"],
                            "preview_text": state.get("preview_text"),
                        },
                    )
                    state["placement_refresh"](rows)

                def preview_input(
                    text=None, format=None, restored=None, report_override=None
                ):
                    if text is not None:
                        value.set_value(text)
                    report = (
                        restored["report"]
                        if restored
                        else report_override
                        if report_override is not None
                        else self.ctx.acquisition.preview_inputs(
                            value.value if text is None else text, format=format
                        )
                    )
                    state["preview"] = report
                    state["preview_text"] = (
                        restored.get("preview_text", value.value)
                        if restored
                        else value.value
                    )
                    state["dirty"] = value.value != state["preview_text"]
                    input_status.set_text(
                        "输入已修改，请重新预览文献。" if state["dirty"] else ""
                    )
                    data = []
                    for entry in report["items"]:
                        if entry["duplicate"]:
                            continue
                        request = entry["request"]
                        data.append(
                            {
                                "id": entry["id"],
                                "enabled": not entry["duplicate"],
                                "doi": request.get("doi") or "",
                                "title": request.get("title") or "",
                                "folder": request.get("folder") or "",
                                "tags": ", ".join(request.get("tags") or []),
                                "filename": request.get("filename") or "",
                                "input_group": entry.get("group")
                                or request.get("folder")
                                or "未分组",
                                "folder_mode": (entry.get("assignment") or {}).get(
                                    "folder_mode",
                                    "custom" if request.get("folder") else "inherit",
                                ),
                                "tags_mode": (entry.get("assignment") or {}).get(
                                    "tags_mode",
                                    "custom" if request.get("tags") else "inherit",
                                ),
                                "resolution": "DOI"
                                if request.get("doi")
                                else "待解析标题",
                            }
                        )
                    if restored:
                        data = restored["rows"]
                    preview_area.clear()
                    with preview_area:
                        ui.label(
                            f"{report['count']} 篇去重候选；{len(report['errors'])} 项输入错误。"
                        )
                        for warning in report.get("warnings", []):
                            ui.label(
                                warning
                                if isinstance(warning, str)
                                else warning.get("message", str(warning))
                            ).classes("an-info w-full")
                        if report.get("conflicts"):
                            ui.label(
                                "同一篇论文有多份不同保存安排：请统一设置并只启用一行，或停用重复行；不会按首条静默决定。"
                            ).classes("an-info w-full")
                        state["grid"] = ui.aggrid(
                            {
                                "localeText": GRID_LOCALE,
                                "stopEditingWhenCellsLoseFocus": True,
                                "columnDefs": [
                                    {
                                        "colId": "_select",
                                        "headerName": "选择",
                                        "checkboxSelection": True,
                                        "headerCheckboxSelection": True,
                                        "headerCheckboxSelectionFilteredOnly": True,
                                        "pinned": "left",
                                        "width": 72,
                                    },
                                    {
                                        "field": "enabled",
                                        "headerName": "获取状态",
                                        "cellDataType": False,
                                        ":valueFormatter": "p => p.value ? '将获取' : '已停用'",
                                        "width": 100,
                                    },
                                    *(
                                        {
                                            "field": k,
                                            "headerName": label,
                                            "editable": k
                                            in {"doi", "title", "filename"},
                                            "width": width,
                                            **(
                                                {
                                                    ":valueFormatter": "p => p.data.folder_mode === 'root' ? '文库根目录' : p.data.folder_mode === 'inherit' ? (p.data.effective_folder || '文库根目录') + '（默认）' : p.value",
                                                    ":valueSetter": "p => { p.data.folder = String(p.newValue || '').trim(); p.data.folder_mode = p.data.folder ? 'custom' : 'root'; return true; }",
                                                }
                                                if k == "folder"
                                                else {}
                                            ),
                                            **(
                                                {
                                                    ":valueFormatter": "p => p.data.tags_mode === 'inherit' ? (p.data.effective_tags || '无标签') + '（默认）' : (p.value || '无标签')",
                                                    ":valueSetter": "p => { p.data.tags = String(p.newValue || '').trim(); p.data.tags_mode = 'custom'; return true; }",
                                                }
                                                if k == "tags"
                                                else {}
                                            ),
                                            **(
                                                {"hide": True}
                                                if k
                                                in {
                                                    "input_group",
                                                    "filename",
                                                    "placement_error",
                                                }
                                                else {}
                                            ),
                                            **(
                                                {
                                                    "hide": not any(
                                                        r["title"] for r in data
                                                    )
                                                }
                                                if k == "title"
                                                else {}
                                            ),
                                            **(
                                                {"hide": all(r["doi"] for r in data)}
                                                if k == "resolution"
                                                else {}
                                            ),
                                            **(
                                                {"filter": "agTextColumnFilter"}
                                                if k == "input_group"
                                                else {}
                                            ),
                                        }
                                        for k, label, width in (
                                            ("doi", "DOI", 210),
                                            ("title", "标题", 260),
                                            ("folder", "最终保存目录", 260),
                                            ("tags", "标签", 230),
                                            ("placement_state", "目录状态", 130),
                                            ("filename", "单篇文件基础名覆盖", 200),
                                            ("resolution", "身份阶段", 150),
                                            ("input_group", "输入分组", 180),
                                            ("placement_error", "需修正的设置", 250),
                                        )
                                    ),
                                ],
                                "rowData": data,
                                "defaultColDef": {"resizable": True},
                                "rowSelection": "multiple",
                                "suppressRowClickSelection": True,
                                "pagination": True,
                                "paginationPageSize": 25,
                                "paginationPageSizeSelector": [25, 50, 100],
                                ":getRowId": "params => params.data.id",
                            },
                            theme="quartz",
                        ).classes("h-96 w-full")
                        state["batch"] = AcquisitionBatchEditor(
                            self,
                            state["grid"],
                            report,
                            lambda: folder.value or None,
                            lambda: split_tags(tags.value),
                            save_draft,
                        )
                        state["batch"].rows = state["batch"].decorate(data)
                        state["grid"].options["rowData"] = state["batch"].rows
                        state["grid"].update()
                        state["batch"].render_tools()
                        save_draft(state["batch"].rows)

                        async def edit_row(event):
                            if event.args["colDef"].get("field") not in {
                                "folder",
                                "tags",
                            }:
                                return
                            await guard(
                                lambda: state["batch"].open_row(
                                    event.args["data"]["id"]
                                )
                            )()

                        state["grid"].on(
                            "cellDoubleClicked", edit_row, args=["data", "colDef"]
                        )
                        ui.timer(0.2, guard(state["batch"].refresh_count), once=True)
                        if report["errors"]:
                            rows_table(report["errors"], row_key="line")
                        if any(not row["doi"] for row in data):
                            ui.label(
                                "没有 DOI 的标题需先确认书目候选；PDF 获取后再解析原文。"
                            ).classes("an-muted text-xs")
                            ui.button(
                                "解析 / 确认当前选中标题",
                                icon="manage_search",
                                on_click=guard(resolve_title),
                            ).props("outline")

                async def uploaded(event):
                    text = await event.file.text(encoding="utf-8-sig")
                    preview_input(
                        text, Path(event.file.name).suffix.lstrip(".").lower()
                    )

                with ui.row().classes("an-toolbar"):
                    ui.button(
                        "手动整理并预览",
                        icon="fact_check",
                        on_click=guard(preview_input),
                    )

                    async def normalization_snapshot():
                        return {
                            "text": value.value or "",
                            "rows": await read_edited_grid(state["grid"])
                            if state["grid"] is not None
                            else [],
                            "default_folder": folder.value or "",
                            "default_tags": split_tags(tags.value),
                            "library": str(self.ctx.library.root),
                        }

                    def normalize_with_model():
                        from .ui_input_normalization import normalization_dialog

                        normalization_dialog(
                            self,
                            normalization_snapshot,
                            lambda report: preview_input(report_override=report),
                            text_hint=value.value or "",
                        )

                    ui.button(
                        "AI 整理输入",
                        icon="auto_awesome",
                        on_click=guard(normalize_with_model),
                    ).props("outline")
                    ui.button(
                        "导入已有 PDF",
                        icon="upload_file",
                        on_click=guard(self.import_dialog),
                    ).props("flat")

                    def clear_input():
                        state.update(preview=None, grid=None, batch=None, dirty=False)
                        value.set_value("")
                        preview_area.clear()
                        save_draft([])

                    ui.button(
                        "清空本批", icon="clear", on_click=guard(clear_input)
                    ).props("flat")
                ui.label(
                    "输入和逐篇设置自动保存在本地，切换页面或刷新后可继续；不会自动启动下载。"
                ).classes("an-muted text-xs")
                ui.upload(
                    label="或导入 TXT / CSV / JSON",
                    on_upload=uploaded,
                    auto_upload=True,
                    max_file_size=5_000_000,
                ).props('accept=".txt,.csv,.json"').classes("w-full")
                preview_area = ui.column().classes("w-full")
                acquisition_actions = ui.column().classes("w-full gap-3")
            with ui.card().classes("an-card min-w-0 w-full"):
                ui.label("2 · 分类与保存").classes("font-semibold text-lg")
                ui.label(str(self.ctx.library.root)).classes(
                    "an-muted text-xs break-all"
                )
                from .ui_acquisition_groups import render_acquisition_groups

                state["placement_refresh"] = render_acquisition_groups(
                    self, lambda: state["batch"], preview_input
                )
                folder = (
                    ui.input(
                        "批次默认目录（未单独指定时）",
                        value=workflow_defaults["folder"],
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                ui.button(
                    "选已有目录 / 新建子目录",
                    icon="create_new_folder",
                    on_click=guard(
                        lambda: choose_library_folder(
                            self.ctx.library,
                            folder.set_value,
                            initial=folder.value or "",
                        )
                    ),
                ).props("outline")
                tags = (
                    ui.input(
                        "批次默认标签（逗号分隔）",
                        value=", ".join(workflow_defaults["tags"]),
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                ui.label(
                    "这是批次默认值。分组、行内设置或逐篇编辑优先；预览中会显示各篇最终安排。"
                ).classes("an-muted text-sm")
                collection = (
                    ui.input(
                        "成功论文加入固定研究集合（可选）",
                        value=workflow_defaults["collection"],
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                from .ui_naming import NamingTemplateControl

                naming = NamingTemplateControl(
                    self.ctx.library, workflow_defaults["template"]
                )
                ui.label(
                    "缺失译名或书目信息时回退已有原题；入库后可在整理流程补齐译名并预览改名。"
                ).classes("an-muted text-xs")
                include_si = ui.switch("同时尝试获取 SI", value=defaults["include_si"])
                auto_parse = ui.switch(
                    "成功后自动创建本地解析", value=workflow_defaults["auto_parse"]
                )
                read_translation = self.title_translation_controls(
                    workflow_defaults["title_translation"]["options"],
                    initial_enabled=workflow_defaults["title_translation"]["enabled"],
                )
                strategy = ui.select(
                    {"public": "仅公开获取", "institution": "公开 + 机构浏览器"},
                    value="public" if defaults["public_only"] else "institution",
                    label="获取策略",
                ).classes("w-full")
                from .defaults import browser_profile_choices, browser_readiness

                readiness = ui.label(browser_readiness(defaults)["message"]).classes(
                    "an-muted text-xs"
                )
                with ui.expansion("来源与登录处理（可选）", icon="tune").classes(
                    "w-full"
                ):
                    sessions = browser_profile_choices(defaults["browser"])
                    profile = ui.select(
                        sessions["options"],
                        value=sessions["current"]
                        if sessions["current"] in sessions["options"]
                        else None,
                        label="浏览器登录会话",
                        with_input=True,
                        new_value_mode="add-unique",
                    ).classes("w-full")
                    ui.label(sessions["message"]).classes("an-muted text-xs")
                    for warning in sessions["warnings"]:
                        ui.label(warning).classes("text-orange-9 text-xs")
                    source = ui.select(
                        {
                            "auto": "自动来源（可用时含CNKI）",
                            "cnki": "指定CNKI",
                            "exclude_cnki": "排除CNKI",
                        },
                        value=defaults["source_preference"],
                        label="来源策略",
                    ).classes("w-full")
                    interaction = ui.select(
                        {
                            "wait": "等待人工登录 / 验证",
                            "skip": "跳过并继续后续论文",
                            "pause": "暂停批次，等待人工决定",
                        },
                        value=defaults["interaction_policy"],
                        label="需要人工操作时",
                    ).classes("w-full")
                    timeout = ui.number(
                        "交互等待（秒；0表示不限时）",
                        value=defaults["interaction_timeout"],
                        min=0,
                    )

        def text_changed():
            if state["preview"]:
                state["dirty"] = value.value != state.get("preview_text")
            input_status.set_text(
                "输入已修改，请重新预览文献。" if state["dirty"] else ""
            )
            save_draft()

        value.on_value_change(guard(text_changed))
        value.on("keydown.ctrl.enter", guard(preview_input))
        folder.on_value_change(
            guard(lambda: state["batch"].refresh() if state["batch"] else save_draft())
        )
        tags.on_value_change(
            guard(lambda: state["batch"].refresh() if state["batch"] else save_draft())
        )
        excluded = {
            "include_si",
            "public_only",
            "browser_enabled",
            "source_preference",
            "interaction_policy",
            "interaction_timeout",
        }
        with ui.expansion(
            "高级 · 超时、间隔、重试、路线和机构浏览器配置", icon="tune"
        ).classes("w-full an-card"):
            ui.label(
                "普通论文间隔控制开始下一篇的时间；CNKI间隔只用于CNKI路线，失败退避用于重试。"
                "站点限流和权限拒绝仍服从既有边界。"
            )
            advanced_defaults = {
                k: deepcopy(v) for k, v in defaults.items() if k not in excluded
            }
            advanced_defaults["browser"].pop("profile_name")
            read_advanced = parameter_editor(advanced_defaults)
        with ui.expansion("任务预设", icon="bookmarks").classes("w-full"):
            preset = ui.select(
                ["", *self.ctx.settings.presets("acquisition")],
                value="",
                label="载入预设",
            )
            preset_name = ui.input("保存为预设名称")
            ui.label(
                "预设载入实际表单，保留当前论文清单；标题外发与费用授权每次重新勾选。"
            )

            def load_preset():
                if not preset.value:
                    raise ValueError("请先选择获取预设。")
                apply_recipe(self.ctx.settings.load_preset("acquisition", preset.value))

            ui.button("载入并显示", on_click=guard(load_preset)).props("flat")

        def options():
            if strategy.value == "institution" and not profile.value:
                raise ValueError("请先选择或输入有效的浏览器登录会话名称。")
            advanced = read_advanced()
            advanced["browser"]["profile_name"] = (
                profile.value or defaults["browser"]["profile_name"]
            )
            return _options(
                {
                    **advanced,
                    "include_si": include_si.value,
                    "public_only": strategy.value == "public",
                    "browser_enabled": strategy.value == "institution",
                    "source_preference": source.value,
                    "interaction_policy": interaction.value,
                    "interaction_timeout": timeout.value,
                }
            )

        def check_browser_configuration():
            report = browser_readiness(options())
            readiness.set_text(report["message"])
            return report

        strategy.on_value_change(guard(check_browser_configuration))
        with readiness.parent_slot:
            ui.button(
                "检查本次浏览器配置",
                icon="fact_check",
                on_click=guard(check_browser_configuration),
            ).props("flat dense size=sm")

        def workflow(require_consent=True):
            translated = read_translation(require_consent=require_consent)
            result = acquisition_workflow_preferences(
                {
                    "template": naming.value,
                    "folder": folder.value,
                    "tags": split_tags(tags.value),
                    "collection": collection.value,
                    "auto_parse": auto_parse.value,
                    "title_translation": translated,
                }
            )
            if require_consent:
                result["title_translation"]["consent"] = translated["consent"]
            return result

        def apply_recipe(value):
            legacy = "parameters" not in value and "workflow" not in value
            recipe = read_acquisition_preset(value, workflow_defaults=workflow_defaults)
            engine, preferences = recipe["parameters"], recipe["workflow"]
            advanced = {k: deepcopy(v) for k, v in engine.items() if k not in excluded}
            advanced["browser"].pop("profile_name")
            read_advanced._pending_updates(advanced)
            if not legacy:
                read_translation.validate(preferences["title_translation"])
            read_advanced.apply(advanced)
            include_si.set_value(engine["include_si"])
            strategy.set_value("public" if engine["public_only"] else "institution")
            if engine["browser"]["profile_name"] not in profile.options:
                profile.set_options(
                    [*profile.options, engine["browser"]["profile_name"]]
                )
            profile.set_value(engine["browser"]["profile_name"])
            source.set_value(engine["source_preference"])
            interaction.set_value(engine["interaction_policy"])
            timeout.set_value(engine["interaction_timeout"])
            check_browser_configuration()
            if legacy:
                read_translation.clear_consent()
                ui.notify(
                    "旧版获取预设已载入；当前整理偏好保留，本次费用授权已清除。",
                    type="positive",
                )
                return
            folder.set_value(preferences["folder"])
            tags.set_value(", ".join(preferences["tags"]))
            collection.set_value(preferences["collection"])
            auto_parse.set_value(preferences["auto_parse"])
            naming.apply(preferences["template"])
            read_translation.apply(preferences["title_translation"])
            ui.notify("获取参数及整理偏好已载入；本次费用授权未复用。", type="positive")

        def save_preset():
            recipe = acquisition_recipe(options(), workflow(require_consent=False))
            self.ctx.settings.save_preset("acquisition", preset_name.value, recipe)
            preset.set_options(
                ["", *self.ctx.settings.presets("acquisition")],
                value=preset_name.value.strip(),
            )
            ui.notify(
                "已保存获取参数、分类与后处理偏好；未保存外发授权。", type="positive"
            )

        def save_defaults():
            recipe = acquisition_recipe(options(), workflow(require_consent=False))
            self.ctx.settings.set("acquisition", recipe["parameters"])
            self.ctx.settings.set("acquisition_workflow", recipe["workflow"])
            ui.notify(
                "已保存获取默认设置与整理偏好；下次仍需重新授权标题外发。",
                type="positive",
            )

        ui.button(
            "保存当前获取预设",
            on_click=guard(save_preset),
        ).props("flat")
        ui.button(
            "保存为获取默认设置",
            on_click=guard(save_defaults),
        ).props("flat")

        async def resolve_title():
            from nicegui import run

            if state["grid"] is None:
                raise ValueError("请先预览论文")
            await read_edited_grid(state["grid"])
            selected_rows = await state["grid"].get_selected_rows()
            if len(selected_rows) != 1:
                raise ValueError("请在候选表左侧选择一篇待解析标题")
            selected = selected_rows[0]
            queried_identity = (selected["doi"], selected["title"])
            request = next(
                e["request"]
                for e in state["preview"]["items"]
                if e["id"] == selected["id"]
            )
            request = {
                **request,
                "title": selected["title"],
                "doi": selected["doi"] or None,
            }
            ui.notify("正在查询公共书目元数据…")
            report = await run.io_bound(self.ctx.acquisition.resolve_title, request)

            async def apply(candidate):
                rows = await read_edited_grid(state["grid"])
                current = next(row for row in rows if row["id"] == selected["id"])
                if (current["doi"], current["title"]) != queried_identity:
                    raise ValueError(
                        "查询期间已修改本篇 DOI 或标题，请按新内容重新查询"
                    )
                for key in ("doi", "title", "authors", "journal", "year"):
                    if candidate.get(key) is not None:
                        request[key] = candidate[key]
                original = next(
                    e for e in state["preview"]["items"] if e["id"] == selected["id"]
                )
                original["request"] = deepcopy(request)
                state["batch"].originals[selected["id"]] = deepcopy(request)
                for row in rows:
                    if row["id"] == selected["id"]:
                        row.update(
                            doi=request.get("doi") or "",
                            title=request.get("title") or "",
                            resolution=value_label(report["status"])
                            if not candidate.get("doi")
                            else "候选已确认",
                        )
                await state["batch"].replace(rows)

            if report["status"] in {"RESOLVED", "CNKI_TITLE"}:
                await apply(report["request"])
                ui.notify(
                    f"标题解析：{value_label(report['status'])}；PDF尚未获取。",
                    type="positive",
                )
            else:
                with (
                    ui.dialog() as dialog,
                    ui.card().classes("w-[1000px] max-w-[95vw]"),
                ):
                    ui.label(f"标题解析：{value_label(report['status'])}").classes(
                        "text-xl font-semibold"
                    )
                    ui.label(
                        "请核对原题、作者、年份、期刊与DOI；系统不会自动选择第一个相近结果。"
                    )
                    for candidate in report.get("candidates", []):
                        with ui.card().classes("an-card w-full"):
                            ui.label(candidate["title"]).classes("font-semibold")
                            ui.label(
                                f"{candidate.get('authors')} · {candidate.get('year')} · {candidate.get('journal')} · {candidate.get('doi')}"
                            )
                            json_view(candidate, label="匹配和冲突依据")

                            async def accept(c=candidate):
                                await apply(c)
                                dialog.close()

                            ui.button(
                                "确认是此论文",
                                on_click=guard(accept),
                            )
                    if not report.get("candidates"):
                        ui.label(
                            "未找到可靠候选。可修正书目信息后重试，或自行提供可靠DOI。"
                        )
                    ui.button("关闭", on_click=dialog.close).props("flat")
                dialog.open()

        async def start(show_preview=False):
            if state["batch"] is None:
                raise ValueError("请先生成输入预览")
            if state["dirty"]:
                raise ValueError(
                    "输入文字已修改，请先重新预览；逐篇目录和标签编辑可直接生效"
                )
            requests = await state["batch"].requests()
            config = options()
            postprocess = acquisition_postprocess_snapshot(
                workflow(),
                self.ctx.research.parser_options(),
                self.ctx.settings.get("parsing", {}),
            )

            def submit():
                self.submit(
                    "acquisition",
                    f"获取 {len(requests)} 篇论文",
                    [r.get("doi") or r["title"] for r in requests],
                    self.acquisition_worker(requests, config, postprocess),
                    {
                        "library": str(self.ctx.library.root),
                        "requests": requests,
                        "options": config,
                        "postprocess": postprocess,
                    },
                )

            if show_preview:
                state["batch"].confirm(
                    requests, submit, include_si=config["include_si"]
                )
            else:
                submit()

        with acquisition_actions:
            with ui.row().classes("an-toolbar"):
                ui.button(
                    "开始获取已启用论文", icon="download", on_click=guard(start)
                ).props("size=lg")
                ui.button(
                    "查看完整保存安排",
                    icon="folder_open",
                    on_click=guard(lambda: start(True)),
                ).props("outline")
            from .ui_acquisition_progress import AcquisitionProgressPanel

            AcquisitionProgressPanel(self)
        if draft.get("report") and draft.get("rows"):
            preview_input(restored=draft)
        if getattr(self, "open_normalization_on_acquire", False):
            self.open_normalization_on_acquire = False
            normalize_with_model()
