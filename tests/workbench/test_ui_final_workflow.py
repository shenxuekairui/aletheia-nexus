"""Actual widget actions keep view IDs and paid planning submissions distinct."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui")

from nicegui import run, ui

from aletheia_nexus.workbench import ui_research
from aletheia_nexus.workbench.settings import SettingsStore


def buttons(monkeypatch):
    callbacks = {}
    original = ui.button

    def capture(*args, **kwargs):
        element = original(*args, **kwargs)
        callbacks[args[0] if args else kwargs.get("text")] = (
            kwargs.get("on_click"),
            element,
        )
        return element

    monkeypatch.setattr(ui, "button", capture)
    monkeypatch.setattr(ui_research, "guard", lambda callback: callback)
    return callbacks


def test_switch_search_views_rebuilds_same_report_and_clears_old_id_selection(
    monkeypatch,
):
    callbacks = buttons(monkeypatch)
    calls, selected, notices = [], [], []
    paper = {"id": "paper1", "title": "原题", "folder": "", "tags": []}
    report = {
        "hits": [
            {
                "id": "hit1",
                "number": 1,
                "paper_id": "paper1",
                "pages": [3],
                "source": {"title": "原题", "document_role": "ARTICLE"},
                "text": "Exact original paragraph",
                "kind": "paragraph",
                "status": "PARSED",
            }
        ],
        "coverage": {
            "searched_documents": 1,
            "completed": 1,
            "partial": 0,
            "unsearched": [],
        },
        "offset": 50,
        "returned_hits": 1,
        "total_hits": 100,
        "search_scope": {"ids": ["paper1"]},
        "interpretation": "Keyword evidence only",
    }

    def search(*args, **kwargs):
        calls.append((args, kwargs))
        return deepcopy(report)

    class Page(ui_research.ResearchPages):
        def title(self, *_):
            pass

    page = Page()
    page.ctx = SimpleNamespace(
        library=SimpleNamespace(
            scan=lambda **_: {"items": [paper]},
            collections=lambda: {},
            get=lambda _: paper,
            set_selection=lambda ids, **_: selected.append(ids),
        ),
        research=SimpleNamespace(search=search),
    )

    async def io_bound(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    monkeypatch.setattr(run, "io_bound", io_bound)
    monkeypatch.setattr(ui, "notify", lambda text, **_: notices.append(text))
    before = set(ui.context.client.elements)
    page.search_page()

    def elements():
        return [
            value
            for key, value in ui.context.client.elements.items()
            if key not in before
        ]

    view = next(e for e in elements() if getattr(e, "label", None) == "展示方式")
    offset = next(e for e in elements() if getattr(e, "label", None) == "证据偏移量")
    offset.set_value(50)
    asyncio.run(callbacks["检索本地原文"][0]())
    evidence = next(e for e in elements() if isinstance(e, ui.table))
    evidence.selected = [evidence.rows[0]]
    view.set_value("论文视图")
    papers = next(e for e in elements() if isinstance(e, ui.table))
    assert evidence.is_deleted and papers is not evidence
    assert papers.rows[0]["id"] == "paper1" and not papers.selected
    assert "清空本页勾选" in notices[-1]
    with pytest.raises(ValueError, match="请勾选"):
        callbacks["选择命中论文"][0]()
    papers.selected = [papers.rows[0]]
    callbacks["选择命中论文"][0]()
    assert selected == [["paper1"]]
    view.set_value("证据视图")
    evidence_again = next(e for e in elements() if isinstance(e, ui.table))
    assert evidence_again.rows[0]["id"] == "hit1" and not evidence_again.selected
    evidence_again.selected = [evidence_again.rows[0]]
    callbacks["选择命中论文"][0]()
    assert selected == [["paper1"], ["paper1"]]
    assert len(calls) == 1 and calls[0][1]["offset"] == offset.value == 50
    assert page.search_report == report


def mount_planning(tmp_path, monkeypatch):
    callbacks = buttons(monkeypatch)
    jobs, submitted, notices = [], [], []
    monkeypatch.setattr(ui, "timer", lambda *_, **__: None)
    monkeypatch.setattr(ui, "notify", lambda text, **_: notices.append(text))

    class Page(ui_research.ResearchPages):
        current_task = None
        before_submit = None

        def title(self, *_):
            pass

        def selection_dialog(self):
            pass

        def submit(self, kind, label, ids, worker, parameters):
            if self.before_submit:
                self.before_submit()
            job = {
                "id": str(len(jobs) + 1),
                "kind": kind,
                "status": "QUEUED",
                "parameters": deepcopy(parameters),
            }
            jobs.append(job)
            submitted.append((worker, deepcopy(parameters)))
            return job

    page = Page()
    research_calls = []

    def plan(*args, **kwargs):
        research_calls.append((deepcopy(args), deepcopy(kwargs)))
        return {"task": {"objective": args[0]}}

    page.ctx = SimpleNamespace(
        library=SimpleNamespace(selection=lambda: ["paper1"], root=tmp_path),
        research=SimpleNamespace(
            parser_options=lambda: {"ocr": False},
            plan=plan,
            configure_plan=lambda task, options, previous: previous,
        ),
        settings=SettingsStore(tmp_path / "settings"),
        jobs=SimpleNamespace(list=lambda: deepcopy(jobs)),
    )
    before = set(ui.context.client.elements)
    page.research_page()
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    consent = next(
        e for e in elements if getattr(e, "text", "").startswith("我授权仅将科研目标")
    )
    consent.set_value(True)
    return page, callbacks, elements, jobs, submitted, notices, research_calls


def test_planning_blocks_reentrant_and_identical_active_requests_but_not_reviewed_changes(
    tmp_path, monkeypatch
):
    page, callbacks, elements, jobs, submitted, notices, research_calls = (
        mount_planning(tmp_path, monkeypatch)
    )
    callback, button = callbacks["授权自然语言规划"]
    goal = next(
        e for e in elements if getattr(e, "label", None) == "科研目标（自然语言）"
    )
    goal.set_value("比较原文中的电位")

    def double_click():
        assert not button.enabled
        callback()

    page.before_submit = double_click
    callback()
    assert len(submitted) == 1 and button.enabled
    assert "正在核对并提交规划" in notices[-1]
    page.before_submit = None
    callback()
    assert len(submitted) == 1 and "未重复提交" in notices[-1]
    original_parameters = deepcopy(submitted[0][1])
    goal.set_value("新的目标")
    page.ctx.settings.set("parsing", {"ocr": True})
    submitted[0][0](None)
    assert research_calls[0][0] == ("比较原文中的电位", ["paper1"])
    assert research_calls[0][1]["parse_options"] == {"ocr": False}
    assert submitted[0][1] == original_parameters
    callback()
    assert len(submitted) == 2
    assert (
        submitted[0][1]["planning_fingerprint"]
        != submitted[1][1]["planning_fingerprint"]
    )
    jobs[-1]["status"] = "FAILED"
    callback()
    assert len(submitted) == 3 and button.enabled


def test_failed_planning_submission_unlocks_and_can_be_explicitly_retried(
    tmp_path, monkeypatch
):
    page, callbacks, _, _, submitted, _, _ = mount_planning(tmp_path, monkeypatch)
    callback, button = callbacks["授权自然语言规划"]

    def failed():
        raise RuntimeError("synthetic queue failure")

    page.before_submit = failed
    with pytest.raises(RuntimeError, match="synthetic"):
        callback()
    assert button.enabled and not submitted
    page.before_submit = None
    callback()
    assert len(submitted) == 1 and button.enabled
