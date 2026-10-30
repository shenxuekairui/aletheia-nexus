"""Official SDK connection: title candidates, independent grant, chosen DOI acquisition."""

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


def test_sdk_title_candidates_and_explicit_selected_doi(tmp_path, monkeypatch, capsys):
    papers, workspace = tmp_path / "论文", tmp_path / "结果"
    papers.mkdir()
    pdf = papers / "自编.pdf"
    FIXTURE["_write_pdf"](
        pdf,
        [
            [
                (50, 730, 15, "Self-authored discovery fixture"),
                (50, 680, 12, "10.5555/title-sdk"),
            ]
        ],
        title="Self-authored discovery fixture",
    )
    FIXTURE["_sidecar"](pdf, "10.5555/title-sdk")
    original = sha256_file(pdf)
    metadata_marker, download_marker = (
        tmp_path / "metadata.txt",
        tmp_path / "downloads.txt",
    )
    helper = Path(__file__).parent / "helpers/mcp_title_discovery_server.py"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def grant(challenge):
        request = read_json(Path(challenge["authorization_request"]))
        assert (
            authorize_main(
                [
                    "authorize",
                    challenge["authorization_request"],
                    "--approve-fingerprint",
                    request["binding"],
                ]
            )
            == 0
        )
        return capsys.readouterr().out.strip().splitlines()[-1]

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                str(helper),
                str(pdf),
                str(metadata_marker),
                str(download_marker),
                "serve",
                "--allow-dir",
                str(papers),
                "--workspace",
                str(workspace),
                "--enable-acquisition",
            ],
            env={
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        async with Client(params, read_timeout_seconds=30) as client:
            assert "find_paper_candidates" in {
                t.name for t in (await client.list_tools()).tools
            }
            query = {"title_query": "Self-authored discovery fixture", "limit": 2}
            challenge = (
                await client.call_tool("find_paper_candidates", query)
            ).structured_content
            assert (
                challenge["status"] == "AUTHORIZATION_REQUIRED"
                and not metadata_marker.exists()
            )
            token = grant(challenge)
            result = (
                await client.call_tool(
                    "find_paper_candidates", {**query, "authorization": token}
                )
            ).structured_content
            assert result["model_calls"] == result["downloads"] == 0
            assert not download_marker.exists() and len(result["candidates"]) == 2
            assert all(not row["identity_verified"] for row in result["candidates"])
            reused = (
                await client.call_tool(
                    "find_paper_candidates", {**query, "authorization": token}
                )
            ).structured_content
            assert reused["error"] == "authorization_missing_or_used"
            selected = result["candidates"][1]
            payload = {"papers": [{"doi": selected["doi"], "title": selected["title"]}]}
            next_challenge = (
                await client.call_tool("acquire_documents", payload)
            ).structured_content
            assert (
                next_challenge["status"] == "AUTHORIZATION_REQUIRED"
                and not download_marker.exists()
            )
            started = (
                await client.call_tool(
                    "acquire_documents",
                    {**payload, "authorization": grant(next_challenge)},
                )
            ).structured_content
            for _ in range(100):
                status = (
                    await client.call_tool(
                        "get_run_status", {"job_id": started["job_id"]}
                    )
                ).structured_content
                if status["status"] not in {"QUEUED", "RUNNING"}:
                    break
                await asyncio.sleep(0.05)
            assert status["status"] == "COMPLETED"
            assert metadata_marker.read_text("utf-8").splitlines() == [
                query["title_query"]
            ]
            assert download_marker.read_text("utf-8").splitlines() == [
                "10.5555/title-sdk"
            ]

    asyncio.run(run())
    assert sha256_file(pdf) == original
