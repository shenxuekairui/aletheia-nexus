"""Naming semantics and persistence, without a browser or model request."""

from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_naming import (
    CUSTOM_TEMPLATE,
    NamingTemplateControl,
    naming_template_catalog,
    validate_naming_template,
)


class Field:
    def __init__(self, value=None):
        self.value = value

    def set_value(self, value):
        self.value = value

    def set_options(self, options, *, value):
        self.options, self.value = options, value


def control(library):
    result = NamingTemplateControl.__new__(NamingTemplateControl)
    result.library = library
    options, result._values = naming_template_catalog(library.templates())
    result.template = Field("{title_original}")
    result.choice = Field(result._key(result.template.value))
    result.choice.options = options
    return result


@pytest.mark.parametrize(
    "value",
    [
        "{year}-{journal}-{title_zh}",
        "{first_author}-{year}-{title_original}",
        "固定前缀-{custom_name}",
        "原始文件",
        "{{文字}}-{title_original}",
    ],
)
def test_shared_template_rules_keep_the_actual_formula(value):
    assert validate_naming_template(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "{",
        "{unknown}",
        "{title_zh!r}",
        "{year:04d}",
        "{authors[0]}",
        "x" * 501,
    ],
)
def test_invalid_or_empty_templates_are_rejected_before_submission(value):
    with pytest.raises(ValueError, match="模板"):
        validate_naming_template(value)


def test_user_names_and_duplicate_formulas_cannot_collide_with_custom_choice():
    options, values = naming_template_catalog(
        {
            "custom": "{title_zh}",
            "自定义模板": "{title_original}",
            "另一个名称": "{title_original}",
        }
    )
    assert len(options) == 4 and len(values) == 3
    assert options[CUSTOM_TEMPLATE] == "自定义模板"
    assert CUSTOM_TEMPLATE not in values
    assert list(values.values()) == [
        "{title_zh}",
        "{title_original}",
        "{title_original}",
    ]


def test_preset_apply_and_direct_edit_share_the_effective_value_atomically(tmp_path):
    actual = control(LibraryService(tmp_path / "library"))
    actual.apply("{year}-{journal}-{title_zh}")
    assert actual.value == "{year}-{journal}-{title_zh}"
    assert actual.choice.value != CUSTOM_TEMPLATE
    before = actual.template.value, actual.choice.value
    with pytest.raises(ValueError):
        actual.apply("{unsupported}")
    assert (actual.template.value, actual.choice.value) == before
    actual.template.set_value("自定义-{title_original}")
    actual._edited(SimpleNamespace(value=actual.template.value))
    assert actual.choice.value == CUSTOM_TEMPLATE
    assert actual.value == "自定义-{title_original}"


def test_custom_selection_and_incomplete_typing_do_not_erase_the_formula(tmp_path):
    actual = control(LibraryService(tmp_path / "library"))
    actual._choose(SimpleNamespace(value=CUSTOM_TEMPLATE))
    assert actual.value == "{title_original}"
    actual.template.set_value("{title_")
    actual._edited(SimpleNamespace(value=actual.template.value))
    assert actual.choice.value == CUSTOM_TEMPLATE
    with pytest.raises(ValueError):
        _ = actual.value
    actual.template.set_value("{title_zh}")
    actual._edited(SimpleNamespace(value=actual.template.value))
    assert actual.choice.value != CUSTOM_TEMPLATE


def test_saved_template_reopens_and_does_not_write_pdf_or_request_a_translation(
    tmp_path,
):
    root = tmp_path / "library"
    root.mkdir()
    paper = root / "untouched.pdf"
    paper.write_bytes(b"original-fixture-bytes")
    actual = control(LibraryService(root))
    actual.apply("{year}-中文整理-{title_zh}")
    assert actual.save(" 中文整理 ") == "{year}-中文整理-{title_zh}"
    assert actual.choice.options[actual.choice.value] == "中文整理"
    assert LibraryService(root).templates()["中文整理"] == actual.value
    assert paper.read_bytes() == b"original-fixture-bytes"


def test_invalid_save_keeps_existing_templates_and_formula(tmp_path):
    library = LibraryService(tmp_path / "library")
    actual = control(library)
    before = library.templates()
    actual.template.set_value("{unsupported}")
    with pytest.raises(ValueError):
        actual.save("不能保存")
    assert library.templates() == before
