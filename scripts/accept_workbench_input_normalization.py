"""Bounded input-normalization acceptance. Default: plan only, no HTTP/model.

Use a NEW output directory. Explicit --live requires --budget-cny (<=30) and
--baseline-ledger. Chain the generated budget-ledger.json into a later run;
never reuse an older baseline or run other paid tests outside this ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from aletheia_nexus.core.identifiers.doi import extract_dois, normalize_doi
from aletheia_nexus.processing.contracts import digest
from aletheia_nexus.research_app import _lock_job_owner
from aletheia_nexus.workbench.acquisition_input import parse_text_input
from aletheia_nexus.workbench.input_normalization import (
    InputNormalizationService,
    input_normalization_options,
    validate_input_text,
)
from aletheia_nexus.workbench.jobs import safe_data
from aletheia_nexus.workbench.settings import atomic_json


def now():
    return datetime.now(timezone.utc).isoformat()


def amount(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("预算台账必须使用非负有限金额。")
    return float(value)


def baseline_amount(value):
    """The parent's ledger and this script both expose these non-overlap totals."""
    if not isinstance(value, dict) or any(
        key not in value
        for key in ("previous_estimated_cny", "known_estimate_cny", "reserved_cny")
    ):
        raise ValueError("基线台账需要既有费用、已知估算与未结清预留三个累计字段。")
    return sum(
        amount(value[key])
        for key in ("previous_estimated_cny", "known_estimate_cny", "reserved_cny")
    )


def _bibliography_text(items):
    lines = []
    for index, item in enumerate(items, 1):
        doi = normalize_doi(item.get("doi") or item.get("DOI"))
        title = item.get("title") or ""
        if isinstance(title, list):
            title = title[0] if title else ""
        journal = item.get("journal") or item.get("container-title") or ""
        if isinstance(journal, list):
            journal = journal[0] if journal else ""
        year = item.get("year")
        if year is None:
            date = (item.get("published") or {}).get("date-parts") or [[]]
            year = date[0][0] if date and date[0] else None
        authors = item.get("authors") or item.get("author") or []
        if isinstance(authors, str):
            authors = [authors]
        names = [
            " ".join(str(a.get(k) or "") for k in ("given", "family")).strip()
            if isinstance(a, dict)
            else str(a)
            for a in authors
        ]
        fields = [
            title,
            "作者：" + "; ".join(names) if names else "",
            "年份：" + str(year) if year else "",
            "期刊：" + str(journal) if journal else "",
            "DOI: " + doi,
        ]
        lines.append(f"{index}. " + "；".join(field for field in fields if field))
    return "\n".join(lines)


def load_cases(paths):
    cases = []
    for path in paths:
        path = Path(path).resolve(strict=True)
        source = path.read_text(encoding="utf-8-sig")
        value = json.loads(source) if path.suffix.lower() == ".json" else source
        if isinstance(value, dict) and "cases" in value:
            specifications = value["cases"]
        elif isinstance(value, str):
            specifications = [{"name": path.stem, "text": value}]
        else:
            items = (
                value.get("items", value.get("papers"))
                if isinstance(value, dict)
                else value
            )
            if not isinstance(items, list) or not items:
                raise ValueError("书目夹具需要items/papers数组，或cases中的明确text。")
            specifications = [{"name": path.stem, "text": _bibliography_text(items)}]
        if not isinstance(specifications, list):
            raise ValueError("验收cases必须是数组。")
        for specification in specifications:
            text = validate_input_text(specification["text"])
            assignments = [
                {
                    "doi": e["value"]["doi"],
                    "line": e["line"],
                    "folder": e["value"].get("folder"),
                    "tags": list(e["value"].get("tags") or ()),
                    "assignment": e["assignment"],
                }
                for e in parse_text_input(text)["entries"]
                if e["value"].get("doi")
            ]
            expected = {
                "dois": sorted(set(extract_dois(text))),
                "assignments": assignments,
            }
            expected.update(specification.get("expected") or {})
            expected["dois"] = sorted(set(normalize_doi(d) for d in expected["dois"]))
            if set(expected["dois"]) != set(extract_dois(text)):
                raise ValueError("夹具预期DOI必须与原文显式DOI集合一致。")
            cases.append(
                {
                    "id": f"case-{len(cases) + 1:03}",
                    "name": specification.get("name") or path.stem,
                    "fixture": str(path),
                    "text": text,
                    "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "expected": expected,
                }
            )
    if not cases:
        raise ValueError("请至少提供一个包含文献的夹具。")
    return cases


