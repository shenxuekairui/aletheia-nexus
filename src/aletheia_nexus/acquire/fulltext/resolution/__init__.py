"""Route resolution for landing pages and other non-file full-text routes."""

from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    DerivedFullTextCandidate,
    PageIdentityReport,
    PageType,
    ResolutionStatus,
    RetrievedPage,
    RouteResolutionResult,
)
from aletheia_nexus.acquire.fulltext.resolution.service import resolve_full_text_route

__all__ = [
    "DerivationMethod",
    "DerivedFullTextCandidate",
    "PageIdentityReport",
    "PageType",
    "ResolutionStatus",
    "RetrievedPage",
    "RouteResolutionResult",
    "resolve_full_text_route",
]
