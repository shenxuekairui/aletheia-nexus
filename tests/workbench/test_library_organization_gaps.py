import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_common import split_tags
from aletheia_nexus.workbench.ui_library import (
    SELECTION_COLUMN,
    library_columns,
    metadata_column_state,
    view_title,
)


def add_paper(library, directory, name, width=200):
    path = directory / (name + ".pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=300)
    with path.open("wb") as output:
        writer.write(output)
    return library.import_pdf(path, title=name, folder="化学/羧酸")


def test_explicit_root_move_keeps_shared_si_and_can_restore_category(tmp_path):
    library = LibraryService(tmp_path / "library")
    paper = add_paper(library, tmp_path, "main")
    attachment = tmp_path / "data.csv"
    attachment.write_text("name,value\na,1\n", encoding="utf-8")
    si = library.import_attachment(paper["id"], attachment)
    original_hashes = {
        "pdf": sha256_file(Path(paper["pdf_path"])),
        "source": sha256_file(Path(paper["sidecar_path"])),
        "si": sha256_file(Path(si["path"])),
    }
    # Existing callers using None or '' keep their original semantics.
    for value in (None, ""):
        assert library.preview_rename([paper["id"]], "renamed", folder=value)["items"][
            0
        ]["new_path"] == str(library.root / "化学/羧酸/renamed.pdf")
    with pytest.raises(ValueError, match="移动目标冲突"):
        library.preview_rename(
            [paper["id"]], "renamed", folder="other", move_to_root=True
        )
    preview = library.preview_rename([paper["id"]], "中文正文", move_to_root=True)
    assert preview["items"][0]["new_path"] == str(library.root / "中文正文.pdf")
    assert preview["items"][0]["si_directory"] == str(library.root / "SI")
    operation = library.execute_rename(preview)
    assert operation["status"] == "COMPLETED"
    current = library.get(paper["id"])
    assert current["folder"] == ""
    assert Path(current["attachments"][0]["path"]).parent == library.root / "SI"
    assert sha256_file(Path(current["pdf_path"])) == original_hashes["pdf"]
    assert sha256_file(Path(current["sidecar_path"])) == original_hashes["source"]
    assert sha256_file(Path(current["attachments"][0]["path"])) == original_hashes["si"]
    assert library.rollback(operation["id"])["status"] == "ROLLED_BACK"
    assert library.get(paper["id"])["folder"] == "化学/羧酸"


def test_parse_status_filter_can_be_saved_reopened_and_keeps_bool_compatibility(
    tmp_path,
):
    library = LibraryService(tmp_path / "library")
    ids = {}
    for index, status in enumerate(("PARSED", "PARTIAL", "FAILED", "UNPARSED")):
        row = add_paper(library, tmp_path, status, 200 + index)
        library.update_metadata(row["id"], parse_status=status)
        ids[status] = row["id"]
    library.save_filter("解析失败待重试", {"parsed": "FAILED"})
    again = LibraryService(library.root)
    assert [
        r["id"] for r in again.scan(**again.filters()["解析失败待重试"])["items"]
    ] == [ids["FAILED"]]
    assert {r["id"] for r in again.scan(parsed=True)["items"]} == {
        ids["PARSED"],
        ids["PARTIAL"],
    }
    assert {r["id"] for r in again.scan(parsed=False)["items"]} == {
        ids["FAILED"],
        ids["UNPARSED"],
    }
    assert again.scan(parsed="PARTIAL")["items"][0]["id"] == ids["PARTIAL"]


def test_scenario_ten_view_never_hides_selection_control():
    visible = [
        "title_original",
        "title_zh",
        "authors",
        "journal",
        "tags",
        "si_count",
        "parse_status",
    ]
    columns = library_columns(visible)
    controls = [c for c in columns if c.get("checkboxSelection")]
    assert len(controls) == 1
    assert controls[0]["colId"] == SELECTION_COLUMN and controls[0]["lockVisible"]
    assert controls[0]["headerCheckboxSelectionCurrentPageOnly"]
    assert next(c for c in columns if c.get("field") == "title")["hide"]
    # A stale/manually edited saved view cannot hide the selection control.
    saved = [
        {"colId": SELECTION_COLUMN, "hide": True},
        {"colId": "title_original", "width": 321},
    ]
    assert metadata_column_state(saved) == [{"colId": "title_original", "width": 321}]
    assert next(c for c in columns if c.get("field") == "title_original")["wrapText"]


def test_tag_selection_accepts_existing_and_new_values_without_breaking_text_import():
    assert split_tags(["已有标签", "新标签", "已有标签", "追加一，追加二"]) == [
        "已有标签",
        "新标签",
        "追加一",
        "追加二",
    ]
    assert split_tags("已有标签, 新标签;保留分号") == ["已有标签", "新标签;保留分号"]
    assert split_tags(None) == []
    with pytest.raises(ValueError, match="标签"):
        split_tags(["合法", 42])


def test_file_operations_show_newest_creation_time_instead_of_random_id(tmp_path):
    library = LibraryService(tmp_path / "library")
    directory = library.state_dir / "operations"
    directory.mkdir()
    for operation_id, created in (
        ("rename_zzold", "2020-01-01T00:00:00+00:00"),
        ("rename_aanew", "2026-10-28T00:00:00+00:00"),
    ):
        (directory / (operation_id + ".json")).write_text(
            json.dumps(
                {
                    "id": operation_id,
                    "status": "COMPLETED",
                    "created_at": created,
                    "root": str(library.root),
                }
            ),
            encoding="utf-8",
        )
    assert [op["id"] for op in library.operations()] == ["rename_aanew", "rename_zzold"]


def test_named_views_restore_their_title_preference_independently(tmp_path):
    library = LibraryService(tmp_path / "library")
    row = {
        "title_original": "Original title",
        "title_zh": "中文译名",
        "custom_name": "短名称",
    }
    library.save_view(
        "双语阅读", {"columns": ["title"], "title_mode": "bilingual", "wrap": True}
    )
    library.save_view(
        "整理文件",
        {"columns": ["title", "filename"], "title_mode": "custom", "wrap": False},
    )
    reopened = LibraryService(library.root)
    assert (
        view_title(row, reopened.views()["双语阅读"], default_mode="original")
        == "中文译名\nOriginal title"
    )
    assert (
        view_title(row, reopened.views()["整理文件"], default_mode="original")
        == "短名称"
    )
    assert view_title(row, {"title_mode": "zh"}) == "中文译名"
    assert view_title(row, {"title_mode": "original"}) == "Original title"
    assert view_title(row, {}, default_mode="zh") == "中文译名"
