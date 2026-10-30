"""Literal location recovery changes no scientific value or model output."""

import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_workflow import MockProvider, response_for, task_for, write_pdf
from test_workflow import papers as papers

import aletheia_nexus.processing.results as results
from aletheia_nexus.content import parse_document
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.processing.contracts import validate_task
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.materials import build_package, load_source


def wrong_location(request):
    response = response_for(request)
    correct = deepcopy(response["records"][0]["fields"]["method"]["citations"][0])
    wrong = {**correct, "page": 2, "block_id": "unknown"}
    record = response["records"][0]
    record["fields"]["method"]["citations"] = [deepcopy(wrong)]
    record["steps"][0]["citations"] = [deepcopy(wrong)]
    response["claims"] = [
        {
            "text": record["steps"][0]["description"],
            "nature": "reported",
            "citations": [deepcopy(wrong)],
        }
    ]
    return response


def test_engine_exact_location_keeps_raw_and_science_replays_cache_export_revision(
    tmp_path, papers
):
    task = task_for(papers[:1])
    task["budget"].update(max_calls=1, max_repair_rounds=0, max_review_rounds=0)
    provider = MockProvider(wrong_location)
    output = tmp_path / "out"

    def run():
        return run_task(
            task,
            base_dir=tmp_path,
            output_dir=output,
            allow_remote=True,
            provider=provider,
        )

    manifest = run()
    row = manifest["items"][0]
    assert row["status"] == "COMPLETED" and len(provider.requests) == 1
    directory = Path(manifest["run_directory"])
    raw_path = directory / "paper0.0.candidate.json"
    raw_bytes = raw_path.read_bytes()
    raw = json.loads(raw_bytes)
    result = json.loads((directory / row["result"]).read_text("utf-8"))
    results.verify_result(result)
    proof = result["citation_source_resolution"]
    assert proof["version"] == 2 and len(proof["changes"]) == 3
    restored = deepcopy(result["response"])
    for change in proof["changes"]:
        assert change["after"]["source_id"] == change["before"]["source_id"]
        assert change["after"]["quote"] == change["before"]["quote"]
        assert change["after"]["page"] == 1 and change["after"]["block_id"] != "unknown"
        assert (
            change["evidence"]["match_mode"] == "same_source_single_block_unique_quote"
        )
        parent = restored
        for key in change["path"][:-1]:
            parent = parent[key]
        parent[change["path"][-1]] = deepcopy(change["before"])
    assert restored == raw
    assert result["validation"]["record_states"] == {"r1": "review_required"}
    assert result["validation"]["claim_states"] == {"0": "review_required"}
    assert all(
        c["reading"] == "source-location-unverified" and c["support"] == "not-verified"
        for c in result["validation"]["citations"]
    )
    assert "同源唯一原句" in (directory / "report.md").read_text("utf-8")
    assert "page=1" in (directory / "report.md").read_text("utf-8")
    exported = json.loads((directory / "records.jsonl").read_text("utf-8"))
    assert exported["citation_source_resolution"] == proof
    assert exported["state"] == "review_required"
    with (directory / "table.csv").open(encoding="utf-8-sig", newline="") as stream:
        exported_row = next(csv.DictReader(stream))
    assert all(c["page"] == 1 for c in json.loads(exported_row["sources"]))
    assert exported_row["result_id"] == result["artifact_id"]
    cache = next((output / "cache").glob("*.json"))
    cache_bytes = cache.read_bytes()
    resumed = run()
    assert resumed["items"][0]["reused"] and len(provider.requests) == 1
    assert cache.read_bytes() == cache_bytes and raw_path.read_bytes() == raw_bytes
    assert (
        json.loads(
            (Path(resumed["run_directory"]) / resumed["items"][0]["result"]).read_text(
                "utf-8"
            )
        )
        == result
    )
    revision = results.revise_result(
        result,
        {
            "record_id": "r1",
            "replacement": deepcopy(result["response"]["records"][0]),
            "author": "self-authored fixture",
            "authority": "assistant",
            "at": "2026-10-30T00:00:00Z",
            "reason": "Review locator separately from scientific support",
            "confirm": False,
        },
    )
    results.verify_result(revision)
    assert revision["validation"]["record_states"]["r1"] == "review_required"
    for key, value in (
        ("version", 1),
        ("reason", "guessed"),
        ("block_hash", "changed"),
    ):
        modified = deepcopy(result)
        if key == "version":
            modified["citation_source_resolution"][key] = value
        elif key == "reason":
            modified["citation_source_resolution"]["changes"][0][key] = value
        else:
            modified["citation_source_resolution"]["changes"][0]["evidence"][
                "block_text_sha256"
            ] = value
        results.seal_result(modified)
        with pytest.raises(ValueError, match="does not replay"):
            results.verify_result(modified)


def test_legacy_v1_unresolved_valid_cache_reuses_without_changing_old_bytes(
    tmp_path, papers, monkeypatch
):
    task = task_for(papers[:1])
    task["budget"].update(max_calls=1, max_repair_rounds=0, max_review_rounds=0)
    provider = MockProvider(wrong_location)
    output = tmp_path / "legacy"
    kwargs = dict(
        base_dir=tmp_path, output_dir=output, allow_remote=True, provider=provider
    )
    resolver = results.resolve_citation_source_ids
    # Version 1 explicitly preserves the old legal-page/unverified-quote behavior.
    with monkeypatch.context() as legacy:
        legacy.setattr(
            results,
            "resolve_citation_source_ids",
            lambda response, package, **_: resolver(response, package, version=1),
        )
        first = run_task(task, **kwargs)
    old_result_path = Path(first["run_directory"]) / first["items"][0]["result"]
    old_result_bytes = old_result_path.read_bytes()
    old_result = json.loads(old_result_bytes)
    assert "citation_source_resolution" not in old_result
    cache_path = next((output / "cache").glob("*.json"))
    cache_bytes = cache_path.read_bytes()
    second = run_task(task, **kwargs)
    assert second["items"][0]["reused"] and len(provider.requests) == 1
    assert (
        cache_path.read_bytes() == cache_bytes
        and old_result_path.read_bytes() == old_result_bytes
    )
    current = json.loads(
        (Path(second["run_directory"]) / second["items"][0]["result"]).read_text(
            "utf-8"
        )
    )
    assert current == old_result
    results.verify_result(current)


