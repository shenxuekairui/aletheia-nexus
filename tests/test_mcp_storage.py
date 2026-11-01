from pathlib import Path
from types import SimpleNamespace

from aletheia_nexus import mcp_server
from aletheia_nexus.storage_paths import PathPreferences, StoragePaths


def test_mcp_uses_saved_paths_and_explicit_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    prefs = PathPreferences()
    saved = StoragePaths(*(tmp_path / name for name in ("papers", "index", "work")))
    prefs.save(saved)
    observed = []

    def server(app):
        observed.append((app.roots, app.workspace, app.library.state_dir))
        return SimpleNamespace(run=lambda **_: None)

    monkeypatch.setattr(mcp_server, "create_server", server)
    assert mcp_server.main(["serve"]) == 0
    assert observed[-1] == ((saved.library,), saved.workspace, saved.library_state_dir)
    custom = tmp_path / "custom"
    assert (
        mcp_server.main(
            [
                "serve",
                "--library",
                str(custom),
                "--workspace",
                str(tmp_path / "custom-work"),
                "--library-state-dir",
                str(tmp_path / "custom-index"),
            ]
        )
        == 0
    )
    assert observed[-1] == (
        (custom,),
        tmp_path / "custom-work",
        tmp_path / "custom-index",
    )
    assert prefs.resolve() == saved


def test_explicit_allow_directory_uses_original_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    original = tmp_path / "original"
    original.mkdir()
    moved = StoragePaths(tmp_path / "moved", tmp_path / "index", tmp_path / "work")
    PathPreferences().save(moved, relocations={str(original): str(moved.library)})
    observed = []

    def server(app):
        observed.append(app.path(original / "paper.pdf"))
        return SimpleNamespace(run=lambda **_: None)

    monkeypatch.setattr(mcp_server, "create_server", server)
    assert mcp_server.main(["serve", "--allow-dir", str(original)]) == 0
    assert observed == [original / "paper.pdf"]


def test_real_stdio_reads_separate_saved_library_index(tmp_path):
    import asyncio
    import os
    import sys

    import pytest
    from pypdf import PdfWriter

    pytest.importorskip("mcp")
    from mcp import Client, StdioServerParameters

    from aletheia_nexus.workbench.library import LibraryService

    root = tmp_path / "papers"
    state = tmp_path / "separate-index"
    library = LibraryService(root, state)
    pdf = tmp_path / "input.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    with pdf.open("wb") as handle:
        writer.write(handle)
    paper = library.import_pdf(pdf, title="MCP storage fixture", tags=["保存标签"])
    library.save_collection("保存集合", [paper["id"]])
    paths = StoragePaths(root, state, tmp_path / "work")
    PathPreferences(tmp_path / ".aletheia-nexus").save(paths)

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "aletheia_nexus.mcp_server", "serve"],
            env={
                **os.environ,
                "HOME": str(tmp_path),
                "USERPROFILE": str(tmp_path),
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            },
        )
        async with Client(params, read_timeout_seconds=30) as client:
            response = await client.call_tool(
                "get_library_catalog", {"tag": "保存标签"}
            )
            value = response.structured_content
            assert value["ok"]
            assert value["catalog"]["items"][0]["id"] == paper["id"]
            assert value["collections"]["保存集合"] == [paper["id"]]
            assert value["storage_paths"] == paths.strings()

    asyncio.run(run())
