"""Engineering fixtures are self-authored, not scientific model performance data."""

import json
import runpy
import shutil
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from aletheia_nexus.content import parse_document
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.processing.contracts import TASK_SCHEMA, validate_task
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.materials import build_package, load_source
from aletheia_nexus.processing.provider import DeepSeekProvider, ProcessingError
from aletheia_nexus.processing.results import (
    check_response,
    make_result,
    revise_result,
    verify_result,
)
from aletheia_nexus.processing_cli import main

ROOT = Path(__file__).resolve().parents[2]
write_pdf = runpy.run_path(str(ROOT / "scripts/generate_v07_fixtures.py"))["_write_pdf"]


@pytest.fixture
def papers(tmp_path):
    paths = []
    for number in range(2):
        original = tmp_path / f"original{number}.pdf"
        write_pdf(
            original,
            [
                [
                    (50, 730, 15, f"Self-authored experiment {number}"),
                    (50, 680, 12, "Methods"),
                    (
                        50,
                        650,
                        12,
                        "The precursor ratio was 1:2. Synthesis lasted 6 h at 180 C.",
                    ),
                    (
                        50,
                        610,
                        12,
                        "The proposed mechanism is uncertain. A control experiment is needed.",
                    ),
                ],
                [
                    (50, 730, 15, "Testing and limitations"),
                    (
                        50,
                        670,
                        12,
                        "Testing was performed at 25 C under nitrogen for 2 h.",
                    ),
                    (
                        50,
                        630,
                        12,
                        "Yield was not measured. No heating rate was reported.",
                    ),
                ],
            ],
            title=f"Self-authored experiment {number}",
        )
        pdf = register_local_pdf(
            original, output_dir=tmp_path / "library", title=f"Example {number}"
        )
        parse_document(pdf)
        paths.append(pdf)
    return paths


def task_for(papers, kind="extract", mode="parsed"):
    return {
        "schema": TASK_SCHEMA,
        "id": "test",
        "type": kind,
        "objective": "Use only supplied material; organize method, evidence and conditions.",
        "documents": [
            {"id": f"paper{i}", "artifact": str(p.with_suffix(".parsed.json"))}
            for i, p in enumerate(papers)
        ],
        "fields": [
            {
                "id": "method",
                "type": "string",
                "description": "Exact method and conditions",
            }
        ],
        "mode": mode,
        "allow_remote": True,
        "synthesize": kind == "compare",
        "budget": {"max_supplement_rounds": 1, "max_calls": 10},
    }


def response_for(request):
    document = request["material"]["documents"][0]
    block = next(b for b in document["blocks"] if "Synthesis lasted" in b["text"])
    citation = {
        "source_id": document["id"],
        "block_id": block["id"],
        "page": block["page"],
        "quote": block["text"],
    }
    fields = {
        f["id"]: {
            "value": block["text"],
            "raw_value": block["text"],
            "unit": None,
            "status": "reported",
            "nature": "reported",
            "context": "Synthesis",
            "step_ids": ["s1"],
            "citations": [citation],
        }
        for f in request["fields"]
    }
    return {
        "records": [
            {
                "id": "r1",
                "subject": "sample",
                "stage": "synthesis",
                "fields": fields,
                "steps": [
                    {
                        "id": "s1",
                        "order": 1,
                        "description": block["text"],
                        "nature": "reported",
                        "citations": [citation],
                    }
                ],
            }
        ],
        "claims": [],
        "issues": [],
        "requests": [],
    }


class MockProvider:
    def __init__(self, function=response_for, version="1"):
        self.function = function
        self.requests = []
        self.version = version

    @property
    def identity(self):
        return {"provider": "mock", "version": self.version}

    def generate(self, request, schema, images, budget, max_output_tokens):
        self.requests.append(deepcopy(request))
        row = budget.reserve(None)
        row.update(status="completed", usage={"input_tokens": 10, "output_tokens": 10})
        return self.function(request)


@pytest.mark.parametrize("kind", ["organize", "extract", "procedure"])
def test_three_task_capabilities_use_same_engine_and_keep_sources(
    papers, tmp_path, kind
):
    task = task_for(papers, kind)
    hashes = {
        p: sha256_file(p)
        for pdf in papers
        for p in [pdf, pdf.with_suffix(".parsed.json")]
    }
    mock = MockProvider()
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert manifest["status"] == "COMPLETED"
    directory = Path(manifest["run_directory"])
    assert len(mock.requests) == 2
    assert len((directory / "records.jsonl").read_text("utf-8").splitlines()) == 2
    assert "180 C" in (directory / "table.csv").read_text("utf-8-sig")
    assert "PDF p.1" in (directory / "report.md").read_text("utf-8")
    assert all(sha256_file(p) == h for p, h in hashes.items())
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    assert "human_confirmed" not in result["validation"]["record_states"].values()
    assert result["validation"]["scientific_support"] == "not-verified"


