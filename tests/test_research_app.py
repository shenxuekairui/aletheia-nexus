"""Application permission and source-preserving workflow tests; no paid API."""

import json
import runpy
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.processing.contracts import TASK_SCHEMA
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import ResearchApplication, read_json

ROOT = Path(__file__).resolve().parents[1]
write_pdf = runpy.run_path(str(ROOT / "scripts/generate_v07_fixtures.py"))["_write_pdf"]


@pytest.fixture
def app(tmp_path):
    papers = tmp_path / "论文"
    papers.mkdir()
    pdf = papers / "方法.PDF"
    write_pdf(
        pdf,
        [
            [
                (50, 730, 15, "Self-authored method"),
                (50, 650, 12, "A sample was measured at 25 C for 2 h."),
            ]
        ],
        title="Self-authored method",
    )
    service = ResearchApplication([papers], tmp_path / "results", remote=True)
    yield service, pdf
    service.close()


def task_for(documents, *, mode="local"):
    return {
        "schema": TASK_SCHEMA,
        "id": "test",
        "type": "extract",
        "objective": "用中文整理方法",
        "documents": documents,
        "fields": [
            {
                "id": "method",
                "label": "方法",
                "type": "string",
                "description": "对象、方法与适用条件",
            }
        ],
        "mode": mode,
        "allow_remote": mode != "local",
        "model": {
            "name": "deepseek-flash",
            "input_cost_per_million": 2,
            "output_cost_per_million": 8,
        },
        "budget": {
            "max_calls": 1,
            "max_cost": 1,
            "max_output_tokens": 1000,
            "max_repair_rounds": 0,
            "max_supplement_rounds": 0,
        },
    }


def test_folder_prepare_reuse_and_local_execution(app, monkeypatch):
    service, pdf = app
    original = sha256_file(pdf)
    broken = pdf.parent / "损坏.pdf"
    broken.write_bytes(b"not a PDF")
    listed = service.list_documents(str(pdf.parent))
    assert len(listed["documents"]) == 2
    assert sum(d["status"] == "UNAVAILABLE" for d in listed["documents"]) == 1
    prepared = service.prepare_documents([str(pdf), str(broken)])
    assert len(prepared["documents"]) == len(prepared["failures"]) == 1
    first = prepared["documents"][0]
    assert Path(first["pdf"]).name == "paper.pdf"
    reused = service.prepare_documents([str(pdf)])["documents"][0]
    assert first == reused
    assert sha256_file(pdf) == original
    assert not pdf.with_suffix(".parsed.json").exists()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    job = service.execute_research_task(task_for([first]), background=False)
    assert job["status"] == "PREPARED"
    assert job["usage"]["http_attempts"] == 0
    status = service.get_run_status(job["job_id"])
    assert status["manifest"]["mode"] == "local"


