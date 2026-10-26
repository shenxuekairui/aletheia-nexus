"""Metadata projection preserves science and its history without paid repair calls."""

import json
from copy import deepcopy
from pathlib import Path

from test_workflow import (
    MockProvider,
    response_for,
    review_for,
    task_for,
)
from test_workflow import (
    papers as papers,
)

from aletheia_nexus.processing.contracts import digest
from aletheia_nexus.processing.engine import run_task


def test_metadata_projection_survives_review_revision_cache_and_detects_changed_raw(
    papers, tmp_path
):
    task = task_for(papers[:1])
    task["budget"]["max_review_rounds"] = 1

    def generate(request):
        if request["phase"] == "evidence_review":
            review = review_for(request)
            for check, target in zip(review["checks"], request["targets"]):
                check.update(target)
                if check["target_id"] == "record:0/steps":
                    check["verdict"] = "revise"
            return review
        if request["phase"] == "document_revision":
            record = request["candidate"]["records"][0]
            steps = deepcopy(record["steps"])
            steps[0]["citations_note"] = "not_a_field"
            return {
                "replacements": {
                    "record:0/steps": {
                        "steps": steps,
                        "field_step_ids": {"method": ["s1"]},
                    }
                },
                "issues": [],
                "requests": [],
            }
        response = response_for(request)
        response["records"][0]["ordering_hint"] = []
        response["claims"] = [
            {
                "text": response["records"][0]["steps"][0]["description"],
                "nature": "reported",
                "citations": response["records"][0]["steps"][0]["citations"],
                "step_ids": [],
            }
        ]
        return response

    mock = MockProvider(generate)
    output = tmp_path / "out"

    def run():
        return run_task(
            task, base_dir=tmp_path, output_dir=output, allow_remote=True, provider=mock
        )

    first = run()
    row = first["items"][0]
    assert row["status"] == "COMPLETED"
    assert len(mock.requests) == 4  # Extraction, two review batches, targeted revision.
    assert not row.get("output_repairs")
    assert len(row["response_metadata"]) == 4
    directory = Path(first["run_directory"])
    result = json.loads((directory / row["result"]).read_text("utf-8"))
    before = json.loads((directory / "paper0.review1.input.json").read_text("utf-8"))
    assert result["response"] == before  # No scientific content was rewritten.

    cached = run()
    assert cached["items"][0]["reused"]
    assert len(mock.requests) == 4
    for entry in row["response_metadata"]:
        assert (Path(cached["run_directory"]) / entry["file"]).read_bytes() == (
            directory / entry["file"]
        ).read_bytes()

    cache_file = next((output / "cache").glob("*.json"))
    envelope = json.loads(cache_file.read_text("utf-8"))
    entry = envelope["response_metadata"][0]
    proof = envelope["metadata_artifacts"][entry["file"]]
    raw = json.loads(proof["raw_text"])
    raw["records"][0]["steps"][0]["description"] = "Changed science"
    proof["raw_text"] = json.dumps(raw)
    entry["sha256"] = digest(
        proof
    )  # Hash alone is insufficient; projection must replay.
    cache_file.write_text(json.dumps(envelope), "utf-8")
    rebuilt = run()
    assert not rebuilt["items"][0]["reused"]
    assert len(mock.requests) == 8


def test_comparison_metadata_history_is_preserved_on_resume(papers, tmp_path):
    task = task_for(papers, kind="compare")

    def generate(request):
        if request["phase"] != "cross_document_synthesis":
            return response_for(request)
        return {
            "claims": [
                {
                    "text": "The supplied methods have the same reported duration.",
                    "nature": "ai_synthesis",
                    "citations": [],
                    "step_ids": [],
                }
            ],
            "issues": [],
        }

    mock = MockProvider(generate)
    kwargs = dict(
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=mock,
    )
    first = run_task(task, **kwargs)
    assert first["comparison"]["status"] == "COMPLETED"
    assert len(mock.requests) == 3
    second = run_task(task, **kwargs)
    assert second["comparison"]["reused"]
    assert len(mock.requests) == 3
    assert (
        second["comparison"]["response_metadata"]
        == first["comparison"]["response_metadata"]
    )
    assert (
        Path(second["run_directory"]) / "comparison.metadata.json"
    ).read_bytes() == (
        Path(first["run_directory"]) / "comparison.metadata.json"
    ).read_bytes()


def test_disabled_steps_completion_keeps_raw_and_replays_additions_on_resume(
    papers, tmp_path
):
    task = {**task_for(papers[:1]), "include_steps": False}

    def generate(request):
        response = response_for(request)
        record = response["records"][0]
        del record["steps"]
        del record["fields"]["method"]["step_ids"]
        return response

    mock = MockProvider(generate)
    output = tmp_path / "out"
    kwargs = dict(
        base_dir=tmp_path, output_dir=output, allow_remote=True, provider=mock
    )
    first = run_task(task, **kwargs)
    row = first["items"][0]
    assert row["status"] == "COMPLETED" and not row.get("output_repairs")
    assert len(mock.requests) == 1
    directory = Path(first["run_directory"])
    raw = json.loads((directory / "paper0.0.candidate.json").read_text("utf-8"))
    result = json.loads((directory / row["result"]).read_text("utf-8"))
    expected = deepcopy(raw)
    expected["records"][0]["steps"] = []
    expected["records"][0]["fields"]["method"]["step_ids"] = []
    assert result["response"] == expected
    entry = row["response_metadata"][0]
    proof = json.loads((directory / entry["file"]).read_text("utf-8"))
    assert json.loads(proof["raw_text"]) == raw
    assert len(proof["changes"]) == 2
    assert all(change["operation"] == "add" for change in proof["changes"])

    cached = run_task(task, **kwargs)
    assert cached["items"][0]["reused"] and len(mock.requests) == 1
    assert (Path(cached["run_directory"]) / entry["file"]).read_bytes() == (
        directory / entry["file"]
    ).read_bytes()

    cache_file = next((output / "cache").glob("*.json"))
    envelope = json.loads(cache_file.read_text("utf-8"))
    proof = envelope["metadata_artifacts"][entry["file"]]
    proof["changes"][0]["value"] = ["forged addition"]
    envelope["response_metadata"][0]["sha256"] = digest(proof)
    cache_file.write_text(json.dumps(envelope), "utf-8")
    rebuilt = run_task(task, **kwargs)
    assert not rebuilt["items"][0]["reused"] and len(mock.requests) == 2
