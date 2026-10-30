"""Retry actual unsuccessful scope; retain old evidence and resume real mains."""

import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.paper_request import PaperRequest
from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.acquisition_recovery import (
    recovery_checkpoint,
    recovery_preview,
    recovery_requests,
)
from aletheia_nexus.workbench.library import LibraryService


def verified(service, request, width=200):
    """Deterministic PDF/source fixture, not a publisher identity acceptance."""
    path = (
        service.root / (request.folder or "") / (request.doi.rsplit("/", 1)[1] + ".pdf")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=200)
    writer.add_metadata({"/Title": request.title or request.doi})
    with path.open("wb") as handle:
        writer.write(handle)
    sidecar = acquisition_sidecar_path(path)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps(
            {
                "schema": "aletheia-nexus/acquisition-record/v1",
                "status": "VERIFIED",
                "target": {"doi": request.doi, "expected_title": request.title},
                "retrieval": {"sha256": sha256_file(path)},
                "pdf_validation": {"valid_pdf": True, "page_count": 1},
                "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
            }
        ),
        encoding="utf-8",
    )
    source = validate_parser_input(path)
    return path, {
        "doi": request.doi,
        "status": "VERIFIED",
        "verified_path": str(path),
        "sha256": source.pdf_sha256,
        "sidecar_sha256": source.sidecar_sha256,
    }


def original_job(service, requests, records, items=(), *, include_si=True):
    checkpoint = service.state_dir / "original.checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {"schema": "aletheia-nexus/access-batch-checkpoint/v1", "records": records}
        ),
        encoding="utf-8",
    )
    return {
        "id": "previous",
        "label": "原批次",
        "kind": "acquisition",
        "status": "PARTIAL",
        "parameters": {
            "library": str(service.root),
            "requests": [asdict(r) for r in requests],
            "options": {"include_si": include_si, "bulk_interval": 0},
            "postprocess": {"title_translation": {"enabled": True, "consent": True}},
        },
        "records": [],
        "result": {"checkpoint": str(checkpoint), "items": list(items)},
    }


@pytest.fixture
def service(tmp_path):
    library = LibraryService(
        tmp_path / "library", reference_roots=[tmp_path / "workspace"]
    )
    return AcquisitionService(library.root, tmp_path / "workspace", library=library)


def test_mixed_retry_scope_keeps_directory_tags_and_excludes_complete(service):
    done = PaperRequest(doi="10.1000/done", folder="已有分类", tags=("保留",))
    failed = PaperRequest(doi="10.1000/failed", folder="新分类", tags=())
    pending = PaperRequest(doi="10.1000/pending", folder=None, tags=("待读",))
    _, record = verified(service, done)
    job = original_job(
        service,
        [done, failed, pending],
        {done.batch_key: record},
        [
            {"request": asdict(done), "status": "VERIFIED"},
            {"request": asdict(failed), "status": "EXHAUSTED"},
        ],
        include_si=False,
    )
    original = deepcopy(job)
    preview = recovery_preview(job, service)
    assert [r["category"] for r in preview["rows"]] == [
        "COMPLETE",
        "MAIN_FAILED",
        "NOT_STARTED",
    ]
    assert [r["selected"] for r in preview["rows"]] == [False, True, True]
    chosen = recovery_requests(preview, [failed.batch_key, pending.batch_key])
    assert chosen == [asdict(failed), asdict(pending)]
    assert chosen[0]["tags"] == () and chosen[1]["folder"] is None
    assert job == original
    with pytest.raises(ValueError, match="完整完成"):
        recovery_requests(preview, [done.batch_key])


