"""Engineering fixtures are self-authored, not scientific model performance data."""

import csv
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
from aletheia_nexus.processing.contracts import (
    TASK_SCHEMA,
    digest,
    response_schema,
    validate_task,
)
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


def review_for(request):
    return {
        "checks": [
            {
                "target_id": target["target_id"],
                "verdict": "supported",
                "detail": "Checked supplied evidence; this is model advice only.",
                "citations": [],
            }
            for target in request["targets"]
        ],
        "issues": [],
        "requests": [],
    }


def test_model_review_preserves_lineage_and_reuses_without_new_calls(papers, tmp_path):
    task = task_for(papers[:1])
    task["budget"]["max_review_rounds"] = 1

    def generate(request):
        if request["phase"] == "evidence_review":
            return review_for(request)
        return response_for(request)

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert [r["phase"] for r in mock.requests] == [
        "document_extraction",
        "evidence_review",
        "evidence_review",
    ]
    assert run["items"][0]["model_reviews"][0]["revision_mode"] == "unchanged"
    assert run["items"][0]["model_reviews"][0]["scientific_support"] == "not-verified"
    directory = Path(run["run_directory"])
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    verify_result(result)
    assert result["validation"]["record_states"] == {"r1": "source_located"}
    assert result["history"] == []
    cached = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert cached["items"][0]["reused"]
    assert len(mock.requests) == 3
    for suffix in ("input", "feedback", "output"):
        name = f"paper0.review1.{suffix}.json"
        assert (Path(cached["run_directory"]) / name).read_bytes() == (
            directory / name
        ).read_bytes()


def test_review_omits_unrequested_procedures_and_keeps_resolved_advice_in_history(
    papers, tmp_path
):
    task = task_for(papers[:1])
    task["include_steps"] = False
    task["fields"] *= 4
    task["fields"] = [
        dict(field, id=f"field{i}") for i, field in enumerate(task["fields"])
    ]
    task["budget"]["max_review_rounds"] = 1
    old_issue = {
        "kind": "strategy_problem",
        "detail": "The first draft omits the precursor ratio; restore it from page 1.",
        "source_id": "paper0",
        "page": 1,
    }

    def generate(request):
        if request["phase"] == "evidence_review":
            review = review_for(request)
            if any(t["kind"] == "field" for t in request["targets"]):
                review["issues"] = [old_issue]
                for check in review["checks"]:
                    check["verdict"] = "revise"
            return review
        response = response_for(request)
        response["records"][0]["steps"] = []
        for field in response["records"][0]["fields"].values():
            field["step_ids"] = []
            if request["phase"] == "document_extraction":
                field["value"] = "Synthesis lasted 6 h at 180 C."
                field["raw_value"] = field["value"]
        if request["phase"] == "document_revision":
            assert request["revision_mode"] == "targeted"
            return {
                "replacements": {
                    f"record:0/field:{fid}": value
                    for fid, value in response["records"][0]["fields"].items()
                },
                "issues": [],
                "requests": [],
            }
        return response

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    reviews = [r for r in mock.requests if r["phase"] == "evidence_review"]
    assert len(reviews) == 2  # Four fields together, then task coverage.
    assert not any(t["kind"] == "procedure" for r in reviews for t in r["targets"])
    directory = Path(run["run_directory"])
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    assert result["response"]["issues"] == []
    assert "1:2" in result["response"]["records"][0]["fields"]["field0"]["value"]
    feedback = json.loads(
        (directory / "paper0.review1.feedback.json").read_text("utf-8")
    )
    assert old_issue in feedback["issues"]
    assert run["items"][0]["model_reviews"][0]["scientific_support"] == "not-verified"
    verify_result(result)
    cached = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert cached["items"][0]["reused"]
    assert len(mock.requests) == 4
    assert (
        Path(cached["run_directory"]) / "paper0.review1.feedback.json"
    ).read_bytes() == (directory / "paper0.review1.feedback.json").read_bytes()


@pytest.mark.parametrize("failure", ["coverage", "citation", "budget", "revision"])
def test_failed_review_retains_valid_result_and_is_not_cached(
    papers, tmp_path, failure
):
    task = task_for(papers[:1])
    task["budget"].update(max_review_rounds=1, max_repair_rounds=0)
    if failure == "budget":
        task["budget"]["max_calls"] = 1

    def generate(request):
        if request["phase"] == "evidence_review":
            audit = review_for(request)
            if failure == "coverage":
                audit["checks"].pop()
            if failure == "citation":
                audit["checks"][0]["citations"] = [
                    {
                        "source_id": "paper0",
                        "page": 999,
                        "block_id": None,
                        "quote": "invented",
                    }
                ]
            if failure == "revision":
                for check in audit["checks"]:
                    if check["target_id"].startswith("record:"):
                        check["verdict"] = "revise"
            return audit
        if request["phase"] == "document_revision":
            raise ProcessingError("network_error")
        return response_for(request)

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert run["status"] == "PARTIAL"
    row = run["items"][0]
    assert (
        row["review_status"]
        == {
            "coverage": "incomplete_model_review",
            "citation": "invalid_citation",
            "budget": "call_budget_exhausted",
            "revision": "network_error",
        }[failure]
    )
    directory = Path(run["run_directory"])
    result = json.loads((directory / row["result"]).read_text("utf-8"))
    assert result["response"] == response_for(mock.requests[0])
    verify_result(result)
    assert not list((tmp_path / "out" / "cache").glob("*.json"))


def test_local_task_with_review_budget_still_never_calls_provider(papers, tmp_path):
    task = task_for(papers[:1], mode="local")
    task["budget"]["max_review_rounds"] = 2
    mock = MockProvider()
    run = run_task(task, base_dir=tmp_path, output_dir=tmp_path / "out", provider=mock)
    assert run["status"] == "PREPARED"
    assert mock.requests == []


