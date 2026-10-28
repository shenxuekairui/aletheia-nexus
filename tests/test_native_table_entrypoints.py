"""Local app boundary and real official SDK v2 stdio use of synthetic XLSX."""

import asyncio
import hashlib
import json
import runpy
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import NATIVE_TABLE_LIMITS, ResearchApplication


@pytest.fixture
def native_source(tmp_path, monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    papers = tmp_path / "论文附件"
    papers.mkdir()
    factory = runpy.run_path(
        str(Path(__file__).parent / "processing/test_native_table.py")
    )["workbook"]
    source = factory.__wrapped__(papers)
    return papers, source


def oversized_workbook(source, destination):
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    count = NATIVE_TABLE_LIMITS["max_cells"] + 1
    text = f'<worksheet xmlns="{namespace}"><dimension ref="A1:A{count}"/><sheetData>'
    text += "".join(
        f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, count + 1)
    )
    text += "</sheetData></worksheet>"
    with ZipFile(source) as original, ZipFile(destination, "w", ZIP_DEFLATED) as output:
        for part in original.namelist():
            output.writestr(
                part,
                text if part == "xl/worksheets/sheet2.xml" else original.read(part),
            )
    return destination


def test_native_table_local_without_keys_and_no_source_or_workspace_writes(
    native_source, tmp_path
):
    papers, source = native_source
    original = source.read_bytes()
    with_app = ResearchApplication([papers], tmp_path / "work")
    try:
        result = with_app.read_native_table(str(source), ["Small"])
        assert result["ok"] and not result["network_access"] and not result["new_files"]
        assert result["source"]["sha256"] == hashlib.sha256(original).hexdigest()
        assert result["source"]["identity_verified"] is False
        assert result["source"]["parent_document_assigned"] is False
        assert result["sheet_count"] == 1 and result["cell_count"] == 12
        decoded = json.loads(result["table_notes"].split("\n", 1)[1])
        assert decoded["source_workbook_sha256"] == result["source"]["sha256"]
        assert "properties_xml" not in result["table_notes"]
        assert source.read_bytes() == original
        assert not list(with_app.workspace.iterdir())
    finally:
        with_app.close()


def test_native_table_rejects_outside_traversal_and_private_paths(
    native_source, tmp_path
):
    papers, source = native_source
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(source.read_bytes())
    app = ResearchApplication([papers], tmp_path / "work")
    try:
        for path in [outside, papers / ".." / outside.name]:
            with pytest.raises(
                ProcessingError, match="path_outside_allowed_directories"
            ):
                app.read_native_table(str(path))
        with pytest.raises(ProcessingError, match="authorization_directory_private"):
            app.read_native_table(str(app.private / "private.xlsx"))
    finally:
        app.close()


def test_native_table_symlink_cannot_escape_roots(native_source, tmp_path):
    papers, source = native_source
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(source.read_bytes())
    link = papers / "linked.xlsx"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This Windows account cannot create symlinks")
    app = ResearchApplication([papers], tmp_path / "work")
    try:
        with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
            app.read_native_table(str(link))
    finally:
        app.close()


def test_native_table_fixed_limit_error_is_explicit_and_has_no_partial_notes(
    native_source, tmp_path
):
    papers, source = native_source
    huge = oversized_workbook(source, papers / "超限.xlsx")
    app = ResearchApplication([papers], tmp_path / "work")
    try:
        result = app.read_native_table(str(huge), ["Large"])
        assert result["ok"] is False
        assert result["error"] == "native_table_resource_limit"
        assert "max_cells=10000" in result["detail"]
        assert "table_notes" not in result
        assert result["network_access"] is False
        invalid = app.read_native_table(str(source), ["Missing"])
        assert invalid["error"] == "invalid_native_table"
        unsupported = papers / "legacy.xls"
        unsupported.write_bytes(b"Not an XLSX")
        with pytest.raises(ProcessingError, match="native_table_format_unsupported"):
            app.read_native_table(str(unsupported))
    finally:
        app.close()


def test_native_table_real_sdk_stdio_lists_and_reads_without_keys(
    native_source, tmp_path
):
    pytest.importorskip("mcp")
    from mcp import Client, StdioServerParameters

    papers, source = native_source
    huge = oversized_workbook(source, papers / "超限.xlsx")
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(source.read_bytes())
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "aletheia_nexus.mcp_server",
                "serve",
                "--allow-dir",
                str(papers),
                "--workspace",
                str(tmp_path / "work"),
            ],
            env={
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        async with Client(params, read_timeout_seconds=30) as client:
            listed = await client.list_tools()
            tool = next(t for t in listed.tools if t.name == "read_native_table")
            assert set(tool.input_schema["properties"]) == {"path", "sheets"}
            result = await client.call_tool(
                "read_native_table", {"path": str(source), "sheets": ["Small"]}
            )
            assert not result.is_error and result.structured_content["ok"]
            content = result.structured_content
            assert (
                content["cell_count"] == 12
                and content["source"]["sha256"] == original_sha
            )
            assert content["network_access"] is False
            assert "properties_xml" not in content["table_notes"]
            denied = await client.call_tool("read_native_table", {"path": str(outside)})
            assert denied.structured_content == {
                "ok": False,
                "error": "path_outside_allowed_directories",
            }
            excess = await client.call_tool(
                "read_native_table", {"path": str(huge), "sheets": ["Large"]}
            )
            assert excess.structured_content["ok"] is False
            assert excess.structured_content["error"] == "native_table_resource_limit"
            assert "table_notes" not in excess.structured_content
            assert "max_cells=10000" in excess.structured_content["detail"]
            # A denied/limited request does not break the protocol or next call.
            again = await client.call_tool(
                "read_native_table", {"path": str(source), "sheets": ["Small"]}
            )
            assert again.structured_content["table_notes"] == content["table_notes"]

    asyncio.run(run())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_sha
    assert not list((tmp_path / "work").iterdir())
