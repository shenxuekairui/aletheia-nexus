"""Deterministic field notes from fallible AI readings, never scientific confirmation."""

from __future__ import annotations

import json

READINGS_VERSION = "preserve-readings/2"

_NATURE_LABELS = {
    "experimental": "实验观察",
    "computational": "计算结果",
    "author_interpretation": "作者解释",
    "other_source_statement": "原文陈述",
}


def readings_identity(task: dict) -> dict:
    if task.get("source_assembly") != "preserve_readings":
        return {}
    return {
        "source_assembly": "preserve_readings",
        "source_readings_renderer": READINGS_VERSION,
    }


def preserve_readings(
    task: dict, package: dict, inventory: dict, owner_id: str
) -> dict:
    """Copy observations with readable scope/nature; keep provenance in the inventory.

    Field assignment is the first model's assignment. No scope inference, numerical
    normalization, absence inference or scientific correction occurs here. The full
    inventory is also retained by the existing source-first artifact/cache path.
    """
    definitions = {f["id"]: f for f in task["fields"]}
    documents = {d["id"]: d for d in package["documents"]}
    owner = documents[owner_id]
    assigned = {key: [] for key in definitions}
    unassigned = []
    for index, item in enumerate(inventory["items"]):
        if set(item["field_ids"]) - definitions.keys():
            raise ValueError("reading references unknown field")
        if item["source_id"] not in documents:
            raise ValueError("reading references unknown source")
        if not item["field_ids"]:
            unassigned.append((index, item))
        for field_id in dict.fromkeys(item["field_ids"]):
            assigned[field_id].append((index, item))

    fields = {}
    for field_id, items in assigned.items():
        notes = [
            "【"
            + _NATURE_LABELS[item["evidence_type"]]
            + ("｜" + item["subject_stage"] if item["subject_stage"] else "")
            + "】\n"
            + item["observation"]
            for _, item in items
        ]
        fields[field_id] = {
            "value": (
                notes
                if definitions[field_id]["type"] == "string_list"
                else "\n\n".join(notes)
            )
            if notes
            else None,
            "raw_value": None,
            "unit": None,
            "status": "unconfirmed",
            "nature": "ai_synthesis",
            "context": (
                "逐字归档的AI首读笔记；字段分配与科学内容均未经确认，"
                "不是重新综合的结论。完整谱系保留在关联的source-inventory工件中；"
                "原清单从0开始的条目索引：" + json.dumps([index for index, _ in items])
                if notes
                else "AI首读没有为此字段分配条目；不代表原文未报告。"
            ),
            "citations": [
                {
                    "source_id": item["source_id"],
                    "block_id": None,
                    "page": item["page"],
                    "quote": item["quote"],
                }
                for _, item in items
            ],
            "step_ids": [],
        }
    return {
        "records": [
            {
                "id": owner_id + "-readings",
                "subject": owner["source"]["title"],
                "stage": "source_reading_notes",
                "fields": fields,
                "steps": [],
            }
        ],
        "claims": [],
        "issues": [
            {
                "kind": "strategy_problem",
                "detail": "有AI首读笔记未分配到配置字段；原始内容及谱系已保留在关联首读清单中，需核对归属。",
                "source_id": item["source_id"],
                "page": item["page"],
            }
            for _, item in unassigned
        ],
        "requests": [],
    }
