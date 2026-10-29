"""Collection, saved-filter and tag-group management preserves scope/history."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pypdf import PdfWriter

from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.messages import user_message


@pytest.fixture
def organized(tmp_path):
    library = LibraryService(tmp_path / "library")
    papers = []
    for number in range(2):
        incoming = tmp_path / f"paper-{number}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200 + number, height=300)
        writer.write(incoming)
        papers.append(
            library.import_pdf(incoming, title=f"Original {number}", tags=["保留标签"])
        )
    ids = [paper["id"] for paper in papers]
    library.set_selection(ids)
    library.save_collection("原集合", ids[:1])
    library.save_collection("其他集合", ids[1:])
    library.save_filter("集合内待读", {"collection": "原集合", "tags": ["保留标签"]})
    library.save_filter("只看集合", {"collection": "原集合", "ids": ids})
    library.save_filter("无关筛选", {"collection": "其他集合"})
    library.save_tag_group("原分组", ["保留标签"])
    history = tmp_path / "old-research-task.json"
    history.write_text(
        json.dumps({"collection": "原集合", "documents": ids[:1]}), encoding="utf-8"
    )
    immutable = {
        Path(path): Path(path).read_bytes()
        for paper in papers
        for path in (paper["pdf_path"], paper["sidecar_path"])
    }
    immutable[history] = history.read_bytes()
    return library, ids, immutable


def test_collection_rename_updates_all_filter_references_in_one_write(
    organized, monkeypatch
):
    from aletheia_nexus.workbench import library as module

    library, ids, immutable = organized
    before = library._load()
    expected_members = library.scan(**library.filters()["集合内待读"])["items"]
    native_write, writes = module._write, []

    def observed(path, state):
        writes.append(deepcopy(state))
        return native_write(path, state)

    monkeypatch.setattr(module, "_write", observed)
    receipt = library.rename_named("collections", "原集合", " 新集合 ")
    assert receipt["updated_filters"] == ["集合内待读", "只看集合"]
    assert len(writes) == 1
    written = writes[0]
    assert "原集合" not in written["collections"]
    assert written["collections"]["新集合"] == ids[:1]
    assert written["filters"]["集合内待读"]["collection"] == "新集合"
    assert written["filters"]["只看集合"]["collection"] == "新集合"
    assert written["filters"]["无关筛选"] == before["filters"]["无关筛选"]
    for section in before.keys() - {"collections", "filters"}:
        assert written[section] == before[section]
    monkeypatch.setattr(module, "_write", native_write)
    reopened = LibraryService(library.root)
    actual_members = reopened.scan(**reopened.filters()["集合内待读"])["items"]
    assert [row["id"] for row in actual_members] == [
        row["id"] for row in expected_members
    ]
    assert reopened.selection() == ids
    assert all(path.read_bytes() == content for path, content in immutable.items())


def test_referenced_collection_delete_refuses_without_changing_any_scope(organized):
    library, _, immutable = organized
    before = library.state_path.read_bytes()
    with pytest.raises(ValueError) as exc:
        library.delete_named("collections", "原集合")
    assert "集合内待读" in user_message(exc.value)
    assert "只看集合" in user_message(exc.value)
    assert library.state_path.read_bytes() == before
    assert all(path.read_bytes() == content for path, content in immutable.items())
    library.delete_named("filters", "集合内待读")
    library.delete_named("filters", "只看集合")
    library.delete_named("collections", "原集合")
    assert "原集合" not in LibraryService(library.root).collections()


@pytest.mark.parametrize("section", ["filters", "tag_groups"])
def test_filter_and_group_rename_and_delete_leave_other_sections_unchanged(
    organized, section
):
    library, _, immutable = organized
    old = "集合内待读" if section == "filters" else "原分组"
    before = library._load()
    receipt = library.rename_named(section, old, "新名称")
    assert receipt["value"] == before[section][old]
    assert receipt["updated_filters"] == []
    changed = library._load()
    assert changed[section]["新名称"] == before[section][old]
    assert old not in changed[section]
    for name in before.keys() - {section}:
        assert changed[name] == before[name]
    library.delete_named(section, "新名称")
    assert "新名称" not in LibraryService(library.root)._load()[section]
    assert all(path.read_bytes() == content for path, content in immutable.items())


@pytest.mark.parametrize(
    "section,old,new",
    [
        ("collections", "原集合", "其他集合"),
        ("collections", "不存在", "新集合"),
        ("collections", "原集合", " "),
        ("collections", "原集合", "a" * 101),
        ("collections", "原集合", "第一行\n第二行"),
        ("views", "标准文献视图", "新视图"),
        ("papers", "原集合", "新集合"),
        ("selection", "原集合", "新集合"),
    ],
)
def test_invalid_rename_never_overwrites_or_partially_updates(
    organized, section, old, new
):
    library, _, _ = organized
    before = library.state_path.read_bytes()
    with pytest.raises(ValueError):
        library.rename_named(section, old, new)
    assert library.state_path.read_bytes() == before


def test_noop_and_failed_atomic_write_preserve_original_registry(
    organized, monkeypatch
):
    from aletheia_nexus.workbench import library as module

    library, _, _ = organized
    before = library.state_path.read_bytes()

    def failed_write(*_):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(module, "_write", failed_write)
    assert library.rename_named("collections", "原集合", "原集合")["name"] == "原集合"
    with pytest.raises(OSError, match="simulated storage failure"):
        library.rename_named("collections", "原集合", "新集合")
    assert library.state_path.read_bytes() == before
    assert library.filters()["集合内待读"]["collection"] == "原集合"
