"""Native local SI/library wrappers and real SDK stdio; no network or model."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
from test_research_app import write_pdf

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import ResearchApplication


@pytest.fixture
def local_library(tmp_path):
    papers = tmp_path / "论文"
    papers.mkdir()
    main, si = papers / "主文.pdf", papers / "补充.pdf"
    for path, title, text in [
        (main, "Local main", "Self-authored main: sample measured at 25 C."),
        (si, "Local supplement", "Self-authored supplement: control repeated twice."),
    ]:
        write_pdf(path, [[(50, 650, 12, text)]], title=title)
    app = ResearchApplication([papers], tmp_path / "results")
    try:
        yield app, main, si
    finally:
        app.close()


def test_explicit_si_parent_and_preserved_registered_source(local_library):
    app, main, si = local_library
    original = {p: p.read_bytes() for p in (main, si)}
    parent = app.import_local_document(str(main), "Main", doi="10.1234/local")
    main_record = Path(parent["document"]["sidecar"])
    parent_bytes = main_record.read_bytes()
    imported = app.import_local_document(
        str(si), "Explicit SI", role="SUPPLEMENT", parent=parent["document"]
    )
    source = imported["source"]
    assert source["document_role"] == "SUPPLEMENT"
    assert source["identity_basis"] == "local_declared"
    assert source["parent"]["pdf_sha256"] == parent["source"]["pdf_sha256"]
    assert source["parent"]["article_id"] == "doi:10.1234/local"
    assert source["parent"]["doi"] == "10.1234/local"
    assert imported["parent_document"] == {
        "pdf": parent["document"]["pdf"],
        "sidecar": parent["document"]["sidecar"],
    }
    record = Path(imported["document"]["sidecar"])
    record_bytes = record.read_bytes()
    with pytest.raises(ProcessingError, match="source_already_registered"):
        app.import_local_document(imported["document"]["pdf"], "Overwrite")
    prepared = app.prepare_documents([imported["document"]["pdf"]])
    assert not prepared["failures"]
    copied = app.check_document(prepared["documents"][0], "parsed")
    assert copied.identity["document_role"] == "SUPPLEMENT"
    assert copied.identity["parent"] == source["parent"]
    assert Path(prepared["documents"][0]["sidecar"]).read_bytes() == record_bytes
    assert (
        record.read_bytes() == record_bytes and main_record.read_bytes() == parent_bytes
    )
    assert all(p.read_bytes() == data for p, data in original.items())


def test_si_can_reference_verified_main_without_redeclaring_it(local_library):
    app, main, si = local_library
    # Synthetic acquisition record exercises the native VERIFIED parent gate;
    # no actual acquisition or scientific identity claim is made by this test.
    register_local_pdf(main, output_dir=main.parent, title="Verified fixture")
    sidecar = acquisition_sidecar_path(main)
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    record.update(schema="aletheia-nexus/acquisition-record/v1", status="VERIFIED")
    record["target"]["doi"] = "10.1234/verified"
    record["target"]["article_id"] = "doi:10.1234/verified"
    record["identity_validation"]["status"] = "MATCH"
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    before = main.read_bytes(), sidecar.read_bytes()
    imported = app.import_local_document(
        str(si),
        "Explicit SI",
        role="SUPPLEMENT",
        parent={"pdf": str(main), "sidecar": str(sidecar)},
    )
    assert imported["source"]["parent"]["article_id"] == "doi:10.1234/verified"
    assert imported["source"]["identity_basis"] == "local_declared"
    checked = app.get_acquisition_status(str(sidecar), pdf=str(main))
    assert checked["current_check"]["identity_verified"] is True
    assert (main.read_bytes(), sidecar.read_bytes()) == before
    with pytest.raises(ProcessingError, match="source_already_registered"):
        app.import_local_document(str(main), "Cannot downgrade acquired identity")


@pytest.mark.parametrize(
    "case",
    [
        "missing_parent",
        "article_parent",
        "own_doi",
        "same_pdf",
        "si_parent",
        "outside_parent",
    ],
)
def test_si_rejects_invalid_relationship_before_copy(local_library, tmp_path, case):
    app, main, si = local_library
    parent = app.import_local_document(str(main), "Main")["document"]
    options = {"role": "SUPPLEMENT", "parent": parent}
    selected = str(si)
    if case == "missing_parent":
        options.pop("parent")
    elif case == "article_parent":
        options["role"] = "ARTICLE"
    elif case == "own_doi":
        options["doi"] = "10.1234/si"
    elif case == "same_pdf":
        selected = str(main)  # Same bytes as parent copy, still unregistered here.
    elif case == "si_parent":
        options["parent"] = app.import_local_document(str(si), "First SI", **options)[
            "document"
        ]
    else:
        options["parent"] = {"pdf": str(tmp_path / "outside.pdf")}
    before = {p: p.read_bytes() for p in app.workspace.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, ProcessingError)):
        app.import_local_document(selected, "Invalid SI", **options)
    assert {
        p: p.read_bytes() for p in app.workspace.rglob("*") if p.is_file()
    } == before


def test_catalog_filters_workspace_labels_and_scientific_bytes(local_library):
    app, main, si = local_library
    parent = app.import_local_document(str(main), "Main")["document"]
    imported = app.import_local_document(
        str(si), "Supplement", role="SUPPLEMENT", parent=parent
    )
    parsed = app.parse_document(parent)
    protected = [Path(parent[k]) for k in ("pdf", "sidecar")]
    protected += [Path(parsed["document"]["artifact"]), main, si]
    before = {p: p.read_bytes() for p in protected}
    tagged = app.update_document_tags(parent["pdf"], add=["重点", " 待读 ", "重点"])
    assert tagged["tags"] == ["重点", "待读"]
    assert tagged["network_access"] is False
    assert tagged["source_files_modified"] is False
    assert Path(tagged["labels_file"]).parent.name == "json"
    listing = app.list_documents(str(app.workspace), catalog=True, recursive=True)
    assert len(listing["documents"]) == 2
    supplement = next(
        r for r in listing["documents"] if r["document_role"] == "SUPPLEMENT"
    )
    assert supplement["parent"] == imported["source"]["parent"]
    assert all(r["identity_basis"] == "local_declared" for r in listing["documents"])
    selected = app.list_documents(
        str(app.workspace),
        catalog=True,
        recursive=True,
        folder=str(Path(parent["pdf"]).parent.relative_to(app.workspace)),
        tag="重点",
        query="main",
    )
    assert [r["pdf_path"] for r in selected["documents"]] == [parent["pdf"]]
    assert not app.list_documents(str(app.workspace), catalog=True)["documents"]
    assert len(app.list_documents(str(main.parent))["documents"]) == 2
    assert not app.list_documents(str(main.parent), catalog=True)["documents"]
    app.update_document_tags(parent["pdf"], add=["已读"], remove=["重点", "待读"])
    assert not app.list_documents(
        str(app.workspace), catalog=True, recursive=True, tag="重点"
    )["documents"]
    with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
        app.update_document_tags(str(main), add=["不允许"])
    with pytest.raises(ValueError):
        app.list_documents(str(app.workspace), tag="requires catalog")
    with pytest.raises(ValueError):
        app.update_document_tags(parent["pdf"], add="not a list")
    assert all(p.read_bytes() == data for p, data in before.items())
    # Native local records fail their source gate after tampering; labels cannot
    # repair the PDF or promote an invalid source into a valid library record.
    Path(parent["pdf"]).write_bytes(Path(parent["pdf"]).read_bytes() + b"tampered")
    with pytest.raises((ValueError, RuntimeError)):
        app.update_document_tags(parent["pdf"], add=["不得掩盖"])
    catalog = app.list_documents(str(app.workspace), catalog=True, recursive=True)
    assert len(catalog["documents"]) == 1 and catalog["warnings"]


def test_catalog_applies_private_path_guard_before_read(local_library):
    app, main, _ = local_library
    imported = app.import_local_document(str(main), "Main")
    private = app.private / "records"
    private.mkdir(parents=True)
    # Even a source-looking file under the private grant directory is not
    # exposed by a recursive library scan of the permitted workspace.
    (private / "secret.acquisition.json").write_bytes(
        Path(imported["document"]["sidecar"]).read_bytes()
    )
    with pytest.raises(ProcessingError, match="authorization_directory_private"):
        app.list_documents(str(app.workspace), catalog=True, recursive=True)


def test_catalog_and_tags_reject_redirected_label_directory(local_library, tmp_path):
    app, main, _ = local_library
    parent = app.import_local_document(str(main), "Main")["document"]
    labels_dir = Path(parent["pdf"]).parent / "json"
    outside = tmp_path / "outside"
    outside.mkdir()
    # Keep the legitimate sidecar outside the redirected directory, in its
    # supported legacy location, so only label path guarding is under test.
    old_sidecar = Path(parent["sidecar"])
    Path(parent["pdf"]).with_suffix(".acquisition.json").write_bytes(
        old_sidecar.read_bytes()
    )
    old_sidecar.unlink()
    labels_dir.rmdir()
    try:
        labels_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        shell = shutil.which("powershell") if os.name == "nt" else None
        if shell is None:
            pytest.skip("OS user cannot create directory symlinks")
        # Windows directory junctions do not need symlink privilege. Paths are
        # data in environment variables, never interpolated into shell code.
        junction = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "New-Item -ItemType Junction -Path $env:AN_MCP_TEST_LINK "
                "-Value $env:AN_MCP_TEST_TARGET -ErrorAction Stop | Out-Null",
            ],
            env={
                **os.environ,
                "AN_MCP_TEST_LINK": str(labels_dir),
                "AN_MCP_TEST_TARGET": str(outside),
            },
            capture_output=True,
        )
        if junction.returncode:
            pytest.skip("OS user cannot create directory symlinks or junctions")
    with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
        app.update_document_tags(parent["pdf"], add=["escape"])
    assert not list(outside.iterdir())
    with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
        app.list_documents(str(app.workspace), catalog=True, recursive=True)


def test_stdio_explicit_si_catalog_and_workspace_labels(local_library, monkeypatch):
    pytest.importorskip("mcp")
    from mcp import Client, StdioServerParameters

    app, main, si = local_library
    root = Path(__file__).resolve().parents[1]
    original = {p: sha256_file(p) for p in (main, si)}
    for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "QWEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-B",
                "-m",
                "aletheia_nexus.mcp_server",
                "serve",
                "--allow-dir",
                str(main.parent),
                "--workspace",
                str(app.workspace),
            ],
            env={"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        async with Client(params, read_timeout_seconds=30) as client:
            tools = (await client.list_tools()).tools
            assert len(tools) == 23
            assert "update_document_tags" in {t.name for t in tools}
            listing = next(t for t in tools if t.name == "list_documents")
            assert {"catalog", "folder", "tag", "query"} <= set(
                listing.input_schema["properties"]
            )

            async def call(name, payload):
                reply = await client.call_tool(name, payload)
                assert not reply.is_error
                result = reply.structured_content
                calls.append(
                    {"tool": name, "ok": result["ok"], "error": result.get("error")}
                )
                return result

            parent = await call(
                "import_local_document", {"pdf": str(main), "title": "SDK Main"}
            )
            imported = await call(
                "import_local_document",
                {
                    "pdf": str(si),
                    "title": "SDK Supplement",
                    "role": "SUPPLEMENT",
                    "parent": parent["document"],
                },
            )
            assert imported["source"]["parent"]["pdf_sha256"] == original[main]
            assert imported["source"]["identity_basis"] == "local_declared"
            assert imported["source"]["document_role"] == "SUPPLEMENT"
            protected = {
                Path(d[k]): Path(d[k]).read_bytes()
                for d in (parent["document"], imported["document"])
                for k in ("pdf", "sidecar")
            }
            tagged = await call(
                "update_document_tags",
                {
                    "pdf": imported["document"]["pdf"],
                    "add": ["待核SI", "重点"],
                },
            )
            assert tagged["tags"] == ["待核SI", "重点"]
            catalog = await call(
                "list_documents",
                {
                    "directory": str(app.workspace),
                    "recursive": True,
                    "catalog": True,
                    "tag": "待核SI",
                    "query": "Supplement",
                },
            )
            assert len(catalog["documents"]) == 1
            assert catalog["documents"][0]["parent"] == imported["source"]["parent"]
            assert catalog["network_access"] is False
            status = await call(
                "get_acquisition_status",
                {
                    "sidecar": imported["document"]["sidecar"],
                    "pdf": imported["document"]["pdf"],
                },
            )
            assert status["current_check"]["status"] == "PASSED"
            assert status["current_check"]["identity_verified"] is False
            denied = await call(
                "update_document_tags", {"pdf": str(main), "add": ["deny"]}
            )
            assert denied["error"] == "path_outside_allowed_directories"
            overwritten = await call(
                "import_local_document",
                {
                    "pdf": imported["document"]["pdf"],
                    "title": "Wrong main",
                },
            )
            assert (
                overwritten["error"]
                == "source_already_registered_use_prepare_documents"
            )
            await call(
                "update_document_tags",
                {
                    "pdf": imported["document"]["pdf"],
                    "remove": ["重点"],
                },
            )
            prepared = await call(
                "prepare_documents", {"paths": [imported["document"]["pdf"]]}
            )
            assert not prepared["failures"]
            reread = await call(
                "get_acquisition_status",
                {
                    "sidecar": prepared["documents"][0]["sidecar"],
                    "pdf": prepared["documents"][0]["pdf"],
                },
            )
            assert reread["current_check"]["identity_basis"] == "local_declared"
            assert reread["current_check"]["document_role"] == "SUPPLEMENT"
            disabled = await call(
                "acquire_documents", {"papers": [{"doi": "10.1234/disabled"}]}
            )
            assert disabled["error"] == "network_disabled"
            assert all(p.read_bytes() == data for p, data in protected.items())

    asyncio.run(run())
    assert all(sha256_file(p) == value for p, value in original.items())
    print(
        "SDK_LOCAL_LIBRARY_SMOKE "
        + json.dumps(
            {
                "sdk_version": version("mcp"),
                "calls": calls,
                "network_calls": 0,
                "model_calls": 0,
                "originals_unchanged": True,
            },
            ensure_ascii=False,
        )
    )