def check_result(case, result):
    canonical = result.get("canonical") or {}
    papers = canonical.get("papers") or []
    source_map = canonical.get("source_map") or []
    actual_dois = sorted({p["doi"] for p in papers if p.get("doi")})
    expected = case["expected"]
    checked = []
    for wanted in expected.get("assignments", []):
        candidates = [
            p
            for p in papers
            if p.get("doi") == wanted["doi"]
            and any(
                s.get("paper_sha256") == digest(p)
                and wanted["line"] in s.get("source_lines", [])
                for s in source_map
            )
        ]
        matches = []
        for paper in candidates:
            bindings = [
                s
                for s in source_map
                if s.get("paper_sha256") == digest(paper)
                and wanted["line"] in s.get("source_lines", [])
            ]
            for binding in bindings:
                folder_ok = wanted["assignment"]["folder_mode"] == "inherit" or (
                    paper.get("folder") == wanted["folder"]
                    and binding["assignment"]["folder_mode"]
                    == wanted["assignment"]["folder_mode"]
                )
                tags_ok = wanted["assignment"]["tags_mode"] == "inherit" or (
                    set(paper.get("tags") or []) == set(wanted["tags"])
                    and binding["assignment"]["tags_mode"] == "custom"
                )
                matches.append(folder_ok and tags_ok)
        checked.append(
            {"doi": wanted["doi"], "line": wanted["line"], "passed": any(matches)}
        )
    quotes_ok = all(
        " ".join(s.get("quote", "").split()) in " ".join(case["text"].split())
        and s.get("quote")
        for s in source_map
    )
    expected_groups = sorted(
        {
            row.get("folder") or "/"
            for row in expected.get("assignments", [])
            if row["assignment"]["folder_mode"] != "inherit"
        }
    )
    groups = sorted(
        {
            "（继承默认）"
            if source["assignment"]["folder_mode"] == "inherit"
            else "/"
            if source["assignment"]["folder_mode"] == "root"
            else paper["folder"]
            for source in source_map
            for paper in papers
            if source.get("paper_sha256") == digest(paper)
        }
    )
    return {
        "expected_dois": expected["dois"],
        "actual_dois": actual_dois,
        "doi_coverage_equal": actual_dois == expected["dois"],
        "actual_groups": groups,
        "expected_explicit_groups": expected_groups,
        "assignment_checks": checked,
        "explicit_assignments_retained": all(c["passed"] for c in checked),
        "quotes_point_to_input": bool(source_map) and bool(quotes_ok),
        "requires_confirmation": canonical.get("requires_confirmation"),
        "unassigned_source_lines": canonical.get("unassigned_source_lines", []),
        "passed": result.get("status") == "COMPLETED"
        and actual_dois == expected["dois"]
        and all(c["passed"] for c in checked)
        and bool(source_map)
        and bool(quotes_ok),
    }


