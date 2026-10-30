"""Synthetic local contract/workflow tests, not scientific performance evidence."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_workflow import MockProvider, response_for, task_for
from test_workflow import papers as papers

from aletheia_nexus.processing import readings
from aletheia_nexus.processing.contracts import validate_task
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.provider import DeepSeekProvider
from aletheia_nexus.processing.results import export_results, verify_result
from aletheia_nexus.research_app import ResearchApplication


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def task(papers, **changes):
    config = task_for(papers)
    config.update(
        extraction_strategy="source_first",
        source_assembly="preserve_readings",
        include_steps=False,
        include_claims=False,
    )
    config["budget"].update(max_supplement_rounds=0, max_repair_rounds=0)
    config.update(changes)
    return config


def inventory(request):
    doc = request["material"]["documents"][0]
    block = next(b for b in doc["blocks"] if "Synthesis lasted" in b["text"])
    return {
        "items": [
            {
                "observation": block["text"],
                "subject_stage": "sample / synthesis",
                "evidence_type": "experimental",
                "source_id": doc["id"],
                "page": block["page"],
                "quote": block["text"],
                "field_ids": ["method"],
            }
        ]
    }


def run(config, output, provider):
    return run_task(
        config,
        base_dir=output.parent,
        output_dir=output,
        allow_remote=True,
        provider=provider,
    )


def result(manifest, index=0):
    return read(Path(manifest["run_directory"]) / manifest["items"][index]["result"])


def test_real_serializer_one_call_preserves_all_readings_and_offline_exports(
    papers,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-only")
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"synthetic-image",
    )
    config = task(papers[:1], mode="hybrid")
    config["documents"][0]["image_pages"] = [1]
    config["fields"] += [
        {"id": "notes", "description": "Reading list", "type": "string_list"},
        {"id": "empty", "description": "Unassigned field", "type": "string"},
    ]
    config["model"] = {"name": "synthetic", "max_retries": 0, "min_interval_seconds": 0}
    captured = []
    originals = []

    def handler(request):
        payload = json.loads(request.content)
        supplied = json.loads(payload["input"][0]["content"][0]["text"])
        captured.append(payload)
        assert supplied["phase"] == "source_evidence_inventory"
        assert (
            sum(c["type"] == "input_image" for c in payload["input"][0]["content"]) == 1
        )
        answer = inventory(supplied)
        answer["items"][0]["field_ids"] = ["method", "notes"]
        other = {
            **answer["items"][0],
            "observation": "The source may explain this.",
            "evidence_type": "author_interpretation",
            "subject_stage": "control",
        }
        answer["items"].append(other)
        answer["items"].append(
            {**other, "field_ids": [], "observation": "Unassigned reading."}
        )
        originals.append(deepcopy(answer))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 50, "output_tokens": 30},
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
        config["model"], enabled=True, transport=httpx.MockTransport(handler)
    )
    output = tmp_path / "notes"
    first = run(config, output, provider)
    assert len(first["calls"]) == len(captured) == 1
    saved = result(first)
    verify_result(saved)
    record = saved["response"]["records"][0]
    assert (
        record["id"] == "paper0-readings" and record["stage"] == "source_reading_notes"
    )
    fields = record["fields"]
    for i, item in enumerate(originals[0]["items"][:2]):
        label, observation = fields["notes"]["value"][i].split("\n", 1)
        assert observation == item["observation"]
        assert item["subject_stage"] in label
        assert ("实验观察" if i == 0 else "作者解释") in label
        assert fields["notes"]["citations"][i]["quote"] == item["quote"]
    assert all(
        key not in json.dumps(fields["notes"]["value"])
        for key in ("field_ids", "source_id", "[reading", "source_index")
    )
    assert fields["method"]["value"] == "\n\n".join(fields["notes"]["value"])
    assert fields["empty"]["value"] is None
    assert {f["status"] for f in fields.values()} == {"unconfirmed"}
    assert {f["nature"] for f in fields.values()} == {"ai_synthesis"}
    assert "不代表原文未报告" in fields["empty"]["context"]
    assert "未分配到配置字段" in saved["response"]["issues"][0]["detail"]
    assert "field_ids" not in saved["response"]["issues"][0]["detail"]
    assert (
        originals[0]["items"][2]["observation"]
        not in saved["response"]["issues"][0]["detail"]
    )
    assert saved["response"]["claims"] == record["steps"] == []
    assert "human_confirmed" not in json.dumps(saved["validation"])
    trace = first["items"][0]["source_inventories"][0]
    artifact = read(Path(first["run_directory"]) / trace["file"])
    assert artifact["response"] == artifact["raw_response"] == originals[0]
    indices = json.loads(fields["notes"]["context"].split("条目索引：", 1)[1])
    assert indices == [0, 1]
    for index, note in zip(indices, fields["notes"]["value"], strict=True):
        original = artifact["response"]["items"][index]
        assert note.split("\n", 1)[1] == original["observation"]
        assert original == originals[0]["items"][index]  # Full original lineage.
    unassigned = [
        item for item in artifact["response"]["items"] if not item["field_ids"]
    ]
    assert unassigned == [originals[0]["items"][2]]
    cached = run(config, output, provider)
    assert cached["items"][0]["reused"] and cached["calls"] == [] and len(captured) == 1
    assert (
        cached["items"][0]["source_inventories"][0]["usage_owner_run"]
        == first["run_directory"]
    )
    before = json.dumps(saved, ensure_ascii=False)
    exports = tmp_path / "offline"
    exports.mkdir()
    assert export_results([saved], saved["task"], exports)
    assert len(captured) == 1 and json.dumps(saved, ensure_ascii=False) == before


def test_empty_inventory_is_unconfirmed_not_absence(papers, tmp_path):
    output = run(
        task(papers[:1]), tmp_path / "empty", MockProvider(lambda _: {"items": []})
    )
    fields = result(output)["response"]["records"][0]["fields"]
    assert fields["method"]["status"] == "unconfirmed"
    assert fields["method"]["value"] is None
    assert "not_reported" not in json.dumps(fields)


def test_render_failure_keeps_successful_inventory_without_repaying(
    papers, tmp_path, monkeypatch
):
    from aletheia_nexus.processing import engine

    config = task(papers[:1])
    provider = MockProvider(inventory)
    original = engine.check_response
    monkeypatch.setattr(
        engine,
        "check_response",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("synthetic render rejection")),
    )
    failed = run(config, tmp_path / "recover", provider)
    assert failed["status"] == "FAILED" and len(provider.requests) == 1
    assert list(Path(failed["run_directory"]).glob("*.readings-render.json"))
    assert list(Path(failed["run_directory"]).glob("*.source-inventory.candidate.json"))
    monkeypatch.setattr(engine, "check_response", original)
    recovered = run(config, tmp_path / "recover", provider)
    assert recovered["status"] == "COMPLETED" and recovered["calls"] == []
    assert len(provider.requests) == 1
    assert recovered["items"][0]["source_inventories"][0]["reused"]


def test_unknown_field_rejected_and_raw_reading_retained(papers, tmp_path):
    def invalid(request):
        answer = inventory(request)
        answer["items"][0]["field_ids"] = ["unknown"]
        return answer

    failed = run(task(papers[:1]), tmp_path / "invalid", MockProvider(invalid))
    assert failed["status"] == "FAILED"
    assert failed["items"][0]["error"] == "invalid_source_inventory"
    raw = next(Path(failed["run_directory"]).glob("*.source-inventory.candidate.json"))
    assert read(raw)["items"][0]["field_ids"] == ["unknown"]
    assert not list((tmp_path / "invalid/cache").glob("source-inventory-*"))


@pytest.mark.parametrize(
    "change",
    [
        {"extraction_strategy": "direct"},
        {"include_steps": True},
        {"include_claims": True},
        {"type": "procedure"},
        {"budget": {"max_review_rounds": 1}},
        {"fields": [{"id": "n", "description": "A number", "type": "number"}]},
    ],
)
def test_unsupported_requirements_fail_before_provider(papers, tmp_path, change):
    with pytest.raises(ValueError, match="preserve_readings"):
        run(
            task(papers[:1], **change),
            tmp_path / "rejected",
            MockProvider(lambda _: pytest.fail("no call")),
        )


def test_default_two_calls_and_versioned_note_cache_authorization(
    papers, tmp_path, monkeypatch
):
    def generate(request):
        if request["phase"] == "source_evidence_inventory":
            return inventory(request)
        answer = response_for(request)
        answer["records"][0]["steps"] = []
        answer["records"][0]["fields"]["method"]["step_ids"] = []
        return answer

    config = task(papers[:1])
    default = deepcopy(config)
    default.pop("source_assembly")
    provider = MockProvider(generate)
    normal = run(default, tmp_path / "shared", provider)
    assert len(normal["calls"]) == 2
    assert "source_assembly" not in normal["provider"]
    notes = run(config, tmp_path / "shared", provider)
    assert len(notes["calls"]) == 1 and not notes["items"][0]["reused"]
    assert notes["provider"]["source_readings_renderer"] == readings.READINGS_VERSION
    app = ResearchApplication([tmp_path], tmp_path / "app", remote=True)
    before = app.binding("execute", config)
    monkeypatch.setattr(readings, "READINGS_VERSION", "preserve-readings/test-next")
    assert app.binding("execute", config) != before
    updated = run(config, tmp_path / "shared", provider)
    assert len(updated["calls"]) == 1  # No cross-version inventory borrowing.


def test_two_mains_keep_notes_and_use_existing_comparison_once(papers, tmp_path):
    def generate(request):
        if request["phase"] == "source_evidence_inventory":
            return inventory(request)
        assert request["phase"] == "cross_document_synthesis"
        return {
            "claims": [],
            "issues": [
                {
                    "kind": "strategy_problem",
                    "detail": "Synthetic comparison remains unconfirmed.",
                    "source_id": "paper0",
                    "page": 1,
                }
            ],
        }

    provider = MockProvider(generate)
    config = task(papers, type="compare", synthesize=True)
    manifest = run(config, tmp_path / "compare", provider)
    assert len(manifest["calls"]) == 3
    assert [r["phase"] for r in provider.requests] == [
        "source_evidence_inventory",
        "source_evidence_inventory",
        "cross_document_synthesis",
    ]
    for index in range(2):
        saved = result(manifest, index)
        assert saved["response"]["records"][0]["id"] == f"paper{index}-readings"
        assert (
            saved["response"]["records"][0]["fields"]["method"]["status"]
            == "unconfirmed"
        )
    assert "另有原引擎跨篇综合调用及费用" in ResearchApplication.plan(
        validate_task(config), []
    )


def test_local_preparation_never_constructs_remote_provider(
    papers, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "aletheia_nexus.processing.engine.DeepSeekProvider",
        lambda *a, **k: pytest.fail("local mode must not call"),
    )
    manifest = run_task(
        task(papers[:1], mode="local"), base_dir=tmp_path, output_dir=tmp_path / "local"
    )
    assert manifest["status"] == "PREPARED" and manifest["calls"] == []


def test_direct_page_readings_keep_original_page_links(papers, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"synthetic-original-page",
    )
    config = task(papers[:1], mode="direct")
    config["documents"][0].update(pdf=str(papers[0]), image_pages=[1])

    def generate(request):
        document = request["material"]["documents"][0]
        assert document["blocks"] == []
        return {
            "items": [
                {
                    "observation": "The proposed mechanism is uncertain.",
                    "subject_stage": "sample",
                    "evidence_type": "author_interpretation",
                    "source_id": document["id"],
                    "page": 1,
                    "quote": "The proposed mechanism is uncertain.",
                    "field_ids": ["method"],
                }
            ]
        }

    manifest = run(config, tmp_path / "direct", MockProvider(generate))
    saved = result(manifest)
    citation = saved["response"]["records"][0]["fields"]["method"]["citations"][0]
    assert len(manifest["calls"]) == 1 and citation["page"] == 1
    assert citation["block_id"] is None
    assert saved["validation"]["citations"][0]["reading"] == "visual-unverified"


def test_cli_explicit_selection_is_saved_before_preview_without_editing_original(
    papers,
    tmp_path,
    capsys,
):
    from aletheia_nexus.research_ask import main

    config = task(papers[:1], mode="local")
    config.pop("source_assembly")
    original = tmp_path / "task.json"
    original.write_text(json.dumps(config), encoding="utf-8")
    before = original.read_bytes()
    assert (
        main(
            [
                "ask",
                "--papers",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "app"),
                "--task",
                str(original),
                "--source-assembly",
                "preserve_readings",
                "--save-only",
                "--non-interactive",
            ]
        )
        == 0
    )
    saved = list((tmp_path / "app/tasks").glob("*.json"))
    assert len(saved) == 1
    assert read(saved[0])["source_assembly"] == "preserve_readings"
    assert original.read_bytes() == before
    assert "本地模式不调用模型" in capsys.readouterr().out
