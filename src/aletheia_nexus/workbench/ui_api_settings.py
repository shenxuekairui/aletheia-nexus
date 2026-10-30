"""Visible Chinese API configuration; opening the card never sends a request."""

from .api_settings import ApiSettingsService
from .jobs import TERMINAL
from .ui_common import guard


def render_api_settings(ctx):
    from nicegui import run, ui

    service = getattr(ctx, "api_settings", None)
    if service is None:
        can_change = getattr(ctx, "can_change_api_configuration", None)
        if can_change is None:

            def can_change():
                return not any(job["status"] not in TERMINAL for job in ctx.jobs.list())

        service = ApiSettingsService(
            ctx.settings,
            ctx.workspace,
            can_change=can_change,
            source=getattr(ctx, "api_credentials", None),
        )
        ctx.api_settings = service
    state = {"busy": False}
    initial = service.status()
    with ui.card().classes("an-card w-full gap-3") as card:
        with ui.row().classes("an-toolbar w-full"):
            ui.icon("vpn_key", size="26px")
            ui.label("DeepSeek API 配置").classes("text-xl font-semibold")
            configured = ui.badge()
        source = ui.label().classes("an-muted text-sm")
        storage = ui.label().classes("an-muted text-sm")
        ui.label(
            "密钥仅用于你明确授权的远程请求；本地导入、整理、解析和检索无需密钥。"
            "已配置不表示认证、账户余额或模型权限已通过检查。"
        ).classes("an-info w-full text-sm")
        key = (
            ui.input(
                "新的 DeepSeek API 密钥（留空保留现有）",
                value="",
                password=True,
                password_toggle_button=True,
            )
            .props("outlined autocomplete=new-password")
            .classes("w-full")
        )
        base = (
            ui.input("接口基础地址", value=initial["base_url"])
            .props("outlined")
            .classes("w-full")
        )
        ui.label(
            "支持 DeepSeek 官方 HTTPS 主站或 /v1。不要粘贴密钥到地址中；当前不开放第三方密钥转发代理。"
        ).classes("an-muted text-xs")
        persist = ui.checkbox(
            "同时保存到当前工作区的 Windows 用户凭据管理器（可跨重启）", value=False
        )
        persist.set_enabled(initial["persistence_supported"])
        ui.label(
            "不勾选时，新密钥仅在本次进程使用；先前已保存的 Windows 凭据保持原样。"
            "预设、任务、日志和导出不保存密钥。"
        ).classes("an-muted text-xs")
        message = ui.label().classes("text-sm whitespace-pre-wrap")

        def show_status(report):
            configured.set_text("本机已配置" if report["configured"] else "尚未配置")
            configured.props("color=teal" if report["configured"] else "color=grey")
            label = {
                "environment": "环境变量（当前进程）",
                "windows": "此工作区的 Windows 用户凭据",
                "session": "本次设置的会话密钥",
                "missing": "未提供密钥",
            }.get(report["source"], "当前进程")
            source.set_text("密钥来源：" + label + "；现有密钥不会回显。")
            storage.set_text(
                "此电脑支持当前工作区的 Windows 用户凭据保存；默认不会写入。"
                if report["persistence_supported"]
                else "当前平台只使用会话或环境变量；此处不提供跨重启密钥保存。"
            )
            if report.get("warning"):
                message.set_text(report["warning"])

        def busy(value):
            state["busy"] = value
            for button in (save_button, check_button):
                if not button.is_deleted:
                    button.set_enabled(not value)
            for control in (key, base):
                if not control.is_deleted:
                    control.set_enabled(not value)
            if not persist.is_deleted:
                persist.set_enabled(not value and initial["persistence_supported"])

        async def save():
            if state["busy"]:
                return
            busy(True)
            base_value, key_value, keep = base.value, key.value, bool(persist.value)
            message.set_text("正在保存 API 配置…")
            try:
                report = await run.io_bound(
                    service.save, base_url=base_value, api_key=key_value, persist=keep
                )
                if card.is_deleted:
                    return
                show_status(report)
                base.set_value(report["base_url"])
                message.set_text(
                    "配置已保存；密钥已写入此工作区的 Windows 用户凭据管理器。"
                    if keep
                    else "配置已保存；没有将密钥写入预设、任务或普通文件。"
                )
            except Exception:
                if not card.is_deleted:
                    message.set_text("本次配置未完整保存，请按错误提示处理后重试。")
                raise
            finally:
                if not key.is_deleted:
                    key.set_value("")
                busy(False)

        async def check():
            if state["busy"]:
                return
            busy(True)
            base_value, key_value = base.value, key.value
            message.set_text("正在检查连接，仅查询模型列表，不发送论文或生成内容…")
            try:
                report = await run.io_bound(
                    service.check_connection, base_url=base_value, api_key=key_value
                )
                if not card.is_deleted:
                    message.set_text(
                        report["message"]
                        + " 检查不会保存输入；需要应用新配置时请点击“保存 API 配置”。"
                    )
            except Exception:
                if not card.is_deleted:
                    message.set_text("连接尚未确认；本机密钥与接口配置没有因此改变。")
                raise
            finally:
                busy(False)

        with ui.row().classes("an-toolbar"):
            save_button = ui.button("保存 API 配置", icon="save", on_click=guard(save))
            check_button = ui.button(
                "检查连接（不发论文）", icon="wifi", on_click=guard(check)
            ).props("outline")
        ui.label(
            "模型、单价、Token 与费用上限请在常用默认设置和相应任务表单核对；"
            "保存 API 配置不会自动运行研究或开启材料外发授权。"
        ).classes("an-muted text-sm")
        show_status(initial)
    return card
