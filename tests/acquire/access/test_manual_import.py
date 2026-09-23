import json

from pypdf import PdfWriter

from aletheia_nexus.acquire.access import import_local_pdf, service
from aletheia_nexus.acquire.access.models import MaximizedAcquisitionStatus
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus


def test_user_selected_pdf_is_verified_without_modifying_original(tmp_path):
    source = tmp_path / "user-selected.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Expected IEEE Article"})
    with source.open("wb") as handle:
        writer.write(handle)
    original = source.read_bytes()

    result = import_local_pdf(
        "10.1109/example.123",
        source,
        output_dir=tmp_path / "out",
        expected_title="Expected IEEE Article",
    )

    assert result.status == AcquisitionStatus.VERIFIED
    assert source.read_bytes() == original
    assert result.file_path is not None and result.file_path.is_file()
    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["transport"] == "user_selected_local_file"
    assert sidecar["retrieval"]["http_status"] == 0
    assert str(source) not in json.dumps(sidecar)


def test_user_selected_wrong_file_never_verifies(tmp_path):
    source = tmp_path / "not-a-pdf.pdf"
    source.write_text("not a PDF", encoding="utf-8")

    result = import_local_pdf(
        "10.1109/example.123",
        source,
        output_dir=tmp_path / "out",
        expected_title="Expected IEEE Article",
    )

    assert result.status == AcquisitionStatus.INVALID_PDF
    assert result.file_path is None
    assert source.is_file()
    assert list((tmp_path / "out").glob(".an-local-import-*.part")) == []


def test_user_selected_other_article_does_not_verify(tmp_path):
    source = tmp_path / "other-article.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "A completely unrelated article"})
    with source.open("wb") as handle:
        writer.write(handle)

    result = import_local_pdf(
        "10.1109/example.123",
        source,
        output_dir=tmp_path / "out",
        expected_title="Expected IEEE Article",
    )

    assert result.status != AcquisitionStatus.VERIFIED
    assert result.file_path is None
    assert source.is_file()


def test_ieee_maximized_imports_user_file_without_network(monkeypatch, tmp_path):
    source = tmp_path / "article.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Expected IEEE Article"})
    with source.open("wb") as handle:
        writer.write(handle)

    def forbid_network(*args, **kwargs):
        raise AssertionError("user file import must not start network acquisition")

    monkeypatch.setattr(service, "acquire_full_text", forbid_network)
    result = service.acquire_full_text_maximized(
        "10.1109/example.123",
        output_dir=tmp_path / "out",
        expected_title="Expected IEEE Article",
        local_pdf_path=source,
    )

    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert result.verified_path is not None
    assert source.is_file()
