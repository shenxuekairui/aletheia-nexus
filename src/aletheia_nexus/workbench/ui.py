"""NiceGUI local literature workbench, backed by shared application services."""

from __future__ import annotations

import json
from pathlib import Path

from .labels import status_label, value_label
from .ui_acquisition import AcquisitionPage
from .ui_common import FileRegistry, guard, json_text, json_view, parameter_editor
from .ui_home import HomePages
from .ui_library import LibraryPage
from .ui_research import ResearchPages

_STYLE = """
:root { --an-ink:#183247; --an-muted:#5b7082; --an-line:#dce5ec; --an-teal:#087f78; --an-surface:#fff; --an-canvas:#f3f6fa; --an-page-gutter:40px; }
body { background:var(--an-canvas); color:var(--an-ink); font-family:Inter,'Segoe UI','Noto Sans CJK SC','Microsoft YaHei','PingFang SC',sans-serif; font-size:15px; line-height:1.6; }
.nicegui-content { padding:0; gap:0; }
.an-header { background:#102b40!important; color:#fff; padding:0!important; gap:0!important; box-shadow:0 1px 0 #ffffff12; }
.an-header-inner { max-width:1760px; margin:0 auto; padding:16px var(--an-page-gutter); min-height:90px; gap:24px; }
.an-brand-lockup { gap:14px; flex-shrink:0; }
.an-brand-mark { width:46px; height:46px; display:flex; align-items:center; justify-content:center; border:1px solid #74c9c84d; border-radius:13px; color:#a0e7df; background:#1e655b44; }
.an-brand { letter-spacing:.045em; font-size:28px; line-height:1.2; font-weight:750; white-space:nowrap; }
.an-subtitle { font-size:12px; line-height:1.6; letter-spacing:.08em; color:#b8cdd9; margin-top:5px; }
.an-header-tools { gap:8px; flex-wrap:nowrap; }
.an-header-tools .q-btn { min-height:42px; border-radius:9px; font-size:14px; }
.an-nav { background:#fff; border-bottom:1px solid var(--an-line); gap:0; }
.an-nav-inner { max-width:1760px; margin:0 auto; padding:9px var(--an-page-gutter); gap:8px; }
.an-nav .q-btn { min-height:42px; border-radius:8px; font-size:14px; padding:7px 13px; }
.an-nav-active { background:#e6f3f1!important; color:#086a66!important; box-shadow:inset 0 -2px 0 #15988b; }
.an-main { width:100%; max-width:1760px; margin:0 auto; padding:30px var(--an-page-gutter) 48px; gap:24px; }
.an-page-heading { gap:6px; margin-bottom:0; }
.an-title { font-size:28px; line-height:1.3; font-weight:700; letter-spacing:-.025em; }
.an-page-heading .an-muted { max-width:85ch; font-size:14px; line-height:1.8; }
.an-muted { color:var(--an-muted); }
.an-card { border:1px solid var(--an-line); border-radius:14px; box-shadow:0 2px 7px #17324b04; background:var(--an-surface); }
.an-toolbar { gap:8px; align-items:center; flex-wrap:wrap; }
.an-library { height:calc(100vh - 300px); min-height:340px; width:100%; }
.q-btn { text-transform:none; font-weight:600; letter-spacing:0; }
.q-btn:focus-visible, a:focus-visible { outline:3px solid #55b9bb; outline-offset:3px; }
.q-field--outlined .q-field__control { border-radius:8px; }
.q-field__label { color:#5b7082; }
.an-pdf { width:100%; height:70vh; border:0; background:#e5ebf1; }
.an-info { padding:10px 14px; border-left:3px solid #2e7896; background:#edf6fb; border-radius:5px; }
.an-hero { padding:32px 38px; border:1px solid #2c6173; border-radius:18px; background:radial-gradient(ellipse at 92% 8%,#438d8b35,transparent 55%),linear-gradient(112deg,#102a40 0%,#18485b 72%,#1b6065 100%); color:#fff; box-shadow:0 10px 28px #12304710; }
.an-hero-kicker { font-size:13px; letter-spacing:.15em; color:#b4d9df; font-weight:600; }
.an-hero-product { font-size:clamp(38px,3.5vw,54px); font-weight:750; line-height:1.08; letter-spacing:-.045em; }
.an-hero-title { font-size:clamp(20px,1.5vw,25px); font-weight:600; line-height:1.5; letter-spacing:.01em; }
.an-hero-copy { font-size:14px; color:#d4e5eb; line-height:1.85; }
.an-hero-aside { padding:23px 26px; min-width:270px; border-left:1px solid #ffffff26; align-self:center; }
.an-stat-card { padding:20px 22px; gap:8px; }
.an-stat-number { font-size:36px; font-weight:700; letter-spacing:-.04em; line-height:1.2; font-variant-numeric:tabular-nums; }
.an-section-title { font-size:21px; font-weight:700; line-height:1.4; }
.an-flow-card { padding:22px; transition:border-color .15s,box-shadow .15s; }
.an-flow-card:hover { border-color:#69aab1; }
.an-step-number { color:#bdcbd7; font-size:22px; font-weight:600; }
.an-recent-row { padding:10px 0; border-top:1px solid #e8edf2; }
.an-guide-section { border-bottom:1px solid #e5ebf0; padding:6px 0; }
.an-root-path { max-width:26vw; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; color:var(--an-muted); align-self:center; }
.an-main .ag-root-wrapper { --ag-font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif; --ag-font-size:14px; --ag-row-hover-color:#eff7f7; --ag-header-background-color:#f5f8fa; border-color:var(--an-line); border-radius:10px; }
.an-job-card { border:1px solid var(--an-line); border-radius:10px; background:#fff; }
.an-job-card .q-expansion-item__content { padding:12px 18px 18px; }
.an-task-table td { white-space:normal; max-width:360px; overflow-wrap:anywhere; vertical-align:top; }
.an-task-table th { font-weight:600; color:var(--an-ink); background:#f4f8fa; }
.an-task-dialog { padding:24px; }
.an-acquisition-layout { display:grid!important; grid-template-columns:minmax(0,1fr) 390px; gap:20px; align-items:start; }
@media(max-width:1000px){ .an-acquisition-layout { grid-template-columns:minmax(0,1fr); } }
@media(max-width:1200px){ :root{--an-page-gutter:28px;} .an-brand{font-size:26px;} .an-header-inner{gap:16px;} .an-header-tools{gap:2px;} }
@media(max-width:1000px){ :root{--an-page-gutter:20px;} .an-header-inner{flex-wrap:wrap!important;gap:12px;} .an-brand{font-size:24px;} .an-nav-inner{flex-wrap:wrap!important;} .an-parameter-grid{grid-template-columns:1fr 1fr;} .an-hero{padding:28px;} }
@media(max-width:1050px){ .an-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr));} .an-overview-grid{grid-template-columns:1fr;} .an-hero-aside{display:none;} }
@media(max-width:760px){ .an-header-inner{padding:12px 20px;gap:8px;} .an-header-tools .q-btn{min-height:36px;font-size:13px;padding:4px 8px;} .an-nav-inner{padding:6px 20px;gap:4px;} .an-nav .q-btn{min-height:36px;font-size:13px;padding:6px 7px;} .an-root-path{display:none;} }
@media(prefers-reduced-motion:reduce){ .an-flow-card{transition:none;} }
"""


