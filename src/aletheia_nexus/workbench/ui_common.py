"""Small reusable NiceGUI helpers, with capability-only local file delivery."""

from __future__ import annotations

import inspect
import json
import secrets
from pathlib import Path


class FileRegistry:
    """Serve only individually selected, root-checked files; never mount a tree."""

    def __init__(self, roots):
        self.roots = tuple(Path(p).resolve() for p in roots)
        self.tokens = {}

    def register(self, path):
        from aletheia_nexus.content.gate import sha256_file

        supplied = Path(path)
        if any(p.is_symlink() for p in (supplied, *supplied.parents)):
            raise ValueError("Symbolic links cannot be served")
        target = supplied.resolve(strict=True)
        if not target.is_file() or not any(
            target.is_relative_to(p) for p in self.roots
        ):
            raise ValueError("File is outside the current workbench")
        # Authorization grants never become downloadable, even if the output
        # workspace itself was selected as a read root.
        if any(part in {".authorizations", ".env"} for part in target.parts):
            raise ValueError("Private credentials cannot be served")
        token = secrets.token_urlsafe(32)
        self.tokens[token] = (target, sha256_file(target))
        return "/an-file/" + token

    def resolve(self, token):
        from aletheia_nexus.content.gate import sha256_file

        stored = self.tokens.get(token)
        if stored is None:
            raise KeyError("Unknown file")
        path, expected = stored
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Selected path became a symbolic link")
        target = path.resolve(strict=True)
        if target != path or not any(target.is_relative_to(p) for p in self.roots):
            raise ValueError("Selected file changed location")
        if sha256_file(target) != expected:
            raise ValueError("Selected file bytes changed")
        return target


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def split_tags(value):
    return list(
        dict.fromkeys(
            t.strip() for t in value.replace("，", ",").split(",") if t.strip()
        )
    )


def guard(callback):
    """Convert errors at a UI action boundary into visible, actionable messages."""

    async def run(*_):
        from nicegui import ui

        try:
            result = callback()
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception as exc:
            from .messages import error_record

            record = error_record(exc)
            ui.notify(
                record["message"],
                type="negative",
                timeout=12000,
                multi_line=True,
                close_button="关闭",
            )
            if not record["known"]:
                # Unknown details stay available; an untranslated exception must
                # never disappear behind a generic notification or imply success.
                with (
                    ui.dialog() as diagnostic,
                    ui.card().classes("w-[760px] max-w-[95vw]"),
                ):
                    ui.label("操作未完成").classes("text-lg font-semibold")
                    ui.label(record["message"]).classes("whitespace-pre-wrap")
                    with ui.expansion("原始诊断（专家）", icon="data_object").classes(
                        "w-full"
                    ):
                        ui.code(
                            json.dumps(
                                {"诊断代码": record["code"], "原始原因": record["raw"]},
                                ensure_ascii=False,
                                indent=2,
                            )
                        ).classes("w-full max-h-96 overflow-auto")
                    ui.button("关闭", on_click=diagnostic.close)
                diagnostic.open()

    return run


def json_view(value, *, label="详情"):
    from nicegui import ui

    label = label if label.startswith("专家") else "专家 · " + label
    with ui.expansion(label, icon="data_object").classes("w-full"):
        ui.code(json_text(value), language="json").classes(
            "w-full max-h-96 overflow-auto"
        )


