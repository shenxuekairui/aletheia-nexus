"""Authenticated/browser access and acquisition-maximization capability."""

from aletheia_nexus.acquire.access.browser import (
    BrowserCapabilityUnavailable,
    BrowserSession,
    acquire_with_browser,
    browser_profile_dir,
)
from aletheia_nexus.acquire.access.challenge import classify_access_challenge
from aletheia_nexus.acquire.access.elsevier import acquire_elsevier_pdf
from aletheia_nexus.acquire.access.elsevier import acquire_elsevier_pdf
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    BrowserRecoveryResult,
    ElsevierAccessAttempt,
    ElsevierAccessConfig,
    ElsevierAccessStatus,
    ChallengeKind,
    ElsevierAccessAttempt,
    ElsevierAccessConfig,
    ElsevierAccessStatus,
    ChallengeReport,
    MaximizedAcquisitionResult,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.access.service import (
    acquire_full_text_maximized,
    browser_recovery_routes,
)

__all__ = [
    "BrowserAccessAttempt",
    "BrowserAccessConfig",
    "BrowserAttemptStatus",
    "BrowserCapabilityUnavailable",
    "BrowserFileAttempt",
    "BrowserRecoveryResult",
    "BrowserSession",
    "ElsevierAccessAttempt",
    "ElsevierAccessConfig",
    "ElsevierAccessStatus",
    "ChallengeKind",
    "ChallengeReport",
    "ElsevierAccessAttempt",
    "ElsevierAccessConfig",
    "ElsevierAccessStatus",
    "MaximizedAcquisitionResult",
    "MaximizedAcquisitionStatus",
    "acquire_elsevier_pdf",
    "acquire_elsevier_pdf",
    "acquire_full_text_maximized",
    "acquire_with_browser",
    "browser_profile_dir",
    "browser_recovery_routes",
    "classify_access_challenge",
]
