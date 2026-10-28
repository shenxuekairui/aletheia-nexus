from copy import deepcopy

from aletheia_nexus.workbench.task_view import task_costs, task_counts, task_rows
from aletheia_nexus.workbench.ui_input_normalization import (
    batch_normalization_options,
    draft_fingerprint,
    normalization_preview_rows,
    normalization_warning_summaries,
)


def test_large_batch_recommendation_is_bounded_and_preserves_existing_budget():
    text = "\n".join(f"{n}. 10.9999/paper-{n}" for n in range(100))
    proposal = batch_normalization_options(text, {"max_cost": 3})
    assert proposal["max_output_tokens"] == 32768
    assert proposal["max_cost"] == 3
    assert proposal["max_calls"] == 1 and proposal["model"]["max_retries"] == 0
    proposal = batch_normalization_options(text * 10, {"max_cost": 0.1})
    assert proposal["max_output_tokens"] == 65536
    assert proposal["max_cost"] > 0.1


def test_large_model_batch_warning_summary_retains_count_without_repeating_rows():
    warning = {"code": "SERVER_ORGANIZATION_RESTORED", "message": "已保留原文明示分类"}
    summaries = normalization_warning_summaries([warning] * 100 + ["请核对标题"])
    assert len(summaries) == 2
    assert (
        "100 项" in summaries[0] and "SERVER_ORGANIZATION_RESTORED" not in summaries[0]
    )
    assert summaries[1] == "请核对标题"
    model_notes = [
        {"code": "MODEL_WARNING", "message": "Line 1 is not a paper"},
        {"code": "MODEL_WARNING", "message": "Keep original titles"},
    ]
    summaries = normalization_warning_summaries(model_notes)
    assert len(summaries) == 1 and "2 项" in summaries[0]
    assert model_notes[0]["message"] == "Line 1 is not a paper"


def test_preview_keeps_explicit_root_and_no_tags_distinct_from_default():
    items = [
        {
            "id": "a",
            "request": {"doi": "10.9999/a", "folder": None, "tags": []},
            "assignment": {"folder_mode": "root", "tags_mode": "custom"},
        },
        {
            "id": "b",
            "request": {"doi": "10.9999/b", "folder": None, "tags": []},
            "assignment": {"folder_mode": "inherit", "tags_mode": "inherit"},
        },
    ]
    rows = normalization_preview_rows({"items": items})
    assert (rows[0]["folder"], rows[0]["tags"]) == ("文库根目录", "无标签")
    assert (rows[1]["folder"], rows[1]["tags"]) == ("跟随批次默认", "跟随批次默认")


def test_async_preview_is_bound_to_text_placement_tags_and_library():
    snapshot = {
        "text": "10.9999/a",
        "rows": [{"id": "1", "folder": "催化", "tags": "待读"}],
        "default_folder": "",
        "default_tags": [],
        "library": "C:/papers",
    }
    original = draft_fingerprint(snapshot)
    assert original == draft_fingerprint(dict(reversed(list(snapshot.items()))))
    for path, value in (
        ("text", "10.9999/b"),
        ("default_folder", "文库"),
        ("default_tags", ["已读"]),
        ("library", "C:/other"),
    ):
        assert draft_fingerprint({**snapshot, path: value}) != original
    for key, value in (("folder", "机理"), ("tags", "已读")):
        changed = deepcopy(snapshot)
        changed["rows"][0][key] = value
        assert draft_fingerprint(changed) != original


def test_normalization_task_does_not_claim_file_moves_or_downloads():
    job = {
        "kind": "input_normalization",
        "status": "COMPLETED",
        "result": {
            "options": {"model": {"currency": "CNY"}},
            "calls": [
                {"estimated_cost": 0.03},
                {"estimated_cost": None, "reserved_cost": 0.1},
            ],
            "preview": {
                "items": [
                    {"id": "a", "request": {"doi": "10.9999/a", "folder": "催化"}},
                    {"id": "b", "request": {"title": "Untitled work"}},
                    {"id": "dup", "duplicate": True, "request": {"doi": "10.9999/a"}},
                ]
            },
        },
    }
    rows = task_rows(job)
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"PREPARED"}
    assert all("尚未获取" in row["phase"] for row in rows)
    assert task_counts(rows)["success"] == 2
    assert task_costs(job) == [
        {
            "label": "AI 整理输入",
            "calls": 2,
            "currency": "CNY",
            "known_cost": 0.03,
            "reserved_cost": 0.1,
            "unknown_calls": 1,
        }
    ]
