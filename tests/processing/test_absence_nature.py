"""An unspecified nature for an absent value is not a scientific classification."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_workflow import MockProvider, response_for, task_for
from test_workflow import papers as papers

from aletheia_nexus.processing.contracts import response_schema, validate
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import (
    check_response,
    export_results,
    revise_result,
    verify_result,
)


@pytest.fixture
def absent_response():
    task = {"fields": [{"id": "duration", "type": "string"}]}
    response = {
        "records": [
            {
                "id": "r1",
                "subject": "sample",
                "stage": "measurement",
                "fields": {
                    "duration": {
                        "value": None,
                        "raw_value": None,
                        "unit": None,
                        "status": "not_reported",
                        "nature": None,
                        "context": "No duration was supplied for this measurement.",
                        "citations": [],
                        "step_ids": [],
                    }
                },
                "steps": [],
            }
        ],
        "claims": [],
        "issues": [],
        "requests": [],
    }
    return task, {"documents": [], "images": []}, response


def test_absent_nature_is_preserved_without_classification(absent_response):
    task, package, response = absent_response
    original = deepcopy(response)
    validate(response, response_schema(task), "response")
    checked = check_response(response, task, package)
    assert checked["record_states"] == {"r1": "evidence_insufficient"}
    assert response == original


@pytest.mark.parametrize(
    "status", ["reported", "normalized", "ambiguous", "unconfirmed"]
)
def test_other_statuses_still_require_nature(absent_response, status):
    task, package, response = absent_response
    response["records"][0]["fields"]["duration"].update(
        status=status, value="brief", raw_value="brief"
    )
    with pytest.raises(ProcessingError, match="missing_field_nature"):
        check_response(response, task, package)


@pytest.mark.parametrize("key", ["value", "raw_value", "unit"])
def test_absent_nature_does_not_allow_a_missing_value_to_have_content(
    absent_response, key
):
    task, package, response = absent_response
    response["records"][0]["fields"]["duration"][key] = "6 h"
    with pytest.raises(ProcessingError, match="invented_missing_value"):
        check_response(response, task, package)


@pytest.mark.parametrize("kind", ["step", "claim"])
def test_steps_and_claims_keep_string_nature(absent_response, kind):
    task, package, response = absent_response
    if kind == "step":
        response["records"][0]["steps"] = [
            {
                "id": "s1",
                "order": 1,
                "description": "Measure the sample.",
                "nature": None,
                "citations": [],
            }
        ]
    else:
        response["claims"] = [
            {"text": "A measurement was reported.", "nature": None, "citations": []}
        ]
    with pytest.raises(ValueError, match="nature"):
        check_response(response, task, package)


def test_absent_nature_does_not_bypass_citations_or_reported_values(absent_response):
    task, package, response = absent_response
    field = response["records"][0]["fields"]["duration"]
    field["citations"] = [
        {"source_id": "missing", "block_id": None, "page": 1, "quote": "No duration"}
    ]
    with pytest.raises(ProcessingError, match="invalid_citation"):
        check_response(response, task, package)
    field.update(citations=[], status="reported")
    with pytest.raises(ProcessingError, match="missing_original_value"):
        check_response(response, task, package)
    field.update(status="not_reported", nature="unknown")
    with pytest.raises(ValueError, match="nature"):
        check_response(response, task, package)


def test_absent_nature_roundtrips_run_export_and_explicit_revision(papers, tmp_path):
    task = task_for(papers[:1])

    def generate(request):
        response = response_for(request)
        response["records"][0]["fields"]["method"].update(
            value=None,
            raw_value=None,
            unit=None,
            nature=None,
            status="not_reported",
            context="The selected material does not report the requested condition.",
            citations=[],
            step_ids=[],
        )
        return response

    mock = MockProvider(generate)
    run = run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "run",
        allow_remote=True,
        provider=mock,
    )
    assert len(mock.requests) == 1
    directory = Path(run["run_directory"])
    result = json.loads((directory / run["items"][0]["result"]).read_text("utf-8"))
    verify_result(result)
    original = deepcopy(result)
    replacement = deepcopy(result["response"]["records"][0])
    replacement["fields"]["method"]["context"] += " Scope checked locally."
    revised = revise_result(
        result,
        {
            "record_id": "r1",
            "replacement": replacement,
            "author": "test-reviewer",
            "at": "2026-10-28T00:00:00Z",
            "reason": "Clarify the supplied scope without classifying absent content.",
            "confirm": False,
            "authority": "assistant",
        },
    )
    verify_result(revised)
    assert result == original
    assert revised["response"]["records"][0]["fields"]["method"]["nature"] is None
    output = tmp_path / "export"
    output.mkdir()
    export_results([revised], revised["task"], output)
    assert "未指定 / 材料中未报告" in (output / "report.md").read_text("utf-8")
    record = json.loads((output / "records.jsonl").read_text("utf-8"))
    assert record["fields"]["method"]["nature"] is None
    assert (output / "table.csv").exists()
