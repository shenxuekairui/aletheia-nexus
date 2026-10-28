"""Visible, editable naming templates over the shared library registry."""

from .library import LibraryService
from .ui_common import guard

CUSTOM_TEMPLATE = "custom"


def validate_naming_template(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请填写实际命名模板，或选择一个已有模板。")
    try:
        LibraryService._check_template(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "命名模板无效：最多500字符，只支持下方列出的字段，不支持格式转换或属性访问。"
        ) from exc
    return value


def naming_template_catalog(templates):
    """Use separate choice IDs so user names/templates cannot hide 'custom'."""
    options, values = {}, {}
    for index, (name, template) in enumerate(templates.items()):
        key = f"saved:{index}"
        options[key], values[key] = name, template
    options[CUSTOM_TEMPLATE] = "自定义模板"
    return options, values


class NamingTemplateControl:
    """Read ``value`` on submission; ``apply`` loads an exact preset template."""

    def __init__(
        self, library, value="{title_original}", *, label="主文与 SI 命名模板"
    ):
        from nicegui import ui

        value = validate_naming_template(value)
        self.library = library
        options, self._values = naming_template_catalog(library.templates())
        with ui.column().classes("w-full gap-2"):
            self.choice = (
                ui.select(options, value=self._key(value), label=label)
                .props("outlined dense")
                .classes("w-full")
            )
            self.template = (
                ui.input("实际模板（可直接修改）", value=value)
                .props("outlined dense")
                .classes("w-full")
            )
            ui.label(
                "原题 {title_original} · 中文译名 {title_zh} · 年份 {year} · "
                "期刊 {journal} · 第一作者 {first_author} · 显示名 {custom_name}"
            ).classes("an-muted text-xs whitespace-pre-wrap")
            ui.label(
                "正文与对应 SI 使用同一基础名称；此处编辑不会调用翻译模型或移动已有文件。"
            ).classes("an-muted text-xs")
            with ui.row().classes("an-toolbar w-full"):
                self.name = (
                    ui.input("保存模板名称").props("outlined dense").classes("grow")
                )

                def save():
                    self.save(self.name.value)
                    ui.notify("命名模板已保存，可在下拉列表复用。", type="positive")

                ui.button("保存模板", icon="save", on_click=guard(save)).props(
                    "outline"
                )
        self.choice.on_value_change(self._choose)
        self.template.on_value_change(self._edited)

    def _key(self, template):
        return next(
            (key for key, value in self._values.items() if value == template),
            CUSTOM_TEMPLATE,
        )

    def _choose(self, event):
        if event.value in self._values:
            self.template.set_value(self._values[event.value])

    def _edited(self, event):
        # Incomplete braces are normal while typing. Validate only on use/save.
        self.choice.set_value(self._key(event.value))

    @property
    def value(self):
        return validate_naming_template(self.template.value)

    def apply(self, template):
        template = validate_naming_template(template)
        self.template.set_value(template)
        self.choice.set_value(self._key(template))

    def save(self, name):
        template = self.value
        self.library.save_template(name, template)
        options, self._values = naming_template_catalog(self.library.templates())
        selected = next(
            key
            for key, label in options.items()
            if key != CUSTOM_TEMPLATE and label == name.strip()
        )
        self.choice.set_options(options, value=selected)
        return template
