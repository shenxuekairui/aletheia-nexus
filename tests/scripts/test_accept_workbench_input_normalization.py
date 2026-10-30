"""Acceptance accounting must not accidentally authorize real model work."""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[2] / "scripts" / "accept_workbench_input_normalization.py"
)
spec = importlib.util.spec_from_file_location("accept_normalization", SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def baseline(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "schema": "workbench-acceptance-budget/v1",
                "previous_estimated_cny": 0.626434,
                "known_estimate_cny": 0.025104,
                "reserved_cny": 0,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_default_is_plan_only_and_preserves_original_fixture(tmp_path, monkeypatch):
    fixture = tmp_path / "input.txt"
    fixture.write_text(
        "[甲]\n1. 10.9999/synthetic-a\n2. 10.9999/synthetic-b | 分类=/ | 标签=[]",
        encoding="utf-8",
    )
    original = fixture.read_bytes()
    monkeypatch.setattr(
        acceptance,
        "InputNormalizationService",
        lambda *a, **k: pytest.fail("plan must not instantiate model service"),
    )
    cases = acceptance.load_cases([fixture])
    result = acceptance.run(cases, tmp_path / "plan")
    assert result["status"] == "PLAN_ONLY" and result["http_attempts"] == 0
    assert result["options"]["model"]["input_cost_per_million"] == 8
    assert result["options"]["model"]["output_cost_per_million"] == 32
    assert (
        result["cases"][0]["expected"]["assignments"][1]["assignment"]["folder_mode"]
        == "root"
    )
    assert fixture.read_bytes() == original


def test_three_reservations_cannot_overcommit_remaining_global_budget(tmp_path):
    source = baseline(tmp_path)
    original = source.read_bytes()
    budget = acceptance.AcceptanceBudget(tmp_path / "ledger.json", source, 30)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda n: budget.reserve(str(n), 10), range(3)))
    assert sum(results) == 2
    assert budget.data["reserved_cny"] == 20
    assert budget.data["conservative_total_cny"] == pytest.approx(20.651538)
    assert source.read_bytes() == original


def test_unknown_billing_retains_full_cap_and_next_ledger_can_chain(tmp_path):
    source = baseline(tmp_path)
    budget = acceptance.AcceptanceBudget(tmp_path / "ledger.json", source, 30)
    assert budget.reserve("one", 3)
    budget.settle(
        "one",
        {
            "status": "FAILED",
            "billing_uncertain": True,
            "calls": [{"estimated_cost": None}],
            "accounted_cost": 0.4,
        },
    )
    assert budget.data["reserved_cny"] == 3
    assert acceptance.baseline_amount(budget.data) == pytest.approx(3.651538)
    following = acceptance.AcceptanceBudget(tmp_path / "next.json", budget.path, 30)
    assert following.data["previous_estimated_cny"] == pytest.approx(3.651538)


def test_known_usage_settles_cap_and_changed_baseline_blocks_new_work(tmp_path):
    source = baseline(tmp_path)
    budget = acceptance.AcceptanceBudget(tmp_path / "ledger.json", source, 30)
    budget.reserve("one", 3)
    budget.settle(
        "one",
        {
            "status": "FAILED",
            "billing_uncertain": False,
            "calls": [{"estimated_cost": 0.05}],
            "accounted_cost": 0.05,
        },
    )
    assert budget.data["reserved_cny"] == 0
    assert (
        budget.data["known_estimate_cny"] == 0.05
    )  # Invalid candidates still cost money.
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="已变动"):
        budget.reserve("two", 3)


def test_real_crossref_fixture_can_be_planned_without_metadata_network(tmp_path):
    fixture = tmp_path / "metadata.json"
    fixture.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "DOI": "10.9999/synthetic-a",
                        "title": ["CO₂ on Cu(I)"],
                        "author": [{"given": "Jane", "family": "Smith"}],
                        "published": {"date-parts": [[2026]]},
                        "container-title": ["Fixture Journal"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    case = acceptance.load_cases([fixture])[0]
    assert "CO₂ on Cu(I)" in case["text"] and "Jane Smith" in case["text"]
    assert case["expected"]["dois"] == ["10.9999/synthetic-a"]
    for limit in [31, float("nan"), -1]:
        with pytest.raises(ValueError):
            acceptance.run(
                [case],
                tmp_path / "invalid",
                live=True,
                baseline=fixture,
                budget_cny=limit,
            )