@pytest.mark.parametrize("resolved", [True, False])
def test_diagnostic_only_revision_preserves_answers_and_reuses_result(
    papers, tmp_path, resolved
):
    task = task_for(papers[:1])
    task["budget"]["max_review_rounds"] = 1

    def generate(request):
        if request["phase"] == "evidence_review":
            return review_for(request)
        if request["phase"] == "document_revision":
            assert request["revision_mode"] == "targeted"
            candidate = request["candidate"]
            return {
                "replacements": {},
                "issues": [] if resolved else candidate["issues"],
                "requests": [] if resolved else candidate["requests"],
            }
        response = response_for(request)
        response["issues"] = [
            {
                "kind": "strategy_problem",
                "detail": "Recheck whether the precursor ratio is included.",
                "source_id": "paper0",
                "page": 1,
            }
        ]
        response["requests"] = [
            {
                "source_id": "paper0",
                "pages": [1],
                "reason": "Recheck the already supplied synthesis page.",
            }
        ]
        return response

    output = tmp_path / "out"
    mock = MockProvider(generate)
    run = run_task(
        task, base_dir=tmp_path, output_dir=output, allow_remote=True, provider=mock
    )
    assert len(mock.requests) == 4
    assert run["status"] == ("COMPLETED" if resolved else "PARTIAL")
    directory = Path(run["run_directory"])
    before = json.loads((directory / "paper0.review1.input.json").read_text("utf-8"))
    after = json.loads((directory / "paper0.review1.output.json").read_text("utf-8"))
    expected = deepcopy(before)
    if resolved:
        expected.update(issues=[], requests=[])
    assert after == expected  # Only the model may clear current diagnostics.
    assert before["issues"] and before["requests"]  # History remains intact.
    repeat = run_task(
        task, base_dir=tmp_path, output_dir=output, allow_remote=True, provider=mock
    )
    assert repeat["status"] == run["status"]
    assert repeat["items"][0]["reused"] and len(mock.requests) == 4


@pytest.mark.parametrize("cache_fault", ["patch", "version"])
def test_targeted_review_preserves_supported_fields_and_replays_cached_patch(
    papers, tmp_path, cache_fault
):
    task = task_for(papers[:1])
    task["include_claims"] = False
    task["fields"].append(
        {
            "id": "context",
            "type": "string",
            "description": "Retain reported context and limitations",
        }
    )
    task["budget"].update(max_review_rounds=1, max_repair_rounds=0)

    def generate(request):
        if request["phase"] == "document_extraction":
            assert "return claims: []" in request["instruction"]
        else:
            # Review checks and targeted replacements have their own schemas.
            assert "instruction" not in request
        if request["phase"] == "evidence_review":
            review = review_for(request)
            for check in review["checks"]:
                if check["target_id"] == "record:0/field:method":
                    check.update(
                        verdict="revise",
                        detail="Restore precursor ratio to this existing field; no record is missing.",
                    )
            return review
        answer = response_for(request)
        if request["phase"] == "document_revision":
            assert request["revision_mode"] == "targeted"
            assert request["base_candidate_sha256"] == digest(request["candidate"])
            return {
                "replacements": {
                    "record:0/field:method": answer["records"][0]["fields"]["method"]
                },
                "issues": [],
                "requests": [],
            }
        answer["records"][0]["fields"]["method"].update(
            value="6 h at 180 C", raw_value="6 h at 180 C"
        )
        return answer

    output = tmp_path / "out"
    mock = MockProvider(generate)
    run = run_task(
        task, base_dir=tmp_path, output_dir=output, allow_remote=True, provider=mock
    )
    directory = Path(run["run_directory"])
    before = json.loads((directory / "paper0.review1.input.json").read_text("utf-8"))
    after = json.loads((directory / "paper0.review1.output.json").read_text("utf-8"))
    expected = deepcopy(before)
    expected["records"][0]["fields"]["method"] = response_for(mock.requests[0])[
        "records"
    ][0]["fields"]["method"]
    assert (
        after == expected
    )  # Whole untouched compound field, steps and metadata survive.
    assert "1:2" in after["records"][0]["fields"]["method"]["value"]
    repeat = run_task(
        task, base_dir=tmp_path, output_dir=output, allow_remote=True, provider=mock
    )
    assert repeat["items"][0]["reused"] and len(mock.requests) == 4
    cache_file = next((output / "cache").glob("*.json"))
    cached = json.loads(cache_file.read_text("utf-8"))
    trace = cached["model_reviews"][0]
    if cache_fault == "version":
        trace["version"] = "evidence-review/4"
    else:
        name = next(n for n in cached["review_artifacts"] if n.endswith(".patch.json"))
        patch = cached["review_artifacts"][name]
        patch["replacements"]["record:0/field:method"]["context"] = (
            "Changed after review"
        )
        trace["patch_sha256"] = digest(
            patch
        )  # Hash alone must not replace replay validation.
    cache_file.write_text(json.dumps(cached), "utf-8")
    fresh = MockProvider(generate)
    rerun = run_task(
        task, base_dir=tmp_path, output_dir=output, allow_remote=True, provider=fresh
    )
    assert not rerun["items"][0].get("reused") and len(fresh.requests) == 4


@pytest.mark.parametrize("repair", [True, False])
def test_procedure_revision_checks_associations_before_atomic_acceptance(
    papers, tmp_path, repair
):
    task = task_for(papers[:1])
    task["budget"].update(max_review_rounds=1, max_repair_rounds=int(repair))

    def generate(request):
        if request["phase"] == "evidence_review":
            review = review_for(request)
            for check in review["checks"]:
                if check["target_id"] == "record:0/steps":
                    check["verdict"] = "revise"
            return review
        if request["phase"] == "document_revision":
            step = {
                **deepcopy(request["candidate"]["records"][0]["steps"][0]),
                "id": "replacement-step",
            }
            if "validation_feedback" in request:
                assert (
                    request["validation_feedback"]["code"] == "invalid_step_reference"
                )
                assert "replacements" in request["unvalidated_candidate"]
            return {
                "replacements": {
                    "record:0/steps": {
                        "steps": [step],
                        "field_step_ids": {
                            "method": [
                                "replacement-step"
                                if "validation_feedback" in request
                                else "s1"
                            ]
                        },
                    }
                },
                "issues": [],
                "requests": [],
            }
        return response_for(request)

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    row = run["items"][0]
    directory = Path(run["run_directory"])
    result = json.loads((directory / row["result"]).read_text("utf-8"))
    before = response_for(mock.requests[0])
    if repair:
        expected = deepcopy(before)
        expected["records"][0]["steps"][0]["id"] = "replacement-step"
        expected["records"][0]["fields"]["method"]["step_ids"] = ["replacement-step"]
        assert result["response"] == expected
        assert run["status"] == "COMPLETED"
    else:
        assert result["response"] == before
        assert row["review_status"] == "invalid_step_reference"
        assert not list((tmp_path / "out" / "cache").glob("*.json"))
    verify_result(result)
    assert (directory / "paper0.review1.candidate.json").is_file()


