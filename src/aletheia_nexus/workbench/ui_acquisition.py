"""Paper acquisition UI; all retrieval routes stay in AN's existing engine."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .labels import GRID_LOCALE, value_label
from .ui_common import guard, json_view, parameter_editor, rows_table, split_tags


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
        )
        consent = ui.checkbox(
            "我授权仅将待翻译的英文标题发送给DeepSeek，并接受所示费用上限", value=False
        )
        with ui.expansion("标题翻译高级参数", icon="translate").classes("w-full"):
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
        state = {"preview": None, "grid": None}
        defaults = _options(self.ctx.settings.get("acquisition", {}))
        workflow_defaults = acquisition_workflow_preferences(
            self.ctx.settings.get("acquisition_workflow", {}),
            translation_defaults=self.ctx.settings.get("translation", {}),
        )
        with ui.row().classes("w-full gap-5 items-start"):
            with ui.card().classes("an-card grow min-w-[450px]"):
                ui.label("1 · 添加论文").classes("font-semibold text-lg")
                value = (
                    ui.textarea("DOI、中英文标题或文献清单（每行一篇）")
                    .classes("w-full")
                    .props('outlined rows=7 placeholder="10.xxxx/... 或完整标题"')
                )

                def preview_input(text=None, format=None):
                    report = self.ctx.acquisition.preview_inputs(
                        value.value if text is None else text, format=format
                    )
                    state["preview"] = report
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
                                "resolution": "DOI"
                                if request.get("doi")
                                else "待解析标题",
                            }
                        )
                    preview_area.clear()
                    with preview_area:
                        ui.label(
                            f"{report['count']} 篇去重候选；{len(report['errors'])} 项输入错误。"
                        )
                        state["grid"] = ui.aggrid(
                            {
                                "localeText": GRID_LOCALE,
                                "columnDefs": [
                                    {
                                        "field": "enabled",
                                        "headerName": "获取",
                                        "editable": True,
                                        "width": 80,
                                    },
                                    *(
                                        {
                                            "field": k,
                                            "headerName": label,
                                            "editable": k != "resolution",
                                            "width": width,
                                        }
                                        for k, label, width in (
                                            ("doi", "DOI", 210),
                                            ("title", "标题", 380),
                                            ("folder", "单篇分类覆盖", 160),
                                            ("tags", "单篇标签覆盖", 160),
                                            ("filename", "单篇文件基础名覆盖", 200),
                                            ("resolution", "身份阶段", 150),
                                        )
                                    ),
                                ],
                                "rowData": data,
                                "defaultColDef": {"resizable": True},
                                "rowSelection": "single",
                                ":getRowId": "params => params.data.id",
                            },
                            theme="quartz",
                        ).classes("h-72 w-full")
                        if report["errors"]:
                            rows_table(report["errors"], row_key="line")
                        ui.label(
                            "无DOI的英文标题须先解析并确认候选；中文标题沿用CNKI书目身份流程。"
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
                        "规范化与预览", icon="fact_check", on_click=guard(preview_input)
                    )
                    ui.button(
                        "导入已有 PDF",
                        icon="upload_file",
                        on_click=guard(self.import_dialog),
                    ).props("flat")
                ui.upload(
                    label="或导入 TXT / CSV / JSON",
                    on_upload=uploaded,
                    auto_upload=True,
                    max_file_size=5_000_000,
                ).props('accept=".txt,.csv,.json"').classes("w-full")
            with ui.card().classes("an-card w-[390px] max-w-full"):
                ui.label("2 · 分类与保存").classes("font-semibold text-lg")
                ui.label(str(self.ctx.library.root)).classes(
                    "an-muted text-xs break-all"
                )
                folder = (
                    ui.input(
                        "分类目录（可直接输入新分类）",
                        value=workflow_defaults["folder"],
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                tags = (
                    ui.input(
                        "标签（逗号分隔）", value=", ".join(workflow_defaults["tags"])
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                collection = (
                    ui.input(
                        "成功论文加入固定研究集合（可选）",
                        value=workflow_defaults["collection"],
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                templates = self.ctx.library.templates()
                naming_options = {v: k for k, v in templates.items()}
                naming_options.setdefault(
                    workflow_defaults["template"], "已保存的命名格式"
                )
                naming = ui.select(
                    naming_options,
                    value=workflow_defaults["template"],
                    label="主文与 SI 统一命名模板",
                ).classes("w-full")
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
        preview_area = ui.column().classes("w-full")
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
            read_advanced = parameter_editor(
                {k: v for k, v in defaults.items() if k not in excluded},
            )
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
            return _options(
                {
                    **read_advanced(),
                    "include_si": include_si.value,
                    "public_only": strategy.value == "public",
                    "browser_enabled": strategy.value == "institution",
                    "source_preference": source.value,
                    "interaction_policy": interaction.value,
                    "interaction_timeout": timeout.value,
                }
            )

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
            advanced = {k: v for k, v in engine.items() if k not in excluded}
            read_advanced._pending_updates(advanced)
            if not legacy:
                read_translation.validate(preferences["title_translation"])
            read_advanced.apply(advanced)
            include_si.set_value(engine["include_si"])
            strategy.set_value("public" if engine["public_only"] else "institution")
            source.set_value(engine["source_preference"])
            interaction.set_value(engine["interaction_policy"])
            timeout.set_value(engine["interaction_timeout"])
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
            choices = dict(naming.options)
            choices.setdefault(preferences["template"], "预设命名格式")
            naming.set_options(choices, value=preferences["template"])
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
            selected = await state["grid"].get_selected_row()
            if not selected:
                raise ValueError("请在候选表中单击一篇待解析标题")
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

            def apply(candidate):
                for key in ("doi", "title", "authors", "journal", "year"):
                    if candidate.get(key) is not None:
                        request[key] = candidate[key]
                original = next(
                    e for e in state["preview"]["items"] if e["id"] == selected["id"]
                )
                original["request"] = deepcopy(request)
                rows = state["grid"].options["rowData"]
                for row in rows:
                    if row["id"] == selected["id"]:
                        row.update(
                            doi=request.get("doi") or "",
                            title=request.get("title") or "",
                            resolution=value_label(report["status"])
                            if not candidate.get("doi")
                            else "候选已确认",
                        )
                state["grid"].update()

            if report["status"] in {"RESOLVED", "CNKI_TITLE"}:
                apply(report["request"])
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
                            ui.button(
                                "确认是此论文",
                                on_click=guard(
                                    lambda c=candidate: (apply(c), dialog.close())
                                ),
                            )
                    if not report.get("candidates"):
                        ui.label(
                            "未找到可靠候选。可修正书目信息后重试，或自行提供可靠DOI。"
                        )
                    ui.button("关闭", on_click=dialog.close).props("flat")
                dialog.open()

        async def start():
            if state["grid"] is None:
                raise ValueError("请先生成输入预览")
            rows = [
                r for r in await state["grid"].get_client_data() if r.get("enabled")
            ]
            request_map = {e["id"]: e["request"] for e in state["preview"]["items"]}
            requests = []
            for row in rows:
                request = {
                    **request_map[row["id"]],
                    "doi": row["doi"] or None,
                    "title": row["title"] or None,
                    "folder": row["folder"] or folder.value or None,
                    "tags": split_tags(row["tags"] or tags.value),
                }
                if not request["doi"] and row["resolution"] == "待解析标题":
                    raise ValueError("请先解析并确认无DOI标题，避免错误关联")
                request["filename"] = row["filename"] or None
                requests.append(request)
            if not requests:
                raise ValueError("没有启用的论文")
            config = options()
            postprocess = acquisition_postprocess_snapshot(
                workflow(),
                self.ctx.research.parser_options(),
                self.ctx.settings.get("parsing", {}),
            )
            self.submit(
                "acquisition",
                f"获取 {len(requests)} 篇论文",
                [r.get("doi") or r["title"] for r in requests],
                self.acquisition_worker(requests, config, postprocess),
                {"requests": requests, "options": config, "postprocess": postprocess},
            )

        ui.button("开始获取已启用论文", icon="download", on_click=guard(start)).props(
            "size=lg"
        )
