"""Full-text candidate discovery for Aletheia Nexus."""

from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryConfigurationError,
    DiscoveryError,
    DiscoveryNetworkError,
    DiscoveryNotFoundError,
    DiscoveryParseError,
    DiscoveryRequestError,
    DiscoveryServiceError,
    DiscoveryRateLimitError,
)
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    FullTextVersion,
    HostType,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.openalex import discover_openalex
from aletheia_nexus.acquire.discovery.service import discover_full_text
from aletheia_nexus.acquire.discovery.unpaywall import discover_unpaywall

__all__ = [
    "AccessType",
    "CandidateUrlType",
    "DiscoveryConfigurationError",
    "DiscoveryError",
    "DiscoveryNetworkError",
    "DiscoveryNotFoundError",
    "DiscoveryParseError",
    "DiscoveryProvider",
    "DiscoveryRateLimitError",
    "DiscoveryRequestError",
    "DiscoveryResult",
    "DiscoveryServiceError",
    "FullTextCandidate",
    "FullTextVersion",
    "HostType",
    "ProviderDiscoveryResult",
    "ProviderDiscoveryStatus",
    "discover_full_text",
    "discover_openalex",
    "discover_unpaywall",
]
