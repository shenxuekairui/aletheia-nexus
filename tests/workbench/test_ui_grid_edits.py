"""Button actions must observe editor commits, including edits without Enter."""

import ast
import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from aletheia_nexus.workbench.ui_grids import read_edited_grid


@pytest.mark.parametrize(
    "field,old,new",
    [
        ("pages", "1-6", "2,4"),
        ("image_pages", "1", "3-4"),
        ("final_stem", "original", "2026-中文基础名称"),
        ("title", "Old title", "Revised title"),
        ("label", "旧提取字段", "工作电位与参比体系"),
    ],
)
def test_button_data_read_waits_for_the_active_editor(field, old, new):
    events = []

    class Grid:
        rows = [{"id": "paper", field: old}]

        async def run_grid_method(self, name):
            assert name == "stopEditing"
            events.append("commit-request")
            await asyncio.sleep(0)  # Browser acknowledgement can arrive later.
            self.rows[0][field] = new
            events.append("commit-applied")

        async def get_client_data(self):
            events.append("read")
            return deepcopy(self.rows)

    data = asyncio.run(read_edited_grid(Grid()))
    assert data[0][field] == new
    assert events == ["commit-request", "commit-applied", "read"]


def test_commit_failure_cannot_fall_back_to_old_action_parameters():
    class Grid:
        async def run_grid_method(self, _):
            raise TimeoutError("Synthetic client acknowledgement failure")

        async def get_client_data(self):
            pytest.fail("A failed commit must prevent reading stale values")

    with pytest.raises(TimeoutError):
        asyncio.run(read_edited_grid(Grid()))


def test_all_editable_business_grids_commit_on_blur_and_use_the_ordered_reader():
    package = Path(__file__).parents[2] / "src" / "aletheia_nexus" / "workbench"
    editable_grids = 0
    for name in ("ui_research.py", "ui_library.py", "ui_acquisition.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if not isinstance(call.func, ast.Attribute):
                continue
            assert call.func.attr != "get_client_data", (
                f"{name} must use the commit-and-read boundary for button actions"
            )
            if call.func.attr != "aggrid" or not call.args:
                continue
            options = call.args[0]
            if not isinstance(options, ast.Dict):
                continue
            editable = any(
                isinstance(key, ast.Constant) and key.value == "editable"
                for obj in ast.walk(options)
                if isinstance(obj, ast.Dict)
                for key in obj.keys
            )
            if editable:
                editable_grids += 1
                entries = {
                    key.value: value
                    for key, value in zip(options.keys, options.values)
                    if isinstance(key, ast.Constant)
                }
                assert (
                    ast.literal_eval(entries["stopEditingWhenCellsLoseFocus"]) is True
                )
    assert editable_grids == 4
