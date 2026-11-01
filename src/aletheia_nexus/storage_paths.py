"""User-level locations shared by UI and MCP; native data formats stay unchanged."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .workbench.settings import SettingsStore, atomic_json


def user_data_dir() -> Path:
    # Matches the existing browser profile/runtime convention on every platform.
    return Path.home() / ".aletheia-nexus"


@dataclass(frozen=True)
class StoragePaths:
    library: Path
    library_state_dir: Path
    workspace: Path

    def strings(self):
        return {key: str(value) for key, value in asdict(self).items()}


class PathPreferences:
    def __init__(self, directory=None):
        self.path = Path(directory or user_data_dir()) / "storage-paths.json"

    def read(self):
        if not self.path.exists():
            return {
                "schema": "aletheia-nexus/storage-paths/v1",
                "paths": {},
                "relocations": {},
            }
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema") != "aletheia-nexus/storage-paths/v1":
            raise ValueError("不支持的存储路径配置版本")
        return value

    def save(self, paths: StoragePaths, *, relocations=None):
        value = self.read()
        value["paths"] = paths.strings()
        if relocations is not None:
            value["relocations"] = relocations
        atomic_json(self.path, value)

    def relocations_for(self, paths: StoragePaths):
        # Explicitly selecting an original copy must override its saved move,
        # just as explicit path arguments override saved locations.
        return {
            old: new
            for old, new in self.read().get("relocations", {}).items()
            if not any(
                Path(current).is_relative_to(Path(old))
                for current in (paths.library, paths.workspace)
            )
        }

    def resolve(self, *, library=None, workspace=None, library_state_dir=None):
        saved = self.read()["paths"]
        work = (
            Path(workspace or saved.get("workspace") or user_data_dir() / "workbench")
            .expanduser()
            .resolve()
        )
        # Adopt an existing v0.8.1 workspace only on first use. Never create a
        # cwd-based directory. Thereafter the user-level pointer is authoritative.
        if workspace is None and not saved.get("workspace"):
            legacy = Path.cwd() / ".aletheia-nexus" / "workbench"
            if (legacy / "settings.json").is_file():
                work = legacy.resolve()
        previous_library = SettingsStore(work).get("library_root")
        root = (
            Path(
                library
                or saved.get("library")
                or previous_library
                or user_data_dir() / "library"
            )
            .expanduser()
            .resolve()
        )
        same_library = root == Path(saved.get("library", root)).expanduser().resolve()
        state = library_state_dir or (
            saved.get("library_state_dir") if same_library else None
        )
        return StoragePaths(
            root, Path(state or root / ".an-workbench").expanduser().resolve(), work
        )


def relocate_path(value, relocations):
    """Map old absolute locators to verified copies without editing evidence bytes."""
    path = Path(value)
    if not path.is_absolute():
        return path
    # Longest prefix wins. Follow a nested index that was moved separately
    # after its containing library, without accepting cycles in edited config.
    seen = set()
    for _ in range(len(relocations) + 1):
        if path in seen:
            raise ValueError("存储迁移路径映射存在循环")
        seen.add(path)
        for old, new in sorted(
            relocations.items(), key=lambda item: len(item[0]), reverse=True
        ):
            try:
                updated = Path(new) / path.relative_to(Path(old))
            except ValueError:
                continue
            if updated == path:
                return path
            path = updated
            break
        else:
            return path
    return path


def relocate_values(value, relocations):
    """Project mutable indexes/receipts into the current locations in memory."""
    if isinstance(value, dict):
        return {key: relocate_values(item, relocations) for key, item in value.items()}
    if isinstance(value, list):
        return [relocate_values(item, relocations) for item in value]
    if isinstance(value, str):
        return (
            str(relocate_path(value, relocations))
            if Path(value).is_absolute()
            else value
        )
    return value
