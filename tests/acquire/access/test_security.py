import pytest

from aletheia_nexus.acquire.access.browser_route import _safe_referer
from aletheia_nexus.acquire.access.security import (
    redact_url_for_record,
    validate_browser_network_url,
)


def test_redact_url_preserves_route_shape_but_not_values():
    value = redact_url_for_record(
        "https://cdn.example/paper.pdf?token=secret&download=true#viewer"
    )
    assert value == (
        "https://cdn.example/paper.pdf?token=%5Bredacted%5D&download=%5Bredacted%5D"
    )
    assert "secret" not in value
    assert "true" not in value
    assert "#viewer" not in value


def test_redact_url_without_query_is_unchanged_except_fragment():
    assert (
        redact_url_for_record("https://publisher.example/article#section")
        == "https://publisher.example/article"
    )


def test_redact_url_accepts_none():
    assert redact_url_for_record(None) is None


def test_redact_url_removes_embedded_userinfo_credentials():
    value = redact_url_for_record(
        "https://user:secret@example.com:8443/paper.pdf?token=abc"
    )
    assert value == ("https://example.com:8443/paper.pdf?token=%5Bredacted%5D")
    assert "user" not in value
    assert "secret" not in value


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/paper.pdf",
        "http://lab.local/paper.pdf",
        "http://127.0.0.1/paper.pdf",
        "http://127.0.0.1./paper.pdf",
        "http://127.1/paper.pdf",
        "http://2130706433/paper.pdf",
        "http://0x7f000001/paper.pdf",
        "http://0177.0.0.1/paper.pdf",
        "http://10.0.0.1/paper.pdf",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/paper.pdf",
    ],
)
def test_browser_network_url_rejects_obvious_local_targets(url):
    with pytest.raises(ValueError):
        validate_browser_network_url(url)


def test_browser_network_url_allows_public_hostname_without_local_dns_dependency():
    assert (
        validate_browser_network_url("https://publisher.example/article?token=abc")
        == "https://publisher.example/article?token=abc"
    )


def test_browser_network_url_rejects_embedded_credentials():
    with pytest.raises(ValueError):
        validate_browser_network_url(
            "https://user:secret@publisher.example/article.pdf"
        )


def test_authenticated_request_referer_strips_same_origin_query_secrets(monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.acquire.access.browser_route.validate_browser_network_url",
        lambda value: value,
    )

    assert (
        _safe_referer(
            "https://publisher.example/article?ticket=secret#viewer",
            "https://publisher.example/article.pdf",
        )
        == "https://publisher.example/article"
    )


def test_authenticated_request_referer_is_origin_only_cross_origin(monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.acquire.access.browser_route.validate_browser_network_url",
        lambda value: value,
    )

    assert (
        _safe_referer(
            "https://publisher.example/article?ticket=secret",
            "https://cdn.example/article.pdf",
        )
        == "https://publisher.example/"
    )


def test_redact_unparseable_url_fails_closed():
    value = redact_url_for_record(
        "https://user:secret@[invalid/paper.pdf?token=super-secret"
    )

    assert value == "[unparseable-url]"
    assert "secret" not in value


def test_browser_network_url_allows_canonical_public_ip():
    assert (
        validate_browser_network_url("https://8.8.8.8/article")
        == "https://8.8.8.8/article"
    )
