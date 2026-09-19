"""Authenticated/browser access and acquisition-maximization capability."""

from aletheia_nexus.acquire.access.browser import (
    BrowserCapabilityUnavailable,
    BrowserSession,
    acquire_with_browser,
    browser_profile_dir,
)
from aletheia_nexus.acquire.access.challenge import classify_access_challenge
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    BrowserRecoveryResult,
    ChallengeKind,
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
    "ChallengeKind",
    "ChallengeReport",
    "MaximizedAcquisitionResult",
    "MaximizedAcquisitionStatus",
    "acquire_full_text_maximized",
    "acquire_with_browser",
    "browser_profile_dir",
    "browser_recovery_routes",
    "classify_access_challenge",
]
