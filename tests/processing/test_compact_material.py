"""Synthetic material/transport checks; no scientific accuracy measurement."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_source_first import generate, source_task
from test_workflow import MockProvider, response_for, review_for, task_for
from test_workflow import papers as papers

from aletheia_nexus.processing import presentation
from aletheia_nexus.processing.contracts import digest, validate_task
from aletheia_nexus.processing.engine import _request, run_task
from aletheia_nexus.processing.materials import build_package, load_source
from aletheia_nexus.processing.presentation import compact_material, decompress_material
from aletheia_nexus.processing.provider import DeepSeekProvider


def read(path):
    return json.loads(Path(path).read_text("utf-8"))


def run(task, output, provider):
    return run_task(
        task,
        base_dir=output.parent,
        output_dir=output,
        allow_remote=True,
        provider=provider,
    )


def test_roundtrip_preserves_types_text_order_tables_and_nondefault_values():
    blocks = [
        {
            "id": "b1",
            "text": "μmol, Na₂CO₃, 0.08 ≠ .008",
            "page": 2,
            "kind": "paragraph",
            "uncertain": False,
            "content_region": "body",
        },
        {
            "id": "b2",
            "text": "caption",
            "page": 2,
            "kind": "caption",
            "uncertain": True,
            "content_region": "figure",
        },
    ]
    for value in [None, 0, "false"]:
        blocks.append(
            {
                "id": str(value),
                "text": "unchanged",
                "page": 2,
                "kind": None,
                "uncertain": value,
                "content_region": None,
            }
        )
    request = {
        "fields": [{"id": "x"}],
        "material": {
            "documents": [
                {
                    "id": "main",
                    "blocks": blocks,
                    "tables": [{"cells": [[0, None, "μ"]]}],
                    "figures": [{"source_regions": [1, 2]}],
                    "notes": ["literal"],
                },
                {"id": "si", "blocks": [], "tables": []},
            ],
            "images": [{"source_id": "main", "page": 2, "sha256": "image-hash"}],
        },
    }
    before = deepcopy(request)
    compact = compact_material(request)
    assert request == before and decompress_material(compact) == before
    assert compact["material"]["documents"][0]["blocks"][0] == {
        "id": "b1",
        "text": "μmol, Na₂CO₃, 0.08 ≠ .008",
        "page": 2,
    }
    assert compact["material"]["documents"][0]["blocks"][1:] == blocks[1:]
    with pytest.raises(ValueError, match="already"):
        compact_material(compact)


def test_optional_contract_keeps_omission_and_rejects_unknown_mode(papers):
    raw = task_for(papers[:1])
    normal = validate_task(raw)
    assert "material_presentation" not in normal
    assert presentation.presentation_identity(normal) == {}
    compact = validate_task({**raw, "material_presentation": "compact"})
    assert compact["material_presentation"] == "compact"
    assert digest(normal) != digest(compact)
    with pytest.raises(ValueError):
        validate_task({**raw, "material_presentation": "drop_text"})


def test_real_two_stage_serializer_saved_requests_and_cache_isolation(
    papers, tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-secret")
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"same-image-bytes",
    )
    task = source_task(papers)
    task["mode"] = "hybrid"
    task["documents"][0]["image_pages"] = [1]
    task["model"] = {
        "name": "deepseek-flash",
        "max_retries": 0,
        "min_interval_seconds": 0,
    }
    captures = []

    def handler(http_request):
        wire = json.loads(http_request.content)
        request = json.loads(wire["input"][0]["content"][0]["text"])
        captures.append((request, wire))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(generate(request)),
                            }
                        ],
                    }
                ],
            },
        )

    provider = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    out = tmp_path / "same-cache"
    normal = run(task, out, provider)
    assert normal["status"] == "COMPLETED" and len(captures) == 2
    compact_task = {**task, "material_presentation": "compact"}
    compact = run(compact_task, out, provider)
    assert compact["status"] == "COMPLETED" and len(captures) == 4
    assert "material_presentation" not in normal["provider"]
    assert compact["provider"]["material_presentation_version"] == presentation.VERSION
    directory = Path(compact["run_directory"])
    for n, ((normal_req, normal_wire), (compact_req, compact_wire)) in enumerate(
        zip(captures[:2], captures[2:], strict=True)
    ):
        expanded = decompress_material(compact_req)
        # Package identity includes task fingerprint; only this derived ID changes.
        expanded["material"]["artifact_id"] = normal_req["material"]["artifact_id"]
        assert expanded == normal_req
        assert normal_wire["instructions"] == compact_wire["instructions"]
        assert normal_wire["text"] == compact_wire["text"]
        assert (
            normal_wire["input"][0]["content"][1:]
            == compact_wire["input"][0]["content"][1:]
        )
        assert compact["calls"][n]["input_sha256"] == digest(compact_req)
    binding = read(directory / "paper0.0.source-inventory.input.json")
    assert binding["request"] == captures[2][0]
    assert read(directory / "paper0.0.request.json")["request"] == captures[3][0]
    result = read(directory / compact["items"][0]["result"])
    package = result["package"]
    assert "compact_version" not in package
    assert all("kind" in b for b in package["documents"][0]["blocks"])
    assert result["response"] == response_for(captures[3][0])
    cached = run(compact_task, out, provider)
    assert cached["items"][0]["reused"] and len(captures) == 4
    assert run(task, out, provider)["items"][0]["reused"] and len(captures) == 4
    monkeypatch.setattr(presentation, "VERSION", "compact-material/test-next")
    assert run(compact_task, out, provider)["status"] == "COMPLETED"
    assert len(captures) == 6  # A new presentation cannot reuse either old cache.


def test_failed_assembly_reuses_compact_inventory_without_new_owner_fee(
    papers, tmp_path
):
    task = {**source_task(papers), "material_presentation": "compact"}
    fail = True

    def answer(request):
        nonlocal fail
        if request["phase"] == "document_extraction" and fail:
            fail = False
            return {"wrong_schema": True}
        return generate(request)

    provider = MockProvider(answer)
    out = tmp_path / "recover"
    first = run(task, out, provider)
    assert first["status"] == "FAILED"
    second = run(task, out, provider)
    assert second["status"] == "COMPLETED"
    assert [x["phase"] for x in provider.requests] == [
        "source_evidence_inventory",
        "document_extraction",
        "document_extraction",
    ]
    inventory = second["items"][0]["source_inventories"][0]
    assert (
        inventory["reused"] and inventory["usage_owner_run"] == first["run_directory"]
    )
    assert len(first["calls"]) == 2 and len(second["calls"]) == 1
    assert provider.requests[1] == provider.requests[2]


def test_direct_empty_blocks_and_local_mode_remain_local(papers, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"same-direct-image",
    )
    task = task_for(papers[:1], mode="direct")
    task["material_presentation"] = "compact"
    task["documents"][0] = {"id": "paper0", "pdf": str(papers[0]), "pages": [1]}
    task = validate_task(task)
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, images = build_package(task, [source])
    full_request = _request(
        {k: v for k, v in task.items() if k != "material_presentation"}, package
    )
    assert decompress_material(_request(task, package)) == full_request
    assert full_request["material"]["documents"][0]["blocks"] == []
    assert images[0]["bytes"] == b"same-direct-image"

    def forbidden(*args, **kwargs):
        raise AssertionError("local mode must not create a remote provider")

    monkeypatch.setattr("aletheia_nexus.processing.engine.DeepSeekProvider", forbidden)
    local = {**task_for(papers[:1], mode="local"), "material_presentation": "compact"}
    result = run_task(local, base_dir=tmp_path, output_dir=tmp_path / "local")
    assert result["status"] == "PREPARED" and result["calls"] == []


def test_supplement_keeps_original_package_and_compact_actual_request(papers, tmp_path):
    task = task_for(papers[:1])
    task["material_presentation"] = "compact"
    task["documents"][0]["pages"] = [1]

    def answer(request):
        result = response_for(request)
        if "evidence_update" not in request:
            result["requests"] = [
                {
                    "source_id": "paper0",
                    "pages": [2],
                    "reason": "Read the test conditions",
                }
            ]
        return result

    provider = MockProvider(answer)
    manifest = run(task, tmp_path / "supplement", provider)
    assert manifest["status"] == "COMPLETED" and len(provider.requests) == 2
    first, second = provider.requests
    assert second["material"]["compact_version"] == presentation.VERSION
    assert second["evidence_update"]["current_coverage"][0]["added_text_pages"] == [2]
    assert {
        b["page"]
        for b in decompress_material(second)["material"]["documents"][0]["blocks"]
    } == {1, 2}
    assert {
        b["page"]
        for b in decompress_material(first)["material"]["documents"][0]["blocks"]
    } == {1}
    directory = Path(manifest["run_directory"])
    assert read(directory / "paper0.1.request.json")["request"] == second


def test_review_and_comparison_save_compact_requests_and_reuse_cache(papers, tmp_path):
    task = task_for(papers, kind="compare")
    task["material_presentation"] = "compact"
    task["budget"]["max_review_rounds"] = 1

    def answer(request):
        if request["phase"] == "cross_document_synthesis":
            return {
                "claims": [
                    {
                        "text": "Both supplied examples describe synthesis.",
                        "nature": "ai_synthesis",
                        "citations": [
                            r["records"][0]["fields"]["method"]["citations"][0]
                            for r in request["extractions"]
                        ],
                    }
                ],
                "issues": [],
            }
        return (
            review_for(request)
            if request["phase"] == "evidence_review"
            else response_for(request)
        )

    provider = MockProvider(answer)
    output = tmp_path / "compare"
    manifest = run(task, output, provider)
    assert manifest["status"] == "COMPLETED"
    assert {r["phase"] for r in provider.requests} == {
        "document_extraction",
        "evidence_review",
        "cross_document_synthesis",
    }
    saved = [
        read(path)["request"]
        for path in Path(manifest["run_directory"]).glob("*.request.json")
    ]
    assert sorted(map(digest, saved)) == sorted(map(digest, provider.requests))
    assert all(r["material"]["compact_version"] == presentation.VERSION for r in saved)
    calls = len(provider.requests)
    cached = run(task, output, provider)
    assert cached["comparison"]["reused"] and len(provider.requests) == calls
