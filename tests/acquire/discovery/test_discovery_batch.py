import pytest

import aletheia_nexus.acquire.discovery.batch as batch_module
from aletheia_nexus.acquire.discovery.batch import (
    DiscoveryStatus,
    discover_full_text_batch,
)
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)


def _candidate(doi: str) -> FullTextCandidate:
    return FullTextCandidate(
        doi=doi,
        url=f"https://example.org/{doi}.pdf",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
    )


def _result(
    doi: str,
    *,
    candidates: tuple[FullTextCandidate, ...] = (),
    provider_statuses: tuple[ProviderDiscoveryStatus, ...],
) -> DiscoveryResult:
    providers = tuple(
        ProviderDiscoveryResult(
            provider=(
                DiscoveryProvider.OPENALEX
                if index == 0
                else DiscoveryProvider.UNPAYWALL
            ),
            status=status,
            candidates=(
                candidates if status == ProviderDiscoveryStatus.SUCCESS else ()
            ),
            error=(
                f"{status.value} error"
                if status
                not in {
                    ProviderDiscoveryStatus.SUCCESS,
                    ProviderDiscoveryStatus.NO_CANDIDATES,
                    ProviderDiscoveryStatus.SKIPPED,
                }
                else None
            ),
            attempts=(0 if status == ProviderDiscoveryStatus.SKIPPED else 1),
        )
        for index, status in enumerate(provider_statuses)
    )
    return DiscoveryResult(
        doi=doi,
        candidates=candidates,
        providers=providers,
    )


def test_batch_handles_mixed_inputs_and_preserves_order(monkeypatch):
    def fake_discover(doi, **kwargs):
        if doi == "10.1000/not-found":
            return _result(
                doi,
                provider_statuses=(
                    ProviderDiscoveryStatus.NOT_FOUND,
                    ProviderDiscoveryStatus.SKIPPED,
                ),
            )
        return _result(
            doi,
            candidates=(_candidate(doi),),
            provider_statuses=(
                ProviderDiscoveryStatus.SUCCESS,
                ProviderDiscoveryStatus.SKIPPED,
            ),
        )

    monkeypatch.setattr(batch_module, "discover_full_text", fake_discover)

    results = discover_full_text_batch(
        [
            "10.1000/alpha",
            "https://doi.org/10.1000/NOT-FOUND",
            "not a doi",
        ]
    )

    assert [result.status for result in results] == [
        DiscoveryStatus.SUCCESS,
        DiscoveryStatus.NOT_FOUND,
        DiscoveryStatus.INVALID_DOI,
    ]
    assert [result.doi for result in results] == [
        "10.1000/alpha",
        "10.1000/not-found",
        None,
    ]
    assert all(result.elapsed_seconds >= 0 for result in results)


def test_batch_deduplicates_normalized_dois(monkeypatch):
    calls = []

    def fake_discover(doi, **kwargs):
        calls.append(doi)
        return _result(
            doi,
            candidates=(_candidate(doi),),
            provider_statuses=(
                ProviderDiscoveryStatus.SUCCESS,
                ProviderDiscoveryStatus.SKIPPED,
            ),
        )

    monkeypatch.setattr(batch_module, "discover_full_text", fake_discover)

    results = discover_full_text_batch(
        [
            "10.1000/alpha",
            "https://doi.org/10.1000/ALPHA",
        ]
    )

    assert len(results) == 1
    assert calls == ["10.1000/alpha"]


def test_batch_can_preserve_duplicates(monkeypatch):
    calls = []

    def fake_discover(doi, **kwargs):
        calls.append(doi)
        return _result(
            doi,
            candidates=(_candidate(doi),),
            provider_statuses=(
                ProviderDiscoveryStatus.SUCCESS,
                ProviderDiscoveryStatus.SKIPPED,
            ),
        )

    monkeypatch.setattr(batch_module, "discover_full_text", fake_discover)

    results = discover_full_text_batch(
        ["10.1000/alpha", "10.1000/ALPHA"],
        deduplicate=False,
    )

    assert len(results) == 2
    assert calls == ["10.1000/alpha", "10.1000/alpha"]


@pytest.mark.parametrize(
    ("candidates", "provider_statuses", "expected_status"),
    [
        (
            True,
            (
                ProviderDiscoveryStatus.SUCCESS,
                ProviderDiscoveryStatus.NETWORK_ERROR,
            ),
            DiscoveryStatus.PARTIAL_SUCCESS,
        ),
        (
            False,
            (
                ProviderDiscoveryStatus.NO_CANDIDATES,
                ProviderDiscoveryStatus.SKIPPED,
            ),
            DiscoveryStatus.NO_CANDIDATES,
        ),
        (
            False,
            (
                ProviderDiscoveryStatus.NOT_FOUND,
                ProviderDiscoveryStatus.SKIPPED,
            ),
            DiscoveryStatus.NOT_FOUND,
        ),
        (
            False,
            (
                ProviderDiscoveryStatus.NETWORK_ERROR,
                ProviderDiscoveryStatus.NO_CANDIDATES,
            ),
            DiscoveryStatus.ERROR,
        ),
    ],
)
def test_batch_classifies_provider_outcomes(
    monkeypatch,
    candidates,
    provider_statuses,
    expected_status,
):
    doi = "10.1000/alpha"
    candidate_tuple = (_candidate(doi),) if candidates else ()

    monkeypatch.setattr(
        batch_module,
        "discover_full_text",
        lambda *args, **kwargs: _result(
            doi,
            candidates=candidate_tuple,
            provider_statuses=provider_statuses,
        ),
    )

    result = discover_full_text_batch([doi])[0]

    assert result.status == expected_status
    assert result.discovery is not None
    assert result.elapsed_seconds >= 0

    if expected_status in {DiscoveryStatus.PARTIAL_SUCCESS, DiscoveryStatus.ERROR}:
        assert result.error is not None


def test_batch_forwards_provider_and_retry_configuration(monkeypatch):
    received = []

    def fake_discover(doi, **kwargs):
        received.append((doi, kwargs))
        return _result(
            doi,
            provider_statuses=(
                ProviderDiscoveryStatus.NO_CANDIDATES,
                ProviderDiscoveryStatus.SKIPPED,
            ),
        )

    monkeypatch.setattr(batch_module, "discover_full_text", fake_discover)

    discover_full_text_batch(
        ["10.1000/alpha"],
        unpaywall_email="person@example.org",
        openalex_api_key="key",
        max_attempts=5,
        backoff_base=0.5,
    )

    assert received == [
        (
            "10.1000/alpha",
            {
                "unpaywall_email": "person@example.org",
                "openalex_api_key": "key",
                "max_attempts": 5,
                "backoff_base": 0.5,
            },
        )
    ]


@pytest.mark.parametrize(
    "invalid_batch",
    [
        "10.1000/alpha",
        b"10.1000/alpha",
        123,
        None,
    ],
)
def test_batch_rejects_non_collection_input(invalid_batch):
    with pytest.raises(TypeError):
        discover_full_text_batch(invalid_batch)


def test_batch_validates_configuration_before_processing():
    with pytest.raises(TypeError):
        discover_full_text_batch([], unpaywall_email=123)

    with pytest.raises(TypeError):
        discover_full_text_batch([], openalex_api_key=123)

    with pytest.raises(ValueError):
        discover_full_text_batch([], max_attempts=0)

    with pytest.raises(TypeError):
        discover_full_text_batch([], deduplicate="yes")
