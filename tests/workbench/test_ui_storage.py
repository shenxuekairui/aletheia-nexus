import asyncio

import pytest

pytest.importorskip("nicegui")
from nicegui import run, ui

from aletheia_nexus.storage_paths import PathPreferences
from aletheia_nexus.ui_cli import create_context
from aletheia_nexus.workbench import ui_storage


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    prefs = PathPreferences(tmp_path / "config")
    ctx = create_context(
        tmp_path / "library", tmp_path / "workspace", preferences=prefs
    )
    prefs.save(ctx.storage.paths)
    callbacks = []
    original = ui.button

    def button(text, **kwargs):
        element = original(text, **kwargs)
        callbacks.append((text, kwargs.get("on_click"), element))
        return element

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui_storage, "guard", lambda callback: callback)
    before = set(ui.context.client.elements)
    ui_storage.storage_dialog(ctx)
    yield ctx, callbacks, before
    ctx.jobs.close(wait=True)
    ctx.research.close()


def test_storage_page_shows_purposes_full_paths_and_open_actions(mounted, monkeypatch):
    ctx, callbacks, before = mounted
    labels = [
        getattr(element, "text", "")
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    assert "数据存储管理" in labels
    assert all(
        str(path) in labels for path in (ctx.root, ctx.workspace, ctx.library.state_dir)
    )
    opened = []
    monkeypatch.setattr(ui_storage, "open_folder", opened.append)
    for text, callback, _ in callbacks:
        if text == "打开文件夹":
            callback()
    assert opened == [ctx.root, ctx.library.state_dir, ctx.workspace]


@pytest.mark.parametrize("migrate", [True, False])
def test_visible_migration_options_perform_switch_and_show_new_location(
    mounted, tmp_path, monkeypatch, migrate
):
    ctx, callbacks, before = mounted
    (ctx.root / "paper.txt").write_text("research data")

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(run, "io_bound", inline)
    next(callback for text, callback, _ in callbacks if text == "修改位置")()
    controls = list(ui.context.client.elements.values())
    field = next(
        e for e in reversed(controls) if getattr(e, "label", "") == "新文件夹完整路径"
    )
    target = tmp_path / "chosen"
    field.set_value(str(target))
    action = "迁移现有数据并切换" if migrate else "使用新的空目录"
    callback = next(
        callback for text, callback, _ in reversed(callbacks) if text == action
    )
    asyncio.run(callback())
    assert ctx.storage.paths.library == target
    assert (target / "paper.txt").exists() is migrate
    assert (ctx.root / "paper.txt").is_file()
    assert any(
        getattr(element, "text", "") == str(target)
        for element in ui.context.client.elements.values()
    )
    assert all(
        not element.enabled for text, _, element in callbacks if text == "修改位置"
    )


def test_folder_picker_returns_selected_absolute_folder(tmp_path, monkeypatch):
    selected, callbacks = [], {}
    original = ui.button

    def button(text, **kwargs):
        callbacks[text] = kwargs.get("on_click")
        return original(text, **kwargs)

    monkeypatch.setattr(ui, "button", button)
    ui_storage.choose_folder(tmp_path, selected.append)
    callbacks["选择此文件夹"]()
    assert selected == [str(tmp_path)]
