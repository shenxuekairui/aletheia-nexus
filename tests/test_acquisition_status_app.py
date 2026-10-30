"""Read-only acquisition receipts and current source checks; no network."""

import json
from pathlib import Path

import pytest
from test_research_app import write_pdf

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import ResearchApplication


@pytest.fixture
def registered(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    pdf = papers / "paper.pdf"
    write_pdf(pdf, [[(50, 650, 12, "A self-authored paper.")]], title="Paper")
    sidecar = papers / "paper.acquisition.json"
    record = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "status": "VERIFIED",
        "target": {"doi": "10.1234/example", "expected_title": "Paper"},
        "retrieval": {"sha256": sha256_file(pdf)},
        "pdf_validation": {"valid_pdf": True, "page_count": 1},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
    }
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    service = ResearchApplication([papers], tmp_path / "workspace")
    yield service, pdf, sidecar, record
    service.close()


@pytest.mark.parametrize(
    "schema", ["acquisition-record", "access-acquisition-record", "local-document"]
)
def test_source_check_preserves_record_and_declared_identity(registered, schema):
    app, pdf, sidecar, record = registered
    local = schema == "local-document"
    record["schema"] = f"aletheia-nexus/{schema}/v1"
    if local:
        record["status"] = "REGISTERED"
        record["identity_validation"]["status"] = "DECLARED"
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    before = {p: p.read_bytes() for p in (pdf, sidecar)}
    report = app.get_acquisition_status(str(sidecar), pdf=str(pdf))
    assert report["recorded_status"] == record["status"]
    assert report["current_check"]["status"] == "PASSED"
    assert report["current_check"]["identity_verified"] is not local
    assert report["current_check"]["identity_basis"] == (
        "local_declared" if local else "acquisition_verified"
    )
    assert report["network_access"] is report["new_files"] is False
    assert not list(app.workspace.iterdir())
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("failure", ["tampered", "doi", "missing"])
def test_old_verified_record_does_not_mask_current_failure(registered, failure):
    app, pdf, sidecar, _ = registered
    kwargs = {}
    if failure == "tampered":
        pdf.write_bytes(pdf.read_bytes() + b"\nchanged")
        expected = "PDF_HASH_MISMATCH"
    elif failure == "doi":
        kwargs["expected_doi"] = "10.1234/different"
        expected = "DOI_MISMATCH"
    else:
        pdf.unlink()
        expected = "PDF_NOT_FOUND"
    before = sidecar.read_bytes()
    report = app.get_acquisition_status(str(sidecar), pdf=str(pdf), **kwargs)
    assert report["recorded_status"] == "VERIFIED"
    assert report["current_check"] == {"status": "FAILED", "error": expected}
    assert sidecar.read_bytes() == before


def test_failed_receipt_is_readable_without_following_record_paths(
    registered, monkeypatch
):
    app, pdf, sidecar, record = registered
    inaccessible = app.workspace.parent / "outside.pdf"
    record.update(status="AUTH_REQUIRED", pdf_validation=None, identity_validation=None)
    record["retrieval"].update(
        local_path=str(inaccessible), final_url="https://invalid.example/private"
    )
    record["locators"] = {"pdf": str(inaccessible)}
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != inaccessible
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    report = app.get_acquisition_status(str(sidecar))
    assert report["recorded_status"] == "AUTH_REQUIRED"
    assert report["current_check"]["status"] == "NOT_CHECKED"
    assert "private" not in json.dumps(report)
    checked = app.get_acquisition_status(str(sidecar), pdf=str(pdf))
    assert checked["current_check"]["error"] == "STATUS_NOT_VERIFIED"
    with pytest.raises(ValueError, match="explicitly selected"):
        app.get_acquisition_status(str(sidecar), expected_doi="10.1234/example")


def test_all_explicit_paths_checked_before_read(registered, monkeypatch):
    app, pdf, sidecar, _ = registered
    outside = app.workspace.parent / "outside.json"

    def forbidden_read(_):
        pytest.fail("record was read before path authorization")

    monkeypatch.setattr("aletheia_nexus.research_app.read_json", forbidden_read)
    for selected_sidecar, selected_pdf in ((outside, pdf), (sidecar, outside)):
        with pytest.raises(ProcessingError, match="path_outside"):
            app.get_acquisition_status(str(selected_sidecar), pdf=str(selected_pdf))
    with pytest.raises(ProcessingError, match="authorization_directory_private"):
        app.get_acquisition_status(str(app.private / "grant.json"))


def test_unknown_json_is_not_an_acquisition_receipt(registered):
    app, _, sidecar, _ = registered
    sidecar.write_text(
        '{"schema":"arbitrary/v1","status":"VERIFIED"}', encoding="utf-8"
    )
    with pytest.raises(ProcessingError, match="unsupported_acquisition_record"):
        app.get_acquisition_status(str(sidecar))
