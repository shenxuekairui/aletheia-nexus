import hashlib
import json

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content import (
    ParserInputError,
    ParserInputErrorCode,
    validate_parser_input,
)


def _artifacts(tmp_path, *, schema="aletheia-nexus/acquisition-record/v1"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    pdf = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as handle:
        writer.write(handle)
    payload = {
        "schema": schema,
        "status": "VERIFIED",
        "target": {"doi": "10.5555/gate"},
        "retrieval": {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
        "pdf_validation": {"valid_pdf": True, "page_count": 1},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
    }
    sidecar = pdf.with_suffix(".acquisition.json")
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return pdf, sidecar, payload


@pytest.mark.parametrize(
    "schema",
    [
        "aletheia-nexus/acquisition-record/v1",
        "aletheia-nexus/access-acquisition-record/v1",
    ],
)
def test_gate_accepts_both_current_sidecar_variants(tmp_path, schema):
    pdf, sidecar, _ = _artifacts(tmp_path, schema=schema)
    result = validate_parser_input(pdf, "https://doi.org/10.5555/GATE")
    assert result.sidecar_path == sidecar
    assert result.doi == "10.5555/gate"
    assert result.page_count == 1


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda item: item.update(schema="future/v2"),
            ParserInputErrorCode.UNKNOWN_SIDECAR_SCHEMA,
        ),
        (
            lambda item: item.update(schema=[]),
            ParserInputErrorCode.UNKNOWN_SIDECAR_SCHEMA,
        ),
        (
            lambda item: item.update(status="EXHAUSTED"),
            ParserInputErrorCode.STATUS_NOT_VERIFIED,
        ),
        (
            lambda item: item["pdf_validation"].update(valid_pdf=False),
            ParserInputErrorCode.PDF_VALIDATION_FAILED,
        ),
        (
            lambda item: item["identity_validation"].update(status="MISMATCH"),
            ParserInputErrorCode.IDENTITY_NOT_MATCHED,
        ),
        (
            lambda item: item["identity_validation"].update(document_role="SUPPLEMENT"),
            ParserInputErrorCode.DOCUMENT_NOT_ARTICLE,
        ),
        (
            lambda item: item["target"].update(doi="10.5555/other"),
            ParserInputErrorCode.DOI_MISMATCH,
        ),
        (
            lambda item: item["retrieval"].update(sha256="bad"),
            ParserInputErrorCode.INVALID_RECORDED_HASH,
        ),
        (
            lambda item: item["pdf_validation"].update(page_count=2),
            ParserInputErrorCode.PAGE_COUNT_MISMATCH,
        ),
    ],
)
def test_gate_fails_closed_for_invalid_evidence(tmp_path, mutation, expected):
    pdf, sidecar, payload = _artifacts(tmp_path)
    mutation(payload)
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ParserInputError) as exc:
        validate_parser_input(pdf, "10.5555/gate")
    assert exc.value.code == expected


def test_gate_detects_changed_and_corrupt_pdf(tmp_path):
    pdf, _, _ = _artifacts(tmp_path)
    pdf.write_bytes(pdf.read_bytes() + b"changed")
    with pytest.raises(ParserInputError) as exc:
        validate_parser_input(pdf, "10.5555/gate")
    assert exc.value.code == ParserInputErrorCode.PDF_HASH_MISMATCH

    pdf, sidecar, payload = _artifacts(tmp_path / "corrupt")
    pdf.write_bytes(b"not a pdf")
    payload["retrieval"]["sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ParserInputError) as exc:
        validate_parser_input(pdf, "10.5555/gate")
    assert exc.value.code == ParserInputErrorCode.PDF_UNREADABLE


def test_gate_rejects_unverified_directory(tmp_path):
    directory = tmp_path / "_unverified"
    directory.mkdir()
    pdf, _, _ = _artifacts(directory)
    with pytest.raises(ParserInputError) as exc:
        validate_parser_input(pdf, "10.5555/gate")
    assert exc.value.code == ParserInputErrorCode.UNVERIFIED_PATH
