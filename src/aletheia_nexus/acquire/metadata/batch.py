import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
    UnsupportedAgencyError,
)
from aletheia_nexus.acquire.metadata.retry import (
    get_metadata_with_retry,
    validate_retry_config,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata


class MetadataStatus(StrEnum):
    """Status of one metadata lookup."""

    SUCCESS = "SUCCESS"
    INVALID_DOI = "INVALID_DOI"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED_AGENCY = "UNSUPPORTED_AGENCY"
    REQUEST_ERROR = "REQUEST_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_ERROR = "SERVICE_ERROR"
    PARSE_ERROR = "PARSE_ERROR"


@dataclass(frozen=True)
class MetadataLookupResult:
    """Result of one metadata lookup, including end-to-end item runtime."""

    input_value: object
    doi: str | None
    status: MetadataStatus
    metadata: PaperMetadata | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0


def get_metadata_batch(
    values: Iterable[object],
    *,
    mailto: str | None = None,
    deduplicate: bool = True,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> list[MetadataLookupResult]:
    """Retrieve metadata for multiple DOI inputs."""

    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TypeError("get_metadata_batch() expects an iterable of DOI values")

    if not isinstance(deduplicate, bool):
        raise TypeError("deduplicate must be a boolean")

    validate_retry_config(
        max_attempts,
        backoff_base,
    )

    results: list[MetadataLookupResult] = []
    seen: set[str] = set()

    for value in values:
        item_started_at = time.perf_counter()

        try:
            doi = normalize_doi(value)

        except (TypeError, ValueError) as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=None,
                    status=MetadataStatus.INVALID_DOI,
                    error=str(exc),
                    elapsed_seconds=time.perf_counter() - item_started_at,
                )
            )
            continue

        if deduplicate and doi in seen:
            continue

        seen.add(doi)

        try:
            metadata = get_metadata_with_retry(
                doi,
                mailto=mailto,
                max_attempts=max_attempts,
                backoff_base=backoff_base,
            )

        except MetadataNotFoundError as exc:
            status = MetadataStatus.NOT_FOUND
            error = str(exc)

        except UnsupportedAgencyError as exc:
            status = MetadataStatus.UNSUPPORTED_AGENCY
            error = str(exc)

        except MetadataRequestError as exc:
            status = MetadataStatus.REQUEST_ERROR
            error = str(exc)

        except MetadataNetworkError as exc:
            status = MetadataStatus.NETWORK_ERROR
            error = str(exc)

        except RateLimitError as exc:
            status = MetadataStatus.RATE_LIMITED
            error = str(exc)

        except MetadataServiceError as exc:
            status = MetadataStatus.SERVICE_ERROR
            error = str(exc)

        except MetadataParseError as exc:
            status = MetadataStatus.PARSE_ERROR
            error = str(exc)

        else:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.SUCCESS,
                    metadata=metadata,
                    elapsed_seconds=time.perf_counter() - item_started_at,
                )
            )
            continue

        results.append(
            MetadataLookupResult(
                input_value=value,
                doi=doi,
                status=status,
                error=error,
                elapsed_seconds=time.perf_counter() - item_started_at,
            )
        )

    return results
