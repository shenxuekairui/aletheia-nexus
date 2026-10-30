"""Batch placement edits retain explicit empty/root intent through submission."""

from copy import deepcopy

import pytest

from aletheia_nexus.workbench.acquisition import normalize_request
from aletheia_nexus.workbench.acquisition_batch import apply_assignment, build_requests


def row(paper_id="a", **values):
    return {
        "id": paper_id,
        "enabled": True,
        "folder_mode": "inherit",
        "folder": "",
        "tags_mode": "inherit",
        "tags": "",
        "doi": "10.1000/fixture-" + paper_id,
        "title": "Edited original title " + paper_id,
        "filename": "",
        "resolution": "DOI",
        "notes": {"untouched": ["caller-owned"]},
        **values,
    }


def originals(rows):
    return {
        r["id"]: {
            "doi": r["doi"],
            "title": "Original title",
            "authors": ["First Author", "Second Author"],
            "year": 2026,
            "journal": "Fixture journal",
            "volume": "8",
            "tags": ["imported"],
        }
        for r in rows
    }


def test_selection_uses_ids_and_preserves_download_switch_and_all_other_edits():
    rows = [row("b", enabled=False), row("a"), row("c")]
    before = deepcopy(rows)
    changed = apply_assignment(
        rows,
        ["a", "b"],
        folder_action="set",
        folder="电合成\\新分类",
        tag_action="replace",
        tags="甲酸盐， 待阅读, 甲酸盐",
    )
    assert rows == before
    assert [r["id"] for r in changed] == ["b", "a", "c"]
    assert changed[0]["enabled"] is False
    assert changed[2] == rows[2]
    for actual, original in zip(changed[:2], rows[:2]):
        assert actual["folder_mode"] == "custom"
        assert actual["folder"] == "电合成/新分类"
        assert actual["tags_mode"] == "custom"
        assert actual["tags"] == "甲酸盐, 待阅读"
        assert actual["title"] == original["title"]
        assert actual["filename"] == original["filename"]
        actual["notes"]["untouched"].append("new")
        assert original["notes"] == {"untouched": ["caller-owned"]}


def test_root_and_empty_custom_tags_do_not_inherit_nonempty_global_defaults():
    rows = [row("a"), row("b"), row("c", enabled=False)]
    rows = apply_assignment(rows, ["b"], folder_action="root", tag_action="clear")
    requests = build_requests(rows, originals(rows), "默认/分类", ["默认标签"])
    assert len(requests) == 2
    assert requests[0]["folder"] == "默认/分类"
    assert requests[0]["tags"] == ["默认标签"]
    assert requests[1]["folder"] is None
    assert requests[1]["tags"] == []
    for request in requests:
        assert normalize_request(request).doi == request["doi"]
        assert request["authors"] == ["First Author", "Second Author"]
        assert request["filename"] is None


def test_inheritance_remains_dynamic_and_reset_is_distinct_from_copy():
    rows = [
        row(folder_mode="custom", folder="旧分类", tags_mode="custom", tags="旧标签")
    ]
    inherited = apply_assignment(
        rows,
        ["a"],
        folder_action="inherit",
        tag_action="inherit",
        default_folder="第一次默认",
        default_tags=["第一次标签"],
    )
    assert inherited[0]["folder"] == inherited[0]["tags"] == ""
    request = build_requests(inherited, originals(inherited), "后来默认", ["后来标签"])[
        0
    ]
    assert request["folder"] == "后来默认" and request["tags"] == ["后来标签"]
    copied = apply_assignment(
        rows,
        ["a"],
        folder_action="set",
        folder="第一次默认",
        tag_action="replace",
        tags=["第一次标签"],
    )
    request = build_requests(copied, originals(copied), "后来默认", ["后来标签"])[0]
    assert request["folder"] == "第一次默认" and request["tags"] == ["第一次标签"]


def test_add_remove_resolves_each_rows_effective_tags_without_sharing_lists():
    rows = [row("a"), row("b", tags_mode="custom", tags="局部, 保留")]
    added = apply_assignment(
        rows,
        ["a", "b"],
        tag_action="add",
        tags=["新增", "共同"],
        default_tags=["全局", "共同"],
    )
    assert [r["tags"] for r in added] == ["全局, 共同, 新增", "局部, 保留, 新增, 共同"]
    removed = apply_assignment(added, ["b"], tag_action="remove", tags=["局部", "新增"])
    assert removed[0] == added[0]
    assert removed[1]["tags"] == "保留, 共同"
    assert apply_assignment(rows, ["a"], tag_action="add", tags=[]) == rows
    assert apply_assignment(rows, ["a"], tag_action="remove", tags=[]) == rows


@pytest.mark.parametrize("action", ["clear", "replace"])
def test_clear_or_empty_replace_intentionally_disables_default_tags(action):
    rows = apply_assignment([row()], ["a"], tag_action=action, tags=[])
    assert rows[0]["tags_mode"] == "custom" and rows[0]["tags"] == ""
    assert (
        build_requests(rows, originals(rows), default_tags=["default"])[0]["tags"] == []
    )


