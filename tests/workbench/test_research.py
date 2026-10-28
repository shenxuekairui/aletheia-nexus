"""Deterministic workbench flows: immutable inputs, scoped search and consent."""

import runpy
from pathlib import Path

import pytest

from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.workbench.research import WorkbenchResearch


class Library:
    def __init__(self, root, rows):
        self.root, self.rows = root, rows

    def get(self, key):
        return next(r for r in self.rows if r["id"] == key)

    def scan(self):
        return {"items": self.rows}

    def update_metadata(self, key, **fields):
        self.get(key).setdefault("metadata", {}).update(fields)


@pytest.fixture
def research(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    write_pdf = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    rows = []
    for key, title in (("p1", "Alpha catalysis"), ("p2", "Beta measurement")):
        incoming = tmp_path / (key + ".pdf")
        write_pdf(
            incoming,
            [
                [
                    (50, 730, 15, title),
                    (50, 650, 12, "A sample was measured at 25 C for 2 h."),
                ]
            ],
            title=title,
        )
        pdf = register_local_pdf(incoming, output_dir=root, title=title)
        rows.append(
            {
                "id": key,
                "pdf_path": str(pdf),
                "sidecar_path": str(acquisition_sidecar_path(pdf)),
                "attachments": [],
            }
        )
    service = WorkbenchResearch(Library(root, rows), tmp_path / "workspace")
    yield service
    service.close()


def test_parse_search_paginate_and_snapshot(research):
    assert research.search("sample")["coverage"]["searched_documents"] == 0
    parsed = research.parse(["p1", "p2"])
    assert len(parsed["items"]) == 2
    assert all(row["status"] == "PARSED" for row in parsed["items"])
    first_artifact = parsed["items"][0]["document"]["artifact"]
    unchanged = Path(first_artifact).read_bytes()
    assert research.parse(["p1"])["items"][0]["reused"]
    assert (
        research.parse(["p1"], {"new_version": True})["items"][0]["document"][
            "artifact"
        ]
        != first_artifact
    )
    assert Path(first_artifact).read_bytes() == unchanged
    report = research.search("sample", ["p1"], limit=1)
    assert report["total_hits"] >= 1
    assert report["hits"][0]["paper_id"] == "p1"
    assert research.search("sample", ["p1"], offset=report["total_hits"])["hits"] == []
    exported = research.export_evidence(report["hits"])
    assert all(Path(p).is_file() for p in exported["outputs"])
    task = research.local_plan("整理测量条件", ["p1"])
    original_pdf = research.library.get("p1")["pdf_path"]
    Path(original_pdf).rename(Path(original_pdf).with_name("改名.pdf"))
    result = research.execute(task)
    assert result["status"] == "PREPARED"
    assert result["usage"]["http_attempts"] == 0


def test_no_implicit_remote_request(research, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ProcessingError, match="explicit_planning_consent"):
        research.plan("整理测量条件", ["p1"])
    task = research.local_plan("整理测量条件", ["p1"], mode="parsed")
    with pytest.raises(ProcessingError, match="explicit_research_consent"):
        research.execute(task)
    with pytest.raises(ProcessingError, match="explicit_human_revision"):
        research.revise("unused", {}, {}, reason="test", author="test")


def test_parse_unknown_option_rejected(research):
    with pytest.raises(ValueError, match="Unsupported"):
        research.parse(["p1"], {"renderer_command": "unsafe"})
    with pytest.raises(ValueError, match="language"):
        research.parse(["p1"], {"ocr_languages": "eng; command"})


def test_legacy_parsed_artifact_discovered_without_reparse(research, monkeypatch):
    from aletheia_nexus.content.service import parse_document

    original = research.library.get("p1")
    artifact = Path(original["pdf_path"]).with_suffix(".parsed.json")
    parse_document(
        original["pdf_path"],
        sidecar_path=original["sidecar_path"],
        output_path=artifact,
    )
    before = artifact.read_bytes()
    monkeypatch.setattr(
        research.app,
        "prepare_documents",
        lambda *_: pytest.fail("Search must not reparse an existing library"),
    )
    report = research.search("sample", ["p1"])
    assert report["hits"] and report["coverage"]["searched_documents"] == 1
    assert artifact.read_bytes() == before


def test_selecting_old_version_changes_future_plans_only(research):
    first = research.parse(["p1"])["items"][0]["document"]
    old_task = research.local_plan("整理测量条件", ["p1"])
    second = research.parse(["p1"], {"new_version": True})["items"][0]["document"]
    assert (
        research.local_plan("整理测量条件", ["p1"])["documents"][0]["artifact"]
        == second["artifact"]
    )
    research.select_version("p1", first["artifact"])
    assert (
        research.local_plan("整理测量条件", ["p1"])["documents"][0]["artifact"]
        == first["artifact"]
    )
    assert old_task["documents"][0]["artifact"] == first["artifact"]
    assert Path(first["artifact"]).is_file() and Path(second["artifact"]).is_file()
    with pytest.raises(ValueError, match="Unknown"):
        research.select_version("p1", "arbitrary-path.parsed.json")


def test_same_pdf_bytes_with_distinct_source_declarations_keep_distinct_ids(research):
    first = research.library.get("p1")
    other = register_local_pdf(
        first["pdf_path"],
        output_dir=research.library.root / "other",
        title="Independent local title declaration",
    )
    research.library.rows.append(
        {
            "id": "p3",
            "pdf_path": str(other),
            "sidecar_path": str(acquisition_sidecar_path(other)),
            "attachments": [],
        }
    )
    task = research.local_plan("比较来源声明", ["p1", "p3"])
    assert [d["id"] for d in task["documents"]] == ["p1", "p3"]
    assert task["documents"][0]["pdf"] == task["documents"][1]["pdf"]
    assert task["documents"][0]["sidecar"] != task["documents"][1]["sidecar"]
    assert research.execute(task)["status"] == "PREPARED"


def test_human_revision_and_unicode_export_name(research):
    import hashlib
    import json
    import zipfile

    from aletheia_nexus.processing.engine import write_json
    from aletheia_nexus.processing.materials import build_package
    from aletheia_nexus.processing.results import make_result

    task = research.local_plan("整理测量条件", ["p1"])
    package, _ = build_package(
        task, [research.app.check_document(task["documents"][0], "parsed")]
    )
    source = package["documents"][0]
    block = next(b for b in source["blocks"] if "sample" in b["text"])
    field = {
        "value": "25 C",
        "raw_value": "25 C",
        "unit": None,
        "status": "reported",
        "nature": "reported",
        "context": "measurement",
        "step_ids": [],
        "citations": [
            {
                "source_id": source["id"],
                "page": block["page"],
                "block_id": block["id"],
                "quote": block["text"],
            }
        ],
    }
    record = {
        "id": "r1",
        "subject": "sample",
        "stage": "measurement",
        "fields": {"finding": field},
        "steps": [],
    }
    response = {"records": [record], "claims": [], "issues": [], "requests": []}
    result = make_result(task, package, {"provider": "deterministic-test"}, response)
    path = research.workspace / "research" / "runs" / "fixture" / "p1.result.json"
    write_json(path, result)
    parent_bytes = path.read_bytes()
    citation = research.citation_document(str(path), source["id"])
    assert Path(citation["pdf"]).is_file()
    revised = research.revise(
        str(path),
        {"record_id": "r1"},
        record,
        reason="已核对合成夹具原文",
        author="研究者",
        confirm=True,
        human=True,
    )
    assert (
        research.read_result(revised["result"])["validation"]["record_states"]["r1"]
        == "human_confirmed"
    )
    exported = research.export([revised["result"]], name="验收结果")
    assert exported["display_name"] == "验收结果"
    assert all(Path(p).is_file() for p in exported["outputs"])
    native = json.loads(Path(exported["native_manifest"]).read_text(encoding="utf-8"))
    assert native["status"] == "COMPLETED"
    copied_result = Path(exported["directory"]) / native["results"][0]["result_file"]
    assert copied_result.read_bytes() == Path(revised["result"]).read_bytes()
    with zipfile.ZipFile(exported["native_bundle"]) as archive:
        for entry in native["files"]:
            assert (
                hashlib.sha256(archive.read(entry["path"])).hexdigest()
                == entry["sha256"]
            )
        assert any(name.endswith("package.json") for name in archive.namelist())
        assert any(name.endswith("history.json") for name in archive.namelist())
        assert any(name.endswith("task.json") for name in archive.namelist())
    assert path.read_bytes() == parent_bytes


def test_extra_pages_require_fresh_execution_consent(research, monkeypatch):
    task = research.local_plan("整理测量条件", ["p1"], mode="parsed")
    assert task["budget"]["max_supplement_rounds"] == 0
    task["budget"]["max_supplement_rounds"] = 1
    calls = []
    monkeypatch.setattr(
        research.app,
        "execute_research_task",
        lambda *args, **kwargs: calls.append(True) or {"status": "COMPLETED"},
    )
    with pytest.raises(ProcessingError, match="supplement_page_consent"):
        research.execute(task, consent=True)
    assert not calls
    assert (
        research.execute(task, consent=True, allow_extra_pages=True)["status"]
        == "COMPLETED"
    )
    assert calls == [True]


def test_material_request_adds_explicit_si_to_new_unapproved_plan(research):
    from copy import deepcopy

    from aletheia_nexus.processing.engine import write_json
    from aletheia_nexus.processing.materials import build_package
    from aletheia_nexus.processing.results import make_result

    task = research.local_plan("核对补充材料", ["p1"], mode="parsed")
    package, _ = build_package(
        task, [research.app.check_document(task["documents"][0], "parsed")]
    )
    sid = package["documents"][0]["id"]
    response = {
        "records": [],
        "claims": [],
        "issues": [
            {
                "kind": "material_insufficient",
                "detail": "需要补充信息",
                "source_id": sid,
                "page": 1,
            }
        ],
        "requests": [{"source_id": sid, "pages": [1], "reason": "核对原页与新增SI"}],
    }
    value = make_result(task, package, {"provider": "deterministic-test"}, response)
    path = research.workspace / "request.result.json"
    write_json(path, value)
    unchanged = path.read_bytes()
    no_page = deepcopy(response)
    no_page["requests"][0]["pages"] = []
    blocked = research.workspace / "missing-si.result.json"
    write_json(
        blocked, make_result(task, package, {"provider": "deterministic-test"}, no_page)
    )
    with pytest.raises(ValueError, match="尚无新增"):
        research.supplement_task(str(blocked), 0)
    original = research.library.get("p1")
    source = research.library.root / "incoming-si.pdf"
    writer = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    writer(
        source,
        [[(50, 700, 12, "Supplementary information for the authored fixture")]],
        title="SI",
    )
    si = register_local_pdf(
        source,
        output_dir=research.library.root / "SI",
        title="Explicit SI",
        role="SUPPLEMENT",
        parent_pdf=original["pdf_path"],
        parent_sidecar=original["sidecar_path"],
    )
    original["attachments"].append(
        {
            "id": "si_fixture",
            "path": str(si),
            "role": "SUPPLEMENT",
            "sidecar_path": str(acquisition_sidecar_path(si)),
        }
    )
    prepared = research.supplement_task(str(path), 0)
    assert (
        prepared["network_access"] is False
        and prepared["authorization_required"] is True
    )
    assert prepared["task"]["id"] != task["id"]
    assert len(prepared["task"]["documents"]) == 2
    assert prepared["task"]["documents"][0]["image_pages"] == [1]
    assert prepared["task"]["budget"]["max_supplement_rounds"] == 0
    with pytest.raises(ProcessingError, match="research_consent"):
        research.execute(prepared["task"])
    assert path.read_bytes() == unchanged


def test_planning_preserves_user_limits_and_defaults_adaptive_pages_off(
    research, monkeypatch
):
    monkeypatch.setattr(
        "aletheia_nexus.workbench.research.draft_task",
        lambda app, request, **kwargs: request,
    )
    request = research.plan(
        "核对材料",
        ["p1"],
        consent=True,
        budget={
            "max_input_characters": 500,
            "max_images": 1,
            "max_output_tokens": 1024,
            "max_supplement_rounds": 2,
            "max_review_rounds": 1,
        },
    )
    assert request["research_budget"]["max_input_characters"] == 500
    assert request["research_budget"]["max_images"] == 1
    assert request["research_budget"]["max_output_tokens"] == 1024
    assert request["research_budget"]["max_review_rounds"] == 1
    assert request["research_budget"]["max_supplement_rounds"] == 0


def test_parse_source_failure_isolated_and_real_metadata_recorded(research):
    Path(research.library.get("p2")["pdf_path"]).write_bytes(b"changed, invalid PDF")
    receipt = research.parse(["p1", "p2"])
    assert receipt["status"] == "PARTIAL"
    assert {r["id"]: r["status"] for r in receipt["items"]} == {
        "p1": "PARSED",
        "p2": "FAILED",
    }
    metadata = research.library.get("p1")["metadata"]
    assert metadata["ocr_status"] == "NOT_REQUESTED"
    assert metadata["ocr_diagnostics"]["ocr_text_blocks"] == 0
    task = research.local_plan("本地任务关联", ["p1"])
    run = research.execute(task)
    history = research.library.get("p1")["metadata"]["research_tasks"]
    assert history[-1]["job_id"] == run["job_id"]
    assert history[-1]["status"] == "PREPARED"
    assert (
        research.ocr_summary({"quality": {"ocr_supplemented_blocks": 4}}, {})[0]
        == "USED"
    )


def test_cancel_after_completed_paper_retains_native_diagnostics(research):
    from aletheia_nexus.workbench.jobs import TaskCancelled

    class BoundaryCancel:
        cancelled = False
        completed = False

        def checkpoint(self):
            if self.completed:
                self.cancelled = True
                raise TaskCancelled()

        def progress(self, *args, **kwargs):
            pass

        def record(self, *args, **kwargs):
            self.completed = True

    class MockProvider:
        identity = {"provider": "deterministic-test"}

        def generate(self, request, schema, images, budget, max_output_tokens):
            row = budget.reserve(0.01)
            row.update(
                status="completed", usage={"input_tokens": 1, "output_tokens": 1}
            )
            source = request["material"]["documents"][0]
            block = next(b for b in source["blocks"] if "sample" in b["text"])
            citation = {
                "source_id": source["id"],
                "page": block["page"],
                "block_id": block["id"],
                "quote": block["text"],
            }
            field = {
                "value": block["text"],
                "raw_value": block["text"],
                "unit": None,
                "status": "reported",
                "nature": "reported",
                "context": "measurement",
                "step_ids": [],
                "citations": [citation],
            }
            return {
                "records": [
                    {
                        "id": "r1",
                        "subject": "sample",
                        "stage": "measurement",
                        "fields": {"finding": field},
                        "steps": [],
                    }
                ],
                "claims": [],
                "issues": [],
                "requests": [],
            }

    task = research.local_plan("整理测量条件", ["p1", "p2"], mode="parsed")
    receipt = research.execute(
        task, context=BoundaryCancel(), consent=True, provider=MockProvider()
    )
    assert receipt["status"] == "CANCELLED"
    assert receipt["native_receipt"]["status"] == "FAILED"
    assert receipt["interruption_point"] == "completed_paper_boundary"
    assert len(receipt["native_runs"]) == 1
    rows = receipt["native_runs"][0]["items"]
    assert rows[0]["status"] == "COMPLETED", rows[0].get("error")
    assert rows[1]["status"] == "PENDING"
    assert receipt["native_runs"][0]["usage"]["http_attempts"] == 1
