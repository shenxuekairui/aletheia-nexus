"""Each verified fixture is organized before the next acquisition starts.

Source declarations and HTTP responses below are synthetic engineering fixtures;
they are not live publisher verification or scientific extraction evidence.
"""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.workbench import acquisition, supplements
from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.research import WorkbenchResearch
from aletheia_nexus.workbench.translation import TranslationService
from aletheia_nexus.workbench.ui_acquisition import AcquisitionPage


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-incremental-key")
    workspace = tmp_path / "workspace"
    library = LibraryService(tmp_path / "library", reference_roots=[workspace])
    inputs, initial, attachments = [], {}, {}
    for number in range(2):
        pdf = library.root / f"paper-{number}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100 + number, height=200)
        writer.write(pdf)
        doi = f"10.1000/incremental-{number}"
        source = acquisition_sidecar_path(pdf)
        source.parent.mkdir(exist_ok=True)
        source.write_text(
            json.dumps(
                {
                    "schema": "aletheia-nexus/acquisition-record/v1",
                    "status": "VERIFIED",
                    "target": {
                        "doi": doi,
                        "expected_title": f"Engineering title {number}",
                    },
                    "retrieval": {"sha256": sha256_file(pdf)},
                    "pdf_validation": {"valid_pdf": True, "page_count": 1},
                    "identity_validation": {
                        "status": "MATCH",
                        "document_role": "ARTICLE",
                    },
                }
            ),
            encoding="utf-8",
        )
        row = next(p for p in library.scan()["items"] if p["doi"] == doi)
        library.update_metadata(row["id"], year=2026, journal="Fixture journal")
        csv = tmp_path / f"attachment-{number}.csv"
        csv.write_text(f"fixture,value\n{number},1\n", encoding="utf-8")
        attached = library.import_attachment(row["id"], csv)
        initial[row["id"]] = {
            "pdf": pdf.read_bytes(),
            "sidecar": source.read_bytes(),
            "si": csv.read_bytes(),
        }
        inputs.append({"doi": doi})
        attachments[str(pdf)] = attached

    ids = [
        next(p["id"] for p in library.scan()["items"] if p["doi"] == r["doi"])
        for r in inputs
    ]
    state = SimpleNamespace(
        library=library,
        inputs=inputs,
        ids=ids,
        http=[],
        native=[],
        parsed=[],
        before_next=[],
        mode="success",
    )
    research = WorkbenchResearch(library, workspace)
    native_parse = research.parse

    def parse(ids, **kwargs):
        for paper_id in ids:
            state.parsed.append(
                (
                    paper_id,
                    library.get(paper_id)["pdf_path"],
                    deepcopy(kwargs.get("options")),
                )
            )
        return native_parse(ids, **kwargs)

    research.parse = parse

    def http(request):
        payload = json.loads(
            json.loads(request.content)["input"][0]["content"][0]["text"]
        )
        state.http.append(payload)
        ledger = list((workspace / "translations").glob("budget-*.json"))
        assert len(ledger) == 1
        assert json.loads(ledger[0].read_text())["calls"][-1]["status"] == "started"
        if state.mode == "unknown":
            raise httpx.ReadTimeout("fixture uncertain billing")
        translations = [
            {"id": p["id"], "title": "催化测试" + str(ids.index(p["id"]))}
            for p in payload["titles"]
        ]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 60},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"translations": translations}),
                            }
                        ],
                    }
                ],
            },
        )

    def batch(requests, **kwargs):
        number = len(state.native)
        if number:
            first = library.get(ids[0])
            state.before_next.append(deepcopy(first))
        state.native.append(requests[0].doi)
        if state.mode == "skip_next" and number == 0:
            state.manager.control(state.manager.list()[0]["id"], "skip")
        pdf = library.root / f"paper-{number}.pdf"
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    requests[0],
                    requests[0].doi,
                    BatchItemStatus.VERIFIED,
                    verified_path=pdf,
                    attempts=1,
                )
            ]
        )

    def si(main, **kwargs):
        attached = attachments[str(main)]
        return {
            "status": "COMPLETED",
            "items": [
                {
                    "status": "REUSED",
                    "path": attached["path"],
                    "sha256": attached["sha256"],
                    "role": attached["role"],
                }
            ],
        }

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    monkeypatch.setattr(supplements, "acquire_supplements", si)
    monkeypatch.setattr(
        acquisition.BrowserSession,
        "_ensure_started",
        lambda *_: pytest.fail("No browser may start"),
    )
    page = AcquisitionPage()
    page.ctx = SimpleNamespace(
        library=library,
        research=research,
        acquisition=acquisition.AcquisitionService(library.root, library=library),
        translation=TranslationService(
            library, workspace, transport=httpx.MockTransport(http)
        ),
    )
    manager = TaskManager(workspace)
    state.page, state.manager, state.initial = page, manager, initial
    try:
        yield state
    finally:
        manager.close(wait=True)
        research.close()


