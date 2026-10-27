"""Real SDK v2 subprocess transport, not merely direct Python function calls."""

import asyncio
import base64
import shutil
import sys

import pytest
from test_research_app import task_for, write_pdf

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters


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
        async with Client(params, read_timeout_seconds=30) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {
                "list_documents",
                "get_acquisition_status",
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
                "list_research_runs",
                "read_original_page",
            }
            result = await client.call_tool(
                "list_documents", {"directory": str(papers)}
            )
            assert not result.is_error
            assert len(result.structured_content["documents"]) == 1
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
            else:
                assert image.is_error
            history = await client.call_tool("list_research_runs", {})
            assert history.structured_content["runs"] == []
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
            private = await client.call_tool(
                "list_documents", {"directory": str(workspace / ".authorizations")}
            )
            assert (
                private.structured_content["error"] == "authorization_directory_private"
            )

    asyncio.run(run())
