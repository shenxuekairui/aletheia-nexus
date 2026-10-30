"""Score explicit source-reviewed annotations against a frozen evaluation plan.

This never asks a model to grade itself. Private references/annotations stay outside
Git. Missing annotations fail closed; assistant reviews cannot satisfy human gates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.processing.contracts import digest
from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing.results import verify_result


def output_inventory(run_directories: list[Path]) -> dict:
    """Bind review coverage to every saved field, step and claim, including absences."""
    runs, results, outputs = [], [], []
    seen_runs = set()
    for directory in sorted(run_directories, key=lambda p: str(p.resolve())):
        directory = directory.resolve()
        manifest = json.loads((directory / "manifest.json").read_text("utf-8-sig"))
        if (
            manifest.get("schema") != "aletheia-nexus/research-run/v1"
            or not manifest.get("run_id")
            or manifest["run_id"] in seen_runs
            or manifest.get("status")
            not in {"COMPLETED", "PARTIAL", "FAILED", "PREPARED", "INTERRUPTED"}
        ):
            raise ValueError("unique stopped research runs required")
        run_id = manifest["run_id"]
        seen_runs.add(run_id)
        runs.append(
            {
                "run_id": run_id,
                "manifest_sha256": digest(manifest),
                "items": [
                    {k: row.get(k) for k in ("id", "status", "error", "result_id")}
                    for row in manifest["items"]
                ],
            }
        )
        rows = [*manifest["items"], manifest.get("comparison", {})]
        for row in rows:
            if not row.get("result"):
                continue
            path = (directory / row["result"]).resolve()
            if not path.is_relative_to(directory):
                raise ValueError("result must be inside its run directory")
            result = json.loads(path.read_text("utf-8-sig"))
            verify_result(result)
            for document in result["package"]["documents"]:
                pdf = document.get("locators", {}).get("pdf")
                if (
                    not pdf
                    or sha256_file(Path(pdf)) != document["source"]["pdf_sha256"]
                ):
                    raise ValueError("original PDF missing or changed before review")
            if (
                row.get("result_id", result["artifact_id"]) != result["artifact_id"]
                or digest(result["task"]) != manifest["task_fingerprint"]
                or result["provider"] != manifest["provider"]
            ):
                raise ValueError("result does not match its run manifest")
            results.append(
                {
                    "run_id": run_id,
                    "result_id": result["artifact_id"],
                    "path": str(path),
                    "sources": [
                        {
                            "id": d["id"],
                            "identity": d["source"],
                            "locators": d.get("locators", {}),
                        }
                        for d in result["package"]["documents"]
                    ],
                }
            )

            def add(
                kind: str, pointer: str, value: dict, requires_evidence: bool
            ) -> None:
                identity = {
                    "run_id": run_id,
                    "result_id": result["artifact_id"],
                    "pointer": pointer,
                }
                outputs.append(
                    {
                        "id": digest(identity),
                        **identity,
                        "kind": kind,
                        "requires_evidence": requires_evidence,
                        "output": value,
                    }
                )

            for index, record in enumerate(result["response"].get("records", [])):
                for fid, value in record["fields"].items():
                    add(
                        "field",
                        f"/records/{index}/fields/{fid}",
                        value,
                        value["value"] is not None,
                    )
                for step_index, step in enumerate(record["steps"]):
                    add("step", f"/records/{index}/steps/{step_index}", step, True)
            for index, claim in enumerate(result["response"]["claims"]):
                add("claim", f"/claims/{index}", claim, True)
    if not runs or len({o["id"] for o in outputs}) != len(outputs):
        raise ValueError("nonempty runs and unique output identities required")
    return {
        "schema": "aletheia-nexus/output-review-inventory/v1",
        "runs": runs,
        "results": results,
        "outputs": outputs,
    }


def score_outputs(plan: dict, review: dict, inventory: dict | None) -> dict | None:
    policy = plan.get("output_audit_policy")
    if policy not in {None, "all_emitted"}:
        raise ValueError("unsupported output audit policy")
    if (
        plan["split"] == "holdout"
        and plan["reference_authority"] == "human"
        and policy != "all_emitted"
    ):
        raise ValueError(
            "human holdout requires a frozen all_emitted output audit policy"
        )
    if policy is None:
        if inventory is not None or review.get("output_judgments"):
            raise ValueError("freeze the output audit policy before reviewing outputs")
        return None
    if inventory is None or review.get("output_inventory_sha256") != digest(inventory):
        raise ValueError("review must identify the exact actual-output inventory")
    if set(review["run_ids"]) != {r["run_id"] for r in inventory["runs"]}:
        raise ValueError("output audit must cover every declared run")
    outputs = {item["id"]: item for item in inventory["outputs"]}
    judgments = review.get("output_judgments", [])
    judged = {item["id"]: item for item in judgments}
    if len(judged) != len(judgments) or outputs.keys() != judged.keys():
        raise ValueError("every emitted field, step and claim must be reviewed")
    total = correct = supported = resolvable = association_errors = 0
    errors = []
    for oid, output in outputs.items():
        item = judged[oid]
        if (
            any(type(item.get(k)) is not bool for k in ("correct", "association_error"))
            or not isinstance(item.get("rationale"), str)
            or not item["rationale"].strip()
            or item["association_error"]
            and item["correct"]
        ):
            raise ValueError(
                "explicit output correctness and association review required"
            )
        if output["requires_evidence"]:
            if type(item.get("citation_resolvable")) is not bool or item.get(
                "evidence_support"
            ) not in {"supported", "unsupported", "uncertain"}:
                raise ValueError(
                    "every output assertion requires citation/support review"
                )
            total += 1
            correct += item["correct"]
            supported += item["evidence_support"] == "supported"
            resolvable += item["citation_resolvable"]
        elif (
            item.get("evidence_support") != "not_applicable"
            or item.get("citation_resolvable") is not None
        ):
            raise ValueError(
                "absence decisions are reviewed separately from asserted values"
            )
        association_errors += item["association_error"]
        if not item["correct"] or item.get("evidence_support") in {
            "unsupported",
            "uncertain",
        }:
            errors.append(
                {
                    "id": oid,
                    "kind": output["kind"],
                    "pointer": output["pointer"],
                    **item,
                }
            )
    return {
        "policy": policy,
        "inventory_sha256": digest(inventory),
        "reviewed_outputs": len(outputs),
        "counts_by_kind": {
            k: sum(o["kind"] == k for o in outputs.values())
            for k in ("field", "step", "claim")
        },
        "assertion_accuracy": ratio(correct, total),
        "citation_resolvability": ratio(resolvable, total),
        "evidence_support": ratio(supported, total),
        "all_output_decision_accuracy": ratio(
            sum(j["correct"] for j in judgments), len(judgments)
        ),
        "condition_association_errors": association_errors,
        "errors": errors,
    }


def ratio(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def score(plan: dict, review: dict, *, inventory: dict | None = None) -> dict:
    if plan.get("schema") != "aletheia-nexus/evaluation-plan/v1":
        raise ValueError("unsupported plan")
    if review.get("plan_sha256") != digest(plan):
        raise ValueError("review must identify the exact frozen plan")
    if review.get("draft") or plan.get("draft"):
        raise ValueError("draft references or reviews cannot be scored")
    if (
        plan.get("split") not in {"development", "holdout"}
        or plan.get("reference_authority") not in {"human", "assistant"}
        or not plan.get("frozen_at")
        or not review.get("reviewer")
        or review.get("reviewer_kind") not in {"human", "assistant"}
        or not review.get("run_ids")
    ):
        raise ValueError(
            "explicit split, reference authority, freeze, reviewer and runs required"
        )
    cases = {c["id"]: c for c in plan["cases"]}
    judged = {c["id"]: c for c in review["judgments"]}
    if (
        not cases
        or len(cases) != len(plan["cases"])
        or len(judged) != len(review["judgments"])
    ):
        raise ValueError("nonempty unique case IDs required")
    if cases.keys() != judged.keys():
        raise ValueError(
            "every frozen case must be judged, including failures and omissions"
        )
    output_audit = score_outputs(plan, review, inventory)
    records = {}
    field_present = correct_present = expected = omitted = field_correct = 0
    supported = resolvable = evidence_total = association_errors = 0
    uncertainty_correct = uncertainty_total = introduced = repaired = 0
    errors = []
    for cid, case in cases.items():
        item = judged[cid]
        if (
            case.get("kind") not in {"field", "step", "claim"}
            or type(case.get("expected_present")) is not bool
            or any(
                type(item.get(k)) is not bool
                for k in ("present", "correct", "association_error")
            )
            or item.get("evidence_support")
            not in {"supported", "unsupported", "uncertain", "not_applicable"}
            or not item.get("rationale")
        ):
            raise ValueError("invalid case or judgment")
        if item["present"]:
            if (
                type(item.get("citation_resolvable")) is not bool
                or item["evidence_support"] == "not_applicable"
            ):
                raise ValueError("every output needs citation and support judgments")
            evidence_total += 1
            supported += item["evidence_support"] == "supported"
            resolvable += item["citation_resolvable"]
        if item["correct"] and case["expected_present"] != item["present"]:
            raise ValueError(
                "a missing expected value or invented absent value cannot be correct"
            )
        if item["association_error"]:
            if item["correct"]:
                raise ValueError(
                    "a condition associated with the wrong stage cannot be correct"
                )
            association_errors += 1
        if case.get("check_uncertainty"):
            if type(item.get("uncertainty_correct")) is not bool:
                raise ValueError("uncertainty judgment required")
            uncertainty_total += 1
            uncertainty_correct += item["uncertainty_correct"]
        if case["kind"] == "field":
            field_present += item["present"]
            correct_present += item["present"] and item["correct"]
            expected += case["expected_present"]
            omitted += case["expected_present"] and not item["present"]
            field_correct += item["correct"]
        if case["kind"] in {"field", "step"}:
            records.setdefault(case["record_id"], []).append(item["correct"])
        if "baseline_correct" in case:
            if type(case["baseline_correct"]) is not bool:
                raise ValueError("baseline judgment must be explicit")
            introduced += case["baseline_correct"] and not item["correct"]
            repaired += not case["baseline_correct"] and item["correct"]
        if not item["correct"] or item["evidence_support"] in {
            "unsupported",
            "uncertain",
        }:
            errors.append(
                {
                    "id": cid,
                    "rationale": item["rationale"],
                    "association_error": item["association_error"],
                    "evidence_support": item["evidence_support"],
                }
            )
    return {
        "schema": "aletheia-nexus/scientific-review-score/v1",
        "plan_sha256": digest(plan),
        "split": plan["split"],
        "reference_authority": plan["reference_authority"],
        "reviewer_kind": review["reviewer_kind"],
        "reviewer": review["reviewer"],
        "run_ids": review["run_ids"],
        "human_holdout_review": plan["split"] == "holdout"
        and plan["reference_authority"] == review["reviewer_kind"] == "human",
        "output_audit": output_audit,
        "field_precision": ratio(correct_present, field_present),
        "field_recall": ratio(correct_present, expected),
        "field_correct_including_absence": ratio(
            field_correct, sum(c["kind"] == "field" for c in cases.values())
        ),
        "complete_record_accuracy": ratio(
            sum(all(v) for v in records.values()), len(records)
        ),
        "complete_record_scope": "predeclared_field_and_step_checks",
        "citation_resolvability": ratio(resolvable, evidence_total),
        "evidence_support": ratio(supported, evidence_total),
        "uncertainty_handling": ratio(uncertainty_correct, uncertainty_total),
        "omitted_fields": omitted,
        "condition_association_errors": association_errors,
        "new_errors_vs_baseline": introduced
        if any("baseline_correct" in c for c in cases.values())
        else None,
        "fixed_errors_vs_baseline": repaired
        if any("baseline_correct" in c for c in cases.values())
        else None,
        "baseline_comparisons": sum("baseline_correct" in c for c in cases.values()),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("review", type=Path, nargs="?")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-dir", type=Path, action="append", default=[])
    parser.add_argument("--prepare-output-review", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text("utf-8-sig"))
    inventory = output_inventory(args.run_dir) if args.run_dir else None
    if args.prepare_output_review:
        if inventory is None or plan.get("output_audit_policy") != "all_emitted":
            parser.error(
                "preparation requires --run-dir and a plan with all_emitted policy"
            )
        if args.review:
            parser.error(
                "preparation creates a new draft; do not pass an existing review"
            )
        judgment = {
            "correct": None,
            "association_error": None,
            "citation_resolvable": None,
            "evidence_support": None,
            "rationale": "",
        }
        write_json(
            args.output,
            {
                "draft": True,
                "plan_sha256": digest(plan),
                "reviewer": "",
                "reviewer_kind": "pending_review",
                "review_duration_seconds": None,
                "run_ids": [r["run_id"] for r in inventory["runs"]],
                "judgments": [
                    {
                        "id": c["id"],
                        "present": None,
                        **judgment,
                        **(
                            {"uncertainty_correct": None}
                            if c.get("check_uncertainty")
                            else {}
                        ),
                    }
                    for c in plan["cases"]
                ],
                "output_inventory_sha256": digest(inventory),
                "output_inventory": inventory,
                "output_judgments": [
                    {"id": o["id"], **judgment} for o in inventory["outputs"]
                ],
            },
        )
        print(f"Prepared unscored review draft: {args.output.resolve()}")
        return 0
    if args.review is None:
        parser.error("review required for scoring")
    report = score(
        plan,
        json.loads(args.review.read_text("utf-8-sig")),
        inventory=inventory,
    )
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
