import httpx
import pytest

from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionAccessBlockedError,
    AcquisitionAuthRequiredError,
    AcquisitionRedirectError,
    AcquisitionTooLargeError,
)
from aletheia_nexus.acquire.fulltext.resolution import transport


def _unsafe_checks_off(monkeypatch):
    monkeypatch.setattr(transport, "validate_safe_url", lambda value: value)


def test_page_transport_follows_redirects_and_decodes_html(monkeypatch):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(
                302, headers={"Location": "/article"}, request=request
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<html><title>Paper</title></html>",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        page = transport.retrieve_page("https://example.org/start", client=client)

    assert page.final_url == "https://example.org/article"
    assert page.text is not None and "Paper" in page.text
    assert len(page.redirects) == 1
    assert page.is_pdf_response is False


def test_page_transport_recognizes_direct_pdf_response_without_full_download(
    monkeypatch,
):
    _unsafe_checks_off(monkeypatch)
    body = b"%PDF-1.7\n" + b"x" * 100_000

    def handler(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/octet-stream"},
            content=body,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        page = transport.retrieve_page(
            "https://example.org/route",
            max_bytes=1024,
            client=client,
        )

    assert page.is_pdf_response is True
    assert page.text is None
    assert page.body_truncated is True
    assert page.size_bytes <= transport._READ_CHUNK_BYTES
    assert page.size_bytes < len(body)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AcquisitionAuthRequiredError),
        (403, AcquisitionAccessBlockedError),
    ],
)
def test_page_transport_preserves_access_semantics(monkeypatch, status, error):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(status, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error):
            transport.retrieve_page("https://example.org/article", client=client)


def test_page_transport_rejects_large_html(monkeypatch):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(200, content=b"x" * 101, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AcquisitionTooLargeError):
            transport.retrieve_page(
                "https://example.org/article", max_bytes=100, client=client
            )


def test_page_transport_rejects_redirect_without_location(monkeypatch):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(302, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AcquisitionRedirectError):
            transport.retrieve_page("https://example.org/article", client=client)


def test_page_transport_marks_non_text_non_pdf_content_as_unparsed(monkeypatch):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/zip"},
            content=b"PK-not-html",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        page = transport.retrieve_page("https://example.org/archive", client=client)

    assert page.text is None
    assert page.is_pdf_response is False
