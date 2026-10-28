"""Named task parameters loaded into real controls, without a second executor."""

from .ui_common import guard


def preset_controls(settings, kind, read, apply, *, title="任务参数预设"):
    from nicegui import ui

    with ui.expansion(title, icon="bookmarks").classes("w-full"):
        with ui.row().classes("an-toolbar w-full"):
            selected = ui.select(
                list(settings.presets(kind)), value=None, label="已有预设"
            ).classes("grow")
            name = ui.input("保存名称").classes("grow")

            def load():
                if not selected.value:
                    raise ValueError("请先选择参数预设")
                apply(settings.load_preset(kind, selected.value))
                name.set_value(selected.value)
                ui.notify(
                    "预设已载入实际表单；本次外发和费用授权仍需重新勾选。",
                    type="positive",
                )

            def save():
                settings.save_preset(kind, name.value, read())
                selected.set_options(list(settings.presets(kind)), value=name.value)
                ui.notify("当前实际参数已保存为预设。", type="positive")

            ui.button("载入表单", icon="download", on_click=guard(load)).props(
                "outline"
            )
            ui.button("保存当前参数", icon="save", on_click=guard(save))
        ui.label(
            "预设只保存参数组合，不保存当前材料选择、密钥或本次授权；执行仍走相同校验与服务。"
        ).classes("an-muted text-sm")
    return selected