class WorkbenchUI(HomePages, LibraryPage, AcquisitionPage, ResearchPages):
    def __init__(self, context, files):
        self.ctx = context.lease() if hasattr(context, "lease") else context
        self.files = files
        self.active = "主页"
        self.library_filters = {}
        self.library_rows = []
        self.search_report = None
        self.current_task = None
        self.current_result = None
        self.rename_preview = None
        self.nav_buttons = {}

    def title(self, title, detail):
        from nicegui import ui

        with ui.column().classes("an-page-heading"):
            ui.label(title).classes("an-title").props("role=heading aria-level=1")
            ui.label(detail).classes("an-muted")

    def submit(self, kind, label, ids, worker, parameters=None, *, resume_of=None):
        from nicegui import ui

        receipt = self.ctx.jobs.submit(
            kind, label, list(ids), worker, parameters=parameters, resume_of=resume_of
        )
        if kind == "acquisition":
            root = str(self.ctx.library.root)
            self.ctx.settings.set(
                "acquisition_live_task", {"id": receipt["id"], "library": root}
            )
            panel = getattr(self, "acquisition_progress_panel", None)
            if panel is not None and not panel.body.is_deleted and panel.root == root:
                panel.track(receipt)
        ui.notify(f"已加入任务中心：{label}", type="positive")
        return receipt

    def output_links(self, report):
        from nicegui import ui

        for value in report.get("outputs", []):
            path = Path(value)
            if not path.is_absolute():
                directory = report.get("directory") or report.get("run_directory")
                if directory:
                    path = Path(directory) / path
            if path.is_file():
                ui.link(path.name, self.files.register(path), new_tab=True)

    def show_pdf(self, document, *, page=1, title=None, container=None):
        from nicegui import ui

        source = self.ctx.research.app.check_document(document, "direct")
        source.verify()
        if not 1 <= int(page) <= source.identity["page_count"]:
            raise ValueError("PDF物理页码超出范围")
        file_url = self.files.register(source.pdf)
        url = file_url + f"#page={int(page)}&view=FitH"
        image_url = "/an-page/" + file_url.rsplit("/", 1)[-1] + f"/{int(page)}"
        reading = {"page": int(page)}

        def content():
            with ui.row().classes("an-toolbar w-full"):
                ui.label(title or source.identity["title"]).classes(
                    "font-semibold grow"
                )
                pdf_link = ui.link("在新标签页打开 PDF", url, new_tab=True)
            locator_label = ui.label(
                f"{value_label(source.identity['document_role'])} · 物理 PDF 第 {page} 页 / "
                f"{source.identity['page_count']} · {value_label(source.identity['identity_basis'])}"
            ).classes("an-muted text-xs")
            import shutil

            with ui.tabs().classes("w-full") as tabs:
                image_tab = ui.tab("原页图像", icon="image")
                pdf_tab = ui.tab("完整 PDF", icon="picture_as_pdf")
            with ui.tab_panels(tabs, value=image_tab).classes("w-full"):
                with ui.tab_panel(image_tab).classes("p-0"):
                    if shutil.which("pdftoppm"):
                        with ui.row().classes("an-toolbar w-full"):
                            page_number = (
                                ui.number(
                                    "物理页码",
                                    value=reading["page"],
                                    min=1,
                                    max=source.identity["page_count"],
                                    step=1,
                                )
                                .props("outlined dense")
                                .classes("w-28")
                            )
                            previous_page = (
                                ui.button(
                                    "上一页",
                                    icon="chevron_left",
                                    on_click=guard(
                                        lambda: turn_page(reading["page"] - 1)
                                    ),
                                )
                                .props("flat dense")
                                .set_enabled(reading["page"] > 1)
                            )
                            next_page = (
                                ui.button(
                                    "下一页",
                                    icon="chevron_right",
                                    on_click=guard(
                                        lambda: turn_page(reading["page"] + 1)
                                    ),
                                )
                                .props("flat dense")
                                .set_enabled(
                                    reading["page"] < source.identity["page_count"]
                                )
                            )
                            ui.button(
                                "定位",
                                icon="my_location",
                                on_click=guard(lambda: turn_page(page_number.value)),
                            ).props("flat dense")
                            zoom_label = ui.label("显示比例 100%").classes(
                                "an-muted text-xs"
                            )
                            zoom = ui.slider(
                                min=100, max=250, step=25, value=100
                            ).classes("w-40")
                        with ui.scroll_area().classes("w-full h-[70vh]"):
                            page_image = (
                                ui.image(image_url)
                                .classes("w-full")
                                .props("fit=contain")
                            )
                        image_link = ui.link(
                            "在新标签页放大原页图像", image_url, new_tab=True
                        )

                        def turn_page(number):
                            if (
                                type(number) not in (int, float)
                                or int(number) != number
                                or not 1 <= number <= source.identity["page_count"]
                            ):
                                raise ValueError("物理页码超出文献范围")
                            reading["page"] = int(number)
                            page_number.set_value(int(number))
                            next_url = (
                                "/an-page/"
                                + file_url.rsplit("/", 1)[-1]
                                + f"/{int(number)}"
                            )
                            page_image.set_source(next_url)
                            image_link.props(f'href="{next_url}"')
                            pdf_link.props(
                                f'href="{file_url}#page={int(number)}&view=FitH"'
                            )
                            pdf_frame.props(
                                f'src="{file_url}#page={int(number)}&view=FitH"'
                            )
                            previous_page.set_enabled(number > 1)
                            next_page.set_enabled(
                                number < source.identity["page_count"]
                            )
                            locator_label.set_text(
                                f"{value_label(source.identity['document_role'])} · 当前物理第 {int(number)} 页 / {source.identity['page_count']} · 初始引用第 {int(page)} 页 · {value_label(source.identity['identity_basis'])}"
                            )

                        page_number.on(
                            "keydown.enter", guard(lambda: turn_page(page_number.value))
                        )
                        zoom.on_value_change(
                            lambda e: (
                                page_image.style(f"width:{e.value}%;max-width:none"),
                                zoom_label.set_text(f"显示比例 {int(e.value)}%"),
                            )
                        )
                    else:
                        ui.label(
                            "原页图像需要本地 Poppler 的 pdftoppm。请安装并加入系统 PATH，"
                            "随后重启工作台；当前仍可用完整PDF标签或原PDF链接核对。"
                        ).classes("an-info w-full")
                with ui.tab_panel(pdf_tab).classes("p-0"):
                    ui.label(
                        "若浏览器不支持内嵌PDF，请切回原页图像或用上方链接在桌面浏览器打开。"
                    ).classes("an-muted text-xs")
                    pdf_frame = (
                        ui.element("iframe")
                        .props(f'src="{url}" title="PDF original"')
                        .classes("an-pdf")
                    )
            with ui.expansion("局部放大与原文文字", icon="zoom_in").classes("w-full"):
                regions = {
                    "整页": [0, 0, 1, 1],
                    "上半页": [0, 0, 1, 0.5],
                    "下半页": [0, 0.5, 1, 1],
                    "左半页": [0, 0, 0.5, 1],
                    "右半页": [0.5, 0, 1, 1],
                    "中央区域": [0.2, 0.2, 0.8, 0.8],
                }
                region_choice = (
                    ui.select(list(regions), value="整页", label="选择要放大的区域")
                    .props("outlined")
                    .classes("w-full")
                )
                with ui.expansion("专家 · 自定义原页区域", icon="tune").classes(
                    "w-full"
                ):
                    ui.label(
                        "按左、上、右、下填写 0–1 坐标；对应当前物理页，原 PDF 不变。"
                    )
                    region = ui.input("原页区域坐标", value="0,0,1,1").classes("w-full")
                region_choice.on_value_change(
                    lambda e: region.set_value(",".join(map(str, regions[e.value])))
                )
                image_area = ui.column().classes("w-full")

                async def render():
                    import base64

                    from nicegui import run

                    coordinates = [float(p.strip()) for p in region.value.split(",")]
                    metadata, png = await run.io_bound(
                        self.ctx.research.app.read_original_page,
                        document,
                        reading["page"],
                        region=coordinates,
                    )
                    image_area.clear()
                    with image_area:
                        ui.image(
                            "data:image/png;base64," + base64.b64encode(png).decode()
                        )
                        json_view(metadata, label="区域来源")

                async def text():
                    from nicegui import run

                    report = await run.io_bound(
                        self.ctx.research.app.read_original_page_text,
                        document,
                        reading["page"],
                    )
                    image_area.clear()
                    with image_area:
                        ui.code(report["text"]).classes("w-full max-h-96 overflow-auto")
                        json_view(report, label="原页读取诊断")

                ui.button("放大选定区域", on_click=guard(render), icon="image")
                ui.button(
                    "读取此页文字层", on_click=guard(text), icon="text_snippet"
                ).props("flat")

        if container is not None:
            container.clear()
            with container:
                content()
        else:
            with (
                ui.dialog() as dialog,
                ui.card().classes("w-[1100px] max-w-[95vw] an-card"),
            ):
                content()
                ui.button("关闭", on_click=dialog.close).props("flat")
            dialog.open()

    def selection_dialog(self):
        from nicegui import ui

        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[1050px] max-w-[95vw] an-card"),
        ):
            ui.label("当前文献选择清单").classes("an-title")
            summary = ui.label()

            def change_selection(ids, mode="replace"):
                self.ctx.library.set_selection(ids, mode=mode)
                selected_rows.refresh()

            @ui.refreshable
            def selected_rows():
                rows = [self.ctx.library.get(i) for i in self.ctx.library.selection()]
                rows = [r for r in rows if r]
                summary.set_text(
                    f"共 {len(rows)} 篇论文；AI执行前另行确认主文和 SI 材料范围。"
                )
                if not rows:
                    ui.label("选择清单为空，可从文库或检索结果继续添加。").classes(
                        "an-muted"
                    )
                for row in rows:
                    with ui.row().classes("an-toolbar w-full"):
                        ui.label(row.get("title_zh") or row["title"]).classes("grow")
                        ui.badge(f"SI {row.get('si_count', 0)}").props("outline")
                        ui.button(
                            icon="close",
                            on_click=guard(
                                lambda i=row["id"]: change_selection([i], mode="remove")
                            ),
                        ).props("flat round dense").tooltip("移出当前选择清单")

            selected_rows()
            collection = ui.input("保存为固定研究集合").classes("w-full")
            with ui.row().classes("an-toolbar"):
                ui.button(
                    "保存集合",
                    icon="folder_special",
                    on_click=guard(
                        lambda: self.ctx.library.save_collection(
                            collection.value, self.ctx.library.selection()
                        )
                    ),
                )
                ui.button(
                    "批量整理",
                    icon="drive_file_rename_outline",
                    on_click=guard(
                        lambda: self.organize_dialog(self.ctx.library.selection())
                    ),
                )

                def translate_selected():
                    entry = self.title_translation_dialog(self.ctx.library.selection())
                    entry.on("hide", lambda: selected_rows.refresh())

                ui.button(
                    "补中文标题", icon="translate", on_click=guard(translate_selected)
                ).props("outline")
                ui.button(
                    "解析",
                    icon="document_scanner",
                    on_click=guard(
                        lambda: self.parse_dialog(self.ctx.library.selection())
                    ),
                )
                ui.button(
                    "AI研究",
                    icon="science",
                    on_click=lambda: (dialog.close(), self.navigate("AI 研究")),
                )
                ui.button("清空", on_click=guard(lambda: change_selection([]))).props(
                    "flat"
                )
                ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def task_dialog(self):
        from .ui_tasks import render_task_dialog

        render_task_dialog(self)

    async def recover_acquisition_dialog(self, job):
        from copy import deepcopy

        from nicegui import run, ui

        from .acquisition import _options, normalize_request
        from .acquisition_recovery import (
            recovery_checkpoint,
            recovery_preview,
            recovery_requests,
        )
        from .defaults import browser_profile_choices

        preview = await run.io_bound(recovery_preview, job, self.ctx.acquisition)
        parameters = job.get("parameters") or {}
        postprocess = deepcopy(parameters.get("postprocess", {}))
        previous_translation = (job.get("result") or {}).get("translation") or {}
        adopted_parse_defaults = bool(
            postprocess.get("auto_parse") and "parse_options" not in postprocess
        )
        if adopted_parse_defaults:
            postprocess["parse_options"] = deepcopy(
                {
                    **self.ctx.research.parser_options(),
                    **self.ctx.settings.get("parsing", {}),
                }
            )
        with ui.dialog() as dialog, ui.card().classes("w-[1150px] max-w-[96vw]"):
            ui.label("重试获取失败 / 补取 SI").classes("text-xl font-semibold")
            ui.label(
                "默认只选未成功项。正文已验证但 SI 待补时，复用正文，只继续附件获取；"
                "完整完成项不重新调度。请核对篇数、目录和标签后开始。"
            ).classes("an-info w-full")
            categories = {
                "COMPLETE": "已完整完成",
                "SI_INCOMPLETE": "正文有效，SI 待补",
                "MAIN_FAILED": "正文未成功",
                "NOT_STARTED": "未开始 / 已中断或跳过",
                "NEEDS_REVIEW": "来源或检查点需先核对",
            }
            ui.label(
                " · ".join(
                    f"{label} {sum(row['category'] == key for row in preview['rows'])} 篇"
                    for key, label in categories.items()
                )
            ).classes("text-sm")
            table_rows = [
                {
                    **row,
                    "category_label": categories[row["category"]],
                    "main_label": status_label(row["main_status"]),
                    "si_label": status_label(row["si_status"]),
                    "target": str(self.ctx.library.root / row["folder"]),
                    "tag_label": ", ".join(row["tags"]) or "无标签",
                }
                for row in preview["rows"]
            ]
            columns = [
                {"name": key, "field": key, "label": label, "align": "left"}
                for key, label in (
                    ("title", "论文"),
                    ("category_label", "本次处理"),
                    ("main_label", "正文状态"),
                    ("si_label", "SI 状态"),
                    ("target", "实际保存目录"),
                    ("tag_label", "保留标签"),
                    ("reason", "核验与重试说明"),
                )
            ]
            table = ui.table(
                columns=columns,
                rows=[row for row in table_rows if row["can_retry"]],
                row_key="id",
                selection="multiple",
                pagination=10,
                on_select=lambda _: selection_count(),
            ).classes("an-task-table w-full")
            table.selected = [row for row in table_rows if row["selected"]]
            excluded = [row for row in table_rows if not row["can_retry"]]
            if excluded:
                with ui.expansion(
                    f"不重复调度 / 来源需核对：{len(excluded)} 篇", icon="fact_check"
                ).classes("w-full"):
                    ui.table(
                        columns=columns, rows=excluded, row_key="id", pagination=5
                    ).classes("an-task-table w-full")
            count = ui.label()

            def selection_count():
                count.set_text(f"本次将重试 {len(table.selected)} 篇；不包括未勾选项。")

            selection_count()
            with ui.row().classes("an-toolbar"):

                def choose(category=None):
                    table.selected = [
                        row
                        for row in table_rows
                        if row["can_retry"]
                        and (category is None or row["category"] == category)
                    ]
                    selection_count()

                ui.button("选择全部可重试项", on_click=lambda: choose()).props("flat")
                ui.button("仅补取 SI", on_click=lambda: choose("SI_INCOMPLETE")).props(
                    "flat"
                )
            for warning in preview["warnings"]:
                ui.label(warning).classes("text-orange-9 text-sm")
            strategy = ui.select(
                {"public": "仅公开获取", "institution": "公开 + 机构浏览器"},
                value="public" if preview["options"]["public_only"] else "institution",
                label="本次重试获取策略（其余超时、间隔与预算保留原参数）",
            ).classes("w-full")
            sessions = browser_profile_choices(preview["options"]["browser"])
            profile = (
                ui.select(
                    sessions["options"],
                    value=sessions["current"]
                    if sessions["current"] in sessions["options"]
                    else None,
                    label="本次机构浏览器会话",
                )
                .classes("w-full")
                .bind_visibility_from(
                    strategy, "value", lambda value: value == "institution"
                )
            )
            ui.label(sessions["message"]).classes("an-muted text-xs")
            for warning in sessions["warnings"]:
                ui.label(warning).classes("text-orange-9 text-sm")
            ui.label(
                "需要机构权限时可在本次切换为公开 + 机构浏览器；登录或验证仍由你完成。"
                "原请求的分类、标签与文件名覆盖保留，已移动的正文按来源哈希重新定位。"
            ).classes("an-muted text-sm")
            ui.label(
                f"自动解析：{'是' if postprocess.get('auto_parse') else '否'}；"
                f"研究集合：{postprocess.get('collection') or '不加入'}。命名按原任务模板与当前可靠元数据执行。"
            )
            if adopted_parse_defaults:
                ui.label(
                    "历史任务未保存解析配置；本次恢复采用当前解析默认设置的新快照，"
                    "可在下方查看。执行期间修改默认设置不会改变此快照。"
                ).classes("an-info w-full")
            if job.get("billing_uncertain") or previous_translation.get(
                "billing_uncertain"
            ):
                ui.label(
                    "先前模型请求的费用尚待核对。恢复获取默认不再翻译标题；重新开启可能再次计费，"
                    "需要在下方重新确认标题范围和本次费用上限。"
                ).classes("an-info w-full")
            elif previous_translation:
                ui.label(
                    f"先前标题翻译：{status_label(previous_translation.get('status'))}；"
                    f"已记录费用估算：{previous_translation.get('accounted_cost', '待核对')}。"
                )
            read_translation = self.title_translation_controls(
                (postprocess.get("title_translation") or {}).get("options")
            )
            json_view(
                {
                    "preview": preview,
                    "postprocess": postprocess,
                    "previous_translation": previous_translation,
                },
                label="原参数、检查点与来源核验（专家）",
            )

            async def submit_retry():
                selected_ids = [row["id"] for row in table.selected]
                # Revalidate on confirmation. Previewed status or a stale path
                # never authorizes reuse, even when a previous task said success.
                fresh = await run.io_bound(
                    recovery_preview, self.ctx.jobs.get(job["id"]), self.ctx.acquisition
                )
                requests = recovery_requests(fresh, selected_ids)
                if strategy.value == "institution" and not profile.value:
                    raise ValueError("请先选择有效的机构浏览器会话，再开始重试。")
                options = _options(
                    {
                        **fresh["options"],
                        "browser": {
                            **fresh["options"]["browser"],
                            "profile_name": profile.value
                            or fresh["options"]["browser"]["profile_name"],
                        },
                        "public_only": strategy.value == "public",
                        "browser_enabled": strategy.value == "institution",
                        "resume": True,
                    }
                )
                reviewed_postprocess = {
                    **postprocess,
                    "title_translation": read_translation(),
                    "preserve_existing_names_for": [
                        normalize_request(row["request"]).key
                        for row in fresh["rows"]
                        if row["id"] in selected_ids
                        and row["category"] == "SI_INCOMPLETE"
                    ],
                }
                checkpoint = await run.io_bound(
                    recovery_checkpoint, fresh, self.ctx.acquisition
                )
                reviewed_parameters = {
                    **parameters,
                    "library": str(self.ctx.library.root),
                    "requests": requests,
                    "options": options,
                    "postprocess": reviewed_postprocess,
                    "recovery": {
                        "selected_ids": selected_ids,
                        "source_checkpoint": fresh["checkpoint"],
                        "source_checkpoint_sha256": fresh["checkpoint_sha256"],
                    },
                }
                self.submit(
                    "acquisition",
                    f"重试 {len(requests)} 篇 · " + job["label"],
                    [r.get("doi") or r["title"] for r in requests],
                    self.acquisition_worker(
                        requests,
                        options,
                        reviewed_postprocess,
                        checkpoint_path=checkpoint,
                    ),
                    reviewed_parameters,
                    resume_of=job["id"],
                )
                dialog.close()

            retry_state = {"busy": False}

            async def start():
                if retry_state["busy"]:
                    return
                retry_state["busy"] = True
                start_button.disable()
                try:
                    await submit_retry()
                except Exception:
                    retry_state["busy"] = False
                    start_button.enable()
                    raise

            start_button = ui.button(
                "确认重试所选未成功项", icon="play_arrow", on_click=guard(start)
            )
            start_button.set_enabled(any(row["can_retry"] for row in table_rows))
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def settings_dialog(self):
        from nicegui import ui

        from .translation import DEFAULT_OPTIONS

        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[1150px] max-w-[95vw] an-card"),
        ):
            ui.label("设置与任务预设").classes("an-title")
            root = ui.input("文献库根目录", value=str(self.ctx.library.root)).classes(
                "w-full"
            )
            ui.label(f"工作区：{self.ctx.workspace}").classes("an-muted text-xs")
            if hasattr(self.ctx, "switch_root"):

                async def switch():
                    self.ctx.switch_root(root.value)
                    ui.navigate.to("/")

                ui.button("切换文献库", icon="folder_open", on_click=guard(switch))
            ui.label("API密钥从系统环境读取；预设与任务记录不保存密钥或Cookie。")
            mode = ui.select(
                {
                    "bilingual": "中英文双行",
                    "zh": "中文优先",
                    "original": "原题优先",
                    "custom": "自定义短名称优先",
                },
                value=self.ctx.settings.get("title_mode", "bilingual"),
                label="标题显示方式",
            ).classes("w-full")
            ui.button(
                "保存显示偏好",
                on_click=guard(
                    lambda: (
                        self.ctx.settings.set("title_mode", mode.value),
                        ui.notify("已保存"),
                    )
                ),
            )
            for section, label, defaults in (
                ("translation", "DeepSeek 标题翻译默认参数", DEFAULT_OPTIONS),
                ("parsing", "PDF 解析默认参数", self.ctx.research.parser_options()),
            ):
                with ui.expansion(label, icon="tune").classes("w-full"):
                    current = {**defaults, **self.ctx.settings.get(section, {})}
                    if current:
                        read = parameter_editor(current)
                        ui.button(
                            "保存",
                            on_click=guard(
                                lambda s=section, r=read: (
                                    self.ctx.settings.set(s, r()),
                                    ui.notify("已保存"),
                                )
                            ),
                        )
            with ui.expansion("参数预设", icon="bookmarks").classes("w-full"):
                kind = ui.select(
                    {
                        "acquisition": "论文获取",
                        "parsing": "PDF解析",
                        "translation": "标题翻译",
                        "research": "AI研究",
                    },
                    value="acquisition",
                    label="类型",
                )
                name = ui.input("预设名称")
                parameters = (
                    ui.textarea("实际参数 JSON", value="{}")
                    .classes("w-full")
                    .props("autogrow")
                )
                ui.button(
                    "保存可复用预设",
                    on_click=guard(
                        lambda: (
                            self.ctx.settings.save_preset(
                                kind.value, name.value, json.loads(parameters.value)
                            ),
                            ui.notify("已保存预设"),
                        )
                    ),
                )
                ui.button(
                    "载入此预设",
                    on_click=guard(
                        lambda: parameters.set_value(
                            json_text(
                                self.ctx.settings.load_preset(kind.value, name.value)
                            )
                        )
                    ),
                )
                json_view(
                    {
                        k: self.ctx.settings.presets(k)
                        for k in ("acquisition", "parsing", "translation", "research")
                    },
                    label="现有预设",
                )
            with ui.expansion("环境诊断", icon="health_and_safety").classes("w-full"):
                import importlib.util
                import os
                import shutil
                import sys

                diagnostics = {
                    "python": sys.version.split()[0],
                    "platform": sys.platform,
                    "poppler": bool(shutil.which("pdftoppm")),
                    "tesseract": bool(shutil.which("tesseract")),
                    "playwright": importlib.util.find_spec("playwright") is not None,
                    "DeepSeek_API_key_present": bool(
                        os.environ.get("DEEPSEEK_API_KEY")
                    ),
                    "local_only": True,
                }
                ui.label(
                    f"Python {diagnostics['python']} · "
                    + {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}.get(
                        sys.platform, sys.platform
                    )
                ).classes("font-semibold")
                ui.table(
                    columns=[
                        {
                            "name": "name",
                            "label": "组件",
                            "field": "name",
                            "align": "left",
                        },
                        {
                            "name": "state",
                            "label": "检测结果",
                            "field": "state",
                            "align": "left",
                        },
                        {
                            "name": "next",
                            "label": "用途与下一步",
                            "field": "next",
                            "align": "left",
                        },
                    ],
                    rows=[
                        {
                            "name": "PDF 原页图像（Poppler）",
                            "state": "已检测到"
                            if diagnostics["poppler"]
                            else "未检测到",
                            "next": "用于原页渲染与局部放大。未安装时仍可阅读完整 PDF。",
                        },
                        {
                            "name": "经典 OCR（Tesseract）",
                            "state": "已检测到"
                            if diagnostics["tesseract"]
                            else "未检测到",
                            "next": "扫描件需选择已安装的 OCR 引擎；原生文字 PDF 不要求启用 OCR。",
                        },
                        {
                            "name": "机构浏览器 Python 依赖",
                            "state": "已安装"
                            if diagnostics["playwright"]
                            else "未安装",
                            "next": "在获取页检查本次浏览器配置；此项不代表浏览器运行时、登录或机构权限已就绪。",
                        },
                        {
                            "name": "DeepSeek API 环境变量",
                            "state": "已配置"
                            if diagnostics["DeepSeek_API_key_present"]
                            else "未配置",
                            "next": "本地整理与检索无需密钥；远程请求仍须逐次核对材料与费用授权。",
                        },
                    ],
                    row_key="name",
                ).classes("an-task-table w-full").props(
                    "flat bordered wrap-cells hide-bottom"
                )
                json_view(diagnostics, label="原始依赖状态（专家）")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def navigate(self, page):
        self.active = page
        for name, button in self.nav_buttons.items():
            if name == page:
                button.classes("an-nav-active")
            else:
                button.classes(remove="an-nav-active")
        self.page_content.refresh()

    def build(self):
        from nicegui import ui

        ui.add_css(_STYLE)
        ui.colors(primary="#17678b", secondary="#45627c", accent="#18a999")
        header = ui.header().classes("an-header")
        with header:
            with ui.row().classes("an-header-inner w-full items-center no-wrap"):
                with ui.row().classes("an-brand-lockup items-center no-wrap"):
                    with ui.element("div").classes("an-brand-mark"):
                        ui.icon("hub", size="29px").props("aria-hidden=true")
                    with ui.column().classes("gap-0"):
                        ui.label("ALETHEIA NEXUS").classes("an-brand")
                        ui.label("本地科研工作台 · v0.8").classes("an-subtitle")
                ui.space()
                with ui.row().classes("an-header-tools items-center"):
                    ui.button(
                        "操作指南", icon="menu_book", on_click=guard(self.guide_dialog)
                    ).props("flat color=white")
                    ui.button(
                        "选择清单",
                        icon="playlist_add_check",
                        on_click=guard(self.selection_dialog),
                    ).props("flat color=white")
                    ui.button(
                        "任务中心",
                        icon="pending_actions",
                        on_click=guard(self.task_dialog),
                    ).props("flat color=white")
                    ui.button(
                        "设置", icon="settings", on_click=guard(self.settings_dialog)
                    ).props("flat color=white")
        with header, ui.row().classes("an-nav w-full"):
            with (
                ui.row()
                .classes("an-nav-inner w-full items-center no-wrap")
                .props("role=navigation aria-label=主导航")
            ):
                for label, icon in (
                    ("主页", "space_dashboard"),
                    ("获取论文", "cloud_download"),
                    ("文献库", "local_library"),
                    ("科研检索", "manage_search"),
                    ("AI 研究", "science"),
                    ("研究成果", "fact_check"),
                ):
                    button = ui.button(
                        label,
                        icon=icon,
                        on_click=guard(lambda p=label: self.navigate(p)),
                    ).props("flat")
                    if label == self.active:
                        button.classes("an-nav-active")
                    self.nav_buttons[label] = button
                ui.space()
                ui.label(f"当前文库 · {self.ctx.library.root.name}").classes(
                    "an-root-path"
                ).tooltip(str(self.ctx.library.root))

        @ui.refreshable
        def page_content():
            with ui.column().classes("an-main"):
                {
                    "主页": self.home_page,
                    "获取论文": self.acquisition_page,
                    "文献库": self.library_page,
                    "科研检索": self.search_page,
                    "AI 研究": self.research_page,
                    "研究成果": self.results_page,
                }[self.active]()

        self.page_content = page_content
        page_content()