def test_si_retry_uses_actual_native_checkpoint_resume_without_main_fetch(
    service, monkeypatch
):
    from aletheia_nexus.acquire.access import batch
    from aletheia_nexus.workbench import supplements

    request = PaperRequest(doi="10.1000/si", folder="分类", tags=("保留",))
    pdf, record = verified(service, request)
    job = original_job(
        service,
        [request],
        {request.batch_key: record},
        [{"request": asdict(request), "status": "VERIFIED", "si_status": "PARTIAL"}],
    )
    checkpoint = Path(job["result"]["checkpoint"])
    before = (
        checkpoint.read_bytes(),
        pdf.read_bytes(),
        acquisition_sidecar_path(pdf).read_bytes(),
    )
    preview = recovery_preview(job, service)
    assert preview["rows"][0]["category"] == "SI_INCOMPLETE"
    assert preview["rows"][0]["main_verified"] is True
    copied = recovery_checkpoint(preview, service)
    monkeypatch.setattr(
        batch,
        "_acquire_item",
        lambda *a, **k: pytest.fail("Verified main must resume, not fetch"),
    )
    calls = []
    monkeypatch.setattr(
        supplements,
        "acquire_supplements",
        lambda source, *a, **k: (
            calls.append(source) or {"status": "COMPLETED", "items": []}
        ),
    )
    report = service.run(
        recovery_requests(preview, [request.batch_key]),
        preview["options"],
        checkpoint_path=copied,
    )
    assert report["status"] == "COMPLETED"
    assert report["items"][0]["resumed"] is True and report["items"][0]["attempts"] == 0
    assert calls == [pdf]
    assert (
        checkpoint.read_bytes(),
        pdf.read_bytes(),
        acquisition_sidecar_path(pdf).read_bytes(),
    ) == before


def test_failed_checkpoint_really_reenters_native_fetch_only_for_chosen_failure(
    service, monkeypatch
):
    from aletheia_nexus.acquire.access import batch

    failed = PaperRequest(doi="10.1000/failure", folder="分类", tags=("保留",))
    unselected = PaperRequest(doi="10.1000/not-chosen")
    job = original_job(
        service,
        [failed, unselected],
        {failed.batch_key: {"status": "EXHAUSTED", "doi": failed.doi, "attempts": 1}},
        [{"request": asdict(failed), "status": "EXHAUSTED"}],
        include_si=False,
    )
    checkpoint = Path(job["result"]["checkpoint"])
    before = checkpoint.read_bytes()
    preview = recovery_preview(job, service)
    copied = recovery_checkpoint(preview, service)
    entered = []

    def fetch(request, **kwargs):
        entered.append(request)
        raise RuntimeError("deterministic offline retry boundary")

    monkeypatch.setattr(batch, "_acquire_item", fetch)
    report = service.run(
        recovery_requests(preview, [failed.batch_key]),
        preview["options"],
        checkpoint_path=copied,
    )
    assert entered == [failed]
    assert len(report["items"]) == 1 and report["items"][0]["attempts"] == 1
    assert report["items"][0]["status"] == "RUNNER_ERROR"
    assert report["items"][0]["resumed"] is False
    assert checkpoint.read_bytes() == before


def test_moved_main_is_previewed_at_current_location_and_native_adapter_relocates(
    service, monkeypatch
):
    from aletheia_nexus.acquire.access import batch

    request = PaperRequest(doi="10.1000/moved", folder="原分类", tags=("保留",))
    _, record = verified(service, request)
    job = original_job(
        service,
        [request],
        {request.batch_key: record},
        [{"request": asdict(request), "status": "VERIFIED", "si_status": "NOT_FOUND"}],
    )
    row = service.library.scan()["items"][0]
    service.library.execute_rename(
        service.library.preview_rename([row["id"]], "新名称", folder="新分类")
    )
    preview = recovery_preview(job, service)
    assert preview["rows"][0]["folder"] == "新分类"
    assert preview["rows"][0]["main_verified"] is True
    # Keep the original request/keys; the established adapter performs relocation.
    assert recovery_requests(preview, [request.batch_key])[0]["folder"] == "原分类"
    copied = recovery_checkpoint(preview, service)
    monkeypatch.setattr(
        batch, "_acquire_item", lambda *a, **k: pytest.fail("Moved main must resume")
    )
    options = {**preview["options"], "include_si": False}
    report = service.run(
        recovery_requests(preview, [request.batch_key]), options, checkpoint_path=copied
    )
    assert report["items"][0]["resumed"] is True
    assert Path(report["items"][0]["pdf"]).parent.name == "新分类"