class AcceptanceBudget:
    """Reserve each whole case before HTTP; unknown billing retains its full cap."""

    def __init__(self, path, baseline_path, limit):
        self.path, self.baseline_path = Path(path), Path(baseline_path)
        self.raw_baseline = self.baseline_path.read_bytes()
        baseline = json.loads(self.raw_baseline)
        self.lock = Lock()
        self.data = {
            "schema": "aletheia-nexus/input-normalization-acceptance-budget/v1",
            "limit_cny": amount(limit),
            "baseline": {
                "path": str(self.baseline_path.resolve()),
                "sha256": hashlib.sha256(self.raw_baseline).hexdigest(),
            },
            "previous_estimated_cny": baseline_amount(baseline),
            "known_estimate_cny": 0,
            "reserved_cny": 0,
            "tests": [],
            "created_at": now(),
        }
        if not 0 < limit <= 30 or self.data["previous_estimated_cny"] > limit:
            raise ValueError("本轮预算必须覆盖既有保守费用且不超过30元。")
        self._save()

    def _save(self):
        self.data["known_estimate_cny"] = sum(
            row.get("known_cost_cny") or 0 for row in self.data["tests"]
        )
        self.data["reserved_cny"] = sum(
            row["reservation_cny"]
            for row in self.data["tests"]
            if row["state"] in {"STARTED", "BILLING_UNCERTAIN", "INTERRUPTED"}
        )
        self.data["conservative_total_cny"] = sum(
            self.data[k]
            for k in ("previous_estimated_cny", "known_estimate_cny", "reserved_cny")
        )
        atomic_json(self.path, safe_data(self.data))

    def reserve(self, case_id, cap):
        with self.lock:
            if self.baseline_path.read_bytes() != self.raw_baseline:
                raise ValueError("基线台账已变动，本轮停止调度新的收费请求。")
            if (
                self.data["conservative_total_cny"] + amount(cap)
                > self.data["limit_cny"]
            ):
                return False
            self.data["tests"].append(
                {
                    "id": case_id,
                    "state": "STARTED",
                    "reservation_cny": amount(cap),
                    "started_at": now(),
                }
            )
            self._save()
            return True

    def settle(self, case_id, result):
        with self.lock:
            row = next(row for row in self.data["tests"] if row["id"] == case_id)
            unknown = bool(result.get("billing_uncertain"))
            known = sum(
                c["estimated_cost"]
                for c in result.get("calls", [])
                if c.get("estimated_cost") is not None
            )
            row.update(
                state="BILLING_UNCERTAIN" if unknown else "COMPLETED",
                known_cost_cny=known,
                receipt=result.get("receipt"),
                result_status=result.get("status"),
                http_attempts=len(result.get("calls", [])),
                billing_uncertain=unknown,
                service_accounted_cost_cny=result.get("accounted_cost"),
                finished_at=now(),
            )
            self._save()

    def interrupt(self, case_id, error_type):
        with self.lock:
            row = next(row for row in self.data["tests"] if row["id"] == case_id)
            row.update(
                state="INTERRUPTED",
                billing_uncertain=True,
                error_type=error_type,
                finished_at=now(),
            )
            self._save()


