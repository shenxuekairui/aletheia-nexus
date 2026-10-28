"""Readable task delivery and live controls, with native receipts as expert detail."""

from .jobs import TERMINAL
from .labels import status_label, value_label
from .messages import user_message
from .task_view import attachment_rows, state_color, task_costs, task_counts, task_rows
from .ui_common import guard, json_view, rows_table


def render_task_dialog(controller):
    from nicegui import ui

    manager = controller.ctx.jobs
    timers = []
    state = {"limit": 20}
    with (
        ui.dialog() as dialog,
        ui.card().classes("w-[1350px] max-w-[96vw] an-card an-task-dialog"),
    ):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("统一任务中心").classes("an-title")
            ui.button("关闭", icon="close", on_click=dialog.close).props("flat")
        ui.label(
            "关闭页面后任务继续运行。暂停和取消会等待安全边界；已发送的模型请求可能已经计费。进程中断后不会自动重发。"
        ).classes("an-info w-full")
        summary = ui.label().classes("an-muted text-sm")
        with ui.row().classes("an-toolbar w-full"):
            query = (
                ui.input("查找任务名称")
                .props("outlined dense clearable")
                .classes("grow")
            )
            status = ui.select(
                {
                    "all": "全部状态",
                    "active": "正在进行 / 等待处理",
                    "done": "已完成",
                    "attention": "部分完成 / 失败 / 中断",
                },
                value="all",
                label="任务状态",
            ).props("outlined dense")
            ui.button(
                "刷新详细结果", icon="refresh", on_click=lambda: content.refresh()
            ).props("outline")

        def render_snapshot(job, container):
            container.clear()
            with container:
                rows = task_rows(job)
                if rows:
                    counts = task_counts(rows)
                    ui.label(
                        f"已交付 {counts['total']} 项 · 成功 {counts['success']} · 失败 {counts['failed']} · 等待人工 {counts['interaction']} · 部分 {counts['partial']} · 跳过/取消 {counts['skipped']} · 待处理 {counts['pending']}"
                    ).classes("font-medium")
                    fields = [
                        ("title", "文献 / 文件"),
                        ("document_role", "材料角色"),
                        ("status", "处理状态"),
                    ]
                    if job["kind"] in {"acquisition", "acquire"}:
                        fields.extend(
                            [
                                ("si_status", "SI 状态"),
                                ("source", "实际获取来源"),
                                ("attempts", "尝试次数"),
                            ]
                        )
                    fields.extend(
                        [
                            ("phase", "当前阶段"),
                            ("reason", "结果说明与恢复提示"),
                            ("folder", "最终保存目录"),
                        ]
                    )
                    columns = [
                        {
                            "name": k,
                            "label": label,
                            "field": k,
                            "align": "left",
                            "sortable": True,
                        }
                        for k, label in fields
                    ]
                    table = rows_table(rows, columns=columns)
                    table.classes("an-task-table")
                elif job["status"] not in TERMINAL:
                    ui.label(
                        "尚无已交付的逐项结果；当前操作结束后会保存在这里。"
                    ).classes("an-muted")
                attachments = attachment_rows(job)
                if attachments:
                    with ui.expansion(
                        "正文关联附件的独立结果",
                        icon="attach_file",
                        value=any(
                            r["status"] in {"FAILED", "PARTIAL"} for r in attachments
                        ),
                    ).classes("w-full"):
                        rows_table(
                            attachments,
                            columns=[
                                {"name": k, "label": label, "field": k, "align": "left"}
                                for k, label in (
                                    ("title", "所属论文"),
                                    ("filename", "附件"),
                                    ("role", "附件角色"),
                                    ("status", "实际状态"),
                                    ("reason", "诊断与覆盖"),
                                    ("path", "保存位置"),
                                )
                            ],
                        ).classes("an-task-table")
                for cost in task_costs(job):
                    known = (
                        "尚无可核对金额"
                        if cost["known_cost"] is None
                        else f"已知用量估算 {cost['known_cost']:.6f} {cost['currency']}"
                    )
                    suffix = (
                        f"；另有 {cost['unknown_calls']} 次费用待核对"
                        if cost["unknown_calls"]
                        else "；不是服务商实际账单"
                    )
                    ui.label(
                        f"{cost['label']} · 实际请求 {cost['calls']} 次 · {known}{suffix}"
                    ).classes("an-info w-full")
                    if cost["unknown_calls"] and cost["reserved_cost"]:
                        ui.label(
                            f"计费未知请求保留预算预留 {cost['reserved_cost']:.6f} {cost['currency']}，不按零费用处理。"
                        ).classes("text-amber-9 text-sm")
                if job.get("billing_uncertain") and not task_costs(job):
                    ui.label(
                        "该任务存在可能已收费的请求，费用尚不确定。请核对既有模型账本和服务商记录，再决定是否继续。"
                    ).classes("an-info w-full")
                if job.get("error"):
                    ui.label(user_message(job["error"])).classes(
                        "text-red-8 whitespace-pre-wrap"
                    )
                if job.get("needs_recovery"):
                    ui.label(
                        "文件操作尚需恢复。请先核对下方文件日志并验证回滚，不要直接重复改名。"
                    ).classes("text-red-8")
                result = job.get("result")
                if job.get("planning_manifest"):
                    ui.link(
                        "查看本次规划的持久调用账本",
                        controller.files.register(job["planning_manifest"]),
                        new_tab=True,
                    )
                if isinstance(result, dict):
                    controller.output_links(result)
                    if job["kind"] == "input_normalization":

                        def review_input(j=job):
                            controller.ctx.settings.set(
                                "input_normalization_last_job", j["id"]
                            )
                            controller.open_normalization_on_acquire = True
                            dialog.close()
                            controller.navigate("获取论文")

                        ui.button(
                            "回到输入页核对整理结果",
                            icon="fact_check",
                            on_click=guard(review_input),
                        ).props("outline")
                    if job["kind"] == "parse" and result.get("items"):
                        from .ui_research import render_parse_summary

                        items = result["items"]
                        with ui.expansion(
                            "逐文件解析覆盖与诊断", icon="document_scanner"
                        ).classes("w-full"):
                            selected = (
                                ui.select(
                                    {
                                        str(
                                            i
                                        ): f"{item.get('title') or item.get('original_pdf') or item['id']} · {status_label(item['status'])}"
                                        for i, item in enumerate(items)
                                    },
                                    value="0",
                                    label="查看某份文件的解析结果",
                                )
                                .props("outlined")
                                .classes("w-full")
                            )
                            diagnostics = ui.column().classes("w-full")

                            def render_diagnostics():
                                diagnostics.clear()
                                with diagnostics:
                                    item = items[int(selected.value)]
                                    render_parse_summary(item)
                                    if item.get("error"):
                                        ui.label(user_message(item["error"])).classes(
                                            "text-red-8"
                                        )

                            selected.on_value_change(guard(render_diagnostics))
                            render_diagnostics()
                if job["status"] in {"PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED"}:
                    if job["kind"] == "acquisition":
                        ui.button(
                            "核对并恢复 / 重试未成功项",
                            icon="restart_alt",
                            on_click=guard(
                                lambda j=job: controller.recover_acquisition_dialog(j)
                            ),
                        ).props("outline")
                    elif job["kind"] == "translation":
                        ui.button(
                            "重新审阅翻译范围与预算",
                            icon="translate",
                            on_click=guard(
                                lambda j=job: controller.organize_dialog(j["items"])
                            ),
                        ).props("outline")
                task = (job.get("parameters") or {}).get("task") or (
                    (result or {}).get("task") if isinstance(result, dict) else None
                )
                if job["kind"] in {"research", "planning"} and task:

                    def reuse():
                        from copy import deepcopy

                        controller.current_task = deepcopy(task)
                        dialog.close()
                        controller.navigate("AI 研究")

                    ui.button(
                        "载入原计划，重新核对材料与授权",
                        icon="history",
                        on_click=guard(reuse),
                    ).props("outline")
                checkpoint = job.get("checkpoint") or (
                    result.get("checkpoint") if isinstance(result, dict) else None
                )
                if checkpoint:
                    ui.label(f"检查点已保存：{checkpoint}").classes(
                        "an-muted text-xs break-all"
                    )
                json_view(job, label="完整逐项诊断、调用账本与恢复记录")

        def job_card(job):
            job_id = job["id"]
            with ui.expansion(
                f"{job['label']} · {status_label(job['status'])}",
                icon="pending_actions",
            ).classes("w-full an-job-card") as expansion:
                live = ui.column().classes("w-full gap-2")
                snapshot = ui.column().classes("w-full gap-3")
            views = {"ready": False, "status": job["status"], "records": -1}

            def update_live():
                if not dialog.value or not expansion.value:
                    return
                latest = manager.get(job_id)
                expansion.set_text(
                    f"{latest['label']} · {status_label(latest['status'])}"
                )
                live.clear()
                with live:
                    with ui.row().classes("an-toolbar w-full"):
                        ui.badge(
                            status_label(latest["status"]),
                            color=state_color(latest["status"]),
                        )
                        ui.label(
                            f"{value_label(latest.get('stage') or latest['kind'])} · "
                            + (
                                f"已完成 {latest.get('total', 0)} 项"
                                if latest["status"] == "COMPLETED"
                                else f"进度 {latest.get('current_index', 0)}/{latest.get('total', 0)}"
                            )
                        ).classes("text-sm")
                        ui.label(f"任务编号 {job_id[:10]}").classes("an-muted text-xs")
                    interaction = latest.get("interaction") or {}
                    if latest["status"] == "INTERACTION_REQUIRED":
                        paper = interaction.get("paper") or {}
                        title = (
                            paper.get("title")
                            or paper.get("doi")
                            or latest.get("current_item")
                            or "当前论文"
                        )
                        ui.label(
                            f"等待人工处理：{title}\n来源：{interaction.get('source') or '请查看机构浏览器当前页面'}\n{value_label(interaction.get('challenge') or interaction.get('status') or '')}"
                        ).classes("an-info w-full whitespace-pre-wrap")
                        if interaction.get("resume_instruction"):
                            ui.label(interaction["resume_instruction"]).classes(
                                "text-sm"
                            )
                    planning = "planning_max_cost" in (latest.get("parameters") or {})
                    if planning:
                        for cost in task_costs(latest):
                            known = cost["known_cost"]
                            ui.label(
                                f"自然语言规划 · 请求 {cost['calls']} 次 · "
                                + (
                                    f"已知用量估算 {known:.6f} {cost['currency']}"
                                    if known is not None
                                    else "用量金额尚未确认"
                                )
                                + (
                                    f" · {cost['unknown_calls']} 次费用待核对，预留 {cost['reserved_cost'] or 0:.6f} {cost['currency']}"
                                    if cost["unknown_calls"]
                                    else " · 非服务商实际账单"
                                )
                            ).classes("an-info w-full text-sm")
                    elif latest["kind"] == "research":
                        observed = controller.ctx.research.live_run(
                            latest.get("native_job_id") or job_id
                        )
                        current = observed.get("current_item") or {}
                        model = observed.get("model") or {}
                        model_name = (
                            model.get("name")
                            or model.get("model")
                            or model.get("provider")
                            or "本地处理"
                            if isinstance(model, dict)
                            else str(model)
                        )
                        if observed.get("progress_total") is not None:
                            ui.label(
                                f"{model_name} · {observed.get('phase_label') or '原生科研处理'} · "
                                f"已处理 {observed['progress_current']}/{observed['progress_total']} 组 · "
                                f"材料 {observed.get('material_count', 0)} 份"
                            ).classes("font-medium text-sm")
                        if current.get("title"):
                            ui.label(f"当前论文：{current['title']}").classes("text-sm")
                        if observed.get("notice"):
                            ui.label(observed["notice"]).classes("an-muted text-xs")
                        comparison = observed.get("comparison")
                        if comparison:
                            ui.label(
                                f"跨论文比较：{status_label(comparison.get('status'))}"
                                + (
                                    " · " + user_message(comparison["error"])
                                    if comparison.get("error")
                                    else ""
                                )
                            ).classes("an-info w-full text-sm")
                        if isinstance(observed.get("calls"), list):
                            costs = task_costs({"result": observed})
                            for cost in costs:
                                known = cost["known_cost"]
                                ui.label(
                                    f"已观测请求 {cost['calls']} 次 · "
                                    + (
                                        f"已知用量估算 {known:.6f} {cost['currency']}"
                                        if known is not None
                                        else "用量金额尚未确认"
                                    )
                                    + (
                                        f" · {cost['unknown_calls']} 次费用待核对，预留 {cost['reserved_cost'] or 0:.6f} {cost['currency']}"
                                        if cost["unknown_calls"]
                                        else " · 非服务商实际账单"
                                    )
                                ).classes("an-info w-full text-sm")
                        elif latest["status"] not in TERMINAL:
                            ui.label("尚无已确认调用账本，不按零费用处理。").classes(
                                "an-muted text-xs"
                            )
                    with ui.row().classes("an-toolbar"):
                        atomic = (
                            latest["kind"] in {"rename", "rollback"}
                            and latest["status"] != "QUEUED"
                        )
                        can_skip = latest["kind"] in {
                            "acquisition",
                            "acquire",
                            "parse",
                            "translation",
                            "import",
                        } and not (
                            latest["kind"] == "import"
                            and latest.get("import_phase") == "postprocess"
                        )
                        skip_label = (
                            "跳过当前论文"
                            if latest["status"] == "INTERACTION_REQUIRED"
                            else {
                                "acquisition": "跳过下一篇论文",
                                "acquire": "跳过下一篇论文",
                                "parse": "跳过下一份文件",
                                "translation": "跳过下一批标题",
                                "import": "跳过下一份文件",
                            }.get(latest["kind"], "此阶段不支持跳过")
                        )
                        for action, label, icon, enabled in (
                            (
                                "pause",
                                "暂停后续",
                                "pause",
                                latest["status"] in {"RUNNING", "QUEUED"}
                                and not atomic,
                            ),
                            (
                                "resume",
                                "恢复调度",
                                "play_arrow",
                                latest["status"] in {"PAUSED", "PAUSE_REQUESTED"},
                            ),
                            (
                                "continue",
                                "验证后继续",
                                "verified_user",
                                latest["status"] == "INTERACTION_REQUIRED",
                            ),
                            (
                                "skip",
                                skip_label,
                                "skip_next",
                                latest["status"] not in TERMINAL and can_skip,
                            ),
                            (
                                "cancel",
                                "取消后续",
                                "stop",
                                latest["status"] not in TERMINAL
                                and latest["status"] != "CANCEL_REQUESTED"
                                and not atomic,
                            ),
                        ):
                            ui.button(
                                label,
                                icon=icon,
                                on_click=guard(
                                    lambda a=action: (
                                        manager.control(job_id, a),
                                        update_live(),
                                    )
                                ),
                            ).props("flat dense").set_enabled(enabled)
                        if atomic and latest["status"] not in TERMINAL:
                            ui.label(
                                "正在执行不可分的安全文件事务；此时不强行停止。完成后可查看日志并验证回滚。"
                            ).classes("an-muted text-xs")
                        elif (
                            latest["kind"] == "research"
                            and latest["status"] not in TERMINAL
                        ):
                            ui.label(
                                "当前规划请求无法撤回；暂停或取消只会在再次收费请求前的安全边界处理。"
                                if planning
                                else "科研模型不支持即时跳过；可在论文组边界暂停或取消，保留已交付结果后调整新计划。"
                            ).classes("an-muted text-xs")
                if (
                    not views["ready"]
                    or len(latest.get("records", [])) != views["records"]
                    or (
                        latest["status"] in TERMINAL
                        and views["status"] != latest["status"]
                    )
                ):
                    render_snapshot(latest, snapshot)
                    views["ready"] = True
                views["status"] = latest["status"]
                views["records"] = len(latest.get("records", []))

            expansion.on_value_change(guard(update_live))
            timer = ui.timer(2, guard(update_live))
            timers.append(timer)

        @ui.refreshable
        def content():
            for timer in timers:
                timer.active = False
            timers.clear()
            jobs = manager.list()
            needle = (query.value or "").strip().casefold()
            filtered = [
                j
                for j in jobs
                if (not needle or needle in j["label"].casefold())
                and (
                    status.value == "all"
                    or status.value == "active"
                    and j["status"] not in TERMINAL
                    or status.value == "done"
                    and j["status"] == "COMPLETED"
                    or status.value == "attention"
                    and j["status"] in {"PARTIAL", "FAILED", "INTERRUPTED", "CANCELLED"}
                )
            ]
            summary.set_text(
                f"共 {len(jobs)} 个已保存任务 · {len(filtered)} 个符合当前条件"
            )
            if not filtered:
                ui.label("暂无符合条件的任务。").classes("an-muted py-5")
            for job in filtered[: state["limit"]]:
                job_card(job)
            if len(filtered) > state["limit"]:
                ui.button(
                    "加载更多任务",
                    icon="expand_more",
                    on_click=lambda: (
                        state.update(limit=state["limit"] + 20),
                        content.refresh(),
                    ),
                ).props("flat")
            with ui.expansion("文件操作日志与验证回滚", icon="restore").classes(
                "w-full"
            ):
                active_transaction = any(
                    j["kind"] in {"rename", "rollback", "import"}
                    and j["status"] not in TERMINAL
                    for j in jobs
                )
                if active_transaction:
                    ui.label(
                        "文件事务正在执行，逐步日志已持久保存。为避免阻塞监控，完成后请刷新详细结果读取与验证恢复记录。"
                    ).classes("an-info")
                for operation in (
                    [] if active_transaction else controller.ctx.library.operations()
                ):
                    ui.label(
                        f"{operation['created_at'][:10]} · {len(operation.get('preview', {}).get('items', []))} 篇 · {status_label(operation['status'])}"
                    )
                    moves = [
                        {
                            "id": str(i),
                            "source": m["source"],
                            "target": m["target"],
                            "role": m["role"],
                            "status": m.get("state", operation["status"]),
                        }
                        for i, m in enumerate(operation["moves"])
                    ]
                    rows_table(moves).classes("an-task-table")
                    if operation.get("errors"):
                        ui.label(_operation_errors(operation)).classes("text-red-8")
                    json_view(operation, label="完整事务与不可变文件指纹")
                    if operation["status"] != "ROLLED_BACK":
                        ui.button(
                            "验证并回滚此操作",
                            icon="restore",
                            on_click=guard(
                                lambda o=operation: controller.submit(
                                    "rollback",
                                    "验证回滚",
                                    [],
                                    lambda c: (
                                        c.checkpoint(),
                                        controller.ctx.library.rollback(o["id"]),
                                    )[1],
                                    {"operation_id": o["id"]},
                                )
                            ),
                        ).props("outline")
            with ui.expansion("CLI / MCP 原生科研运行历史", icon="history").classes(
                "w-full"
            ):
                histories = controller.ctx.research.history()
                rows = [
                    {
                        "id": r.get("job_id") or r.get("run_id") or str(i),
                        "kind": "自然语言规划"
                        if r.get("kind") == "planning"
                        else "科研运行",
                        "status": r["status"],
                        "reason": user_message(r["error"]) if r.get("error") else "",
                        "folder": r.get("run_directory") or r.get("directory", ""),
                        "calls": (r.get("usage") or {}).get("http_attempts"),
                        "cost": (r.get("usage") or {}).get("estimated_cost"),
                    }
                    for i, r in enumerate(histories)
                ]
                rows_table(
                    rows,
                    columns=[
                        {"name": k, "field": k, "label": label}
                        for k, label in (
                            ("id", "运行编号"),
                            ("kind", "类型"),
                            ("status", "状态"),
                            ("calls", "已记录请求数"),
                            ("cost", "用量费用估算"),
                            ("reason", "诊断"),
                            ("folder", "结果目录"),
                        )
                    ],
                )
                available = {
                    str(i): r for i, r in enumerate(histories) if r.get("task_file")
                }
                if available:
                    picked = (
                        ui.select(
                            {
                                i: ("规划" if r.get("kind") == "planning" else "科研")
                                + " · "
                                + (r.get("run_id") or r.get("job_id") or i)
                                + " · "
                                + status_label(r["status"])
                                for i, r in available.items()
                            },
                            value=next(iter(available)),
                            label="复用已保存的原生任务计划",
                        )
                        .props("outlined")
                        .classes("w-full")
                    )

                    async def reuse_native():
                        from nicegui import run

                        from aletheia_nexus.research_app import read_json

                        def read():
                            path = controller.ctx.research.app.path(
                                available[picked.value]["task_file"]
                            )
                            return controller.ctx.research.validate_plan(
                                read_json(path)
                            )["task"]

                        controller.current_task = await run.io_bound(read)
                        dialog.close()
                        controller.navigate("AI 研究")

                    ui.button(
                        "载入所选计划，重新核对材料和授权",
                        icon="history",
                        on_click=guard(reuse_native),
                    ).props("outline")

        query.on_value_change(lambda _: content.refresh())
        status.on_value_change(lambda _: content.refresh())
        content()
    dialog.on_value_change(
        lambda e: [setattr(t, "active", False) for t in timers] if not e.value else None
    )
    dialog.open()


def _operation_errors(operation):
    return "；".join(user_message(error) for error in operation.get("errors", []))
