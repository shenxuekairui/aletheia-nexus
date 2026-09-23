from dataclasses import dataclass
from enum import StrEnum

from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import (
    DocumentRole,
    IdentityStatus,
    RedirectHop,
)


class ResolutionStatus(StrEnum):
    """Stable outcome for resolving one full-text route."""

    RESOLVED = "RESOLVED"
    NO_FILE_CANDIDATES = "NO_FILE_CANDIDATES"
    PAGE_MISMATCH = "PAGE_MISMATCH"
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
    INVALID_CONTENT = "INVALID_CONTENT"
    ERROR = "ERROR"


class PageType(StrEnum):
    """Best-effort semantic classification of a retrieved route page."""

    ARTICLE = "ARTICLE"
    LOGIN = "LOGIN"
    ACCESS_DENIED = "ACCESS_DENIED"
    CHALLENGE = "CHALLENGE"
    GENERIC = "GENERIC"
    PDF_RESPONSE = "PDF_RESPONSE"
    UNKNOWN = "UNKNOWN"


class DerivationMethod(StrEnum):
    """How Aletheia Nexus derived a more concrete file route."""

    DIRECT_PDF_RESPONSE = "DIRECT_PDF_RESPONSE"
    CITATION_PDF_URL = "CITATION_PDF_URL"
    META_PDF_URL = "META_PDF_URL"
    LINK_PDF = "LINK_PDF"
    JSON_LD_PDF = "JSON_LD_PDF"
    ANCHOR_DOWNLOAD = "ANCHOR_DOWNLOAD"
    EMBEDDED_PDF = "EMBEDDED_PDF"
    PDF_URL_PATTERN = "PDF_URL_PATTERN"
    HTTPS_UPGRADE = "HTTPS_UPGRADE"


@dataclass(frozen=True, slots=True)
class RetrievedPage:
    """Bounded HTTP representation of one page-like route."""

    requested_url: str
    final_url: str
    http_status: int
    content_type: str | None
    text: str | None
    size_bytes: int
    redirects: tuple[RedirectHop, ...] = ()
    elapsed_seconds: float = 0.0
    is_pdf_response: bool = False
    body_truncated: bool = False


@dataclass(frozen=True, slots=True)
class PageIdentityReport:
    """Evidence that a landing page represents the requested paper."""

    status: IdentityStatus
    doi_match: bool
    title_similarity: float | None = None
    metadata_dois: tuple[str, ...] = ()
    metadata_title: str | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DerivedFullTextCandidate:
    """One PDF candidate derived by AN from a parent route with provenance."""

    candidate: FullTextCandidate
    parent_url: str
    source_page_url: str | None
    method: DerivationMethod
    role_hint: DocumentRole = DocumentRole.UNKNOWN
    evidence: tuple[str, ...] = ()
    priority: int = 0


@dataclass(frozen=True, slots=True)
class RouteResolutionResult:
    """Result of resolving one landing/unknown route or safe route transform."""

    source_candidate: FullTextCandidate
    status: ResolutionStatus
    candidates: tuple[DerivedFullTextCandidate, ...] = ()
    page: RetrievedPage | None = None
    page_type: PageType | None = None
    identity: PageIdentityReport | None = None
    error: str | None = None
    attempts: int = 0
    elapsed_seconds: float = 0.0
