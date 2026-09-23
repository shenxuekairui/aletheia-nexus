from io import BytesIO

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access.browser_route import (
    _browser_response_to_file_attempt,
    _CdpDownloadCapture,
    _download_to_file_attempt,
    _request_pdf_candidate,
    _safe_context_get,
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


class _CdpSession:
    def __init__(self):
        self.handlers = {}
        self.commands = []
        self.detached = False

    def on(self, event, callback):
        self.handlers[event] = callback

    def send(self, method, params=None):
        self.commands.append((method, params or {}))

    def detach(self):
        self.detached = True


class _CdpBrowser:
    def __init__(self):
        self.session = _CdpSession()

    def new_browser_cdp_session(self):
        return self.session


class _CdpContext:
    def __init__(self):
        self.browser = _CdpBrowser()


class _WaitPage:
    url = "https://publisher.example/article.pdf"

    def wait_for_timeout(self, value):
        return None


def test_cdp_download_capture_uses_completed_browser_domain_file(tmp_path):
    context = _CdpContext()
    capture = _CdpDownloadCapture(context, tmp_path)
    session = context.browser.session

    behavior = session.commands[0]
    assert behavior[0] == "Browser.setDownloadBehavior"
    assert behavior[1]["behavior"] == "allowAndName"
    staging_dir = capture.staging_dir
    assert staging_dir is not None
    saved = staging_dir / "download-guid"
    saved.write_bytes(_pdf_bytes())
    session.handlers["Browser.downloadWillBegin"](
        {
            "guid": "download-guid",
            "url": "https://publisher.example/article.pdf",
        }
    )
    session.handlers["Browser.downloadProgress"](
        {
            "guid": "download-guid",
            "state": "completed",
            "filePath": str(saved),
        }
    )

    result = capture.wait(_WaitPage(), 1)
    assert result == (saved, "https://publisher.example/article.pdf")

    capture.close()
    assert session.commands[-1] == (
        "Browser.setDownloadBehavior",
        {"behavior": "default"},
    )
    assert session.detached is True
    assert not staging_dir.exists()


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


class _SaveAsDownload(_BlobDownload):
    def path(self):
        raise FileNotFoundError("Chromium temp path was already reclaimed")

    def save_as(self, destination):
        destination = type(self._path)(destination)
        destination.write_bytes(self._path.read_bytes())


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


def test_browser_download_prefers_save_as_over_ephemeral_path(tmp_path):
    source = tmp_path / "download.pdf"
    source.write_bytes(_pdf_bytes())
    parent = FullTextCandidate(
        doi="10.1000/captured-response",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    attempt = _download_to_file_attempt(
        _SaveAsDownload(source),
        parent=parent,
        source_page_url=parent.url,
        output_dir=tmp_path / "out",
        expected_title="Captured Browser Response",
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert attempt.result is not None
    assert attempt.result.status == AcquisitionStatus.VERIFIED


class _RedirectResponse:
    def __init__(self, *, url, status, location=None):
        self.url = url
        self.status = status
        self.headers = {}
        if location is not None:
            self.headers["location"] = location
        self.disposed = False

    def dispose(self):
        self.disposed = True


class _RequestClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class _RequestContext:
    def __init__(self, responses):
        self.request = _RequestClient(responses)


def test_authenticated_request_follows_public_redirects_manually():
    first = _RedirectResponse(
        url="https://publisher.example/start",
        status=302,
        location="https://cdn.example/article.pdf",
    )
    final = _RedirectResponse(
        url="https://cdn.example/article.pdf",
        status=200,
    )
    context = _RequestContext([first, final])

    response, redirects = _safe_context_get(
        context,
        url="https://publisher.example/start",
        request_kwargs={"timeout": 1000, "fail_on_status_code": False},
        max_redirects=2,
    )

    assert response is final
    assert first.disposed is True
    assert len(redirects) == 1
    assert redirects[0].to_url == "https://cdn.example/article.pdf"
    assert [call[0] for call in context.request.calls] == [
        "https://publisher.example/start",
        "https://cdn.example/article.pdf",
    ]
    assert all(call[1]["max_redirects"] == 0 for call in context.request.calls)


def test_authenticated_request_rejects_redirect_to_private_network():
    first = _RedirectResponse(
        url="https://publisher.example/start",
        status=302,
        location="http://127.0.0.1/private",
    )
    context = _RequestContext([first])

    with pytest.raises(ValueError):
        _safe_context_get(
            context,
            url="https://publisher.example/start",
            request_kwargs={"timeout": 1000, "fail_on_status_code": False},
            max_redirects=2,
        )

    assert first.disposed is True
    assert len(context.request.calls) == 1
    assert context.request.calls[0][1]["max_redirects"] == 0


def test_failed_browser_download_validation_cleans_temp_file(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "download.pdf"
    source.write_bytes(_pdf_bytes())
    output_dir = tmp_path / "out"
    parent = FullTextCandidate(
        doi="10.1000/captured-response",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    def fail_validation(**kwargs):
        raise RuntimeError("failed at https://cdn.example/pdf?token=super-secret")

    monkeypatch.setattr(
        "aletheia_nexus.acquire.access.browser_route.finalize_browser_resource",
        fail_validation,
    )

    attempt = _download_to_file_attempt(
        _BlobDownload(source),
        parent=parent,
        source_page_url=parent.url,
        output_dir=output_dir,
        expected_title="Captured Browser Response",
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert attempt.result is None
    assert attempt.error == "RuntimeError"
    assert "super-secret" not in attempt.error
    assert "cdn.example" not in attempt.error
    assert list(output_dir.glob(".an-browser-download-*.part")) == []


class _PdfRequestResponse:
    def __init__(self, body: bytes):
        self.url = "https://cdn.example/article.pdf"
        self.status = 200
        self.headers = {"content-type": "application/pdf"}
        self._body = body
        self.disposed = False

    def body(self):
        return self._body

    def dispose(self):
        self.disposed = True


def test_failed_captured_response_validation_cleans_temp_file(
    monkeypatch,
    tmp_path,
):
    output_dir = tmp_path / "captured-out"
    parent = FullTextCandidate(
        doi="10.1000/captured-response",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    monkeypatch.setattr(
        "aletheia_nexus.acquire.access.browser_route.finalize_browser_resource",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("validation failed")),
    )

    attempt = _browser_response_to_file_attempt(
        _Response(_pdf_bytes()),
        parent=parent,
        source_page_url=parent.url,
        output_dir=output_dir,
        expected_title="Captured Browser Response",
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert attempt.result is None
    assert attempt.error == "RuntimeError"
    assert list(output_dir.glob(".an-browser-*.part")) == []


def test_failed_context_request_validation_cleans_temp_file(
    monkeypatch,
    tmp_path,
):
    output_dir = tmp_path / "request-out"
    candidate = FullTextCandidate(
        doi="10.1000/captured-response",
        url="https://cdn.example/article.pdf",
        provenance=(),
        url_type=CandidateUrlType.PDF,
    )
    response = _PdfRequestResponse(_pdf_bytes())
    context = _RequestContext([response])

    monkeypatch.setattr(
        "aletheia_nexus.acquire.access.browser_route.finalize_browser_resource",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("validation failed")),
    )

    attempt, challenge = _request_pdf_candidate(
        context,
        candidate=candidate,
        source_page_url="https://publisher.example/article?ticket=secret",
        output_dir=output_dir,
        expected_title="Captured Browser Response",
        config=BrowserAccessConfig(profile_root=tmp_path),
    )

    assert challenge is None
    assert attempt.result is None
    assert attempt.error == "RuntimeError"
    assert response.disposed is True
    assert list(output_dir.glob(".an-browser-*.part")) == []


def test_captured_response_honors_content_length_before_body(tmp_path):
    class OversizedResponse:
        url = "https://cdn.example/article.pdf"
        status = 200
        headers = {
            "content-type": "application/pdf",
            "content-length": "999999",
        }

        def body(self):
            raise AssertionError("oversized body must not be read")

    parent = FullTextCandidate(
        doi="10.1000/oversized-response",
        url="https://publisher.example/article",
        provenance=(),
        url_type=CandidateUrlType.LANDING_PAGE,
    )

    attempt = _browser_response_to_file_attempt(
        OversizedResponse(),
        parent=parent,
        source_page_url=parent.url,
        output_dir=tmp_path,
        expected_title=None,
        config=BrowserAccessConfig(
            profile_root=tmp_path,
            max_bytes=1024,
        ),
    )

    assert attempt.result is None
    assert "exceeds max_bytes" in attempt.error
