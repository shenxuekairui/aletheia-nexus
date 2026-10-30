"""A focused title editor over the existing independent translation service."""

from __future__ import annotations

import inspect
import math

from .jobs import TERMINAL
from .labels import status_label
from .messages import user_message
from .translation import translation_options
from .ui_common import guard, json_view, parameter_editor, rows_table
from .ui_presets import preset_controls


def title_translation_scope(library, ids, *, only_missing=True):
    """Freeze selected identities; protect researcher text independently of cache."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError("请先在文献列表左侧勾选一篇或多篇论文，再点击“补中文标题”。")
    rows, eligible, protected, existing = [], [], [], []
    for paper_id in ids:
        row = library.get(paper_id)
        if row is None:
            raise ValueError("所选文献已移出当前文库，请刷新列表后重新勾选。")
        previous = row.get("translation") or {}
        has_title = bool((row.get("title_zh") or "").strip())
        if has_title and (
            previous.get("confirmed") or previous.get("source") == "manual"
        ):
            protected.append(paper_id)
            state = "保留人工译名"
        elif has_title and only_missing:
            existing.append(paper_id)
            state = "已有译名，保持"
        else:
            eligible.append(paper_id)
            state = "补充缺失译名" if not has_title else "重新审阅未确认译名"
        rows.append({**row, "translation_action": state})
    return {
        "rows": rows,
        "eligible": eligible,
        "protected": protected,
        "existing": existing,
    }


def render_title_translation_dialog(controller, ids, *, on_updated=None):
    from nicegui import ui

    ids = list(dict.fromkeys(ids))
    initial = title_translation_scope(controller.ctx.library, ids)
    options = translation_options(controller.ctx.settings.get("translation", {}))
    state = {"job": None, "marker": None, "manual_baseline": None}
    on_updated = on_updated or getattr(controller, "_refresh_library_metadata", None)

    async def updated():
        if on_updated:
            result = on_updated()
            if inspect.isawaitable(result):
                await result

    with ui.dialog() as dialog, ui.card().classes("w-[1050px] max-w-[96vw] an-card"):
        ui.label(f"补中文标题 · 已选 {len(ids)} 篇").classes("an-title")
        ui.label(
            "可手动填写，也可让 DeepSeek 仅翻译原题。原题独立保留；保存译名不会改 PDF、文件名或分类。"
        ).classes("an-info w-full")
        with ui.expansion(
            "手动填写 / 修改（不联网）", icon="edit_note", value=len(ids) == 1
        ).classes("w-full"):
            choices = {
                row["id"]: row.get("title_original") or row.get("title") or row["id"]
                for row in initial["rows"]
            }
            selected = ui.select(
                choices,
                value=initial["eligible"][0] if initial["eligible"] else ids[0],
                label="手动填写哪篇论文",
                with_input=True,
            ).classes("w-full")
            selected.set_visibility(len(ids) > 1)
            original = ui.label().classes("an-muted text-sm break-all")
            manual = ui.textarea("中文标题").props("autogrow").classes("w-full")
            confirmed = ui.checkbox("我已核对并确认此译名", value=False)

            def load_manual():
                paper = controller.ctx.library.get(selected.value)
                if paper is None:
                    raise ValueError("文献已移出当前文库，请刷新后重试。")
                original.set_text(
                    "原题：" + (paper.get("title_original") or paper["title"])
                )
                value = paper.get("title_zh") or ""
                manual.set_value(value)
                confirmed.set_value(
                    bool((paper.get("translation") or {}).get("confirmed"))
                )
                state["manual_baseline"] = value

            selected.on_value_change(guard(load_manual))
            load_manual()

            async def save_manual():
                controller.ctx.translation.edit(
                    selected.value, manual.value, confirmed=confirmed.value
                )
                state["manual_baseline"] = manual.value
                ui.notify(
                    "中文标题已保存；原题、PDF 和文件名保持原样。", type="positive"
                )
                await updated()
                try:
                    refresh_estimate()
                except ValueError as exc:
                    ui.notify(
                        "译名已保存；请修正模型参数后再刷新翻译范围："
                        + user_message(exc),
                        type="warning",
                    )

            ui.button("保存中文标题", icon="save", on_click=guard(save_manual))

        ui.label("DeepSeek 批量补充").classes("font-semibold text-lg")
        only_missing = ui.checkbox("仅补缺失中文标题，已有译名保持", value=True)
        cost = ui.number(
            "本次费用上限（按下方计费币种）", value=options["max_cost"], min=0.01
        ).classes("w-full")
        with ui.expansion("模型、缓存与预算参数", icon="tune").classes("w-full"):
            read_advanced = parameter_editor(
                {k: v for k, v in options.items() if k != "max_cost"}
            )
            force = ui.checkbox("忽略缓存，重新请求未人工编辑的译名", value=False)

        def read_options():
            return translation_options({**read_advanced(), "max_cost": cost.value})

        def apply_options(values):
            checked = translation_options(values)
            advanced = {k: v for k, v in checked.items() if k != "max_cost"}
            read_advanced._pending_updates(advanced)
            read_advanced.apply(advanced)
            cost.set_value(checked["max_cost"])
            consent.set_value(False)
            force.set_value(False)
            refresh_estimate()

        preset_controls(
            controller.ctx.settings,
            "translation",
            read_options,
            apply_options,
            title="标题翻译预设",
        )
        consent = ui.checkbox(
            "我授权仅将下方待翻译原题发送给 DeepSeek，并接受所示费用上限", value=False
        )
        estimate_area = ui.column().classes("w-full gap-2")
        progress = ui.label().classes("an-muted text-sm")

        def refresh_estimate():
            scope = title_translation_scope(
                controller.ctx.library, ids, only_missing=only_missing.value
            )
            configuration = read_options()
            estimate = controller.ctx.translation.estimate(
                scope["eligible"], configuration
            )
            busy = (
                state["job"]
                and controller.ctx.jobs.get(state["job"])["status"] not in TERMINAL
            )
            translate_button.set_enabled(bool(scope["eligible"]) and not busy)
            pending = len(estimate["pending"]) + (
                len(estimate["cached"]) if force.value else 0
            )
            cached = 0 if force.value else len(estimate["cached"])
            estimate_area.clear()
            with estimate_area:
                ui.label(
                    f"已选 {len(ids)} 篇 · 保留人工译名 {len(scope['protected'])} 篇 · "
                    f"已有译名保持 {len(scope['existing'])} 篇 · 本次处理 {len(scope['eligible'])} 篇；"
                    f"缓存复用 {cached} 篇，待外发 {pending} 篇。"
                ).classes("an-info w-full")
                ui.label(
                    f"模型 {configuration['model']['name']} · 预计基础请求 {math.ceil(pending / configuration['batch_size'])} 次 · "
                    f"请求上限 {configuration['max_calls']} 次 · 费用上限 {configuration['max_cost']} "
                    f"{'人民币元' if estimate['currency'] == 'CNY' else '美元'}。"
                    "只发送原题，不发送 PDF、正文或整个文库。"
                ).classes("text-sm")
                with ui.expansion("查看逐篇标题与处理范围", icon="list").classes(
                    "w-full"
                ):
                    rows_table(
                        [
                            {
                                "id": row["id"],
                                "title_original": row.get("title_original")
                                or row.get("title"),
                                "title_zh": row.get("title_zh") or "—",
                                "action": row["translation_action"],
                            }
                            for row in scope["rows"]
                        ],
                        columns=[
                            {"name": key, "field": key, "label": label, "align": "left"}
                            for key, label in (
                                ("title_original", "原题"),
                                ("title_zh", "当前中文标题"),
                                ("action", "本次处理"),
                            )
                        ],
                    )
                json_view(estimate, label="缓存指纹、稳定身份与预算（专家）")
            return scope, estimate, configuration

        def scope_changed():
            consent.set_value(False)
            refresh_estimate()

        only_missing.on_value_change(guard(scope_changed))
        force.on_value_change(guard(scope_changed))

        def submit():
            if (
                state["job"]
                and controller.ctx.jobs.get(state["job"])["status"] not in TERMINAL
            ):
                raise ValueError(
                    "本窗口的标题任务仍在进行，请先查看进度，不要重复提交。"
                )
            scope, estimate, configuration = refresh_estimate()
            selected_ids = list(scope["eligible"])
            if not selected_ids:
                raise ValueError(
                    "所选论文已有中文标题；可手动修改，或取消仅补缺失以审阅未确认译名。"
                )
            grant, forced, missing = (
                bool(consent.value),
                bool(force.value),
                bool(only_missing.value),
            )
            pending = len(estimate["pending"]) + (
                len(estimate["cached"]) if forced else 0
            )
            if pending and not grant:
                raise ValueError(
                    "请核对待外发标题、模型与费用上限，再明确勾选本次授权。"
                )

            def worker(context):
                # A manual value entered while this job was queued wins. The
                # actual service also protects manual edits made during HTTP.
                current = title_translation_scope(
                    controller.ctx.library, selected_ids, only_missing=missing
                )
                return controller.ctx.translation.translate(
                    current["eligible"],
                    configuration,
                    consent=grant,
                    context=context,
                    force=forced,
                )

            job = controller.submit(
                "translation",
                f"补中文标题 {len(selected_ids)} 篇",
                selected_ids,
                worker,
                {
                    "ids": selected_ids,
                    "only_missing": missing,
                    "force": forced,
                    "title_entry": "focused",
                    "options": configuration,
                    "library": str(controller.ctx.library.root),
                },
            )
            state["job"], state["marker"] = job["id"], None
            translate_button.disable()
            consent.set_value(False)
            progress.set_text(
                "已创建标题任务；关闭此窗口后仍可在任务中心查看进度与费用。"
            )
            timer.activate()

        async def poll():
            if not state["job"] or progress.is_deleted:
                return
            job = controller.ctx.jobs.get(state["job"])
            marker = job.get("updated_at"), job["status"]
            if marker == state["marker"]:
                return
            state["marker"] = marker
            progress.set_text("标题任务：" + status_label(job["status"]))
            if job.get("error"):
                progress.set_text(
                    "标题任务："
                    + status_label(job["status"])
                    + "；"
                    + user_message(job["error"])
                )
            if job["status"] in TERMINAL:
                timer.deactivate()
                result = job.get("result") or {}
                if result.get("billing_uncertain") or job.get("billing_uncertain"):
                    progress.set_text(
                        "标题任务："
                        + status_label(job["status"])
                        + "；有请求费用待核对，请查看任务中心，勿盲目重试。"
                    )
                refresh_estimate()
                if manual.value == state["manual_baseline"]:
                    load_manual()
                await updated()

        timer = ui.timer(0.8, guard(poll), active=False)
        dialog.on("hide", lambda: timer.deactivate())
        with ui.row().classes("an-toolbar w-full"):
            ui.button("核对标题范围与费用", on_click=guard(refresh_estimate)).props(
                "outline"
            )
            translate_button = ui.button(
                "开始补中文标题 / 复用缓存", icon="translate", on_click=guard(submit)
            )
            ui.button("查看翻译任务", on_click=guard(controller.task_dialog)).props(
                "flat"
            )
            ui.button("关闭", on_click=dialog.close).props("flat")
        refresh_estimate()
    dialog.open()
    return dialog