def test_report_keeps_model_markup_literal_and_structured_value_unchanged(
    papers, tmp_path
):
    value = (
        "[open](https://example.invalid/visit) "
        "![image](https://example.invalid/pixel) "
        '<img src="https://example.invalid/html"> | Cu(OH)2 *H'
    )

    def generate(request):
        response = response_for(request)
        response["records"][0]["fields"]["method"]["value"] = value
        return response

    manifest = run_task(
        task_for(papers),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=MockProvider(generate),
    )
    directory = Path(manifest["run_directory"])
    report = (directory / "report.md").read_text("utf-8")
    assert "[open](https:" not in report and "![image](https:" not in report
    assert "<img" not in report
    assert r"\[open\]\(https://example.invalid/visit\)" in report
    assert r"Cu\(OH\)2 \*H" in report
    # Generated local evidence links stay usable; the JSONL preserves exact data.
    assert "[paper0 PDF p.1](file:" in report
    records = [
        json.loads(line)
        for line in (directory / "records.jsonl").read_text("utf-8").splitlines()
    ]
    assert all(record["fields"]["method"]["value"] == value for record in records)


def test_compare_uses_original_citations(papers, tmp_path):
    def generate(request):
        if "extractions" in request:
            return {
                "claims": [
                    {
                        "text": "Both examples report synthesis conditions, not testing conditions.",
                        "nature": "ai_synthesis",
                        "citations": [
                            r["records"][0]["fields"]["method"]["citations"][0]
                            for r in request["extractions"]
                        ],
                    }
                ],
                "issues": [],
            }
        return response_for(request)

    mock = MockProvider(generate)
    manifest = run_task(
        task_for(papers, "compare"),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert manifest["status"] == "COMPLETED"
    assert manifest["comparison"]["status"] == "COMPLETED"
    assert len(mock.requests) == 3
    claims = [
        json.loads(line)
        for line in (Path(manifest["run_directory"]) / "claims.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    assert len(claims) == 1
    assert {c["source_id"] for c in claims[0]["citations"]} == {"paper0", "paper1"}
    assert claims[0]["state"] == "review_required"
    assert claims[0]["schema"] == "aletheia-nexus/research-claim/v1"
    assert claims[0]["result_id"] and len(claims[0]["source_documents"]) == 2
    resumed = MockProvider(generate)
    replay = run_task(
        task_for(papers, "compare"),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=resumed,
    )
    assert replay["comparison"]["reused"] and not resumed.requests


def test_export_combines_modes_but_not_different_field_meanings(papers, tmp_path):
    paths = []
    for index, mode in enumerate(["parsed", "hybrid"]):
        task = task_for(papers, mode=mode)
        run = run_task(
            task,
            base_dir=tmp_path,
            output_dir=tmp_path / "runs",
            allow_remote=True,
            provider=MockProvider(),
        )
        paths.append(str(Path(run["run_directory"]) / f"paper{index}.result.json"))
    assert main(["export", *paths, "--output-dir", str(tmp_path / "combined")]) == 0
    records = (tmp_path / "combined/records.jsonl").read_text("utf-8").splitlines()
    assert len(records) == 2
    assert len({json.loads(r)["result_id"] for r in records}) == 2
    assert (
        len(
            json.loads((tmp_path / "combined/export-manifest.json").read_text("utf-8"))[
                "inputs"
            ]
        )
        == 2
    )
    task["fields"][0]["description"] = "A different scientific meaning"
    changed = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "runs",
        allow_remote=True,
        provider=MockProvider(),
    )
    assert (
        main(
            [
                "export",
                paths[0],
                str(Path(changed["run_directory"]) / "paper1.result.json"),
                "--output-dir",
                str(tmp_path / "incompatible"),
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    "mode,limit,corrupt,error",
    [
        ("direct", 2, False, None),
        ("hybrid", 2, False, None),
        ("direct", 1, False, "image_budget_exceeded"),
        ("direct", 2, True, "comparison_image_changed"),
    ],
)
def test_comparison_sends_images_checks_budget_and_keeps_individual_results(
    papers, tmp_path, monkeypatch, mode, limit, corrupt, error
):
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"\x89PNG\r\n\x1a\n" + pdf.name.encode(),
    )
    task = task_for(papers, "compare", mode)
    task["budget"]["max_images"] = limit
    for document in task["documents"]:
        document.update(pages=[1], image_pages=[1])

    class ImageProvider(MockProvider):
        def generate(self, request, schema, images, budget, max_output_tokens):
            self.requests.append(deepcopy(request))
            budget.reserve(None).update(status="completed")
            assert {(i["source_id"], i["page"]) for i in images} == {
                (i["source_id"], i["page"]) for i in request["material"]["images"]
            }
            assert all(i["bytes"].startswith(b"\x89PNG") for i in images)
            if "extractions" in request:
                assert len(images) == 2
                return {
                    "claims": [
                        {
                            "text": "Both source pages report conditions.",
                            "nature": "ai_synthesis",
                            "citations": [
                                r["records"][0]["fields"]["method"]["citations"][0]
                                for r in request["extractions"]
                            ],
                        }
                    ],
                    "issues": [],
                }
            synthetic = deepcopy(request)
            if not synthetic["material"]["documents"][0]["blocks"]:
                synthetic["material"]["documents"][0]["blocks"] = [
                    {"id": None, "page": 1, "text": "Synthesis lasted 6 h at 180 C."}
                ]
            response = response_for(synthetic)
            for record in response["records"]:
                record["fields"]["method"]["citations"][0]["block_id"] = None
                record["steps"][0]["citations"][0]["block_id"] = None
            if corrupt:
                for path in (tmp_path / "out/runs").rglob("*.png"):
                    path.write_bytes(b"changed after rendering")
            return response

    provider = ImageProvider()
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    assert all(row["status"] == "COMPLETED" for row in manifest["items"])
    assert all(
        (Path(manifest["run_directory"]) / row["result"]).exists()
        for row in manifest["items"]
    )
    if error:
        assert manifest["status"] == "PARTIAL"
        assert manifest["comparison"]["error"] == error
        assert len(provider.requests) == 2
    else:
        assert manifest["comparison"]["status"] == "COMPLETED"
        assert len(provider.requests) == 3
        comparison = json.loads(
            (Path(manifest["run_directory"]) / "comparison.result.json").read_text(
                "utf-8"
            )
        )
        assert comparison["package"]["builder_version"] == 2
        reused = ImageProvider()
        replay = run_task(
            task,
            base_dir=tmp_path,
            output_dir=tmp_path / "out",
            allow_remote=True,
            provider=reused,
        )
        assert replay["comparison"]["reused"] and not reused.requests


def test_local_never_touches_provider_or_environment(papers, tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("remote provider called")

    monkeypatch.setattr("aletheia_nexus.processing.engine.DeepSeekProvider", forbidden)
    mock = MockProvider(forbidden)
    manifest = run_task(
        task_for(papers, mode="local"),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        provider=mock,
    )
    assert manifest["status"] == "PREPARED"
    assert manifest["usage"]["http_attempts"] == 0
    assert not mock.requests
    directory = Path(manifest["run_directory"])
    assert "180 C" in (directory / "report.md").read_text("utf-8")
    assert not (directory / "records.jsonl").exists()


def test_output_review_inventory_preserves_failures_and_binds_originals(
    papers, tmp_path, monkeypatch
):
    evaluation = runpy.run_path(str(ROOT / "scripts/score_v08_review.py"))

    def generate(request):
        if request["material"]["documents"][0]["id"] == "paper1":
            raise ProcessingError("model_refusal")
        response = response_for(request)
        response["claims"] = [
            {
                "text": "Source reports a procedure.",
                "nature": "reported",
                "citations": deepcopy(
                    response["records"][0]["fields"]["method"]["citations"]
                ),
            }
        ]
        return response

    run = run_task(
        task_for(papers),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=MockProvider(generate),
    )
    directory = Path(run["run_directory"])
    inventory = evaluation["output_inventory"]([directory])
    assert len(inventory["outputs"]) == 3
    assert {o["kind"] for o in inventory["outputs"]} == {"field", "step", "claim"}
    assert inventory["runs"][0]["items"][1]["status"] == "FAILED"
    plan = {
        "schema": "aletheia-nexus/evaluation-plan/v1",
        "split": "development",
        "reference_authority": "assistant",
        "frozen_at": "2026-10-25",
        "output_audit_policy": "all_emitted",
        "cases": [
            {
                "id": "method",
                "record_id": "r1",
                "kind": "field",
                "expected_present": True,
            }
        ],
    }
    plan_path, draft_path = tmp_path / "plan.json", tmp_path / "review.json"
    plan_path.write_text(json.dumps(plan), "utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "score_v08_review.py",
            str(plan_path),
            "--run-dir",
            str(directory),
            "--prepare-output-review",
            "--output",
            str(draft_path),
        ],
    )
    assert evaluation["main"]() == 0
    draft = json.loads(draft_path.read_text("utf-8"))
    assert draft["draft"] and draft["reviewer_kind"] == "pending_review"
    assert len(draft["output_judgments"]) == 3
    assert all(j["correct"] is None for j in draft["output_judgments"])
    with pytest.raises(ValueError, match="draft"):
        evaluation["score"](plan, draft, inventory=inventory)
    papers[0].write_bytes(papers[0].read_bytes() + b"\nchanged")
    with pytest.raises(ValueError, match="original PDF missing or changed"):
        evaluation["output_inventory"]([directory])


def test_selected_export_formats_and_offline_override(papers, tmp_path, monkeypatch):
    task = task_for(papers)
    task["export_formats"] = ["csv"]
    mock = MockProvider()
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "runs",
        allow_remote=True,
        provider=mock,
    )
    directory = Path(run["run_directory"])
    assert run["outputs"] == ["table.csv", "task.json"]
    assert (directory / "table.csv").exists()
    assert not (directory / "report.md").exists()
    assert not (directory / "records.jsonl").exists()
    result_path = directory / "paper0.result.json"
    original = result_path.read_bytes()

    def forbidden(*a, **kw):
        raise AssertionError("offline export must not call a provider")

    monkeypatch.setattr("aletheia_nexus.processing.engine.DeepSeekProvider", forbidden)
    output = tmp_path / "jsonl-only"
    assert (
        main(
            [
                "export",
                str(result_path),
                "--output-dir",
                str(output),
                "--formats",
                "jsonl",
            ]
        )
        == 0
    )
    assert not (output / "report.md").exists()
    assert not (output / "table.csv").exists()
    records = (output / "records.jsonl").read_text("utf-8").splitlines()
    assert len(records) == 1
    manifest = json.loads((output / "export-manifest.json").read_text("utf-8"))
    assert manifest["export_formats"] == ["jsonl"]
    assert manifest["outputs"] == ["records.jsonl"]
    assert result_path.read_bytes() == original
    assert len(mock.requests) == 2


@pytest.mark.parametrize("formats", [[], ["csv", "csv"], ["xlsx"]])
def test_invalid_export_formats_rejected_before_processing(papers, formats):
    task = task_for(papers)
    task["export_formats"] = formats
    with pytest.raises(ValueError):
        validate_task(task)


@pytest.mark.parametrize(
    "task_gate,run_gate", [(False, True), (True, False), (False, False)]
)
def test_both_remote_gates_required(papers, tmp_path, task_gate, run_gate):
    task = task_for(papers)
    task["allow_remote"] = task_gate
    with pytest.raises(ProcessingError, match="remote_disabled"):
        run_task(
            task,
            base_dir=tmp_path,
            output_dir=tmp_path / "out",
            provider=MockProvider(),
            allow_remote=run_gate,
        )


def test_failed_document_recovers_without_repeating_success(papers, tmp_path):
    def fail_second(request):
        if request["material"]["documents"][0]["id"] == "paper1":
            raise ProcessingError("network_error")
        return response_for(request)

    task = task_for(papers)
    first = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=MockProvider(fail_second),
    )
    assert first["status"] == "PARTIAL"
    mock = MockProvider()
    resumed = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert resumed["status"] == "COMPLETED"
    assert len(mock.requests) == 1
    assert resumed["items"][0]["reused"]


@pytest.mark.parametrize("change", ["objective", "field", "notes", "provider"])
def test_changed_inputs_never_reuse_cache(papers, tmp_path, change):
    task = task_for(papers[:1])
    run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=MockProvider(),
    )
    mock = MockProvider(version="2" if change == "provider" else "1")
    if change == "objective":
        task["objective"] += " A different objective."
    if change == "field":
        task["fields"][0]["description"] += " New meaning."
    if change == "notes":
        task["documents"][0]["notes"] = ["Review atmosphere."]
    result = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 1 and not result["items"][0]["reused"]


