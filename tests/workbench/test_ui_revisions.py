from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.processing.contracts import response_schema
from aletheia_nexus.processing.results import FIELD_STATUS
from aletheia_nexus.workbench.ui_revisions import revised_field, revision_history_rows


def field():
    return {
        "value": 25,
        "raw_value": "25 C",
        "unit": "°C",
        "status": "reported",
        "nature": "reported",
        "context": "measurement",
        "step_ids": [],
        "citations": [],
    }


def test_missing_report_status_clears_scientific_values_and_preserves_parent():
    original = field()
    before = deepcopy(original)
    edited = revised_field(
        original,
        "number",
        {"status": "not_reported", "context": "当前材料范围不足，不能核实。"},
    )
    assert original == before
    assert edited["value"] is None
    assert edited["raw_value"] is None
    assert edited["unit"] is None and edited["nature"] is None
    schema = response_schema({"fields": [{"id": "x", "type": "number"}]})
    native = schema["properties"]["records"]["items"]["properties"]["fields"][
        "properties"
    ]["x"]
    assert set(native["properties"]["status"]["enum"]) == set(FIELD_STATUS)
    with pytest.raises(ValueError, match="科学报告状态"):
        revised_field(original, "number", {"status": "fabricated"})


def test_history_uses_exact_child_links_and_distinguishes_ai_from_human():
    result = {
        "artifact_id": "child-2",
        "history": [
            {
                "record_id": "r1",
                "parent_result_id": "original",
                "author": "researcher",
                "at": "2026-10-28T01:00:00Z",
                "reason": "checked original page",
                "authority": "human",
                "confirm": True,
            },
            {
                "claim_index": 0,
                "parent_result_id": "child-1",
                "author": "assistant-review",
                "at": "2026-10-28T02:00:00Z",
                "reason": "revised claim",
                "authority": "assistant",
                "confirm": False,
            },
        ],
    }
    rows = revision_history_rows(result)
    assert [r["id"] for r in rows] == ["child-1", "child-2"]
    assert [r["authority"] for r in rows] == ["人工修订", "AI 修订"]
    assert [r["confirmed"] for r in rows] == ["人工已确认", "未人工确认"]
    assert [r["at"] for r in rows] == [r["at"] for r in result["history"]]


def test_ordinary_revision_widgets_really_submit_unit_raw_and_status(monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench.ui_research import ResearchPages

    # Run the actual synchronous save callback without a live server event loop.
    monkeypatch.setattr("aletheia_nexus.workbench.ui_research.guard", lambda f: f)

    class Controller(ResearchPages):
        pass

    saved = []

    def revise(*args, **kwargs):
        saved.append((args, kwargs))
        return {"result": "new-version.result.json"}

    controller = Controller()
    controller.ctx = SimpleNamespace(research=SimpleNamespace(revise=revise))
    controller.page_content = SimpleNamespace(refresh=lambda: None)
    result = {
        "task": {"fields": [{"id": "temperature", "type": "number"}]},
        "response": {
            "records": [{"id": "r1", "fields": {"temperature": field()}}],
            "claims": [],
            "issues": [],
        },
    }
    previous = set(ui.context.client.elements)
    controller.revision_dialog("parent.result.json", result)
    elements = [
        item for key, item in ui.context.client.elements.items() if key not in previous
    ]

    def labeled(label):
        return next(item for item in elements if item._props.get("label") == label)

    raw = labeled("原文值（保留原文拼写；无单一原文值时可留空）")
    unit = labeled("单位（没有单位时留空）")
    status = labeled("科学报告状态")
    status.set_value("not_reported")
    assert not unit.parent_slot.parent.visible
    status.set_value("normalized")
    assert unit.parent_slot.parent.visible
    raw.set_value("25 C")
    unit.set_value("K")
    labeled("值").set_value(298.15)
    labeled("修改理由 / 核对依据").set_value("按原文温度作显式单位转换")
    button = next(
        item for item in elements if getattr(item, "text", "") == "保存独立修订版本"
    )
    handler = next(
        v.handler for v in button._event_listeners.values() if v.type == "click"
    )
    handler(None)
    replacement = saved[0][0][2]["fields"]["temperature"]
    assert replacement["value"] == 298.15
    assert replacement["raw_value"] == "25 C"
    assert replacement["unit"] == "K"
    assert replacement["status"] == "normalized"
    assert not saved[0][1]["confirm"]
