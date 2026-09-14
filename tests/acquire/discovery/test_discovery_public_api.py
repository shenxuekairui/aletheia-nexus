from aletheia_nexus.acquire.discovery import (
    DiscoveryError,
    DiscoveryLookupResult,
    DiscoveryProvider,
    DiscoveryResult,
    DiscoveryStatus,
    FullTextCandidate,
    ProviderContribution,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
    discover_full_text,
    discover_full_text_batch,
    discover_openalex,
    discover_unpaywall,
    summarize_provider_contributions,
)


def test_public_discovery_api_is_importable():
    assert callable(discover_full_text)
    assert callable(discover_full_text_batch)
    assert callable(discover_openalex)
    assert callable(discover_unpaywall)
    assert callable(summarize_provider_contributions)


def test_public_discovery_models_are_exposed():
    assert FullTextCandidate is not None
    assert DiscoveryResult is not None
    assert DiscoveryLookupResult is not None
    assert ProviderContribution is not None
    assert ProviderDiscoveryResult is not None
    assert DiscoveryProvider.OPENALEX == "openalex"
    assert DiscoveryStatus.PARTIAL_SUCCESS == "PARTIAL_SUCCESS"
    assert ProviderDiscoveryStatus.NETWORK_ERROR == "NETWORK_ERROR"
    assert issubclass(DiscoveryError, RuntimeError)
