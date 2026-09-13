import httpx
import pytest

import aletheia_nexus.acquire.metadata.transport as transport_module
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
)
from aletheia_nexus.acquire.metadata.transport import (
    build_user_agent,
    get_json,
)


def test_build_user_agent():
    user_agent = build_user_agent("test@example.com")

    assert user_agent.startswith("Aletheia-Nexus/")
    assert "test@example.com" in user_agent


def test_get_json_success(
    monkeypatch,
):
    captured = {}

    def fake_get(
        url,
        **kwargs,
    ):
        captured["url"] = url
        captured.update(kwargs)

        return httpx.Response(
            200,
            json={
                "hello": "world",
            },
        )

    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        fake_get,
    )

    result = get_json(
        "https://example.com/api",
        context="test request",
        params={
            "q": "value",
        },
        mailto="test@example.com",
    )

    assert result == {
        "hello": "world",
    }

    assert captured["url"] == "https://example.com/api"

    assert captured["params"] == {
        "q": "value",
    }

    assert captured["follow_redirects"] is True

    assert "test@example.com" in captured["headers"]["User-Agent"]


@pytest.mark.parametrize(
    (
        "status_code",
        "expected_exception",
    ),
    [
        (
            404,
            MetadataNotFoundError,
        ),
        (
            429,
            RateLimitError,
        ),
        (
            400,
            MetadataRequestError,
        ),
        (
            403,
            MetadataRequestError,
        ),
        (
            500,
            MetadataServiceError,
        ),
        (
            503,
            MetadataServiceError,
        ),
        (
            302,
            MetadataServiceError,
        ),
    ],
)
def test_get_json_maps_http_errors(
    monkeypatch,
    status_code,
    expected_exception,
):
    def fake_get(
        *args,
        **kwargs,
    ):
        return httpx.Response(status_code)

    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(expected_exception):
        get_json(
            "https://example.com/api",
            context="test request",
        )


@pytest.mark.parametrize(
    "network_exception",
    [
        httpx.TimeoutException(
            "Timed out",
            request=httpx.Request(
                "GET",
                "https://example.com",
            ),
        ),
        httpx.ConnectError(
            "Connection failed",
            request=httpx.Request(
                "GET",
                "https://example.com",
            ),
        ),
    ],
)
def test_get_json_maps_network_errors(
    monkeypatch,
    network_exception,
):
    def fake_get(
        *args,
        **kwargs,
    ):
        raise network_exception

    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataNetworkError):
        get_json(
            "https://example.com/api",
            context="test request",
        )


def test_get_json_rejects_invalid_json(
    monkeypatch,
):
    def fake_get(
        *args,
        **kwargs,
    ):
        return httpx.Response(
            200,
            content=b"not valid json",
        )

    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_json(
            "https://example.com/api",
            context="test request",
        )


def test_get_json_rejects_non_object_json(
    monkeypatch,
):
    def fake_get(
        *args,
        **kwargs,
    ):
        return httpx.Response(
            200,
            json=[
                "unexpected",
            ],
        )

    monkeypatch.setattr(
        transport_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_json(
            "https://example.com/api",
            context="test request",
        )
