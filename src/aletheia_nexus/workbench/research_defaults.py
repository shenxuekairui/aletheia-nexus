"""Validate UI model/budget preferences with the unchanged native task contract."""

from copy import deepcopy
from math import isfinite

from aletheia_nexus.processing.contracts import TASK_SCHEMA, validate_task
from aletheia_nexus.research_planner import DEFAULT_MODEL


def research_defaults(value=None):
    value = {} if value is None else deepcopy(value)
    if not isinstance(value, dict) or value.keys() - {
        "model",
        "budget",
        "planning_max_cost",
    }:
        raise ValueError("科研默认设置只接受模型、执行预算和规划费用上限。")
    if any(not isinstance(value.get(key, {}), dict) for key in ("model", "budget")):
        raise ValueError("科研模型与预算默认设置必须是一组命名参数。")
    planning_cost = value.get("planning_max_cost", 0.5)
    if (
        type(planning_cost) not in (int, float)
        or not isfinite(planning_cost)
        or planning_cost <= 0
    ):
        raise ValueError("自然语言规划费用上限必须为有限的正数。")
    model = {**DEFAULT_MODEL, "min_interval_seconds": 1, **value.get("model", {})}
    budget = {
        "max_calls": 10,
        "max_cost": 2.0,
        "max_input_characters": 100000,
        "max_images": 6,
        "max_output_tokens": 65536,
        "max_repair_rounds": 1,
        "max_supplement_rounds": 0,
        "max_review_rounds": 0,
        **value.get("budget", {}),
    }
    # Schema-only validation: no file is opened, no real task is registered, and
    # no provider is constructed. This reuses native limits instead of forking
    # the contract's pricing, type, model, repair or supplement semantics.
    try:
        checked = validate_task(
            {
                "schema": TASK_SCHEMA,
                "id": "settings_defaults",
                "type": "extract",
                "objective": "仅校验默认参数",
                "documents": [
                    {
                        "id": "settings_document",
                        "artifact": "preference-validation-only",
                    }
                ],
                "fields": [
                    {"id": "data", "description": "仅校验参数", "type": "string"}
                ],
                "model": model,
                "budget": budget,
            }
        )
    except ValueError as exc:
        from .messages import user_message

        raise ValueError("科研默认设置不符合任务契约：" + user_message(exc)) from None
    return {
        "model": checked["model"],
        "budget": checked["budget"],
        "planning_max_cost": planning_cost,
    }
