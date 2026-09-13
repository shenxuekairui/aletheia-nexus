import math
import time

from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataServiceError,
    RateLimitError,
)
from aletheia_nexus.acquire.metadata.resolver import get_metadata
from aletheia_nexus.core.models import PaperMetadata

RETRYABLE_ERRORS = (
    MetadataNetworkError,
    RateLimitError,
    MetadataServiceError,
)


def validate_retry_config(
    max_attempts: int,
    backoff_base: float,
) -> None:
    """Validate retry configuration."""

    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise TypeError("max_attempts must be an integer")

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    if isinstance(backoff_base, bool) or not isinstance(backoff_base, (int, float)):
        raise TypeError("backoff_base must be a number")

    if not math.isfinite(backoff_base) or backoff_base < 0:
        raise ValueError("backoff_base must be finite and non-negative")


def get_metadata_with_retry(
    doi: str,
    *,
    mailto: str | None = None,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> PaperMetadata:
    """Retrieve metadata and retry temporary failures."""

    validate_retry_config(
        max_attempts,
        backoff_base,
    )

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        try:
            return get_metadata(
                doi,
                mailto=mailto,
            )

        except RETRYABLE_ERRORS:
            if attempt == max_attempts:
                raise

            delay = backoff_base * 2 ** (attempt - 1)

            time.sleep(delay)

    raise RuntimeError("Retry loop ended unexpectedly")
