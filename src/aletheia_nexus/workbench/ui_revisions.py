"""Readable editing and history of native, immutable scientific revisions."""

from copy import deepcopy

from aletheia_nexus.processing.contracts import NATURE
from aletheia_nexus.processing.results import FIELD_STATUS


def revised_field(original, kind, values):
    """Build a field replacement without altering its evidence or parent value."""
    status = values["status"]
    if status not in FIELD_STATUS:
        raise ValueError("请选择受支持的科学报告状态。")
    updated = deepcopy(original)
    updated["status"] = status
    updated["context"] = values["context"]
    if status == "not_reported":
        updated.update(value=None, raw_value=None, unit=None, nature=None)
        return updated
    value = values["value"]
    if kind == "string_list" and isinstance(value, str):
        value = [part.strip() for part in value.splitlines() if part.strip()]
    elif kind == "integer" and value is not None:
        if isinstance(value, bool) or int(value) != value:
            raise ValueError("整数类型不能保存小数。")
        value = int(value)
    elif kind == "boolean" and isinstance(value, str):
        value = {"true": True, "false": False, "null": None}[value]
    nature = values["nature"]
    if nature not in NATURE["enum"]:
        raise ValueError("请选择科学内容来自原文报告、作者解释或 AI 综合。")
    updated.update(
        value=value,
        raw_value=values["raw_value"] if values["raw_value"].strip() else None,
        nature=nature,
    )
    if "unit" in values:
        updated["unit"] = values["unit"].strip() or None
    return updated


def revision_history_rows(result):
    """Derive actual version links from native history, never invent timestamps."""
    history = result.get("history", [])
    rows = []
    for index, event in enumerate(history):
        if "record_id" in event:
            target = "记录 " + event["record_id"]
        elif "claim_index" in event:
            target = "主张 " + str(event["claim_index"] + 1)
        else:
            target = "诊断 " + str(event["issue_index"] + 1)
        child_id = (
            history[index + 1]["parent_result_id"]
            if index + 1 < len(history)
            else result["artifact_id"]
        )
        rows.append(
            {
                "id": child_id,
                "version": f"第 {index + 2} 版",
                "author": event["author"],
                "reason": event["reason"],
                "authority": "人工修订"
                if event.get("authority", "human") == "human"
                else "AI 修订",
                "confirmed": "人工已确认" if event["confirm"] else "未人工确认",
                "at": event["at"],
                "target": target,
            }
        )
    return rows


def render_revision_history(result):
    from nicegui import ui

    from .ui_common import rows_table

    with ui.expansion("版本与修订历史", icon="history").classes("w-full"):
        rows = revision_history_rows(result)
        if not rows:
            ui.label("这是原始科研结果，尚无人工或 AI 修订历史。")
            return
        ui.label(
            "第 1 版为不可变原始结果；每次修订创建下一版。人工确认只适用于该次明确核对的条目。"
        ).classes("an-muted text-sm")
        rows_table(
            rows,
            columns=[
                {
                    "name": key,
                    "label": label,
                    "field": key,
                    "align": "left",
                    "style": "white-space:pre-wrap;min-width:110px;max-width:320px",
                }
                for key, label in (
                    ("version", "版本"),
                    ("author", "修订人"),
                    ("reason", "修改理由"),
                    ("authority", "修订方式"),
                    ("confirmed", "人工确认"),
                    ("at", "时间"),
                    ("target", "修订条目"),
                )
            ],
        )
