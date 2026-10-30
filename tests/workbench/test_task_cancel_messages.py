"""Pure acquisition cancellation must not invent a model billing warning."""

from copy import deepcopy
from threading import Event

import pytest

from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.task_view import acquisition_retry_label, task_stage_text


@pytest.mark.parametrize(
    "kind,parameters",
    [
        (
            "acquisition",
            {
                "postprocess": {
                    "title_translation": {"enabled": False, "consent": False}
                }
            },
        ),
        (
            "acquisition",
            {"postprocess": {"title_translation": {"enabled": True, "consent": False}}},
        ),
        ("parse", {}),
        ("import", {}),
        ("research", {"model": {"name": "fixture-only"}, "budget": {"max_cost": 1}}),
        ("research", {"task": {"mode": "local", "allow_remote": False}}),
    ],
)
def test_local_and_unauthorized_work_has_only_safe_boundary_instructions(
    kind, parameters
):
    receipt = {
        "kind": kind,
        "status": "CANCEL_REQUESTED",
        "parameters": parameters,
        "stage": "正在等待当前操作结束；远程请求可能已计费",
    }
    original = deepcopy(receipt)
    text = task_stage_text(receipt)
    assert "安全边界" in text and "不会继续调度" in text
    assert "计费" not in text and "模型请求" not in text
    assert receipt == original  # Old diagnostic bytes stay unchanged.


@pytest.mark.parametrize(
    "receipt",
    [
        {"kind": "translation"},
        {"kind": "input_normalization"},
        {"kind": "research", "parameters": {"planning_max_cost": 0.1}},
        {
            "kind": "research",
            "parameters": {"task": {"mode": "parsed", "allow_remote": True}},
        },
        {
            "kind": "acquisition",
            "parameters": {
                "postprocess": {"title_translation": {"enabled": True, "consent": True}}
            },
        },
        {
            "kind": "import",
            "parameters": {"title_translation": {"enabled": True, "consent": True}},
        },
        {"kind": "acquisition", "billing_uncertain": True},
    ],
)
def test_model_work_preserves_conditional_billing_notice(receipt):
    text = task_stage_text({**receipt, "status": "CANCEL_REQUESTED"})
    assert "若模型请求已经发送" in text and "调用账本" in text


def test_manager_persists_true_acquisition_cancellation_stage(tmp_path):
    manager = TaskManager(tmp_path)
    entered, release = Event(), Event()

    def worker(context):
        entered.set()
        assert release.wait(3)
        context.checkpoint()
        return {"status": "COMPLETED"}

    try:
        receipt = manager.submit(
            "acquisition",
            "合成取消边界",
            [],
            worker,
            parameters={"postprocess": {"title_translation": {"enabled": False}}},
        )
        assert entered.wait(2)
        cancelled = manager.control(receipt["id"], "cancel")
        assert cancelled["status"] == "CANCEL_REQUESTED"
        assert "后续论文" in cancelled["stage"] and "计费" not in cancelled["stage"]
    finally:
        release.set()
        manager.close(wait=True)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("获取 25 篇论文", "获取 25 篇论文"),
        ("重试 1 篇 · 获取 25 篇论文", "获取 25 篇论文"),
        ("重试1篇 · 重试 2 篇 · 获取25篇论文", "获取25篇论文"),
        ("我的重试1篇 · 特定研究", "我的重试1篇 · 特定研究"),
        ("重试问题记录", "重试问题记录"),
    ],
)
def test_retry_display_label_does_not_accumulate_generated_prefixes(label, expected):
    assert acquisition_retry_label(label, 3) == "重试 3 篇 · " + expected
    assert (
        acquisition_retry_label(acquisition_retry_label(label, 3), 1)
        == "重试 1 篇 · " + expected
    )
