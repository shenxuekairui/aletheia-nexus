"""Full-text candidate discovery for Aletheia Nexus."""

from aletheia_nexus.acquire.discovery.batch import (
    DiscoveryLookupResult,
    DiscoveryStatus,
    discover_full_text_batch,
)
from aletheia_nexus.acquire.discovery.evaluation import (
    ProviderContribution,
    summarize_provider_contributions,
)
from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryConfigurationError,
    DiscoveryError,
    DiscoveryNetworkError,
    DiscoveryNotFoundError,
    DiscoveryParseError,
    DiscoveryRateLimitError,
    DiscoveryRequestError,
    DiscoveryServiceError,
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
    "DiscoveryLookupResult",
    "DiscoveryNetworkError",
    "DiscoveryNotFoundError",
    "DiscoveryParseError",
    "DiscoveryProvider",
    "DiscoveryRateLimitError",
    "DiscoveryRequestError",
    "DiscoveryResult",
    "DiscoveryServiceError",
    "DiscoveryStatus",
    "FullTextCandidate",
    "FullTextVersion",
    "HostType",
    "ProviderContribution",
    "ProviderDiscoveryResult",
    "ProviderDiscoveryStatus",
    "discover_full_text",
    "discover_full_text_batch",
    "discover_openalex",
    "discover_unpaywall",
    "summarize_provider_contributions",
]
