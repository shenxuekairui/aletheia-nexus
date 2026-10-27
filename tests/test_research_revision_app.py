"""Local result revisions keep source identity, history and assistant authority."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_research_app import task_for, write_pdf

from aletheia_nexus.processing.contracts import validate_task
from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing.materials import build_package
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import make_result, seal_result, verify_result
from aletheia_nexus.research_app import ResearchApplication, read_json


def save_fixture_result(service, pdf):
    documents = service.prepare_documents([str(pdf)])["documents"]
    task = validate_task(task_for(documents))
    package, _ = build_package(task, [service.check_document(documents[0], "parsed")])
    document = package["documents"][0]
    block = next(b for b in document["blocks"] if "25 C" in b["text"])
    citations = [
        {
            "source_id": document["id"],
            "page": block["page"],
            "block_id": block["id"],
            "quote": block["text"],
        }
    ]
    field = {
        "value": "25 C测量",
        "raw_value": block["text"],
        "unit": None,
        "status": "reported",
        "nature": "reported",
        "context": "自编夹具",
        "step_ids": [],
        "citations": citations,
    }
    response = {
        "records": [
            {
                "id": "r1",
                "subject": "sample",
                "stage": "measurement",
                "fields": {"method": field},
                "steps": [],
            }
        ],
        "claims": [{"text": "25 C测量", "nature": "reported", "citations": citations}],
        "issues": [
            {
                "kind": "material_insufficient",
                "detail": "仅提供一页夹具",
                "source_id": document["id"],
                "page": 1,
            }
        ],
        "requests": [],
    }
    result = make_result(task, package, {"provider": "local-test-fixture"}, response)
    path = service.workspace / "parent.result.json"
    write_json(path, result)
    return path, result


@pytest.fixture
def saved(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    pdf = papers / "source.pdf"
    write_pdf(
        pdf,
        [[(50, 650, 12, "A sample was measured at 25 C for 2 h.")]],
        title="Self-authored method",
    )
    service = ResearchApplication([papers], tmp_path / "workspace")
    path, result = save_fixture_result(service, pdf)
    yield service, pdf, path, result
    service.close()


def test_assistant_child_history_exports_and_source_immutability(saved):
    service, pdf, parent_path, parent = saved
    paths = [pdf, parent_path] + [
        Path(p) for p in parent["package"]["documents"][0]["locators"].values() if p
    ]
    before = {p: p.read_bytes() for p in paths}
    replacement = deepcopy(parent["response"]["records"][0])
    replacement["fields"]["method"]["context"] = "已核对夹具原文，仍待研究者确认"
    started = datetime.now(timezone.utc)
    report = service.revise_research_result(
        str(parent_path),
        {"record_id": "r1", "replacement": replacement, "reason": "补充适用范围"},
        client_identity="local-test-client",
    )
    child = read_json(Path(report["result"]))
    verify_result(child)
    assert report["network_access"] is False and report["confirmed"] is False
    assert child["artifact_id"] != parent["artifact_id"]
    assert child["response"]["records"][0] == replacement
    assert child["validation"]["record_states"]["r1"] == "review_required"
    history = child["history"][-1]
    assert history["authority"] == "assistant" and history["confirm"] is False
    assert history["author"] == "local-test-client"
    assert datetime.fromisoformat(history["at"]) >= started
    assert history["before"] == parent["response"]["records"][0]
    assert history["parent_result_id"] == parent["artifact_id"]
    assert service.read_research_result(report["result"])["history"] == child["history"]
    assert {Path(p).suffix for p in report["outputs"]} == {
        ".json",
        ".jsonl",
        ".csv",
        ".md",
    }
    assert all(Path(p).is_file() for p in report["outputs"])
    assert all(p.read_bytes() == content for p, content in before.items())
    # A second existing-target edit retains its immutable predecessor and history.
    first_bytes = Path(report["result"]).read_bytes()
    issue = deepcopy(child["response"]["issues"][0])
    issue["detail"] = "仍仅有这份自编材料"
    second = service.revise_research_result(
        report["result"],
        {"issue_index": 0, "replacement": issue, "reason": "明确材料范围"},
        client_identity="local-test-client",
    )
    updated = read_json(Path(second["result"]))
    assert second["history_length"] == 2
    assert updated["history"][:-1] == child["history"]
    assert updated["history"][-1]["parent_result_id"] == child["artifact_id"]
    assert Path(report["result"]).read_bytes() == first_bytes


def test_claim_revision_reuses_validation_and_remains_unconfirmed(saved):
    service, _, parent_path, parent = saved
    claim = deepcopy(parent["response"]["claims"][0])
    claim["text"] = "所供夹具报告在25 C测量"
    report = service.revise_research_result(
        str(parent_path),
        {"claim_index": 0, "replacement": claim, "reason": "明确来源范围"},
        client_identity="client",
    )
    child = read_json(Path(report["result"]))
    assert child["validation"]["claim_states"]["0"] == "review_required"
    assert child["response"]["records"] == parent["response"]["records"]
    claim["citations"][0]["page"] = 99
    with pytest.raises((ValueError, ProcessingError)):
        service.revise_research_result(
            str(parent_path),
            {"claim_index": 0, "replacement": claim, "reason": "invalid citation"},
            client_identity="client",
        )
    assert len(list((service.workspace / "revisions").iterdir())) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"authority": "human"},
        {"confirm": True},
        {"authority": "assistant", "confirm": False},
        {"author": "human"},
        {"at": "2000-01-01"},
        {"reason": " "},
        {"claim_index": 0},
        {"record_id": "new-record"},
    ],
)
def test_client_cannot_confirm_spoof_history_or_add_targets(saved, extra):
    service, _, path, parent = saved
    revision = {
        "record_id": "r1",
        "replacement": deepcopy(parent["response"]["records"][0]),
        "reason": "review",
        **extra,
    }
    with pytest.raises(ValueError):
        service.revise_research_result(str(path), revision, client_identity="client")
    assert not (service.workspace / "revisions").exists()


@pytest.mark.parametrize("location", ["task", "package", "canonical"])
def test_source_path_authorization_precedes_source_loading(
    saved, tmp_path, monkeypatch, location
):
    service, _, path, parent = saved
    outside = str(tmp_path / "outside.pdf")
    altered = deepcopy(parent)
    if location == "task":
        altered["task"]["documents"][0]["pdf"] = outside
    elif location == "package":
        altered["package"]["documents"][0]["locators"]["pdf"] = outside
    else:
        artifact_path = service.workspace / "malicious.parsed.json"
        old = read_json(
            Path(altered["package"]["documents"][0]["locators"]["artifact"])
        )
        old["source"]["locators"]["pdf"] = outside
        write_json(artifact_path, old)
        altered["package"]["documents"][0]["locators"]["artifact"] = str(artifact_path)
    malicious = service.workspace / "malicious.result.json"
    write_json(malicious, seal_result(altered))

    def forbidden(*args, **kwargs):
        pytest.fail("source loading happened before path authorization")

    monkeypatch.setattr("aletheia_nexus.research_app.load_source", forbidden)
    with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
        service.revise_research_result(
            str(malicious),
            {
                "record_id": "r1",
                "replacement": parent["response"]["records"][0],
                "reason": "review",
            },
            client_identity="client",
        )
    assert read_json(path) == parent
    assert not (service.workspace / "revisions").exists()


def test_current_source_or_canonical_mismatch_is_not_revised(saved):
    service, _, path, parent = saved
    altered = deepcopy(parent)
    altered["package"]["documents"][0]["parsed_artifact_id"] = "different-version"
    other = service.workspace / "different-version.result.json"
    write_json(
        other,
        make_result(
            altered["task"],
            altered["package"],
            altered["provider"],
            altered["response"],
        ),
    )
    revision = {
        "record_id": "r1",
        "replacement": parent["response"]["records"][0],
        "reason": "review",
    }
    with pytest.raises(ProcessingError, match="source_identity_mismatch"):
        service.revise_research_result(str(other), revision, client_identity="client")
    source_pdf = Path(parent["package"]["documents"][0]["locators"]["pdf"])
    source_pdf.write_bytes(source_pdf.read_bytes() + b"\nchanged")
    with pytest.raises(Exception, match="hash|HASH"):
        service.revise_research_result(str(path), revision, client_identity="client")
    assert read_json(path) == parent
    assert not (service.workspace / "revisions").exists()
