import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("nicegui")

from nicegui import run, ui

from aletheia_nexus.workbench import ui_research
from aletheia_nexus.workbench.library import LibraryService


@pytest.mark.parametrize("leave_page", [False, True])
def test_search_does_not_duplicate_or_overwrite_newer_ui_state(
    tmp_path, monkeypatch, leave_page
):
    buttons = {}
    native_button = ui.button

    def capture(label, **kwargs):
        element = native_button(label, **kwargs)
        buttons[label] = (element, kwargs.get("on_click"))
        return element

    monkeypatch.setattr(ui, "button", capture)
    monkeypatch.setattr(ui_research, "guard", lambda callback: callback)

    class Page(ui_research.ResearchPages):
        def title(self, *args):
            pass

    page = Page()
    page.ctx = SimpleNamespace(
        library=LibraryService(tmp_path / "library"),
        research=SimpleNamespace(search=lambda *a, **k: None),
    )
    with ui.column() as parent:
        prior = set(parent.client.elements)
        page.search_page()
    elements = [
        value for key, value in parent.client.elements.items() if key not in prior
    ]
    query = next(
        e for e in elements if getattr(e, "label", None) == "关键词 / 带引号短语"
    )
    status = next(e for e in elements if getattr(e, "text", "").startswith("尚未检索"))
    query.set_value("first")

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def io_bound(*args, **kwargs):
            calls.append((args, kwargs))
            started.set()
            await release.wait()
            # An opaque result proves that the old response is never rendered.
            return {}

        monkeypatch.setattr(run, "io_bound", io_bound)
        button, callback = buttons["检索本地原文"]
        task = asyncio.create_task(callback())
        await asyncio.wait_for(started.wait(), 2)
        assert not button.enabled
        await callback()
        assert len(calls) == 1
        if leave_page:
            parent.delete()
        else:
            query.set_value("newer query")
        release.set()
        await task
        assert not hasattr(page, "search_report")
        if not leave_page:
            assert query.value == "newer query"
            assert "条件或材料选择已修改" in status.text
            assert button.enabled

    asyncio.run(scenario())
