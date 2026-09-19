from io import BytesIO

from pypdf import PdfWriter

from aletheia_nexus.acquire.access.browser_route import (
    _browser_response_to_file_attempt,
    _context_get_with_safe_redirects,
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
    from aletheia_nexus.acquire.access.browser_route import _safe_context_get

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
    import pytest

    from aletheia_nexus.acquire.access.browser_route import _safe_context_get

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
        )

    assert first.disposed is True
    assert len(context.request.calls) == 1



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


def test_authenticated_request_redirects_are_followed_manually_and_bounded(tmp_path):
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
    config = BrowserAccessConfig(
        profile_root=tmp_path,
        max_request_redirects=2,
    )

    response = _context_get_with_safe_redirects(
        context,
        url="https://publisher.example/start",
        source_page_url="https://publisher.example/article",
        config=config,
    )

    assert response is final
    assert first.disposed is True
    assert [call[0] for call in context.request.calls] == [
        "https://publisher.example/start",
        "https://cdn.example/article.pdf",
    ]
    assert all(call[1]["max_redirects"] == 0 for call in context.request.calls)


def test_authenticated_request_rejects_unsafe_redirect_before_second_request(tmp_path):
    first = _RedirectResponse(
        url="https://publisher.example/start",
        status=302,
        location="http://127.0.0.1/private.pdf",
    )
    context = _RequestContext([first])
    config = BrowserAccessConfig(
        profile_root=tmp_path,
        max_request_redirects=2,
    )

    import pytest

    with pytest.raises(ValueError):
        _context_get_with_safe_redirects(
            context,
            url="https://publisher.example/start",
            source_page_url=None,
            config=config,
        )

    assert first.disposed is True
    assert len(context.request.calls) == 1
    assert context.request.calls[0][1]["max_redirects"] == 0
