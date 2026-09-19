from io import BytesIO

from pypdf import PdfWriter

from aletheia_nexus.acquire.access.browser_route import (
    _browser_response_to_file_attempt,
    _download_to_file_attempt,
)
from aletheia_nexus.acquire.access.models import BrowserAccessConfig
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus


class _Response:
    def __init__(self, body: bytes):
        self.url = "https://cdn.example/article.pdf?signature=secret"
        self.status = 200
        self.headers = {"content-type": "application/pdf"}
        self._body = body

    def body(self) -> bytes:
        return self._body


def _pdf_bytes() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Captured Browser Response"})
    writer.write(output)
    return output.getvalue()


def test_captured_browser_response_is_validated_without_rerequest(tmp_path):
    parent = FullTextCandidate(
        doi="10.1000/captured-response",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )
    attempt = _browser_response_to_file_attempt(
        _Response(_pdf_bytes()),
        parent=parent,
        source_page_url="https://publisher.example/article",
        output_dir=tmp_path,
        expected_title="Captured Browser Response",
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert attempt.method == "browser_response"
    assert attempt.result is not None
    assert attempt.result.status == AcquisitionStatus.VERIFIED
    assert attempt.result.file_path is not None


class _BlobDownload:
    def __init__(self, path):
        self.url = "blob:https://publisher.example/7c0f1a8c"
        self._path = path

    def path(self):
        return str(self._path)


def test_blob_download_is_validated_using_parent_route_provenance(tmp_path):
    source = tmp_path / "blob-download.pdf"
    source.write_bytes(_pdf_bytes())
    parent = FullTextCandidate(
        doi="10.1000/captured-response",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    attempt = _download_to_file_attempt(
        _BlobDownload(source),
        parent=parent,
        source_page_url=parent.url,
        output_dir=tmp_path / "out",
        expected_title="Captured Browser Response",
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert attempt.method == "browser_download"
    assert attempt.result is not None
    assert attempt.result.status == AcquisitionStatus.VERIFIED
    assert attempt.result.retrieved is not None
    assert attempt.result.retrieved.final_url == parent.url
    assert attempt.result.candidate.url == parent.url
