from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

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
    PAGE_MISMATCH = "PAGE_MISMATCH"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    NAVIGATION_ERROR = "NAVIGATION_ERROR"
    ERROR = "ERROR"


class MaximizedAcquisitionStatus(StrEnum):
    """Stable DOI-level outcome after public and authenticated access paths."""

    VERIFIED = "VERIFIED"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    EXHAUSTED = "EXHAUSTED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ChallengeReport:
    """Conservative classification of an access/authentication challenge."""

    kind: ChallengeKind
    evidence: tuple[str, ...] = ()


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
    interactive: bool = True
    navigation_timeout: float = 45.0
    request_timeout: float = 45.0
    auto_challenge_grace: float = 8.0
    interaction_timeout: float = 180.0
    poll_interval: float = 1.0
    max_pdf_candidates: int = 12
    max_bytes: int = 100 * 1024 * 1024
    keep_unverified: bool = False


@dataclass(frozen=True, slots=True)
class BrowserAccessAttempt:
    """One browser-backed attempt with challenge and validation provenance."""

    source_url: str
    final_url: str | None
    status: BrowserAttemptStatus
    challenge: ChallengeReport | None = None
    result: AcquisitionResult | None = None
    candidates_considered: int = 0
    evidence: tuple[str, ...] = ()
    error: str | None = None
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class MaximizedAcquisitionResult:
    """Complete v0.6 trace across v0.5 and authenticated browser recovery."""

    doi: str
    status: MaximizedAcquisitionStatus
    base_result: MultiRouteAcquisitionResult
    browser_attempts: tuple[BrowserAccessAttempt, ...] = ()
    verified_result: AcquisitionResult | None = None
    elapsed_seconds: float = 0.0
    message: str | None = None

    @property
    def verified_path(self) -> Path | None:
        if self.verified_result is None:
            return None
        return self.verified_result.file_path
