"""Paper acquisition UI; all retrieval routes stay in AN's existing engine."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .ui_common import guard, json_view, parameter_editor, rows_table, split_tags

ACQUISITION_LABELS = {
    "timeout": "网络请求超时（秒）", "base_timeout": "基础获取超时（秒）",
    "request_timeout": "网络请求超时（秒）", "cnki_delay_seconds": "CNKI文献间隔（秒）",
    "bulk_interval": "普通批量论文间隔（秒）", "max_item_attempts": "单篇批量重试次数（含首次）",
    "retry_backoff": "失败重试退避基数（秒）", "interaction_timeout": "人工交互等待（秒；0不限时）",
    "navigation_timeout_ms": "浏览器导航超时（毫秒）", "visible": "显示浏览器窗口",
    "headless": "无头浏览器", "use_system_proxy": "使用系统代理",
    "max_si_files": "每篇最多SI文件数", "si_max_bytes": "单个SI字节上限",
    "public_only": "仅公开获取", "browser_enabled": "允许机构浏览器获取",
}


class AcquisitionPage:
    def acquisition_page(self):
        from nicegui import ui

        from .acquisition import get_acquisition_defaults

        self.title("获取论文", "先确认论文身份，再交给现有可信获取引擎；正文与 SI 分别报告结果。")
        state = {"preview": None, "grid": None}
        defaults = {**get_acquisition_defaults(), **self.ctx.settings.get("acquisition", {})}
        with ui.row().classes("w-full gap-5 items-start"):
            with ui.card().classes("an-card grow min-w-[450px]"):
                ui.label("1 · 添加论文").classes("font-semibold text-lg")
                value = ui.textarea("DOI、中英文标题或文献清单（每行一篇）").classes("w-full")\
                    .props('outlined rows=7 placeholder="10.xxxx/... 或完整标题"')

                def preview_input(text=None, format=None):
                    report = self.ctx.acquisition.preview_inputs(value.value if text is None else text,
                                                                 format=format)
                    state["preview"] = report
                    data = []
                    for entry in report["items"]:
                        request = entry["request"]
                        data.append({"id": entry["id"], "enabled": not entry["duplicate"],
                                     "doi": request.get("doi") or "", "title": request.get("title") or "",
                                     "folder": request.get("folder") or "", "tags": ", ".join(request.get("tags") or []),
                                     "filename": request.get("filename") or "", "resolution": "DOI" if request.get("doi") else "待解析标题"})
                    preview_area.clear()
                    with preview_area:
                        ui.label(f"{report['count']} 篇去重候选；{len(report['errors'])} 项输入错误。")
                        state["grid"] = ui.aggrid({
                            "columnDefs": [
                                {"field": "enabled", "headerName": "获取", "editable": True, "width": 80},
                                *({"field": k, "headerName": label, "editable": k != "resolution", "width": width}
                                  for k, label, width in (("doi", "DOI", 210), ("title", "标题", 380),
                                    ("folder", "单篇分类覆盖", 160), ("tags", "单篇标签覆盖", 160),
                                    ("filename", "单篇文件基础名覆盖", 200), ("resolution", "身份阶段", 150)))],
                            "rowData": data, "defaultColDef": {"resizable": True},
                            "rowSelection": "single", ":getRowId": "params => params.data.id",
                        }, theme="quartz").classes("h-72 w-full")
                        if report["errors"]:
                            rows_table(report["errors"], row_key="line")
                        ui.label("无DOI的英文标题须先解析并确认候选；中文标题沿用CNKI书目身份流程。")\
                            .classes("an-muted text-xs")
                        ui.button("解析 / 确认当前选中标题", icon="manage_search",
                                  on_click=guard(resolve_title)).props("outline")

                async def uploaded(event):
                    text = await event.file.text(encoding="utf-8-sig")
                    preview_input(text, Path(event.file.name).suffix.lstrip(".").lower())

                with ui.row().classes("an-toolbar"):
                    ui.button("规范化与预览", icon="fact_check", on_click=guard(preview_input))
                    ui.button("导入已有 PDF", icon="upload_file", on_click=guard(self.import_dialog)).props("flat")
                ui.upload(label="或导入 TXT / CSV / JSON", on_upload=uploaded,
                          auto_upload=True, max_file_size=5_000_000).props('accept=".txt,.csv,.json"').classes("w-full")
            with ui.card().classes("an-card w-[390px] max-w-full"):
                ui.label("2 · 分类与保存").classes("font-semibold text-lg")
                ui.label(str(self.ctx.library.root)).classes("an-muted text-xs break-all")
                folder = ui.input("分类目录（可直接输入新分类）", value="").props("outlined").classes("w-full")
                tags = ui.input("标签（逗号分隔）").props("outlined").classes("w-full")
                collection = ui.input("成功论文加入固定研究集合（可选）").props("outlined").classes("w-full")
                templates = self.ctx.library.templates()
                naming = ui.select({v: k for k, v in templates.items()}, value=next(iter(templates.values())),
                                   label="主文与 SI 统一命名模板").classes("w-full")
                ui.label("缺失译名或书目信息时回退已有原题；入库后可在整理流程补齐译名并预览改名。")\
                    .classes("an-muted text-xs")
                include_si = ui.switch("同时尝试获取 SI", value=defaults["include_si"])
                auto_parse = ui.switch("成功后自动创建本地解析", value=False)
                strategy = ui.select({"public": "仅公开获取", "institution": "公开 + 机构浏览器"},
                                     value="public" if defaults["public_only"] else "institution",
                                     label="获取策略").classes("w-full")
                source = ui.select({"auto": "自动来源（可用时含CNKI）", "cnki": "指定CNKI", "exclude_cnki": "排除CNKI"},
                                   value=defaults["source_preference"], label="来源策略").classes("w-full")
                interaction = ui.select({"wait": "等待人工登录 / 验证", "skip": "跳过并继续后续论文",
                                         "pause": "暂停批次，等待人工决定"},
                                        value=defaults["interaction_policy"], label="需要人工操作时").classes("w-full")
                timeout = ui.number("交互等待（秒；0表示不限时）", value=defaults["interaction_timeout"], min=0)
        preview_area = ui.column().classes("w-full")
        excluded = {"include_si", "public_only", "browser_enabled", "source_preference",
                    "interaction_policy", "interaction_timeout"}
        with ui.expansion("高级 · 超时、间隔、重试、路线和机构浏览器配置", icon="tune").classes("w-full an-card"):
            ui.label("普通论文间隔控制开始下一篇的时间；CNKI间隔只用于CNKI路线，失败退避用于重试。"
                     "站点限流和权限拒绝仍服从既有边界。")
            read_advanced = parameter_editor({k: v for k, v in defaults.items() if k not in excluded},
                                             labels=ACQUISITION_LABELS)
        with ui.expansion("任务预设", icon="bookmarks").classes("w-full"):
            preset = ui.select(["", *self.ctx.settings.presets("acquisition")], value="", label="载入预设")
            preset_name = ui.input("保存为预设名称")
            ui.label("载入后保存为全局默认并刷新此页面；本批设置仍在开始前完整显示。")
            def load_preset():
                self.ctx.settings.set("acquisition", self.ctx.settings.load_preset("acquisition", preset.value))
                self.page_content.refresh()
            ui.button("载入并显示", on_click=guard(load_preset)).props("flat")

        def options():
            return {**read_advanced(), "include_si": include_si.value,
                    "public_only": strategy.value == "public",
                    "browser_enabled": strategy.value == "institution",
                    "source_preference": source.value, "interaction_policy": interaction.value,
                    "interaction_timeout": timeout.value}

        ui.button("保存当前获取预设", on_click=guard(lambda:
            self.ctx.settings.save_preset("acquisition", preset_name.value, options()))).props("flat")
        ui.button("保存为获取默认设置", on_click=guard(lambda:
            self.ctx.settings.set("acquisition", options()))).props("flat")

        async def resolve_title():
            from nicegui import run
            if state["grid"] is None:
                raise ValueError("请先预览论文")
            selected = await state["grid"].get_selected_row()
            if not selected:
                raise ValueError("请在候选表中单击一篇待解析标题")
            request = next(e["request"] for e in state["preview"]["items"] if e["id"] == selected["id"])
            request = {**request, "title": selected["title"], "doi": selected["doi"] or None}
            ui.notify("正在查询公共书目元数据…")
            report = await run.io_bound(self.ctx.acquisition.resolve_title, request)

            def apply(candidate):
                for key in ("doi", "title", "authors", "journal", "year"):
                    if candidate.get(key) is not None:
                        request[key] = candidate[key]
                original = next(e for e in state["preview"]["items"] if e["id"] == selected["id"])
                original["request"] = deepcopy(request)
                rows = state["grid"].options["rowData"]
                for row in rows:
                    if row["id"] == selected["id"]:
                        row.update(doi=request.get("doi") or "", title=request.get("title") or "",
                                   resolution=report["status"] if not candidate.get("doi") else "候选已确认")
                state["grid"].update()

            if report["status"] in {"RESOLVED", "CNKI_TITLE"}:
                apply(report["request"])
                ui.notify(f"标题解析：{report['status']}；PDF尚未获取。", type="positive")
            else:
                with ui.dialog() as dialog, ui.card().classes("w-[1000px] max-w-[95vw]"):
                    ui.label(f"标题解析：{report['status']}").classes("text-xl font-semibold")
                    ui.label("请核对原题、作者、年份、期刊与DOI；系统不会自动选择第一个相近结果。")
                    for candidate in report.get("candidates", []):
                        with ui.card().classes("an-card w-full"):
                            ui.label(candidate["title"]).classes("font-semibold")
                            ui.label(f"{candidate.get('authors')} · {candidate.get('year')} · {candidate.get('journal')} · {candidate.get('doi')}")
                            json_view(candidate, label="匹配和冲突依据")
                            ui.button("确认是此论文", on_click=guard(lambda c=candidate:
                                (apply(c), dialog.close())))
                    if not report.get("candidates"):
                        ui.label("未找到可靠候选。可修正书目信息后重试，或自行提供可靠DOI。")
                    ui.button("关闭", on_click=dialog.close).props("flat")
                dialog.open()

        async def start():
            if state["grid"] is None:
                raise ValueError("请先生成输入预览")
            rows = [r for r in await state["grid"].get_client_data() if r.get("enabled")]
            request_map = {e["id"]: e["request"] for e in state["preview"]["items"]}
            requests = []
            for row in rows:
                request = {**request_map[row["id"]], "doi": row["doi"] or None,
                           "title": row["title"] or None,
                           "folder": row["folder"] or folder.value or None,
                           "tags": split_tags(row["tags"] or tags.value)}
                if not request["doi"] and row["resolution"] == "待解析标题":
                    raise ValueError("请先解析并确认无DOI标题，避免错误关联")
                title_value = request.get("title") or request.get("doi") or "paper"
                values = {"title_original": title_value, "title_zh": title_value,
                          "year": str(request.get("year") or ""), "journal": request.get("journal") or "",
                          "first_author": next(iter(request.get("authors") or []), ""), "custom_name": ""}
                request["filename"] = row["filename"] or naming.value.format(**values)
                requests.append(request)
            if not requests:
                raise ValueError("没有启用的论文")
            config = options()
            parse_success, collection_name = auto_parse.value, collection.value

            def worker(context):
                report = self.ctx.acquisition.run(requests, config, context=context)
                successful = {r.get("pdf_path", r.get("pdf")) for r in report["items"] if r.get("status") == "VERIFIED"}
                paper_ids = [r["id"] for r in self.ctx.library.scan()["items"] if r["pdf_path"] in successful]
                if collection_name and paper_ids:
                    old = self.ctx.library.collections().get(collection_name, [])
                    self.ctx.library.save_collection(collection_name, list(dict.fromkeys([*old, *paper_ids])))
                if parse_success and paper_ids:
                    report["parsing"] = self.ctx.research.parse(paper_ids, context=context, include_si=config["include_si"])
                return report

            self.submit("acquisition", f"获取 {len(requests)} 篇论文", [r.get("doi") or r["title"] for r in requests],
                        worker, {"requests": requests, "options": config})

        ui.button("开始获取已启用论文", icon="download", on_click=guard(start)).props("size=lg")
