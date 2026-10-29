"""Live acquisition delivery beside the input, backed by durable task receipts."""

from __future__ import annotations

from copy import deepcopy

from .jobs import TERMINAL
from .labels import status_label, value_label
from .messages import user_message
from .task_view import state_color, task_counts, task_rows
from .ui_common import guard, rows_table
from .ui_tasks import continue_label, skip_control


def _paper_key(request):
    import json

    from .acquisition import normalize_request

    try:
        return normalize_request(request).key
    except (TypeError, ValueError):
        # An old invalid request remains a distinct, read-only diagnostic row.
        return "invalid:" + json.dumps(request, sort_keys=True, ensure_ascii=False)


def acquisition_progress(job):
    """Count papers independently of later translation/parse file progress."""
    requests = (job.get("parameters") or {}).get("requests") or []
    delivered = {}
    for record in job.get("records", []):
        if isinstance(record.get("request"), dict):
            delivered[_paper_key(record["request"])] = record
    current_item = job.get("current_item")
    if isinstance(current_item, dict) and isinstance(current_item.get("request"), dict):
        delivered[_paper_key(current_item["request"])] = current_item
    for item in (job.get("result") or {}).get("items", []):
        if isinstance(item.get("request"), dict):
            delivered[_paper_key(item["request"])] = item
    current = job.get("current") or {}
    current_key = _paper_key(current) if current else None
    items = []
    for request in requests:
        key = _paper_key(request)
        row = delivered.get(key)
        if row is None:
            state = (
                "INTERACTION_REQUIRED"
                if key == current_key and job["status"] == "INTERACTION_REQUIRED"
                else "RUNNING"
                if key == current_key and job["status"] not in TERMINAL
                else "DEFERRED"
            )
            row = {
                "request": request,
                "status": state,
                "phase": "等待人工处理"
                if state == "INTERACTION_REQUIRED"
                else "尚未完成"
                if state == "RUNNING"
                else "尚未开始",
                "si_status": "NOT_ATTEMPTED",
            }
        items.append(row)
    rows = task_rows(
        {"kind": "acquisition", "status": job["status"], "result": {"items": items}}
    )
    attachments = [
        row["si_status"] for row in rows if row["si_status"] != "NOT_REQUESTED"
    ]
    completed = sum(
        _paper_key(request) in delivered
        and delivered[_paper_key(request)].get("status")
        not in {None, "RUNNING", "DEFERRED", "NOT_ATTEMPTED"}
        for request in requests
    )
    return {
        "rows": rows,
        "counts": task_counts(rows),
        "attachments": {
            "total": len(attachments),
            "completed": attachments.count("COMPLETED"),
            "running": attachments.count("RUNNING"),
            "interaction": sum(
                s in {"INTERACTION_REQUIRED", "AUTH_REQUIRED"} for s in attachments
            ),
            "failed": attachments.count("FAILED"),
            "partial": attachments.count("PARTIAL"),
            "not_found": attachments.count("NOT_FOUND"),
        },
        "current": (
            job.get("current_item")
            if job.get("task_phase") == "postprocess"
            and isinstance(job.get("current_item"), str)
            else current.get("title") or current.get("doi") or ""
        ),
        "status": job["status"],
        "download_completed": completed,
        "download_remaining": len(requests) - completed,
    }


def acquisition_stage_summary(job, progress=None):
    """Keep original paper scheduling separate from title/file work counters."""
    progress = progress if progress is not None else acquisition_progress(job)
    if job.get("task_phase") != "postprocess" or job["status"] in TERMINAL:
        return ""
    stage = value_label(job.get("stage") or "整理已入库论文")
    unit = (
        "文件"
        if any(word in stage for word in ("解析", "OCR"))
        else "标题"
        if "翻译" in stage
        else None
    )
    index, total = job.get("current_index"), job.get("total")
    if unit and type(index) is int and type(total) is int and total > 0:
        stage += f" · {unit} {index}/{total}"
    if progress["counts"]["total"] and not progress["download_remaining"]:
        return "下载阶段已完成，正在" + stage + "；整个任务将在后续处理结束后完成。"
    return (
        "当前篇正在"
        + stage
        + "；之后继续余下获取"
        + (
            f"（尚有 {progress['download_remaining']} 篇未完成获取）。"
            if progress["download_remaining"]
            else "。"
        )
    )


