import hashlib
import json

import pytest

import aletheia_nexus.acquire.access.batch as batch_module
from aletheia_nexus.acquire.access import PaperRequest
from aletheia_nexus.acquire.access.batch import (
    BatchItemStatus,
    acquire_full_text_batch_maximized,
)
from aletheia_nexus.acquire.access.browser import BrowserSession
from aletheia_nexus.acquire.access.cnki_provider import _source_candidate
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAttemptStatus,
    MaximizedAcquisitionStatus,
)


class _Result:
    def __init__(self, doi, status, verified_path=None):
        self.doi = doi
        self.status = status
        self.verified_path = verified_path
        self.verified_result = None
        self.browser_attempts = ()
        if verified_path is not None and verified_path.is_file():
            sidecar = verified_path.with_suffix(".acquisition.json")
            if not sidecar.exists():
                sidecar.write_text(
                    json.dumps({"fixture": "verified"}), encoding="utf-8"
                )


def test_structured_batches_separate_same_title_authors_and_resume_by_request(
    monkeypatch, tmp_path
):
    from dataclasses import replace

    request = PaperRequest(
        title="相同题名但不是相同论文", authors=("张三",), journal="测试学报", year=2024
    )
    other = replace(request, authors=("李四",))
    pdf = tmp_path / "fixture.pdf"
    pdf.write_bytes(b"verified fixture")
    calls = []
    monkeypatch.setattr(
        batch_module,
        "acquire_full_text_maximized",
        lambda req, **kw: (
            calls.append(req)
            or _Result(req.doi, MaximizedAcquisitionStatus.VERIFIED, pdf)
        ),
    )
    checkpoint = tmp_path / "checkpoint.json"
    first = acquire_full_text_batch_maximized(
        [request, request, other], output_dir=tmp_path, checkpoint_path=checkpoint
    )
    assert len(first.items) == 2 and len(calls) == 2
    assert first.items[0].doi is None
    assert set(json.loads(checkpoint.read_text())["records"]) == {
        request.key,
        other.key,
    }
    resumed = acquire_full_text_batch_maximized(
        [request, other], output_dir=tmp_path, checkpoint_path=checkpoint
    )
    assert all(item.resumed for item in resumed.items) and len(calls) == 2
    pdf.write_bytes(b"changed")
    acquire_full_text_batch_maximized(
        [request], output_dir=tmp_path, checkpoint_path=checkpoint
    )
    assert len(calls) == 3


def test_ambiguity_and_unverified_are_item_outcomes_not_batch_crashes(
    monkeypatch, tmp_path
):
    statuses = iter(
        (
            MaximizedAcquisitionStatus.AMBIGUOUS,
            MaximizedAcquisitionStatus.RETRIEVED_UNVERIFIED,
        )
    )
    monkeypatch.setattr(
        batch_module,
        "acquire_full_text_maximized",
        lambda req, **kw: _Result(req.doi, next(statuses)),
    )
    result = acquire_full_text_batch_maximized(
        [PaperRequest(title="第一个题名"), PaperRequest(title="第二个题名")],
        output_dir=tmp_path,
    )
    assert [item.status for item in result.items] == [
        BatchItemStatus.AMBIGUOUS,
        BatchItemStatus.RETRIEVED_UNVERIFIED,
    ]
    assert not result.halted_for_interaction


def test_batch_never_replays_an_error_after_download_started(monkeypatch, tmp_path):
    calls = []

    def acquire(doi, **kwargs):
        calls.append(doi)
        result = _Result(doi, MaximizedAcquisitionStatus.ERROR)
        result.browser_attempts = (
            BrowserAccessAttempt(
                source_candidate=_source_candidate(doi),
                final_url=None,
                status=BrowserAttemptStatus.ERROR,
                download_started=True,
            ),
        )
        return result

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", acquire)
    result = acquire_full_text_batch_maximized(
        ["10.1000/test"],
        output_dir=tmp_path,
        max_item_attempts=3,
        retry_backoff=0,
    )
    assert calls == ["10.1000/test"]
    assert result.items[0].attempts == 1


