class MetadataError(Exception):
    """Base exception for metadata retrieval errors."""


class MetadataNotFoundError(MetadataError):
    """Raised when metadata for a DOI is not found."""


class MetadataNetworkError(MetadataError):
    """Raised when a network problem prevents metadata retrieval."""


class RateLimitError(MetadataError):
    """Raised when the metadata service rate-limits the request."""


class MetadataServiceError(MetadataError):
    """Raised when the metadata service returns an unexpected server-side error."""


class MetadataParseError(MetadataError):
    """Raised when a metadata response cannot be parsed correctly."""


class UnsupportedAgencyError(MetadataError):
    """Raised when a DOI belongs to an unsupported registration agency."""


class MetadataRequestError(MetadataError):
    """Raised when a metadata service rejects the request."""