def test_coverage_adds_requested_record_through_explicit_full_revision(
    papers, tmp_path
):
    task = task_for(papers[:1])
    task["budget"]["max_review_rounds"] = 1

    def generate(request):
        if request["phase"] == "evidence_review":
            review = review_for(request)
            for check in review["checks"]:
                if check["target_id"] == "coverage":
                    check.update(
                        verdict="revise",
                        detail="Requested testing stage has no record; existing field edits cannot add it.",
                    )
            return review
        answer = response_for(request)
        if request["phase"] == "document_revision":
            assert request["revision_mode"] == "full_coverage"
            testing = deepcopy(answer["records"][0])
            testing.update(id="test-stage", stage="testing")
            block = next(
                b
                for b in request["material"]["documents"][0]["blocks"]
                if "Testing was performed" in b["text"]
            )
            citation = {
                "source_id": "paper0",
                "block_id": block["id"],
                "page": block["page"],
                "quote": block["text"],
            }
            testing["fields"]["method"].update(
                value=block["text"],
                raw_value=block["text"],
                context="Testing",
                citations=[citation],
            )
            testing["steps"][0].update(description=block["text"], citations=[citation])
            answer["records"].append(testing)
        return answer

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    directory = Path(run["run_directory"])
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    assert [r["stage"] for r in result["response"]["records"]] == [
        "synthesis",
        "testing",
    ]
    assert (
        result["response"]["records"][0] == response_for(mock.requests[0])["records"][0]
    )
    assert run["items"][0]["model_reviews"][0]["revision_mode"] == "full_coverage"
    assert not (directory / "paper0.review1.patch.json").exists()
    verify_result(result)


def test_later_review_failure_keeps_last_successful_targeted_revision(papers, tmp_path):
    task = task_for(papers[:1])
    task["budget"].update(max_review_rounds=2, max_repair_rounds=0)
    revised_once = False

    def generate(request):
        nonlocal revised_once
        if request["phase"] == "evidence_review":
            if revised_once:
                raise ProcessingError("network_error")
            review = review_for(request)
            for check in review["checks"]:
                if check["target_id"] == "record:0/field:method":
                    check["verdict"] = "revise"
            return review
        answer = response_for(request)
        if request["phase"] == "document_revision":
            revised_once = True
            return {
                "replacements": {
                    "record:0/field:method": answer["records"][0]["fields"]["method"]
                },
                "issues": [],
                "requests": [],
            }
        answer["records"][0]["fields"]["method"].update(
            value="Incomplete method", raw_value="Incomplete method"
        )
        return answer

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert run["status"] == "PARTIAL"
    directory = Path(run["run_directory"])
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    accepted = json.loads((directory / "paper0.review1.output.json").read_text("utf-8"))
    assert result["response"] == accepted
    assert "1:2" in accepted["records"][0]["fields"]["method"]["value"]
    assert run["items"][0]["model_reviews"][1]["status"] == "FAILED"
    verify_result(result)


def test_duplicate_record_names_get_local_ids_without_repeating_extraction(
    papers, tmp_path
):
    def generate(request):
        answer = response_for(request)
        second = deepcopy(answer["records"][0])
        second["stage"] = "different-stage"
        answer["records"].append(second)
        return answer

    mock = MockProvider(generate)
    task = task_for(papers[:1])
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert run["status"] == "COMPLETED" and len(mock.requests) == 1
    directory = Path(run["run_directory"])
    original = json.loads((directory / "paper0.0.candidate.json").read_text("utf-8"))
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    records = result["response"]["records"]
    assert len({r["id"] for r in records}) == 2
    assert records[0] == original["records"][0]
    assert {k: v for k, v in records[1].items() if k != "id"} == {
        k: v for k, v in original["records"][1].items() if k != "id"
    }
    assert run["items"][0]["record_id_adjustments"][0]["candidate_sha256"] == digest(
        original
    )
    verify_result(result)
    cached = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert cached["items"][0]["reused"] and len(mock.requests) == 1
    assert (
        cached["items"][0]["record_id_adjustments"]
        == run["items"][0]["record_id_adjustments"]
    )


@pytest.mark.skipif(
    not shutil.which("pdftoppm"), reason="Poppler optional for page vision"
)
def test_page_tiles_have_real_overlapping_crops_and_enforce_image_budget(
    papers, tmp_path
):
    import struct

    task = task_for(papers[:1], mode="direct")
    task["documents"] = [
        {
            "id": "paper0",
            "pdf": str(papers[0]),
            "pages": [1],
            "image_layout": "page_and_tiles",
        }
    ]
    task["budget"]["max_images"] = 4
    normalized = validate_task(task)
    source = load_source(normalized["documents"][0], tmp_path, "direct")
    with pytest.raises(ProcessingError, match="image_budget_exceeded"):
        build_package(normalized, [source])
    normalized["budget"]["max_images"] = 5
    before = sha256_file(papers[0])
    package, images = build_package(normalized, [source])
    assert len(images) == len(package["images"]) == 5
    assert len({i["sha256"] for i in images}) == 5
    assert images[0]["region"] == [0, 0, 1, 1]
    width, height = struct.unpack(">II", images[0]["bytes"][16:24])
    for image in images[1:]:
        w, h = struct.unpack(">II", image["bytes"][16:24])
        x0, y0, x1, y1 = image["region"]
        assert (w, h) == (round((x1 - x0) * width), round((y1 - y0) * height))
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
        assert image["page"] == 1 and image["view"] == "tile"
    assert images[1]["region"][2] > images[2]["region"][0]
    assert images[1]["region"][3] > images[3]["region"][1]
    assert sha256_file(papers[0]) == before
    assert not package["documents"][0]["blocks"]