def run(
    cases,
    output,
    *,
    live=False,
    baseline=None,
    budget_cny=None,
    per_case_budget_cny=3,
    concurrency=1,
    max_output_tokens=8192,
    timeout_seconds=180,
):
    if concurrency not in (1, 2, 3):
        raise ValueError("验收并发数只能为1、2或3。")
    cap = amount(per_case_budget_cny)
    if not cap:
        raise ValueError("每个用例的预算上限必须大于零。")
    options = input_normalization_options(
        {
            "max_cost": cap,
            "max_output_tokens": max_output_tokens,
            "model": {
                "currency": "CNY",
                "input_cost_per_million": 8,
                "cached_input_cost_per_million": 8,
                "output_cost_per_million": 32,
                "timeout_seconds": timeout_seconds,
            },
        }
    )
    if live and (baseline is None or budget_cny is None):
        raise ValueError("真实验收需明确提供既有预算台账与本轮总费用上限。")
    if budget_cny is not None and not 0 < amount(budget_cny) <= 30:
        raise ValueError("真实验收总预算必须为正且不超过30元。")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "aletheia-nexus/input-normalization-acceptance/v1",
        "live": bool(live),
        "options": options,
        "concurrency": concurrency,
        "created_at": now(),
        "budget_limit_cny": budget_cny,
        "cases": [{k: v for k, v in case.items() if k != "text"} for case in cases],
        "results": [],
    }
    atomic_json(output / "acceptance.json", plan)
    if not live:
        plan.update(
            status="PLAN_ONLY",
            http_attempts=0,
            message="仅生成验收计划，未调用模型；真实执行需显式--live和预算台账。",
        )
        atomic_json(output / "acceptance.json", plan)
        return plan
    baseline = Path(baseline).resolve(strict=True)
    owner = _lock_job_owner(
        baseline.with_name(baseline.name + ".normalization-acceptance.lock"),
        create=True,
    )
    if owner is None:
        raise ValueError("另一验收进程正在使用此预算基线，请等待后使用其新台账继续。")
    try:
        ledger = AcceptanceBudget(
            output / "budget-ledger.json", baseline, amount(budget_cny)
        )
        normalizer = InputNormalizationService(output / "model-state")

        def execute(case):
            if not ledger.reserve(case["id"], cap):
                return {
                    "id": case["id"],
                    "status": "NOT_RUN",
                    "reason": "总预算不足以预留本次最大费用；未发起请求。",
                    "http_attempts": 0,
                }
            started = time.monotonic()
            try:
                result = normalizer.normalize(
                    case["text"], options=options, consent=True
                )
            except BaseException as exc:
                ledger.interrupt(case["id"], type(exc).__name__)
                raise
            ledger.settle(case["id"], result)
            return {
                "id": case["id"],
                "name": case["name"],
                "status": result["status"],
                "receipt": result["receipt"],
                "latency_seconds": round(time.monotonic() - started, 3),
                "usage": result["usage"],
                "calls": result["calls"],
                "billing_uncertain": result["billing_uncertain"],
                "accounted_cost_cny": result["accounted_cost"],
                "checks": check_result(case, result),
                "warnings": result["warnings"],
                "diagnostics": result["diagnostics"],
            }

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(execute, case) for case in cases]
            for future in as_completed(futures):
                plan["results"].append(future.result())
                atomic_json(output / "acceptance.json", safe_data(plan))
        plan.update(
            status="PASSED"
            if all(row.get("checks", {}).get("passed") for row in plan["results"])
            else "PARTIAL",
            finished_at=now(),
            budget_ledger=str(ledger.path),
            budget=ledger.data,
            baseline_unchanged=baseline.read_bytes() == ledger.raw_baseline,
            note="金额按8/32元每百万Token保守配置估算，不是服务商账单；未知计费保留整次预算预留。",
        )
        atomic_json(output / "acceptance.json", safe_data(plan))
        return plan
    finally:
        owner.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        action="append",
        required=True,
        help="TXT原文或包含cases/items/papers的JSON；可重复",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="尚不存在的新验收目录"
    )
    parser.add_argument(
        "--live", action="store_true", help="明确允许真实模型请求，默认关闭"
    )
    parser.add_argument(
        "--baseline-ledger",
        type=Path,
        help="既有预算台账，仅只读；下一次请接本轮新台账",
    )
    parser.add_argument(
        "--budget-cny", type=float, help="含既有费用与未结预留的总上限，最多30元"
    )
    parser.add_argument("--per-case-budget-cny", type=float, default=3)
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="单次模型请求超时，大批次默认180秒",
    )
    args = parser.parse_args(argv)
    try:
        result = run(
            load_cases(args.fixture),
            args.output,
            live=args.live,
            baseline=args.baseline_ledger,
            budget_cny=args.budget_cny,
            per_case_budget_cny=args.per_case_budget_cny,
            concurrency=args.concurrency,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout_seconds,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": result["status"],
                "live": args.live,
                "output": str(args.output),
                "case_count": len(result["cases"]),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] in {"PASSED", "PLAN_ONLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