def test_background_preparation_progress_partial_and_reuse(app, monkeypatch):
    import aletheia_nexus.research_app as module

    service, original = app
    other = original.parent / "第二篇.pdf"
    write_pdf(
        other,
        [[(50, 700, 12, "A different self-authored preparation method.")]],
        title="Second fixture",
    )
    broken = original.parent / "损坏.pdf"
    broken.write_bytes(b"not a PDF")
    selected = [str(original), str(other), str(broken)]
    hashes = {p: sha256_file(p) for p in (original, other, broken)}
    entered, release = Event(), Event()
    native_parse, calls = module.parse_document, []

    def observed_parse(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 2:
            entered.set()
            assert release.wait(5), "test did not release second parse"
        return native_parse(*args, **kwargs)

    monkeypatch.setattr(module, "parse_document", observed_parse)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    job = service.prepare_documents_job(selected)
    try:
        assert entered.wait(5), "background preparation did not reach second PDF"
        running = service.get_run_status(job["job_id"])
        assert running["kind"] == "preparation"
        assert running["status"] == "RUNNING"
        assert running["completed"] == 1 and running["total"] == 3
        assert running["latest_document"]["path"] == str(original.resolve())
        assert running["items"][0]["reused"] is False
    finally:
        release.set()
    service._jobs[job["job_id"]].result(timeout=10)
    completed = service.get_run_status(job["job_id"])
    assert completed["status"] == "PARTIAL"
    assert completed["completed"] == completed["total"] == 3
    assert len(completed["documents"]) == 2
    assert completed["failures"][0]["path"] == str(broken.resolve())
    assert completed["items"][-1]["status"] == "FAILED"
    assert completed["model_calls"] == 0 and not completed["network_access"]
    assert Path(completed["preparation_file"]).is_file()
    artifacts = {
        Path(d[k]): sha256_file(Path(d[k]))
        for d in completed["documents"]
        for k in ("pdf", "sidecar", "artifact")
    }
    before = read_json(Path(completed["directory"]) / "status.json")
    repeated = service.prepare_documents_job(selected, background=False)
    assert repeated["job_id"] != job["job_id"]
    assert repeated["status"] == "PARTIAL"
    assert repeated["documents"] == completed["documents"]
    assert all(
        row["reused"] for row in repeated["items"] if row["status"] == "PREPARED"
    )
    assert len(calls) == 2
    assert read_json(Path(completed["directory"]) / "status.json") == before
    assert {p: sha256_file(p) for p in artifacts} == artifacts
    assert {p: sha256_file(p) for p in hashes} == hashes


def test_background_preparation_scope_is_checked_before_job_files(app, tmp_path):
    service, original = app
    before = set(service.workspace.rglob("*"))
    with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
        service.prepare_documents_job([str(original), str(tmp_path / "outside.pdf")])
    with pytest.raises(ValueError, match="unique PDF"):
        service.prepare_documents_job([])
    with pytest.raises(ValueError, match="unique PDF"):
        service.prepare_documents_job(
            [str(original), str(original.parent) + "/./" + original.name]
        )
    assert set(service.workspace.rglob("*")) == before


def test_worker_finishing_between_status_read_and_owner_probe(app, monkeypatch):
    """A released lock may mean normal completion after the initial stale read."""
    import aletheia_nexus.research_app as module

    service, _ = app
    job_id = "1" * 32
    directory = service.workspace / "jobs" / job_id
    directory.mkdir(parents=True)
    status = directory / "status.json"
    (directory / ".owner").touch()
    running = {"job_id": job_id, "status": "RUNNING"}
    status.write_text(json.dumps(running), encoding="utf-8")
    original_probe = module._lock_job_owner
    final = {**running, "status": "PREPARED", "usage": {"http_attempts": 0}}

    def completed_before_probe(path, **kwargs):
        status.write_text(json.dumps(final), encoding="utf-8")
        return original_probe(path, **kwargs)

    monkeypatch.setattr(module, "_lock_job_owner", completed_before_probe)
    assert service.get_run_status(job_id) == final
    assert read_json(status) == final


def test_empty_and_path_boundaries(app, tmp_path):
    service, pdf = app
    empty = pdf.parent / "empty"
    empty.mkdir()
    assert service.list_documents(str(empty))["documents"] == []
    outside = tmp_path / "private.txt"
    outside.write_text("secret")
    for value in (
        outside,
        pdf.parent / ".." / "private.txt",
        service.private / "a.json",
    ):
        with pytest.raises(ProcessingError):
            service.path(value)
    with pytest.raises(ProcessingError):
        service.prepare_documents([str(outside)])
    with pytest.raises(ProcessingError):
        service.path(pdf.parent / "new.json", write=True)


def test_nested_locator_cannot_escape(app, tmp_path):
    service, pdf = app
    doc = service.prepare_documents([str(pdf)])["documents"][0]
    payload = read_json(Path(doc["artifact"]))
    payload["source"]["locators"]["pdf"] = str(tmp_path / "private.pdf")
    malicious = service.workspace / "evil.json"
    malicious.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProcessingError, match="path_outside"):
        service.validate_research_task(task_for([{**doc, "artifact": str(malicious)}]))


def test_implicit_sidecar_checked_before_loading(app, tmp_path, monkeypatch):
    service, pdf = app
    import aletheia_nexus.research_app as module

    outside = tmp_path / "outside.acquisition.json"
    monkeypatch.setattr(module, "acquisition_sidecar_path", lambda _: outside)
    calls = []
    monkeypatch.setattr(module, "load_source", lambda *args: calls.append(args))
    with pytest.raises(ProcessingError, match="path_outside"):
        service.check_document({"id": "test", "pdf": str(pdf)}, "direct")
    assert not calls


def test_symlink_boundary(app, tmp_path):
    service, pdf = app
    target = tmp_path / "outside"
    target.mkdir()
    link = pdf.parent / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not allow this account to create symlinks")
    with pytest.raises(ProcessingError):
        service.path(link / "paper.pdf")


