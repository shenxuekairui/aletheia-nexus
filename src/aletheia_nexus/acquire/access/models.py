from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import AcquisitionResult
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    MultiRouteAcquisitionResult,
)


class ChallengeKind(StrEnum):
    """Access challenge observed in a real browser session."""

    NONE = "NONE"
    BOT_CHALLENGE = "BOT_CHALLENGE"
    CAPTCHA = "CAPTCHA"
    AUTHENTICATION = "AUTHENTICATION"
    SSO = "SSO"
    MFA = "MFA"
    ENTITLEMENT = "ENTITLEMENT"
    ACCESS_DENIED = "ACCESS_DENIED"
    UNKNOWN = "UNKNOWN"


class BrowserAttemptStatus(StrEnum):
    """Outcome for one browser-backed access attempt."""

    VERIFIED = "VERIFIED"
    RETRIEVED_UNVERIFIED = "RETRIEVED_UNVERIFIED"
    NO_FILE_CANDIDATES = "NO_FILE_CANDIDATES"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    UNSAFE_URL = "UNSAFE_URL"
    PAGE_MISMATCH = "PAGE_MISMATCH"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    NAVIGATION_ERROR = "NAVIGATION_ERROR"
    ERROR = "ERROR"


class ElsevierAccessStatus(StrEnum):
    """Outcome for the official ScienceDirect Article Retrieval API."""

    VERIFIED = "VERIFIED"
    RETRIEVED_UNVERIFIED = "RETRIEVED_UNVERIFIED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_ERROR = "SERVICE_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    ERROR = "ERROR"


class MaximizedAcquisitionStatus(StrEnum):
    """Stable DOI-level outcome after public and authenticated access paths."""

    VERIFIED = "VERIFIED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    UNSAFE_URL = "UNSAFE_URL"
    EXHAUSTED = "EXHAUSTED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ChallengeReport:
    """Conservative classification of an access/authentication challenge."""

    kind: ChallengeKind
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ElsevierAccessConfig:
    """Credentials and limits for Elsevier's official Article Retrieval API."""

    api_key: str = field(repr=False)
    inst_token: str | None = field(default=None, repr=False)
    bearer_token: str | None = field(default=None, repr=False)
    timeout: float = 30.0
    max_bytes: int = 100 * 1024 * 1024
    max_redirects: int = 5
    allow_author_manuscript_fallback: bool = True
    keep_unverified: bool = False

    @classmethod
    def from_env(cls) -> "ElsevierAccessConfig | None":
        import os

        api_key = (os.getenv("ELSEVIER_API_KEY") or "").strip()
        if not api_key:
            return None

        inst_token = (os.getenv("ELSEVIER_INST_TOKEN") or "").strip() or None
        bearer_token = (os.getenv("ELSEVIER_BEARER_TOKEN") or "").strip() or None
        return cls(
            api_key=api_key,
            inst_token=inst_token,
            bearer_token=bearer_token,
        )


@dataclass(frozen=True, slots=True)
class BrowserAccessConfig:
    """Configuration for the persistent authenticated browser capability.

    Browser profiles live outside the repository by default and may contain
    sensitive authenticated session state. Aletheia Nexus never logs cookies,
    credentials, local storage values, or authentication tokens.
    """

    profile_name: str = "default"
    profile_root: Path | None = None
    headless: bool = False
    channel: str | None = None
    cdp_endpoint: str | None = None
    cdp_resume_existing_page: bool = True
    interactive: bool = True
    wait_for_interaction: bool = False
    interaction_callback: Callable[[ChallengeReport, str], None] | None = None
    navigation_timeout: float = 45.0
    request_timeout: float = 45.0
    auto_challenge_grace: float = 8.0
    interaction_timeout: float = 180.0
    poll_interval: float = 1.0
    max_source_routes: int = 12
    max_pdf_candidates: int = 12
    max_request_redirects: int = 10
    max_bytes: int = 100 * 1024 * 1024
    keep_unverified: bool = False


@dataclass(frozen=True, slots=True)
class ElsevierAccessAttempt:
    """One official Elsevier full-text API attempt."""

    status: ElsevierAccessStatus
    result: AcquisitionResult | None = None
    http_status: int | None = None
    credential_modes: tuple[str, ...] = ()
    error: str | None = None
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class BrowserFileAttempt:
    """One browser-authenticated concrete-file retrieval and validation."""

    candidate: FullTextCandidate
    result: AcquisitionResult | None = None
    source_page_url: str | None = None
    method: str = "context_request"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserAccessAttempt:
    """One browser-backed route attempt with complete access provenance."""

    source_candidate: FullTextCandidate
    final_url: str | None
    status: BrowserAttemptStatus
    challenge_history: tuple[ChallengeReport, ...] = ()
    file_attempts: tuple[BrowserFileAttempt, ...] = ()
    candidates_considered: int = 0
    interaction_used: bool = False
    evidence: tuple[str, ...] = ()
    error: str | None = None
    elapsed_seconds: float = 0.0

    @property
    def source_url(self) -> str:
        return self.source_candidate.url

    @property
    def result(self) -> AcquisitionResult | None:
        for attempt in reversed(self.file_attempts):
            if attempt.result is not None:
                return attempt.result
        return None


@dataclass(frozen=True, slots=True)
class BrowserRecoveryResult:
    """Result of one persistent-browser recovery pass across multiple routes."""

    doi: str
    attempts: tuple[BrowserAccessAttempt, ...] = ()
    verified_result: AcquisitionResult | None = None
    profile_dir: Path | None = None
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class MaximizedAcquisitionResult:
    """Complete v0.6 trace across v0.5 and authenticated browser recovery."""

    doi: str
    status: MaximizedAcquisitionStatus
    base_result: MultiRouteAcquisitionResult
    browser_attempts: tuple[BrowserAccessAttempt, ...] = ()
    elsevier_attempt: ElsevierAccessAttempt | None = None
    verified_result: AcquisitionResult | None = None
    elapsed_seconds: float = 0.0
    message: str | None = None

    @property
    def verified_path(self) -> Path | None:
        if self.verified_result is None:
            return None
        return self.verified_result.file_path
