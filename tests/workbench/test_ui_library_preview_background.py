"""Filesystem provenance audits must not block NiceGUI's websocket heartbeat."""

import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench import ui_library


def callback(name, namespace):
    tree = ast.parse(Path(ui_library.__file__).read_text(encoding="utf-8"))
    organize = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "organize_dialog"
    )
    function = next(
        node
        for node in ast.walk(organize)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )
    # Exercise the actual nested event callback without creating a UI or socket.
    module = ast.Module(body=[deepcopy(function)], type_ignores=[])
    exec(
        compile(ast.fix_missing_locations(module), ui_library.__file__, "exec"),
        namespace,
    )
    return namespace[name]


@pytest.mark.parametrize("name", ["preview", "regenerate"])
def test_preview_keeps_event_loop_responsive_and_snapshots_options(name):
    async def scenario():
        loop_thread = get_ident()
        release = Event()
        calls, shown, messages = [], [], []

        def provenance_audit(ids, template, **options):
            assert get_ident() != loop_thread
            calls.append((ids, template, options))
            assert release.wait(2), "The UI heartbeat must run during the audit"
            return {"executable": 1, "skipped": 0, "items": []}

        async def io_bound(function, *args, **kwargs):
            return await asyncio.to_thread(function, *args, **kwargs)

        async def edited(_):
            await asyncio.sleep(0)
            return [{"id": "paper", "enabled": True, "final_stem": "中文标题"}]

        namespace = {
            "run": SimpleNamespace(io_bound=io_bound),
            "self": SimpleNamespace(
                ctx=SimpleNamespace(
                    library=SimpleNamespace(preview_rename=provenance_audit)
                )
            ),
            "ids": ["paper"],
            "state": {"grid": object()},
            "template": SimpleNamespace(value="{year}-{title_zh}"),
            "target_mode": SimpleNamespace(value="category"),
            "folder": SimpleNamespace(value="甲酸盐研究/长期积累"),
            "missing": SimpleNamespace(value="fallback"),
            "target_options": lambda: {"folder": "甲酸盐研究/长期积累"},
            "status": SimpleNamespace(set_text=messages.append),
            "display_preview": shown.append,
            "read_edited_grid": edited,
        }
        action = callback(name, namespace)

        async def heartbeat():
            await asyncio.sleep(0.01)
            release.set()

        await asyncio.gather(action(), heartbeat())
        assert calls[0][:2] == (["paper"], "{year}-{title_zh}")
        assert calls[0][2]["folder"] == "甲酸盐研究/长期积累"
        assert calls[0][2]["missing_translation"] == "fallback"
        if name == "regenerate":
            assert calls[0][2]["overrides"] == {"paper": "中文标题"}
        assert shown == [{"executable": 1, "skipped": 0, "items": []}]
        assert "后台" in messages[0]
        assert namespace["state"]["preview_form"] == (
            "{year}-{title_zh}",
            "category",
            "甲酸盐研究/长期积累",
            "fallback",
        )

    asyncio.run(scenario())


def test_background_preview_failure_propagates_to_visible_error_guard():
    async def scenario():
        def audit(*_, **__):
            raise ValueError("legacy explicit references require review")

        async def io_bound(function, *args, **kwargs):
            return await asyncio.to_thread(function, *args, **kwargs)

        namespace = {
            "run": SimpleNamespace(io_bound=io_bound),
            "self": SimpleNamespace(
                ctx=SimpleNamespace(library=SimpleNamespace(preview_rename=audit))
            ),
            "ids": ["paper"],
            "state": {},
            "template": SimpleNamespace(value="中文标题"),
            "target_mode": SimpleNamespace(value="keep"),
            "folder": SimpleNamespace(value=""),
            "missing": SimpleNamespace(value="fallback"),
            "target_options": lambda: {},
            "status": SimpleNamespace(set_text=lambda _: None),
            "display_preview": lambda _: pytest.fail(
                "A failed audit cannot display success"
            ),
        }
        with pytest.raises(ValueError, match="legacy explicit references"):
            await callback("preview", namespace)()

    asyncio.run(scenario())