def parameter_editor(values, *, labels=None, prefix=""):
    """Edit supported values, preserving their JSON types and nested structure."""
    from nicegui import ui

    from .labels import CHOICES, PARAMETER_HELP, PARAMETER_LABELS, field_label

    labels = labels or {}
    controls = {}
    with ui.grid(columns=3).classes("w-full an-parameter-grid"):
        for key, value in values.items():
            full_key = f"{prefix}.{key}" if prefix else key
            title = labels.get(
                full_key,
                labels.get(
                    key,
                    PARAMETER_LABELS.get(
                        full_key, PARAMETER_LABELS.get(key, field_label(key))
                    ),
                ),
            )
            help_text = PARAMETER_HELP.get(full_key, PARAMETER_HELP.get(key, ""))
            if isinstance(value, dict):
                with ui.expansion(title, icon="tune").classes("col-span-3"):
                    if help_text:
                        ui.label(help_text).classes("an-muted text-xs")
                    controls[key] = (
                        "nested",
                        parameter_editor(value, labels=labels, prefix=full_key),
                    )
                continue
            with ui.column().classes("gap-1 w-full"):
                choices = CHOICES.get(full_key, CHOICES.get(key))
                if key == "use_system_proxy":
                    controls[key] = (
                        "optional_boolean",
                        ui.select(
                            {
                                "default": "遵循系统默认",
                                "yes": "使用系统代理",
                                "no": "不使用系统代理",
                            },
                            value="default"
                            if value is None
                            else "yes"
                            if value
                            else "no",
                            label=title,
                        )
                        .props("outlined dense")
                        .classes("w-full"),
                    )
                elif choices is not None and isinstance(value, str):
                    options = dict(choices)
                    if value not in options:
                        options[value] = value
                    controls[key] = (
                        "value",
                        ui.select(options, value=value, label=title)
                        .props("outlined dense")
                        .classes("w-full"),
                    )
                elif isinstance(value, bool):
                    controls[key] = ("value", ui.switch(title, value=value))
                elif isinstance(value, (int, float)):
                    if key in {"si_max_bytes", "max_bytes"}:
                        controls[key] = (
                            "mebibytes",
                            ui.number(
                                title.replace("字节", "MiB"),
                                value=value / 1048576,
                                min=0,
                                step=1,
                            )
                            .props("outlined dense")
                            .classes("w-full"),
                        )
                    else:
                        controls[key] = (
                            "integer" if isinstance(value, int) else "number",
                            ui.number(title, value=value)
                            .props("outlined dense")
                            .classes("w-full"),
                        )
                elif isinstance(value, (list, tuple)):
                    # A line editor is sufficient for the supported string lists;
                    # ordinary users never need to type JSON array syntax.
                    controls[key] = (
                        "lines",
                        ui.textarea(title, value="\n".join(str(v) for v in value))
                        .props("outlined dense autogrow")
                        .classes("w-full"),
                    )
                else:
                    controls[key] = (
                        "nullable" if value is None else "value",
                        ui.input(title, value=value or "")
                        .props("outlined dense")
                        .classes("w-full"),
                    )
                if help_text:
                    ui.label(help_text).classes("an-muted text-xs leading-5")

    def read():
        output = {}
        for key, (kind, element) in controls.items():
            if kind == "nested":
                output[key] = element()
            elif kind == "lines":
                output[key] = [
                    line.strip() for line in element.value.splitlines() if line.strip()
                ]
            elif kind == "optional_boolean":
                output[key] = {"default": None, "yes": True, "no": False}[element.value]
            elif kind == "mebibytes":
                if element.value is None or element.value < 0:
                    raise ValueError(f"{field_label(key)}必须为非负数")
                output[key] = int(element.value * 1048576)
            elif kind == "nullable":
                output[key] = element.value or None
            elif kind == "integer":
                if element.value is None or int(element.value) != element.value:
                    raise ValueError(f"{field_label(key)}必须填写整数")
                output[key] = int(element.value)
            else:
                output[key] = element.value
        return output

    return read


def rows_table(rows, *, columns=None, selection=None, row_key="id"):
    from nicegui import ui

    from .labels import field_label, value_label

    if columns is None:
        keys = [k for k in rows[0] if k != "id"] if rows else ["status"]
        columns = [
            {
                "name": k,
                "label": field_label(k),
                "field": k,
                "align": "left",
                "sortable": True,
            }
            for k in keys
        ]
    enum_fields = {
        "status",
        "si_status",
        "parse_status",
        "role",
        "document_role",
        "kind",
        "identity_basis",
        "authority",
        "confirmation",
        "translation_source",
    }
    translated_rows = [dict(r) for r in rows]
    translated_columns = [dict(c) for c in columns]
    for column in translated_columns:
        key = column.get("field", column.get("name"))
        if key in enum_fields:
            display_key = "_an_display_" + key
            column["field"] = display_key
            for row in translated_rows:
                row[display_key] = value_label(row.get(key))
        if key in {"text", "context", "path", "source", "target"}:
            column.setdefault(
                "style",
                "white-space:pre-wrap;min-width:180px;max-width:480px;overflow-wrap:anywhere",
            )
    return ui.table(
        columns=translated_columns,
        rows=translated_rows,
        row_key=row_key,
        selection=selection,
        pagination=20,
    ).classes("w-full")