@pytest.mark.parametrize("extra", ["steps", "step_ids"])
def test_no_steps_contract_repairs_without_silent_deletion_or_old_cache(
    papers, tmp_path, extra
):
    legacy_task = task_for(papers[:1], "organize")
    old_run = run_task(
        legacy_task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=MockProvider(),
    )
    old_file = Path(old_run["run_directory"]) / "paper0.result.json"
    old_hash = sha256_file(old_file)
    task = {**legacy_task, "include_steps": False}
    schema = response_schema(validate_task(task))
    record_schema = schema["properties"]["records"]["items"]["properties"]
    assert record_schema["steps"]["maxItems"] == 0
    assert (
        record_schema["fields"]["properties"]["method"]["properties"]["step_ids"][
            "maxItems"
        ]
        == 0
    )

    def generate(request):
        assert request["include_steps"] is False
        response = response_for(request)
        record = response["records"][0]
        if extra == "steps":
            record["fields"]["method"]["step_ids"] = []
        else:
            record["steps"] = []
        if "validation_feedback" in request:
            feedback = request["validation_feedback"]
            assert feedback["code"] == "invalid_model_output"
            assert extra in feedback["validation"]
            record["steps"] = []
            record["fields"]["method"]["step_ids"] = []
        return response

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert run["status"] == "COMPLETED"
    assert (
        len(mock.requests) == 2
    )  # Changed output contract cannot reuse the old result.
    directory = Path(run["run_directory"])
    candidate = json.loads((directory / "paper0.0.candidate.json").read_text("utf-8"))
    rejected_record = candidate["records"][0]
    assert (
        rejected_record["steps"]
        if extra == "steps"
        else rejected_record["fields"]["method"]["step_ids"]
    )
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    verify_result(result)
    assert not result["response"]["records"][0]["steps"]
    assert not result["response"]["records"][0]["fields"]["method"]["step_ids"]
    assert "180 C" in (directory / "table.csv").read_text("utf-8-sig")
    repeat = MockProvider(
        lambda _: pytest.fail("compatible no-step result should reuse")
    )
    reused = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=repeat,
    )
    assert reused["items"][0]["reused"]
    assert not reused["calls"]
    # Old results are still valid and have not been rewritten to remove their steps.
    verify_result(json.loads(old_file.read_text("utf-8")))
    assert sha256_file(old_file) == old_hash


def test_field_only_extraction_keeps_comparison_and_invalidates_old_cache(
    papers, tmp_path
):
    legacy_task = task_for(papers, "compare")

    def generate(request):
        if request["phase"] == "cross_document_synthesis":
            assert "include_claims" not in request
            return {
                "claims": [
                    {
                        "text": "Both sources report the supplied synthesis method.",
                        "nature": "ai_synthesis",
                        "citations": request["extractions"][0]["records"][0]["fields"][
                            "method"
                        ]["citations"],
                    }
                ],
                "issues": [],
            }
        return response_for(request)

    kwargs = dict(base_dir=tmp_path, output_dir=tmp_path / "out", allow_remote=True)
    previous = run_task(legacy_task, provider=MockProvider(generate), **kwargs)
    previous_file = Path(previous["run_directory"]) / "paper0.result.json"
    previous_hash = sha256_file(previous_file)
    task = {**legacy_task, "include_claims": False}
    assert "maxItems" not in response_schema(legacy_task)["properties"]["claims"]
    assert response_schema(task)["properties"]["claims"]["maxItems"] == 0
    assert (
        "maxItems" not in response_schema(task, comparison=True)["properties"]["claims"]
    )
    mock = MockProvider(generate)
    result = run_task(task, provider=mock, **kwargs)
    assert result["status"] == "COMPLETED"
    assert len(mock.requests) == 3
    assert all(r["include_claims"] is False for r in mock.requests[:2])
    assert all("configured fields" in r["instruction"] for r in mock.requests[:2])
    saved = json.loads(
        (Path(result["run_directory"]) / "paper0.result.json").read_text("utf-8")
    )
    verify_result(saved)
    assert saved["response"]["records"][0]["fields"]["method"]["value"]
    assert saved["response"]["claims"] == []
    repeat = run_task(
        task,
        provider=MockProvider(lambda _: pytest.fail("reuse field-only result")),
        **kwargs,
    )
    assert not repeat["calls"]
    assert sha256_file(previous_file) == previous_hash
    verify_result(json.loads(previous_file.read_text("utf-8")))


def test_field_only_contract_never_silently_discards_model_claims(papers, tmp_path):
    task = {**task_for(papers[:1]), "include_claims": False}
    task["budget"]["max_repair_rounds"] = 0

    def generate(request):
        response = response_for(request)
        response["claims"] = [
            {
                "text": "An unrequested conclusion.",
                "nature": "ai_synthesis",
                "citations": [],
            }
        ]
        return response

    mock = MockProvider(generate)
    result = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert result["status"] == "FAILED"
    assert result["items"][0]["error"] == "invalid_model_output"
    assert len(mock.requests) == 1
    candidate = json.loads(
        (Path(result["run_directory"]) / "paper0.0.candidate.json").read_text("utf-8")
    )
    assert candidate["claims"][0]["text"] == "An unrequested conclusion."
    with pytest.raises(ValueError, match="include_claims: invalid type"):
        validate_task({**task, "include_claims": "false"})


def test_no_steps_contract_failure_stays_explicit(papers, tmp_path):
    task = {**task_for(papers[:1]), "include_steps": False}
    mock = MockProvider()
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert run["status"] == "FAILED"
    assert len(mock.requests) == 2
    assert run["items"][0]["error"] == "invalid_model_output"
    assert not (Path(run["run_directory"]) / "paper0.result.json").exists()
    report = (Path(run["run_directory"]) / "report.md").read_text("utf-8")
    assert "0/1 份任务文献材料" in report
    assert "本次未包含：paper0。" in report
    with pytest.raises(ValueError, match="include_steps: invalid type"):
        validate_task({**task, "include_steps": "false"})


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