def test_one_use_grant_binds_task_sources_budget_and_scope(app):
    service, pdf = app
    doc = service.prepare_documents([str(pdf)])["documents"][0]
    task = task_for([doc], mode="parsed")
    with pytest.raises(ProcessingError, match="local_authorization"):
        service.execute_research_task(
            task, authorization="confirmed=true", background=False
        )
    token = service.authorize("execute", task)
    changed = deepcopy(task)
    changed["budget"]["max_cost"] = 2
    with pytest.raises(ProcessingError, match="changed"):
        service.consume(token, "execute", changed)
    with pytest.raises(ProcessingError, match="changed"):
        service.consume(token, "plan", {"goal": "different"})
    service.consume(token, "execute", task)
    with pytest.raises(ProcessingError, match="missing_or_used"):
        service.consume(token, "execute", task)
    expired = service.authorize("execute", task, lifetime_seconds=-1)
    with pytest.raises(ProcessingError, match="expired"):
        service.consume(expired, "execute", task)
    token = service.authorize("execute", task)
    Path(doc["pdf"]).write_bytes(b"changed")
    with pytest.raises((ProcessingError, ValueError, RuntimeError)):
        service.consume(token, "execute", task)


def test_long_notes_have_bounded_preview_but_full_input_and_authorization(app):
    from aletheia_nexus.processing.engine import _request
    from aletheia_nexus.processing.materials import build_package

    service, pdf = app
    doc = service.prepare_documents([str(pdf)])["documents"][0]
    note = "温度25 µM；H₂O\n" * 4000 + "甲"
    doc["notes"] = ["仅处理所选文献。", note]
    task = task_for([doc], mode="parsed")
    before = deepcopy(task)
    checked = service.validate_research_task(task)
    assert len(checked["plan"]) < 2000
    assert "仅处理所选文献。" in checked["plan"]
    assert f"{len(note)}字符" in checked["plan"]
    assert "documents[0].notes" in checked["plan"]
    assert "全文将在确认后随所选文献发送给模型" in checked["plan"]
    assert note not in checked["plan"]
    sources = [
        service.check_document(d, "parsed") for d in checked["task"]["documents"]
    ]
    package, _ = build_package(checked["task"], sources)
    request = _request(checked["task"], package)
    assert request["material"]["documents"][0]["notes"] == doc["notes"]
    assert checked["task"]["documents"][0]["notes"] == doc["notes"]
    assert task == before
    challenge = service.authorization_request("execute", task)
    assert read_json(Path(challenge["authorization_request"]))["payload"] == task

    changed = deepcopy(task)
    changed["documents"][0]["notes"][1] = note[:-1] + "乙"
    other = service.validate_research_task(changed)
    assert other["plan"] == checked["plan"]
    assert other["task_fingerprint"] != checked["task_fingerprint"]
    assert service.binding("execute", changed) != service.binding("execute", task)
    token = service.authorize("execute", task)
    with pytest.raises(ProcessingError, match="changed"):
        service.consume(token, "execute", changed)
    service.consume(token, "execute", task)


def test_short_notes_remain_visible_in_local_plan(app):
    service, pdf = app
    doc = service.prepare_documents([str(pdf)])["documents"][0]
    doc["notes"] = ["保留原单位 µM，不换算。", "附件关系由用户确认。"]
    checked = service.validate_research_task(task_for([doc]))
    for note in doc["notes"]:
        assert "注意：" + note in checked["plan"]
    assert "计划不展开" not in checked["plan"]
    assert "本地模式不发送给远程模型" in checked["plan"]
    assert checked["task"]["documents"][0]["notes"] == doc["notes"]


def test_default_remote_disabled_and_challenge_is_not_consent(app):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = task_for(documents, mode="parsed")
    challenge = service.authorization_request("execute", task)
    assert Path(challenge["authorization_request"]).is_file()
    with pytest.raises(ProcessingError, match="authorization_required"):
        service.execute_research_task(task, background=False)
    disabled = ResearchApplication([pdf.parent], service.workspace)
    try:
        token = disabled.authorize("execute", task)
        with pytest.raises(ProcessingError, match="remote_disabled"):
            disabled.execute_research_task(task, authorization=token, background=False)
    finally:
        disabled.close()


