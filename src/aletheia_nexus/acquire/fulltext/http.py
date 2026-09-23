from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version

from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionAccessBlockedError,
    AcquisitionAuthRequiredError,
    AcquisitionNotFoundError,
    AcquisitionRateLimitError,
    AcquisitionRequestError,
    AcquisitionServiceError,
)

PACKAGE_NAME = "aletheia-nexus"
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@lru_cache(maxsize=1)
def _package_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "dev"


def build_user_agent() -> str:
    """Return the stable User-Agent shared by full-text HTTP transports."""

    return f"Aletheia-Nexus/{_package_version()}"


def validate_http_limits(
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int,
) -> None:
    """Validate common bounded-HTTP transport settings."""

    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("timeout must be a positive number")
    if (
        not isinstance(max_redirects, int)
        or isinstance(max_redirects, bool)
        or max_redirects < 0
    ):
        raise ValueError("max_redirects must be a non-negative integer")


def raise_for_http_status(status_code: int, context: str) -> None:
    """Map one terminal HTTP status to the stable acquisition error taxonomy."""

    if status_code == 401:
        raise AcquisitionAuthRequiredError(
            f"Authorization is required while requesting {context}"
        )
    if status_code == 403:
        raise AcquisitionAccessBlockedError(
            f"Access was blocked while requesting {context}"
        )
    if status_code == 404:
        raise AcquisitionNotFoundError(f"Resource not found while requesting {context}")
    if status_code == 429:
        raise AcquisitionRateLimitError(
            f"Rate limit exceeded while requesting {context}"
        )
    if 400 <= status_code < 500:
        raise AcquisitionRequestError(
            f"Request failed with HTTP {status_code} while requesting {context}"
        )
    if 500 <= status_code < 600:
        raise AcquisitionServiceError(
            f"Remote service returned HTTP {status_code} while requesting {context}"
        )
    if not 200 <= status_code < 300:
        raise AcquisitionServiceError(
            f"Unexpected HTTP {status_code} while requesting {context}"
        )