@pytest.mark.parametrize("mode", ["parsed", "hybrid"])
def test_requested_page_adds_real_material_then_reuses_final_result(
    papers, tmp_path, monkeypatch, mode
):
    task = task_for(papers[:1], mode=mode)
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"fake-png-fixture" + str(page).encode(),
    )
    task["documents"][0]["pages"] = [1]

    def generate(request):
        response = response_for(request)
        if len(request["material"]["documents"][0]["pages_requested"]) == 1:
            response["requests"] = [
                {
                    "source_id": "paper0",
                    "pages": [2],
                    "reason": "Need testing and limitations",
                }
            ]
        return response

    mock = MockProvider(generate)
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert manifest["status"] == "COMPLETED"
    assert len(mock.requests) == 2
    assert any(
        "25 C" in b["text"]
        for b in mock.requests[1]["material"]["documents"][0]["blocks"]
    )
    assert (
        mock.requests[1]["material"]["parent_id"]
        == mock.requests[0]["material"]["artifact_id"]
    )
    reused = MockProvider(generate)
    replay = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=reused,
    )
    assert replay["status"] == "COMPLETED"
    assert not reused.requests
    if mode == "hybrid":
        directory = Path(replay["run_directory"])
        result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
        for item in result["package"]["images"]:
            assert (
                (directory / (item["sha256"] + ".png"))
                .read_bytes()
                .startswith(b"fake-png-fixture")
            )


