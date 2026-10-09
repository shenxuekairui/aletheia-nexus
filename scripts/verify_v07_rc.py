"""Run the bounded v0.7 release-candidate checks without duplicating test logic."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(name: str, command: list[str], *, env: dict[str, str] | None = None) -> dict:
    started = time.perf_counter()
    environment = dict(os.environ if env is None else env)
    # An editable install can point at a different checkout. Release checks
    # must import this checkout's src tree even in a reused developer venv.
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "src"), environment.get("PYTHONPATH")) if part
    )
    result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    return {
        "name": name,
        "command": ["<python>", *command[1:]] if command else [],
        "returncode": result.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "passed": result.returncode == 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--browser-smoke", action="store_true")
    parser.add_argument("--ocr-smoke", action="store_true")
    parser.add_argument("--public-oa", action="store_true")
    args = parser.parse_args(argv)

    python = sys.executable
    checks = [
        ("pip-check", [python, "-m", "pip", "check"], None),
        (
            "ruff-format",
            [python, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
            None,
        ),
        (
            "ruff-check",
            [python, "-m", "ruff", "check", "src", "tests", "scripts"],
            None,
        ),
        ("compile", [python, "-m", "compileall", "-q", "src", "scripts"], None),
        ("frozen-acquisition", [python, "scripts/verify_frozen_benchmark.py"], None),
        ("parser-evaluation", [python, "scripts/evaluate_v07_parser.py"], None),
        ("deterministic-suite", [python, "-m", "pytest", "-q"], None),
    ]
    if args.browser_smoke:
        environment = dict(os.environ)
        environment["AN_RUN_BROWSER_SMOKE"] = "1"
        checks.append(
            (
                "real-browser-smoke",
                [
                    python,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/acquire/access/test_browser_integration.py",
                ],
                environment,
            )
        )
    if args.ocr_smoke:
        environment = dict(os.environ)
        environment["AN_RUN_OCR_SMOKE"] = "1"
        checks.append(
            (
                "real-ocr-smoke",
                [python, "-m", "pytest", "-q", "tests/content/test_ocr_integration.py"],
                environment,
            )
        )
    if args.public_oa:
        checks.append(
            (
                "public-oa-qualification",
                [python, "scripts/qualify_v07_public_oa.py"],
                None,
            )
        )

    records = []
    for name, command, environment in checks:
        record = _run(name, command, env=environment)
        records.append(record)
        if not record["passed"]:
            break
    report = {
        "schema": "aletheia-nexus/v07-rc-report/v1",
        "passed": len(records) == len(checks)
        and all(item["passed"] for item in records),
        "checks": records,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
