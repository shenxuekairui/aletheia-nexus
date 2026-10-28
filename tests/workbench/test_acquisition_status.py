"""Requested SI coverage affects the task, never successful main identity."""

import json
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.workbench import acquisition, supplements
from aletheia_nexus.workbench.acquisition import AcquisitionService


@pytest.fixture
def verified_service(tmp_path, monkeypatch):
    pdf = tmp_path / "main.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf.open("wb") as handle:
        writer.write(handle)
    # Synthetic receipt exercises application status, not live identity checks.
    source = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "status": "VERIFIED",
        "target": {"doi": "10.1000/main", "expected_title": "Synthetic main"},
        "retrieval": {"sha256": sha256_file(pdf)},
        "pdf_validation": {"valid_pdf": True, "page_count": 1},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
    }
    sidecar = acquisition_sidecar_path(pdf)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(source), encoding="utf-8")

    def batch(requests, **kwargs):
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    requests[0],
                    requests[0].doi,
                    BatchItemStatus.VERIFIED,
                    verified_path=pdf,
                )
            ]
        )

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    return AcquisitionService(tmp_path), sidecar


@pytest.mark.parametrize(
    "status,truncated,expected",
    [
        ("FAILED", False, "PARTIAL"),
        ("PARTIAL", False, "PARTIAL"),
        ("NOT_FOUND", False, "PARTIAL"),
        ("NOT_SUPPORTED", False, "PARTIAL"),
        ("COMPLETED", True, "PARTIAL"),
        ("COMPLETED", False, "COMPLETED"),
    ],
)
def test_main_verification_survives_incomplete_si_task_status(
    verified_service, monkeypatch, status, truncated, expected
):
    service, sidecar = verified_service
    original = sidecar.read_bytes()
    monkeypatch.setattr(
        supplements,
        "acquire_supplements",
        lambda *a, **kw: {"status": status, "truncated": truncated, "items": []},
    )
    result = service.run(["10.1000/main"], {"include_si": True})
    assert result["status"] == expected
    assert result["success"] == 1
    assert result["items"][0]["status"] == "VERIFIED"
    assert result["items"][0]["identity_verified"] is True
    assert sidecar.read_bytes() == original
    assert result["si_incomplete_count"] == (1 if expected == "PARTIAL" else 0)
    assert bool(result["warnings"]) == (expected == "PARTIAL")


def test_si_count_limit_is_partial_even_when_all_attempted_files_succeeded(tmp_path):
    main = tmp_path / "main.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with main.open("wb") as handle:
        writer.write(handle)
    register_local_pdf(
        main, output_dir=tmp_path, title="Main fixture", doi="10.1000/main"
    )
    html = '<meta name="citation_doi" content="10.1000/main"><a href="/data-one.csv">Supplementary Data 1</a><a href="/data-two.csv">Supplementary Data 2</a>'

    def fetch(url, output_dir, **kwargs):
        path = output_dir / ".data.part"
        path.write_text("key,value\na,1\n", encoding="utf-8")
        return SimpleNamespace(local_path=path, sha256=sha256_file(path), final_url=url)

    result = supplements.acquire_supplements(
        main,
        max_files=1,
        page_fetch=lambda *a, **kw: SimpleNamespace(
            text=html,
            final_url="https://www.nature.com/articles/example",
            body_truncated=False,
        ),
        file_fetch=fetch,
    )
    assert result["status"] == "PARTIAL"
    assert result["truncated"] is True and result["discovered"] == 2
    assert len(result["items"]) == 1 and result["items"][0]["status"] == "SAVED"
