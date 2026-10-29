"""A grid action keeps its exact scope without replacing the cross-page tray."""

import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench import ui_library
from aletheia_nexus.workbench.ui_library import marked_library_ids


def library_callback(name, namespace):
    tree = ast.parse(Path(ui_library.__file__).read_text(encoding="utf-8"))
    page = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "library_page"
    )
    callback = next(
        node
        for node in ast.walk(page)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(body=[deepcopy(callback)], type_ignores=[])
            ),
            ui_library.__file__,
            "exec",
        ),
        namespace,
    )
    return namespace[name]


@pytest.mark.parametrize(
    "action", ["parse_marked", "search_marked", "translate_marked"]
)
def test_direct_grid_action_uses_stable_ids_and_preserves_existing_tray(action):
    async def scenario():
        selected = [
            {"id": "b", "pdf_path": "untrusted-client-path"},
            {"id": "a"},
            {"id": "b"},
        ]
        opened, navigated = [], []
        tray = ["older-paper"]

        async def get_selected_rows():
            return selected

        controller = SimpleNamespace(
            library_rows=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
            parse_dialog=opened.append,
            title_translation_dialog=opened.append,
            navigate=navigated.append,
            ctx=SimpleNamespace(
                library=SimpleNamespace(
                    selection=lambda: list(tray),
                    set_selection=lambda *_args, **_kwargs: pytest.fail(
                        "A direct action must not replace or broaden the global tray"
                    ),
                )
            ),
        )
        callback = library_callback(
            action,
            {
                "self": controller,
                "grid": SimpleNamespace(get_selected_rows=get_selected_rows),
                "marked_library_ids": marked_library_ids,
            },
        )
        await callback()
        assert tray == ["older-paper"]
        if action in {"parse_marked", "translate_marked"}:
            assert opened == [["b", "a"]] and navigated == []
        else:
            assert navigated == ["科研检索"] and opened == []
            assert controller.search_handoff["ids"] == ["b", "a"]
            selected.clear()
            assert controller.search_handoff["ids"] == ["b", "a"]

    asyncio.run(scenario())


@pytest.mark.parametrize("selected", [[], [{"id": "stale"}], [{"title": "missing ID"}]])
@pytest.mark.parametrize(
    "action", ["parse_marked", "search_marked", "organize_marked", "translate_marked"]
)
def test_empty_or_stale_grid_selection_cannot_process_other_materials(selected, action):
    async def scenario():
        async def get_selected_rows():
            return selected

        controller = SimpleNamespace(
            library_rows=[{"id": "a"}],
            parse_dialog=lambda *_: pytest.fail("Unexpected parse"),
            organize_dialog=lambda *_: pytest.fail("Unexpected file operation"),
            title_translation_dialog=lambda *_: pytest.fail("Unexpected translation"),
            navigate=lambda *_: pytest.fail("Unexpected navigation"),
        )
        callback = library_callback(
            action,
            {
                "self": controller,
                "grid": SimpleNamespace(get_selected_rows=get_selected_rows),
                "marked_library_ids": marked_library_ids,
            },
        )
        with pytest.raises(ValueError):
            await callback()
        assert not hasattr(controller, "search_handoff")

    asyncio.run(scenario())


def test_clear_filters_resets_saved_conditions_and_refreshes_without_touching_view_or_tray():
    async def scenario():
        refreshed = []

        class Control:
            value = "old"

            def set_value(self, value):
                self.value = value

        controls = {
            key: Control()
            for key in (
                "query",
                "folder",
                "tag",
                "tag_mode",
                "untranslated",
                "parsed",
                "collection",
                "saved",
            )
        }
        controller = SimpleNamespace(active_view="自定义视图", tray=["older-paper"])

        async def refresh():
            refreshed.append(
                {name: control.value for name, control in controls.items()}
            )

        await library_callback(
            "clear_filters", {"self": controller, "refresh": refresh, **controls}
        )()
        assert refreshed == [
            {
                "query": "",
                "folder": "",
                "tag": [],
                "tag_mode": "AND",
                "untranslated": False,
                "parsed": "",
                "collection": "",
                "saved": "",
            }
        ]
        assert controller.active_view == "自定义视图" and controller.tray == [
            "older-paper"
        ]

    asyncio.run(scenario())


