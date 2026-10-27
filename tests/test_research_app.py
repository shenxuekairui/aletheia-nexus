"""Application permission and source-preserving workflow tests; no paid API."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

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
    assert len(exported["outputs"]) == 3
    assert not exported["network_access"]
    assert "HUMAN_CONFIRMED" not in json.dumps(read_json(Path(results[0])))
    # A validly sealed result cannot smuggle an out-of-scope PDF into re-export.
    from aletheia_nexus.processing.contracts import digest
    malicious = read_json(Path(results[0]))
    malicious["package"]["documents"][0]["locators"]["pdf"] = str(pdf.parent.parent / "private.pdf")
    malicious["artifact_id"] = "an:extraction:sha256:" + digest(
        {k: v for k, v in malicious.items() if k != "artifact_id"})
    path = service.workspace / "malicious-result.json"
    path.write_text(json.dumps(malicious), encoding="utf-8")
    with pytest.raises(ProcessingError, match="path_outside"):
        service.export_research_results([str(path)], "blocked")
