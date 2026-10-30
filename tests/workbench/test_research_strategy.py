"""Ordinary UI choices reuse the native task engine; every model call is mocked."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_research import research as research_fixture

from aletheia_nexus.processing.provider import DeepSeekProvider, ProcessingError
from aletheia_nexus.processing.source_first import INVENTORY_PHASE


@pytest.fixture(name="research")
def strategy_research(tmp_path):
    yield from research_fixture.__wrapped__(tmp_path)


def test_configure_strategy_saves_new_fingerprint_without_changing_old_plan_or_budget(
    research,
):
    original = research.local_plan(
        "仅核对自制夹具", ["p1"], budget={"max_calls": 1, "max_cost": 0.2}
    )
    before = deepcopy(original)
    prior = research.validate_plan(original)
    configured = research.configure_plan(
        original, {"extraction_strategy": "source_first"}
    )
    assert original == before
    assert configured["task"]["extraction_strategy"] == "source_first"
    assert configured["task"]["budget"] == original["budget"]
    assert configured["task_fingerprint"] != prior["task_fingerprint"]
    assert (
        json.loads(Path(configured["task_file"]).read_text("utf-8"))
        == configured["task"]
    )


@pytest.mark.parametrize("strategy", ["field_independent", "unknown", False])
def test_configured_strategy_rejects_retired_and_unknown_values(research, strategy):
    original = research.local_plan("仅核对自制夹具", ["p1"])
    before = deepcopy(original)
    with pytest.raises((ProcessingError, ValueError)):
        research.configure_plan(original, {"extraction_strategy": strategy})
    assert original == before


def test_workbench_source_first_runs_two_native_mock_stages_then_reuses_cache(
    research, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "self-authored-fixture-no-network")
    task = research.local_plan(
        "提取自制夹具测量条件",
        ["p1"],
        mode="parsed",
        budget={
            "max_calls": 2,
            "max_cost": 2,
            "max_output_tokens": 2048,
            "max_repair_rounds": 0,
        },
    )
    task["include_steps"], task["include_claims"] = False, False
    task = research.configure_plan(task, {"extraction_strategy": "source_first"})[
        "task"
    ]
    captured = []

    def handler(request):
        payload = json.loads(request.content)
        native = json.loads(payload["input"][0]["content"][0]["text"])
        captured.append(native)
        source = native["material"]["documents"][0]
        block = next(b for b in source["blocks"] if "sample" in b["text"])
        if native["phase"] == INVENTORY_PHASE:
            answer = {
                "items": [
                    {
                        "observation": block["text"],
                        "subject_stage": "synthetic measurement",
                        "evidence_type": "experimental",
                        "page": block["page"],
                        "quote": block["text"],
                        "field_ids": ["finding"],
                        "source_id": source["id"],
                    }
                ]
            }
        else:
            answer = {
                "records": [
                    {
                        "id": "fixture",
                        "subject": "self-authored sample",
                        "stage": "measurement",
                        "fields": {
                            "finding": {
                                "value": "25 C for 2 h",
                                "raw_value": "25 C for 2 h",
                                "unit": None,
                                "status": "reported",
                                "nature": "reported",
                                "context": "Synthetic fixture, not a scientific result.",
                                "citations": [
                                    {
                                        "source_id": source["id"],
                                        "page": block["page"],
                                        "block_id": block["id"],
                                        "quote": block["text"],
                                    }
                                ],
                                "step_ids": [],
                            }
                        },
                        "steps": [],
                    }
                ],
                "claims": [],
                "issues": [],
                "requests": [],
            }
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(answer)}
                        ],
                    }
                ],
            },
        )

    provider = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    delivered = research.execute(task, consent=True, provider=provider)
    assert delivered["status"] == "COMPLETED"
    assert [r["phase"] for r in captured] == [INVENTORY_PHASE, "document_extraction"]
    assert captured[0]["material"] == captured[1]["material"]
    again = research.execute(task, consent=True, provider=provider)
    assert again["status"] == "COMPLETED" and len(captured) == 2


def test_ordinary_ui_strategy_selection_is_saved_and_old_plan_choice_is_loaded(
    tmp_path, monkeypatch
):
    pytest.importorskip("nicegui")
    import test_ui_research_submission as mounting

    original_contract = mounting.contract
    monkeypatch.setattr(
        mounting,
        "contract",
        lambda: {**original_contract(), "extraction_strategy": "source_first"},
    )
    _, (execute, _), elements, submitted, _, _, _ = mounting.mount(
        tmp_path, monkeypatch
    )
    strategy = next(e for e in elements if getattr(e, "label", "") == "科研提取策略")
    assert strategy.value == "source_first"
    assert set(strategy.options) == {"direct", "source_first"}
    assert any("不会自动提高上限" in getattr(e, "text", "") for e in elements)
    strategy.set_value("direct")
    asyncio.run(execute())
    assert submitted[-1]["task"]["extraction_strategy"] == "direct"


def test_strategy_preset_roundtrip_and_retired_choice_rejection(tmp_path, monkeypatch):
    pytest.importorskip("nicegui")
    import test_ui_research_submission as mounting

    from aletheia_nexus.workbench import ui_research

    controls = {}

    def capture(_settings, _group, read, apply, **_kwargs):
        controls.update(read=read, apply=apply)

    monkeypatch.setattr(ui_research, "preset_controls", capture)
    _, _, elements, _, _, _, _ = mounting.mount(tmp_path, monkeypatch)
    strategy = next(e for e in elements if getattr(e, "label", "") == "科研提取策略")
    controls["apply"]({"extraction_strategy": "source_first"})
    assert strategy.value == "source_first"
    assert controls["read"]()["extraction_strategy"] == "source_first"
    before = controls["read"]()
    with pytest.raises(ValueError, match="科研提取策略"):
        controls["apply"](
            {"extraction_strategy": "field_independent", "budget": {"max_calls": 1}}
        )
    assert controls["read"]() == before


@pytest.mark.parametrize(
    ("kind", "button"),
    [
        ("local", "本地创建可编辑计划（零模型调用）"),
        ("remote", "授权自然语言规划"),
    ],
)
def test_new_ordinary_ui_plans_default_to_source_first_without_raising_budget(
    tmp_path, monkeypatch, kind, button
):
    pytest.importorskip("nicegui")
    import test_ui_catalog_submission as mounting
    from nicegui import ui

    from aletheia_nexus.research_planner import DEFAULT_EXTRACTION_STRATEGY

    before = set(ui.context.client.elements)
    _, callbacks, submitted, calls, _ = mounting.mount(tmp_path, monkeypatch, kind)
    elements = [e for key, e in ui.context.client.elements.items() if key not in before]
    strategy = next(e for e in elements if getattr(e, "label", "") == "科研提取策略")
    assert strategy.value == DEFAULT_EXTRACTION_STRATEGY == "source_first"
    assert not submitted and not calls
    asyncio.run(callbacks[button]())
    parameters = submitted[0][3]
    assert parameters["material_options"]["extraction_strategy"] == "source_first"
    assert parameters["budget"]["max_calls"] == 10
    assert parameters["budget"]["max_cost"] == 2
    assert not calls  # Only queued; neither planning nor research has run.


def test_old_ui_task_without_strategy_keeps_legacy_direct_choice(tmp_path, monkeypatch):
    pytest.importorskip("nicegui")
    import test_ui_research_submission as mounting

    _, (execute, _), elements, submitted, _, _, _ = mounting.mount(
        tmp_path, monkeypatch
    )
    strategy = next(e for e in elements if getattr(e, "label", "") == "科研提取策略")
    assert strategy.value == "direct"
    asyncio.run(execute())
    assert submitted[-1]["task"]["extraction_strategy"] == "direct"


def test_local_mode_with_default_strategy_does_not_construct_or_call_model(research):
    from aletheia_nexus.research_planner import DEFAULT_EXTRACTION_STRATEGY

    task = research.local_plan("只准备本地自制夹具", ["p1"])
    task = research.configure_plan(
        task, {"extraction_strategy": DEFAULT_EXTRACTION_STRATEGY}
    )["task"]

    class ForbiddenProvider:
        def generate(self, *_args, **_kwargs):
            pytest.fail("Local source_first preparation must never call a model")

    receipt = research.execute(task, provider=ForbiddenProvider())
    assert receipt["status"] == "PREPARED"
    assert task["mode"] == "local" and not task["allow_remote"]
