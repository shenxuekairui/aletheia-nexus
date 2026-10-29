"""Real SDK v2 subprocess transport, not merely direct Python function calls."""

import asyncio
import base64
import json
import shutil
import struct
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from test_research_app import task_for, write_pdf
from test_research_history import planning_history
from test_research_revision_app import save_fixture_result

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.research_app import ResearchApplication

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters
from mcp.types import Implementation


def test_stdio_history_optional_directory_read_and_reexport_without_key(
    tmp_path, monkeypatch
):
    papers = tmp_path / "论文"
    papers.mkdir()
    workspace = tmp_path / "results"
    pdf = papers / "历史论文.pdf"
    write_pdf(
        pdf,
        [[(50, 650, 12, "A sample was measured at 25 C.")]],
        title="History fixture",
    )
    fixture_app = ResearchApplication([papers], workspace)
    try:
        parent, result = save_fixture_result(fixture_app, pdf)
    finally:
        fixture_app.close()
    original_bytes = parent.read_bytes()
    history_root = papers / "旧输出"
    native = history_root / "runs/native-run"
    write_json(native / "sample.result.json", result)
    write_json(native / "task.json", result["task"])
    manifest = {
        "schema": "aletheia-nexus/research-run/v1",
        "run_id": "native-run",
        "status": "PARTIAL",
        "task_fingerprint": "fixture-task",
        "task_file": "task.json",
        "items": [{"result": "sample.result.json"}],
        "outputs": [],
        "usage": {"http_attempts": 0, "estimated_cost": 0},
    }
    write_json(native / "manifest.json", manifest)
    write_json(history_root / "runs/copy/manifest.json", manifest)
    planning_history(workspace, "success", "COMPLETED", result["task"])
    planning_history(workspace, "failure", "FAILED")
    for name in ("DEEPSEEK_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

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
                str(workspace),
            ],
            env={
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        async with Client(params, read_timeout_seconds=30) as client:
            tools = await client.list_tools()
            history_tool = next(
                t for t in tools.tools if t.name == "list_research_runs"
            )
            assert "directory" in history_tool.input_schema["properties"]
            reply = await client.call_tool(
                "list_research_runs", {"directory": str(history_root)}
            )
            assert not reply.is_error and reply.structured_content["ok"]
            history = reply.structured_content
            assert (
                history["network_access"] is False
                and history["usage_aggregated"] is False
            )
            assert len(history["runs"]) == 3
            assert {
                r["status"] for r in history["runs"] if r["kind"] == "planning"
            } == {"COMPLETED", "FAILED"}
            row = next(r for r in history["runs"] if r["kind"] == "research")
            assert len(row["manifest_files"]) == 2
            # Prefer the canonical copy with results; mirrored manifests must not
            # hide valid result files because their own folder lacks the bytes.
            assert row["results"] == [str(native / "sample.result.json")]
            loaded = await client.call_tool(
                "read_research_result", {"result": row["results"][0]}
            )
            assert loaded.structured_content["artifact_id"] == result["artifact_id"]
            assert loaded.structured_content["network_access"] is False
            exported = await client.call_tool(
                "export_research_results",
                {
                    "results": row["results"],
                    "name": "history-reuse",
                    "formats": ["markdown", "csv", "jsonl"],
                },
            )
            assert exported.structured_content["ok"]
            assert exported.structured_content["network_access"] is False
            out = Path(exported.structured_content["directory"])
            assert all(
                (out / name).is_file()
                for name in exported.structured_content["outputs"]
            )
            denied = await client.call_tool(
                "list_research_runs", {"directory": str(tmp_path / "outside")}
            )
            assert denied.structured_content == {
                "ok": False,
                "error": "path_outside_allowed_directories",
            }

    asyncio.run(run())
    assert parent.read_bytes() == original_bytes


def test_stdio_background_preparation_partial_reuse_and_scope(tmp_path, monkeypatch):
    papers = tmp_path / "论文"
    papers.mkdir()
    workspace = tmp_path / "results"
    selected = []
    for number in range(2):
        pdf = papers / f"方法{number}.pdf"
        write_pdf(
            pdf,
            [[(50, 700, 12, f"Self-authored method {number}: measured at 25 C.")]],
            title=f"Method {number}",
        )
        selected.append(str(pdf))
    broken = papers / "损坏.pdf"
    broken.write_bytes(b"not a PDF")
    selected.append(str(broken))
    original_hashes = {Path(p): sha256_file(Path(p)) for p in selected}
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

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
                str(workspace),
            ],
            env={
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        async with Client(params, read_timeout_seconds=30) as client:

            async def wait(job_id):
                deadline = asyncio.get_running_loop().time() + 20
                while asyncio.get_running_loop().time() < deadline:
                    reply = await client.call_tool("get_run_status", {"job_id": job_id})
                    assert not reply.is_error and reply.structured_content["ok"]
                    status = reply.structured_content
                    if status["status"] not in {"QUEUED", "RUNNING"}:
                        return status
                    await asyncio.sleep(0.05)
                pytest.fail("background preparation did not finish")

            created = await client.call_tool(
                "prepare_documents_job", {"paths": selected}
            )
            assert not created.is_error and created.structured_content["ok"]
            first_id = created.structured_content["job_id"]
            first = await wait(first_id)
            assert first["kind"] == "preparation" and first["status"] == "PARTIAL"
            assert first["completed"] == first["total"] == 3
            assert len(first["documents"]) == 2 and len(first["failures"]) == 1
            assert first["items"][-1]["path"] == str(broken.resolve())
            assert first["latest_document"]["status"] == "FAILED"
            assert first["model_calls"] == 0 and first["network_access"] is False
            protected = {
                Path(document[key]): sha256_file(Path(document[key]))
                for document in first["documents"]
                for key in ("pdf", "sidecar", "artifact")
            }
            second_job = await client.call_tool(
                "prepare_documents_job", {"paths": selected}
            )
            second_id = second_job.structured_content["job_id"]
            assert second_id != first_id
            second = await wait(second_id)
            assert second["status"] == "PARTIAL"
            assert second["documents"] == first["documents"]
            assert all(
                item["reused"]
                for item in second["items"]
                if item["status"] == "PREPARED"
            )
            assert {p: sha256_file(p) for p in protected} == protected
            before = set((workspace / "jobs").iterdir())
            denied = await client.call_tool(
                "prepare_documents_job",
                {"paths": [selected[0], str(tmp_path / "outside.pdf")]},
            )
            assert denied.structured_content == {
                "ok": False,
                "error": "path_outside_allowed_directories",
            }
            assert set((workspace / "jobs").iterdir()) == before
            old = await client.call_tool("get_run_status", {"job_id": first_id})
            assert old.structured_content == first

    asyncio.run(run())
    assert {p: sha256_file(p) for p in original_hashes} == original_hashes


def test_stdio_local_tools_and_permissions(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    workspace = tmp_path / "results"
    original = papers / "原始论文.pdf"
    write_pdf(
        original,
        [
            [
                (50, 730, 15, "Original paper"),
                (50, 650, 12, "A sample was measured at 25 C."),
            ]
        ],
        title="Original paper",
    )
    fixture_app = ResearchApplication([papers], workspace)
    try:
        parent_path, parent = save_fixture_result(fixture_app, original)
    finally:
        fixture_app.close()
    parent_bytes = parent_path.read_bytes()

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
                str(workspace),
            ],
            env={
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        async with Client(
            params,
            read_timeout_seconds=30,
            client_info=Implementation(name="revision-sdk-test", version="1"),
        ) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {
                "list_documents",
                "update_document_tags",
                "find_paper_candidates",
                "get_acquisition_status",
                "acquire_documents",
                "prepare_documents",
                "prepare_documents_job",
                "import_local_document",
                "parse_document",
                "draft_research_task",
                "validate_research_task",
                "execute_research_task",
                "get_run_status",
                "export_research_results",
                "search_documents",
                "read_document_context",
                "read_native_table",
                "get_parse_diagnostics",
                "read_research_result",
                "revise_research_result",
                "list_research_runs",
                "read_original_page",
                "read_original_page_text",
            }
            result = await client.call_tool(
                "list_documents", {"directory": str(papers)}
            )
            assert not result.is_error
            assert len(result.structured_content["documents"]) == 1
            denied = await client.call_tool(
                "acquire_documents", {"papers": [{"doi": "10.5555/disabled"}]}
            )
            assert denied.structured_content["error"] == "network_disabled"
            imported = await client.call_tool(
                "import_local_document",
                {
                    "pdf": str(original),
                    "title": "Explicit local paper",
                    "doi": "10.1234/local-test",
                },
            )
            assert imported.structured_content["status"] == "REGISTERED"
            assert (
                imported.structured_content["source"]["identity_basis"]
                == "local_declared"
            )
            document = imported.structured_content["document"]
            original_text = await client.call_tool(
                "read_original_page_text", {"document": document, "page": 1}
            )
            assert not original_text.is_error
            native = original_text.structured_content
            assert native["ok"] and "25 C" in native["text"]
            assert native["network_access"] is False
            assert native["extraction"]["mode"] == "layout"
            clipped = await client.call_tool(
                "read_original_page_text",
                {"document": document, "page": 1, "max_characters": 8},
            )
            assert clipped.structured_content["text_truncated"]
            bad_page = await client.call_tool(
                "read_original_page_text", {"document": document, "page": 2}
            )
            assert bad_page.structured_content == {
                "ok": False,
                "error": "page_out_of_bounds",
            }
            source_status = await client.call_tool(
                "get_acquisition_status",
                {"sidecar": document["sidecar"], "pdf": document["pdf"]},
            )
            assert source_status.structured_content["recorded_status"] == "REGISTERED"
            check = source_status.structured_content["current_check"]
            assert check["status"] == "PASSED" and check["identity_verified"] is False
            assert source_status.structured_content["network_access"] is False
            receipt_only = await client.call_tool(
                "get_acquisition_status", {"sidecar": document["sidecar"]}
            )
            assert (
                receipt_only.structured_content["current_check"]["status"]
                == "NOT_CHECKED"
            )
            parsed = await client.call_tool(
                "parse_document", {"document": imported.structured_content["document"]}
            )
            assert parsed.structured_content["status"] in {"PARSED", "PARTIAL"}
            assert parsed.structured_content["document"]["artifact"].endswith(
                ".parsed.json"
            )
            assert parsed.structured_content["network_access"] is False
            prepared = await client.call_tool(
                "prepare_documents", {"paths": [str(original)]}
            )
            documents = prepared.structured_content["documents"]
            assert (
                len(documents) == 1
                and prepared.structured_content["network_access"] is False
            )
            searched = await client.call_tool(
                "search_documents", {"documents": documents, "query": "measured"}
            )
            assert searched.structured_content["hits"]
            hit = searched.structured_content["hits"][0]
            context = await client.call_tool(
                "read_document_context",
                {
                    "document": documents[0],
                    "block_ids": hit["block_ids"],
                    "context_pages": 0,
                },
            )
            assert context.structured_content["evidence"]["included"]
            diagnostics = await client.call_tool(
                "get_parse_diagnostics", {"document": documents[0]}
            )
            assert diagnostics.structured_content["source_check"]["ok"]
            image = await client.call_tool(
                "read_original_page", {"document": documents[0], "page": 1}
            )
            if shutil.which("pdftoppm"):
                assert not image.is_error
                png = next(c for c in image.content if c.type == "image")
                assert base64.b64decode(png.data).startswith(b"\x89PNG")
                region = await client.call_tool(
                    "read_original_page",
                    {"document": documents[0], "page": 1, "region": [0, 0, 0.6, 0.4]},
                )
                assert not region.is_error
                region_meta = json.loads(
                    next(c.text for c in region.content if c.type == "text")
                )
                cropped_png = base64.b64decode(
                    next(c.data for c in region.content if c.type == "image")
                )
                assert region_meta["source_view"]["requested_region"] == [
                    0,
                    0,
                    0.6,
                    0.4,
                ]
                assert (
                    region_meta["source_view"]["coordinates"]
                    == "displayed-cropbox-normalized-top-left"
                )
                assert region_meta["network_access"] is False
                assert (
                    list(struct.unpack(">II", cropped_png[16:24]))
                    == region_meta["source_view"]["crop_pixels_xywh"][2:]
                )
            else:
                assert image.is_error
            invalid_region = await client.call_tool(
                "read_original_page",
                {"document": documents[0], "page": 1, "region": [0, 0, 2, 1]},
            )
            assert invalid_region.is_error
            assert (
                json.loads(invalid_region.content[0].text)["error"]
                == "invalid_page_region"
            )
            history = await client.call_tool("list_research_runs", {})
            assert history.structured_content["runs"] == []
            revision_tool = next(
                t for t in tools.tools if t.name == "revise_research_result"
            )
            assert set(revision_tool.input_schema["properties"]) == {
                "result",
                "revision",
            }
            claim = deepcopy(parent["response"]["claims"][0])
            claim["text"] = "所供材料报告25 C测量，仍待研究者确认"
            revision = {
                "claim_index": 0,
                "replacement": claim,
                "reason": "明确适用范围",
            }
            revised = await client.call_tool(
                "revise_research_result",
                {"result": str(parent_path), "revision": revision},
            )
            assert revised.structured_content["ok"], revised.structured_content
            assert revised.structured_content["network_access"] is False
            child = await client.call_tool(
                "read_research_result", {"result": revised.structured_content["result"]}
            )
            audit = child.structured_content["history"][-1]
            assert audit["author"] == "MCP client: revision-sdk-test (1)"
            assert audit["authority"] == "assistant" and audit["confirm"] is False
            assert (
                child.structured_content["validation"]["claim_states"]["0"]
                == "review_required"
            )
            for arguments in (
                {"result": str(parent_path), "revision": {**revision, "confirm": True}},
                {
                    "result": str(parent_path),
                    "revision": revision,
                    "authority": "human",
                },
                {"result": str(parent_path), "revision": revision, "confirm": True},
            ):
                rejected = await client.call_tool("revise_research_result", arguments)
                assert rejected.structured_content == {
                    "ok": False,
                    "error": "ValueError",
                }
            assert parent_path.read_bytes() == parent_bytes
            task = task_for(documents)
            drafted = await client.call_tool("draft_research_task", {"task": task})
            assert drafted.structured_content["task"]["fields"][0]["label"] == "方法"
            preview = await client.call_tool("validate_research_task", {"task": task})
            assert "研究目标" in preview.structured_content["plan"]
            started = await client.call_tool("execute_research_task", {"task": task})
            job_id = started.structured_content["job_id"]
            for _ in range(100):
                status = await client.call_tool("get_run_status", {"job_id": job_id})
                if status.structured_content["status"] not in {"QUEUED", "RUNNING"}:
                    break
                await asyncio.sleep(0.05)
            assert status.structured_content["status"] == "PREPARED"
            assert status.structured_content["manifest"]["usage"]["http_attempts"] == 0
            remote_task = task_for(documents, mode="parsed")
            denied = await client.call_tool(
                "execute_research_task", {"task": remote_task}
            )
            assert denied.structured_content["error"] == "remote_disabled"
            outside = await client.call_tool(
                "list_documents", {"directory": str(tmp_path)}
            )
            assert outside.structured_content == {
                "ok": False,
                "error": "path_outside_allowed_directories",
            }
            escaped = {**document, "pdf": str(tmp_path / "outside.pdf")}
            denied_text = await client.call_tool(
                "read_original_page_text", {"document": escaped, "page": 1}
            )
            assert denied_text.structured_content == {
                "ok": False,
                "error": "path_outside_allowed_directories",
            }
            private = await client.call_tool(
                "list_documents", {"directory": str(workspace / ".authorizations")}
            )
            assert (
                private.structured_content["error"] == "authorization_directory_private"
            )

    asyncio.run(run())