def test_batch_reuses_one_session_and_preserves_order(monkeypatch, tmp_path):
    sessions = []

    def fake_acquire(doi, **kwargs):
        sessions.append(kwargs["browser_session"])
        return _Result(doi, MaximizedAcquisitionStatus.EXHAUSTED)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)

    result = acquire_full_text_batch_maximized(
        ["10.1000/one", "bad", "https://doi.org/10.1000/TWO"],
        output_dir=tmp_path,
    )

    assert [item.status for item in result.items] == [
        BatchItemStatus.EXHAUSTED,
        BatchItemStatus.INVALID_DOI,
        BatchItemStatus.EXHAUSTED,
    ]
    assert result.items[2].doi == "10.1000/two"
    assert len(sessions) == 2
    assert sessions[0] is sessions[1]
    assert isinstance(sessions[0], BrowserSession)


def test_batch_deduplicates_normalized_dois(monkeypatch, tmp_path):
    calls = []

    def fake_acquire(doi, **kwargs):
        calls.append(doi)
        return _Result(doi, MaximizedAcquisitionStatus.EXHAUSTED)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)

    result = acquire_full_text_batch_maximized(
        ["10.1000/ONE", "https://doi.org/10.1000/one"],
        output_dir=tmp_path,
    )

    assert calls == ["10.1000/one"]
    assert len(result.items) == 1


def test_batch_stops_after_interaction_and_defers_remaining(monkeypatch, tmp_path):
    calls = []

    def fake_acquire(doi, **kwargs):
        calls.append(doi)
        return _Result(doi, MaximizedAcquisitionStatus.INTERACTION_REQUIRED)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)

    result = acquire_full_text_batch_maximized(
        ["10.1000/one", "10.1000/two"],
        output_dir=tmp_path,
        stop_on_interaction=True,
    )

    assert calls == ["10.1000/one"]
    assert [item.status for item in result.items] == [
        BatchItemStatus.INTERACTION_REQUIRED,
        BatchItemStatus.DEFERRED,
    ]
    assert result.halted_for_interaction is True


def test_batch_continues_after_item_level_interaction_only_when_requested(
    monkeypatch,
    tmp_path,
):
    calls = []

    def fake_acquire(doi, **kwargs):
        calls.append(doi)
        status = (
            MaximizedAcquisitionStatus.INTERACTION_REQUIRED
            if len(calls) == 1
            else MaximizedAcquisitionStatus.EXHAUSTED
        )
        return _Result(doi, status)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)

    result = acquire_full_text_batch_maximized(
        ["10.1000/one", "10.1000/two"],
        output_dir=tmp_path,
        stop_on_interaction=False,
    )

    assert calls == ["10.1000/one", "10.1000/two"]
    assert [item.status for item in result.items] == [
        BatchItemStatus.INTERACTION_REQUIRED,
        BatchItemStatus.EXHAUSTED,
    ]
    assert result.halted_for_interaction is False


def test_ieee_manual_file_handoff_resumes_same_item(monkeypatch, tmp_path):
    calls = []
    chosen = tmp_path / "user.pdf"

    def fake_acquire(doi, **kwargs):
        calls.append((doi, kwargs["local_pdf_path"]))
        status = (
            MaximizedAcquisitionStatus.VERIFIED
            if kwargs["local_pdf_path"] == chosen
            else MaximizedAcquisitionStatus.INTERACTION_REQUIRED
        )
        return _Result(doi, status)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)
    result = acquire_full_text_batch_maximized(
        ["10.1109/ICEET.2009.450"],
        output_dir=tmp_path,
        manual_file_callback=lambda doi: chosen,
    )

    assert calls == [
        ("10.1109/iceet.2009.450", None),
        ("10.1109/iceet.2009.450", chosen),
    ]
    assert result.items[0].status == BatchItemStatus.VERIFIED