@pytest.mark.parametrize(
    "context,markdown,csv_text",
    [
        (
            "Only synthesis; testing conditions were not reported in supplied pages.",
            "Only synthesis; testing conditions were not reported in supplied pages.",
            "Only synthesis; testing conditions were not reported in supplied pages.",
        ),
        (
            '=1+1 | [external](https://example.invalid) <img src="x">',
            "=1+1 \\| \\[external\\]\\(https://example.invalid\\) &lt;img src=&quot;x&quot;&gt;",
            '\'=1+1 | [external](https://example.invalid) <img src="x">',
        ),
    ],
)
def test_context_survives_run_and_offline_exports(
    papers, tmp_path, monkeypatch, context, markdown, csv_text
):
    def generate(request):
        response = response_for(request)
        response["records"][0]["fields"]["method"]["context"] = context
        return response

    run = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=MockProvider(generate),
    )
    directory = Path(run["run_directory"])
    original = directory / "paper0.result.json"
    original_hash = sha256_file(original)

    def no_remote(*args, **kwargs):
        pytest.fail("offline re-export must not call a provider")

    monkeypatch.setattr(DeepSeekProvider, "generate", no_remote)
    exported = tmp_path / "reexport"
    assert main(["export", str(original), "--output-dir", str(exported)]) == 0
    for output in [directory, exported]:
        assert "<br>说明：" + markdown in (output / "report.md").read_text("utf-8")
        with (output / "table.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1
        assert rows[0]["method.context"] == csv_text
        record = json.loads((output / "records.jsonl").read_text("utf-8"))
        assert record["fields"]["method"]["context"] == context
        assert rows[0]["result_id"] == record["result_id"]
    assert sha256_file(original) == original_hash


def test_step_relationships_survive_run_and_offline_exports(
    papers, tmp_path, monkeypatch
):
    def generate(request):
        response = response_for(request)
        first = response["records"][0]
        second_step = deepcopy(first["steps"][0])
        second_step.update(id="s2", order=2)
        first["steps"].append(second_step)
        first["fields"]["method"]["step_ids"] = ["s2"]
        # Repeated step IDs in another record must never borrow that record's
        # order or imply that its unlinked field applies to every step.
        second = deepcopy(first)
        second.update(id="r2", stage="separate procedure")
        second["steps"] = [dict(second_step, order=1)]
        second["fields"]["method"]["step_ids"] = []
        response["records"].append(second)
        return response

    mock = MockProvider(generate)
    run = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    directory = Path(run["run_directory"])
    original = directory / "paper0.result.json"
    original_hash = sha256_file(original)
    saved = json.loads(original.read_text("utf-8"))["response"]["records"]

    def no_remote(*args, **kwargs):
        pytest.fail("offline re-export must not call a provider")

    monkeypatch.setattr(DeepSeekProvider, "generate", no_remote)
    exported = tmp_path / "reexport"
    assert main(["export", str(original), "--output-dir", str(exported)]) == 0
    for output in [directory, exported]:
        report = (output / "report.md").read_text("utf-8")
        assert report.count("关联本记录步骤：") == 1
        assert "关联本记录步骤：2" in report
        with (output / "table.csv").open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
        assert reader.fieldnames == [
            "record_id",
            "subject",
            "stage",
            "method.value",
            "method.raw_value",
            "method.unit",
            "method.status",
            "method.context",
            "result_id",
            "sources",
            "method.step_ids",
            "steps",
        ]
        assert len(rows) == 2
        for row, record in zip(rows, saved, strict=True):
            assert (
                json.loads(row["method.step_ids"])
                == record["fields"]["method"]["step_ids"]
            )
            assert json.loads(row["steps"]) == record["steps"]
            assert row["method.value"] == record["fields"]["method"]["value"]
    assert len(mock.requests) == 1
    assert sha256_file(original) == original_hash


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
    directory = Path(manifest["run_directory"])
    assert "claims.csv" in manifest["outputs"]
    with (directory / "claims.csv").open(encoding="utf-8-sig", newline="") as stream:
        comparison_rows = list(csv.DictReader(stream))
    assert len(comparison_rows) == 1
    assert comparison_rows[0]["text"] == claims[0]["text"]
    assert json.loads(comparison_rows[0]["sources"]) == claims[0]["citations"]
    assert comparison_rows[0]["state"] == "review_required"
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
        # Differing task scopes must be unioned, including sources absent from
        # the chosen results. Do not mistake a selected subset for a full batch.
        task["documents"] = task["documents"][index:]
        task["documents"].append(
            {
                "id": f"unselected{index}",
                "artifact": str(papers[index].with_suffix(".parsed.json")),
            }
        )
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
    report = (tmp_path / "combined/report.md").read_text("utf-8")
    assert "2/4 份任务文献材料" in report
    assert "本次未包含：unselected0、unselected1。" in report
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
    report = (Path(first["run_directory"]) / "report.md").read_text("utf-8")
    assert "1/2 份任务文献材料" in report
    assert "本次未包含：paper1。" in report
    assert "不表示原文未报告所需信息" in report
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
    assert "本次未包含" not in (Path(resumed["run_directory"]) / "report.md").read_text(
        "utf-8"
    )


@pytest.mark.parametrize("change", ["material_projection", "extraction", "comparison"])
def test_changed_request_recomputes_only_affected_work(
    papers, tmp_path, monkeypatch, change
):
    from aletheia_nexus.processing import engine

    task = task_for(papers, "compare")

    def generate(request):
        if request["phase"] == "cross_document_synthesis":
            return {
                "claims": [
                    {
                        "text": "Both sources report the supplied synthesis method.",
                        "nature": "ai_synthesis",
                        "citations": request["extractions"][0]["records"][0]["fields"][
                            "method"
                        ]["citations"],
                    }
                ],
                "issues": [],
            }
        return response_for(request)

    kwargs = dict(base_dir=tmp_path, output_dir=tmp_path / "out", allow_remote=True)
    initial = run_task(task, provider=MockProvider(generate), **kwargs)
    old_file = Path(initial["run_directory"]) / "paper0.result.json"
    old_hash = sha256_file(old_file)
    original_request = engine._request

    def changed_request(*args, **kwargs):
        request = original_request(*args, **kwargs)
        if change == "material_projection":
            document = request["material"]["documents"][0]
            document["notes"] = [*document["notes"], "Keep source roles explicit."]
        elif (change == "extraction" and request["phase"] == "document_extraction") or (
            change == "comparison" and request["phase"] == "cross_document_synthesis"
        ):
            request["instruction"] = (
                request.get("instruction", "") + " Retain source roles."
            )
        return request

    monkeypatch.setattr(engine, "_request", changed_request)
    mock = MockProvider(generate)
    updated = run_task(task, provider=mock, **kwargs)
    assert updated["status"] == "COMPLETED"
    # A changed extraction request with an identical resulting artifact leaves
    # the comparison's actual input unchanged, so only the documents rerun.
    assert updated["comparison"]["reused"] == (change == "extraction")
    assert (
        len(mock.requests)
        == {"material_projection": 3, "extraction": 2, "comparison": 1}[change]
    )
    assert all(row["reused"] == (change == "comparison") for row in updated["items"])
    repeat = run_task(
        task,
        provider=MockProvider(lambda _: pytest.fail("reuse unchanged requests")),
        **kwargs,
    )
    assert not repeat["calls"]
    assert sha256_file(old_file) == old_hash
    verify_result(json.loads(old_file.read_text("utf-8")))


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
            assert "evidence_update" not in request
            response["issues"] = [
                {
                    "kind": "material_insufficient",
                    "detail": "Old candidate: testing page was not supplied",
                    "source_id": "paper0",
                    "page": 2,
                }
            ]
            response["requests"] = [
                {
                    "source_id": "paper0",
                    "pages": [2],
                    "reason": "Need testing and limitations",
                }
            ]
        else:
            assert "previous_candidate" not in request
            assert "Old candidate" not in json.dumps(request)
            update = request["evidence_update"]
            assert update["previous_package_id"] == request["material"]["parent_id"]
            assert update["requested_context"] == [
                {
                    "source_id": "paper0",
                    "pages": [2],
                    "reason": "Need testing and limitations",
                }
            ]
            assert update["current_coverage"] == [
                {
                    "source_id": "paper0",
                    "current_text_pages": [1, 2],
                    "added_text_pages": [2],
                    "current_image_pages": [2] if mode == "hybrid" else [],
                    "added_image_pages": [2] if mode == "hybrid" else [],
                    "omitted_pages": [],
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
    directory = Path(manifest["run_directory"])
    assert "Old candidate" in (directory / "paper0.0.candidate.json").read_text("utf-8")
    assert "Old candidate" not in (directory / "paper0.result.json").read_text("utf-8")
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


def test_hybrid_image_only_page_is_citable_without_expanding_text_scope(
    papers, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"fake-png-fixture" + str(page).encode(),
    )
    task = task_for(papers[:1], mode="hybrid")
    task["documents"][0].update(pages=[1], image_pages=[2])
    original = papers[0].with_suffix(".parsed.json")
    original_hash = sha256_file(original)

    def generate(request):
        document = request["material"]["documents"][0]
        assert {b["page"] for b in document["blocks"]} == {1}
        assert [i["page"] for i in request["material"]["images"]] == [2]
        response = response_for(request)
        response["claims"] = [
            {
                "text": "The testing page reports 25 C under nitrogen.",
                "nature": "reported",
                "citations": [
                    {
                        "source_id": "paper0",
                        "block_id": None,
                        "page": 2,
                        "quote": "Testing was performed at 25 C under nitrogen for 2 h.",
                    }
                ],
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
    assert len(mock.requests) == 1
    result = json.loads(
        (Path(manifest["run_directory"]) / "paper0.result.json").read_text("utf-8")
    )
    document = result["package"]["documents"][0]
    assert document["pages_requested"] == [1, 2]
    assert document["omitted_pages"] == []
    assert {b["page"] for b in document["blocks"]} == {1}
    assert result["validation"]["citations"][-1]["reading"] == "visual-unverified"
    assert result["validation"]["scientific_support"] == "not-verified"

    # A supplied page remains usable, but an unavailable block is not certified.
    invalid = deepcopy(result["response"])
    page_two = next(
        b for b in json.loads(original.read_text("utf-8"))["blocks"] if b["page"] == 2
    )
    invalid["claims"][0]["citations"][0].update(
        block_id=page_two["id"], quote=page_two["text"]
    )
    checked = check_response(invalid, result["task"], result["package"])
    assert checked["citations"][-1]["reading"] == "page-unverified"
    assert checked["citations"][-1]["bbox"] is None
    assert checked["claim_states"] == {"0": "review_required"}
    replay = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert replay["items"][0]["reused"]
    assert len(mock.requests) == 1
    assert sha256_file(original) == original_hash


def test_direct_supplement_reports_image_coverage_without_inventing_text(
    papers, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"fake-png-fixture" + str(page).encode(),
    )
    task = task_for(papers[:1], mode="direct")
    task["documents"][0].update(pages=[1], image_pages=[1])

    def generate(request):
        document = request["material"]["documents"][0]
        assert document["blocks"] == []
        synthetic = deepcopy(request)
        synthetic["material"]["documents"][0]["blocks"] = [
            {"id": None, "page": 1, "text": "Synthesis lasted 6 h at 180 C."}
        ]
        response = response_for(synthetic)
        if "evidence_update" not in request:
            response["requests"] = [
                {"source_id": "paper0", "pages": [2], "reason": "Read testing page"}
            ]
        else:
            assert "previous_candidate" not in request
            assert request["evidence_update"]["current_coverage"] == [
                {
                    "source_id": "paper0",
                    "current_text_pages": [],
                    "added_text_pages": [],
                    "current_image_pages": [1, 2],
                    "added_image_pages": [2],
                    "omitted_pages": [],
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
    assert manifest["status"] == "COMPLETED" and len(mock.requests) == 2
    result = json.loads(
        (Path(manifest["run_directory"]) / "paper0.result.json").read_text("utf-8")
    )
    assert result["validation"]["scientific_support"] == "not-verified"


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


@pytest.mark.parametrize("supplement_rounds", [0, 1])
def test_material_request_without_pages_preserves_result_and_waits_for_input(
    papers, tmp_path, supplement_rounds
):
    task = task_for(papers[:1])
    task["budget"]["max_supplement_rounds"] = supplement_rounds
    material_request = {
        "source_id": "paper0",
        "pages": [],
        "reason": "Please provide the supplementary methods; their pages are unknown.",
    }

    def generate(request):
        response = response_for(request)
        response["requests"] = [deepcopy(material_request)]
        return response

    mock = MockProvider(generate)
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 1
    assert manifest["status"] == "PARTIAL"
    assert manifest["items"][0]["supplement_status"] == "needs_input"
    result = json.loads(
        (Path(manifest["run_directory"]) / "paper0.result.json").read_text("utf-8")
    )
    assert result["response"] == generate(mock.requests[0])
    verify_result(result)
    report = (Path(manifest["run_directory"]) / "report.md").read_text("utf-8")
    assert "待补充材料" in report and material_request["reason"] in report
    cached_mock = MockProvider(generate)
    cached = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=cached_mock,
    )
    assert not cached_mock.requests
    assert cached["status"] == "PARTIAL" and cached["items"][0]["reused"]
    assert cached["items"][0]["supplement_status"] == "needs_input"

    # Empty pages do not relax source identity, page bounds or explanation rules.
    for invalid in (
        {**material_request, "source_id": "not-supplied"},
        {**material_request, "pages": [999]},
        {**material_request, "reason": " "},
    ):
        response = deepcopy(result["response"])
        response["requests"] = [invalid]
        with pytest.raises(ProcessingError, match="invalid_supplement_request"):
            check_response(response, result["task"], result["package"])


def test_material_request_does_not_block_known_page_supplement(papers, tmp_path):
    task = task_for(papers[:1])
    task["documents"][0]["pages"] = [1]

    def generate(request):
        response = response_for(request)
        response["requests"] = [
            {"source_id": "paper0", "pages": [], "reason": "Need the missing SI"}
        ]
        if 2 not in request["material"]["documents"][0]["pages_requested"]:
            response["requests"].append(
                {"source_id": "paper0", "pages": [2], "reason": "Read the limitations"}
            )
        return response

    mock = MockProvider(generate)
    manifest = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 2
    assert mock.requests[1]["material"]["documents"][0]["pages_requested"] == [1, 2]
    assert manifest["status"] == "PARTIAL"
    assert manifest["items"][0]["supplement_status"] == "needs_input"


@pytest.mark.parametrize(
    "initial_wait,new_page", [(False, False), (False, True), (True, True)]
)
def test_review_material_requests_cache_only_when_no_new_page_is_needed(
    papers, tmp_path, monkeypatch, initial_wait, new_page
):
    task = task_for(papers[:1], mode="hybrid")
    task["documents"][0]["pages"] = [1]
    task["budget"].update(max_review_rounds=1, max_repair_rounds=0)
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda pdf, page: b"fake-png-fixture" + str(page).encode(),
    )
    material_request = {
        "source_id": "paper0",
        "pages": [],
        "reason": "Need the missing SI",
    }
    final_requests = [material_request]
    if new_page:
        final_requests.append(
            {"source_id": "paper0", "pages": [2], "reason": "Read the testing page"}
        )

    def generate(request):
        if request["phase"] == "evidence_review":
            review = review_for(request)
            if any(target["kind"] == "field" for target in request["targets"]):
                review["requests"] = deepcopy(final_requests)
            return review
        if request["phase"] == "document_revision":
            assert request["revision_mode"] == "targeted"
            return {
                "replacements": {},
                "issues": [],
                "requests": deepcopy(final_requests),
            }
        response = response_for(request)
        if initial_wait:
            response["requests"] = [deepcopy(material_request)]
        return response

    kwargs = dict(base_dir=tmp_path, output_dir=tmp_path / "out", allow_remote=True)
    mock = MockProvider(generate)
    run = run_task(task, provider=mock, **kwargs)
    row = run["items"][0]
    assert run["status"] == "PARTIAL"
    assert len(mock.requests) == 4
    assert row["model_reviews"][0]["status"] == "COMPLETED"
    assert all(
        request["material"]["documents"][0]["pages_requested"] == [1]
        for request in mock.requests
    )  # Review requests do not start another automatic reading round.
    result = json.loads(
        (Path(run["run_directory"]) / "paper0.result.json").read_text("utf-8")
    )
    assert result["response"]["records"] == response_for(mock.requests[0])["records"]
    assert result["response"]["requests"] == final_requests
    verify_result(result)
    if new_page:
        assert row.get("supplement_status") not in {"needs_input", "no_new_material"}
        assert not list((tmp_path / "out" / "cache").glob("*.json"))
    else:
        assert row["supplement_status"] == "needs_input"

    resumed_mock = MockProvider(generate)
    resumed = run_task(task, provider=resumed_mock, **kwargs)
    assert resumed["status"] == "PARTIAL"
    assert resumed["items"][0]["reused"] is (not new_page)
    assert len(resumed_mock.requests) == (4 if new_page else 0)


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


@pytest.mark.parametrize("corrupt", ["page", "human_status", "step", "unknown_source"])
def test_invalid_model_references_and_confirmation_rejected(papers, tmp_path, corrupt):
    task = validate_task(task_for(papers[:1]))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    citation = response["records"][0]["fields"]["method"]["citations"][0]
    if corrupt == "page":
        citation["page"] = 999
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


@pytest.mark.parametrize("formats", [["csv"], ["markdown", "jsonl"]])
def test_comparison_only_csv_preserves_revision_provenance_and_safe_text(
    papers, tmp_path, formats
):
    task = validate_task({**task_for(papers[:1]), "export_formats": formats})
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    citation = response["records"][0]["fields"]["method"]["citations"][0]
    original = make_result(
        task,
        package,
        {"provider": "mock"},
        {
            "claims": [
                {
                    "text": "Initial reading",
                    "nature": "ai_synthesis",
                    "citations": [citation],
                }
            ],
            "issues": [],
        },
        comparison=True,
    )
    revision = {
        "claim_index": 0,
        "replacement": {
            "text": '=HYPERLINK("https://example.invalid","not an active formula")\n第二行, quoted',
            "nature": "ai_synthesis",
            "citations": [citation],
        },
        "author": "test assistant",
        "authority": "assistant",
        "at": "2026-10-26",
        "reason": "Test reviewed comparison export",
        "confirm": False,
    }
    revised = revise_result(original, revision)
    source_file = tmp_path / "comparison.json"
    source_file.write_text(json.dumps(revised), encoding="utf-8")
    before = sha256_file(source_file)
    output = tmp_path / "comparison-export"
    assert main(["export", str(source_file), "--output-dir", str(output)]) == 0
    assert sha256_file(source_file) == before
    if "csv" in formats:
        assert b"\r\r\n" not in (output / "claims.csv").read_bytes()
        with (output / "claims.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1
        assert rows[0]["text"] == "'" + revision["replacement"]["text"]
        assert rows[0]["claim_index"] == "0"
        assert rows[0]["result_id"] == revised["artifact_id"]
        assert rows[0]["nature"] == "ai_synthesis"
        assert rows[0]["state"] == "review_required"
        assert json.loads(rows[0]["sources"]) == [citation]
        assert not (output / "claims.jsonl").exists()
    else:
        assert not (output / "claims.csv").exists()
        exported = json.loads((output / "claims.jsonl").read_text("utf-8"))
        assert exported["text"] == revision["replacement"]["text"]
        assert exported["state"] == "review_required"


def test_assistant_revisions_revoke_confirmation_and_cannot_self_confirm(
    papers, tmp_path
):
    from aletheia_nexus.processing.results import seal_result

    task = validate_task(task_for(papers[:1]))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    response["claims"] = [
        {
            "text": "The reported synthesis temperature is 180 C.",
            "nature": "reported",
            "citations": deepcopy(
                response["records"][0]["fields"]["method"]["citations"]
            ),
        }
    ]
    result = make_result(task, package, {"provider": "mock"}, response)
    for target, identity, replacement in (
        ("record_id", "r1", response["records"][0]),
        ("claim_index", 0, response["claims"][0]),
    ):
        revision = {
            target: identity,
            "replacement": deepcopy(replacement),
            "author": "reviewer",
            "at": "2026-10-26",
            "reason": "Fixture review",
            "confirm": True,
        }
        result = revise_result(result, revision)
        revision.update(authority="assistant", author="assistant reviewer")
        with pytest.raises(ValueError, match="explicit human"):
            revise_result(result, revision)
        revision["confirm"] = False
        if target == "record_id":
            revision["replacement"]["fields"]["method"]["context"] = (
                "Assistant reviewed scope."
            )
        else:
            revision["replacement"]["text"] = (
                "Synthesis temperature was 180 C in this setup."
            )
        result = revise_result(result, revision)
        verify_result(result)
        states = result["validation"][
            "record_states" if target == "record_id" else "claim_states"
        ]
        assert states[str(identity)] == "review_required"
        assert result["history"][-1]["authority"] == "assistant"
        forged = deepcopy(result)
        forged["history"][-1]["confirm"] = True
        seal_result(forged)
        with pytest.raises(ValueError, match="explicit human"):
            verify_result(forged)


def test_issue_revision_cli_keeps_original_and_exports_corrected_diagnosis(
    papers, tmp_path
):
    task = validate_task(task_for(papers[:1]))
    source = load_source(task["documents"][0], tmp_path, task["mode"])
    package, _ = build_package(task, [source])
    response = response_for({"material": package, "fields": task["fields"]})
    response["issues"] = [
        {
            "kind": "source_ambiguous",
            "detail": "Incorrect diagnosis in fixture.",
            "source_id": "paper0",
            "page": 1,
        }
    ]
    result = make_result(task, package, {"provider": "mock"}, response)
    original = tmp_path / "original.result.json"
    original.write_text(json.dumps(result), encoding="utf-8")
    original_hash = sha256_file(original)
    revision = {
        "issue_index": 0,
        "replacement": {
            "kind": "strategy_problem",
            "detail": "The model misread the source; correction recorded.",
            "source_id": "paper0",
            "page": 1,
        },
        "authority": "assistant",
        "author": "assistant reviewer",
        "at": "2026-10-26",
        "reason": "Checked the original page; preserve the old diagnosis in history.",
        "confirm": False,
    }
    patch = tmp_path / "revision.json"
    patch.write_text(json.dumps(revision), encoding="utf-8")
    updated_path = tmp_path / "updated.result.json"
    assert (
        main(["revise", str(original), str(patch), "--output", str(updated_path)]) == 0
    )
    updated = json.loads(updated_path.read_text("utf-8"))
    verify_result(updated)
    assert sha256_file(original) == original_hash
    assert updated["history"][-1]["before"] == response["issues"][0]
    assert updated["history"][-1]["parent_result_id"] == result["artifact_id"]
    assert updated["validation"] == result["validation"]
    assert (
        main(["export", str(updated_path), "--output-dir", str(tmp_path / "export")])
        == 0
    )
    report = (tmp_path / "export/report.md").read_text("utf-8")
    assert "The model misread the source" in report
    assert "Incorrect diagnosis" not in report
    # Diagnosis changes cannot invent source positions or grant confirmation.
    revision["replacement"]["page"] = 999
    with pytest.raises(ProcessingError, match="invalid_issue_location"):
        revise_result(updated, revision)
    revision["replacement"]["page"] = 1
    revision.update(authority="human", confirm=True)
    with pytest.raises(ValueError, match="confirm=false"):
        revise_result(updated, revision)
    revision["confirm"] = False
    revision["claim_index"] = 0
    with pytest.raises(ValueError, match="exactly one"):
        revise_result(updated, revision)


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


@pytest.mark.parametrize("defect", ["quote", "empty_quote", "missing_citations"])
def test_unmatched_reading_preserves_output_without_spending_on_repairs(
    papers, tmp_path, defect
):
    def generate(request):
        answer = response_for(request)
        field = answer["records"][0]["fields"]["method"]
        if defect == "missing_citations":
            field["citations"] = []
        else:
            field["citations"][0]["quote"] = "999 C" if defect == "quote" else ""
        answer["claims"] = [
            {
                "text": "A reading requiring source review",
                "nature": "reported",
                "citations": deepcopy(field["citations"]),
            }
        ]
        return answer

    mock = MockProvider(generate)
    run = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 1 and run["status"] == "COMPLETED"
    directory = Path(run["run_directory"])
    assert not list(directory.glob("*.rejected.json"))
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    assert result["response"] == generate(mock.requests[0])
    assert result["validation"]["record_states"] == {"r1": "review_required"}
    assert result["validation"]["claim_states"] == {"0": "review_required"}
    assert result["validation"]["scientific_support"] == "not-verified"
    if defect != "missing_citations":
        assert result["validation"]["citations"][-1]["reading"] == (
            "parsed-quotation-unverified"
        )
    verify_result(result)


@pytest.mark.parametrize("defect", ["wrong_block", "wrong_page", "page_only"])
def test_imprecise_block_preserves_real_page_link(papers, tmp_path, defect):
    def generate(request):
        answer = response_for(request)
        citation = answer["records"][0]["fields"]["method"]["citations"][0]
        if defect == "wrong_block":
            citation["block_id"] = "nonexistent-block"
        elif defect == "wrong_page":
            citation["page"] = 2
        else:
            citation["block_id"] = None
        return answer

    mock = MockProvider(generate)
    run = run_task(
        task_for(papers[:1]),
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    assert run["status"] == "COMPLETED" and len(mock.requests) == 1
    directory = Path(run["run_directory"])
    original = json.loads((directory / "paper0.0.candidate.json").read_text("utf-8"))
    result = json.loads((directory / "paper0.result.json").read_text("utf-8"))
    assert result["response"] == original
    assert result["validation"]["record_states"] == {"r1": "review_required"}
    assert any(
        c["reading"] == "page-unverified" for c in result["validation"]["citations"]
    )
    assert result["validation"]["scientific_support"] == "not-verified"
    verify_result(result)


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
    if scope == "changed_symbol":
        checked = check_response(answer, task, package)
        assert checked["record_states"] == {"r1": "review_required"}
        assert checked["citations"][-1]["reading"] == "parsed-quotation-unverified"
        assert citation["quote"] == "Temperature was −95 °C."
        assert block["text"] == "Temperature was ~95 °C."
    else:
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
    for status in ("reported", "normalized"):
        context_only = deepcopy(answer)
        context_only["records"][0]["fields"]["method"].update(
            value=None, raw_value=field["value"], context=field["value"], status=status
        )
        unchanged = deepcopy(context_only)
        with pytest.raises(ProcessingError, match="missing_original_value"):
            check_response(context_only, task, package)
        assert context_only == unchanged
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
