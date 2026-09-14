from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version

import httpx

from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryNetworkError,
    DiscoveryNotFoundError,
    DiscoveryParseError,
    DiscoveryRateLimitError,
    DiscoveryRequestError,
    DiscoveryServiceError,
)

PACKAGE_NAME = "aletheia-nexus"
DEFAULT_TIMEOUT = 10.0


@lru_cache(maxsize=1)
def _package_version() -> str:
    """Return the installed Aletheia Nexus version."""

    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "dev"


def build_user_agent() -> str:
    """Build a consistent discovery User-Agent."""

    return f"Aletheia-Nexus/{_package_version()}"


def get_json(
    url: str,
    *,
    context: str,
    params: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Perform one discovery HTTP GET and return a JSON object."""

    request_headers = dict(headers or {})
    request_headers["User-Agent"] = build_user_agent()

    try:
        response = httpx.get(
            url,
            params=params,
            headers=request_headers,
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.TimeoutException as exc:
        raise DiscoveryNetworkError(f"Timed out while requesting {context}") from exc
    except httpx.RequestError as exc:
        raise DiscoveryNetworkError(
            f"Network error while requesting {context}"
        ) from exc

    status_code = response.status_code

    if status_code == 404:
        raise DiscoveryNotFoundError(f"{context} not found")
    if status_code == 429:
        raise DiscoveryRateLimitError(f"Rate limit exceeded while requesting {context}")
    if 400 <= status_code < 500:
        raise DiscoveryRequestError(f"{context} request failed with HTTP {status_code}")
    if 500 <= status_code < 600:
        raise DiscoveryServiceError(f"{context} service returned HTTP {status_code}")
    if not 200 <= status_code < 300:
        raise DiscoveryServiceError(f"{context} returned unexpected HTTP {status_code}")

    try:
        data = response.json()
    except ValueError as exc:
        raise DiscoveryParseError(f"{context} returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise DiscoveryParseError(f"{context} returned a non-object JSON response")

    return data
