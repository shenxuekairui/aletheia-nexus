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
from pathlib import Path

from aletheia_nexus.processing.contracts import load_task
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


def costs(root: Path) -> dict:
    calls = []
    files = sorted(root.rglob("manifest.json"))
    smoke = root / "connection-smoke.json"
    if smoke.is_file():
        files.append(smoke)
    for path in files:
        data = json.loads(path.read_text("utf-8"))
        if path != smoke and data.get("schema") != "aletheia-nexus/research-run/v1":
            continue
        calls.extend(data.get("calls", []))
    if any(c.get("currency") != "CNY" for c in calls):
        raise ValueError(
            "evaluation ledger requires CNY calls; currencies cannot be added"
        )
    if any(accounted_cost(c) is None for c in calls):
        raise ValueError("unpriced call in ledger; inspect before spending more")
    return {
        "currency": "CNY",
        "attempts": len(calls),
        "usage_based_estimate": sum(c.get("estimated_cost") or 0 for c in calls),
        "historical_reservations": sum(
            max(c.get("estimated_cost") or 0, c.get("reserved_cost") or 0)
            for c in calls
        ),
        "conservative_spend": sum(accounted_cost(c) for c in calls),
        "unknown_usage_calls": sum(c.get("usage") is None for c in calls),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-total-cny", type=float, required=True)
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.max_total_cny) or args.max_total_cny <= 0:
        parser.error("positive cost cap required")
    root = args.output_dir.resolve()
    with ledger_lock(root):
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
