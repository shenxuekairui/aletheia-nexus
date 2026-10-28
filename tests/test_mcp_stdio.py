"""Real SDK v2 subprocess transport, not merely direct Python function calls."""

import asyncio
import base64
import json
import shutil
import struct
import sys
from copy import deepcopy

import pytest
from test_research_app import task_for, write_pdf
from test_research_revision_app import save_fixture_result

from aletheia_nexus.research_app import ResearchApplication

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters
from mcp.types import Implementation


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
        )
        async with Client(
            params,
            read_timeout_seconds=30,
            client_info=Implementation(name="revision-sdk-test", version="1"),
        ) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {
                "list_documents",
                "get_acquisition_status",
                "acquire_documents",
                "prepare_documents",
                "import_local_document",
                "parse_document",
                "draft_research_task",
                "validate_research_task",
                "execute_research_task",
                "get_run_status",
                "export_research_results",
                "search_documents",
                "read_document_context",
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
