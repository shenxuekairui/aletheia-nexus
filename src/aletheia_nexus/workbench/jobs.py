"""Durable local task receipts with honest cooperative control at safe boundaries."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition, Lock, RLock
from uuid import uuid4

from aletheia_nexus.research_app import _lock_job_owner

from .settings import SECRET_KEY, atomic_json, state_directory

TERMINAL = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_data(value):
    """No raw exception/provider body or environment credential in task receipts."""
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if SECRET_KEY.search(str(k)) else safe_data(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [safe_data(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        for key, secret in os.environ.items():
            if SECRET_KEY.search(key) and len(secret) >= 8:
                value = value.replace(secret, "[REDACTED]")
        return value
    return value


class TaskCancelled(RuntimeError):
    pass


class TaskContext:
    def __init__(self, manager: TaskManager, job_id: str):
        self.manager, self.job_id = manager, job_id

    @property
    def cancelled(self) -> bool:
        with self.manager._condition:
            return self.manager._controls[self.job_id]["cancel"]

    @property
    def skip_requested(self) -> bool:
        with self.manager._condition:
            return self.manager._controls[self.job_id]["skip"]

    def should_skip(self, item_id=None) -> bool:
        with self.manager._condition:
            controls = self.manager._controls[self.job_id]
            skip = controls["skip"]
            controls["skip"] = False
            return skip

    def checkpoint(self) -> None:
        manager = self.manager
        with manager._condition:
            control = manager._controls[self.job_id]
            if control["cancel"]:
                raise TaskCancelled("cancelled_at_safe_boundary")
            if control["pause"]:
                manager._update(
                    self.job_id,
                    status="PAUSED",
                    stage="等待恢复；当前操作已到达安全边界",
                )
                while control["pause"] and not control["cancel"]:
                    manager._condition.wait(timeout=1)
                if control["cancel"]:
                    raise TaskCancelled("cancelled_at_safe_boundary")
                manager._update(self.job_id, status="RUNNING")

    def progress(self, index=0, total=None, item=None, stage=None, **details):
        values = {"current_index": index, **details}
        if total is not None:
            values["total"] = total
        if item is not None:
            values["current_item"] = item
        if stage is not None:
            values["stage"] = stage
        self.manager._update(self.job_id, **values)

    def record(self, item_id, status, **details):
        with self.manager._condition:
            receipt = self.manager._receipts[self.job_id]
            receipt["records"].append(
                safe_data(
                    {"item_id": item_id, "status": status, "at": now(), **details}
                )
            )
            self.manager._save(receipt)

    def wait_interaction(self, details, timeout=None) -> str:
        if timeout is not None and timeout < 0:
            raise ValueError("interaction timeout cannot be negative")
        manager = self.manager
        deadline = None if timeout is None else time.monotonic() + timeout
        with manager._condition:
            control = manager._controls[self.job_id]
            control["continue"] = False
            manager._update(
                self.job_id, status="INTERACTION_REQUIRED", interaction=details
            )
            while not control["continue"] and not control["skip"]:
                if control["cancel"]:
                    raise TaskCancelled("cancelled_during_interaction")
                if deadline is not None and time.monotonic() >= deadline:
                    manager._update(
                        self.job_id,
                        status="RUNNING",
                        interaction_resolution="timeout_skip",
                    )
                    return "skip"
                manager._condition.wait(timeout=0.25)
            if control["cancel"]:
                raise TaskCancelled("cancelled_during_interaction")
            action = "skip" if control["skip"] else "continue"
            control["skip"] = control["continue"] = False
            manager._update(
                self.job_id, status="RUNNING", interaction_resolution=action
            )
            return action


class TaskManager:
    def __init__(self, state_dir: str | Path, max_workers=3):
        self.directory = state_directory(state_dir, "tasks")
        if (self.directory / ".owner.lock").is_symlink():
            raise ValueError("任务归属锁不能使用符号链接")
        self._owner = _lock_job_owner(self.directory / ".owner.lock", create=True)
        if self._owner is None:
            raise RuntimeError("This workspace already has an active task manager")
        self._condition = Condition(RLock())
        # Existing engines are synchronous and do not share the library's file
        # transaction lock. Queue their material access against physical moves.
        self._materials = Lock()
        self._receipts, self._controls, self._futures = {}, {}, {}
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="an-workbench"
        )
        self._closed = False
        for path in sorted(self.directory.glob("*.json")):
            try:
                if path.is_symlink():
                    continue
                receipt = json.loads(path.read_text(encoding="utf-8"))
                if receipt.get("schema") != "aletheia-nexus/workbench-task/v1":
                    continue
                if receipt["id"] + ".json" != path.name:
                    continue
                if receipt["status"] not in TERMINAL:
                    receipt.update(
                        status="INTERRUPTED",
                        stage="后台进程已终止；须人工核对后创建恢复任务",
                        interrupted_at=now(),
                        billing_uncertain=bool(
                            receipt.get("billing_uncertain")
                            or receipt["kind"]
                            in {"translation", "research", "planning"}
                            or (
                                receipt.get("parameters", {}).get("postprocess") or {}
                            ).get("translate_titles")
                            or receipt.get("parameters", {}).get("translate_titles")
                            or (
                                (
                                    (
                                        receipt.get("parameters", {}).get("postprocess")
                                        or {}
                                    ).get("title_translation")
                                    or {}
                                ).get("enabled")
                            )
                            or (
                                (
                                    receipt.get("parameters", {}).get(
                                        "title_translation"
                                    )
                                    or {}
                                ).get("enabled")
                            )
                        ),
                    )
                    receipt["events"].append({"at": now(), "status": "INTERRUPTED"})
                    self._save(receipt)
                self._receipts[receipt["id"]] = receipt
            except (ValueError, KeyError, OSError):
                # A damaged receipt remains on disk for diagnostics.
                continue

    def _save(self, receipt):
        receipt["updated_at"] = now()
        atomic_json(self.directory / (receipt["id"] + ".json"), safe_data(receipt))

    def _update(self, job_id, **values):
        with self._condition:
            receipt = self._receipts[job_id]
            if "status" in values and values["status"] != receipt["status"]:
                receipt["events"].append({"at": now(), "status": values["status"]})
            receipt.update(safe_data(values))
            self._save(receipt)

    def submit(
        self, kind, label, items, worker, *, parameters=None, resume_of=None
    ) -> dict:
        with self._condition:
            if self._closed:
                raise RuntimeError("task manager is closed")
            if resume_of is not None and resume_of not in self._receipts:
                raise ValueError("unknown previous task")
            job_id = uuid4().hex
            receipt = {
                "schema": "aletheia-nexus/workbench-task/v1",
                "id": job_id,
                "kind": kind,
                "label": label,
                "items": safe_data(items),
                "parameters": safe_data(parameters or {}),
                "resume_of": resume_of,
                "status": "QUEUED",
                "created_at": now(),
                "total": len(items),
                "current_index": 0,
                "records": [],
                "events": [{"at": now(), "status": "QUEUED"}],
            }
            self._receipts[job_id] = receipt
            self._controls[job_id] = {
                "pause": False,
                "cancel": False,
                "skip": False,
                "continue": False,
            }
            self._save(receipt)
            self._futures[job_id] = self._pool.submit(self._run, job_id, worker)
            return deepcopy(receipt)

    def _run(self, job_id, worker):
        context = TaskContext(self, job_id)
        owns_materials = False
        try:
            context.checkpoint()
            if self._receipts[job_id]["kind"] in {
                "acquisition",
                "acquire",
                "parse",
                "research",
                "rename",
                "import",
                "organize",
                "rollback",
            }:
                while not self._materials.acquire(timeout=0.25):
                    context.checkpoint()
                owns_materials = True
                context.checkpoint()
            self._update(job_id, status="RUNNING")
            result = worker(context)
            # A cancellation requested during an indivisible operation does not
            # undo a completed file transaction or hide delivered results.
            with self._condition:
                statuses = {r["status"] for r in self._receipts[job_id]["records"]}
            state = result.get("status") if isinstance(result, dict) else None
            if state == "ROLLBACK_REQUIRED":
                self._update(job_id, needs_recovery=True)
                state = "FAILED"
            elif state == "ROLLED_BACK":
                state = (
                    "COMPLETED"
                    if self._receipts[job_id]["kind"] == "rollback"
                    else "FAILED"
                )
            if state not in {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}:
                state = (
                    "PARTIAL"
                    if statuses & {"FAILED", "SKIPPED", "PARTIAL"}
                    else "COMPLETED"
                )
            self._update(job_id, status=state, result=result, finished_at=now())
        except TaskCancelled:
            self._update(
                job_id,
                status="CANCELLED",
                finished_at=now(),
                stage="已在安全边界取消；已完成结果保留",
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            self._update(
                job_id,
                status="FAILED",
                finished_at=now(),
                error={
                    "type": type(exc).__name__,
                    "code": code or type(exc).__name__,
                    "message": str(exc)[:1200]
                    if isinstance(exc, (ValueError, FileNotFoundError))
                    else code or "See service diagnostics",
                },
            )
        finally:
            if owns_materials:
                self._materials.release()

    def list(self) -> list[dict]:
        with self._condition:
            return deepcopy(
                sorted(
                    self._receipts.values(), key=lambda r: r["created_at"], reverse=True
                )
            )

    def get(self, job_id: str) -> dict:
        with self._condition:
            return deepcopy(self._receipts[job_id])

    def control(self, job_id: str, action: str) -> dict:
        with self._condition:
            receipt = self._receipts[job_id]
            if receipt["status"] in TERMINAL:
                raise ValueError(
                    "A finished task cannot be resumed automatically; create a reviewed recovery task"
                )
            controls = self._controls[job_id]
            if action == "pause":
                controls["pause"] = True
                self._update(
                    job_id,
                    status="PAUSE_REQUESTED",
                    stage="将在当前操作结束后的安全边界暂停",
                )
            elif action == "resume":
                controls["pause"] = False
            elif action == "cancel":
                controls["cancel"] = True
                self._update(
                    job_id,
                    status="CANCEL_REQUESTED",
                    stage="正在等待当前操作结束；远程请求可能已计费",
                )
            elif action in {"skip", "continue"}:
                controls[action] = True
            else:
                raise ValueError("unsupported task control")
            receipt["events"].append({"at": now(), "action": action})
            self._save(receipt)
            self._condition.notify_all()
            return deepcopy(receipt)

    def close(self, wait=False):
        with self._condition:
            self._closed = True
            for controls in self._controls.values():
                controls["cancel"] = True
            self._condition.notify_all()
        self._pool.shutdown(wait=wait, cancel_futures=False)
        # Retain ownership until workers actually terminate, even after UI close.
        if wait or all(f.done() for f in self._futures.values()):
            self._owner.close()
