"""Metadata acquisition and resolution for Aletheia Nexus."""

from aletheia_nexus.acquire.metadata.batch import (
    MetadataLookupResult,
    MetadataStatus,
    get_metadata_batch,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataError,
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
    UnsupportedAgencyError,
)
from aletheia_nexus.acquire.metadata.resolver import (
    DoiAgency,
    get_doi_agency,
    get_metadata,
)
from aletheia_nexus.acquire.metadata.retry import (
    get_metadata_with_retry,
)
from aletheia_nexus.core.models import PaperMetadata

__all__ = [
    "PaperMetadata",
    "MetadataLookupResult",
    "MetadataStatus",
    "DoiAgency",
    "MetadataError",
    "MetadataNetworkError",
    "MetadataNotFoundError",
    "MetadataParseError",
    "MetadataRequestError",
    "MetadataServiceError",
    "RateLimitError",
    "UnsupportedAgencyError",
    "get_doi_agency",
    "get_metadata",
    "get_metadata_with_retry",
    "get_metadata_batch",
]