def test_v1_trace_never_replays_new_location_rules(tmp_path, papers, monkeypatch):
    original = tmp_path / "supplement.pdf"
    write_pdf(
        original,
        [
            [(50, 700, 12, line)]
            for line in ("Supplement", "Index", "Independent auxiliary source details.")
        ],
        title="Self-authored supplement",
    )
    supplement = register_local_pdf(
        original,
        output_dir=tmp_path / "library",
        title="Supplement",
        role="SUPPLEMENT",
        parent_pdf=papers[0],
    )
    parse_document(supplement)
    task = validate_task(task_for([papers[0], supplement]))
    sources = [
        load_source(config, tmp_path, task["mode"]) for config in task["documents"]
    ]
    package, _ = build_package(task, sources)
    response = response_for({"material": package, "fields": task["fields"]})
    main_citation = deepcopy(response["records"][0]["fields"]["method"]["citations"][0])
    si = next(d for d in package["documents"] if d["id"] == "paper1")
    block = next(b for b in si["blocks"] if b["page"] == 3)
    response["records"][0]["fields"]["method"]["citations"] = [
        {
            "source_id": "paper0",
            "page": 3,
            "block_id": block["id"],
            "quote": block["text"],
        },
        {**main_citation, "page": 2, "block_id": "unknown"},
    ]
    resolver = results.resolve_citation_source_ids
    with monkeypatch.context() as legacy:
        legacy.setattr(
            results,
            "resolve_citation_source_ids",
            lambda response, package, **_: resolver(response, package, version=1),
        )
        result = results.make_result(task, package, {"provider": "fixture"}, response)
    assert result["citation_source_resolution"]["version"] == 1
    assert len(result["citation_source_resolution"]["changes"]) == 1
    assert len(resolver(response, package, version=2)[1]) == 2
    results.verify_result(result)
    # Relabeling an old proof v2 without its missing location transformation fails.
    modified = deepcopy(result)
    modified["citation_source_resolution"]["version"] = 2
    results.seal_result(modified)
    with pytest.raises(ValueError, match="does not replay"):
        results.verify_result(modified)


def fixture():
    block = {
        "id": "b1",
        "page": 1,
        "text": "A microﬂuidic sample measured 5 m² at 3 h.",
    }
    source = {
        "id": "main",
        "source": {"page_count": 3},
        "pages_requested": [1, 2],
        "blocks": [block],
    }
    citation = {
        "source_id": "main",
        "page": 2,
        "block_id": "b2",
        "quote": "microfluidic sample measured 5 m²",
    }
    return {"claims": [{"citations": [citation]}]}, {"documents": [source]}


@pytest.mark.parametrize(
    "failure",
    [
        "correct_anchor_duplicate",
        "same_page_correct_anchor",
        "two_blocks",
        "same_block_repeat",
        "not_supplied",
        "unknown_source",
        "other_source_only",
        "empty",
        "ellipsis",
        "subscript_change",
        "hyphen_change",
        "only_image",
    ],
)
def test_v2_keeps_ambiguous_nonliteral_or_already_correct_anchors(failure):
    response, package = fixture()
    document = package["documents"][0]
    citation = response["claims"][0]["citations"][0]
    if failure == "correct_anchor_duplicate":
        citation.update(page=1, block_id="b1")
        document["blocks"].append({**document["blocks"][0], "page": 2, "id": "b2"})
    elif failure == "same_page_correct_anchor":
        citation.update(page=1, block_id="b1")
    elif failure == "two_blocks":
        document["blocks"].append({**document["blocks"][0], "page": 2, "id": "b3"})
    elif failure == "same_block_repeat":
        document["blocks"][0]["text"] *= 2
    elif failure == "not_supplied":
        document["pages_requested"] = [2]
    elif failure == "unknown_source":
        citation["source_id"] = "unknown"
    elif failure == "other_source_only":
        package["documents"].append({**deepcopy(document), "id": "other"})
        document["blocks"] = []
    elif failure == "empty":
        citation["quote"] = ""
    elif failure == "ellipsis":
        citation["quote"] = "microfluidic … 5 m²"
    elif failure == "subscript_change":
        citation["quote"] = "5 m2"
    elif failure == "hyphen_change":
        document["blocks"][0]["text"] = "The continuous- flow experiment."
        citation["quote"] = "continuous-flow experiment."
    else:
        document["blocks"] = []
        package["images"] = [{"source_id": "main", "page": 1}]
    original = deepcopy((response, package))
    adjusted, changes = results.resolve_citation_source_ids(
        response, package, version=2
    )
    assert (adjusted, changes) == (response, [])
    assert (response, package) == original


def test_v2_fixes_only_block_when_same_page_has_unique_literal():
    response, package = fixture()
    response["claims"][0]["citations"][0]["page"] = 1
    old_response = deepcopy(response)
    adjusted, changes = results.resolve_citation_source_ids(
        response, package, version=2
    )
    assert len(changes) == 1
    citation = adjusted["claims"][0]["citations"][0]
    assert citation == {**old_response["claims"][0]["citations"][0], "block_id": "b1"}
    assert results.resolve_citation_source_ids(old_response, package) == (
        old_response,
        [],
    )
