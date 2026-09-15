from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aletheia_nexus.acquire.discovery.models import FullTextCandidate


class AcquisitionStatus(StrEnum):
    """Stable outcome for one direct-PDF acquisition attempt."""

    VERIFIED = "VERIFIED"
    RETRIEVED_UNVERIFIED = "RETRIEVED_UNVERIFIED"
    SUPPLEMENT = "SUPPLEMENT"
    MISMATCH = "MISMATCH"
    INVALID_PDF = "INVALID_PDF"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    NOT_FOUND = "NOT_FOUND"
    TOO_LARGE = "TOO_LARGE"
    UNSAFE_URL = "UNSAFE_URL"
    REDIRECT_ERROR = "REDIRECT_ERROR"
    REQUEST_ERROR = "REQUEST_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_ERROR = "SERVICE_ERROR"
    ERROR = "ERROR"


class IdentityStatus(StrEnum):
    """How strongly a retrieved PDF matches the requested paper."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class DocumentRole(StrEnum):
    """Role of a retrieved scholarly document."""

    ARTICLE = "ARTICLE"
    SUPPLEMENT = "SUPPLEMENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RedirectHop:
    """One manually validated HTTP redirect."""

    from_url: str
    status_code: int
    location: str
    to_url: str


@dataclass(frozen=True, slots=True)
class RetrievedResource:
    """Bytes retrieved from one candidate URL before scholarly validation.

    ``local_path`` is populated only while the bytes are retained locally. It
    becomes ``None`` after an unverified or invalid temporary file is deleted.
    """

    requested_url: str
    final_url: str
    http_status: int
    content_type: str | None
    size_bytes: int
    sha256: str
    local_path: Path | None
    redirects: tuple[RedirectHop, ...] = ()
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class PdfValidationReport:
    """Structural PDF validation independent of paper identity."""

    valid_pdf: bool
    magic_bytes_ok: bool
    parseable: bool
    page_count: int | None
    encrypted: bool
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityValidationReport:
    """Evidence that a valid PDF represents the requested article."""

    status: IdentityStatus
    document_role: DocumentRole
    doi_match: bool
    title_similarity: float | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """Final result for one direct PDF candidate."""

    candidate: FullTextCandidate
    status: AcquisitionStatus
    retrieved: RetrievedResource | None = None
    pdf_validation: PdfValidationReport | None = None
    identity_validation: IdentityValidationReport | None = None
    file_path: Path | None = None
    sidecar_path: Path | None = None
    error: str | None = None
    attempts: int = 0
    elapsed_seconds: float = 0.0
