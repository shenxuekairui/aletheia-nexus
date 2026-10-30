"""The graphical editor submits the previewed placement, including empty tags."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_acquisition_batch import AcquisitionBatchEditor


class Grid:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.options = {"rowData": deepcopy(rows)}
        self.pending = None

    async def run_grid_method(self, name, *args):
        if name == "stopEditing" and self.pending:
            self.rows[0].update(self.pending)
            self.pending = None
        elif name == "setGridOption":
            self.rows = deepcopy(args[1])

    async def get_client_data(self):
        return deepcopy(self.rows)

    async def get_selected_rows(self):
        return self.rows[:1]


def editor(tmp_path, text="10.1000/first\n10.1000/second"):
    library = LibraryService(tmp_path / "library")
    report = AcquisitionService(library.root).preview_inputs(text)
    rows = [
        {
            "id": entry["id"],
            "enabled": True,
            "doi": entry["request"]["doi"] or "",
            "title": entry["request"]["title"] or "",
            "folder": entry["request"]["folder"] or "",
            "tags": ", ".join(entry["request"]["tags"]),
            "filename": "",
            "resolution": "DOI" if entry["request"]["doi"] else "待解析标题",
            **entry["assignment"],
        }
        for entry in report["items"]
    ]
    saved = []
    grid = Grid(rows)
    instance = AcquisitionBatchEditor(
        SimpleNamespace(ctx=SimpleNamespace(library=library)),
        grid,
        report,
        lambda: "批次默认",
        lambda: ["默认标签"],
        lambda rows: saved.append(deepcopy(rows)),
    )
    return instance, grid, library, saved


def test_final_requests_commit_editor_and_do_not_restore_explicit_empty_tags(tmp_path):
    instance, grid, _, saved = editor(tmp_path)
    grid.pending = {
        "folder_mode": "root",
        "tags_mode": "custom",
        "tags": "",
        "filename": "用户指定名称",
    }
    grid.rows[1]["enabled"] = False
    result = asyncio.run(instance.requests())
    assert len(result) == 1
    assert result[0]["folder"] is None and result[0]["tags"] == []
    assert result[0]["filename"] == "用户指定名称"
    assert saved[-1][0]["tags_mode"] == "custom"


def test_directory_status_does_not_create_unrequested_folders(tmp_path):
    instance, grid, library, _ = editor(tmp_path)
    (library.root / "空的已有分类").mkdir()
    grid.rows[0].update(folder_mode="custom", folder="空的已有分类")
    grid.rows[1].update(folder_mode="custom", folder="新分类/子目录")
    decorated = instance.decorate(grid.rows)
    assert [r["placement_state"] for r in decorated] == ["已有目录", "下载时新建"]
    assert decorated[1]["effective_tags"] == "默认标签"
    assert not (library.root / "新分类").exists()


def test_internal_attachment_directory_is_not_a_classification_target(tmp_path):
    instance, grid, _, _ = editor(tmp_path)
    grid.rows[0].update(folder_mode="custom", folder="普通分类/SI")
    with pytest.raises(ValueError, match="分类目录"):
        asyncio.run(instance.requests())


def test_unresolved_title_has_an_actionable_error_before_submission(tmp_path):
    instance, _, _, _ = editor(tmp_path, "A real English paper title")
    with pytest.raises(ValueError, match="解析并确认"):
        asyncio.run(instance.requests())
