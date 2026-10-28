"""NiceGUI local literature workbench, backed by shared application services."""

from __future__ import annotations

import json
from pathlib import Path

from .ui_acquisition import AcquisitionPage
from .ui_common import FileRegistry, guard, json_text, json_view, parameter_editor
from .ui_library import LibraryPage
from .ui_research import ResearchPages

_STYLE = """
:root { --an-ink:#18314b; --an-muted:#60758a; --an-line:#dce5ed; }
body { background:#f3f6fa; color:var(--an-ink); font-family:Inter,'Segoe UI','Microsoft YaHei',sans-serif; }
.an-header { background:#132d47!important; color:#fff; }
.an-brand { letter-spacing:.08em; font-size:18px; font-weight:700; }
.an-subtitle { font-size:12px; color:#a9c6dc; }
.an-nav { background:#fff; border-bottom:1px solid var(--an-line); }
.an-main { width:100%; max-width:1760px; margin:0 auto; padding:24px 28px; }
.an-title { font-size:25px; font-weight:650; letter-spacing:-.025em; }
.an-muted { color:var(--an-muted); }
.an-card { border:1px solid var(--an-line); border-radius:12px; box-shadow:none; background:#fff; }
.an-toolbar { gap:8px; align-items:center; flex-wrap:wrap; }
.an-library { height:calc(100vh - 300px); min-height:340px; width:100%; }
.q-btn { text-transform:none; font-weight:550; letter-spacing:0; }
.q-field--outlined .q-field__control { border-radius:8px; }
.an-pdf { width:100%; height:70vh; border:0; background:#e5ebf1; }
.an-info { padding:10px 14px; border-left:3px solid #2e7896; background:#edf6fb; border-radius:5px; }
@media(max-width:1000px){ .an-main{padding:16px;} .an-parameter-grid{grid-template-columns:1fr 1fr;} }
"""


