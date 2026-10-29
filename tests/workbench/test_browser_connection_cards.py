"""Ordinary recovery cards explain aggregate facts without exposing CDP internals."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.task_view import (
    browser_connection_summaries,
    task_counts,
    task_rows,
)


def diagnostic(**values):
    return {
        "schema": "aletheia-nexus/browser-connection-diagnostic/v1",
        "code": "browser_cdp_attach_timeout",
        "stage": "cdp_attach",
        "timeout_seconds": 45,
        "elapsed_seconds": 45.027,
        "websocket_connected": None,
        "endpoint_reachable": True,
        "page_count": 15,
        "pdf_like_page_count": 2,
        # These arbitrary native fields must never reach the ordinary card.
        "message": "原始 SDK 消息 ws://127.0.0.1:1234/devtools/browser/private-uuid",
        "endpoint": "http://127.0.0.1:1234/",
        "targets": [{"url": "https://publisher.test/paper.pdf?token=private-secret"}],
        "error_type": "PrivateInternalSDKClass",
        "recovery_actions": [
            {"label": "泄露 private-secret", "description": "https://private.test/"}
        ],
        **values,
    }


def paper(identity, *, si_only=False, details=None):
    details = diagnostic() if details is None else details
    return {
        "id": identity,
        "request": {"doi": f"10.1000/{identity}", "title": f"论文 {identity}"},
        "main_status": "VERIFIED" if si_only else "BROWSER_UNAVAILABLE",
        "status": "VERIFIED" if si_only else "BROWSER_UNAVAILABLE",
        "si_status": "FAILED" if si_only else "NOT_ATTEMPTED",
        "browser_connection": deepcopy(details),
        "reason": details.get("message", "") if isinstance(details, dict) else "",
        "supplements": {"diagnostics": [deepcopy(details)]} if si_only else {},
    }


def job(*items, **values):
    return {
        "id": "job",
        "label": "获取测试",
        "kind": "acquisition",
        "status": "PARTIAL",
        "total": len(items),
        "current_index": len(items),
        "records": [],
        "result": {"items": list(items)},
        **values,
    }


def test_same_connection_is_one_card_with_main_and_si_counts_and_unchanged_receipt():
    receipt = job(paper("a"), paper("b"), paper("c", si_only=True))
    before = deepcopy(receipt)
    summaries = browser_connection_summaries(receipt)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["affected_count"] == 3
    assert summary["main_unavailable_count"] == 2 and summary["si_only_count"] == 1
    assert "2 篇正文尚未验证成功" in summary["summary"]
    assert "1 篇正文已验证、仅 SI" in summary["summary"]
    assert "WebSocket：未知" in summary["observations"]
    assert summary["retry_available"]
    rows = task_rows(receipt)
    assert rows[2]["status"] == "VERIFIED" and rows[2]["si_status"] == "FAILED"
    assert task_counts(rows)["success"] == 1 and task_counts(rows)["failed"] == 2
    assert rows[0]["reason"] == "浏览器连接未完成；请查看本批恢复提示。"
    assert receipt == before
    ordinary = json.dumps([summaries, rows], ensure_ascii=False)
    for forbidden in (
        "private-uuid",
        "private-secret",
        "PrivateInternalSDKClass",
        "http:",
        "https:",
        "ws:",
    ):
        assert forbidden not in ordinary


def test_distinct_connection_stages_are_separate_groups():
    summaries = browser_connection_summaries(
        job(
            paper("a"),
            paper(
                "b",
                details=diagnostic(
                    code="browser_context_setup_failed",
                    stage="ignored unsafe raw stage",
                ),
            ),
        )
    )
    assert len(summaries) == 2
    assert summaries[1]["stage"] == "context_setup"
    assert "安全初始化" in summaries[1]["heading"]
    assert "ignored" not in json.dumps(summaries)


def test_running_task_uses_latest_native_records_and_current_paper_without_result():
    first = paper("a")
    restored = {**paper("a", si_only=True), "si_status": "COMPLETED"}
    current = paper("b", si_only=True)
    receipt = job(
        status="RUNNING",
        result=None,
        records=[
            {"item_id": "a", "native": first},
            {"item_id": "a", "native": restored},
            {"item_id": "parse-irrelevant", "status": "FAILED"},
        ],
        current_item=current,
    )
    summaries = browser_connection_summaries(receipt)
    assert len(summaries) == 1 and summaries[0]["affected_count"] == 1
    assert summaries[0]["si_only_count"] == 1
    assert not summaries[0]["retry_available"]
    assert any("任务结束后" in text for text in summaries[0]["instructions"])


@pytest.mark.parametrize(
    "kind", ["research", "translation", "planning", "input_normalization"]
)
def test_other_task_kinds_never_gain_browser_retry_or_paid_resend_controls(kind):
    assert browser_connection_summaries(job(paper("a"), kind=kind)) == []


def test_completed_task_keeps_historical_diagnostic_without_retry_hint():
    summary = browser_connection_summaries(job(paper("a"), status="COMPLETED"))[0]
    assert not summary["retry_available"]
    assert any("历史诊断" in text for text in summary["instructions"])
    assert not any("使用下方" in text for text in summary["instructions"])
    resolved = paper("b", si_only=True)
    resolved["si_status"] = "COMPLETED"
    assert browser_connection_summaries(job(resolved)) == []


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        42,
        {"code": ["bad"]},
        {"schema": "unknown", "code": "browser_cdp_attach_timeout"},
    ],
)
def test_malformed_or_unknown_native_diagnostic_is_ignored(bad):
    value = paper("a", details=bad)
    value["browser_connection"] = bad
    value["supplements"] = {"diagnostics": 42, "items": 42}
    assert browser_connection_summaries(job(value)) == []


def test_raw_fact_values_are_not_coerced_or_echoed_as_diagnostics():
    summary = browser_connection_summaries(
        job(
            paper(
                "a",
                details=diagnostic(
                    timeout_seconds=float("inf"),
                    websocket_connected="false private-secret",
                    endpoint_reachable="true private-secret",
                    page_count=True,
                    pdf_like_page_count=-1,
                ),
            )
        )
    )[0]
    assert summary["timeout_seconds"] is None
    assert (
        summary["websocket_connected"] is None and summary["endpoint_reachable"] is None
    )
    assert summary["page_count"] is None and summary["pdf_like_page_count"] is None
    assert "private-secret" not in json.dumps(summary)
    assert "未知" in summary["observations"]


def render_task(receipt, monkeypatch):
    ui = pytest.importorskip("nicegui.ui")
    from aletheia_nexus.workbench import ui_tasks

    recoveries, expert = [], []
    manager = SimpleNamespace(
        list=lambda: [deepcopy(receipt)],
        get=lambda _: deepcopy(receipt),
        control=lambda *args: pytest.fail("render must not control jobs"),
    )
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            jobs=manager,
            library=SimpleNamespace(operations=lambda: []),
            research=SimpleNamespace(history=lambda: []),
        ),
        output_links=lambda result: None,
        recover_acquisition_dialog=lambda value: recoveries.append(deepcopy(value)),
    )
    monkeypatch.setattr(ui_tasks, "guard", lambda callback: callback)
    monkeypatch.setattr(
        ui_tasks, "json_view", lambda value, **kwargs: expert.append(deepcopy(value))
    )
    monkeypatch.setattr(
        ui, "timer", lambda *_args, **_kwargs: SimpleNamespace(active=True)
    )
    before = set(ui.context.client.elements)
    ui_tasks.render_task_dialog(controller)
    elements = [
        value for key, value in ui.context.client.elements.items() if key not in before
    ]
    next(value for value in elements if "an-job-card" in value.classes).set_value(True)
    elements = [
        value for key, value in ui.context.client.elements.items() if key not in before
    ]
    return elements, recoveries, expert


@pytest.mark.parametrize("kind", ["acquisition", "acquire"])
def test_real_task_center_renders_one_safe_card_and_reuses_one_existing_preview(
    monkeypatch, kind
):
    receipt = job(paper("a"), paper("b", si_only=True), kind=kind)
    before = deepcopy(receipt)
    elements, recoveries, expert = render_task(receipt, monkeypatch)
    assert (
        len([value for value in elements if "an-browser-recovery" in value.classes])
        == 1
    )
    text = "\n".join(str(getattr(value, "text", "")) for value in elements)
    assert "WebSocket：未知" in text and "正文已验证、仅 SI 待处理" in text
    for forbidden in (
        "private-uuid",
        "private-secret",
        "PrivateInternalSDKClass",
        "127.0.0.1",
    ):
        assert forbidden not in text
    buttons = [
        value
        for value in elements
        if getattr(value, "text", "") == "重试获取失败 / 补取 SI"
    ]
    assert len(buttons) == 1 and buttons[0].enabled
    assert recoveries == []  # Neither rendering nor a live refresh starts work.
    callback = next(
        listener.handler
        for listener in buttons[0]._event_listeners.values()
        if listener.type == "click"
    )
    callback(None)
    assert recoveries == [before]
    assert before in expert and receipt == before  # Original expert receipt retained.


def test_real_completed_task_dialog_does_not_offer_retry_button(monkeypatch):
    elements, recoveries, _ = render_task(
        job(paper("a"), status="COMPLETED"), monkeypatch
    )
    assert not any(
        getattr(value, "text", "") == "重试获取失败 / 补取 SI" for value in elements
    )
    assert recoveries == []
