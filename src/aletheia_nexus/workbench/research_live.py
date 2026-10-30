"""Observe existing native research receipts and ledgers without dispatching work."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from threading import RLock

from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.research_app import _lock_job_owner, read_json

_FINISHED = {"COMPLETED", "PARTIAL", "FAILED", "PREPARED"}
_PHASES = {
    "document_extraction": "单篇科研提取",
    "cross_document_synthesis": "跨文献比较",
    "evidence_review": "证据复核",
    "response_repair": "结构纠错",
    "targeted_revision": "定向修订",
    "document_revision": "科研结果修订",
    "material_supplement": "补充材料处理",
}


def material_groups(documents):
    mains = {}
    for source in documents:
        if source["document_role"] == "ARTICLE":
            mains.setdefault(source["pdf_sha256"], []).append(source["id"])
    owners = {}
    for source in documents:
        matches = mains.get((source.get("parent") or {}).get("pdf_sha256"), [])
        owners[source["id"]] = (
            matches[0]
            if source["document_role"] == "SUPPLEMENT" and len(matches) == 1
            else source["id"]
        )
    return owners


class LiveResearchRuns:
    def __init__(self, app):
        self.app = app
        self.runs = app.workspace / "research" / "runs"
        self._records = {}
        self._workbench_ids = {}
        self._lock = RLock()

    def register(self, receipt, checked, before, *, workbench_job_id=None):
        native_id = receipt["job_id"]
        record = {
            "schema": "aletheia-nexus/workbench-live-research/v1",
            "native_job_id": native_id,
            "workbench_job_id": workbench_job_id,
            "task_fingerprint": checked["task_fingerprint"],
            "mode": checked["task"]["mode"],
            "model": checked["task"].get("model"),
            "documents": checked["documents"],
            "owners": material_groups(checked["documents"]),
            "before": sorted(str(p.resolve()) for p in before),
        }
        path = self.app.path(
            self.app.workspace / "jobs" / native_id / "workbench-live.json", write=True
        )
        write_json(path, record)
        with self._lock:
            self._records[native_id] = record
            if workbench_job_id:
                self._workbench_ids[workbench_job_id] = native_id

    def _tracker(self, job_id):
        with self._lock:
            native_id = self._workbench_ids.get(job_id, job_id)
            record = deepcopy(self._records.get(native_id))
        if not isinstance(native_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", native_id
        ):
            raise ValueError("原生科研任务编号无效")
        if record is None:
            path = self.app.path(
                self.app.workspace / "jobs" / native_id / "workbench-live.json"
            )
            record = read_json(path)
        if (
            not isinstance(record, dict)
            or record.get("native_job_id") != native_id
            or not isinstance(record.get("documents"), list)
            or not isinstance(record.get("owners"), dict)
            or any(
                not isinstance(d, dict) or not isinstance(d.get("id"), str)
                for d in record.get("documents", [])
            )
            or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in record.get("owners", {}).items()
            )
        ):
            raise ValueError("原生科研监控记录与任务编号不一致")
        return native_id, record

    def get(self, job_id):
        """None is unavailable evidence; an empty calls list is observed zero calls."""
        try:
            native_id, tracker = self._tracker(job_id)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return {
                "status": "UNAVAILABLE",
                "calls": None,
                "usage": None,
                "notice": "尚无可读取的原生科研账本，不将缺失记录表示为零费用。",
            }
        base = {
            "native_job_id": native_id,
            "model": tracker.get("model"),
            "material_count": len(tracker["documents"]),
            "group_count": len(set(tracker["owners"].values())),
            "mode": tracker["mode"],
            "calls": None,
            "usage": None,
        }
        receipt_path = self.app.path(
            self.app.workspace / "jobs" / native_id / "status.json"
        )
        try:
            receipt = read_json(receipt_path)
            if not isinstance(receipt, dict):
                raise ValueError("科研运行回执格式无效。")
        except (OSError, ValueError):
            return {
                **base,
                "status": "STARTING",
                "notice": "正在建立原生运行，尚无可读取账本。",
            }
        native_status = receipt.get("status", "UNKNOWN")
        if native_status in {"QUEUED", "RUNNING"}:
            owner = receipt_path.parent / ".owner"
            if owner.exists():
                probe = _lock_job_owner(owner)
                if probe is not None:
                    probe.close()
                    # Re-read after the lock probe: completion may have happened
                    # between the first receipt read and normal owner release.
                    try:
                        receipt = read_json(receipt_path)
                    except (OSError, ValueError):
                        return {
                            **base,
                            "status": "UNAVAILABLE",
                            "notice": "原生状态读取失败，账本未确认。",
                        }
                    native_status = (
                        receipt.get("status", "UNKNOWN")
                        if isinstance(receipt, dict)
                        else "UNKNOWN"
                    )
                    if native_status in {"QUEUED", "RUNNING"}:
                        native_status = "INTERRUPTED"
            else:
                native_status = "OWNERSHIP_UNKNOWN"
        candidates, unreadable = [], []
        if receipt.get("run_directory"):
            try:
                paths = [
                    self.app.path(Path(receipt["run_directory"]) / "manifest.json")
                ]
            except (ValueError, RuntimeError):
                return {
                    **base,
                    "status": "UNAVAILABLE",
                    "notice": "原生运行位置不在授权范围内。",
                }
        else:
            before = set(tracker["before"])
            paths = [
                p
                for p in self.runs.glob("*/manifest.json")
                if str(p.resolve()) not in before
            ]
        for path in paths:
            try:
                manifest = read_json(self.app.path(path))
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("schema") != "aletheia-nexus/research-run/v1"
                ):
                    raise ValueError("科研运行清单格式无效。")
                if manifest.get("task_fingerprint") == tracker["task_fingerprint"]:
                    candidates.append((path, manifest))
            except (OSError, ValueError, RuntimeError):
                unreadable.append(str(path))
        if len(candidates) != 1 or unreadable:
            return {
                **base,
                "status": "UNCERTAIN"
                if len(candidates) > 1 or unreadable
                else native_status,
                "native_status": native_status,
                "candidate_count": len(candidates),
                "notice": "无法唯一绑定本次原生运行；不猜测论文、请求次数或费用。"
                if candidates or unreadable
                else "原生清单尚未交付，账本未读。",
            }
        path, manifest = candidates[0]
        if not isinstance(manifest.get("items"), list) or any(
            not isinstance(r, dict) or not r.get("id") for r in manifest["items"]
        ):
            return {
                **base,
                "status": "UNAVAILABLE",
                "notice": "原生条目结构不完整，进度与费用尚未确认。",
            }
        rows = {row["id"]: row for row in manifest.get("items", [])}
        owners = tracker["owners"]
        finished = {
            sid
            for sid in set(owners.values())
            if rows.get(sid, {}).get("status") in _FINISHED
        }
        finished_materials = sum(owner in finished for owner in owners.values())
        active = [row for row in rows.values() if row.get("status") == "RUNNING"]
        identities = {d["id"]: d for d in tracker["documents"]}
        current = None
        if len(active) == 1:
            row = active[0]
            source = row.get("source") if isinstance(row.get("source"), dict) else {}
            current = {
                "id": row["id"],
                "title": source.get("title")
                or identities.get(row["id"], {}).get("title"),
                "status": row["status"],
            }
        calls = manifest.get("calls")
        if calls is not None and (
            not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)
        ):
            calls = None
        last = calls[-1] if isinstance(calls, list) and calls else {}
        phase = last.get("phase")
        return {
            **base,
            "status": native_status,
            "native_status": native_status,
            "manifest_status": manifest.get("status"),
            "manifest": str(path),
            "calls": calls if isinstance(calls, list) else None,
            "usage": manifest.get("usage"),
            "current_item": current,
            "phase": phase,
            "phase_label": _PHASES.get(phase, "原生科研处理"),
            "call_state": last.get("status"),
            "finished_groups": len(finished),
            "finished_materials": finished_materials,
            "progress_current": finished_materials
            if tracker["mode"] == "local"
            else len(finished),
            "progress_total": len(owners)
            if tracker["mode"] == "local"
            else base["group_count"],
            "items": manifest.get("items", []),
            "comparison": deepcopy(manifest.get("comparison")),
            "observed_only": True,
        }
