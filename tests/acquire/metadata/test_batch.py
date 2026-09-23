import pytest

import aletheia_nexus.acquire.metadata.batch as batch_module
from aletheia_nexus.acquire.metadata.batch import (
    MetadataStatus,
    get_metadata_batch,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
    UnsupportedAgencyError,
)
from aletheia_nexus.core.models import PaperMetadata


def _paper(doi: str) -> PaperMetadata:
    """Create simple metadata for batch tests."""

    return PaperMetadata(
        doi=doi,
        title=f"Test paper for {doi}",
        authors=("Test Author",),
        journal="Test Journal",
        issn=(),
        published_date="2026",
        year=2026,
        publisher="Test Publisher",
        work_type="journal-article",
        volume=None,
        issue=None,
        pages=None,
        url=f"https://doi.org/{doi}",
    )


def test_batch_handles_mixed_inputs_and_preserves_order(
    monkeypatch,
):
    """Mixed inputs should produce independent ordered results."""

    def fake_get_metadata_with_retry(
        doi,
        *,
        mailto=None,
        max_attempts=3,
        backoff_base=1.0,
    ):
        if doi == "10.9999/not-real-doi":
            raise MetadataNotFoundError("Not found")

        return _paper(doi)

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        fake_get_metadata_with_retry,
    )

    values = [
        "10.1038/nphys1170",
        "https://doi.org/10.5281/ZENODO.31780",
        "10.9999/not-real-doi",
        "not a doi",
    ]

    results = get_metadata_batch(values)

    assert [result.status for result in results] == [
        MetadataStatus.SUCCESS,
        MetadataStatus.SUCCESS,
        MetadataStatus.NOT_FOUND,
        MetadataStatus.INVALID_DOI,
    ]

    assert [result.doi for result in results] == [
        "10.1038/nphys1170",
        "10.5281/zenodo.31780",
        "10.9999/not-real-doi",
        None,
    ]
    assert all(result.elapsed_seconds >= 0 for result in results)


def test_batch_deduplicates_normalized_dois(
    monkeypatch,
):
    """Equivalent DOI forms should be queried only once."""

    calls = []

    def fake_get_metadata_with_retry(
        doi,
        *,
        mailto=None,
        max_attempts=3,
        backoff_base=1.0,
    ):
        calls.append(doi)
        return _paper(doi)

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        fake_get_metadata_with_retry,
    )

    results = get_metadata_batch(
        [
            "10.1038/nphys1170",
            "https://doi.org/10.1038/NPHYS1170",
        ]
    )

    assert len(results) == 1

    assert calls == [
        "10.1038/nphys1170",
    ]


def test_batch_can_keep_duplicates(
    monkeypatch,
):
    """deduplicate=False should preserve repeated DOI requests."""

    calls = []

    def fake_get_metadata_with_retry(
        doi,
        *,
        mailto=None,
        max_attempts=3,
        backoff_base=1.0,
    ):
        calls.append(doi)
        return _paper(doi)

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        fake_get_metadata_with_retry,
    )

    results = get_metadata_batch(
        [
            "10.1038/nphys1170",
            "10.1038/NPHYS1170",
        ],
        deduplicate=False,
    )

    assert len(results) == 2

    assert calls == [
        "10.1038/nphys1170",
        "10.1038/nphys1170",
    ]


@pytest.mark.parametrize(
    ("exception_type", "expected_status"),
    [
        (
            MetadataNotFoundError,
            MetadataStatus.NOT_FOUND,
        ),
        (
            UnsupportedAgencyError,
            MetadataStatus.UNSUPPORTED_AGENCY,
        ),
        (
            MetadataRequestError,
            MetadataStatus.REQUEST_ERROR,
        ),
        (
            MetadataNetworkError,
            MetadataStatus.NETWORK_ERROR,
        ),
        (
            RateLimitError,
            MetadataStatus.RATE_LIMITED,
        ),
        (
            MetadataServiceError,
            MetadataStatus.SERVICE_ERROR,
        ),
        (
            MetadataParseError,
            MetadataStatus.PARSE_ERROR,
        ),
    ],
)
def test_batch_maps_metadata_errors_to_statuses(
    monkeypatch,
    exception_type,
    expected_status,
):
    """Final metadata errors should become stable batch statuses."""

    def fake_get_metadata_with_retry(
        doi,
        *,
        mailto=None,
        max_attempts=3,
        backoff_base=1.0,
    ):
        raise exception_type("Test error")

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        fake_get_metadata_with_retry,
    )

    result = get_metadata_batch(["10.1038/nphys1170"])[0]

    assert result.status == expected_status
    assert result.metadata is None
    assert result.error == "Test error"
    assert result.elapsed_seconds >= 0


