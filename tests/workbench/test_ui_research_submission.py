"""Paid execution clicks must await one preflight and reuse active full contracts."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.ui_research import ResearchPages, active_research_task


def contract():
    return {
        "schema": "aletheia-nexus/research-task/v1",
        "id": "shared-visible-id",
        "objective": "核对两篇文献中的催化剂",
        "type": "compare",
        "mode": "parsed",
        "allow_remote": True,
        "documents": [
            {"id": name, "pdf": name + ".pdf", "pages": [1, 2]}
            for name in ("paper1", "si1", "paper2", "si2")
        ],
        "fields": [
            {
                "id": "catalyst",
                "label": "催化剂",
                "type": "string",
                "description": "仅记录原文明确的催化剂",
                "unit": None,
                "scope": "正文",
            }
        ],
        "budget": {"max_calls": 3, "max_cost": 1.0, "max_supplement_rounds": 0},
        "synthesize": True,
        "include_steps": False,
    }


@pytest.mark.parametrize(
    "status", ["QUEUED", "RUNNING", "PAUSED", "WAITING_INTERACTION", "CANCEL_REQUESTED"]
)
def test_active_full_contract_is_found_in_all_nonterminal_states(status):
    task = contract()
    active = {
        "id": "same",
        "kind": "research",
        "status": status,
        "parameters": {"task": deepcopy(task)},
    }
    assert active_research_task([active], task) is active


@pytest.mark.parametrize(
    "status", ["COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED"]
)
def test_terminal_runs_do_not_block_an_explicit_reviewed_new_execution(status):
    task = contract()
    assert (
        active_research_task(
            [{"kind": "research", "status": status, "parameters": {"task": task}}], task
        )
        is None
    )


@pytest.mark.parametrize("changed", ["cost", "pages", "model", "documents"])
def test_same_visible_task_id_does_not_block_changed_actual_parameters(changed):
    task = contract()
    other = deepcopy(task)
    if changed == "cost":
        other["budget"]["max_cost"] = 0.7
    elif changed == "pages":
        other["documents"][0]["pages"] = [3]
    elif changed == "model":
        other["model"] = {"name": "another-model"}
    else:
        other["documents"].pop()
    job = {"kind": "research", "status": "RUNNING", "parameters": {"task": task}}
    assert task["id"] == other["id"]
    assert active_research_task([job], other) is None


def test_explicit_fingerprint_survives_secret_redaction_in_durable_parameters():
    from aletheia_nexus.processing.contracts import digest

    task = contract()
    job = {
        "id": "active",
        "kind": "research",
        "status": "QUEUED",
        "parameters": {
            "task": {"objective": "[REDACTED]"},
            "task_fingerprint": digest(task),
        },
    }
    assert active_research_task([job], task) is job


def mount(tmp_path, monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.processing.contracts import digest
    from aletheia_nexus.workbench import ui_research
    from aletheia_nexus.workbench.settings import SettingsStore

    jobs, calls, notices, callbacks = [], [], [], {}

    def checked(task):
        return {
            "task": deepcopy(task),
            "plan": "本次只使用固定材料",
            "task_fingerprint": digest(task),
        }

    research = SimpleNamespace(
        app=SimpleNamespace(
            check_document=lambda document, mode: SimpleNamespace(
                identity={
                    "title": document["id"],
                    "document_role": "SUPPLEMENT"
                    if document["id"].startswith("si")
                    else "ARTICLE",
                    "page_count": 10,
                    "identity_basis": "acquisition_verified",
                }
            )
        ),
        validate_plan=checked,
    )

    class Controller(ResearchPages):
        current_task = contract()

        def title(self, *_):
            pass

        def selection_dialog(self):
            pytest.fail("Selection is separate from this fixed historical plan")

        def task_dialog(self):
            pass

        def submit(self, kind, label, ids, worker, parameters):
            # Record the real callback's task; never execute its model worker.
            calls.append(deepcopy(parameters))
            receipt = {
                "id": str(len(calls)),
                "kind": kind,
                "status": "QUEUED",
                "parameters": deepcopy(parameters),
            }
            jobs.append(receipt)
            return receipt

    original_button = ui.button

    def capture(*args, **kwargs):
        button = original_button(*args, **kwargs)
        label = args[0] if args else kwargs.get("text")
        callbacks[label] = (kwargs.get("on_click"), button)
        return button

    monkeypatch.setattr(ui_research, "guard", lambda callback: callback)
    monkeypatch.setattr(ui, "button", capture)
    monkeypatch.setattr(ui, "timer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ui, "notify", lambda text, **kwargs: notices.append(text))

    async def read(grid):
        return deepcopy(grid.options["rowData"])

    monkeypatch.setattr(ui_research, "read_edited_grid", read)
    before = set(ui.context.client.elements)
    controller = Controller()
    controller.ctx = SimpleNamespace(
        research=research,
        library=SimpleNamespace(selection=lambda: ["global1", "global2", "global3"]),
        jobs=SimpleNamespace(list=lambda: deepcopy(jobs)),
        settings=SettingsStore(tmp_path),
    )
    controller.research_page()
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    consent = next(
        element
        for element in elements
        if getattr(element, "text", "").startswith("我已核对实际材料和预算")
    )
    consent.set_value(True)
    return (
        controller,
        callbacks["执行已核对计划"],
        elements,
        calls,
        jobs,
        notices,
        research,
    )


def test_actual_execute_callback_blocks_double_click_during_async_preflight_and_active_job(
    tmp_path, monkeypatch
):
    from aletheia_nexus.workbench import ui_research

    _, (execute, button), elements, submitted, jobs, notices, _ = mount(
        tmp_path, monkeypatch
    )
    assert any(
        "本计划固定材料：2 篇正文、2 份附件" in getattr(element, "text", "")
        for element in elements
    )
    assert any(
        "当前选择 3 篇论文" == getattr(element, "text", "") for element in elements
    )

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def read(grid):
            entered.set()
            await release.wait()
            return deepcopy(grid.options["rowData"])

        monkeypatch.setattr(ui_research, "read_edited_grid", read)
        first = asyncio.create_task(execute())
        await entered.wait()
        assert not button.enabled and not submitted
        await execute()  # A second click can arrive despite the disabled widget.
        assert not submitted and "正在核对" in notices[-1]
        release.set()
        await first
        assert button.enabled and len(submitted) == 1
        await execute()  # Preflight finished, but its exact job is still queued.
        assert len(submitted) == 1 and "未重复提交" in notices[-1]
        jobs[-1]["status"] = "COMPLETED"
        await execute()
        assert len(submitted) == 2 and button.enabled

    asyncio.run(scenario())


def test_actual_execute_callback_releases_gate_after_failed_validation(
    tmp_path, monkeypatch
):
    _, (execute, button), _, submitted, _, _, research = mount(tmp_path, monkeypatch)
    original = research.validate_plan

    def invalid(_):
        raise ValueError("本次计划尚未通过验证")

    research.validate_plan = invalid
    with pytest.raises(ValueError, match="尚未通过验证"):
        asyncio.run(execute())
    assert button.enabled and not submitted
    research.validate_plan = original
    asyncio.run(execute())
    assert len(submitted) == 1 and button.enabled
