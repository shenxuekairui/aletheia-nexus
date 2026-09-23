import threading

import pytest

import aletheia_nexus.acquire.discovery.retry as retry_module
from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryNetworkError,
    DiscoveryParseError,
)
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.service import discover_full_text


def _candidate() -> FullTextCandidate:
    return FullTextCandidate(
        doi="10.1000/test",
        url="https://example.org/paper.pdf",
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
    )


def test_discover_full_text_isolates_provider_failure(monkeypatch):
    candidate = _candidate()

    def fail_openalex(*args, **kwargs):
        raise DiscoveryNetworkError("OpenAlex unavailable")

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        fail_openalex,
    )
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_unpaywall",
        lambda *args, **kwargs: (candidate,),
    )

    result = discover_full_text(
        "10.1000/test",
        unpaywall_email="person@example.org",
        max_attempts=1,
    )

    assert result.candidates == (candidate,)
    assert result.elapsed_seconds >= 0
    assert result.providers[0].status == ProviderDiscoveryStatus.NETWORK_ERROR
    assert result.providers[0].attempts == 1
    assert result.providers[0].elapsed_seconds >= 0
    assert result.providers[1].status == ProviderDiscoveryStatus.SUCCESS
    assert result.providers[1].attempts == 1
    assert result.providers[1].elapsed_seconds >= 0


def test_discover_full_text_runs_configured_providers_concurrently(monkeypatch):
    barrier = threading.Barrier(2, timeout=3)

    def synchronized_provider(*args, **kwargs):
        barrier.wait()
        return ()

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        synchronized_provider,
    )
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_unpaywall",
        synchronized_provider,
    )

    result = discover_full_text(
        "10.1000/test",
        unpaywall_email="person@example.org",
        max_attempts=1,
    )

    assert [provider.provider for provider in result.providers] == [
        DiscoveryProvider.OPENALEX,
        DiscoveryProvider.UNPAYWALL,
    ]
    assert all(
        provider.status == ProviderDiscoveryStatus.NO_CANDIDATES
        for provider in result.providers
    )


def test_discover_full_text_propagates_programming_error_from_worker(monkeypatch):
    def broken_openalex(*args, **kwargs):
        raise ValueError("programming bug")

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        broken_openalex,
    )
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_unpaywall",
        lambda *args, **kwargs: (),
    )

    with pytest.raises(ValueError, match="programming bug"):
        discover_full_text(
            "10.1000/test",
            unpaywall_email="person@example.org",
            max_attempts=1,
        )


def test_discover_full_text_retries_temporary_provider_failure(monkeypatch):
    calls = 0
    delays = []

    def flaky_openalex(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise DiscoveryNetworkError("temporary failure")
        return ()

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        flaky_openalex,
    )
    monkeypatch.setattr(retry_module.time, "sleep", delays.append)

    result = discover_full_text(
        "10.1000/test",
        max_attempts=3,
        backoff_base=0.25,
    )

    assert calls == 3
    assert delays == [0.25, 0.5]
    assert result.providers[0].status == ProviderDiscoveryStatus.NO_CANDIDATES
    assert result.providers[0].attempts == 3
    assert result.providers[0].elapsed_seconds >= 0


def test_discover_full_text_does_not_retry_parse_failure(monkeypatch):
    calls = 0
    delays = []

    def malformed_openalex(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise DiscoveryParseError("malformed response")

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        malformed_openalex,
    )
    monkeypatch.setattr(retry_module.time, "sleep", delays.append)

    result = discover_full_text(
        "10.1000/test",
        max_attempts=3,
    )

    assert calls == 1
    assert delays == []
    assert result.providers[0].status == ProviderDiscoveryStatus.PARSE_ERROR
    assert result.providers[0].attempts == 1
    assert result.providers[0].elapsed_seconds >= 0


def test_discover_full_text_skips_unpaywall_without_email(monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        lambda *args, **kwargs: (),
    )

    result = discover_full_text("10.1000/test")

    assert result.providers[1].provider == DiscoveryProvider.UNPAYWALL
    assert result.providers[1].status == ProviderDiscoveryStatus.SKIPPED
    assert result.providers[1].attempts == 0
    assert result.providers[1].elapsed_seconds == 0.0


def test_discover_full_text_skips_unpaywall_with_whitespace_email(monkeypatch):
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        lambda *args, **kwargs: (),
    )

    result = discover_full_text("10.1000/test", unpaywall_email="   ")

    assert result.providers[1].provider == DiscoveryProvider.UNPAYWALL
    assert result.providers[1].status == ProviderDiscoveryStatus.SKIPPED


def test_discover_full_text_strips_optional_provider_configuration(monkeypatch):
    received = []

    def fake_openalex(*args, **kwargs):
        received.append(kwargs.get("api_key"))
        return ()

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        fake_openalex,
    )

    discover_full_text(
        "10.1000/test",
        openalex_api_key="  secret-key  ",
    )

    assert received == ["secret-key"]


def test_discover_full_text_rejects_invalid_configuration_before_network(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.service.discover_openalex",
        lambda *args, **kwargs: calls.append(True),
    )

    with pytest.raises(TypeError):
        discover_full_text("10.1000/test", unpaywall_email=123)

    with pytest.raises(TypeError):
        discover_full_text("10.1000/test", openalex_api_key=123)

    with pytest.raises(ValueError):
        discover_full_text("10.1000/test", max_attempts=0)

    assert calls == []
