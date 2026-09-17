"""DOI-level multi-route full-text acquisition orchestration."""

from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FileAttempt,
    FileCandidateOrigin,
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    RouteAttempt,
    RouteCandidateOrigin,
    TitleSource,
)
from aletheia_nexus.acquire.fulltext.orchestration.service import (
    DEFAULT_MAX_FILE_ATTEMPTS,
    DEFAULT_MAX_ROUTE_ATTEMPTS,
    acquire_from_discovery,
    acquire_full_text,
)

__all__ = [
    "DEFAULT_MAX_FILE_ATTEMPTS",
    "DEFAULT_MAX_ROUTE_ATTEMPTS",
    "FileAttempt",
    "FileCandidateOrigin",
    "FullTextAcquisitionStatus",
    "MultiRouteAcquisitionResult",
    "RouteAttempt",
    "RouteCandidateOrigin",
    "TitleSource",
    "acquire_from_discovery",
    "acquire_full_text",
]
