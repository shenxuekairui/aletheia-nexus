"""Actual organization controls share one paid request; transport is entirely fake."""

import asyncio
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfWriter

pytest.importorskip("nicegui")

from nicegui import ui

from aletheia_nexus.workbench import ui_library
from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.translation import TranslationService
from aletheia_nexus.workbench.ui import WorkbenchUI


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-organization-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    source = tmp_path / "synthetic.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with source.open("wb") as handle:
        writer.write(handle)
    library = LibraryService(tmp_path / "library")
    paper = library.import_pdf(
        source, title="Synthetic title for duplicate request tests"
    )
    original_files = {
        Path(paper[key]): Path(paper[key]).read_bytes()
        for key in ("pdf_path", "sidecar_path")
    }
    entered, release = Event(), Event()
    http_calls, callbacks, ticks = [], {}, []

    def handler(request):
        http_calls.append(request)
        entered.set()
        assert release.wait(5)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 60},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "translations": [
                                            {
                                                "id": paper["id"],
                                                "title": "用于重复请求测试的合成题目",
                                            }
                                        ],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    manager = TaskManager(tmp_path / "workspace")
    translation = TranslationService(
        library, tmp_path / "workspace", transport=httpx.MockTransport(handler)
    )
    original_button = ui.button

    def button(text, **kwargs):
        result = original_button(text, **kwargs)
        callbacks[text] = kwargs.get("on_click"), result
        return result

    def timer(_, callback, **kwargs):
        ticks.append(callback)
        return SimpleNamespace(active=True)

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui, "timer", timer)
    monkeypatch.setattr(ui, "notify", lambda *a, **k: None)
    monkeypatch.setattr(ui_library, "guard", lambda callback: callback)
    page = WorkbenchUI.__new__(WorkbenchUI)
    page.ctx = SimpleNamespace(
        library=library,
        translation=translation,
        jobs=manager,
        settings=SettingsStore(tmp_path / "workspace"),
    )
    client = ui.context.client
    before = set(client.elements)

    def open_dialog():
        page.organize_dialog([paper["id"]])

    open_dialog()

    def elements():
        return [
            element
            for key, element in client.elements.items()
            if key not in before and not element.is_deleted
        ]

    def consent():
        return next(
            element
            for element in reversed(elements())
            if isinstance(element, ui.checkbox)
            and element.text.startswith("我授权将本批")
        )

    def missing():
        return next(
            element
            for element in reversed(elements())
            if getattr(element, "label", None) == "缺失中文译名策略"
        )

    async def preview():
        # guard is intentionally bypassed to surface test exceptions, so restore
        # the actual client's event context when entering a new asyncio task.
        with client.layout:
            return await callbacks["生成完整预览"][0]()

    try:
        yield SimpleNamespace(
            page=page,
            paper=paper,
            callbacks=callbacks,
            ticks=ticks,
            elements=elements,
            manager=manager,
            http_calls=http_calls,
            entered=entered,
            release=release,
            consent=consent,
            missing=missing,
            preview=preview,
            open_dialog=open_dialog,
        )
    finally:
        release.set()
        manager.close(wait=True)
        assert all(path.read_bytes() == raw for path, raw in original_files.items())


@pytest.mark.parametrize("first", ["translation", "preview"])
def test_two_entry_points_and_rapid_clicks_create_one_task_and_one_mock_http(
    mounted, first
):
    view = mounted
    view.consent().set_value(True)
    view.missing().set_value("translate")

    def translate():
        view.callbacks["仅翻译标题"][0]()

    def preview():
        asyncio.run(view.preview())

    (translate if first == "translation" else preview)()
    assert view.entered.wait(3)
    translate()
    preview()
    translate()
    assert len(view.manager.list()) == len(view.http_calls) == 1
    assert not view.callbacks["仅翻译标题"][1].enabled
    assert not view.callbacks["生成完整预览"][1].enabled
    view.release.set()
    job = view.manager.list()[0]
    view.manager._futures[job["id"]].result(timeout=5)
    view.ticks[-1]()
    assert view.callbacks["仅翻译标题"][1].enabled
    assert view.callbacks["生成完整预览"][1].enabled
    assert len(view.manager.list()) == 1  # Timer never automatically retries.
    translate()  # An explicit terminal action may reuse the completed cache.
    latest = view.manager.list()[0]
    view.manager._futures[latest["id"]].result(timeout=5)
    assert len(view.manager.list()) == 2 and len(view.http_calls) == 1


def test_submit_failure_unlocks_both_actions_for_explicit_retry(mounted, monkeypatch):
    view = mounted
    original = view.page.submit
    attempts = []

    def submit(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("合成提交失败")
        return original(*args, **kwargs)

    monkeypatch.setattr(view.page, "submit", submit)
    view.consent().set_value(True)
    with pytest.raises(ValueError, match="合成提交失败"):
        view.callbacks["仅翻译标题"][0]()
    assert view.callbacks["仅翻译标题"][1].enabled
    assert view.callbacks["生成完整预览"][1].enabled
    assert not view.manager.list() and not view.http_calls
    view.callbacks["仅翻译标题"][0]()
    assert view.entered.wait(3)
    assert len(view.manager.list()) == len(view.http_calls) == 1


def test_reopened_dialog_attaches_identical_active_scope_without_another_request(
    mounted,
):
    view = mounted
    view.consent().set_value(True)
    view.callbacks["仅翻译标题"][0]()
    assert view.entered.wait(3)
    view.open_dialog()
    view.consent().set_value(True)
    view.missing().set_value("translate")
    asyncio.run(view.preview())
    assert len(view.manager.list()) == len(view.http_calls) == 1
    assert any(
        "已关联其进度" in getattr(element, "text", "") for element in view.elements()
    )
    view.release.set()
    view.manager._futures[view.manager.list()[0]["id"]].result(timeout=5)
    view.ticks[-1]()
    assert any(
        "重新生成完整预览" in getattr(element, "text", "")
        for element in view.elements()
    )


def test_existing_or_new_folder_picker_only_changes_the_explicit_move_target(
    mounted, monkeypatch
):
    from aletheia_nexus.workbench import ui_folders

    view = mounted
    selected = []
    monkeypatch.setattr(
        ui_folders,
        "choose_library_folder",
        lambda library, callback, initial="": selected.append(callback),
    )
    mode = next(
        element
        for element in view.elements()
        if getattr(element, "label", None) == "分类移动目标"
    )
    folder = next(
        element
        for element in view.elements()
        if getattr(element, "label", None) == "目标分类（相对文库根目录）"
    )
    mode.set_value("category")
    view.callbacks["选择已有 / 新建分类"][0]()
    selected[-1]("已有分类/新子分类")
    assert mode.value == "category" and folder.value == "已有分类/新子分类"
    selected[-1]("")
    assert mode.value == "root" and folder.value == ""
    assert not view.manager.list() and not view.http_calls
