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


def _archive_interaction(receipt, resolution, control=None):
    details = receipt.get("interaction")
    if details is None:
        return {}
    previous = {
        **(deepcopy(details) if isinstance(details, dict) else {"detail": details}),
        "resolution": resolution,
        "started_at": receipt.get("interaction_started_at"),
        "finished_at": now(),
    }
    if receipt.get("interaction_error_type"):
        previous["error_type"] = receipt["interaction_error_type"]
    if receipt.get("interaction_recheck_requested_at"):
        previous["recheck_requested_at"] = receipt["interaction_recheck_requested_at"]
        previous["requested_action"] = "continue"
    if control is not None:
        if control["skip"] or control["continue"]:
            previous["requested_action"] = "skip" if control["skip"] else "continue"
        control["skip"] = control["continue"] = False
    return {
        "last_interaction": previous,
        "interaction": None,
        "interaction_started_at": None,
        "interaction_resolution": resolution,
        "interaction_error_type": None,
        "interaction_recheck_requested_at": None,
    }


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

    def checkpoint(self, *, pump=None) -> None:
        manager = self.manager
        with manager._condition:
            control = manager._controls[self.job_id]
            if control["cancel"]:
                raise TaskCancelled("cancelled_at_safe_boundary")
            if not control["pause"]:
                return
            previous_stage = control.get(
                "stage_before_pause", manager._receipts[self.job_id].get("stage")
            )
            manager._update(
                self.job_id,
                status="PAUSED",
                stage="等待恢复；当前操作已到达安全边界",
            )
        while True:
            with manager._condition:
                if control["cancel"]:
                    raise TaskCancelled("cancelled_at_safe_boundary")
                if not control["pause"]:
                    waiting = (
                        manager._receipts[self.job_id].get("interaction") is not None
                    )
                    manager._update(
                        self.job_id,
                        status="INTERACTION_REQUIRED" if waiting else "RUNNING",
                        stage=control.pop("stage_before_pause", previous_stage),
                    )
                    return
                if pump is None:
                    manager._condition.wait(timeout=1)
                    continue
            # Playwright's synchronous dispatcher belongs to this worker. Never
            # hold the task-control lock while processing browser callbacks.
            try:
                pump(0.25)
            except Exception:
                with manager._condition:
                    if control["cancel"]:
                        raise TaskCancelled("cancelled_at_safe_boundary") from None
                raise

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

    def begin_interaction(self, details) -> None:
        """Publish an owned wait without blocking the core browser poll loop."""
        if not isinstance(details, dict):
            raise ValueError("人工交互详情必须是命名字段。")
        manager = self.manager
        with manager._condition:
            control = manager._controls[self.job_id]
            if control["cancel"]:
                raise TaskCancelled("cancelled_during_interaction")
            receipt = manager._receipts[self.job_id]
            # A repeated notification for the same live wait is not a new wait
            # and must not discard a pending explicit recheck/skip decision.
            if receipt.get("interaction") is not None and receipt[
                "interaction"
            ] == safe_data(details):
                return
            control["continue"] = False
            status = (
                ("PAUSED" if receipt["status"] == "PAUSED" else "PAUSE_REQUESTED")
                if control["pause"]
                else "INTERACTION_REQUIRED"
            )
            manager._update(
                self.job_id,
                status=status,
                interaction=deepcopy(details),
                interaction_started_at=now(),
                interaction_resolution=None,
                interaction_error_type=None,
                interaction_recheck_requested_at=None,
            )

    def finish_interaction(self, resolution) -> None:
        """Archive only the active wait; never release an explicit pause/cancel."""
        if not isinstance(resolution, str) or not resolution.strip():
            raise ValueError("请提供明确的人工交互结束原因。")
        manager = self.manager
        with manager._condition:
            receipt, control = (
                manager._receipts[self.job_id],
                manager._controls[self.job_id],
            )
            values = _archive_interaction(receipt, resolution, control)
            if not values:
                return
            if receipt["status"] in TERMINAL:
                status = receipt["status"]
            elif control["cancel"]:
                status = "CANCEL_REQUESTED"
            elif control["pause"]:
                status = (
                    "PAUSED" if receipt["status"] == "PAUSED" else "PAUSE_REQUESTED"
                )
            else:
                status = "RUNNING"
            manager._update(self.job_id, status=status, **values)

    def poll_interaction(self, *, pump=None) -> str | None:
        """Cooperate with controls; a recheck request never proves verification.

        ``pump`` is used only by a paused checkpoint on the owning worker. The
        mature core remains responsible for polling and deciding when the wait
        has actually ended; a plain None return carries no completion meaning.
        """
        manager = self.manager
        try:
            while True:
                self.checkpoint(pump=pump)
                with manager._condition:
                    control = manager._controls[self.job_id]
                    if control["cancel"]:
                        raise TaskCancelled("cancelled_during_interaction")
                    if control["pause"]:
                        continue
                    if control["skip"]:
                        self.finish_interaction("skip")
                        control["skip"] = control["continue"] = False
                        return "skip"
                    if control["continue"]:
                        control["continue"] = False
                        manager._update(
                            self.job_id,
                            interaction_resolution="recheck_requested",
                            interaction_recheck_requested_at=now(),
                        )
                        return "continue"
                    return None
        except TaskCancelled:
            self.finish_interaction("cancelled")
            raise

    def wait_interaction(self, details, timeout=None, *, pump=None) -> str:
        """Wait for a human decision, optionally servicing an owned event loop.

        ``pump(seconds)`` runs on the waiting worker, outside the control lock.
        It must only process events, never navigate or resolve a challenge.
        """
        if timeout is not None and timeout < 0:
            raise ValueError("interaction timeout cannot be negative")
        manager = self.manager
        deadline = None if timeout is None else time.monotonic() + timeout
        self.begin_interaction(details)
        while True:
            with manager._condition:
                control = manager._controls[self.job_id]
                if control["cancel"]:
                    self.finish_interaction("cancelled")
                    raise TaskCancelled("cancelled_during_interaction")
                if control["continue"] or control["skip"]:
                    action = "skip" if control["skip"] else "continue"
                    self.finish_interaction(action)
                    control["skip"] = control["continue"] = False
                    return action
                paused = control["pause"]
                if not paused and deadline is not None and time.monotonic() >= deadline:
                    self.finish_interaction("timeout_skip")
                    return "skip"
                delay = 0.25
                if deadline is not None:
                    delay = min(delay, max(0.0, deadline - time.monotonic()))
                if not paused and pump is None:
                    manager._condition.wait(timeout=delay)
                    continue
            try:
                if paused:
                    self.checkpoint(pump=pump)
                else:
                    pump(delay)
            except Exception as exc:
                with manager._condition:
                    if control["cancel"]:
                        self.finish_interaction("cancelled")
                        raise TaskCancelled("cancelled_during_interaction") from None
                    self.finish_interaction("event_processing_failed")
                    manager._update(
                        self.job_id,
                        interaction_error_type=type(exc).__name__,
                    )
                raise


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
                            in {
                                "translation",
                                "research",
                                "planning",
                                "input_normalization",
                            }
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
                    receipt.update(_archive_interaction(receipt, "interrupted"))
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
            if values.get("status") in TERMINAL:
                values.update(
                    _archive_interaction(
                        receipt, values["status"].lower(), self._controls.get(job_id)
                    )
                )
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
                if not controls["pause"]:
                    controls["stage_before_pause"] = receipt.get("stage")
                controls["pause"] = True
                self._update(
                    job_id,
                    status="PAUSE_REQUESTED",
                    stage="将在当前操作结束后的安全边界暂停",
                )
            elif action == "resume":
                controls["pause"] = False
                if (
                    not controls["cancel"]
                    and receipt.get("interaction") is not None
                    and receipt["status"] in {"PAUSED", "PAUSE_REQUESTED"}
                ):
                    self._update(
                        job_id,
                        status="INTERACTION_REQUIRED",
                        stage=controls.get("stage_before_pause"),
                    )
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
