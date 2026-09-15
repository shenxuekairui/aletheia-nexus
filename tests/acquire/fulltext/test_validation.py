from pypdf import PdfWriter

from aletheia_nexus.acquire.fulltext.validation import inspect_pdf


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
