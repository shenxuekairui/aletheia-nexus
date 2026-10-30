"""Lossless budget recovery changes only otherwise rejected assembly requests."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_source_first import generate, inventory_for, source_task
from test_workflow import MockProvider
from test_workflow import papers as papers

from aletheia_nexus.processing import engine
from aletheia_nexus.processing.contracts import digest, validate_task
from aletheia_nexus.processing.materials import build_package, load_source
from aletheia_nexus.processing.presentation import compact_material, decompress_material
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.source_first import (
    INVENTORY_PHASE,
    assembly_request,
    inventory_request,
)


def request_for(papers, tmp_path):
    task = validate_task(source_task(papers))
    package, _ = build_package(
        task, [load_source(task["documents"][0], tmp_path, task["mode"])]
    )
    return task, engine._request(task, package)


def length(request):
    return len(json.dumps(request, ensure_ascii=False))


def test_same_successful_inventory_survives_input_guard_failure_without_repayment(
    papers, tmp_path, monkeypatch
):
    task, original = request_for(papers, tmp_path)
    assembly = assembly_request(original, inventory_for(inventory_request(original)))
    task["budget"]["max_input_characters"] = max(
        length(inventory_request(original)), length(compact_material(assembly))
    )
    assert task["budget"]["max_input_characters"] < length(assembly)
    before = deepcopy(task)
    output = tmp_path / "output"
    provider = MockProvider(generate)
    kwargs = dict(
        base_dir=tmp_path, output_dir=output, allow_remote=True, provider=provider
    )
    # Emulate the previously released guard: successful reading, rejected assembly.
    with monkeypatch.context() as old:
        old.setattr(
            engine, "_fit_assembly_request", lambda task, request: (request, None)
        )
        failed = engine.run_task(task, **kwargs)
    assert failed["items"][0]["error"] == "input_budget_exceeded"
    assert len(failed["calls"]) == len(provider.requests) == 1
    # The package identity includes the final budget, so compare against the
    # actual pre-fix input rather than the earlier size-calculation package.
    assembly = json.loads(
        next(
            Path(failed["run_directory"]).glob("*.source-first-assembly.input.json")
        ).read_text("utf8")
    )["request"]
    cache = next((output / "cache").glob("source-inventory-*.json"))
    saved_inventory = cache.read_bytes()
    failed_manifest = Path(failed["run_directory"]) / "manifest.json"
    failed_bytes = failed_manifest.read_bytes()
    recovered = engine.run_task(task, **kwargs)
    assert recovered["status"] == "COMPLETED" and len(recovered["calls"]) == 1
    assert [r["phase"] for r in provider.requests] == [
        INVENTORY_PHASE,
        "document_extraction",
    ]
    assert decompress_material(provider.requests[-1]) == assembly
    assert cache.read_bytes() == saved_inventory
    assert failed_manifest.read_bytes() == failed_bytes and task == before
    item = recovered["items"][0]
    assert item["source_inventories"][0]["reused"]
    assert item["source_inventories"][0]["usage_owner_run"] == failed["run_directory"]
    trace = item["input_presentations"][0]
    recorded = json.loads(
        (Path(recovered["run_directory"]) / trace["file"]).read_text("utf8")
    )
    assert recorded["request"] == provider.requests[-1]
    assert recorded["input_presentation"]["original_request_sha256"] == digest(assembly)
    assert recorded["input_presentation"]["encoded_characters"] == length(
        provider.requests[-1]
    )
    assert recorded["input_presentation"]["codec"] == "compact-material/1"
    requests = deepcopy(provider.requests)
    resumed = engine.run_task(task, **kwargs)
    assert resumed["items"][0]["reused"] and resumed["calls"] == []
    assert provider.requests == requests


def test_lossless_encoding_still_respects_original_budget(papers, tmp_path):
    task, original = request_for(papers, tmp_path)
    task["budget"]["max_input_characters"] = length(inventory_request(original))

    def long_reading(request):
        response = inventory_for(request)
        response["items"][0]["observation"] *= 20
        return response

    provider = MockProvider(long_reading)
    run = engine.run_task(
        task,
        base_dir=tmp_path,
        output_dir=tmp_path / "out",
        allow_remote=True,
        provider=provider,
    )
    assert run["items"][0]["error"] == "input_budget_exceeded"
    assert len(run["calls"]) == 1 and len(provider.requests) == 1
    trace = run["items"][0]["input_presentations"][0]
    assert trace["encoded_characters"] > trace["max_input_characters"]
    assert trace["max_input_characters"] == task["budget"]["max_input_characters"]


def test_working_requests_and_explicit_compact_are_not_changed(papers, tmp_path):
    task, original = request_for(papers, tmp_path)
    assembly = assembly_request(original, inventory_for(inventory_request(original)))
    task["budget"]["max_input_characters"] = length(assembly)
    returned, trace = engine._fit_assembly_request(task, assembly)
    assert returned is assembly and trace is None
    task["budget"]["max_input_characters"] = 1
    for request in (original, inventory_request(original), compact_material(assembly)):
        before = deepcopy(request)
        returned, trace = engine._fit_assembly_request(task, request)
        assert returned is request and returned == before and trace is None
        with pytest.raises(ProcessingError, match="input_budget_exceeded"):
            engine._within_input_budget(task, returned)
