class AcquisitionError(RuntimeError):
    """Base exception for expected full-text acquisition failures."""


class AcquisitionUnsafeUrlError(AcquisitionError):
    """Candidate URL is unsafe to request automatically."""


class AcquisitionRedirectError(AcquisitionError):
    """Redirect handling failed or exceeded the configured limit."""


class AcquisitionAuthRequiredError(AcquisitionError):
    """The resource explicitly requires user or institutional authorization."""


class AcquisitionAccessBlockedError(AcquisitionError):
    """The server denied access without proving that authentication is required."""


class AcquisitionNotFoundError(AcquisitionError):
    """The requested resource does not exist at this route."""


class AcquisitionTooLargeError(AcquisitionError):
    """The response exceeds the configured download-size limit."""


class AcquisitionRequestError(AcquisitionError):
    """The remote server rejected the request with a permanent client error."""


class AcquisitionNetworkError(AcquisitionError):
    """A network or DNS failure prevented retrieval."""


class AcquisitionRateLimitError(AcquisitionError):
    """The remote service rate-limited the request."""


class AcquisitionServiceError(AcquisitionError):
    """The remote server failed with a transient service error."""
