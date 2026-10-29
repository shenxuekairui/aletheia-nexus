"""Selection presentation groups duplicates without expanding material scope."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest


def test_basket_removes_only_selected_sources_and_saves_exact_raw_ids(monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import core, ui

    from aletheia_nexus.workbench import ui as ui_module
    from aletheia_nexus.workbench.ui import WorkbenchUI

    common = {
        "title": "A selected paper",
        "doi": "10.1000/paper",
        "pdf_sha256": "a" * 64,
        "integrity": "verified",
        "document_role": "ARTICLE",
        "identity_basis": "acquisition_verified",
        "si_count": 0,
    }
    rows = [{**common, "id": name} for name in ("first", "second", "unselected")]
    selected, saved, calls = ["first", "second"], [], []

    def update(ids, mode="replace"):
        calls.append((list(ids), mode))
        selected[:] = [i for i in selected if i not in ids] if mode == "remove" else ids

    page = WorkbenchUI.__new__(WorkbenchUI)
    page.ctx = SimpleNamespace(
        library=SimpleNamespace(
            selection=lambda: list(selected),
            get=lambda identity: deepcopy(
                next(row for row in rows if row["id"] == identity)
            ),
            set_selection=update,
            save_collection=lambda name, ids: saved.append((name, list(ids))),
        )
    )
    monkeypatch.setattr(ui_module, "guard", lambda callback: callback)
    callbacks = []
    original = ui.button

    def button(*args, **kwargs):
        result = original(*args, **kwargs)
        callbacks.append((args, kwargs, result))
        return result

    monkeypatch.setattr(ui, "button", button)
    before = set(ui.context.client.elements)
    page.selection_dialog()
    elements = [
        value for key, value in ui.context.client.elements.items() if key not in before
    ]
    assert any("共 1 篇论文、2 份已选来源" in getattr(e, "text", "") for e in elements)
    save = next(kwargs for args, kwargs, _ in callbacks if args == ("保存集合",))
    next(
        e for e in elements if getattr(e, "label", "") == "保存为固定研究集合"
    ).set_value("研究")
    save["on_click"]()
    assert saved == [("研究", ["first", "second"])]
    remove = next(
        kwargs for args, kwargs, _ in callbacks if kwargs.get("icon") == "close"
    )

    async def remove_selected():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        remove["on_click"]()
        await asyncio.sleep(0)

    asyncio.run(remove_selected())
    assert calls == [(["first", "second"], "remove")]
    assert not selected