def acquisition_count_summary(progress):
    counts = progress["counts"]
    return (
        f"下载论文：正文成功 {counts['success']} · 失败 {counts['failed']} · 等待人工 {counts['interaction']} · "
        f"跳过 {counts['skipped']} · 其余未完成 {counts['pending'] + counts['partial']} · 共 {counts['total']} 篇"
    )


class AcquisitionProgressPanel:
    def __init__(self, controller):
        from nicegui import ui

        self.controller = controller
        controller.acquisition_progress_panel = self
        self.manager = controller.ctx.jobs
        self.root = str(controller.ctx.library.root)
        self.job_id, self.marker = None, None
        self.choices = {}
        last = controller.ctx.settings.get("acquisition_live_task", {}) or {}
        for job in self.manager.list():
            if job["kind"] == "acquisition" and (
                (job.get("parameters") or {}).get("library") == self.root
                or (last.get("library") == self.root and job["id"] == last.get("id"))
            ):
                self.choices[job["id"]] = (
                    f"{job['label']} · {status_label(job['status'])}"
                )
        selected = last.get("id") if last.get("library") == self.root else None
        if selected not in self.choices:
            selected = next(iter(self.choices), None)
        with ui.card().classes("an-card w-full gap-3") as self.card:
            with ui.row().classes("an-toolbar w-full justify-between"):
                ui.label("本页获取进度").classes("font-semibold text-lg")
                ui.button(
                    "全部任务与历史",
                    icon="history",
                    on_click=guard(controller.task_dialog),
                ).props("flat dense")
            self.choice = (
                ui.select(self.choices, value=selected, label="查看获取任务")
                .props("outlined dense")
                .classes("w-full")
            )
            self.choice.set_visibility(bool(self.choices))
            self.body = ui.column().classes("w-full gap-3")
            self.timer = ui.timer(0.8, guard(self.refresh), active=False)
        self.choice.on_value_change(guard(lambda: self.show(self.choice.value)))
        if selected:
            self.show(selected)
        else:
            with self.body:
                ui.label(
                    "开始获取后，当前论文、结果和需要人工处理的事项会直接显示在这里。关闭页面后任务仍继续。"
                ).classes("an-muted text-sm")

    def track(self, job):
        self.choices[job["id"]] = job["label"] + " · " + status_label(job["status"])
        self.choice.set_options(self.choices, value=job["id"])
        self.choice.set_visibility(True)
        self.controller.ctx.settings.set(
            "acquisition_live_task", {"id": job["id"], "library": self.root}
        )
        self.show(job["id"])

    def show(self, job_id):
        self.job_id, self.marker = job_id, None
        self.refresh()

    def refresh(self):
        from nicegui import ui

        if self.body.is_deleted or not self.job_id:
            return
        job = self.manager.get(self.job_id)
        progress = acquisition_progress(job)
        marker = deepcopy(
            (
                progress,
                job.get("stage"),
                job.get("task_phase"),
                job.get("current_index"),
                job.get("total"),
                job.get("interaction"),
                job.get("interaction_resolution"),
                job.get("error"),
                (job.get("result") or {}).get("warnings"),
            )
        )
        if marker == self.marker:
            return
        self.marker = marker
        label = job["label"] + " · " + status_label(job["status"])
        if self.choices.get(self.job_id) != label:
            self.choices[self.job_id] = label
            self.choice.set_options(self.choices, value=self.job_id)
        self.body.clear()
        with self.body:
            with ui.row().classes("an-toolbar w-full"):
                ui.badge(status_label(job["status"]), color=state_color(job["status"]))
                ui.label(value_label(job.get("stage") or job["status"])).classes(
                    "font-medium"
                )
            ui.label(acquisition_count_summary(progress)).classes("an-info w-full")
            stage_summary = acquisition_stage_summary(job, progress)
            if stage_summary:
                ui.label(stage_summary).classes("an-info w-full text-sm")
            attachments = progress["attachments"]
            if attachments["total"]:
                ui.label(
                    f"附件（含 SI）：完成 {attachments['completed']} · 处理中 {attachments['running']} · 需人工 {attachments['interaction']} · "
                    f"失败 {attachments['failed']} · 部分 {attachments['partial']} · 未发现 {attachments['not_found']}"
                ).classes("text-sm")
                if attachments["interaction"]:
                    ui.label(
                        "附件下载需要单独完成人工登录或验证，已验证正文保留。任务结束后点击“选择失败论文重试 / 仅补 SI”，"
                        "选择“仅补 SI”即可；不会重新下载有效正文或改掉现有正文名称。"
                    ).classes("an-info w-full text-sm")
            if progress["current"] and job["status"] not in TERMINAL:
                ui.label("当前论文 / 文件：" + str(progress["current"])).classes(
                    "text-sm break-all"
                )
            interaction = job.get("interaction") or {}
            at_boundary = (
                job["status"] == "INTERACTION_REQUIRED"
                and interaction.get("stage") == "paper_boundary"
            )
            if job["status"] == "INTERACTION_REQUIRED":
                ui.label(
                    interaction.get("resume_instruction")
                    if at_boundary
                    else "请在机构浏览器完成人工登录或验证，程序会自动复查并继续；“立即重新检查”只请求再次检查，不代表验证通过或论文已经获取。"
                    if interaction.get("auto_monitoring")
                    else "请到机构浏览器完成登录或验证，然后点击“验证后继续”；也可跳过当前论文。"
                ).classes("an-info w-full")
                if interaction.get("source"):
                    ui.label("需要操作的来源：" + interaction["source"]).classes(
                        "an-muted text-sm break-all"
                    )
            if job.get("error"):
                ui.label(user_message(job["error"])).classes("text-red-8 text-sm")
            with ui.row().classes("an-toolbar"):
                for action, label, enabled in (
                    ("pause", "暂停后续", job["status"] in {"RUNNING", "QUEUED"}),
                    (
                        "resume",
                        "恢复获取",
                        job["status"] in {"PAUSED", "PAUSE_REQUESTED"},
                    ),
                    (
                        "continue",
                        continue_label(job),
                        job["status"] == "INTERACTION_REQUIRED",
                    ),
                    (
                        "skip",
                        skip_control(job)[0],
                        job["status"] in {"RUNNING", "INTERACTION_REQUIRED"}
                        and skip_control(job)[1],
                    ),
                    (
                        "cancel",
                        "取消后续",
                        job["status"] not in TERMINAL
                        and job["status"] != "CANCEL_REQUESTED",
                    ),
                ):

                    def control(a=action):
                        latest = self.manager.get(self.job_id)
                        if a == "skip" and not skip_control(latest)[1]:
                            raise ValueError(
                                "任务阶段已变化，当前不能跳过论文。请查看最新进度后再操作。"
                            )
                        if (
                            a == "continue"
                            and latest["status"] != "INTERACTION_REQUIRED"
                        ):
                            raise ValueError(
                                "当前任务已不再等待人工操作，请查看最新进度。"
                            )
                        self.manager.control(self.job_id, a)
                        self.refresh()

                    ui.button(label, on_click=guard(control)).props(
                        "outline dense"
                    ).set_enabled(enabled)
            if job["status"] not in TERMINAL:
                ui.label(
                    "暂停与取消在安全边界生效；已开始的传输或模型请求可能继续完成。"
                ).classes("an-muted text-xs")
            if progress["rows"]:
                rows_table(
                    progress["rows"],
                    columns=[
                        {"name": k, "field": k, "label": label, "align": "left"}
                        for k, label in (
                            ("title", "论文"),
                            ("status", "正文状态"),
                            ("si_status", "SI 状态"),
                            ("phase", "阶段"),
                            ("reason", "结果说明"),
                        )
                    ],
                ).classes("an-task-table w-full")
            result = job.get("result") or {}
            for warning in result.get("warnings", []):
                ui.label(user_message(warning)).classes("text-orange-9 text-sm")
            if job["status"] in {"PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED"}:
                ui.button(
                    "选择失败论文重试 / 仅补 SI",
                    icon="restart_alt",
                    on_click=guard(
                        lambda: self.controller.recover_acquisition_dialog(job)
                    ),
                ).props("outline")
        if job["status"] in TERMINAL:
            self.timer.deactivate()
        else:
            self.timer.activate()
