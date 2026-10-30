"""Local pasted assignments: no network, AI or private literature required."""

import json

import pytest

from aletheia_nexus.workbench.acquisition import AcquisitionService


def test_twenty_five_numbered_dois_under_four_explicit_chinese_groups(tmp_path):
    groups = [
        ("A", "甲酸盐研究", 7),
        ("B", "催化剂设计", 7),
        ("C", "电解条件", 6),
        ("D", "机理证据", 5),
    ]
    lines, expected, number = [], [], 0
    for letter, name, size in groups:
        lines.extend([f"{letter}. {name}", f"标签={name},待读"])
        for _ in range(size):
            number += 1
            lines.append(f"{number}. https://doi.org/10.9999/an-input-{number:02}")
            expected.append((name, (name, "待读"), len(lines)))
    report = AcquisitionService(tmp_path).preview_inputs("\n".join(lines))
    assert report["count"] == report["paper_count"] == 25
    assert report["ready"] and not report["errors"] and not report["conflicts"]
    for index, (entry, (folder, tags, line)) in enumerate(
        zip(report["items"], expected, strict=True), 1
    ):
        assert entry["request"]["doi"] == f"10.9999/an-input-{index:02}"
        assert entry["request"]["title"] is None
        assert entry["request"]["folder"] == folder
        assert entry["request"]["tags"] == tags
        assert entry["line"] == line
        assert entry["assignment"] == {"folder_mode": "custom", "tags_mode": "custom"}
    assert list(tmp_path.iterdir()) == [tmp_path / ".an-workbench"]


def test_explicit_group_styles_metadata_and_named_inline_tab_overrides(tmp_path):
    text = """## 电催化 | 标签=甲酸,待读
1. 10.1000/a
### 羧酸
2、10.1000/b
3) 10.1000/c | 分类=独立分类/待整理 | 标签=重点;已读
4. 10.1000/d\t分类=/\t标签=[]
[分离方法] | 标签=分析
5. 10.1000/e
A. 其它课题
6. 10.1000/f
"""
    report = AcquisitionService(tmp_path).preview_inputs(text)
    assert report["ready"] and report["count"] == 6
    rows = report["items"]
    assert [r["request"]["folder"] for r in rows] == [
        "电催化",
        "电催化/羧酸",
        "独立分类/待整理",
        None,
        "分离方法",
        "其它课题",
    ]
    assert [r["request"]["tags"] for r in rows] == [
        ("甲酸", "待读"),
        ("甲酸", "待读"),
        ("重点", "已读"),
        (),
        ("分析",),
        (),
    ]
    assert rows[3]["assignment"] == {"folder_mode": "root", "tags_mode": "custom"}
    assert rows[5]["assignment"]["tags_mode"] == "inherit"
    assert rows[3]["group"] == "羧酸"


@pytest.mark.parametrize("clear", ["", "[]", "空", "无标签"])
def test_explicit_empty_tags_override_group_instead_of_inheriting(tmp_path, clear):
    result = AcquisitionService(tmp_path).preview_inputs(
        f"[分类]\n标签=组标签\n10.1000/a | 标签={clear}\n10.1000/b"
    )
    assert result["ready"]
    assert result["items"][0]["request"]["tags"] == ()
    assert result["items"][0]["assignment"]["tags_mode"] == "custom"
    assert result["items"][1]["request"]["tags"] == ("组标签",)


def test_unassigned_rows_remain_inherit_and_root_is_explicit(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "10.1000/a\n10.1000/b | 分类=根目录\n10.1000/c | 分类=文献库\\羧酸"
    )
    assert result["ready"]
    assert result["items"][0]["assignment"] == {
        "folder_mode": "inherit",
        "tags_mode": "inherit",
    }
    assert result["items"][1]["assignment"]["folder_mode"] == "root"
    assert result["items"][1]["request"]["folder"] is None
    assert result["items"][2]["request"]["folder"] == "文献库/羧酸"


def test_bracket_groups_are_not_misparsed_as_json_or_dois(tmp_path):
    service = AcquisitionService(tmp_path)
    result = service.preview_inputs("[分类一]\n[10.1000/a]\n[分类二]\n10.1000/b")
    assert result["ready"]
    assert [r["request"]["folder"] for r in result["items"]] == ["分类一", "分类二"]
    assert service.preview_inputs('["10.1000/a", "10.1000/b"]')["count"] == 2


@pytest.mark.parametrize(
    "folder",
    [
        "../逃逸",
        "C:\\private",
        "/绝对目录",
        "合法/../逃逸",
        "CON",
        "末尾.",
        "重复//目录",
        "a" * 81,
    ],
)
def test_invalid_group_blocks_members_without_sanitizing_or_previous_assignment(
    tmp_path, folder
):
    result = AcquisitionService(tmp_path).preview_inputs(
        f"[原分组]\n10.1000/a\n## {folder}\n10.1000/b\n[新分组]\n10.1000/c"
    )
    assert [r["request"]["doi"] for r in result["items"]] == ["10.1000/a", "10.1000/c"]
    assert [r["request"]["folder"] for r in result["items"]] == ["原分组", "新分组"]
    assert [e["line"] for e in result["errors"]] == [3, 4]
    assert not result["ready"]


def test_invalid_inline_override_does_not_poison_valid_group(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "[有效]\n10.1000/a | 分类=../无效\n10.1000/b"
    )
    assert result["count"] == 1 and result["items"][0]["request"]["folder"] == "有效"
    assert result["errors"][0]["line"] == 2