def test_refresh_updates_only_rows_and_keeps_checks_and_column_layout():
    async def scenario():
        source_rows = [
            {
                "id": paper_id,
                "title": paper_id,
                "pdf_path": paper_id + ".pdf",
                "tags": [],
                "authors": [],
                "collections": [],
                "journal": "Catalysis Science &amp; Technology"
                if paper_id == "a"
                else "Journal &lt;Example&gt;",
            }
            for paper_id in ["a", "b"]
        ]
        report = {"items": source_rows, "warnings": []}
        selected = ["a"]
        layout = {"title": {"width": 480, "sort": "desc"}}
        updates = []

        class ObservableOptions(dict):
            def __setitem__(self, key, value):
                pytest.fail("Mutating observable options also rebuilds the grid")

        options = ObservableOptions({"rowData": [{"id": "old-server-snapshot"}]})

        async def run_grid_method(method, name, rows):
            assert method == "setGridOption" and name == "rowData"
            updates.append(rows)
            # AG Grid uses getRowId to keep the selected identities on rowData update.
            selected[:] = [pid for pid in selected if any(r["id"] == pid for r in rows)]

        class Area:
            def clear(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        class Label:
            def classes(self, *_):
                return self

        controller = SimpleNamespace(
            ctx=SimpleNamespace(
                library=SimpleNamespace(
                    scan=lambda **_: report, selection=lambda: ["older-paper"]
                )
            )
        )

        async def io_bound(function, **options):
            return function(**options)

        async def marked_count():
            assert selected == ["a"]

        callback = library_callback(
            "refresh",
            {
                "self": controller,
                "filters": lambda: {"query": None},
                "run": SimpleNamespace(io_bound=io_bound),
                "grid": SimpleNamespace(
                    options=options,
                    run_grid_method=run_grid_method,
                    update=lambda: pytest.fail(
                        "Rebuilding the grid loses checks/layout"
                    ),
                ),
                "title_for": lambda r: r["title"],
                "value_label": ui_library.value_label,
                "INTEGRITY_LABELS": ui_library.INTEGRITY_LABELS,
                "count": SimpleNamespace(set_text=lambda _: None),
                "diagnostic_area": Area(),
                "ui": SimpleNamespace(label=lambda _: Label()),
                "show_marked_count": marked_count,
            },
        )
        await callback()
        assert controller.library_rows == source_rows and len(updates) == 1
        assert [row["journal"] for row in updates[0]] == [
            "Catalysis Science & Technology",
            "Journal <Example>",
        ]
        assert [row["journal"] for row in source_rows] == [
            "Catalysis Science &amp; Technology",
            "Journal &lt;Example&gt;",
        ]
        assert options["rowData"] == [{"id": "old-server-snapshot"}]
        assert selected == ["a"] and layout == {"title": {"width": 480, "sort": "desc"}}

    asyncio.run(scenario())


def test_an_old_background_refresh_cannot_replace_newer_filter_results():
    async def scenario():
        controller = SimpleNamespace(
            library_rows=[{"id": "current"}],
            ctx=SimpleNamespace(library=SimpleNamespace(scan=lambda **_: None)),
        )

        async def io_bound(_function, **_options):
            controller.library_filters = {"query": "newer"}
            return {"items": [{"id": "old"}], "warnings": []}

        await library_callback(
            "refresh",
            {
                "self": controller,
                "filters": lambda: {"query": "older"},
                "run": SimpleNamespace(io_bound=io_bound),
            },
        )()
        assert controller.library_rows == [{"id": "current"}]

    asyncio.run(scenario())
