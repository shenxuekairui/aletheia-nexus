import math
import time
from collections.abc import Callable
from typing import TypeVar

from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryError,
    DiscoveryNetworkError,
    DiscoveryRateLimitError,
    DiscoveryServiceError,
)

T = TypeVar("T")

RETRYABLE_ERRORS = (
    DiscoveryNetworkError,
    DiscoveryRateLimitError,
    DiscoveryServiceError,
)


class RetryCallError(RuntimeError):
    """Internal wrapper preserving the final discovery error and attempt count."""

    def __init__(self, error: DiscoveryError, attempts: int) -> None:
        super().__init__(str(error))
        self.error = error
        self.attempts = attempts


def validate_retry_config(max_attempts: int, backoff_base: float) -> None:
    """Validate retry configuration before any provider call is made."""

    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise TypeError("max_attempts must be an integer")

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    if isinstance(backoff_base, bool) or not isinstance(backoff_base, (int, float)):
        raise TypeError("backoff_base must be a number")

    if not math.isfinite(backoff_base) or backoff_base < 0:
        raise ValueError("backoff_base must be finite and non-negative")


def call_with_retry(
    call: Callable[[], T],
    *,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> tuple[T, int]:
    """Run one provider call with bounded exponential-backoff retries.

    Only temporary transport/service failures are retried. Known permanent
    discovery errors are returned immediately through RetryCallError. Unknown
    programming errors are intentionally not swallowed.
    """

    validate_retry_config(max_attempts, backoff_base)

    for attempt in range(1, max_attempts + 1):
        try:
            return call(), attempt
        except DiscoveryError as exc:
            should_retry = isinstance(exc, RETRYABLE_ERRORS) and attempt < max_attempts

            if not should_retry:
                raise RetryCallError(exc, attempt) from exc

            delay = backoff_base * 2 ** (attempt - 1)
            time.sleep(delay)

    raise RuntimeError("Retry loop ended unexpectedly")
