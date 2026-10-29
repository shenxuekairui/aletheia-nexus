"""Grouped UI actions resolve exact raw IDs; display fallback is not provenance."""

import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench import ui_library
from aletheia_nexus.workbench.catalog_groups import catalog_groups
from aletheia_nexus.workbench.ui_home import home_catalog_counts
from aletheia_nexus.workbench.ui_library import (
    LibraryPage,
    library_table_row,
    marked_library_ids,
)

ui = pytest.importorskip("nicegui.ui")


def rows():
    base = {
        "doi": "10.1039/d1cy02168k",
        "pdf_sha256": "0" * 64,
        "integrity": "verified",
        "identity_basis": "acquisition_verified",
        "document_role": "ARTICLE",
        "title_original": "Original parent title",
        "title": "Original parent title",
        "tags": [],
        "collections": [],
        "year": 2022,
        "journal": "Catalysis Science &amp; Technology",
    }
    return [
        {
            **base,
            "id": "first",
            "pdf_path": "F:/local-synthetic/A/main.pdf",
            "folder": "A",
            "authors": [],
            "first_author": "",
            "parse_status": "PARSED",
            "si_count": 1,
            "attachments": [
                {
                    "id": "si-A",
                    "path": "F:/local-synthetic/A/SI/main.pdf",
                    "role": "SUPPLEMENT",
                    "parent_id": "first",
                }
            ],
        },
        {
            **base,
            "id": "second",
            "pdf_path": "F:/local-synthetic/B/copy.pdf",
            "folder": "B",
            "authors": ["Recorded author"],
            "first_author": "Recorded author",
            "parse_status": "FAILED",
            "si_count": 1,
            "attachments": [
                {
                    "id": "si-B",
                    "path": "F:/local-synthetic/B/SI/copy.pdf",
                    "role": "SUPPLEMENT",
                    "parent_id": "second",
                }
            ],
        },
    ]


def test_marking_one_paper_expands_only_server_matching_members_not_client_payload():
    catalogue = catalog_groups(rows())
    selected = [{"id": "first", "member_ids": ["forged"], "catalog_key": "untrusted"}]
    assert marked_library_ids(selected, catalogue) == ["first", "second"]
    filtered = catalog_groups(rows(), matching_ids=["first"])
    assert marked_library_ids(selected, filtered) == ["first"]
    with pytest.raises(ValueError, match="选择已过期"):
        marked_library_ids([{"id": filtered[0]["catalog_key"]}], filtered)


def test_display_authors_do_not_adopt_other_source_path_or_si_in_filtered_scope():
    raw = rows()
    group = catalog_groups(raw, matching_ids=["first"])[0]
    table = library_table_row(group, "Original parent title")
    assert (
        table["authors"] == "Recorded author"
        and table["field_sources"]["authors"] == "second"
    )
    assert table["path"] == raw[0]["pdf_path"] and table["si_count"] == 1
    assert table["attachments"] == raw[0]["attachments"]
    assert table["member_ids"] == ["first"]
    assert "2 条来源；本筛选 1 条" in table["title"]
    assert "variants" not in table and "matched_variants" not in table
    assert group["variants"][1]["attachments"][0]["parent_id"] == "second"


def test_full_group_table_lists_both_real_paths_and_separate_parse_statuses():
    raw = rows()
    table = library_table_row(catalog_groups(raw)[0], "Original parent title")
    assert table["path"].splitlines() == [row["pdf_path"] for row in raw]
    assert table["filename"].splitlines() == ["main.pdf", "copy.pdf"]
    # AG Grid infers this column from ordinary numeric rows. Group totals must
    # stay numeric too, for rendering and numeric sorting of a mixed library.
    assert table["si_count"] == 2 and type(table["si_count"]) is int
    assert "1" in table["parse_status"] and " · " in table["parse_status"]
    assert table["folder"] == "各来源分类目录不同，双击查看"
    assert (
        table["attachments"] == raw[0]["attachments"]
    )  # Never reparent the second SI.


def test_source_view_rows_do_not_expand_into_sibling_sources():
    individual = [catalog_groups([row])[0] for row in rows()]
    assert marked_library_ids([{"id": "first"}], individual) == ["first"]
    assert len(individual) == 2 and all(row["source_count"] == 1 for row in individual)