def test_useless_repeated_requests_stop_and_remain_partial(papers, tmp_path):
    def generate(request):
        response = response_for(request)
        response["requests"] = [
            {
                "source_id": "paper0",
                "pages": [1],
                "reason": "Cannot understand the existing text",
            }
        ]
        return response

    mock = MockProvider(generate)
    manifest = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 1
    assert manifest["status"] == "PARTIAL"
    assert manifest["items"][0]["supplement_status"] == "no_new_material"
    cached_mock = MockProvider(generate)
    cached = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=cached_mock,
    )
    assert not cached_mock.requests
    assert cached["status"] == "PARTIAL"
    assert cached["items"][0]["supplement_status"] == "no_new_material"


def test_failure_after_supplement_preserves_previous_candidate(papers, tmp_path):
    task = task_for(papers[:1])
    task["documents"][0]["pages"] = [1]

    def generate(request):
        if len(request["material"]["documents"][0]["pages_requested"]) > 1:
            raise ProcessingError("network_error")
        response = response_for(request)
        response["requests"] = [
            {"source_id": "paper0", "pages": [2], "reason": "Need context"}
        ]
        return response

    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=MockProvider(generate),
    )
    assert manifest["status"] == "PARTIAL"
    assert manifest["items"][0]["supplement_status"] == "network_error"
    result = json.loads(
        (Path(manifest["run_directory"]) / "paper0.result.json").read_text("utf-8")
    )
    assert result["package"]["documents"][0]["pages_requested"] == [1]
    assert result["response"]["records"]


