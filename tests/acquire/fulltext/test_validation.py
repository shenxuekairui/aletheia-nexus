from pypdf import PdfWriter

from aletheia_nexus.acquire.fulltext.validation import inspect_pdf


def test_compressed_stream_limit_is_reported_without_disabling_guard(tmp_path):
    from pypdf import apply_configuration, get_configuration
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 10 Tf (" + b"X" * 4096 + b") Tj ET")
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    path = tmp_path / "compressed.pdf"
    writer.write(path)
    with apply_configuration(zlib_maximum_output_length=128):
        inspection = inspect_pdf(path)
        assert get_configuration().zlib_maximum_output_length == 128

    assert inspection.report.valid_pdf and inspection.report.page_count == 1
    assert "resource limit" in inspection.report.warning
    assert not inspection.extracted_text
    assert not inspection.first_page_text
    assert not inspection.page_margins


def _write_pdf(
    path,
    *,
    title=None,
    encrypted=False,
    empty_user_password=False,
):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if title:
        writer.add_metadata({"/Title": title})
    if empty_user_password:
        writer.encrypt("", owner_password="owner", algorithm="AES-256")
    elif encrypted:
        writer.encrypt("secret")
    with path.open("wb") as handle:
        writer.write(handle)


def test_valid_pdf_is_parseable_and_reports_pages(tmp_path):
    path = tmp_path / "paper.pdf"
    _write_pdf(path, title="Target Paper")

    inspection = inspect_pdf(path)

    assert inspection.report.valid_pdf is True
    assert inspection.report.magic_bytes_ok is True
    assert inspection.report.parseable is True
    assert inspection.report.page_count == 1
    assert inspection.metadata_title == "Target Paper"


def test_html_disguised_as_pdf_is_rejected(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_text("<html>login</html>", encoding="utf-8")

    inspection = inspect_pdf(path)

    assert inspection.report.valid_pdf is False
    assert inspection.report.magic_bytes_ok is False


def test_malformed_pdf_header_is_not_enough(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not a real PDF")

    inspection = inspect_pdf(path)

    assert inspection.report.valid_pdf is False
    assert inspection.report.magic_bytes_ok is True
    assert inspection.report.parseable is False


def test_locked_encrypted_pdf_is_valid_but_not_fully_inspectable(tmp_path):
    path = tmp_path / "encrypted.pdf"
    _write_pdf(path, title="Secret Paper", encrypted=True)

    inspection = inspect_pdf(path)

    assert inspection.report.valid_pdf is True
    assert inspection.report.encrypted is True
    assert inspection.report.page_count is None
    assert inspection.report.warning is not None


def test_aes_pdf_with_empty_user_password_can_be_inspected(tmp_path):
    path = tmp_path / "permission-encrypted.pdf"
    _write_pdf(
        path,
        title="Readable Encrypted Paper",
        empty_user_password=True,
    )

    inspection = inspect_pdf(path)

    assert inspection.report.valid_pdf is True
    assert inspection.report.encrypted is True
    assert inspection.report.page_count == 1
    assert inspection.report.warning is None
    assert inspection.metadata_title == "Readable Encrypted Paper"


def test_margin_extraction_uses_positions_and_orders_reversed_digit_fragments(tmp_path):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"\n".join(
            [
                b"BT /F1 10 Tf 1 0 0 1 40 770 Tm (Journal of Testing) Tj ET",
                b"BT /F1 10 Tf 1 0 0 1 40 755 Tm (2024 03) Tj ET",
                b"BT /F1 10 Tf 1 0 0 1 40 400 Tm (References: Another Journal 2025) Tj ET",
                b"BT /F1 10 Tf 1 0 0 1 52 30 Tm (1) Tj ET",
                b"BT /F1 10 Tf 1 0 0 1 46 30 Tm (2) Tj ET",
                b"BT /F1 10 Tf 1 0 0 1 40 30 Tm (0) Tj ET",
            ]
        )
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "margins.pdf"
    writer.write(path)
    inspection = inspect_pdf(path)
    margins = inspection.page_margins[0]
    assert margins.page_number == 1
    assert "Journal of Testing" in margins.header and "2024 03" in margins.header
    assert margins.footer.replace(" ", "") == "021"
    assert "Another Journal" not in margins.header + margins.footer
    assert "Another Journal" in inspection.first_page_text
