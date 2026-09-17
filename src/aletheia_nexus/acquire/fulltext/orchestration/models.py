from dataclasses import dataclass
from enum import StrEnum

from aletheia_nexus.acquire.discovery.models import DiscoveryResult, FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    DocumentRole,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    RouteResolutionResult,
)
from aletheia_nexus.core.models import PaperMetadata


class FullTextAcquisitionStatus(StrEnum):
    """Stable final outcome for DOI-level multi-route acquisition."""

    VERIFIED = "VERIFIED"
    NO_CANDIDATES = "NO_CANDIDATES"
    DISCOVERY_FAILED = "DISCOVERY_FAILED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"
    EXHAUSTED = "EXHAUSTED"
    LIMIT_REACHED = "LIMIT_REACHED"


class TitleSource(StrEnum):
    """Where the title used for identity fallback came from."""

    USER = "USER"
    METADATA = "METADATA"
    NONE = "NONE"


class FileCandidateOrigin(StrEnum):
    """Whether a concrete file candidate came from Discovery or Route Resolution."""

    DISCOVERY = "DISCOVERY"
    DERIVED = "DERIVED"


class RouteCandidateOrigin(StrEnum):
    """Why a route was sent to v0.5.1 Route Resolution."""

    DISCOVERY = "DISCOVERY"
    PAGE_EXPANSION = "PAGE_EXPANSION"
    URL_TRANSFORM = "URL_TRANSFORM"
    PDF_TRANSFORM = "PDF_TRANSFORM"
    INVALID_PDF_FALLBACK = "INVALID_PDF_FALLBACK"
    DOI_RESOLVER_FALLBACK = "DOI_RESOLVER_FALLBACK"


@dataclass(frozen=True, slots=True)
class RouteAttempt:
    """One invocation of v0.5.1 Route Resolution."""

    candidate: FullTextCandidate
    origin: RouteCandidateOrigin
    result: RouteResolutionResult
    depth: int = 0
    parent_url: str | None = None
    expansion_method: str | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FileAttempt:
    """One invocation of v0.5.0 Direct PDF Acquisition."""

    candidate: FullTextCandidate
    origin: FileCandidateOrigin
    result: AcquisitionResult
    parent_url: str | None = None
    derivation_method: DerivationMethod | None = None
    role_hint: DocumentRole = DocumentRole.UNKNOWN
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MultiRouteAcquisitionResult:
    """Complete DOI-level acquisition trace across discovery, routes, and files."""

    doi: str
    status: FullTextAcquisitionStatus
    discovery: DiscoveryResult
    route_attempts: tuple[RouteAttempt, ...] = ()
    file_attempts: tuple[FileAttempt, ...] = ()
    verified_result: AcquisitionResult | None = None
    metadata: PaperMetadata | None = None
    metadata_error: str | None = None
    expected_title: str | None = None
    title_source: TitleSource = TitleSource.NONE
    duplicate_file_candidates_skipped: int = 0
    duplicate_route_candidates_skipped: int = 0
    supplement_candidates_skipped: int = 0
    page_route_attempts: int = 0
    route_expansions_enqueued: int = 0
    max_route_depth_reached: int = 0
    elapsed_seconds: float = 0.0
    message: str | None = None