@pytest.mark.parametrize(
    "folder",
    [
        "../越界",
        "a/../b",
        "/absolute",
        "C:\\outside",
        "\\\\host\\share",
        "a//b",
        "NUL",
        "_unverified",
        "",
        None,
    ],
)
def test_unsafe_or_empty_explicit_category_is_rejected_atomically(folder):
    rows = [row("a"), row("b")]
    before = deepcopy(rows)
    with pytest.raises(ValueError, match="分类|根目录"):
        apply_assignment(
            rows, ["a", "b"], folder_action="set", folder=folder, tag_action="clear"
        )
    assert rows == before


@pytest.mark.parametrize(
    "tags", [[""], ["x" * 81], "a\nb", "a\x00b", "\na", {"x": 1}, ["a,b"]]
)
def test_invalid_tags_reject_the_whole_assignment(tags):
    rows = [row("a"), row("b")]
    before = deepcopy(rows)
    with pytest.raises(ValueError, match="标签"):
        apply_assignment(
            rows, ["a", "b"], folder_action="root", tag_action="replace", tags=tags
        )
    assert rows == before


@pytest.mark.parametrize("selection", [["unknown"], ["a", "a"], "a", [None]])
def test_selection_validation_never_edits_a_different_or_partial_row(selection):
    rows = [row("a"), row("b")]
    before = deepcopy(rows)
    with pytest.raises(ValueError):
        apply_assignment(rows, selection, tag_action="clear")
    assert rows == before


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": 1},
        {"folder_mode": []},
        {"tags_mode": "clear"},
        {"id": " "},
        {"folder_mode": "custom", "folder": "../x"},
    ],
)
def test_invalid_complete_row_state_is_rejected_before_edit(changes):
    rows = [row("a"), row("b", **changes)]
    before = deepcopy(rows)
    with pytest.raises(ValueError):
        apply_assignment(rows, ["a"], tag_action="clear")
    assert rows == before


def test_rows_and_original_map_must_have_exactly_the_same_unique_ids():
    rows = [row("a"), row("b")]
    for mapping in ({}, {"a": originals(rows)["a"]}, {**originals(rows), "extra": {}}):
        with pytest.raises(ValueError, match="编号不一致"):
            build_requests(rows, mapping)
    with pytest.raises(ValueError, match="重复稳定编号"):
        apply_assignment([row(), row()], ["a"])


@pytest.mark.parametrize("conflict", ["same", "folder", "tags", "filename", "title"])
def test_duplicate_enabled_doi_is_never_silently_kept_first(conflict):
    rows = [row("a"), row("b", doi="https://doi.org/10.1000/FIXTURE-A")]
    if conflict == "folder":
        rows[1].update(folder_mode="custom", folder="另一个分类")
    elif conflict == "tags":
        rows[1].update(tags_mode="custom", tags="不同标签")
    elif conflict == "filename":
        rows[1]["filename"] = "另一个文件名"
    before = deepcopy(rows)
    with pytest.raises(ValueError, match="重复启用同一论文身份") as error:
        build_requests(rows, originals(rows))
    if conflict in {"folder", "tags", "filename"}:
        assert "存在冲突" in str(error.value)
    assert rows == before
    rows[1]["enabled"] = False
    assert len(build_requests(rows, originals(rows))) == 1


def test_distinct_dois_with_same_title_are_not_falsely_merged():
    rows = [row("a", title="Same title"), row("b", title="Same title")]
    assert len(build_requests(rows, originals(rows))) == 2


def test_duplicate_cnki_and_doi_less_bibliography_are_rejected():
    for changes in ({"cnki_id": "cnki:CJFD:ABCD.2026.001"}, {}):
        rows = [row("a", doi="", title="中文标题"), row("b", doi="", title="中文标题")]
        mapping = originals(rows)
        for original in mapping.values():
            original.update(changes)
        with pytest.raises(ValueError, match="重复启用同一论文身份"):
            build_requests(rows, mapping)


def test_build_preserves_server_bibliography_and_edited_fields_without_mutation():
    rows = [
        row(title="Manually confirmed title", filename="手动文件名.pdf", year="2025")
    ]
    mapping = originals(rows)
    before_rows, before_map = deepcopy(rows), deepcopy(mapping)
    request = build_requests(rows, mapping)[0]
    assert request["title"] == "Manually confirmed title"
    assert request["filename"] == "手动文件名"
    assert request["year"] == 2025 and request["volume"] == "8"
    assert rows == before_rows and mapping == before_map
    request["authors"].append("New author")
    assert mapping == before_map


def test_invalid_identity_or_zero_enabled_rows_cannot_be_submitted():
    with pytest.raises(ValueError, match="获取参数无效"):
        build_requests([row(doi="", title="")], {"a": {"doi": "10.1000/original"}})
    with pytest.raises(ValueError, match="没有启用"):
        build_requests([row(enabled=False)], {"a": {"doi": "10.1000/original"}})
