"""Offline input/assignment and task-concurrency acceptance, without HTTP or PDFs.

Each size runs in its own process for attributable Windows peak working-set
measurements. Only the requested report and an isolated temporary task workspace
are written. All DOI strings are synthetic fixtures and are never acquired.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from aletheia_nexus.core.organization import normalize_folder
from aletheia_nexus.workbench.acquisition import normalize_request
from aletheia_nexus.workbench.acquisition_input import (
    build_input_preview,
    parse_text_input,
)
from aletheia_nexus.workbench.jobs import TERMINAL, TaskManager


def memory():
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (key, ctypes.c_size_t)
                for key in (
                    "peak",
                    "working",
                    "peak_paged",
                    "paged",
                    "peak_nonpaged",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not query(current(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return {
            "working_set_bytes": counters.working,
            "process_peak_working_set_bytes": counters.peak,
        }
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "process_peak_working_set_bytes": peak
        if sys.platform == "darwin"
        else peak * 1024
    }


def fixture(count, mode="grouped", *, prefix="offline"):
    lines, expected = [], []
    if mode == "grouped":
        for index in range(count):
            group = f"{prefix}/分类{index // 100:03}"
            if index % 100 == 0:
                lines.append(f"[{group}] | 标签=待读,离线测试")
            doi = f"10.9999/{prefix}-{index:06}"
            if index % 137 == 0:
                lines.append(f"{index + 1}. {doi} | 分类=/ | 标签=[]")
                expected.append((None, (), "root"))
            elif index % 17 == 0:
                lines.append(f"{index + 1}. {doi} | 分类=单篇/特别 | 标签=独立")
                expected.append(("单篇/特别", ("独立",), "custom"))
            else:
                lines.append(f"{index + 1}. {doi}")
                expected.append((group, ("待读", "离线测试"), "custom"))
    else:
        unique = count * 8 // 10
        base = [
            f"10.9999/{prefix}-{i:06} | 分类=分组/{i // 100:03} | 标签=待读"
            for i in range(unique)
        ]
        lines = [
            *base,
            *base[: count // 10],
            *[
                f"10.9999/{prefix}-{i:06} | 分类=冲突/分类 | 标签=另一标签"
                for i in range(count // 10)
            ],
        ]
        original = [(f"分组/{i // 100:03}", ("待读",), "custom") for i in range(unique)]
        expected = [
            *original,
            *original[: count // 10],
            *(("冲突/分类", ("另一标签",), "custom") for _ in range(count // 10)),
        ]
    return "\n".join(lines), expected


def preview(text):
    parsed = parse_text_input(text)
    return build_input_preview(
        parsed["entries"],
        normalizer=normalize_request,
        folder_check=normalize_folder,
        errors=parsed["errors"],
        warnings=parsed["warnings"],
    )


def case(count, mode):
    before = memory()
    text, expected = fixture(count, mode)
    started = time.perf_counter()
    report = preview(text)
    elapsed = time.perf_counter() - started
    assignments = (
        all(
            (
                row["request"]["folder"],
                row["request"]["tags"],
                row["assignment"]["folder_mode"],
            )
            == wanted
            and row["assignment"]["tags_mode"] == "custom"
            for row, wanted in zip(report["items"], expected, strict=True)
        )
        if expected
        else True
    )
    expected_duplicate = count // 10 if mode == "conflicts" else 0
    expected_papers = count * 8 // 10 if mode == "conflicts" else count
    passed = (
        len(report["items"]) == count
        and not report["errors"]
        and len({row["id"] for row in report["items"]}) == count
        and report["paper_count"] == expected_papers
        and sum(row["duplicate"] for row in report["items"]) == expected_duplicate
        and len(report["conflicts"]) == expected_duplicate
        and report["ready"] is (mode == "grouped")
        and assignments
    )
    return {
        "rows": count,
        "mode": mode,
        "seconds": elapsed,
        "rows_per_second": count / elapsed,
        "input_characters": len(text),
        "input_utf8_bytes": len(text.encode("utf-8")),
        "fits_model_api_text_limit": len(text) <= 50000
        and len(text.encode("utf-8")) <= 200000,
        "memory_before": before,
        "memory_after": memory(),
        "items": len(report["items"]),
        "unique_papers": report["paper_count"],
        "duplicates": sum(row["duplicate"] for row in report["items"]),
        "conflicts": len(report["conflicts"]),
        "errors": len(report["errors"]),
        "assignments_preserved": assignments,
        "passed": passed,
    }


def concurrent():
    gate, lock = threading.Barrier(4), threading.Lock()
    active, maximum = 0, 0
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="an-input-stress-") as temporary:
        directory = Path(temporary).resolve()
        assert directory.is_relative_to(Path(tempfile.gettempdir()).resolve())
        manager = TaskManager(directory, max_workers=4)
        jobs = []

        def worker(index):
            def run(context):
                nonlocal active, maximum
                context.checkpoint()
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                try:
                    gate.wait(timeout=15)
                    text, expected = fixture(500, prefix=f"task{index}")
                    result = preview(text)
                    correct = all(
                        (
                            item["request"]["folder"],
                            item["request"]["tags"],
                            item["assignment"]["folder_mode"],
                        )
                        == wanted
                        and item["assignment"]["tags_mode"] == "custom"
                        and item["request"]["doi"].startswith(f"10.9999/task{index}-")
                        for item, wanted in zip(result["items"], expected, strict=True)
                    )
                    if not result["ready"] or not correct:
                        raise AssertionError("Concurrent assignments changed")
                    context.progress(1, 1, stage="离线输入验证")
                    return {
                        "status": "COMPLETED",
                        "count": 500,
                        "assignment_check": correct,
                        "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "model_calls": 0,
                        "cost": 0,
                    }
                finally:
                    with lock:
                        active -= 1

            return run

        try:
            for index in range(8):
                jobs.append(
                    manager.submit(
                        "input_normalization",
                        f"离线并发样本{index}",
                        [str(index)],
                        worker(index),
                    )
                )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and any(
                manager.get(job["id"])["status"] not in TERMINAL for job in jobs
            ):
                time.sleep(0.02)
            finished = [manager.get(job["id"]) for job in jobs]
        finally:
            manager.close(wait=True)
        reopened = TaskManager(directory)
        try:
            persisted = [reopened.get(job["id"]) for job in jobs]
        finally:
            reopened.close(wait=True)
        passed = (
            maximum == 4
            and all(
                job["status"] == "COMPLETED"
                and job["result"]["assignment_check"]
                and job["result"]["model_calls"] == 0
                for job in finished
            )
            and all(job["status"] == "COMPLETED" for job in persisted)
            and len({job["result"]["input_sha256"] for job in finished}) == 8
        )
        return {
            "jobs": 8,
            "workers": 4,
            "rows_per_job": 500,
            "max_running_workers": maximum,
            "seconds": time.perf_counter() - started,
            "passed": passed,
            "persisted_receipts": len(persisted),
            "model_calls": 0,
            "cost": 0,
            "memory_after": memory(),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--case", type=int)
    parser.add_argument("--mode", choices=["grouped", "conflicts"], default="grouped")
    args = parser.parse_args()
    if args.case:
        print(json.dumps(case(args.case, args.mode), ensure_ascii=False))
        return
    if args.report is None:
        parser.error("--report is required")
    results = []
    for count in (500, 2000, 10000):
        for mode in ("grouped", "conflicts"):
            process = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--case",
                    str(count),
                    "--mode",
                    mode,
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            result = json.loads(process.stdout)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    concurrency = concurrent()
    report = {
        "schema": "aletheia-nexus/offline-input-stress/v1",
        "at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "status": "PASSED"
        if all(r["passed"] for r in results) and concurrency["passed"]
        else "FAILED",
        "cases": results,
        "concurrency": concurrency,
        "model_calls": 0,
        "cost": 0,
        "limitations": [
            "Synthetic bibliography fixtures, not 10000 real papers/PDFs or scientific-quality verification.",
            "Pure local parser scale can exceed the 50000-character normalization API bound; those rows require batches.",
            "No model/provider/network or GUI calls; concurrency workers run local parsing under TaskManager only.",
            "Windows working-set values include interpreter/imports; each size/mode runs in a fresh child process.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.report)
    print(
        json.dumps(
            {
                "report": str(args.report),
                "status": report["status"],
                "concurrency": concurrency,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