def test_grid_display_key_changes_with_scope_not_with_author_display():
    raw = rows()
    full = library_table_row(catalog_groups(raw)[0], "title")
    filtered = library_table_row(
        catalog_groups(raw, matching_ids=["first"])[0], "title"
    )
    assert full["id"] == filtered["id"] == "first"
    assert full["_view_row_key"] != filtered["_view_row_key"]
    raw[1]["authors"] = ["Updated author display"]
    assert (
        library_table_row(catalog_groups(raw)[0], "title")["_view_row_key"]
        == full["_view_row_key"]
    )


def test_home_counts_papers_and_exact_selected_source_members_separately():
    raw = rows()
    assert home_catalog_counts(raw) == {"papers": 1, "sources": 2}
    assert home_catalog_counts(raw, ["first"]) == {"papers": 1, "sources": 1}
    assert home_catalog_counts(raw, []) == {"papers": 0, "sources": 0}
    raw[1]["pdf_sha256"] = "1" * 64
    assert home_catalog_counts(raw) == {"papers": 2, "sources": 2}


def created_elements(render):
    prior = set(ui.context.client.elements)
    render()
    return [
        element
        for key, element in ui.context.client.elements.items()
        if key not in prior
    ]


def click(elements, text):
    button = next(
        element for element in elements if getattr(element, "text", None) == text
    )
    callback = next(
        item.handler
        for item in button._event_listeners.values()
        if item.type == "click"
    )
    return callback(None)


def test_catalogue_details_show_each_source_and_do_not_broaden_organize_scope(
    monkeypatch,
):
    # Run the actual source callbacks synchronously, rather than NiceGUI's
    # guarded background-event scheduler (which requires a connected client).
    monkeypatch.setattr(ui_library, "guard", lambda callback: callback)
    calls = []

    class Page(LibraryPage):
        def details_dialog(self, identity):
            calls.append(("details", identity))

        def organize_dialog(self, identities):
            calls.append(("organize", identities))

    raw = rows()
    before = deepcopy(raw)
    page = Page()
    group = catalog_groups(raw, matching_ids=["first"])[0]
    elements = created_elements(lambda: page.catalog_details_dialog(group))
    texts = [getattr(element, "text", "") for element in elements]
    assert any("2 条独立来源" in text and "包含 1 条" in text for text in texts)
    assert any("作者列表来自来源 2" in text for text in texts)
    assert any("main.pdf" in text for text in texts) and any(
        "copy.pdf" in text for text in texts
    )
    assert not calls and raw == before
    click(elements, "整理本次筛选的 1 条来源")
    assert calls == [("organize", ["first"])]


def test_catalogue_details_open_second_original_identity_not_representative(
    monkeypatch,
):
    monkeypatch.setattr(ui_library, "guard", lambda callback: callback)
    opened = []

    class Page(LibraryPage):
        def details_dialog(self, identity):
            opened.append(identity)

    elements = created_elements(
        lambda: Page().catalog_details_dialog(catalog_groups(rows())[0])
    )
    buttons = [
        element
        for element in elements
        if getattr(element, "text", None) == "查看 / 编辑此来源及其 SI"
    ]
    callback = next(
        item.handler
        for item in buttons[1]._event_listeners.values()
        if item.type == "click"
    )
    callback(None)
    assert opened == ["second"]


def test_source_view_toggle_persists_only_display_preference_and_refreshes():
    tree = ast.parse(Path(ui_library.__file__).read_text("utf-8"))
    callback = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "change_source_view"
    )
    changes, refreshed = [], []
    controller = SimpleNamespace(
        ctx=SimpleNamespace(
            settings=SimpleNamespace(set=lambda *args: changes.append(args))
        )
    )

    async def refresh():
        refreshed.append(True)

    namespace = {
        "self": controller,
        "refresh": refresh,
        "source_view": SimpleNamespace(value=True),
    }
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
    asyncio.run(namespace["change_source_view"]())
    assert controller.library_source_view is True
    assert changes == [("library_source_view", True)] and refreshed == [True]
