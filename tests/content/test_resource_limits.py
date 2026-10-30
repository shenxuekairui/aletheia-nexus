"""Compressed drawing limits fail per page without losing other evidence."""

from pypdf import PdfWriter, apply_configuration, get_configuration
from pypdf.generic import DecodedStreamObject, NameObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.service import parse_document


def test_native_layout_enforces_stream_guard_before_interpretation(tmp_path):
    writer = PdfWriter()
    first = writer.add_blank_page(600, 800)
    first[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    compressed = DecodedStreamObject()
    compressed.set_data(b"BT /F 10 Tf (" + b"X" * 4096 + b") Tj ET")
    first[NameObject("/Contents")] = writer._add_object(compressed.flate_encode())
    second = writer.add_blank_page(600, 800)
    second[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    second[NameObject("/Contents")] = stream(
        writer, b"BT /F 12 Tf 50 700 Td (Measured at 18 C for 2 h.) Tj ET"
    )
    pdf = tmp_path / "resource-limit.pdf"
    writer.write(pdf)
    registered = register_local_pdf(
        pdf, output_dir=tmp_path / "library", title="Self-authored resource fixture"
    )
    before = sha256_file(registered)
    with apply_configuration(zlib_maximum_output_length=128):
        result = parse_document(registered)
        assert get_configuration().zlib_maximum_output_length == 128
    assert result.status == "PARTIAL"
    assert any(
        b["page"] == 2 and "18 C" in b["text"] for b in result.document["blocks"]
    )
    error = next(
        e for e in result.document["errors"] if e["code"] == "PAGE_EXTRACTION_FAILED"
    )
    assert error["page"] == 1 and "LimitReachedError" in error["detail"]
    assert sha256_file(registered) == before