def test_batch_checkpoint_resumes_only_hash_matching_verified_file(
    monkeypatch, tmp_path
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"verified-pdf")
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sidecar = pdf.with_suffix(".acquisition.json")
    sidecar.write_bytes(b'{"fixture":"verified"}')
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema": "aletheia-nexus/access-batch-checkpoint/v1",
                "records": {
                    "10.1000/one": {
                        "status": "VERIFIED",
                        "verified_path": str(pdf),
                        "sha256": digest,
                        "sidecar_sha256": hashlib.sha256(
                            sidecar.read_bytes()
                        ).hexdigest(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def should_not_acquire(*args, **kwargs):
        raise AssertionError("valid VERIFIED checkpoint must skip acquisition")

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", should_not_acquire)
    result = acquire_full_text_batch_maximized(
        ["10.1000/one"],
        output_dir=tmp_path,
        checkpoint_path=checkpoint,
    )

    assert result.items[0].status == BatchItemStatus.VERIFIED
    assert result.items[0].resumed is True
    assert result.items[0].verified_path == pdf
    sidecar.unlink()
    assert (
        batch_module._verified_checkpoint_item(
            "10.1000/one",
            "10.1000/one",
            json.loads(checkpoint.read_text())["records"]["10.1000/one"],
        )
        is None
    )


def test_changed_verified_file_is_not_trusted(monkeypatch, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"changed")
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema": "aletheia-nexus/access-batch-checkpoint/v1",
                "records": {
                    "10.1000/one": {
                        "status": "VERIFIED",
                        "verified_path": str(pdf),
                        "sha256": "0" * 64,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_acquire(doi, **kwargs):
        calls.append(doi)
        return _Result(doi, MaximizedAcquisitionStatus.EXHAUSTED)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)
    result = acquire_full_text_batch_maximized(
        ["10.1000/one"],
        output_dir=tmp_path,
        checkpoint_path=checkpoint,
    )

    assert calls == ["10.1000/one"]
    assert result.items[0].resumed is False


def test_checkpoint_does_not_persist_exception_message(monkeypatch, tmp_path):
    checkpoint = tmp_path / "checkpoint.json"

    def explode(*args, **kwargs):
        raise RuntimeError("https://example.test/file?token=top-secret")

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", explode)
    result = acquire_full_text_batch_maximized(
        ["10.1000/one"],
        output_dir=tmp_path,
        checkpoint_path=checkpoint,
    )

    assert result.items[0].status == BatchItemStatus.RUNNER_ERROR
    assert result.items[0].error == "RuntimeError"
    persisted = checkpoint.read_text(encoding="utf-8")
    assert "top-secret" not in persisted
    assert "example.test" not in persisted


def test_batch_retries_only_internal_errors(monkeypatch, tmp_path):
    calls = []

    def fake_acquire(doi, **kwargs):
        calls.append(doi)
        status = (
            MaximizedAcquisitionStatus.ERROR
            if len(calls) == 1
            else MaximizedAcquisitionStatus.ACCESS_DENIED
        )
        return _Result(doi, status)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)
    monkeypatch.setattr(batch_module.time, "sleep", lambda value: None)
    result = acquire_full_text_batch_maximized(
        ["10.1000/one"],
        output_dir=tmp_path,
        max_item_attempts=3,
    )

    assert len(calls) == 2
    assert result.items[0].attempts == 2
    assert result.items[0].status == BatchItemStatus.ACCESS_DENIED


def test_batch_forwards_title_and_options(monkeypatch, tmp_path):
    received = {}

    def fake_acquire(doi, **kwargs):
        received.update(kwargs)
        return _Result(doi, MaximizedAcquisitionStatus.EXHAUSTED)

    monkeypatch.setattr(batch_module, "acquire_full_text_maximized", fake_acquire)
    acquire_full_text_batch_maximized(
        ["10.1000/one"],
        output_dir=tmp_path,
        expected_titles={"https://doi.org/10.1000/ONE": "Target title"},
        unpaywall_email="researcher@example.org",
    )

    assert received["expected_title"] == "Target title"
    assert received["unpaywall_email"] == "researcher@example.org"


@pytest.mark.parametrize("value", ["10.1000/one", b"10.1000/one", None, 3])
def test_batch_rejects_non_collection_input(value, tmp_path):
    with pytest.raises(TypeError):
        acquire_full_text_batch_maximized(value, output_dir=tmp_path)


def test_batch_public_api_is_exported():
    from aletheia_nexus.acquire.access import acquire_full_text_batch_maximized

    assert callable(acquire_full_text_batch_maximized)