def test_same_doi_different_assignments_are_preserved_conflicts_not_silently_deduplicated(
    tmp_path,
):
    report = AcquisitionService(tmp_path).preview_inputs(
        "A. 组一 | 标签=待读\n1. 10.1000/a\nB. 组二 | 标签=重点\n2. 10.1000/a"
    )
    assert report["count"] == 2 and report["paper_count"] == 1
    assert len({r["id"] for r in report["items"]}) == 2
    assert all(r["conflict"] and not r["duplicate"] for r in report["items"])
    assert report["conflicts"][0]["lines"] == [2, 4]
    assert set(report["conflicts"][0]["fields"]) == {"folder", "tags"}
    assert not report["ready"] and not report["errors"]


def test_explicit_root_or_clear_and_inherit_are_distinct_assignment_variants(tmp_path):
    report = AcquisitionService(tmp_path).preview_inputs(
        "10.1000/a\n10.1000/a | 分类=/ | 标签="
    )
    assert report["count"] == 2 and not report["ready"]
    assert set(report["conflicts"][0]["fields"]) == {"folder", "tags"}


def test_exact_duplicates_warn_but_multi_doi_lines_and_titles_remain_supported(
    tmp_path,
):
    service = AcquisitionService(tmp_path)
    report = service.preview_inputs(
        "10.1000/a 10.1000/b\n10.1000/a\n中文完整标题\nEnglish full title\n10.1000/c,10.1000/d\n10.1000/e\t10.1000/f"
    )
    assert report["ready"] and report["count"] == report["paper_count"] == 8
    assert report["items"][2]["duplicate"]
    assert report["warnings"][0]["code"] == "DUPLICATE_INPUT"
    assert report["items"][3]["request"]["title"] == "中文完整标题"
    assert report["items"][4]["request"]["title"] == "English full title"


def test_plain_titles_with_pipes_are_not_assumed_to_be_assignments(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "Catalysis | a mechanistic perspective"
    )
    assert result["ready"]
    assert (
        result["items"][0]["request"]["title"]
        == "Catalysis | a mechanistic perspective"
    )


def test_structured_csv_and_json_preserve_existing_fields_and_detect_assignment_conflicts(
    tmp_path,
):
    service = AcquisitionService(tmp_path)
    csv = "doi,title,authors,year,folder,tags\n10.1000/a,Original,Alice;Bob,2026,分类,待读;重点\n"
    csv_report = service.preview_inputs(csv, format="csv")
    assert csv_report["ready"]
    row = csv_report["items"][0]
    assert (
        row["request"]["authors"] == ("Alice", "Bob") and row["request"]["year"] == 2026
    )
    assert row["assignment"] == {"folder_mode": "custom", "tags_mode": "custom"}
    report = service.preview_inputs(
        json.dumps(
            [{"doi": "10.1000/a", "folder": "甲"}, {"doi": "10.1000/a", "folder": "乙"}]
        )
    )
    assert len(report["conflicts"]) == 1 and report["count"] == 2
    assert service.preview_inputs('{"doi":"10.1000/a"}')["ready"]


def test_bad_numbered_doi_and_repeated_metadata_do_not_become_paper_titles(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "1. 10.1000/\n2. 10.1000/a | 标签=甲 | 标签=乙\n3. 10.1000/b"
    )
    assert [r["request"]["doi"] for r in result["items"]] == ["10.1000/b"]
    assert [r["line"] for r in result["errors"]] == [1, 2]
    assert not result["ready"]


def test_invalid_group_tags_do_not_leak_previous_group_tags(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "[甲] | 标签=原标签\n10.1000/a\n[乙] | 标签="
        + "x" * 81
        + "\n10.1000/b\n[丙]\n10.1000/c"
    )
    assert [r["request"]["doi"] for r in result["items"]] == ["10.1000/a", "10.1000/c"]
    assert result["items"][-1]["request"]["tags"] == ()
    assert result["items"][-1]["assignment"]["tags_mode"] == "inherit"


def test_bad_markdown_parent_cannot_silently_turn_child_into_top_level(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "## 有效\n10.1000/a\n## ../无效\n### 子分类\n10.1000/b\n## 新分类\n10.1000/c"
    )
    assert [r["request"]["doi"] for r in result["items"]] == ["10.1000/a", "10.1000/c"]
    assert [e["line"] for e in result["errors"]] == [3, 4, 5]


def test_unrecognized_doi_assignment_is_error_instead_of_a_bare_title(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "10.1000/a | 错拼字段\n10.1000/b | folders=误拼\n10.1000/c"
    )
    assert [r["request"]["doi"] for r in result["items"]] == ["10.1000/c"]
    assert [e["line"] for e in result["errors"]] == [1, 2]


def test_semicolon_multi_doi_list_does_not_break_an_internal_semicolon(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "10.1000/a;10.1000/b\n10.1002/(sici)1234;2-a"
    )
    assert result["ready"]
    assert [r["request"]["doi"] for r in result["items"]] == [
        "10.1000/a",
        "10.1000/b",
        "10.1002/(sici)1234;2-a",
    ]


def test_invalid_parent_metadata_blocks_child_instead_of_using_previous_tags(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "## 父组 | 标签=原标签\n标签=" + "x" * 81 + "\n### 子组\n10.1000/a"
    )
    assert not result["items"]
    assert [e["line"] for e in result["errors"]] == [2, 3, 4]


def test_new_letter_group_even_if_invalid_ends_previous_markdown_parent(tmp_path):
    result = AcquisitionService(tmp_path).preview_inputs(
        "## 不应继承的父组\nA. ../无效\n### 明确新组\n10.1000/a"
    )
    assert result["items"][0]["request"]["folder"] == "明确新组"
    assert [e["line"] for e in result["errors"]] == [2]