def run(state, *, max_calls=20, consent=True):
    worker = state.page.acquisition_worker(
        state.inputs,
        {"include_si": True},
        {
            "template": "{year}-{journal}-{title_zh}",
            "collection": "逐篇集合",
            "auto_parse": True,
            "parse_options": {"ocr": False, "max_pages": 1},
            "title_translation": {
                "enabled": True,
                "consent": consent,
                "options": {
                    "max_calls": max_calls,
                    "model": {"min_interval_seconds": 0},
                },
            },
        },
    )
    job = state.manager.submit(
        "acquisition", "synthetic incremental pipeline", state.inputs, worker
    )
    state.manager._futures[job["id"]].result(timeout=20)
    receipt = state.manager.get(job["id"])
    assert receipt["status"] in {"COMPLETED", "PARTIAL"}, receipt
    return receipt


def assert_sources_unchanged(state):
    for paper_id, before in state.initial.items():
        current = state.library.get(paper_id)
        assert Path(current["pdf_path"]).read_bytes() == before["pdf"]
        assert Path(current["sidecar_path"]).read_bytes() == before["sidecar"]
        assert Path(current["attachments"][0]["path"]).read_bytes() == before["si"]


def test_first_translation_naming_and_parsing_finish_before_second_paper(workflow):
    receipt = run(workflow)
    first = workflow.before_next[0]
    assert first["title_zh"] == "催化测试0"
    assert Path(first["pdf_path"]).name == "2026-Fixture journal-催化测试0.pdf"
    assert first["parse_status"] == "PARTIAL"  # Blank synthetic pages remain partial.
    assert Path(first["metadata"]["artifact"]).is_file()
    assert workflow.parsed[0][0] == workflow.ids[0]
    assert workflow.parsed[0][2] == {"ocr": False, "max_pages": 1}
    assert all(row["status"] == "VERIFIED" for row in receipt["result"]["items"])
    assert len(workflow.http) == 2
    assert len(receipt["result"]["translation"]["calls"]) == 2
    assert receipt["result"]["translation"]["accounted_cost"] == pytest.approx(0.00136)
    assert [
        len(row["postprocess"]["translation"]["calls"])
        for row in receipt["result"]["items"]
    ] == [1, 1]
    assert set(workflow.library.collections()["逐篇集合"]) == set(workflow.ids)
    for paper_id in workflow.ids:
        paper = workflow.library.get(paper_id)
        assert (
            Path(paper["attachments"][0]["path"]).parent
            == Path(paper["pdf_path"]).parent / "SI"
        )
        assert Path(paper["attachments"][0]["path"]).stem.startswith(
            Path(paper["pdf_path"]).stem + "__SI-"
        )
    assert_sources_unchanged(workflow)


@pytest.mark.parametrize("mode", ["call_limit", "unknown"])
def test_shared_failure_keeps_downloading_without_extra_charged_requests(
    workflow, mode
):
    workflow.mode = mode
    receipt = run(workflow, max_calls=1 if mode == "call_limit" else 20)
    report = receipt["result"]
    assert len(workflow.native) == 2 and len(workflow.http) == 1
    assert report["success"] == 2
    assert all(row["status"] == "VERIFIED" for row in report["items"])
    assert len(report["translation"]["calls"]) == 1
    assert report["translation"]["billing_uncertain"] is (mode == "unknown")
    assert len(workflow.parsed) == 2
    assert_sources_unchanged(workflow)


@pytest.mark.parametrize("stage", ["rename", "parse"])
def test_local_postprocess_failure_does_not_downgrade_verified_main(
    workflow, monkeypatch, stage
):
    def fail(*_args, **_kwargs):
        raise OSError("synthetic local processing failure")

    if stage == "rename":
        monkeypatch.setattr(workflow.library, "preview_rename", fail)
    else:
        monkeypatch.setattr(workflow.page.ctx.research, "parse", fail)
    report = run(workflow)["result"]
    assert report["status"] == "PARTIAL" and report["success"] == 2
    assert all(
        row["status"] == "VERIFIED" and row["postprocess"]["status"] == "PARTIAL"
        for row in report["items"]
    )
    assert_sources_unchanged(workflow)


def test_no_title_consent_sends_nothing_and_preserves_both_verified_mains(workflow):
    report = run(workflow, consent=False)["result"]
    assert report["status"] == "PARTIAL" and report["success"] == 2
    assert workflow.http == []
    assert report["translation"]["calls"] == []
    assert report["translation"]["accounted_cost"] == 0
    assert all(row["status"] == "VERIFIED" for row in report["items"])
    assert_sources_unchanged(workflow)


def test_skip_queued_while_downloading_applies_to_next_paper_not_postprocessing(
    workflow,
):
    workflow.mode = "skip_next"
    report = run(workflow)["result"]
    assert len(workflow.native) == len(workflow.http) == len(workflow.parsed) == 1
    assert [row["status"] for row in report["items"]] == ["VERIFIED", "SKIPPED"]
    first = workflow.library.get(workflow.ids[0])
    assert first["title_zh"] == "催化测试0" and first["parse_status"] == "PARTIAL"
    assert_sources_unchanged(workflow)
