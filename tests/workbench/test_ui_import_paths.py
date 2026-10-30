"""The real path-import controls reject blank input and recover without duplicate jobs."""

import asyncio
import inspect
import sys
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

pytest.importorskip("nicegui")

from nicegui import run, ui

from aletheia_nexus.workbench import ui_library


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    callbacks, submitted, workers, chooser_calls = {}, [], [], []
    original_button = ui.button

    def capture(*args, **kwargs):
        element = original_button(*args, **kwargs)
        callbacks[args[0] if args else kwargs.get("text")] = kwargs.get("on_click")
        return element

    class MinimalPage(ui_library.LibraryPage):
        def tag_input(self, _label, *_args, **_kwargs):
            return SimpleNamespace(value=[])

        def title_translation_controls(self):
            return lambda: {"enabled": False, "options": {}}

        def import_worker(self, paths, **options):
            workers.append((list(paths), deepcopy(options)))
            return "fixture worker; never executed"

        def submit(self, kind, label, ids, worker, parameters):
            submitted.append(
                {
                    "kind": kind,
                    "label": label,
                    "ids": list(ids),
                    "worker": worker,
                    "parameters": deepcopy(parameters),
                }
            )
            return {"id": f"fixture_job_{len(submitted)}", "status": "QUEUED"}

    async def io_bound(callback, *args, **kwargs):
        return await asyncio.to_thread(callback, *args, **kwargs)

    monkeypatch.setattr(ui, "button", capture)
    monkeypatch.setattr(ui_library, "guard", lambda callback: callback)
    monkeypatch.setattr(run, "io_bound", io_bound)

    def choose_import_folder(on_select, initial=""):
        chooser_calls.append({"on_select": on_select, "initial": initial})

    monkeypatch.setitem(
        sys.modules,
        "aletheia_nexus.workbench.ui_import_folders",
        SimpleNamespace(choose_import_folder=choose_import_folder),
    )
    page = MinimalPage()
    page.ctx = SimpleNamespace(workspace=tmp_path, library=SimpleNamespace())
    before = set(ui.context.client.elements)
    page.import_dialog()
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    path = next(
        element
        for element in elements
        if getattr(element, "label", None) == "本地 PDF 或文件夹完整路径（必填）"
    )
    button = next(
        element for element in elements if getattr(element, "text", "") == "开始导入"
    )
    recursive = next(
        element
        for element in elements
        if getattr(element, "text", "") == "包含子目录中的 PDF"
    )
    # The path action owns this initially empty status label, not a fabricated
    # notification in the stub controller.
    status = next(
        element
        for element in elements
        if isinstance(element, ui.label) and element.text == ""
    )
    incoming = tmp_path / "合成输入.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(incoming)
    return SimpleNamespace(
        path=path,
        button=button,
        recursive=recursive,
        status=status,
        action=callbacks["开始导入"],
        incoming=incoming,
        submitted=submitted,
        workers=workers,
        chooser_calls=chooser_calls,
        callbacks=callbacks,
        elements=elements,
    )


def test_blank_path_button_is_disabled_and_text_is_required_before_enable(mounted):
    fixture = mounted
    assert fixture.path.value == "" and not fixture.button.enabled
    fixture.path.set_value("   ")
    assert not fixture.button.enabled
    fixture.path.set_value(str(fixture.incoming))
    assert fixture.button.enabled
    fixture.path.set_value("")
    assert not fixture.button.enabled and not fixture.submitted
    # Disabled controls can still receive an already queued event; blank input
    # must not become Path('.') and accidentally import the current directory.
    with pytest.raises(ValueError, match="请先填写"):
        asyncio.run(fixture.action())
    assert "尚未导入" in fixture.status.text
    assert not fixture.button.enabled and not fixture.submitted


def test_failed_path_import_shows_not_imported_and_unlocks_for_a_correct_retry(mounted):
    fixture = mounted
    fixture.path.set_value(str(fixture.incoming.parent / "不存在.pdf"))
    with pytest.raises(ValueError, match="路径不存在"):
        asyncio.run(fixture.action())
    assert not fixture.submitted and not fixture.workers
    assert "尚未导入" in fixture.status.text
    assert fixture.button.enabled
    fixture.path.set_value(str(fixture.incoming))
    asyncio.run(fixture.action())
    assert len(fixture.submitted) == 1
    assert fixture.status.text == "已加入任务中心：1 份 PDF"
    assert fixture.button.enabled


def test_correct_pdf_submits_one_import_job_without_touching_the_source(mounted):
    fixture = mounted
    fingerprint = sha256(fixture.incoming.read_bytes()).hexdigest()
    fixture.path.set_value(str(fixture.incoming))
    asyncio.run(fixture.action())
    assert len(fixture.submitted) == len(fixture.workers) == 1
    assert fixture.submitted[0]["kind"] == "import"
    assert fixture.submitted[0]["ids"] == [str(fixture.incoming.resolve())]
    assert fixture.workers[0][0] == [fixture.incoming.resolve()]
    assert fixture.workers[0][1]["translation"]["enabled"] is False
    assert sha256(fixture.incoming.read_bytes()).hexdigest() == fingerprint


def test_reentrant_path_click_during_async_inspection_cannot_queue_a_second_job(
    mounted, monkeypatch
):
    fixture = mounted
    fixture.path.set_value(str(fixture.incoming))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        checks = []

        async def delayed_inspection(callback, *args, **kwargs):
            checks.append((args, kwargs))
            entered.set()
            await release.wait()
            return callback(*args, **kwargs)

        monkeypatch.setattr(run, "io_bound", delayed_inspection)
        first = asyncio.create_task(fixture.action())
        await asyncio.wait_for(entered.wait(), 2)
        assert not fixture.button.enabled
        assert fixture.status.text == "正在检查路径中的 PDF…"
        await fixture.action()  # A queued click can arrive despite a disabled button.
        assert len(checks) == 1 and not fixture.submitted
        release.set()
        await first
        assert len(fixture.submitted) == len(fixture.workers) == 1
        assert fixture.button.enabled

    asyncio.run(scenario())


def test_computer_folder_picker_fills_source_and_expands_without_importing_or_changing_category(
    mounted,
):
    fixture = mounted
    target = next(
        element
        for element in fixture.elements
        if getattr(element, "label", None) == "目标分类（留空为文库根目录）"
    )
    target.set_value("现有分类/不要改变")
    path_section = next(
        element for element in fixture.elements if isinstance(element, ui.expansion)
    )
    chooser_button = next(
        element
        for element in fixture.elements
        if getattr(element, "text", "") == "从电脑选择文件夹"
    )
    assert not path_section.value and not fixture.button.enabled
    slot = chooser_button.parent_slot
    while slot:
        assert (
            slot.parent is not path_section
        )  # The chooser must remain visible when collapsed.
        slot = slot.parent.parent_slot
    selected = str(fixture.incoming.parent)
    result = fixture.callbacks["从电脑选择文件夹"]()
    if inspect.isawaitable(result):
        asyncio.run(result)
    assert len(fixture.chooser_calls) == 1
    result = fixture.chooser_calls[0]["on_select"](selected)
    if inspect.isawaitable(result):
        asyncio.run(result)
    assert fixture.path.value == selected
    assert path_section.value and fixture.button.enabled
    assert target.value == "现有分类/不要改变"
    assert not fixture.recursive.value
    assert not fixture.submitted and not fixture.workers
