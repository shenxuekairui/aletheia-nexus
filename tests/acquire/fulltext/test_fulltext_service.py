import hashlib
import json

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext import service
from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionAuthRequiredError
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionStatus,
    RetrievedResource,
)


def _candidate(url_type=CandidateUrlType.PDF):
    return FullTextCandidate(
        doi="10.1000/xyz123",
        url="https://example.org/paper.pdf",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=url_type,
    )


def _write_pdf(path, *, title=None):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if title:
        writer.add_metadata({"/Title": title})
    with path.open("wb") as handle:
        writer.write(handle)


def _resource(path):
    data = path.read_bytes()
    return RetrievedResource(
        requested_url="https://example.org/paper.pdf",
        final_url="https://example.org/paper.pdf",
        http_status=200,
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        local_path=path,
    )


def test_verified_pdf_is_promoted_and_sidecar_written(tmp_path, monkeypatch):
    temp = tmp_path / "download.part"
    _write_pdf(temp, title="Electrocatalytic Water Activation at Interfaces")
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(temp)
    )

    result = service.acquire_direct_pdf(
        _candidate(),
        output_dir=tmp_path / "out",
        expected_title="Electrocatalytic Water Activation at Interfaces",
    )

    assert result.status == AcquisitionStatus.VERIFIED
    assert result.file_path is not None and result.file_path.exists()
    assert result.sidecar_path is not None and result.sidecar_path.exists()
    assert result.retrieved is not None
    assert result.retrieved.local_path == result.file_path
    assert not temp.exists()

    record = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert record["status"] == "VERIFIED"
    assert record["retrieval"]["sha256"] == result.retrieved.sha256


def test_auxiliary_pdf_is_not_promoted_as_verified(tmp_path, monkeypatch):
    temp = tmp_path / "download.part"
    _write_pdf(temp, title="Reporting Summary")
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(temp)
    )

    result = service.acquire_direct_pdf(_candidate(), output_dir=tmp_path / "out")

    assert result.status == AcquisitionStatus.SUPPLEMENT
    assert result.file_path is None
    assert result.retrieved is not None
    assert result.retrieved.local_path is None
    assert not temp.exists()


def test_unverified_pdf_is_not_persisted_by_default(tmp_path, monkeypatch):
    temp = tmp_path / "download.part"
    _write_pdf(temp)
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(temp)
    )

    result = service.acquire_direct_pdf(_candidate(), output_dir=tmp_path / "out")

    assert result.status == AcquisitionStatus.RETRIEVED_UNVERIFIED
    assert result.file_path is None
    assert result.retrieved is not None
    assert result.retrieved.local_path is None
    assert not temp.exists()


def test_unverified_pdf_can_be_kept_for_manual_review(tmp_path, monkeypatch):
    temp = tmp_path / "download.part"
    _write_pdf(temp)
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(temp)
    )

    result = service.acquire_direct_pdf(
        _candidate(),
        output_dir=tmp_path / "out",
        keep_unverified=True,
    )

    assert result.status == AcquisitionStatus.RETRIEVED_UNVERIFIED
    assert result.file_path is not None and result.file_path.exists()
    assert result.file_path.parent.name == "_unverified"
    assert result.sidecar_path is not None and result.sidecar_path.exists()
    assert result.retrieved is not None
    assert result.retrieved.local_path == result.file_path


def test_invalid_pdf_is_deleted_without_stale_local_path(tmp_path, monkeypatch):
    temp = tmp_path / "download.part"
    temp.write_text("<html>login</html>", encoding="utf-8")
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(temp)
    )

    result = service.acquire_direct_pdf(_candidate(), output_dir=tmp_path / "out")

    assert result.status == AcquisitionStatus.INVALID_PDF
    assert result.retrieved is not None
    assert result.retrieved.local_path is None
    assert not temp.exists()


def test_new_promoted_pdf_is_rolled_back_if_sidecar_write_fails(tmp_path, monkeypatch):
    temp = tmp_path / "download.part"
    _write_pdf(temp, title="Electrocatalytic Water Activation at Interfaces")
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(temp)
    )

    def fail_sidecar(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service, "write_json_sidecar", fail_sidecar)

    with pytest.raises(OSError, match="disk full"):
        service.acquire_direct_pdf(
            _candidate(),
            output_dir=tmp_path / "out",
            expected_title="Electrocatalytic Water Activation at Interfaces",
        )

    assert list((tmp_path / "out").glob("*.pdf")) == []


def test_existing_verified_pdf_survives_later_sidecar_failure(tmp_path, monkeypatch):
    output_dir = tmp_path / "out"
    title = "Electrocatalytic Water Activation at Interfaces"

    first_temp = tmp_path / "first.part"
    _write_pdf(first_temp, title=title)
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(first_temp)
    )
    first = service.acquire_direct_pdf(
        _candidate(),
        output_dir=output_dir,
        expected_title=title,
    )
    assert first.file_path is not None and first.file_path.exists()
    existing_path = first.file_path
    existing_bytes = existing_path.read_bytes()

    second_temp = tmp_path / "second.part"
    second_temp.write_bytes(existing_bytes)
    monkeypatch.setattr(
        service, "retrieve_to_temp", lambda *args, **kwargs: _resource(second_temp)
    )

    def fail_sidecar(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service, "write_json_sidecar", fail_sidecar)

    with pytest.raises(OSError, match="disk full"):
        service.acquire_direct_pdf(
            _candidate(),
            output_dir=output_dir,
            expected_title=title,
        )

    assert existing_path.exists()
    assert existing_path.read_bytes() == existing_bytes
    assert not second_temp.exists()


def test_authorization_failure_is_returned_as_stable_status(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AcquisitionAuthRequiredError("login required")

    monkeypatch.setattr(service, "retrieve_to_temp", fail)

    result = service.acquire_direct_pdf(_candidate(), output_dir=tmp_path)

    assert result.status == AcquisitionStatus.AUTH_REQUIRED
    assert result.attempts == 1
    assert result.error == "login required"


def test_non_pdf_candidate_is_rejected_before_network(tmp_path):
    with pytest.raises(ValueError, match="only accepts PDF candidates"):
        service.acquire_direct_pdf(
            _candidate(CandidateUrlType.LANDING_PAGE),
            output_dir=tmp_path,
        )
