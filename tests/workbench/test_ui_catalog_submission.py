"""Research and parse actions submit reviewed sources, never every variant."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui")

from nicegui import run, ui

from aletheia_nexus.workbench import ui_catalog_sources, ui_research
from aletheia_nexus.workbench.research import WorkbenchResearch
from aletheia_nexus.workbench.settings import SettingsStore


def mount(tmp_path, monkeypatch, page_kind):
    callbacks, submitted, calls, reviews = {}, [], [], []
    original_button = ui.button

    def button(*args, **kwargs):
        element = original_button(*args, **kwargs)
        callbacks[args[0] if args else kwargs.get("text")] = kwargs.get("on_click")
        return element

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui, "timer", lambda *_, **__: None)
    monkeypatch.setattr(ui_research, "guard", lambda action: action)

    class Page(ui_research.ResearchPages):
        current_task = None

        def title(self, *_):
            pass

        def selection_dialog(self):
            pass

        def submit(self, kind, label, ids, worker, parameters):
            submitted.append((kind, deepcopy(ids), worker, deepcopy(parameters)))
            return {"id": "submitted-job"}

    def plan(goal, ids, **options):
        calls.append((deepcopy(ids), deepcopy(options)))
        return {"task": {"objective": goal}}

    def local_plan(goal, ids, **options):
        calls.append((deepcopy(ids), deepcopy(options)))
        return {"objective": goal}

    def parse(ids, options, **kwargs):
        calls.append((deepcopy(ids), deepcopy(options), kwargs))
        return {"status": "COMPLETED"}

    async def choose(library, ids):
        reviews.append(list(ids))
        assert not submitted and not calls
        return ["second"]

    monkeypatch.setattr(ui_catalog_sources, "choose_catalog_sources", choose)
    page = Page()
    page.ctx = SimpleNamespace(
        library=SimpleNamespace(selection=lambda: ["first", "second"], root=tmp_path),
        research=SimpleNamespace(
            parser_options=WorkbenchResearch.parser_options,
            versions=lambda *_, **__: [],
            parse=parse,
            plan=plan,
            local_plan=local_plan,
            configure_plan=lambda task, options, previous=None: {"task": task},
        ),
        settings=SettingsStore(tmp_path / "settings"),
        jobs=SimpleNamespace(list=lambda: []),
    )
    before = set(ui.context.client.elements)
    if page_kind == "parse":
        page.parse_dialog(["first", "second"])
    else:
        page.research_page()
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    if page_kind != "parse":
        next(
            element
            for element in elements
            if getattr(element, "label", "") == "科研目标（自然语言）"
        ).set_value("仅比较已选材料的催化剂")
        next(
            element
            for element in elements
            if getattr(element, "text", "").startswith("我授权仅将科研目标")
        ).set_value(True)
    return page, callbacks, submitted, calls, reviews


@pytest.mark.parametrize(
    ("kind", "button"),
    [
        ("parse", "开始解析"),
        ("local", "本地创建可编辑计划（零模型调用）"),
        ("remote", "授权自然语言规划"),
    ],
)
def test_new_actions_wait_for_source_review_before_any_worker(
    tmp_path, monkeypatch, kind, button
):
    page, callbacks, submitted, calls, reviews = mount(tmp_path, monkeypatch, kind)
    pending = callbacks[button]()
    assert not submitted and not calls
    asyncio.run(pending)
    assert reviews == [["first", "second"]]
    assert len(submitted) == 1 and submitted[0][1] == ["second"]
    assert not calls
    submitted[0][2](None)
    assert calls[0][0] == ["second"]
    if kind != "parse":
        assert submitted[0][3]["ids"] == ["second"]
    assert page.ctx.library.selection() == ["first", "second"]


@pytest.mark.parametrize(
    ("kind", "button"),
    [
        ("parse", "开始解析"),
        ("local", "本地创建可编辑计划（零模型调用）"),
        ("remote", "授权自然语言规划"),
    ],
)
def test_cancelled_source_review_creates_no_task_or_paid_call(
    tmp_path, monkeypatch, kind, button
):
    _, callbacks, submitted, calls, _ = mount(tmp_path, monkeypatch, kind)

    async def cancel(library, ids):
        return None

    monkeypatch.setattr(ui_catalog_sources, "choose_catalog_sources", cancel)
    asyncio.run(callbacks[button]())
    assert not submitted and not calls


def test_catalog_paper_search_selects_all_actual_hit_sources_and_keeps_evidence(
    tmp_path, monkeypatch
):
    original_button = ui.button
    callbacks, selections, exports = {}, [], []

    def button(*args, **kwargs):
        element = original_button(*args, **kwargs)
        callbacks[args[0] if args else kwargs.get("text")] = kwargs.get("on_click")
        return element

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui_research, "guard", lambda action: action)
    monkeypatch.setattr(ui, "notify", lambda *_, **__: None)
    rows = [
        {
            "id": identity,
            "title": "Same verified paper",
            "doi": "10.1039/d1cy02168k",
            "pdf_sha256": "a" * 64,
            "document_role": "ARTICLE",
            "identity_basis": "acquisition_verified",
            "integrity": "verified",
            "tags": [],
            "folder": "",
        }
        for identity in ("first", "second", "unhit")
    ]
    hits = [
        {
            "id": "hit-" + identity,
            "paper_id": identity,
            "number": index,
            "pages": [index],
            "text": "Exact quote " + identity,
            "source": {"title": "Same paper", "document_role": "ARTICLE"},
            "kind": "paragraph",
            "status": "PARSED",
        }
        for index, identity in enumerate(("first", "second"), 1)
    ]
    report = {
        "hits": hits,
        "coverage": {
            "searched_documents": 2,
            "completed": 2,
            "partial": 0,
            "unsearched": [],
        },
        "offset": 0,
        "returned_hits": 2,
        "total_hits": 2,
        "search_scope": {"ids": ["first", "second"]},
        "interpretation": "Keyword evidence only",
    }

    class Page(ui_research.ResearchPages):
        def title(self, *_):
            pass

        def output_links(self, result):
            pass

    async def io_bound(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    monkeypatch.setattr(run, "io_bound", io_bound)
    page = Page()
    page.ctx = SimpleNamespace(
        library=SimpleNamespace(
            scan=lambda **_: {"items": deepcopy(rows)},
            collections=lambda: {},
            set_selection=lambda ids, **_: selections.append(ids),
        ),
        research=SimpleNamespace(
            search=lambda *_, **__: deepcopy(report),
            export_evidence=lambda selected: exports.append(deepcopy(selected)) or {},
        ),
    )
    before = set(ui.context.client.elements)
    page.search_page()
    view = next(
        element
        for key, element in ui.context.client.elements.items()
        if key not in before and getattr(element, "label", "") == "展示方式"
    )
    view.set_value("论文视图")
    asyncio.run(callbacks["检索本地原文"]())
    table = next(
        element
        for key, element in ui.context.client.elements.items()
        if key not in before and isinstance(element, ui.table)
    )
    assert len(table.rows) == 1
    assert table.rows[0]["member_ids"] == ["first", "second"]
    table.selected = [table.rows[0]]
    callbacks["选择命中论文"]()
    callbacks["导出选中原文证据"]()
    assert selections == [["first", "second"]]
    assert exports == [hits] and page.search_report == report
    view.set_value("证据视图")
    evidence = next(
        element
        for key, element in ui.context.client.elements.items()
        if key not in before and isinstance(element, ui.table)
    )
    assert len(evidence.rows) == 2
    assert {row["id"] for row in evidence.rows} == {"hit-first", "hit-second"}