@pytest.mark.parametrize(
    "corrupt", ["page", "block", "quote", "human_status", "step", "unknown_source"]
)
def test_invalid_model_references_and_confirmation_rejected(papers, tmp_path, corrupt):
    task = validate_task(task_for(papers[:1]))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    citation = response["records"][0]["fields"]["method"]["citations"][0]
    if corrupt == "page":
        citation["page"] = 999
    if corrupt == "block":
        citation["block_id"] = "invented"
    if corrupt == "quote":
        citation["quote"] = "It was 999 C"
    if corrupt == "unknown_source":
        citation["source_id"] = "other"
    if corrupt == "human_status":
        response["records"][0]["status"] = "human_confirmed"
    if corrupt == "step":
        response["records"][0]["fields"]["method"]["step_ids"] = ["wrong"]
    with pytest.raises((ProcessingError, ValueError)):
        check_response(response, task, package)


def test_corrections_and_human_revision_preserve_history(papers, tmp_path):
    task = validate_task(task_for(papers[:1]))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    block = next(b for b in package["documents"][0]["blocks"] if "180 C" in b["text"])
    task["documents"][0]["corrections"] = [
        {
            "block_id": block["id"],
            "original": block["text"],
            "replacement": "Synthetic corrected reading: 181 C.",
            "reason": "Fixture tests the overlay, not a real correction.",
            "author": "test reviewer",
            "at": "2026-10-25",
        }
    ]
    overlay_source = load_source(task["documents"][0], tmp_path, task["mode"])
    overlay, _ = build_package(task, [overlay_source])
    assert block["text"] in [b["text"] for b in overlay["documents"][0]["blocks"]]
    assert overlay["artifact_id"] != package["artifact_id"]
    result = make_result(task, overlay, {"provider": "mock"}, response)
    updated = revise_result(
        result,
        {
            "record_id": "r1",
            "replacement": deepcopy(response["records"][0]),
            "author": "human",
            "at": "2026-10-25",
            "reason": "checked source",
            "confirm": True,
        },
    )
    verify_result(updated)
    assert updated["history"][0]["parent_result_id"] == result["artifact_id"]
    assert updated["validation"]["record_states"]["r1"] == "human_confirmed"
    assert result["validation"]["record_states"]["r1"] != "human_confirmed"


