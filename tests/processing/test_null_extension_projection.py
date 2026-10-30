"""Reversible empty metadata projection, with no scientific value repair."""

import json
from copy import deepcopy

import httpx
import pytest

from aletheia_nexus.processing import contracts, provider


def test_nested_unknown_null_trace_is_reversible_and_known_null_stays():
    module = provider
    schema = contracts.obj(
        {
            "items": contracts.array(
                contracts.obj(
                    {
                        "literal": contracts.TEXT,
                        "optional": {"type": ["string", "null"]},
                        "count": {"type": "number"},
                        "enabled": {"type": "boolean"},
                    }
                )
            )
        }
    )
    raw = {
        "items": [
            {
                "literal": "合成 x² / H₂O / µM / 10−4",
                "optional": None,
                "count": 0,
                "enabled": False,
                "empty_model_extension": None,
            }
        ],
        "another_empty_extension": None,
    }
    original = deepcopy(raw)
    result = module.project_response(raw, schema)
    assert isinstance(result, provider.ProjectedResponse)
    assert raw == original
    assert (
        result["items"][0]["optional"] is None
        and result["items"][0]["count"] == 0
        and result["items"][0]["enabled"] is False
    )
    assert result["items"][0]["literal"] == original["items"][0]["literal"]
    assert result.metadata["raw_text"] == json.dumps(
        original, ensure_ascii=False, allow_nan=False
    )
    restored = deepcopy(dict(result))
    for change in reversed(result.metadata["changes"]):
        assert (
            change["reason"] == "null_unknown_property_extension"
            and change["value"] is None
        )
        value = restored
        for key in change["path"][:-1]:
            value = value[key]
        value[change["path"][-1]] = change["value"]
    assert restored == original


@pytest.mark.parametrize(
    "value", [False, 0, "", "unrequested scientific text", {}, [1]]
)
def test_nonnull_unknown_is_still_rejected(value):
    module = provider
    schema = contracts.obj({"literal": contracts.TEXT})
    with pytest.raises(ValueError, match="unknown keys"):
        module.project_response({"literal": "preserved", "extension": value}, schema)


def test_open_object_null_and_missing_required_science_not_silently_fixed():
    module = provider
    open_schema = {
        "type": "object",
        "properties": {"known": contracts.TEXT},
        "required": ["known"],
    }
    # AN's current validator supports only closed objects even when this marker
    # is omitted. The projection must not silently remove the open-schema null.
    open_raw = {"known": "same", "optional_extra": None}
    with pytest.raises(ValueError, match="unknown keys"):
        module.project_response(open_raw, open_schema)
    assert open_raw == {"known": "same", "optional_extra": None}
    with pytest.raises(ValueError, match="missing"):
        module.project_response(
            {"extension": None},
            contracts.obj({"mandatory_scientific_value": contracts.TEXT}),
        )
    assert (
        module.project_response(
            {"known": "same", "old_empty_array": []},
            contracts.obj({"known": contracts.TEXT}),
        ).metadata["changes"][0]["reason"]
        == "empty_unknown_array_extension"
    )


def test_native_mock_retains_raw_projection_metadata_without_scientific_rewrite(
    monkeypatch,
):
    module = provider
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-mock-only")
    schema = contracts.obj(
        {
            "items": contracts.array(
                contracts.obj(
                    {"value": contracts.TEXT, "unit": {"type": ["string", "null"]}}
                )
            )
        }
    )
    raw = {
        "items": [
            {"value": "虚构值 1 µM", "unit": None, "synthetic_null_extension": None}
        ]
    }

    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 5, "output_tokens": 3},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(raw, ensure_ascii=False),
                            }
                        ],
                    }
                ],
            },
        )

    delegate = module.DeepSeekProvider(
        {"name": "deepseek-flash", "max_retries": 0, "min_interval_seconds": 0},
        enabled=True,
        transport=httpx.MockTransport(handler),
    )
    budget = provider.CallBudget(1)
    answer = delegate.generate({"phase": "synthetic_probe"}, schema, [], budget, 65536)
    assert isinstance(answer, provider.ProjectedResponse)
    assert json.loads(answer.metadata["raw_text"]) == raw
    assert answer == {"items": [{"value": "虚构值 1 µM", "unit": None}]}
    assert len(budget.calls) == 1 and budget.calls[0]["status"] == "completed"