def test_missing_checkpoint_never_trusts_old_verified_status(service):
    request = PaperRequest(doi="10.1000/missing")
    pdf, record = verified(service, request)
    job = original_job(
        service,
        [request],
        {request.batch_key: record},
        [
            {
                "request": asdict(request),
                "status": "VERIFIED",
                "pdf": str(pdf),
                "si_status": "FAILED",
            }
        ],
    )
    Path(job["result"]["checkpoint"]).unlink()
    row = recovery_preview(job, service)["rows"][0]
    assert row["category"] == "NEEDS_REVIEW" and row["can_retry"] is False
    assert row["main_verified"] is False


def test_invalid_source_and_forged_hash_cannot_claim_resumable_main(service):
    request = PaperRequest(doi="10.1000/forged")
    pdf, record = verified(service, request)
    sidecar = acquisition_sidecar_path(pdf)
    source = json.loads(sidecar.read_text())
    source["status"] = "FAILED"
    sidecar.write_text(json.dumps(source))
    record["sidecar_sha256"] = sha256_file(sidecar)
    job = original_job(
        service,
        [request],
        {request.batch_key: record},
        [{"request": asdict(request), "status": "VERIFIED"}],
    )
    row = recovery_preview(job, service)["rows"][0]
    assert row["main_verified"] is False and row["category"] == "NEEDS_REVIEW"


def test_completed_si_receipt_is_not_enough_when_attachment_bytes_are_missing(service):
    request = PaperRequest(doi="10.1000/attachment")
    _, record = verified(service, request)
    item = {
        "request": asdict(request),
        "status": "VERIFIED",
        "si_status": "COMPLETED",
        "supplements": {
            "items": [
                {
                    "status": "SAVED",
                    "path": str(service.root / "SI" / "missing.pdf"),
                    "sha256": "0" * 64,
                }
            ]
        },
    }
    row = recovery_preview(
        original_job(service, [request], {request.batch_key: record}, [item]), service
    )["rows"][0]
    assert row["category"] == "SI_INCOMPLETE" and row["selected"] is True


def test_interrupted_task_without_result_uses_records_and_real_checkpoint(service):
    request = PaperRequest(doi="10.1000/interrupted")
    _, record = verified(service, request)
    job = original_job(service, [request], {request.batch_key: record})
    job["checkpoint"] = job.pop("result")["checkpoint"]
    job["status"] = "INTERRUPTED"
    row = recovery_preview(job, service)["rows"][0]
    assert row["category"] == "SI_INCOMPLETE" and row["main_verified"] is True


def test_wrong_library_active_job_and_changed_checkpoint_are_rejected(service):
    request = PaperRequest(doi="10.1000/control")
    job = original_job(service, [request], {})
    preview = recovery_preview(job, service)
    Path(preview["checkpoint"]).write_text("{}")
    with pytest.raises(ValueError, match="发生变化"):
        recovery_checkpoint(preview, service)
    job["parameters"]["library"] = str(service.root.parent / "other")
    with pytest.raises(ValueError, match="另一文库"):
        recovery_preview(job, service)
    job["status"] = "RUNNING"
    with pytest.raises(ValueError, match="尚未结束"):
        recovery_preview(job, service)


@pytest.mark.parametrize("payload", [[], None, {"schema": "other", "records": {}}])
def test_malformed_history_checkpoint_is_actionable_and_never_used(service, payload):
    request = PaperRequest(doi="10.1000/malformed")
    job = original_job(service, [request], {})
    Path(job["result"]["checkpoint"]).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="检查点格式无效"):
        recovery_preview(job, service)


