"""Stored defaults share native contract limits and cannot save authorizations."""

from copy import deepcopy

import pytest

from aletheia_nexus.workbench.research_defaults import research_defaults


def test_defaults_preserve_previous_ui_values_and_detach_caller_data():
    defaults = research_defaults()
    assert defaults["model"]["name"] == "deepseek-flash"
    assert defaults["model"]["max_retries"] == 0
    assert defaults["budget"]["max_calls"] == 10
    assert defaults["budget"]["max_cost"] == 2.0
    assert defaults["budget"]["max_supplement_rounds"] == 0
    assert defaults["planning_max_cost"] == 0.5
    supplied = {"model": {"name": "fixture-name"}, "budget": {"max_cost": 0.7}}
    before = deepcopy(supplied)
    checked = research_defaults(supplied)
    checked["model"]["name"] = "changed-return"
    assert supplied == before
    assert research_defaults()["model"]["name"] == "deepseek-flash"


@pytest.mark.parametrize(
    "value",
    [
        {"consent": True},
        {"allow_remote": True},
        {"extra_pages_authorized": True},
        {"model": {"max_retries": 4}},
        {"model": {"timeout_seconds": 0}},
        {"budget": {"max_repair_rounds": 2}},
        {"budget": {"max_supplement_rounds": 4}},
        {"budget": {"max_cost": 0}},
        {"model": {"output_cost_per_million": -1}},
        {"planning_max_cost": True},
        {"planning_max_cost": float("nan")},
        {"planning_max_cost": -1},
        {"budget": []},
    ],
)
def test_invalid_settings_and_authorization_fields_are_rejected(value):
    with pytest.raises(ValueError):
        research_defaults(value)
