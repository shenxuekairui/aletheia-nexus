"""Research scoring tests use illustrative annotations, not model performance data."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest

from aletheia_nexus.processing.contracts import digest

ROOT = Path(__file__).resolve().parents[2]
score = runpy.run_path(str(ROOT / "scripts/score_v08_review.py"))["score"]
ledger_lock = runpy.run_path(str(ROOT / "scripts/run_v08_evaluation.py"))["ledger_lock"]
costs = runpy.run_path(str(ROOT / "scripts/run_v08_evaluation.py"))["costs"]
record_provider_bill = runpy.run_path(str(ROOT / "scripts/run_v08_evaluation.py"))[
    "record_provider_bill"
]


def test_cumulative_cost_settles_known_usage_and_keeps_unknown_reservation(tmp_path):
    manifest = {
        "schema": "aletheia-nexus/research-run/v1",
        "calls": [
            {
                "currency": "CNY",
                "estimated_cost": 0.1,
                "reserved_cost": 1,
                "usage": {"input_tokens": 1},
            },
            {
                "currency": "CNY",
                "estimated_cost": None,
                "reserved_cost": 2,
                "usage": None,
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = costs(tmp_path)
    assert report["conservative_spend"] == 2.1
    assert report["historical_reservations"] == 3
    assert report["unknown_usage_calls"] == 1
    manifest["calls"][1]["reserved_cost"] = None
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="unpriced"):
        costs(tmp_path)


def test_provider_bill_replaces_covered_estimates_and_counts_only_new_calls(tmp_path):
    path = tmp_path / "manifest.json"
    manifest = {
        "schema": "aletheia-nexus/research-run/v1",
        "calls": [
            {"currency": "CNY", "estimated_cost": 90, "reserved_cost": 100},
            {"currency": "CNY", "estimated_cost": None, "reserved_cost": 5},
        ],
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    original = path.read_bytes()
    first = record_provider_bill(tmp_path, 40.45, "User bill covers these prior calls")
    report = costs(tmp_path)
    assert path.read_bytes() == original
    assert report["conservative_spend"] == 40.45
    assert report["unreconciled_conservative_spend"] == 95
    assert report["unknown_usage_calls"] == 2
    assert report["subsequent_attempts"] == 0

    # A new call in an existing run and a new run both count after the checkpoint.
    manifest["calls"].append({"currency": "CNY", "estimated_cost": 0.2})
    path.write_text(json.dumps(manifest), encoding="utf-8")
    new_run = tmp_path / "new-run"
    new_run.mkdir()
    (new_run / "manifest.json").write_text(
        json.dumps(
            {
                "schema": manifest["schema"],
                "calls": [{"currency": "CNY", "reserved_cost": 1.5}],
            }
        ),
        encoding="utf-8",
    )
    report = costs(tmp_path)
    assert report["conservative_spend"] == pytest.approx(42.15)
    assert report["subsequent_attempts"] == 2
    assert report["subsequent_estimated_cny"] == pytest.approx(1.7)
    # The next bill replaces the cumulative basis; both checkpoints remain.
    second = record_provider_bill(tmp_path, 41, "Later bill covers all four calls")
    assert first.exists() and second.exists() and first != second
    assert costs(tmp_path)["conservative_spend"] == 41


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_provider_bill_does_not_hide_changed_covered_history(tmp_path, change):
    path = tmp_path / "manifest.json"
    manifest = {
        "schema": "aletheia-nexus/research-run/v1",
        "calls": [{"currency": "CNY", "estimated_cost": 1}],
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    record_provider_bill(tmp_path, 0.5, "Bill covers this call")
    if change == "edit":
        manifest["calls"][0]["estimated_cost"] = 2
        path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        path.unlink()
    with pytest.raises(ValueError, match="billed call history changed"):
        costs(tmp_path)


def test_provider_bill_does_not_excuse_unpriced_future_call(tmp_path):
    record_provider_bill(tmp_path, 40.45, "Bill before a new unpriced request")
    (tmp_path / "connection-smoke.json").write_text(
        json.dumps({"calls": [{"currency": "CNY", "usage": None}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unpriced"):
        costs(tmp_path)


def examples():
    plan = {
        "schema": "aletheia-nexus/evaluation-plan/v1",
        "split": "development",
        "reference_authority": "assistant",
        "frozen_at": "2026-10-25",
        "cases": [
            {"id": k, "record_id": "r1", "kind": "field", "expected_present": True}
            for k in ["temperature", "time", "ratio"]
        ],
    }
    review = {
        "plan_sha256": digest(plan),
        "reviewer": "fixture",
        "reviewer_kind": "assistant",
        "run_ids": ["fixture-only"],
        "judgments": [
            {
                "id": k,
                "present": k != "time",
                "correct": k == "temperature",
                "association_error": k == "ratio",
                "citation_resolvable": True,
                "evidence_support": "supported"
                if k == "temperature"
                else "unsupported"
                if k == "ratio"
                else "not_applicable",
                "rationale": "Self-authored illustrative scoring case.",
            }
            for k in ["temperature", "time", "ratio"]
        ],
    }
    return plan, review


def test_scoring_keeps_precision_recall_and_record_denominators():
    plan, review = examples()
    report = score(plan, review)
    assert report["field_precision"]["value"] == 1 / 2
    assert report["field_recall"]["value"] == 1 / 3
    assert report["complete_record_accuracy"]["value"] == 0
    assert report["citation_resolvability"]["value"] == 1
    assert report["evidence_support"]["value"] == 1 / 2
    assert report["condition_association_errors"] == report["omitted_fields"] == 1
    assert not report["human_holdout_review"]


def test_scoring_rejects_cherry_picking_and_mutated_plan():
    plan, review = examples()
    missing = deepcopy(review)
    missing["judgments"].pop()
    with pytest.raises(ValueError, match="every frozen case"):
        score(plan, missing)
    plan["cases"].pop()
    with pytest.raises(ValueError, match="exact frozen plan"):
        score(plan, review)


def test_cost_ledger_lock_excludes_parallel_spend_and_releases(tmp_path):
    with ledger_lock(tmp_path):
        with pytest.raises(ValueError, match="another evaluation"):
            with ledger_lock(tmp_path):
                pytest.fail("must not enter twice")
    with ledger_lock(tmp_path):
        pass


def test_all_outputs_audit_catches_extra_claims_without_changing_frozen_cases():
    plan, review = examples()
    plan["output_audit_policy"] = "all_emitted"
    review["plan_sha256"] = digest(plan)
    inventory = {
        "runs": [{"run_id": "fixture-only"}],
        "outputs": [
            {"id": k, "kind": k, "pointer": "/fixture/" + k, "requires_evidence": True}
            for k in ("field", "step", "claim")
        ],
    }
    review["output_inventory_sha256"] = digest(inventory)
    review["output_judgments"] = [
        {
            "id": k,
            "correct": k != "claim",
            "association_error": False,
            "citation_resolvable": True,
            "evidence_support": "unsupported" if k == "claim" else "supported",
            "rationale": "Illustrative source review, not actual science results.",
        }
        for k in ("field", "step", "claim")
    ]
    report = score(plan, review, inventory=inventory)
    assert report["field_precision"]["value"] == 1 / 2
    audit = report["output_audit"]
    assert audit["evidence_support"]["value"] == 2 / 3
    assert audit["errors"][0]["id"] == "claim"
    assert audit["counts_by_kind"] == {"field": 1, "step": 1, "claim": 1}
    missing = deepcopy(review)
    missing["output_judgments"].pop()
    with pytest.raises(ValueError, match="every emitted"):
        score(plan, missing, inventory=inventory)
    changed = deepcopy(inventory)
    changed["outputs"][0]["pointer"] = "/changed"
    with pytest.raises(ValueError, match="exact actual-output"):
        score(plan, review, inventory=changed)
    with pytest.raises(ValueError, match="exact actual-output"):
        score(plan, review)
    review["draft"] = True
    with pytest.raises(ValueError, match="draft"):
        score(plan, review, inventory=inventory)


def test_human_holdout_requires_all_emitted_policy():
    plan, review = examples()
    plan.update(split="holdout", reference_authority="human")
    review.update(plan_sha256=digest(plan), reviewer_kind="human")
    with pytest.raises(ValueError, match="human holdout requires"):
        score(plan, review)


def test_predeclared_step_error_prevents_complete_record_credit():
    plan, review = examples()
    plan["cases"] = [
        plan["cases"][0],
        {"id": "order", "kind": "step", "record_id": "r1", "expected_present": True},
    ]
    review["judgments"] = [
        review["judgments"][0],
        {
            "id": "order",
            "present": True,
            "correct": False,
            "association_error": True,
            "citation_resolvable": True,
            "evidence_support": "unsupported",
            "rationale": "Fixture: operation ordered incorrectly.",
        },
    ]
    review["plan_sha256"] = digest(plan)
    result = score(plan, review)
    assert result["field_precision"]["value"] == 1
    assert result["complete_record_accuracy"]["value"] == 0
