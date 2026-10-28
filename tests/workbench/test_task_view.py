from copy import deepcopy
from pathlib import Path

from aletheia_nexus.workbench.task_view import (
    attachment_rows,
    task_costs,
    task_counts,
    task_rows,
)


def test_realistic_acquisition_failure_and_independent_si_are_readable():
    receipt = {
        "kind": "acquisition",
        "status": "PARTIAL",
        "result": {
            "items": [
                {
                    "id": "a",
                    "request": {"title": "论文甲"},
                    "status": "VERIFIED",
                    "main_status": "VERIFIED",
                    "si_status": "PARTIAL",
                    "reason": "正文已验证；SI仍有未完成项",
                    "source": "nature.com",
                    "attempts": 1,
                    "folder": "D:/文库",
                    "supplements": {
                        "truncated": True,
                        "items": [
                            {
                                "path": "D:/文库/SI/a.pdf",
                                "role": "SUPPLEMENT",
                                "status": "SAVED",
                            }
                        ],
                    },
                },
                {
                    "id": "b",
                    "request": {"doi": "10.1000/test"},
                    "status": "EXHAUSTED",
                    "si_status": "NOT_ATTEMPTED",
                    "reason": "所有可用路线已尝试，请核对机构权限。",
                    "attempts": 3,
                },
                {"id": "c", "request": {"title": "论文丙"}, "status": "AUTH_REQUIRED"},
                {"id": "d", "status": "SKIPPED"},
                {"id": "e", "status": "BROWSER_UNAVAILABLE"},
            ]
        },
    }
    unchanged = deepcopy(receipt)
    rows = task_rows(receipt)
    counts = task_counts(rows)
    assert counts == {
        "total": 5,
        "success": 1,
        "failed": 2,
        "interaction": 1,
        "partial": 0,
        "skipped": 1,
        "pending": 0,
    }
    assert rows[0]["status"] == "VERIFIED" and rows[0]["si_status"] == "PARTIAL"
    assert rows[1]["reason"].startswith("所有可用路线")
    attachments = attachment_rows(receipt)
    assert attachments[-1]["status"] == "PARTIAL"
    assert "数量限制" in attachments[-1]["reason"]
    assert receipt == unchanged


def test_cancelled_research_keeps_delivered_results_pending_items_and_usage():
    job = {
        "kind": "research",
        "status": "CANCELLED",
        "result": {
            "native_runs": [
                {
                    "items": [
                        {"id": "a", "status": "COMPLETED"},
                        {"id": "b", "status": "PENDING"},
                    ],
                    "usage": {
                        "http_attempts": 1,
                        "estimated_cost": 0.01,
                        "currency": "CNY",
                        "unknown_usage_calls": 0,
                    },
                }
            ]
        },
    }
    assert task_counts(task_rows(job))["pending"] == 1
    assert task_costs(job)[0]["calls"] == 1
    assert task_costs(job)[0]["known_cost"] == 0.01


def test_unknown_billing_retains_reservation_and_does_not_report_zero_as_known():
    job = {
        "kind": "import",
        "result": {
            "translation": {
                "options": {"model": {"currency": "CNY"}},
                "calls": [
                    {"status": "timeout", "estimated_cost": None, "reserved_cost": 0.2}
                ],
            }
        },
    }
    cost = task_costs(job)[0]
    assert cost["unknown_calls"] == 1 and cost["reserved_cost"] == 0.2
    assert cost["known_cost"] is None


def test_planning_ledger_survives_failure_and_observed_zero_is_explicit():
    job = {"result": None, "planning_calls": [], "planning_usage": {"http_attempts": 0}}
    assert task_costs(job)[0]["calls"] == 0
    job["planning_calls"] = [{"estimated_cost": None, "reserved_cost": 0.13}]
    row = task_costs(job)[0]
    assert row["label"] == "自然语言规划" and row["known_cost"] is None
    assert row["unknown_calls"] == 1 and row["reserved_cost"] == 0.13


def test_rolled_back_rename_does_not_reuse_the_preflight_ready_state():
    job = {
        "kind": "rename",
        "status": "FAILED",
        "result": {
            "status": "ROLLED_BACK",
            "preview": {
                "items": [
                    {
                        "id": "a",
                        "title": "论文",
                        "status": "READY",
                        "new_path": "D:/文库/new.pdf",
                    }
                ]
            },
        },
    }
    assert task_rows(job)[0]["status"] == "ROLLED_BACK"


def test_skipped_preflight_keeps_old_path_and_is_not_claimed_successful():
    job = {
        "kind": "rename",
        "status": "COMPLETED",
        "result": {
            "status": "COMPLETED",
            "preview": {
                "items": [
                    {
                        "id": "a",
                        "status": "SKIP",
                        "old_path": "D:/old/paper.pdf",
                        "new_path": "D:/new/paper.pdf",
                        "errors": ["missing Chinese translation"],
                    }
                ]
            },
        },
    }
    row = task_rows(job)[0]
    assert row["status"] == "SKIPPED" and Path(row["folder"]) == Path("D:/old")
    assert task_counts([row])["success"] == 0
