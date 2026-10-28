"""Explicit, reviewable model assistance for acquisition input, beside manual input."""

from __future__ import annotations

import hashlib
import json


def draft_fingerprint(snapshot):
    """Bind an asynchronous suggestion to the text and placement the user reviewed."""
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalization_preview_rows(preview):
    rows = []
    for item in preview.get("items", []):
        if item.get("duplicate"):
            continue
        request, assignment = item["request"], item.get("assignment") or {}
        folder_mode = assignment.get("folder_mode", "inherit")
        rows.append(
            {
                "id": item["id"],
                "doi": request.get("doi") or "待确认标题",
                "title": request.get("title") or "",
                "folder": "跟随批次默认"
                if folder_mode == "inherit"
                else "文库根目录"
                if folder_mode == "root"
                else request.get("folder") or "需修正",
                "tags": "跟随批次默认"
                if assignment.get("tags_mode", "inherit") == "inherit"
                else ", ".join(request.get("tags") or []) or "无标签",
            }
        )
    return rows


def normalization_dialog(controller, snapshot, apply_preview):
    from nicegui import ui

    from .input_normalization import input_normalization_options
    from .jobs import TERMINAL
    from .labels import status_label
    from .ui_common import guard, json_view, parameter_editor, rows_table

    current = input_normalization_options(
        controller.ctx.settings.get("input_normalization", {})
    )
    state = {"job": None, "shown": None, "result": None, "submitting": False}
    with ui.dialog() as dialog, ui.card().classes("w-[1100px] max-w-[96vw] an-card"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("AI 整理输入").classes("an-title")
            ui.button("关闭", icon="close", on_click=dialog.close).props("flat")
        ui.label(
            "把聊天记录、分组清单或书目信息整理成可编辑的论文清单。"
            "整理只处理输入文字；确认采用后仍可修改各篇目录和标签，再开始获取。"
        ).classes("an-muted")
        ui.label(
            "采用结果会替换当前候选清单及其目录、标签安排；请在预览中核对后采用。"
        ).classes("an-info w-full text-sm")
        budget = ui.number(
            "本次整理费用上限（CNY）", value=current["max_cost"], min=0.01
        ).props("outlined dense")
        with ui.expansion("模型与输出参数", icon="tune").classes("w-full"):
            read = parameter_editor(
                {k: v for k, v in current.items() if k != "max_cost"}
            )
        consent = ui.checkbox(
            "我授权将当前输入文字发送给 DeepSeek，并接受本次费用上限", value=False
        )
        ui.label(
            "不会发送本地 PDF；不会自动下载、创建分类目录或重发失败请求。"
        ).classes("an-muted text-xs")
        result_area = ui.column().classes("w-full")
        replace_changed = ui.checkbox(
            "输入或安排已改变时，我仍确认用此结果替换当前候选安排", value=False
        )
        replace_changed.set_visibility(False)

        async def adopt():
            result = state["result"]
            if not result or not result.get("preview"):
                raise ValueError("尚无可以采用的整理结果")
            now = await snapshot()
            expected = (state["job"].get("parameters") or {}).get("draft_fingerprint")
            if draft_fingerprint(now) != expected and not replace_changed.value:
                replace_changed.set_visibility(True)
                raise ValueError(
                    "整理期间输入文字或保存安排已改变。请保留当前修改，或勾选确认替换后再采用。"
                )
            # The page lease is checked here as well as at job submission.
            controller.ctx.root
            apply_preview(result["preview"])
            dialog.close()
            ui.notify(
                "已采用整理结果；请核对各篇目录、标签和待确认的书目身份。",
                type="positive",
            )

        adopt_button = ui.button(
            "确认采用并预览", icon="fact_check", on_click=guard(adopt)
        )
        adopt_button.set_visibility(False)

        async def poll():
            if not state["job"]:
                return
            job = controller.ctx.jobs.get(state["job"]["id"])
            state["job"] = job
            marker = (job["status"], job.get("updated_at"))
            if state["shown"] == marker:
                return
            state["shown"] = marker
            result = job.get("result") or {}
            state["result"] = result
            result_area.clear()
            with result_area:
                ui.label(
                    f"整理状态：{status_label(job['status'])} · {job.get('stage') or '任务已保存'}"
                ).classes("an-info w-full")
                if result.get("calls"):
                    known = result.get("accounted_cost")
                    ui.label(
                        f"实际请求 {len(result['calls'])} 次；用量估算 {known if known is not None else '待核对'} CNY"
                        + (
                            "；存在计费未知请求，请先核对账本。"
                            if result.get("billing_uncertain")
                            else "；实际账单以服务商为准。"
                        )
                    )
                if job.get("error"):
                    json_view(job["error"], label="失败原因")
                from .messages import user_message

                for diagnostic in result.get("diagnostics", []):
                    ui.label(user_message(diagnostic)).classes(
                        "text-red-8 text-sm whitespace-pre-wrap"
                    )
                for warning in result.get("warnings", []):
                    ui.label(
                        warning
                        if isinstance(warning, str)
                        else warning.get("message", str(warning))
                    ).classes("text-orange-9 text-sm")
                preview = result.get("preview") or {}
                if preview.get("items"):
                    rows_table(
                        normalization_preview_rows(preview),
                        columns=[
                            {"name": key, "field": key, "label": label, "align": "left"}
                            for key, label in (
                                ("doi", "DOI"),
                                ("title", "原题"),
                                ("folder", "建议分类"),
                                ("tags", "标签"),
                            )
                        ],
                    )
                    ui.label(
                        "分类和标签可能包含模型建议，请人工核对；此处没有完成 PDF 身份验证。"
                    ).classes("an-muted text-sm")
                if result:
                    json_view(result, label="来源行、规范化数据与请求账本")
            adopt_button.set_visibility(
                bool((result.get("preview") or {}).get("items"))
                and job["status"] in TERMINAL
            )
            if job["status"] in TERMINAL:
                timer.deactivate()
                start_button.enable()

        async def submit_once():
            if not consent.value:
                raise ValueError("请先授权本次文字外发与费用")
            captured = await snapshot()
            text = captured["text"]
            if not text.strip():
                raise ValueError("请先粘贴要整理的文献文字")
            options = input_normalization_options({**read(), "max_cost": budget.value})
            if options["model"]["currency"] != "CNY":
                raise ValueError("此处费用上限使用 CNY，请将模型计费币种设为 CNY")
            service = controller.ctx.input_normalization
            job = controller.submit(
                "input_normalization",
                "AI 整理文献输入",
                [],
                lambda context: service.normalize(
                    text, options, consent=True, context=context
                ),
                {
                    "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "draft_fingerprint": draft_fingerprint(captured),
                    "options": options,
                },
            )
            controller.ctx.settings.set("input_normalization", options)
            controller.ctx.settings.set("input_normalization_last_job", job["id"])
            state.update(job=job, shown=None, result=None)
            consent.set_value(False)
            replace_changed.set_value(False)
            replace_changed.set_visibility(False)
            start_button.disable()
            timer.activate()
            await poll()

        async def start():
            if state["submitting"] or (
                state["job"] and state["job"]["status"] not in TERMINAL
            ):
                return
            state["submitting"] = True
            start_button.disable()
            try:
                await submit_once()
            except Exception:
                start_button.enable()
                raise
            finally:
                state["submitting"] = False

        start_button = ui.button(
            "开始 AI 整理", icon="auto_awesome", on_click=guard(start)
        )
        timer = ui.timer(0.8, guard(poll), active=False)
        recent = controller.ctx.settings.get("input_normalization_last_job")
        if recent:

            async def previous():
                state.update(job=controller.ctx.jobs.get(recent), shown=None)
                await poll()
                if state["job"]["status"] not in TERMINAL:
                    start_button.disable()
                    timer.activate()

            ui.button("查看上次整理（不再调用模型）", on_click=guard(previous)).props(
                "outline"
            )
            if controller.ctx.jobs.get(recent)["status"] not in TERMINAL:
                start_button.disable()
                ui.timer(0.1, guard(previous), once=True)
        api = getattr(controller.ctx, "normalization_api", None)
        if api:
            with ui.expansion("本机 API 接入", icon="api").classes("w-full"):
                ui.label(
                    "第三方本机工具可提交手动输入或经授权的模型整理。凭据可触发付费整理，仅交给可信工具，重启后失效。"
                )
                ui.code(
                    "POST /an-api/input-normalization/manual\nPOST /an-api/input-normalization/preview\nGET /an-api/input-normalization/{job_id}",
                    language="text",
                ).classes("w-full")
                credential_area = ui.column().classes("w-full")

                def reveal():
                    credential_area.clear()
                    with credential_area:
                        ui.code(
                            "X-AN-Preview-Token: " + api.capability, language="text"
                        ).classes("w-full")

                ui.button("显示本机 API 凭据", on_click=reveal).props("outline")
    dialog.on("hide", timer.deactivate)
    dialog.open()
    return dialog