def test_mock_remote_uses_native_engine_and_local_reexport(app):
    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = task_for(documents, mode="parsed")

    class Mock:
        identity = {"provider": "mock-test"}

        def generate(self, request, schema, images, budget, max_output_tokens):
            budget.reserve(0).update(status="completed", estimated_cost=0)
            document = request["material"]["documents"][0]
            block = next(b for b in document["blocks"] if "25 C" in b["text"])
            return {
                "records": [
                    {
                        "id": "r1",
                        "subject": "sample",
                        "stage": "measurement",
                        "fields": {
                            "method": {
                                "value": "25 C测量2h",
                                "raw_value": block["text"],
                                "unit": None,
                                "status": "reported",
                                "nature": "reported",
                                "context": "自编夹具",
                                "step_ids": [],
                                "citations": [
                                    {
                                        "source_id": document["id"],
                                        "page": block["page"],
                                        "block_id": block["id"],
                                        "quote": block["text"],
                                    }
                                ],
                            }
                        },
                        "steps": [],
                    }
                ],
                "claims": [],
                "issues": [],
                "requests": [],
            }

    token = service.authorize("execute", task)
    job = service.execute_research_task(
        task, authorization=token, background=False, provider=Mock()
    )
    assert job["status"] in {"COMPLETED", "PARTIAL"}
    run = Path(job["run_directory"])
    manifest = read_json(run / "manifest.json")
    assert len(manifest["calls"]) == 1
    results = [str(run / i["result"]) for i in manifest["items"] if i.get("result")]
    exported = service.export_research_results(results, "reuse")
    loaded = service.read_research_result(results[0])
    assert loaded["response"]["records"][0]["fields"]["method"]["value"] == "25 C测量2h"
    assert loaded["provider"]["provider"] == "mock-test"
    assert service.list_research_runs()["runs"][0]["job_id"] == job["job_id"]
    assert len(exported["outputs"]) == 3
    assert not exported["network_access"]
    assert "HUMAN_CONFIRMED" not in json.dumps(read_json(Path(results[0])))
    # A validly sealed result cannot smuggle an out-of-scope PDF into re-export.
    from aletheia_nexus.processing.contracts import digest

    malicious = read_json(Path(results[0]))
    malicious["package"]["documents"][0]["locators"]["pdf"] = str(
        pdf.parent.parent / "private.pdf"
    )
    malicious["artifact_id"] = "an:extraction:sha256:" + digest(
        {k: v for k, v in malicious.items() if k != "artifact_id"}
    )
    path = service.workspace / "malicious-result.json"
    path.write_text(json.dumps(malicious), encoding="utf-8")
    with pytest.raises(ProcessingError, match="path_outside"):
        service.export_research_results([str(path)], "blocked")
    # Reading the allowed historical JSON never dereferences that old PDF.
    history = service.read_research_result(str(path))
    assert history["response"] == malicious["response"]
    assert history["source_byte_verification"].startswith("historical")


def test_live_job_visible_from_another_application_and_crash_detected(app, monkeypatch):
    import subprocess
    import sys
    from threading import Event

    from aletheia_nexus import research_app as module
    from aletheia_nexus.processing.engine import write_json

    service, pdf = app
    documents = service.prepare_documents([str(pdf)])["documents"]
    started, release = Event(), Event()
    native = module.run_task

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return native(*args, **kwargs)

    monkeypatch.setattr(module, "run_task", delayed)
    observer = ResearchApplication([pdf.parent], service.workspace)
    try:
        job = service.execute_research_task(task_for(documents))
        assert started.wait(10)
        assert observer.get_run_status(job["job_id"])["status"] == "RUNNING"
        release.set()
        service._jobs[job["job_id"]].result(timeout=10)
        assert observer.get_run_status(job["job_id"])["status"] == "PREPARED"
        crashed = "c" * 32
        directory = service.workspace / "jobs" / crashed
        write_json(directory / "status.json", {"job_id": crashed, "status": "RUNNING"})
        helper = (
            "import os,sys; from pathlib import Path; "
            "from aletheia_nexus.research_app import _lock_job_owner; "
            "owner=_lock_job_owner(Path(sys.argv[1]),create=True); "
            "assert owner is not None; print('ready',flush=True); sys.stdin.read(1); os._exit(0)"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", helper, str(directory / ".owner")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            assert process.stdout.readline().strip() == b"ready"
            assert observer.get_run_status(crashed)["status"] == "RUNNING"
        finally:
            # EOF makes the actual Python child exit abruptly, including when a
            # Windows venv executable is a redirector rather than that child.
            process.stdin.close()
            process.wait(timeout=10)
        assert observer.get_run_status(crashed)["status"] == "INTERRUPTED"
    finally:
        release.set()
        observer.close()
