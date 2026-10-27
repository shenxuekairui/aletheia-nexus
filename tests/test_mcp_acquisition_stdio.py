"""SDK stdio acquisition, trusted local CLI grant, source preparation and checkpoint reuse."""

import asyncio
import sys
from pathlib import Path

import pytest
from test_research_acquisition import FIXTURE

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.research_app import read_json
from aletheia_nexus.research_ask import main as authorize_main

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters


def test_sdk_public_acquisition_authorization_and_resume(tmp_path, capsys, monkeypatch):
    papers, workspace = tmp_path / "论文", tmp_path / "结果"
    papers.mkdir()
    original = papers / "自编原始.pdf"
    doi = "10.5555/mcp-acquisition"
    FIXTURE["_write_pdf"](
        original,
        [[(50, 730, 15, "Self-authored acquisition SDK fixture"), (50, 680, 12, doi)]],
        title="Self-authored acquisition SDK fixture",
    )
    FIXTURE["_sidecar"](original, doi)
    before = sha256_file(original)
    marker = tmp_path / "mock-network-calls.txt"
    helper = Path(__file__).parent / "helpers/mcp_public_acquisition_server.py"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def grant(challenge):
        path = Path(challenge["authorization_request"])
        payload = read_json(path)
        assert (
            authorize_main(
                ["authorize", str(path), "--approve-fingerprint", payload["binding"]]
            )
            == 0
        )
        return capsys.readouterr().out.strip().splitlines()[-1]

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                str(helper),
                str(original),
                str(marker),
                "serve",
                "--allow-dir",
                str(papers),
                "--workspace",
                str(workspace),
                "--enable-acquisition",
            ],
        )
        async with Client(params, read_timeout_seconds=30) as client:
            payload = {"papers": [{"doi": doi}]}
            preview = (
                await client.call_tool("acquire_documents", payload)
            ).structured_content
            assert preview["status"] == "AUTHORIZATION_REQUIRED" and not marker.exists()
            token = grant(preview)
            started = (
                await client.call_tool(
                    "acquire_documents", {**payload, "authorization": token}
                )
            ).structured_content

            async def terminal(job):
                for _ in range(100):
                    result = (
                        await client.call_tool("get_run_status", {"job_id": job})
                    ).structured_content
                    if result["status"] not in {"QUEUED", "RUNNING"}:
                        return result
                    await asyncio.sleep(0.05)
                raise AssertionError("mock acquisition did not finish")

            first = await terminal(started["job_id"])
            assert first["status"] == "COMPLETED" and first["model_calls"] == 0
            assert first["items"][0]["identity_verified"] is True
            again = await client.call_tool(
                "acquire_documents", {**payload, "authorization": token}
            )
            assert again.structured_content["error"] == "authorization_missing_or_used"
            resume = {**payload, "resume_job_id": first["job_id"]}
            preview2 = (
                await client.call_tool("acquire_documents", resume)
            ).structured_content
            started2 = (
                await client.call_tool(
                    "acquire_documents", {**resume, "authorization": grant(preview2)}
                )
            ).structured_content
            second = await terminal(started2["job_id"])
            assert second["status"] == "COMPLETED" and second["items"][0]["resumed"]
            assert second["resume_of"] == first["job_id"]
            prepared = await client.call_tool(
                "prepare_documents", {"paths": [second["items"][0]["pdf"]]}
            )
            assert len(prepared.structured_content["documents"]) == 1
            assert marker.read_text("utf-8").splitlines() == [doi]

    asyncio.run(run())
    assert sha256_file(original) == before
