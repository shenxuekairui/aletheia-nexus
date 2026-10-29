"""Read-only request reuse proves PDF structure from full current bytes."""

import hashlib
import json
import os
import shutil

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content import gate


def artifacts(tmp_path):
    pdf = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(pdf)
    sidecar = tmp_path / "paper.acquisition.json"
    payload = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "status": "VERIFIED",
        "target": {"doi": "10.5555/request-cache"},
        "retrieval": {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
        "pdf_validation": {"valid_pdf": True, "page_count": 1},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
    }
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return pdf, sidecar, payload


def test_identical_snapshot_reuses_structure_only_inside_one_request(
    tmp_path, monkeypatch
):
    pdf, sidecar, _ = artifacts(tmp_path)
    snapshot = tmp_path / "snapshot.pdf"
    shutil.copyfile(pdf, snapshot)
    native_reader, readers = gate.PdfReader, []

    def counted(*args, **kwargs):
        readers.append(args[0])
        return native_reader(*args, **kwargs)

    monkeypatch.setattr(gate, "PdfReader", counted)
    with gate._pdf_validation_session():
        first = gate.validate_parser_input(pdf, sidecar_path=sidecar)
        second = gate.validate_parser_input(snapshot, sidecar_path=sidecar)
        assert first.pdf_sha256 == second.pdf_sha256
        assert len(readers) == 1
    gate.validate_parser_input(snapshot, sidecar_path=sidecar)
    assert len(readers) == 2


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("status", "EXHAUSTED", "STATUS_NOT_VERIFIED"),
        ("page_count", 2, "PAGE_COUNT_MISMATCH"),
        ("role", "SUPPLEMENT", "DOCUMENT_NOT_ARTICLE"),
        ("doi", "10.5555/other", "DOI_MISMATCH"),
    ],
)
def test_cached_pdf_does_not_cache_its_sidecar_identity(tmp_path, field, value, code):
    pdf, sidecar, payload = artifacts(tmp_path)
    with gate._pdf_validation_session():
        gate.validate_parser_input(pdf, sidecar_path=sidecar)
        container, key = {
            "status": (payload, "status"),
            "page_count": (payload["pdf_validation"], "page_count"),
            "role": (payload["identity_validation"], "document_role"),
            "doi": (payload["target"], "doi"),
        }[field]
        container[key] = value
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(gate.ParserInputError, match=code):
            gate.validate_parser_input(
                pdf, "10.5555/request-cache", sidecar_path=sidecar
            )


def test_same_stat_mutation_and_mutation_during_structure_read_are_not_cached(
    tmp_path, monkeypatch
):
    pdf, sidecar, _ = artifacts(tmp_path)
    with gate._pdf_validation_session():
        gate.validate_parser_input(pdf, sidecar_path=sidecar)
        old = pdf.stat()
        data = bytearray(pdf.read_bytes())
        data[len(data) // 2] ^= 1
        pdf.write_bytes(data)
        os.utime(pdf, ns=(old.st_atime_ns, old.st_mtime_ns))
        with pytest.raises(gate.ParserInputError, match="PDF_HASH_MISMATCH"):
            gate.validate_parser_input(pdf, sidecar_path=sidecar)

    pdf, sidecar, _ = artifacts(tmp_path)
    native_reader = gate.PdfReader

    def changing_reader(*args, **kwargs):
        reader = native_reader(*args, **kwargs)
        pdf.write_bytes(pdf.read_bytes() + b" changed while reading")
        return reader

    monkeypatch.setattr(gate, "PdfReader", changing_reader)
    with gate._pdf_validation_session():
        with pytest.raises(gate.ParserInputError, match="PDF_HASH_MISMATCH"):
            gate.validate_parser_input(pdf, sidecar_path=sidecar)
        assert gate._PDF_PAGE_COUNTS.get() == {}


def test_structure_reuse_is_bounded_and_exception_clears_the_request(tmp_path):
    pdf, sidecar, _ = artifacts(tmp_path)
    with pytest.raises(RuntimeError, match="request interrupted"):
        with gate._pdf_validation_session():
            page_counts = gate._PDF_PAGE_COUNTS.get()
            page_counts.update({f"{index:064x}": 1 for index in range(1024)})
            gate.validate_parser_input(pdf, sidecar_path=sidecar)
            assert len(page_counts) == 1024
            raise RuntimeError("request interrupted")
    assert gate._PDF_PAGE_COUNTS.get() is None


def test_a_b_a_file_race_cannot_seed_structure_proof_for_other_pdf_bytes(
    tmp_path, monkeypatch
):
    pdf, sidecar, _ = artifacts(tmp_path)
    original = pdf.read_bytes()
    other = tmp_path / "different.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=333, height=444)
    writer.write(other)
    different = other.read_bytes()
    assert different != original
    native_reader = gate.PdfReader

    def changed_reader(*args, **kwargs):
        pdf.write_bytes(different)
        try:
            return native_reader(*args, **kwargs)
        finally:
            pdf.write_bytes(original)

    monkeypatch.setattr(gate, "PdfReader", changed_reader)
    with gate._pdf_validation_session():
        with pytest.raises(gate.ParserInputError, match="PDF_HASH_MISMATCH"):
            gate.validate_parser_input(pdf, sidecar_path=sidecar)
        assert gate._PDF_PAGE_COUNTS.get() == {}
    assert pdf.read_bytes() == original
