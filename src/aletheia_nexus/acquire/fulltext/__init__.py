"""Direct full-text acquisition and validation for Aletheia Nexus."""

from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionAccessBlockedError,
    AcquisitionAuthRequiredError,
    AcquisitionError,
    AcquisitionNetworkError,
    AcquisitionNotFoundError,
    AcquisitionRateLimitError,
    AcquisitionRedirectError,
    AcquisitionRequestError,
    AcquisitionServiceError,
    AcquisitionTooLargeError,
    AcquisitionUnsafeUrlError,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    DocumentRole,
    IdentityStatus,
    IdentityValidationReport,
    PdfValidationReport,
    RedirectHop,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.service import acquire_direct_pdf

__all__ = [
    "AcquisitionAccessBlockedError",
    "AcquisitionAuthRequiredError",
    "AcquisitionError",
    "AcquisitionNetworkError",
    "AcquisitionNotFoundError",
    "AcquisitionRateLimitError",
    "AcquisitionRedirectError",
    "AcquisitionRequestError",
    "AcquisitionResult",
    "AcquisitionServiceError",
    "AcquisitionStatus",
    "AcquisitionTooLargeError",
    "AcquisitionUnsafeUrlError",
    "DocumentRole",
    "IdentityStatus",
    "IdentityValidationReport",
    "PdfValidationReport",
    "RedirectHop",
    "RetrievedResource",
    "acquire_direct_pdf",
]