@pytest.mark.parametrize("comparison", [False, True])
def test_claim_revisions_keep_source_validation_and_revoke_confirmation(
    papers, tmp_path, comparison
):
    task = validate_task(task_for(papers[:1]))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    claim = {
        "text": "The reported synthesis temperature is 180 C.",
        "nature": "reported",
        "citations": deepcopy(response["records"][0]["fields"]["method"]["citations"]),
    }
    response["claims"] = [claim]
    if comparison:
        response = {k: response[k] for k in ("claims", "issues")}
    result = make_result(
        task, package, {"provider": "mock"}, response, comparison=comparison
    )
    original = deepcopy(result)
    revision = {
        "claim_index": 0,
        "replacement": deepcopy(claim),
        "author": "human",
        "at": "2026-10-25",
        "reason": "Fixture review",
        "confirm": True,
    }
    reviewed = revise_result(result, revision)
    verify_result(reviewed)
    assert reviewed["validation"]["claim_states"]["0"] == "human_confirmed"
    assert reviewed["history"][-1]["before"] == claim
    assert reviewed["history"][-1]["parent_result_id"] == result["artifact_id"]
    assert result == original
    if not comparison:
        reviewed = revise_result(
            reviewed,
            {
                "record_id": "r1",
                "replacement": deepcopy(response["records"][0]),
                "author": "human",
                "at": "2026-10-25",
                "reason": "Fixture record review",
                "confirm": True,
            },
        )
        verify_result(reviewed)
        assert reviewed["validation"]["claim_states"]["0"] == "human_confirmed"
    revision["replacement"]["text"] = (
        "The source reports synthesis at 180 C; applicability beyond this setup is unverified."
    )
    revision["confirm"] = False
    amended = revise_result(reviewed, revision)
    verify_result(amended)
    assert amended["validation"]["claim_states"]["0"] == "review_required"
    if not comparison:
        assert amended["validation"]["record_states"]["r1"] == "human_confirmed"
    revision["replacement"]["citations"][0]["page"] = 999
    with pytest.raises(ProcessingError, match="invalid_citation"):
        revise_result(amended, revision)
    revision["claim_index"] = True
    with pytest.raises(ValueError):
        revise_result(amended, revision)


def test_original_pdf_change_fails_before_model(papers, tmp_path):
    task = task_for(papers[:1])
    papers[0].write_bytes(papers[0].read_bytes() + b"\nchanged\n")
    mock = MockProvider()
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert manifest["status"] == "FAILED"
    assert not mock.requests


def test_linked_si_is_grouped_with_main_and_keeps_local_page_numbers(papers, tmp_path):
    si = register_local_pdf(
        ROOT / "benchmarks/v07_fixtures/two_column_article.pdf",
        output_dir=tmp_path / "si",
        title="Test SI",
        role="SUPPLEMENT",
        parent_pdf=papers[0],
    )
    parse_document(si)
    task = task_for([papers[0], si])
    mock = MockProvider()
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 1
    assert manifest["items"][1]["status"] == "ATTACHED"
    assert (
        mock.requests[0]["material"]["documents"][1]["source"]["document_role"]
        == "SUPPLEMENT"
    )


@pytest.mark.skipif(
    not shutil.which("pdftoppm"), reason="Poppler optional for page vision"
)
def test_direct_page_images_need_no_parsed_artifact(papers, tmp_path):
    task = task_for(papers[:1], mode="direct")
    task["documents"] = [{"id": "paper0", "pdf": str(papers[0]), "pages": [1]}]
    normalized = validate_task(task)
    source = load_source(task["documents"][0], tmp_path, "direct")
    package, images = build_package(normalized, [source])
    assert package["documents"][0]["blocks"] == []
    assert package["documents"][0]["parsed_artifact_id"] is None
    assert images[0]["bytes"].startswith(b"\x89PNG")
    assert package["documents"][0]["omitted_pages"] == [2]


