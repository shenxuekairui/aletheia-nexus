"""Execute explicit task files with a cumulative local cost ledger.

This measures execution, not scientific correctness. Keep private papers and output
outside Git. Remote permission and DEEPSEEK_API_KEY are still required.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from aletheia_nexus.processing.contracts import digest, load_task
from aletheia_nexus.processing.engine import run_task, write_json
from aletheia_nexus.processing.provider import accounted_cost


@contextmanager
def ledger_lock(root: Path):
    """OS-owned lock: concurrent runs cannot spend against the same old balance."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "evaluation.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("another evaluation owns this cost ledger") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def ledger_calls(root: Path) -> dict[str, list]:
    ledger = {}
    files = sorted(root.rglob("manifest.json"))
    smoke = root / "connection-smoke.json"
    if smoke.is_file():
        files.append(smoke)
    for path in files:
        data = json.loads(path.read_text("utf-8"))
        if path != smoke and data.get("schema") != "aletheia-nexus/research-run/v1":
            continue
        ledger[path.relative_to(root).as_posix()] = data.get("calls", [])
    return ledger


def record_provider_bill(root: Path, amount: float, note: str) -> Path:
    """Caller holds ledger_lock; user confirms bill scope covers existing calls."""
    if not math.isfinite(amount) or amount < 0 or not note.strip():
        raise ValueError("nonnegative provider bill and coverage note required")
    ledger = ledger_calls(root)
    now = datetime.now(timezone.utc)
    path = root / "provider-bills" / (now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    write_json(
        path,
        {
            "schema": "aletheia-nexus/provider-bill-checkpoint/v1",
            "recorded_at": now.isoformat(),
            "currency": "CNY",
            "amount": amount,
            "coverage_note": note,
            "covered_attempts": sum(len(calls) for calls in ledger.values()),
            "covered_calls": {
                name: {"count": len(calls), "sha256": digest(calls)}
                for name, calls in ledger.items()
                if calls
            },
        },
    )
    return path


def costs(root: Path) -> dict:
    ledger = ledger_calls(root)
    calls = [call for rows in ledger.values() for call in rows]
    if any(c.get("currency") != "CNY" for c in calls):
        raise ValueError(
            "evaluation ledger requires CNY calls; currencies cannot be added"
        )
    pending = calls
    bill = None
    checkpoints = sorted((root / "provider-bills").glob("*.json"))
    if checkpoints:
        checkpoint = checkpoints[-1]
        bill = json.loads(checkpoint.read_text("utf-8"))
        if (
            bill["schema"] != "aletheia-nexus/provider-bill-checkpoint/v1"
            or bill["currency"] != "CNY"
            or not math.isfinite(bill["amount"])
            or bill["amount"] < 0
        ):
            raise ValueError("invalid provider bill checkpoint")
        for name, covered in bill["covered_calls"].items():
            if digest(ledger.get(name, [])[: covered["count"]]) != covered["sha256"]:
                raise ValueError("billed call history changed; reconcile ledger")
        pending = [
            call
            for name, rows in ledger.items()
            for call in rows[bill["covered_calls"].get(name, {}).get("count", 0) :]
        ]
    if any(accounted_cost(c) is None for c in pending):
        raise ValueError("unpriced call in ledger; inspect before spending more")
    report = {
        "currency": "CNY",
        "attempts": len(calls),
        "usage_based_estimate": sum(c.get("estimated_cost") or 0 for c in calls),
        "historical_reservations": sum(
            max(c.get("estimated_cost") or 0, c.get("reserved_cost") or 0)
            for c in calls
        ),
        "conservative_spend": (bill["amount"] if bill else 0)
        + sum(accounted_cost(c) for c in pending),
        "unknown_usage_calls": sum(c.get("usage") is None for c in calls),
    }
    if bill:
        original = [accounted_cost(c) for c in calls]
        report.update(
            provider_bill_checkpoint=str(checkpoint),
            provider_bill_cny=bill["amount"],
            provider_bill_recorded_at=bill["recorded_at"],
            covered_attempts=bill["covered_attempts"],
            subsequent_attempts=len(pending),
            subsequent_estimated_cny=sum(accounted_cost(c) for c in pending),
            unreconciled_conservative_spend=None
            if any(c is None for c in original)
            else sum(original),
            accounting_basis="provider_bill_plus_subsequent_estimates",
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="*", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-total-cny", type=float, required=True)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--record-provider-bill-cny", type=float)
    parser.add_argument("--bill-note", default="")
    args = parser.parse_args()
    if not math.isfinite(args.max_total_cny) or args.max_total_cny <= 0:
        parser.error("positive cost cap required")
    if args.record_provider_bill_cny is None and not args.tasks:
        parser.error("task files or --record-provider-bill-cny required")
    if args.record_provider_bill_cny is not None and args.tasks:
        parser.error("record a provider bill separately from starting tasks")
    root = args.output_dir.resolve()
    with ledger_lock(root):
        if args.record_provider_bill_cny is not None:
            record_provider_bill(root, args.record_provider_bill_cny, args.bill_note)
            print(json.dumps(costs(root), ensure_ascii=False, indent=2))
            return 0
        return execute(args, root)


def execute(args, root: Path) -> int:
    report = {
        "schema": "aletheia-nexus/workflow-execution-evaluation/v1",
        "scientific_scoring": "not-performed",
        "items": [],
    }
    for path in args.tasks:
        task = load_task(path)
        balance = costs(root)
        limit = task["budget"].get("max_cost")
        if task.get("model", {}).get("currency") != "CNY" or limit is None:
            raise ValueError("each task requires explicit CNY prices and max_cost")
        if balance["conservative_spend"] + limit > args.max_total_cny:
            raise ValueError("cumulative evaluation budget would be exceeded")
        result = run_task(
            task,
            base_dir=path.resolve().parent,
            output_dir=root / "evaluations",
            allow_remote=args.allow_remote,
        )
        item = {
            "task": str(path.resolve()),
            "mode": task["mode"],
            "status": result["status"],
            "run_directory": result["run_directory"],
            "usage": result["usage"],
        }
        report["items"].append(item)
        report["costs"] = costs(root)
        write_json(root / "workflow-executions.json", report, overwrite=True)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
