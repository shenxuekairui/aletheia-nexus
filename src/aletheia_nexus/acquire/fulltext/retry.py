import math
import time
from collections.abc import Callable
from typing import TypeVar

from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionError,
    AcquisitionNetworkError,
    AcquisitionRateLimitError,
    AcquisitionServiceError,
)

T = TypeVar("T")

_RETRYABLE_ERRORS = (
    AcquisitionNetworkError,
    AcquisitionRateLimitError,
    AcquisitionServiceError,
)


class AcquisitionRetryError(RuntimeError):
    """Internal wrapper preserving final acquisition error and attempt count."""

    def __init__(
        self,
        error: AcquisitionError,
        attempts: int,
        elapsed_seconds: float,
    ) -> None:
        super().__init__(str(error))
        self.error = error
        self.attempts = attempts
        self.elapsed_seconds = elapsed_seconds


def validate_retry_config(max_attempts: int, backoff_base: float) -> None:
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
    max_attempts: int,
    backoff_base: float,
) -> tuple[T, int, float]:
    """Run one acquisition call with bounded exponential backoff."""

    validate_retry_config(max_attempts, backoff_base)
    started_at = time.perf_counter()

    for attempt in range(1, max_attempts + 1):
        try:
            return call(), attempt, time.perf_counter() - started_at
        except AcquisitionError as exc:
            should_retry = isinstance(exc, _RETRYABLE_ERRORS) and attempt < max_attempts
            if not should_retry:
                raise AcquisitionRetryError(
                    exc,
                    attempt,
                    time.perf_counter() - started_at,
                ) from exc
            time.sleep(backoff_base * 2 ** (attempt - 1))

    raise RuntimeError("Acquisition retry loop ended unexpectedly")
