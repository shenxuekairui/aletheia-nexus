import socket

import pytest

from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionNetworkError,
    AcquisitionUnsafeUrlError,
)
from aletheia_nexus.acquire.fulltext.safety import validate_safe_url


def _public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def test_public_url_is_allowed_and_normalized(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    assert validate_safe_url("HTTPS://Example.COM/paper.pdf#page=1") == (
        "https://example.com/paper.pdf"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/paper.pdf",
        "http://127.0.0.1/paper.pdf",
        "http://192.168.1.2/paper.pdf",
        "http://169.254.1.2/paper.pdf",
        "http://[::1]/paper.pdf",
    ],
)
def test_local_and_private_targets_are_rejected(url):
    with pytest.raises(AcquisitionUnsafeUrlError):
        validate_safe_url(url)


def test_hostname_resolving_to_private_ip_is_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))
        ],
    )
    with pytest.raises(AcquisitionUnsafeUrlError):
        validate_safe_url("https://publisher.example/paper.pdf")


def test_dns_failure_is_network_error(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(AcquisitionNetworkError):
        validate_safe_url("https://publisher.example/paper.pdf")