def test_real_adapter_with_mock_http_and_cli_export(papers, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-never-persist")
    seen = []

    def transport(request):
        body = json.loads(request.content)
        seen.append(body)
        response = response_for(json.loads(body["input"][0]["content"][0]["text"]))
        return httpx.Response(
            200,
            json={
                "id": "test-response",
                "model": "deepseek-flash",
                "status": "completed",
                "usage": {"input_tokens": 12, "output_tokens": 25},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(response)}
                        ],
                    }
                ],
            },
        )

    task = task_for(papers[:1])
    task["model"] = {"name": "deepseek-flash", "min_interval_seconds": 0}
    provider = DeepSeekProvider(
        task["model"], enabled=True, transport=httpx.MockTransport(transport)
    )
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    assert manifest["status"] == "COMPLETED"
    assert seen[0]["store"] is False
    assert seen[0]["text"]["format"]["type"] == "json_schema"
    assert "locators" not in seen[0]["input"][0]["content"][0]["text"]
    directory = Path(manifest["run_directory"])
    assert (
        main(
            [
                "export",
                str(directory / "paper0.result.json"),
                "--output-dir",
                str(tmp_path / "export"),
            ]
        )
        == 0
    )
    assert "file:///" in (tmp_path / "export/report.md").read_text("utf-8")
    papers[0].write_bytes(papers[0].read_bytes() + b"\nchanged after extraction")
    assert (
        main(
            [
                "export",
                str(directory / "paper0.result.json"),
                "--output-dir",
                str(tmp_path / "changed-source-export"),
            ]
        )
        == 0
    )
    assert "file:///" not in (tmp_path / "changed-source-export/report.md").read_text(
        "utf-8"
    )
    assert all(
        "test-secret-never-persist" not in p.read_text("utf-8")
        for p in (tmp_path / "out").rglob("*.json")
    )


def test_interruption_checkpoints_and_resume(papers, tmp_path):
    def interrupt(row):
        raise KeyboardInterrupt

    task = task_for(papers)
    with pytest.raises(KeyboardInterrupt):
        run_task(
            task,
            base_dir=tmp_path,
            output_dir=tmp_path / "out",
            allow_remote=True,
            provider=MockProvider(),
            progress=interrupt,
        )
    manifest = json.loads(
        next((tmp_path / "out/runs").glob("*/manifest.json")).read_text("utf-8")
    )
    assert manifest["interrupted"]
    mock = MockProvider()
    resumed = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert resumed["status"] == "COMPLETED" and len(mock.requests) == 1


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_invalid_quote_gets_one_evidence_based_repair(
    papers, tmp_path, repair_succeeds
):
    def generate(request):
        answer = response_for(request)
        if "validation_feedback" not in request or not repair_succeeds:
            answer["records"][0]["fields"]["method"]["citations"][0]["quote"] = "999 C"
            other = deepcopy(answer["records"][0]["fields"]["method"]["citations"][0])
            other["quote"] = "888 C"
            answer["claims"] = [
                {
                    "text": "Incorrect second citation",
                    "nature": "reported",
                    "citations": [other],
                }
            ]
        else:
            assert request["validation_feedback"]["code"] == "quotation_not_in_source"
            assert len(request["validation_feedback"]["errors"]) == 2
            assert request["unvalidated_candidate"]
        return answer

    mock = MockProvider(generate)
    run = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 2
    assert run["status"] == ("COMPLETED" if repair_succeeds else "FAILED")
    assert list(Path(run["run_directory"]).glob("*.rejected.json"))
    assert run["items"][0]["output_repairs"][0]["error"] == "quotation_not_in_source"


@pytest.mark.parametrize("defect", ["wrong_block", "wrong_page"])
def test_quote_location_feedback_repairs_without_mutating_candidate(
    papers, tmp_path, defect
):
    def generate(request):
        answer = response_for(request)
        citation = answer["records"][0]["fields"]["method"]["citations"][0]
        expected = {k: citation[k] for k in ("source_id", "block_id", "page")}
        if "validation_feedback" in request:
            errors = request["validation_feedback"]["errors"]
            assert len(errors) == 1
            assert errors[0]["exact_quote_locations"] == [expected]
            assert request["unvalidated_candidate"] != answer
        elif defect == "wrong_block":
            citation["block_id"] = "nonexistent-block"
        else:
            citation["page"] = 2
        return answer

    mock = MockProvider(generate)
    run = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert run["status"] == "COMPLETED" and len(mock.requests) == 2
    directory = Path(run["run_directory"])
    original = json.loads((directory / "paper0.0.candidate.json").read_text("utf-8"))
    repaired = json.loads(
        (directory / "paper0.0.candidate.repair1.json").read_text("utf-8")
    )
    assert original != repaired
    assert original == mock.requests[1]["unvalidated_candidate"]
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    assert result["validation"]["scientific_support"] == "not-verified"