@pytest.mark.parametrize(
    "invalid_value",
    [
        "not a doi",
        "",
        None,
        123,
    ],
)
def test_batch_marks_invalid_members_without_stopping(
    monkeypatch,
    invalid_value,
):
    """Invalid members should not stop the rest of the batch."""

    calls = []

    def fake_get_metadata_with_retry(
        doi,
        *,
        mailto=None,
        max_attempts=3,
        backoff_base=1.0,
    ):
        calls.append(doi)
        return _paper(doi)

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        fake_get_metadata_with_retry,
    )

    results = get_metadata_batch(
        [
            invalid_value,
            "10.1038/nphys1170",
        ]
    )

    assert results[0].status == MetadataStatus.INVALID_DOI
    assert results[0].metadata is None
    assert results[0].elapsed_seconds >= 0

    assert results[1].status == MetadataStatus.SUCCESS
    assert results[1].doi == "10.1038/nphys1170"

    assert calls == [
        "10.1038/nphys1170",
    ]


@pytest.mark.parametrize(
    "invalid_batch",
    [
        "10.1038/nphys1170",
        b"10.1038/nphys1170",
        123,
        None,
    ],
)
def test_batch_rejects_non_collection_input(
    invalid_batch,
):
    """The batch itself must be a collection, not one DOI value."""

    with pytest.raises(TypeError):
        get_metadata_batch(invalid_batch)


def test_batch_forwards_retry_configuration(
    monkeypatch,
):
    """Batch settings should reach the retry layer unchanged."""

    received = []

    def fake_get_metadata_with_retry(
        doi,
        *,
        mailto=None,
        max_attempts=3,
        backoff_base=1.0,
    ):
        received.append(
            (
                doi,
                mailto,
                max_attempts,
                backoff_base,
            )
        )

        return _paper(doi)

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        fake_get_metadata_with_retry,
    )

    get_metadata_batch(
        [
            "10.1038/nphys1170",
            "10.5281/zenodo.31780",
        ],
        mailto="test@example.com",
        max_attempts=5,
        backoff_base=0.5,
    )

    assert received == [
        (
            "10.1038/nphys1170",
            "test@example.com",
            5,
            0.5,
        ),
        (
            "10.5281/zenodo.31780",
            "test@example.com",
            5,
            0.5,
        ),
    ]


def test_batch_success_contains_metadata(
    monkeypatch,
):
    """Successful results should contain metadata and runtime data."""

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        lambda doi, mailto=None, max_attempts=3, backoff_base=1.0: _paper(doi),
    )

    result = get_metadata_batch(["10.1038/nphys1170"])[0]

    assert result.status == MetadataStatus.SUCCESS
    assert result.metadata is not None
    assert result.error is None
    assert result.elapsed_seconds >= 0


def test_batch_failure_preserves_original_input(
    monkeypatch,
):
    """Failures should retain both original and normalized identifiers."""

    def fake_get_metadata_with_retry(
        doi,
        *,
        mailto=None,
        max_attempts=3,
        backoff_base=1.0,
    ):
        raise MetadataNotFoundError("Not found")

    monkeypatch.setattr(
        batch_module,
        "get_metadata_with_retry",
        fake_get_metadata_with_retry,
    )

    original = "https://doi.org/10.9999/NOT-REAL-DOI"

    result = get_metadata_batch([original])[0]

    assert result.input_value == original
    assert result.doi == "10.9999/not-real-doi"
    assert result.status == MetadataStatus.NOT_FOUND


def test_batch_validates_retry_config_before_processing():
    with pytest.raises(ValueError):
        get_metadata_batch(
            [],
            max_attempts=0,
        )


def test_batch_rejects_non_boolean_deduplicate():
    with pytest.raises(TypeError):
        get_metadata_batch(
            [],
            deduplicate="yes",
        )