def test_frontend_retry_submits_only_selected_scope_and_resets_translation_consent(
    service, monkeypatch
):
    pytest.importorskip("nicegui")
    from nicegui import run, ui

    from aletheia_nexus.workbench import defaults
    from aletheia_nexus.workbench import ui as ui_module
    from aletheia_nexus.workbench.ui import WorkbenchUI

    failed = PaperRequest(doi="10.1000/retry", tags=("原标签",))
    pending = PaperRequest(doi="10.1000/later", folder="分类")
    job = original_job(
        service,
        [failed, pending],
        {},
        [{"request": asdict(failed), "status": "EXHAUSTED"}],
    )
    page = WorkbenchUI.__new__(WorkbenchUI)
    saved = {}
    page.ctx = SimpleNamespace(
        acquisition=service,
        library=service.library,
        settings=SimpleNamespace(get=lambda *a: {}),
        jobs=SimpleNamespace(get=lambda key: deepcopy(job)),
    )
    page.title_translation_controls = lambda options=None: (
        lambda: {"enabled": False, "consent": False}
    )
    page.acquisition_worker = lambda *a, **k: (
        saved.update(worker=(a, k)) or (lambda _: {})
    )
    page.submit = lambda *a, **k: saved.update(submit=(a, k))

    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(run, "io_bound", immediate)
    monkeypatch.setattr(
        defaults,
        "browser_profile_choices",
        lambda _: {
            "options": ["default", "human-handoff"],
            "current": "default",
            "message": "复用已选择的会话，不保证机构权限",
            "warnings": [],
        },
    )
    original_guard = ui_module.guard

    def capture_action(callback):
        if callback.__name__ == "start":
            saved["start_action"] = callback
        return original_guard(callback)

    monkeypatch.setattr(ui_module, "guard", capture_action)
    prior = set(ui.context.client.elements)
    container = ui.column()

    async def exercise():
        with container:
            await page.recover_acquisition_dialog(job)
        elements = [v for k, v in container.client.elements.items() if k not in prior]
        table = next(e for e in elements if isinstance(e, ui.table))
        table.selected = [r for r in table.rows if r["id"] == failed.batch_key]
        strategy = next(
            e
            for e in elements
            if isinstance(e, ui.select) and "重试获取策略" in e.label
        )
        strategy.set_value("institution")
        profile = next(
            e
            for e in elements
            if isinstance(e, ui.select) and e.label == "本次机构浏览器会话"
        )
        profile.set_value("human-handoff")
        with container:
            await saved["start_action"]()
            await saved["start_action"]()  # A second click must not submit twice.

    asyncio.run(exercise())
    args, kwargs = saved["submit"]
    assert args[3] is not None and args[4]["requests"] == [asdict(failed)]
    assert (
        args[4]["options"]["public_only"] is False
        and args[4]["options"]["browser_enabled"] is True
    )
    assert args[4]["options"]["browser"]["profile_name"] == "human-handoff"
    assert args[4]["postprocess"]["title_translation"] == {
        "enabled": False,
        "consent": False,
    }
    assert kwargs["resume_of"] == job["id"] and args[4]["library"] == str(service.root)
    assert saved["worker"][0][0] == [asdict(failed)]
    assert len(list(service.state_dir.glob("*.retry.checkpoint.json"))) == 1


@pytest.mark.parametrize(
    "panel_root,deleted,tracks",
    [("same", False, True), ("other", False, False), ("same", True, False)],
)
def test_new_retry_task_is_persisted_and_only_tracks_current_live_panel(
    service, monkeypatch, panel_root, deleted, tracks
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench.settings import SettingsStore
    from aletheia_nexus.workbench.ui import WorkbenchUI

    monkeypatch.setattr(ui, "notify", lambda *a, **k: None)
    page = WorkbenchUI.__new__(WorkbenchUI)
    receipt = {"id": "new-retry", "kind": "acquisition", "status": "QUEUED"}
    settings = SettingsStore(service.state_dir)
    page.ctx = SimpleNamespace(
        library=service.library,
        settings=settings,
        jobs=SimpleNamespace(submit=lambda *a, **k: receipt),
    )
    tracked = []
    page.acquisition_progress_panel = SimpleNamespace(
        root=str(service.root)
        if panel_root == "same"
        else str(service.root.parent / "other"),
        body=SimpleNamespace(is_deleted=deleted),
        track=tracked.append,
    )
    assert (
        page.submit(
            "acquisition",
            "重试1篇",
            ["10.1000/retry"],
            lambda _: {},
            {},
            resume_of="old",
        )
        == receipt
    )
    assert tracked == ([receipt] if tracks else [])
    assert settings.get("acquisition_live_task") == {
        "id": receipt["id"],
        "library": str(service.root),
    }
