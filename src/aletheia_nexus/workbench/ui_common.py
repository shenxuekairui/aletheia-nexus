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
        if not target.is_file() or not any(target.is_relative_to(p) for p in self.roots):
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
    return list(dict.fromkeys(t.strip() for t in value.replace("，", ",").split(",")
                              if t.strip()))


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
            code = getattr(exc, "code", type(exc).__name__)
            ui.notify(f"{code}：{str(exc)[:800]}", type="negative", timeout=12000,
                      multi_line=True, close_button=True)
    return run


def json_view(value, *, label="详情"):
    from nicegui import ui
    with ui.expansion(label, icon="data_object").classes("w-full"):
        ui.code(json_text(value), language="json").classes("w-full max-h-96 overflow-auto")


def parameter_editor(values, *, labels=None):
    """Edit supported values, preserving their JSON types and nested structure."""
    from nicegui import ui
    labels = labels or {}
    controls = {}
    with ui.grid(columns=3).classes("w-full an-parameter-grid"):
        for key, value in values.items():
            title = labels.get(key, key)
            if isinstance(value, dict):
                with ui.expansion(title, icon="tune").classes("col-span-3"):
                    controls[key] = ("nested", parameter_editor(value, labels=labels))
            elif isinstance(value, bool):
                controls[key] = ("value", ui.switch(title, value=value))
            elif isinstance(value, (int, float)):
                controls[key] = ("integer" if isinstance(value, int) else "number",
                                 ui.number(title, value=value))
            elif isinstance(value, (list, tuple)):
                controls[key] = ("json", ui.input(title, value=json_text(value)))
            else:
                controls[key] = ("nullable" if value is None else "value",
                                 ui.input(title, value=value or ""))

    def read():
        output = {}
        for key, (kind, element) in controls.items():
            if kind == "nested":
                output[key] = element()
            elif kind == "json":
                output[key] = json.loads(element.value)
            elif kind == "nullable":
                output[key] = element.value or None
            elif kind == "integer":
                if element.value is None or int(element.value) != element.value:
                    raise ValueError(f"{key} must be an integer")
                output[key] = int(element.value)
            else:
                output[key] = element.value
        return output

    return read


def rows_table(rows, *, columns=None, selection=None, row_key="id"):
    from nicegui import ui
    if columns is None:
        keys = list(rows[0]) if rows else ["id", "status"]
        columns = [{"name": k, "label": k, "field": k, "align": "left",
                    "sortable": True} for k in keys]
    return ui.table(columns=columns, rows=rows, row_key=row_key,
                    selection=selection, pagination=20).classes("w-full")
