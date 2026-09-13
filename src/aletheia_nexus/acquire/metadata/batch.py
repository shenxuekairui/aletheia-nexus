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
    """Result of one metadata lookup."""

    input_value: object
    doi: str | None
    status: MetadataStatus
    metadata: PaperMetadata | None = None
    error: str | None = None


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
        raise TypeError(
            "get_metadata_batch() expects an iterable of DOI values"
        )

    results: list[MetadataLookupResult] = []
    seen: set[str] = set()

    for value in values:
        try:
            doi = normalize_doi(value)
        except (TypeError, ValueError) as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=None,
                    status=MetadataStatus.INVALID_DOI,
                    error=str(exc),
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
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.NOT_FOUND,
                    error=str(exc),
                )
            )

        except UnsupportedAgencyError as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.UNSUPPORTED_AGENCY,
                    error=str(exc),
                )
            )

        except MetadataRequestError as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.REQUEST_ERROR,
                    error=str(exc),
                )
            )

        except MetadataNetworkError as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.NETWORK_ERROR,
                    error=str(exc),
                )
            )

        except RateLimitError as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.RATE_LIMITED,
                    error=str(exc),
                )
            )

        except MetadataServiceError as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.SERVICE_ERROR,
                    error=str(exc),
                )
            )

        except MetadataParseError as exc:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.PARSE_ERROR,
                    error=str(exc),
                )
            )

        else:
            results.append(
                MetadataLookupResult(
                    input_value=value,
                    doi=doi,
                    status=MetadataStatus.SUCCESS,
                    metadata=metadata,
                )
            )

    return results