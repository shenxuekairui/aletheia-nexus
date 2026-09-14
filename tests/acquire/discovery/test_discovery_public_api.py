from aletheia_nexus.acquire.discovery import (
    DiscoveryError,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
    discover_full_text,
    discover_openalex,
    discover_unpaywall,
)


def test_public_discovery_api_is_importable():
    assert callable(discover_full_text)
    assert callable(discover_openalex)
    assert callable(discover_unpaywall)


def test_public_discovery_models_are_exposed():
    assert FullTextCandidate is not None
    assert DiscoveryResult is not None
    assert ProviderDiscoveryResult is not None
    assert DiscoveryProvider.OPENALEX == "openalex"
    assert ProviderDiscoveryStatus.SUCCESS == "SUCCESS"
    assert issubclass(DiscoveryError, RuntimeError)
