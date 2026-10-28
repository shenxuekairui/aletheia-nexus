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
:root { --an-ink:#18314b; --an-muted:#60758a; --an-line:#dce5ed; }
body { background:#f3f6fa; color:var(--an-ink); font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif; }
.an-header { background:#132d47!important; color:#fff; }
.an-brand { letter-spacing:.08em; font-size:18px; font-weight:700; }
.an-subtitle { font-size:12px; color:#a9c6dc; }
.an-nav { background:#fff; border-bottom:1px solid var(--an-line); }
.an-nav-active { background:#e8f2f5!important; color:#17678b!important; border-radius:8px; }
.an-main { width:100%; max-width:1760px; margin:0 auto; padding:28px 32px; }
.an-title { font-size:25px; font-weight:650; letter-spacing:-.025em; }
.an-muted { color:var(--an-muted); }
.an-card { border:1px solid var(--an-line); border-radius:12px; box-shadow:none; background:#fff; }
.an-toolbar { gap:8px; align-items:center; flex-wrap:wrap; }
.an-library { height:calc(100vh - 300px); min-height:340px; width:100%; }
.q-btn { text-transform:none; font-weight:550; letter-spacing:0; }
.q-field--outlined .q-field__control { border-radius:8px; }
.an-pdf { width:100%; height:70vh; border:0; background:#e5ebf1; }
.an-info { padding:10px 14px; border-left:3px solid #2e7896; background:#edf6fb; border-radius:5px; }
.an-hero { padding:36px 40px; border-radius:16px; background:linear-gradient(112deg,#122d46 0%,#184c61 72%,#1c626b 100%); color:#fff; box-shadow:0 12px 30px #12304712; }
.an-hero-kicker { font-size:12px; letter-spacing:.14em; color:#b1d7df; font-weight:650; }
.an-hero-title { font-size:clamp(28px,2.6vw,42px); font-weight:650; line-height:1.4; letter-spacing:-.03em; }
.an-hero-copy { font-size:15px; color:#d0e1e8; line-height:1.9; }
.an-hero-aside { padding:22px 25px; min-width:270px; border-left:1px solid #ffffff26; }
.an-stat-card { padding:20px 22px; gap:8px; }
.an-stat-number { font-size:35px; font-weight:650; letter-spacing:-.04em; line-height:1.2; }
.an-section-title { font-size:19px; font-weight:650; }
.an-flow-card { padding:22px; transition:border-color .15s; }
.an-flow-card:hover { border-color:#69aab1; }
.an-step-number { color:#bdcbd7; font-size:22px; font-weight:600; }
.an-recent-row { padding:10px 0; border-top:1px solid #e8edf2; }
.an-guide-section { border-bottom:1px solid #e5ebf0; padding:6px 0; }
.an-root-path { max-width:32vw; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; color:var(--an-muted); align-self:center; }
.an-job-card { border:1px solid var(--an-line); border-radius:10px; background:#fff; }
.an-job-card .q-expansion-item__content { padding:12px 18px 18px; }
.an-task-table td { white-space:normal; max-width:360px; overflow-wrap:anywhere; vertical-align:top; }
.an-task-table th { font-weight:600; color:var(--an-ink); background:#f4f8fa; }
.an-task-dialog { padding:24px; }
@media(max-width:1000px){ .an-main{padding:16px;} .an-parameter-grid{grid-template-columns:1fr 1fr;} }
@media(max-width:1050px){ .an-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr));} .an-overview-grid{grid-template-columns:1fr;} .an-hero-aside{display:none;} }
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

        with ui.column().classes("gap-1 mb-4"):
            ui.label(title).classes("an-title")
            ui.label(detail).classes("an-muted")

    def submit(self, kind, label, ids, worker, parameters=None, *, resume_of=None):
        from nicegui import ui

        receipt = self.ctx.jobs.submit(
            kind, label, list(ids), worker, parameters=parameters, resume_of=resume_of
        )
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

    def recover_acquisition_dialog(self, job):
        from copy import deepcopy

        from nicegui import ui

        parameters = job.get("parameters") or {}
        requests = parameters.get("requests", [])
        options = parameters.get("options", {})
        postprocess = deepcopy(parameters.get("postprocess", {}))
        previous_translation = (job.get("result") or {}).get("translation") or {}
        checkpoint = (job.get("result") or {}).get("checkpoint") or job.get(
            "checkpoint"
        )
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
        if not requests:
            raise ValueError("此任务没有可恢复的原始获取参数，请从获取页新建任务")
        with ui.dialog() as dialog, ui.card().classes("w-[850px] max-w-[95vw]"):
            ui.label("恢复获取任务").classes("text-xl font-semibold")
            ui.label(
                f"原批次 {len(requests)} 篇。检查点中成功项仍需通过现有来源核验；未知或失败项按实际参数重新尝试。"
            )
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
                    "requests": requests,
                    "options": options,
                    "checkpoint": checkpoint,
                    "postprocess": postprocess,
                    "previous_translation": previous_translation,
                },
                label="本次恢复的实际范围与参数",
            )

            def start():
                reviewed_postprocess = {
                    **postprocess,
                    "title_translation": read_translation(),
                }
                reviewed_parameters = {
                    **parameters,
                    "postprocess": reviewed_postprocess,
                }
                self.submit(
                    "acquisition",
                    "恢复获取 " + job["label"],
                    requests,
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

            ui.button("确认恢复获取", icon="play_arrow", on_click=guard(start))
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

                json_view(
                    {
                        "python": sys.version.split()[0],
                        "platform": sys.platform,
                        "poppler": bool(shutil.which("pdftoppm")),
                        "tesseract": bool(shutil.which("tesseract")),
                        "playwright": importlib.util.find_spec("playwright")
                        is not None,
                        "DeepSeek_API_key_present": bool(
                            os.environ.get("DEEPSEEK_API_KEY")
                        ),
                        "local_only": True,
                    },
                    label="依赖状态",
                )
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
        with ui.header().classes("an-header items-center px-7 py-3"):
            with ui.column().classes("gap-0 grow"):
                ui.label("ALETHEIA NEXUS").classes("an-brand")
                ui.label("本地科研工作台 · v0.8").classes("an-subtitle")
            ui.button(
                "操作指南", icon="menu_book", on_click=guard(self.guide_dialog)
            ).props("flat color=white")
            ui.button(
                "选择清单",
                icon="playlist_add_check",
                on_click=guard(self.selection_dialog),
            ).props("flat color=white")
            ui.button(
                "任务中心", icon="pending_actions", on_click=guard(self.task_dialog)
            ).props("flat color=white")
            ui.button(
                "设置", icon="settings", on_click=guard(self.settings_dialog)
            ).props("flat color=white")
        with ui.row().classes("an-nav w-full px-7 py-2 gap-3"):
            for label, icon in (
                ("主页", "space_dashboard"),
                ("获取论文", "cloud_download"),
                ("文献库", "local_library"),
                ("科研检索", "manage_search"),
                ("AI 研究", "science"),
                ("研究成果", "fact_check"),
            ):
                button = ui.button(
                    label, icon=icon, on_click=guard(lambda p=label: self.navigate(p))
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
