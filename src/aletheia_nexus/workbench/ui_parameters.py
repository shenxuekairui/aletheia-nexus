"""Tiered parameter presentation sharing one typed reader and atomic preset apply."""

from .ui_common import parameter_editor


def parameter_sections(values, *, common=(), advanced=(), expert=(), labels=None):
    from nicegui import ui

    used = set(common) | set(advanced) | set(expert)
    if len(used) != len(common) + len(advanced) + len(expert) or used - set(values):
        raise ValueError("参数展示分组包含重复或未知字段")
    groups = []
    for keys, title, icon in (
        (list(common), None, None),
        (list(advanced), "高级设置", "tune"),
        (
            [*expert, *(k for k in values if k not in used)],
            "专家设置",
            "settings_suggest",
        ),
    ):
        if not keys:
            continue
        selected = {k: values[k] for k in keys}
        if title:
            with ui.expansion(title, icon=icon).classes("w-full"):
                form = parameter_editor(selected, labels=labels)
        else:
            form = parameter_editor(selected, labels=labels)
        groups.append((set(keys), form))

    def read():
        return {key: value for _, form in groups for key, value in form().items()}

    def pending_updates(incoming):
        if not isinstance(incoming, dict) or set(incoming) - set(values):
            raise ValueError("预设包含不支持的参数")
        pending = []
        for keys, form in groups:
            pending.extend(
                form._pending_updates({k: v for k, v in incoming.items() if k in keys})
            )
        return pending

    def apply(incoming):
        for element, value in pending_updates(incoming):
            element.set_value(value)

    read.apply = apply
    read._pending_updates = pending_updates
    return read
