from copy import deepcopy

import pytest

from aletheia_nexus.processing.contracts import validate_task
from aletheia_nexus.processing.review import (
    apply_revision,
    review_batches,
    review_targets,
    revision_mode,
    revision_schema,
)


def test_review_groups_cover_each_target_once_and_hide_other_field_answers():
    candidate = {
        "records": [
            {
                "id": str(i),
                "subject": "sample",
                "stage": str(i),
                "fields": {f"f{j}": {"value": f"answer-{i}-{j}"} for j in range(7)},
                "steps": [{"id": "s1"}],
            }
            for i in range(2)
        ],
        "claims": [{"text": "claim"}],
        "issues": [],
        "requests": [],
    }
    before = deepcopy(candidate)
    batches = review_batches(candidate)
    targets = [t["target_id"] for group, _ in batches for t in group]
    assert len(targets) == len(set(targets)) == len(review_targets(candidate))
    assert set(targets) == {t["target_id"] for t in review_targets(candidate)}
    for group, view in batches[:-1]:
        assert len(group) <= 4
        for index, record in enumerate(view["records"]):
            expected = {
                t["field_id"]
                for t in group
                if "field_id" in t and t["target_id"].startswith(f"record:{index}/")
            }
            assert set(record["fields"]) == expected
            assert record["steps"] == candidate["records"][index]["steps"]
    assert batches[-1][1] == before
    batches[0][1]["records"][0]["fields"].clear()
    assert candidate == before


def test_default_model_thinks_with_room_for_reasoning_and_review_remains_opt_in():
    task = validate_task(
        {
            "schema": "aletheia-nexus/research-task/v1",
            "id": "example",
            "type": "extract",
            "objective": "Compare methods",
            "documents": [{"id": "p", "artifact": "p.json"}],
            "fields": [{"id": "method", "type": "string", "description": "method"}],
            "model": {"name": "deepseek-flash"},
        }
    )
    assert task["model"]["reasoning_effort"] == "high"
    assert task["model"]["timeout_seconds"] == 300
    assert task["budget"]["max_output_tokens"] == 65536
    assert task["budget"]["max_review_rounds"] == 0
    assert task["mode"] == "local" and not task["allow_remote"]


def revision_example():
    task = {
        "fields": [
            {"id": "method", "type": "string"},
            {"id": "duration", "type": "number"},
        ]
    }
    field = {
        "value": "Keep the full method, control and limitations.",
        "raw_value": None,
        "unit": None,
        "status": "reported",
        "nature": "reported",
        "context": "Preserve original sample/condition association.",
        "citations": [],
        "step_ids": ["s1"],
    }
    candidate = {
        "records": [
            {
                "id": "r1",
                "subject": "sample",
                "stage": "synthesis",
                "fields": {
                    "method": field,
                    "duration": {
                        **deepcopy(field),
                        "value": 6,
                        "raw_value": "6 h",
                        "unit": "h",
                    },
                },
                "steps": [
                    {
                        "id": "s1",
                        "order": 1,
                        "description": "Synthesize",
                        "nature": "reported",
                        "citations": [],
                    }
                ],
            }
        ],
        "claims": [
            {"text": text, "nature": "reported", "citations": []}
            for text in ("wrong", "keep", "correct last")
        ],
        "issues": [],
        "requests": [],
    }
    review = {
        "checks": [
            {
                "target_id": t["target_id"],
                "verdict": "supported",
                "detail": "Source checked",
                "citations": [],
            }
            for t in review_targets(candidate)
        ],
        "issues": [],
        "requests": [],
    }
    return task, candidate, review


def test_target_replacements_preserve_other_content_and_claim_indices():
    task, candidate, review = revision_example()
    selected = {"record:0/field:duration", "claim:0", "claim:2"}
    for check in review["checks"]:
        if check["target_id"] in selected:
            check["verdict"] = "revise"
    before = deepcopy(candidate)
    changed = {
        **deepcopy(candidate["records"][0]["fields"]["duration"]),
        "value": 8,
        "raw_value": "8 h",
    }
    patch = {
        "replacements": {
            "record:0/field:duration": changed,
            "claim:0": None,
            "claim:2": {"text": "revised last", "nature": "reported", "citations": []},
        },
        "issues": [],
        "requests": [],
    }
    revised = apply_revision(candidate, patch, task, review)
    assert candidate == before
    assert (
        revised["records"][0]["fields"]["method"]
        == before["records"][0]["fields"]["method"]
    )
    assert revised["records"][0]["steps"] == before["records"][0]["steps"]
    assert revised["records"][0]["fields"]["duration"]["value"] == 8
    assert [c["text"] for c in revised["claims"]] == ["keep", "revised last"]
    patch["replacements"]["record:0/field:duration"]["value"] = "8"
    with pytest.raises(ValueError, match="invalid type"):
        apply_revision(candidate, patch, task, review)
    patch["replacements"]["record:0/field:duration"]["value"] = 8
    patch["replacements"]["record:0/field:method"] = before["records"][0]["fields"][
        "method"
    ]
    with pytest.raises(ValueError, match="unknown keys"):
        apply_revision(candidate, patch, task, review)


def test_procedure_reassociates_only_step_ids_and_keeps_scientific_content():
    task, candidate, review = revision_example()
    for check in review["checks"]:
        if check["target_id"] in {"record:0/steps", "record:0/field:duration"}:
            check["verdict"] = "uncertain"
    schema = revision_schema(task, candidate, review)
    mappings = schema["properties"]["replacements"]["properties"]["record:0/steps"][
        "properties"
    ]["field_step_ids"]["properties"]
    assert set(mappings) == {"method"}  # Selected duration carries its own association.
    duration = {
        **deepcopy(candidate["records"][0]["fields"]["duration"]),
        "step_ids": ["s2"],
    }
    patch = {
        "replacements": {
            "record:0/steps": {
                "steps": [{**candidate["records"][0]["steps"][0], "id": "s2"}],
                "field_step_ids": {"method": ["s2"]},
            },
            "record:0/field:duration": duration,
        },
        "issues": [],
        "requests": [],
    }
    revised = apply_revision(candidate, patch, task, review)
    assert revised["records"][0]["fields"]["method"] == {
        **candidate["records"][0]["fields"]["method"],
        "step_ids": ["s2"],
    }
    assert revised["records"][0]["fields"]["duration"]["step_ids"] == ["s2"]
    assert candidate["records"][0]["steps"][0]["id"] == "s1"


def test_coverage_and_diagnostic_routing_do_not_force_routine_full_rewrites():
    _, candidate, review = revision_example()
    assert revision_mode(review, candidate) == "unchanged"
    review["checks"][1].update(
        verdict="revise", detail="This method field omits a reported condition."
    )
    assert revision_mode(review, candidate) == "targeted"
    review["checks"][0].update(
        verdict="revise", detail="A requested second experimental stage has no record."
    )
    assert revision_mode(review, candidate) == "full_coverage"
    for check in review["checks"]:
        check["verdict"] = "supported"
    review["requests"] = [
        {"source_id": "p", "pages": [2], "reason": "Read missing original context"}
    ]
    assert revision_mode(review, candidate) == "targeted"
    assert (
        revision_schema(
            {
                "fields": [
                    {"id": "method", "type": "string"},
                    {"id": "duration", "type": "number"},
                ]
            },
            candidate,
            review,
        )["properties"]["replacements"]["properties"]
        == {}
    )
