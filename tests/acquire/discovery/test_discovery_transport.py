import httpx
import pytest

import aletheia_nexus.acquire.discovery.transport as transport_module
from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryNetworkError,
    DiscoveryNotFoundError,
    DiscoveryParseError,
    DiscoveryRateLimitError,
    DiscoveryRequestError,
    DiscoveryServiceError,
)
from aletheia_nexus.acquire.discovery.transport import build_user_agent, get_json


def test_build_user_agent_uses_installed_package_identity():
    user_agent = build_user_agent()

    assert user_agent.startswith("Aletheia-Nexus/")


def test_get_json_success(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(200, json={"hello": "world"})

    monkeypatch.setattr(transport_module.httpx, "get", fake_get)

    result = get_json(
        "https://example.com/api",
        context="test request",
        params={"q": "value"},
    )

    assert result == {"hello": "world"}
    assert captured["url"] == "https://example.com/api"
    assert captured["params"] == {"q": "value"}
    assert captured["follow_redirects"] is True
    assert captured["headers"]["User-Agent"].startswith("Aletheia-Nexus/")


@pytest.mark.parametrize(
    ("status_code", "expected_exception"),
    [
        (404, DiscoveryNotFoundError),
        (429, DiscoveryRateLimitError),
        (400, DiscoveryRequestError),
        (403, DiscoveryRequestError),
        (500, DiscoveryServiceError),
        (503, DiscoveryServiceError),
        (302, DiscoveryServiceError),
    ],
)
def test_get_json_maps_http_errors(monkeypatch, status_code, expected_exception):
    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(status_code),
    )

    with pytest.raises(expected_exception):
        get_json("https://example.com/api", context="test request")


@pytest.mark.parametrize(
    "network_exception",
    [
        httpx.TimeoutException(
            "Timed out",
            request=httpx.Request("GET", "https://example.com"),
        ),
        httpx.ConnectError(
            "Connection failed",
            request=httpx.Request("GET", "https://example.com"),
        ),
    ],
)
def test_get_json_maps_network_errors(monkeypatch, network_exception):
    def fake_get(*args, **kwargs):
        raise network_exception

    monkeypatch.setattr(transport_module.httpx, "get", fake_get)

    with pytest.raises(DiscoveryNetworkError):
        get_json("https://example.com/api", context="test request")


def test_get_json_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(200, content=b"not valid json"),
    )

    with pytest.raises(DiscoveryParseError):
        get_json("https://example.com/api", context="test request")


def test_get_json_rejects_non_object_json(monkeypatch):
    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(200, json=["unexpected"]),
    )

    with pytest.raises(DiscoveryParseError):
        get_json("https://example.com/api", context="test request")