def build_ui(context):
    """Register pages once; each browser client receives isolated view state."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, Response
    from nicegui import app, ui

    from .normalization_api import install_normalization_api

    context.normalization_api = install_normalization_api(context, app=app)

    files = FileRegistry([context.library.root, context.workspace])

    @app.get("/an-file/{token}")
    def read_selected_file(token: str):
        try:
            path = files.resolve(token)
        except (KeyError, ValueError, FileNotFoundError):
            raise HTTPException(404, "Selected file is unavailable") from None
        response = FileResponse(
            path, filename=path.name, content_disposition_type="inline"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/an-page/{token}/{page}")
    def read_selected_page(token: str, page: int):
        from pypdf import PdfReader

        from aletheia_nexus.processing.materials import render_page

        try:
            path = files.resolve(token)
            if path.suffix.lower() != ".pdf" or not 1 <= page <= len(
                PdfReader(path).pages
            ):
                raise ValueError("Invalid physical PDF page")
            png = render_page(path, page)
            files.resolve(token)
        except (KeyError, ValueError, FileNotFoundError):
            raise HTTPException(404, "Selected PDF page is unavailable") from None
        except RuntimeError as exc:
            raise HTTPException(
                409, getattr(exc, "code", "page_renderer_unavailable")
            ) from None
        return Response(
            png,
            media_type="image/png",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @ui.page("/")
    def page():
        # Roots can only be switched by an explicit local UI operation. New
        # clients get the current root; old capabilities remain individually scoped.
        files.roots = tuple(
            Path(p).resolve() for p in (context.library.root, context.workspace)
        )
        WorkbenchUI(context, files).build()

    return files
