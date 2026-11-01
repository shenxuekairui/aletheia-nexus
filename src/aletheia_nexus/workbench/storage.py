"""Conservative folder copies followed by one atomic user-level path switch."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from threading import RLock
from uuid import uuid4

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.research_app import _lock_job_owner
from aletheia_nexus.storage_paths import StoragePaths, relocate_path

from .jobs import TERMINAL


def check_real_path(path):
    if any(
        p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
        for p in (path, *path.parents)
    ):
        raise ValueError("请选择实际文件夹，不能使用符号链接或目录联接")


def open_folder(path):
    path = Path(path).resolve(strict=True)
    if not path.is_dir():
        raise ValueError("文件夹不存在")
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(
            ["open" if sys.platform == "darwin" else "xdg-open", str(path)]
        )


def copy_verified(source, target, *, skip=()):
    """Exclusive creation, streaming hashes, no deletion or merging on failure."""
    files = []
    for entry in source.rglob("*"):
        check_real_path(entry)
        if entry.is_dir():
            (target / entry.relative_to(source)).mkdir(exist_ok=True)
        elif entry.is_file():
            # OS ownership locks describe this process, not user data.
            if entry in skip:
                continue
            dest = target / entry.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            before = sha256_file(entry)
            with entry.open("rb") as incoming, dest.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if before != sha256_file(dest) or before != sha256_file(entry):
                raise ValueError("复制校验失败，原位置继续生效；请使用另一个空目录重试")
            shutil.copystat(entry, dest)
            files.append(entry.relative_to(source))
        else:
            raise ValueError("目录包含不支持的特殊文件")
    return len(files)


class StorageManager:
    def __init__(self, context, preferences, paths):
        self.context, self.preferences, self.paths = context, preferences, paths
        self.busy = False
        self.restart_required = False
        self._lock = RLock()

    def change(self, kind, destination, *, migrate=True):
        if kind not in self.paths.strings():
            raise ValueError("未知数据类型")
        raw = str(destination or "").strip().strip('"')
        if not raw or not Path(raw).expanduser().is_absolute():
            raise ValueError("请选择或输入目标文件夹的完整绝对路径")
        target = Path(raw).expanduser()
        check_real_path(target)
        target = target.resolve()
        with self._lock, self.context.jobs._condition:
            if self.busy or self.restart_required:
                raise ValueError("存储位置已切换，请重新启动工作台")
            if any(job["status"] not in TERMINAL for job in self.context.jobs.list()):
                raise ValueError("请等待所有正在运行、排队或暂停的任务结束后再迁移")
            # Native research/MCP jobs have their own existing OS owner locks.
            for base in (
                self.paths.workspace,
                self.paths.workspace / "research-workspace",
            ):
                for owner_path in (base / "jobs").glob("*/.owner"):
                    check_real_path(owner_path)
                    try:
                        owner = _lock_job_owner(owner_path)
                    except FileNotFoundError:
                        continue
                    if owner is None:
                        raise ValueError("请等待科研或 MCP 后台任务完成后再迁移")
                    owner.close()
            # Keep this flag and the submission gate under the task lock.
            self.busy = True
            self.context.jobs.storage_blocked = True
        try:
            source = getattr(self.paths, kind)
            for current in (
                self.paths.library,
                self.paths.library_state_dir,
                self.paths.workspace,
            ):
                if (
                    target == current
                    or target.is_relative_to(current)
                    or current.is_relative_to(target)
                ):
                    raise ValueError(
                        "新目录不能与现有数据或用户配置目录相同、包含或嵌套"
                    )
            if self.preferences.path.resolve().is_relative_to(target):
                raise ValueError("新目录不能包含用户路径配置文件")
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise ValueError("目标必须是新的或空的文件夹，不能覆盖已有数据")
            target.mkdir(parents=True, exist_ok=True)
            probe = target / (".an-write-test-" + uuid4().hex)
            with probe.open("xb") as handle:
                handle.write(b"writable")
            probe.unlink()
            count = 0
            if migrate:
                check_real_path(source)
                if not source.is_dir():
                    raise ValueError("原目录不存在，无法迁移；请检查位置")
                # Excludes concurrent registry writers in this workbench/other UI.
                with self.context.library._locked():
                    count = copy_verified(
                        source,
                        target,
                        skip={
                            self.context.jobs.directory / ".owner.lock",
                            self.context.library.state_dir / "library.lock",
                        },
                    )
            values = self.paths.strings()
            values[kind] = str(target)
            # A nested native index travels with its owning data folder.
            if migrate or kind == "library":
                for dependent in ("library", "library_state_dir", "workspace"):
                    if not migrate and dependent != "library_state_dir":
                        continue
                    current = getattr(self.paths, dependent)
                    if dependent != kind and current.is_relative_to(source):
                        values[dependent] = str(target / current.relative_to(source))
            updated = StoragePaths(
                **{key: Path(value) for key, value in values.items()}
            )
            if migrate and kind == "workspace":
                # Windows credential targets are scoped by workspace path.
                # Copy a previously persisted credential within the same user's
                # credential manager, never into a data file or log.
                from .api_settings import credential_target

                backend = self.context.api_settings.backend
                if (
                    backend is not None
                    and self.context.settings.get("api", {}).get("storage") == "windows"
                ):
                    saved_key = backend.read(credential_target(source))
                    if saved_key:
                        backend.write(credential_target(target), saved_key)
            aliases = self.preferences.read().get("relocations", {})
            if migrate:
                aliases = {
                    old: str(relocate_path(new, {str(source): str(target)}))
                    for old, new in aliases.items()
                }
                aliases[str(source)] = str(target)
            self.preferences.save(updated, relocations=aliases)
            self.paths = updated
            self.restart_required = True
            return {
                "files": count,
                "paths": updated.strings(),
                "restart_required": True,
            }
        finally:
            self.busy = False
            if not self.restart_required:
                self.context.jobs.storage_blocked = False
