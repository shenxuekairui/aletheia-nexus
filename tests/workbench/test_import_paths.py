"""Import-path collection is explicit, recursive only on request, and read-only."""

import os
import re
from pathlib import Path

import pytest
from pypdf import PdfWriter

from aletheia_nexus.workbench.library import collect_import_paths


def pdf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(path)
    return path.resolve()


@pytest.mark.parametrize("value", [None, "", " ", "\t\r\n"])
def test_blank_input_never_scans_the_current_directory(tmp_path, monkeypatch, value):
    pdf(tmp_path / "must-not-be-imported.pdf")
    monkeypatch.chdir(tmp_path)

    def unexpected_scan(*args, **kwargs):
        pytest.fail(
            "Blank input must be rejected before scanning the current directory"
        )

    monkeypatch.setattr(os, "scandir", unexpected_scan)
    monkeypatch.setattr(Path, "iterdir", unexpected_scan)
    monkeypatch.setattr(Path, "glob", unexpected_scan)
    monkeypatch.setattr(Path, "rglob", unexpected_scan)
    with pytest.raises(ValueError) as error:
        collect_import_paths(value)
    assert re.search(r"[\u4e00-\u9fff]", str(error.value))
    assert "路径" in str(error.value)


@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize("kind", ["file", "directory"])
def test_matching_quotes_around_absolute_file_or_directory_are_accepted(
    tmp_path, quote, kind
):
    source = pdf(tmp_path / "有空格的 资料" / "论文 原文.pdf")
    selected = source if kind == "file" else source.parent
    assert collect_import_paths(f"  {quote}{selected}{quote}  ") == [source]


def test_missing_relative_and_non_pdf_paths_report_distinct_chinese_errors(
    tmp_path, monkeypatch
):
    source = pdf(tmp_path / "paper.pdf")
    text = tmp_path / "notes.txt"
    text.write_text("Unrelated notes", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    messages = []
    for value, expected in (
        (str(tmp_path / "not-existing.pdf"), "不存在"),
        (source.name, "绝对路径"),
        (str(text), "PDF"),
    ):
        with pytest.raises(ValueError) as error:
            collect_import_paths(value)
        message = str(error.value)
        assert expected in message
        assert re.search(r"[\u4e00-\u9fff]", message)
        messages.append(message)
    assert len(set(messages)) == 3


@pytest.mark.parametrize("extension", [".pdf", ".PDF", ".PdF"])
def test_single_pdf_extension_is_case_insensitive(tmp_path, extension):
    source = pdf(tmp_path / ("paper" + extension))
    assert collect_import_paths(str(source)) == [source]


def test_directory_collection_distinguishes_direct_children_from_recursive_scope(
    tmp_path,
):
    directory = tmp_path / "papers"
    direct = [pdf(directory / "a.PDF"), pdf(directory / "z.pdf")]
    nested = [
        pdf(directory / "subfolder" / "b.PdF"),
        pdf(directory / "subfolder" / "deeper" / "c.pdf"),
    ]
    (directory / "notes.txt").write_text("Keep non-PDF files", encoding="utf-8")
    assert set(collect_import_paths(str(directory))) == set(direct)
    assert set(collect_import_paths(str(directory), recursive=False)) == set(direct)
    assert set(collect_import_paths(str(directory), recursive=True)) == set(
        direct + nested
    )


def test_pdf_only_in_subdirectory_prompts_the_recursive_checkbox(tmp_path):
    source = pdf(tmp_path / "papers" / "subfolder" / "paper.pdf")
    directory = source.parent.parent
    with pytest.raises(ValueError, match="包含子目录"):
        collect_import_paths(str(directory), recursive=False)
    assert collect_import_paths(str(directory), recursive=True) == [source]


@pytest.mark.parametrize("recursive", [False, True])
def test_empty_directory_is_rejected(tmp_path, recursive):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError) as error:
        collect_import_paths(str(empty), recursive=recursive)
    assert "PDF" in str(error.value)
    assert re.search(r"[\u4e00-\u9fff]", str(error.value))


def test_collecting_paths_does_not_modify_or_register_source_pdfs(tmp_path):
    directory = tmp_path / "papers"
    direct = pdf(directory / "main.PDF")
    nested = pdf(directory / "subfolder" / "supplement.pdf")
    before = {
        path: path.read_bytes() for path in directory.rglob("*") if path.is_file()
    }
    assert collect_import_paths(str(direct)) == [direct]
    assert collect_import_paths(str(directory), recursive=True) == [direct, nested]
    assert {
        path: path.read_bytes() for path in directory.rglob("*") if path.is_file()
    } == before
