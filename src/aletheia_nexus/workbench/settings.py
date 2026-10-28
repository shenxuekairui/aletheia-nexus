"""Small atomic, versioned preferences. Credentials stay in the environment."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from threading import RLock
from uuid import uuid4

SCHEMA = "aletheia-nexus/workbench-settings/v1"
SECRET_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|cookie|authorization|access[_-]?token)", re.I
)


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(
        p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
        for p in (path, *path.parents)
    ):
        raise ValueError("state files cannot be symbolic links")
    temporary = path.with_name(path.name + "." + uuid4().hex + ".part")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def state_directory(root: str | Path, name: str) -> Path:
    root = Path(root).resolve()
    target = root / name
    if target.resolve() != target or not target.resolve().is_relative_to(root):
        raise ValueError("状态子目录不能通过符号链接或目录联接改变位置")
    target.mkdir(parents=True, exist_ok=True)
    return target


def check_preferences(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or SECRET_KEY.search(key):
                raise ValueError("Do not save API keys, tokens, passwords or cookies")
            check_preferences(item)
    elif isinstance(value, list):
        for item in value:
            check_preferences(item)
    json.dumps(value, allow_nan=False)


class SettingsStore:
    def __init__(self, state_dir: str | Path):
        self.path = Path(state_dir).resolve() / "settings.json"
        self._lock = RLock()
        self._data = {"schema": SCHEMA, "defaults": {}, "presets": {}}
        if self.path.exists():
            if self.path.is_symlink():
                raise ValueError("settings cannot be a symbolic link")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA:
                raise ValueError("unsupported workbench settings version")
            check_preferences(data)
            self._data = data

    def get(self, section: str, default=None):
        with self._lock:
            return deepcopy(self._data["defaults"].get(section, default))

    def set(self, section: str, value: object) -> None:
        check_preferences({section: value})
        with self._lock:
            updated = deepcopy(self._data)
            updated["defaults"][section] = deepcopy(value)
            atomic_json(self.path, updated)
            self._data = updated

    def save_preset(self, kind: str, name: str, parameters: dict) -> None:
        if not name.strip() or len(name) > 120:
            raise ValueError("preset name must contain 1–120 characters")
        check_preferences({kind: {name: parameters}})
        with self._lock:
            updated = deepcopy(self._data)
            updated["presets"].setdefault(kind, {})[name.strip()] = deepcopy(parameters)
            atomic_json(self.path, updated)
            self._data = updated

    def presets(self, kind: str) -> dict:
        with self._lock:
            return deepcopy(self._data["presets"].get(kind, {}))

    def load_preset(self, kind: str, name: str) -> dict:
        return self.presets(kind)[name]

    def delete_preset(self, kind: str, name: str) -> None:
        with self._lock:
            updated = deepcopy(self._data)
            del updated["presets"][kind][name]
            atomic_json(self.path, updated)
            self._data = updated