class WorkbenchUI(LibraryPage, AcquisitionPage, ResearchPages):
    def __init__(self, context, files):
        self.ctx = context.lease() if hasattr(context, "lease") else context
        self.files = files
        self.active = "文献库"
        self.library_filters = {}
        self.library_rows = []
        self.search_report = None
        self.current_task = None
        self.current_result = None
        self.rename_preview = None

    def title(self, title, detail):
        from nicegui import ui
        with ui.column().classes("gap-1 mb-4"):
            ui.label(title).classes("an-title")
            ui.label(detail).classes("an-muted")

    def submit(self, kind, label, ids, worker, parameters=None, *, resume_of=None):
        from nicegui import ui
        receipt = self.ctx.jobs.submit(kind, label, list(ids), worker,
                                       parameters=parameters, resume_of=resume_of)
        ui.notify(f"已加入任务中心：{label}", type="positive")
        return receipt

    def output_links(self, report):
        from nicegui import ui
        for value in report.get("outputs", []):
            path = Path(value)
            if path.is_file():
                ui.link(path.name, self.files.register(path), new_tab=True)

    def show_pdf(self, document, *, page=1, title=None, container=None):
        from nicegui import ui
        source = self.ctx.research.app.check_document(document, "direct")
        source.verify()
        if not 1 <= int(page) <= source.identity["page_count"]:
            raise ValueError("PDF物理页码超出范围")
        url = self.files.register(source.pdf) + f"#page={int(page)}&view=FitH"

        def content():
            with ui.row().classes("an-toolbar w-full"):
                ui.label(title or source.identity["title"]).classes("font-semibold grow")
                ui.link("在新标签页打开 PDF", url, new_tab=True)
            ui.label(f"{source.identity['document_role']} · 物理 PDF 第 {page} 页 / "
                     f"{source.identity['page_count']} · {source.identity['identity_basis']}").classes("an-muted text-xs")
            ui.element("iframe").props(f'src="{url}" title="PDF original"').classes("an-pdf")
            with ui.expansion("原页文本与区域放大", icon="zoom_in").classes("w-full"):
                ui.label("区域为 0–1 归一化坐标：左、上、右、下；默认整页。")
                region = ui.input("区域", value="0,0,1,1").classes("w-full")
                image_area = ui.column().classes("w-full")

                async def render():
                    import base64

                    from nicegui import run
                    coordinates = [float(p.strip()) for p in region.value.split(",")]
                    metadata, png = await run.io_bound(
                        self.ctx.research.app.read_original_page, document, int(page),
                        region=coordinates,
                    )
                    image_area.clear()
                    with image_area:
                        ui.image("data:image/png;base64," + base64.b64encode(png).decode())
                        json_view(metadata, label="区域来源")

                async def text():
                    from nicegui import run
                    report = await run.io_bound(
                        self.ctx.research.app.read_original_page_text, document, int(page)
                    )
                    image_area.clear()
                    with image_area:
                        ui.code(report["text"]).classes("w-full max-h-96 overflow-auto")
                        json_view(report, label="原页读取诊断")

                ui.button("读取区域图像", on_click=guard(render), icon="image")
                ui.button("读取此页文字层", on_click=guard(text), icon="text_snippet").props("flat")

        if container is not None:
            container.clear()
            with container:
                content()
        else:
            with ui.dialog() as dialog, ui.card().classes("w-[1100px] max-w-[95vw] an-card"):
                content()
                ui.button("关闭", on_click=dialog.close).props("flat")
            dialog.open()

    def selection_dialog(self):
        from nicegui import ui
        with ui.dialog() as dialog, ui.card().classes("w-[1050px] max-w-[95vw] an-card"):
            ui.label("当前文献选择清单").classes("an-title")
            ids = self.ctx.library.selection()
            rows = [self.ctx.library.get(i) for i in ids]
            rows = [r for r in rows if r]
            ui.label(f"共 {len(rows)} 篇论文；AI执行前另行确认主文和 SI 材料范围。")
            for row in rows:
                with ui.row().classes("an-toolbar w-full"):
                    ui.label(row.get("title_zh") or row["title"]).classes("grow")
                    ui.badge(f"SI {row.get('si_count',0)}").props("outline")
                    ui.button(icon="close", on_click=guard(lambda i=row["id"]:
                        self.ctx.library.set_selection([i], mode="remove"))).props("flat round dense")
            collection = ui.input("保存为固定研究集合").classes("w-full")
            with ui.row().classes("an-toolbar"):
                ui.button("保存集合", icon="folder_special", on_click=guard(lambda:
                    self.ctx.library.save_collection(collection.value, self.ctx.library.selection())))
                ui.button("批量整理", icon="drive_file_rename_outline", on_click=guard(lambda:
                    self.organize_dialog(self.ctx.library.selection())))
                ui.button("解析", icon="document_scanner", on_click=guard(lambda:
                    self.parse_dialog(self.ctx.library.selection())))
                ui.button("AI研究", icon="science", on_click=lambda:
                    (dialog.close(), self.navigate("AI 研究")))
                ui.button("清空", on_click=guard(lambda: self.ctx.library.set_selection([]))).props("flat")
                ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def task_dialog(self):
        from nicegui import ui
        with ui.dialog() as dialog, ui.card().classes("w-[1250px] max-w-[96vw] an-card"):
            ui.label("统一任务中心").classes("an-title")
            ui.label("关闭页面后任务继续运行。暂停、跳过、取消在安全边界生效；正在进行的 HTTP / 文件步骤需先结束。"
                     "进程退出后的中断任务不会自动重发收费请求。").classes("an-info")
            live_status = ui.label("").classes("w-full whitespace-pre-wrap an-muted text-sm")

            def update_summary():
                if dialog.value:
                    live_status.set_text("\n".join(
                        f"{j['label']} · {j['status']} · {j.get('current_index',0)}/{j.get('total',0)} · {j.get('stage','')}"
                        for j in self.ctx.jobs.list()[:12]))

            @ui.refreshable
            def content():
                jobs = self.ctx.jobs.list()
                if not jobs:
                    ui.label("尚无任务。")
                for job in jobs:
                    job_id = job.get("job_id", job.get("id"))
                    with ui.expansion(f"{job.get('label',job.get('kind','任务'))} · {job['status']}",
                                      icon="task_alt").classes("w-full"):
                        ui.label(f"ID {job_id}").classes("an-muted text-xs")
                        progress = job.get("progress") or {}
                        if isinstance(progress, dict):
                            ui.label(json_text(progress)).classes("text-xs whitespace-pre-wrap")
                        with ui.row().classes("an-toolbar"):
                            for action, label, icon in (("pause", "暂停后续", "pause"),
                                ("resume", "恢复调度", "play_arrow"),
                                ("continue", "验证后继续", "verified_user"),
                                ("skip", "跳过当前", "skip_next"),
                                ("cancel", "取消后续", "stop")):
                                ui.button(label, icon=icon, on_click=guard(
                                    lambda a=action, j=job_id: (self.ctx.jobs.control(j, a), content.refresh())
                                )).props("flat dense")
                        result = job.get("result")
                        if isinstance(result, dict):
                            self.output_links(result)
                        if job["status"] in {"FAILED", "PARTIAL", "INTERRUPTED", "CANCELLED"}:
                            if job["kind"] == "acquisition":
                                ui.button("核对并恢复 / 重试未成功项", icon="restart_alt", on_click=guard(
                                    lambda j=job: self.recover_acquisition_dialog(j))).props("outline")
                            elif job["kind"] == "translation":
                                ui.button("重新审阅翻译范围与预算", icon="translate", on_click=guard(
                                    lambda j=job: self.organize_dialog(j["items"]))).props("outline")
                        if job["kind"] == "research" and (job.get("parameters") or {}).get("task"):
                            def reuse(j=job):
                                from copy import deepcopy
                                self.current_task = deepcopy(j["parameters"]["task"])
                                dialog.close()
                                self.navigate("AI 研究")
                            ui.button("载入原契约，重新核对后执行", icon="history", on_click=guard(reuse)).props("outline")
                        json_view(job, label="逐项结果、检查点、费用与恢复记录")
                with ui.expansion("文件操作日志与验证回滚", icon="restore").classes("w-full"):
                    for operation in self.ctx.library.operations():
                        ui.label(f"{operation['id']} · {operation['status']}")
                        json_view(operation, label="逐步移动与恢复证据")
                        if operation["status"] != "ROLLED_BACK":
                            ui.button("验证并回滚此操作", on_click=guard(
                                lambda o=operation: self.submit("rename", "回滚 " + o["id"], [],
                                    lambda c: (c.checkpoint(), self.ctx.library.rollback(o["id"]))[1],
                                    {"operation_id": o["id"]}))).props("outline")
                # Native CLI/MCP runs are readable alongside workbench tasks.
                with ui.expansion("原生科研运行历史", icon="history").classes("w-full"):
                    for row in self.ctx.research.history():
                        ui.label(f"{row['job_id']} · {row['status']} · {row.get('error') or ''}")
                        json_view(row)

            content()
            # Only the concise status line changes automatically. Reading a long
            # diagnostic expansion must not collapse it every few seconds.
            ui.timer(2, update_summary)
            update_summary()
            ui.button("刷新", on_click=content.refresh).props("flat")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def recover_acquisition_dialog(self, job):
        from nicegui import ui
        parameters = job.get("parameters") or {}
        requests = parameters.get("requests", [])
        options = parameters.get("options", {})
        checkpoint = (job.get("result") or {}).get("checkpoint")
        if not requests:
            raise ValueError("此任务没有可恢复的原始获取参数，请从获取页新建任务")
        with ui.dialog() as dialog, ui.card().classes("w-[850px] max-w-[95vw]"):
            ui.label("恢复获取任务").classes("text-xl font-semibold")
            ui.label(f"原批次 {len(requests)} 篇。检查点中成功项仍需通过现有来源核验；未知或失败项按实际参数重新尝试。")
            json_view({"requests": requests, "options": options, "checkpoint": checkpoint}, label="本次恢复的实际范围与参数")
            def start():
                self.submit("acquisition", "恢复获取 " + job["label"], requests,
                    lambda c: self.ctx.acquisition.run(requests, options, context=c,
                                                       checkpoint_path=checkpoint),
                    parameters, resume_of=job["id"])
                dialog.close()
            ui.button("确认恢复获取", icon="play_arrow", on_click=guard(start))
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def settings_dialog(self):
        from nicegui import ui

        from .translation import DEFAULT_OPTIONS
        with ui.dialog() as dialog, ui.card().classes("w-[1150px] max-w-[95vw] an-card"):
            ui.label("设置与任务预设").classes("an-title")
            root = ui.input("文献库根目录", value=str(self.ctx.library.root)).classes("w-full")
            ui.label(f"工作区：{self.ctx.workspace}").classes("an-muted text-xs")
            if hasattr(self.ctx, "switch_root"):
                async def switch():
                    self.ctx.switch_root(root.value)
                    ui.navigate.to("/")
                ui.button("切换文献库", icon="folder_open", on_click=guard(switch))
            ui.label("API密钥从系统环境读取；预设与任务记录不保存密钥或Cookie。")
            mode = ui.select({"bilingual": "中英文双行", "zh": "中文优先", "original": "原题优先",
                              "custom": "自定义短名称优先"},
                             value=self.ctx.settings.get("title_mode", "bilingual"),
                             label="标题显示方式").classes("w-full")
            ui.button("保存显示偏好", on_click=guard(lambda: (
                self.ctx.settings.set("title_mode", mode.value), ui.notify("已保存"))))
            for section, label, defaults in (
                ("translation", "DeepSeek 标题翻译默认参数", DEFAULT_OPTIONS),
                ("parsing", "PDF 解析默认参数", self.ctx.research.parser_options()),
            ):
                with ui.expansion(label, icon="tune").classes("w-full"):
                    current = {**defaults, **self.ctx.settings.get(section, {})}
                    if current:
                        read = parameter_editor(current)
                        ui.button("保存", on_click=guard(lambda s=section, r=read:
                            (self.ctx.settings.set(s, r()), ui.notify("已保存"))))
            with ui.expansion("参数预设", icon="bookmarks").classes("w-full"):
                kind = ui.select(["acquisition", "parsing", "translation", "research"],
                                 value="acquisition", label="类型")
                name = ui.input("预设名称")
                parameters = ui.textarea("实际参数 JSON", value="{}").classes("w-full").props("autogrow")
                ui.button("保存可复用预设", on_click=guard(lambda: (
                    self.ctx.settings.save_preset(kind.value, name.value, json.loads(parameters.value)),
                    ui.notify("已保存预设"))))
                ui.button("载入此预设", on_click=guard(lambda:
                    parameters.set_value(json_text(self.ctx.settings.load_preset(kind.value, name.value)))))
                json_view({k: self.ctx.settings.presets(k) for k in
                           ("acquisition", "parsing", "translation", "research")}, label="现有预设")
            with ui.expansion("环境诊断", icon="health_and_safety").classes("w-full"):
                import importlib.util
                import os
                import shutil
                import sys
                json_view({"python": sys.version.split()[0],
                           "platform": sys.platform,
                           "poppler": bool(shutil.which("pdftoppm")),
                           "tesseract": bool(shutil.which("tesseract")),
                           "playwright": importlib.util.find_spec("playwright") is not None,
                           "DeepSeek_API_key_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
                           "local_only": True}, label="依赖状态")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def navigate(self, page):
        self.active = page
        self.page_content.refresh()

    def build(self):
        from nicegui import ui
        ui.add_css(_STYLE)
        ui.colors(primary="#17678b", secondary="#45627c", accent="#18a999")
        with ui.header().classes("an-header items-center px-7 py-3"):
            with ui.column().classes("gap-0 grow"):
                ui.label("ALETHEIA NEXUS").classes("an-brand")
                ui.label("LOCAL RESEARCH WORKBENCH · v0.8").classes("an-subtitle")
            ui.button("选择清单", icon="playlist_add_check", on_click=guard(self.selection_dialog)).props("flat color=white")
            ui.button("任务中心", icon="pending_actions", on_click=guard(self.task_dialog)).props("flat color=white")
            ui.button("设置", icon="settings", on_click=guard(self.settings_dialog)).props("flat color=white")
        with ui.row().classes("an-nav w-full px-7 py-2 gap-3"):
            for label, icon in (("获取论文", "cloud_download"), ("文献库", "local_library"),
                                ("科研检索", "manage_search"), ("AI 研究", "science"),
                                ("研究成果", "fact_check")):
                ui.button(label, icon=icon, on_click=lambda p=label: self.navigate(p)).props("flat")
            ui.space()
            ui.label(str(self.ctx.library.root)).classes("text-xs an-muted self-center")

        @ui.refreshable
        def page_content():
            with ui.column().classes("an-main"):
                {"获取论文": self.acquisition_page, "文献库": self.library_page,
                 "科研检索": self.search_page, "AI 研究": self.research_page,
                 "研究成果": self.results_page}[self.active]()

        self.page_content = page_content
        page_content()


def build_ui(context):
    """Register pages once; each browser client receives isolated view state."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from nicegui import app, ui

    files = FileRegistry([context.library.root, context.workspace])

    @app.get("/an-file/{token}")
    def read_selected_file(token: str):
        try:
            path = files.resolve(token)
        except (KeyError, ValueError, FileNotFoundError):
            raise HTTPException(404, "Selected file is unavailable") from None
        response = FileResponse(path, filename=path.name,
                                content_disposition_type="inline")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @ui.page("/")
    def page():
        # Roots can only be switched by an explicit local UI operation. New
        # clients get the current root; old capabilities remain individually scoped.
        files.roots = tuple(Path(p).resolve() for p in (context.library.root, context.workspace))
        WorkbenchUI(context, files).build()

    return files
