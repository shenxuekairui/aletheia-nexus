"""Free synthetic workflow checks, not scientific accuracy measurements."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import httpx
import pytest
from test_workflow import MockProvider, response_for, task_for
from test_workflow import papers as papers

from aletheia_nexus.processing import source_first
from aletheia_nexus.processing.contracts import (
    FIELD_ONLY_INSTRUCTION,
    PROMPT,
    TEXT,
    digest,
    obj,
    validate_task,
)
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.provider import (
    CallBudget,
    DeepSeekProvider,
)
from aletheia_nexus.research_app import ResearchApplication


def inventory_for(request):
    document = request["material"]["documents"][0]
    block = next(b for b in document["blocks"] if "Synthesis lasted" in b["text"])
    return {
        "items": [
            {
                "observation": block["text"],
                "subject_stage": "sample synthesis",
                "evidence_type": "experimental",
                "page": block["page"],
                "quote": block["text"],
                "field_ids": [f["id"] for f in request["fields"]],
                "source_id": document["id"],
            }
        ]
    }


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


def source_task(papers):
    task = task_for(papers[:1])
    task["extraction_strategy"] = "source_first"
    task["budget"].update(max_repair_rounds=0, max_supplement_rounds=0)
    return task


def generate(request):
    if request["phase"] == source_first.INVENTORY_PHASE:
        return inventory_for(request)
    return response_for(request)


@pytest.mark.parametrize("include_claims", [True, False])
def test_real_adapter_two_stages_same_original_images_and_saved_lineage(
    papers, tmp_path, monkeypatch, include_claims
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-secret")
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"synthetic-page-image",
    )
    task = source_task(papers)
    task["include_claims"] = include_claims
    task["mode"] = "hybrid"
    task["documents"][0]["image_pages"] = [1]
    task["model"] = {
        "name": "deepseek-flash",
        "max_retries": 0,
        "min_interval_seconds": 0,
        "input_cost_per_million": 2,
        "output_cost_per_million": 8,
    }
    captures = []

    def handler(request):
        payload = json.loads(request.content)
        req = json.loads(payload["input"][0]["content"][0]["text"])
        captures.append((req, payload))
        answer = generate(req)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(answer)}
                        ],
                    }
                ],
            },
        )

    provider = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    result = run(task, tmp_path / "output", provider)
    assert result["status"] == "COMPLETED"
    assert len(captures) == len(result["calls"]) == 2
    first, second = captures
    assert first[0]["material"] == second[0]["material"]
    assert first[0]["phase"] == source_first.INVENTORY_PHASE
    assert second[0]["phase"] == "document_extraction"
    assert set(first[1]["text"]["format"]["schema"]["properties"]) == {"items"}
    assert set(second[1]["text"]["format"]["schema"]["properties"]) == {
        "records",
        "claims",
        "issues",
        "requests",
    }
    if not include_claims:
        assert "instruction" not in first[0]
        assert second[0]["instruction"] == FIELD_ONLY_INSTRUCTION
    assert first[1]["input"][0]["content"][1:] == second[1]["input"][0]["content"][1:]
    assert source_first.INVENTORY_PROMPT in first[1]["instructions"]
    assert source_first.ASSEMBLY_PROMPT in second[1]["instructions"]
    assert second[0]["ai_reading_draft"]["items"] == inventory_for(first[0])["items"]
    assert result["usage"]["input_tokens"] == 200
    assert result["usage"]["estimated_cost"] > 0
    assert (
        result["calls"][0]["effective_prompt_sha256"]
        != result["calls"][1]["effective_prompt_sha256"]
    )
    item = result["items"][0]
    artifact = read(
        Path(result["run_directory"]) / item["source_inventories"][0]["file"]
    )
    assert artifact["owner_call_indices"] == [0]
    assert artifact["binding"]["version"] == "source-first/2"
    assert artifact["binding"]["request"] == first[0]
    if not include_claims:
        legacy = deepcopy(artifact["binding"])
        legacy["request"]["instruction"] = FIELD_ONLY_INSTRUCTION
        assert digest(legacy) != digest(artifact["binding"])
    assert artifact["response"] == artifact["raw_response"]
    assert list(Path(result["run_directory"]).glob("*.source-inventory.input.json"))
    assert list(
        Path(result["run_directory"]).glob("*.source-first-assembly.input.json")
    )
    assert result["outputs"]
    cached = run(task, tmp_path / "output", provider)
    assert cached["items"][0]["reused"] and len(captures) == 2
    assert cached["items"][0]["source_inventories"]


def test_inventory_preserves_other_instructions_and_original_request():
    request = {
        "phase": "document_extraction",
        "instruction": "Use the supplied page scope.",
        "include_claims": False,
        "material": {"documents": []},
    }
    before = deepcopy(request)
    assert (
        source_first.inventory_request(request)["instruction"] == request["instruction"]
    )
    assert request == before


def test_inventory_survives_failed_assembly_without_repaying_reading(
    papers, tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-secret")
    state = {"failed": False}
    captures = []

    def handler(request):
        payload = json.loads(request.content)
        supplied = json.loads(payload["input"][0]["content"][0]["text"])
        captures.append(supplied)
        if supplied["phase"] == source_first.ASSEMBLY_PHASE and not state["failed"]:
            state["failed"] = True
            raise httpx.ReadTimeout("synthetic transport failure", request=request)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(generate(supplied)),
                            }
                        ],
                    }
                ],
            },
        )

    task = source_task(papers)
    task["model"] = {
        "name": "deepseek-flash",
        "max_retries": 0,
        "min_interval_seconds": 0,
        "input_cost_per_million": 2,
        "output_cost_per_million": 8,
    }
    provider = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    output = tmp_path / "recover"
    failed = run(task, output, provider)
    assert failed["items"][0]["error"] == "timeout"
    recovered = run(task, output, provider)
    assert recovered["status"] == "COMPLETED"
    assert [r["phase"] for r in captures] == [
        source_first.INVENTORY_PHASE,
        source_first.ASSEMBLY_PHASE,
        source_first.ASSEMBLY_PHASE,
    ]
    trace = recovered["items"][0]["source_inventories"][0]
    assert trace["reused"]
    assert trace["usage_owner_run"] == failed["run_directory"]
    assert len(recovered["calls"]) == 1
    original = read(Path(failed["run_directory"]) / "manifest.json")
    assert len(original["calls"]) == 2
    assert original["calls"][1]["status"] == "timeout"
    assert original["calls"][1]["usage"] is None
    assert original["calls"][1]["reserved_cost"] > 0
    assert original["usage"]["unknown_usage_calls"] == 1


@pytest.mark.parametrize("change", ["task", "material", "model", "prompt"])
def test_inventory_exact_fingerprint_changes_invalidate(
    papers, tmp_path, monkeypatch, change
):
    task = source_task(papers)
    task["model"] = {"name": "synthetic-model"}
    provider = MockProvider(generate)
    output = tmp_path / "fingerprint"
    assert run(task, output, provider)["status"] == "COMPLETED"
    altered = deepcopy(task)
    if change == "task":
        altered["objective"] += " Include the requested context."
    elif change == "material":
        altered["documents"][0]["notes"] = ["User supplied annotation."]
    elif change == "model":
        altered["model"]["name"] = "other-synthetic-model"
    else:
        monkeypatch.setattr(source_first, "SOURCE_FIRST_VERSION", "source-first/test-2")
    assert run(altered, output, provider)["status"] == "COMPLETED"
    assert len(provider.requests) == 4


def test_both_stages_share_call_limit_without_automatic_increase(papers, tmp_path):
    task = source_task(papers)
    task["budget"]["max_calls"] = 1
    provider = MockProvider(generate)
    result = run(task, tmp_path / "limited", provider)
    assert result["items"][0]["error"] == "call_budget_exhausted"
    assert len(result["calls"]) == 1
    assert result["items"][0]["source_inventories"]
    assert "result" not in result["items"][0]


def test_both_stages_share_cost_limit(papers, tmp_path):
    class PricedProvider(MockProvider):
        def generate(self, request, schema, images, budget, max_output_tokens):
            row = budget.reserve(0.6)
            self.requests.append(deepcopy(request))
            row.update(
                status="completed",
                usage={"input_tokens": 10, "output_tokens": 10},
                estimated_cost=0.1,
            )
            return generate(request)

    task = source_task(papers)
    task["model"] = {
        "name": "synthetic-model",
        "input_cost_per_million": 1,
        "output_cost_per_million": 1,
    }
    task["budget"]["max_cost"] = 0.65
    provider = PricedProvider()
    result = run(task, tmp_path / "cost-limited", provider)
    assert result["items"][0]["error"] == "cost_budget_exhausted"
    assert len(result["calls"]) == 1 and len(provider.requests) == 1
    assert result["usage"]["estimated_cost"] == 0.1


def test_source_first_reuses_original_material_supplement_loop(
    papers, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"synthetic-page-" + str(page).encode(),
    )
    task = source_task(papers)
    task["mode"] = "hybrid"
    task["documents"][0].update(pages=[1], image_pages=[1])
    task["budget"]["max_supplement_rounds"] = 1

    def supplement(request):
        answer = generate(request)
        if request["phase"] == source_first.ASSEMBLY_PHASE and not request.get(
            "evidence_update"
        ):
            answer["requests"] = [
                {
                    "source_id": "paper0",
                    "pages": [2],
                    "reason": "Read selected test context",
                }
            ]
        return answer

    provider = MockProvider(supplement)
    result = run(task, tmp_path / "supplement", provider)
    assert result["status"] == "COMPLETED"
    assert [r["phase"] for r in provider.requests] == [
        source_first.INVENTORY_PHASE,
        source_first.ASSEMBLY_PHASE,
        source_first.INVENTORY_PHASE,
        source_first.ASSEMBLY_PHASE,
    ]
    assert provider.requests[2]["material"] == provider.requests[3]["material"]
    assert provider.requests[3]["evidence_update"]["current_coverage"][0][
        "added_image_pages"
    ] == [2]
    assert len(result["items"][0]["source_inventories"]) == 2


def test_direct_and_local_preserve_old_contract_and_call_count(papers, tmp_path):
    task = task_for(papers[:1])
    assert "extraction_strategy" not in validate_task(task)
    provider = MockProvider(generate)
    assert run(task, tmp_path / "direct", provider)["status"] == "COMPLETED"
    assert [r["phase"] for r in provider.requests] == ["document_extraction"]
    local = source_task(papers)
    local["mode"] = "local"
    assert run(local, tmp_path / "local", provider)["status"] == "PREPARED"
    assert len(provider.requests) == 1
    plan = ResearchApplication.plan(validate_task(source_task(papers)), [])
    assert "至少2次模型调用" in plan and "不自动加预算" in plan


def test_provider_prompts_are_request_local_under_concurrency(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-secret")
    barrier = Barrier(3)
    captures = []

    def handler(request):
        payload = json.loads(request.content)
        req = json.loads(payload["input"][0]["content"][0]["text"])
        barrier.wait(timeout=5)
        captures.append((req["test_case"], payload["instructions"]))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"value":"ok"}'}],
                    }
                ],
            },
        )

    provider = DeepSeekProvider(
        {"name": "synthetic-model", "max_retries": 0, "min_interval_seconds": 0},
        enabled=True,
        transport=httpx.MockTransport(handler),
    )
    requests = [
        {"phase": source_first.INVENTORY_PHASE, "test_case": "inventory"},
        source_first.assembly_request(
            {"phase": "document_extraction", "test_case": "assembly"}, {"items": []}
        ),
        {"phase": "document_extraction", "test_case": "direct"},
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        answers = list(
            pool.map(
                lambda request: provider.generate(
                    request, obj({"value": TEXT}), [], CallBudget(1), 100
                ),
                requests,
            )
        )
    assert answers == [{"value": "ok"}] * 3
    expected = {
        "inventory": source_first.INVENTORY_PROMPT,
        "assembly": source_first.ASSEMBLY_PROMPT,
        "direct": PROMPT,
    }
    for stage, instructions in captures:
        assert instructions.startswith(expected[stage])
        if stage == "direct":
            assert "reading draft" not in instructions


def test_inventory_location_validation_does_not_accept_invented_source(
    papers, tmp_path
):
    def invalid(request):
        if request["phase"] != source_first.INVENTORY_PHASE:
            pytest.fail("invalid inventory must not reach assembly")
        answer = inventory_for(request)
        answer["items"][0]["page"] = 999
        return answer

    result = run(source_task(papers), tmp_path / "invalid", MockProvider(invalid))
    assert result["items"][0]["status"] == "FAILED"
    assert list(Path(result["run_directory"]).glob("*.source-inventory.candidate.json"))