@pytest.mark.parametrize(
    "scope", ["other_document", "unselected_page", "changed_symbol"]
)
def test_quote_location_feedback_preserves_source_scope_and_symbols(
    papers, tmp_path, scope
):
    task = validate_task(task_for(papers))
    sources = [load_source(c, tmp_path, task["mode"]) for c in task["documents"]]
    package, _ = build_package(task, sources)
    answer = response_for({"material": package, "fields": task["fields"]})
    citation = answer["records"][0]["fields"]["method"]["citations"][0]
    source = package["documents"][0]
    if scope == "other_document":
        # An identical quote in another document must not repair this source ID.
        source["blocks"] = []
    elif scope == "unselected_page":
        source["pages_requested"] = [2]
    else:
        # Minus and approximation signs are scientifically distinct.
        block = next(b for b in source["blocks"] if b["id"] == citation["block_id"])
        block["text"] = "Temperature was ~95 °C."
        citation["quote"] = "Temperature was −95 °C."
    with pytest.raises(ProcessingError) as caught:
        check_response(answer, task, package)
    assert all(
        not e["exact_quote_locations"] for e in caught.value.diagnostics["errors"]
    )


@pytest.mark.parametrize("defect", ["missing_unit", "unknown_step"])
def test_field_repair_identifies_field_and_keeps_original_candidate(
    papers, tmp_path, defect
):
    def generate(request):
        answer = response_for(request)
        field = answer["records"][0]["fields"]["method"]
        field.update(
            value=None,
            raw_value=None,
            unit="h",
            status="not_reported",
            context="No duration reported in supplied scope.",
            citations=[],
            step_ids=[],
        )
        if defect == "unknown_step":
            field.update(unit=None, step_ids=["not-a-real-step"])
        if "validation_feedback" in request:
            feedback = request["validation_feedback"]
            assert feedback["record_id"] == "r1"
            assert feedback["field_id"] == "method"
            rejected = request["unvalidated_candidate"]["records"][0]["fields"][
                "method"
            ]
            if defect == "missing_unit":
                assert feedback["code"] == "invented_missing_value"
                assert "JSON null" in feedback["validation"]
                assert rejected["unit"] == "h"
            else:
                assert feedback["code"] == "invalid_step_reference"
                assert feedback["unknown_step_ids"] == ["not-a-real-step"]
                assert feedback["available_step_ids"] == ["s1"]
                assert rejected["step_ids"] == ["not-a-real-step"]
                field["step_ids"] = []
            field["unit"] = None
        return answer

    mock = MockProvider(generate)
    run = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 2
    assert run["status"] == "COMPLETED"
    rejected = list(Path(run["run_directory"]).glob("*.rejected.json"))
    assert len(rejected) == 1
    expected = (
        "invented_missing_value"
        if defect == "missing_unit"
        else "invalid_step_reference"
    )
    assert run["items"][0]["output_repairs"][0]["error"] == expected


def test_prose_summary_keeps_source_quotes_without_fake_literal_value(papers, tmp_path):
    task = validate_task(task_for(papers[:1], "organize"))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    answer = response_for({"material": package, "fields": task["fields"]})
    field = answer["records"][0]["fields"]["method"]
    field.update(
        value="A heated synthesis was reported.", raw_value=None, nature="ai_synthesis"
    )
    assert (
        check_response(answer, task, package)["record_states"]["r1"]
        == "review_required"
    )
    task["fields"][0]["type"] = "number"
    field.update(value=180, nature="reported")
    with pytest.raises(ProcessingError, match="missing_original_value"):
        check_response(answer, task, package)
    field["raw_value"] = "180 C"
    check_response(answer, task, package)
    field.update(status="normalized", raw_value=None)
    with pytest.raises(ProcessingError, match="missing_original_value"):
        check_response(answer, task, package)


def test_quote_ligatures_do_not_collapse_scientific_symbols():
    from aletheia_nexus.processing.results import _quotation

    assert _quotation("signiﬁcant\n ﬂow") == "significant flow"
    assert _quotation("CO₂ 10⁻³ −0.5 °C") != _quotation("CO2 10-3 -0.5 C")
