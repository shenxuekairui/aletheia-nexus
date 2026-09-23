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
    """Internal wrapper preserving the final discovery error and runtime data."""

    def __init__(
        self,
        error: DiscoveryError,
        attempts: int,
        elapsed_seconds: float,
    ) -> None:
        super().__init__(str(error))
        self.error = error
        self.attempts = attempts
        self.elapsed_seconds = elapsed_seconds


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
) -> tuple[T, int, float]:
    """Run one provider call with bounded exponential-backoff retries.

    Elapsed time covers the full provider operation, including retries and
    backoff waits. Unknown programming errors are intentionally not swallowed.
    """

    validate_retry_config(max_attempts, backoff_base)
    started_at = time.perf_counter()

    for attempt in range(1, max_attempts + 1):
        try:
            value = call()
            return value, attempt, time.perf_counter() - started_at
        except DiscoveryError as exc:
            should_retry = isinstance(exc, RETRYABLE_ERRORS) and attempt < max_attempts

            if not should_retry:
                raise RetryCallError(
                    exc,
                    attempt,
                    time.perf_counter() - started_at,
                ) from exc

            delay = backoff_base * 2 ** (attempt - 1)
            time.sleep(delay)

    raise RuntimeError("Retry loop ended unexpectedly")
