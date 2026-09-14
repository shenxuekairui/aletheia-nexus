from dataclasses import dataclass
from enum import StrEnum


class DiscoveryProvider(StrEnum):
    """External source that discovered a full-text candidate."""

    OPENALEX = "openalex"
    UNPAYWALL = "unpaywall"


class CandidateUrlType(StrEnum):
    """Provider-reported kind of candidate route, not verified file content."""

    PDF = "pdf"
    LANDING_PAGE = "landing_page"
    UNKNOWN = "unknown"


class AccessType(StrEnum):
    """Known access mode reported for a candidate."""

    OPEN_ACCESS = "open_access"
    UNKNOWN = "unknown"


class FullTextVersion(StrEnum):
    """Provider-reported scholarly version represented by a candidate."""

    PUBLISHED = "published"
    ACCEPTED = "accepted"
    SUBMITTED = "submitted"
    UNKNOWN = "unknown"


class HostType(StrEnum):
    """Kind of access host or route represented by a candidate URL."""

    PUBLISHER = "publisher"
    REPOSITORY = "repository"
    INDEX = "index"
    RESOLVER = "resolver"
    UNKNOWN = "unknown"


class ProviderDiscoveryStatus(StrEnum):
    """Stable per-provider discovery outcome."""

    SUCCESS = "SUCCESS"
    NO_CANDIDATES = "NO_CANDIDATES"
    NOT_FOUND = "NOT_FOUND"
    SKIPPED = "SKIPPED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    REQUEST_ERROR = "REQUEST_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_ERROR = "SERVICE_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class FullTextCandidate:
    """Normalized possible route to scholarly full text.

    Discovery records what providers report. ``url_type`` and ``version`` are
    therefore candidate metadata rather than verified file facts. Actual PDF
    validation and file identity checking belong to Acquisition.
    """

    doi: str
    url: str
    provenance: tuple[DiscoveryProvider, ...]
    url_type: CandidateUrlType = CandidateUrlType.UNKNOWN
    access_type: AccessType = AccessType.UNKNOWN
    version: FullTextVersion = FullTextVersion.UNKNOWN
    host_type: HostType = HostType.UNKNOWN
    license: str | None = None
    source_name: str | None = None
    is_best: bool = False


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryResult:
    """Outcome from one discovery provider, including runtime metadata."""

    provider: DiscoveryProvider
    status: ProviderDiscoveryStatus
    candidates: tuple[FullTextCandidate, ...]
    error: str | None = None
    attempts: int = 0
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Aggregated full-text discovery result for one DOI."""

    doi: str
    candidates: tuple[FullTextCandidate, ...]
    providers: tuple[ProviderDiscoveryResult, ...]
    elapsed_seconds: float = 0.0
