import hashlib

import httpx
import pytest

from aletheia_nexus.acquire.fulltext import transport
from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionAccessBlockedError,
    AcquisitionAuthRequiredError,
    AcquisitionNotFoundError,
    AcquisitionRedirectError,
    AcquisitionTooLargeError,
)


def _unsafe_checks_off(monkeypatch):
    monkeypatch.setattr(transport, "validate_safe_url", lambda value: value)


def test_retrieve_streams_bytes_and_records_hash(tmp_path, monkeypatch):
    _unsafe_checks_off(monkeypatch)
    body = b"%PDF-1.7\nexample"

    def handler(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=body,
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resource = transport.retrieve_to_temp(
            "https://example.org/paper.pdf",
            output_dir=tmp_path,
            client=client,
        )

    assert resource.local_path.read_bytes() == body
    assert resource.size_bytes == len(body)
    assert resource.sha256 == hashlib.sha256(body).hexdigest()
    assert resource.content_type == "application/pdf"
    assert resource.redirects == ()


def test_redirect_is_manually_followed_and_recorded(tmp_path, monkeypatch):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"Location": "/paper.pdf"},
                request=request,
            )
        return httpx.Response(200, content=b"%PDF-1.7\n", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resource = transport.retrieve_to_temp(
            "https://example.org/start",
            output_dir=tmp_path,
            client=client,
        )

    assert resource.final_url == "https://example.org/paper.pdf"
    assert len(resource.redirects) == 1
    assert resource.redirects[0].status_code == 302


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, AcquisitionAuthRequiredError),
        (403, AcquisitionAccessBlockedError),
        (404, AcquisitionNotFoundError),
    ],
)
def test_expected_http_failures_are_mapped(
    tmp_path,
    monkeypatch,
    status_code,
    error_type,
):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(status_code, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error_type):
            transport.retrieve_to_temp(
                "https://example.org/paper.pdf",
                output_dir=tmp_path,
                client=client,
            )


def test_declared_oversized_response_is_rejected(tmp_path, monkeypatch):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(
            200,
            headers={"Content-Length": "1000"},
            content=b"small",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AcquisitionTooLargeError):
            transport.retrieve_to_temp(
                "https://example.org/paper.pdf",
                output_dir=tmp_path,
                max_bytes=100,
                client=client,
            )


def test_actual_oversized_response_is_rejected_and_temp_is_cleaned(
    tmp_path,
    monkeypatch,
):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(200, content=b"x" * 101, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AcquisitionTooLargeError):
            transport.retrieve_to_temp(
                "https://example.org/paper.pdf",
                output_dir=tmp_path,
                max_bytes=100,
                client=client,
            )

    assert list(tmp_path.glob("*.part")) == []


def test_redirect_without_location_is_rejected(tmp_path, monkeypatch):
    _unsafe_checks_off(monkeypatch)

    def handler(request):
        return httpx.Response(302, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AcquisitionRedirectError):
            transport.retrieve_to_temp(
                "https://example.org/paper.pdf",
                output_dir=tmp_path,
                client=client,
            )
