import pytest

import aletheia_nexus.acquire.metadata.retry as retry_module
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
    UnsupportedAgencyError,
)
from aletheia_nexus.acquire.metadata.retry import (
    get_metadata_with_retry,
)
from aletheia_nexus.core.models import PaperMetadata


def _paper(doi: str) -> PaperMetadata:
    """Create simple metadata for retry tests."""

    return PaperMetadata(
        doi=doi,
        title="Test Paper",
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


def test_success_returns_without_retry(
    monkeypatch,
):
    """A successful first attempt should return immediately."""

    attempts = []

    def fake_get_metadata(
        doi,
        *,
        mailto=None,
    ):
        attempts.append(doi)
        return _paper(doi)

    monkeypatch.setattr(
        retry_module,
        "get_metadata",
        fake_get_metadata,
    )

    paper = get_metadata_with_retry("10.1038/nphys1170")

    assert paper.doi == "10.1038/nphys1170"
    assert len(attempts) == 1


@pytest.mark.parametrize(
    "exception_type",
    [
        MetadataNetworkError,
        RateLimitError,
        MetadataServiceError,
    ],
)
def test_retryable_errors_can_recover(
    monkeypatch,
    exception_type,
):
    """Temporary failures should be retried until success."""

    attempts = []

    def fake_get_metadata(
        doi,
        *,
        mailto=None,
    ):
        attempts.append(doi)

        if len(attempts) < 3:
            raise exception_type("Temporary failure")

        return _paper(doi)

    monkeypatch.setattr(
        retry_module,
        "get_metadata",
        fake_get_metadata,
    )

    monkeypatch.setattr(
        retry_module.time,
        "sleep",
        lambda seconds: None,
    )

    paper = get_metadata_with_retry(
        "10.1038/nphys1170",
        max_attempts=3,
    )

    assert paper.doi == "10.1038/nphys1170"
    assert len(attempts) == 3


@pytest.mark.parametrize(
    "exception_type",
    [
        MetadataNotFoundError,
        MetadataRequestError,
        MetadataParseError,
        UnsupportedAgencyError,
    ],
)
def test_non_retryable_errors_fail_immediately(
    monkeypatch,
    exception_type,
):
    """Permanent failures should never be retried."""

    attempts = []

    def fake_get_metadata(
        doi,
        *,
        mailto=None,
    ):
        attempts.append(doi)

        raise exception_type("Permanent failure")

    monkeypatch.setattr(
        retry_module,
        "get_metadata",
        fake_get_metadata,
    )

    with pytest.raises(exception_type):
        get_metadata_with_retry(
            "10.1038/nphys1170",
            max_attempts=5,
        )

    assert len(attempts) == 1


def test_retry_stops_at_max_attempts(
    monkeypatch,
):
    """Retries must stop after the configured attempt limit."""

    attempts = []

    def fake_get_metadata(
        doi,
        *,
        mailto=None,
    ):
        attempts.append(doi)

        raise MetadataNetworkError("Still offline")

    monkeypatch.setattr(
        retry_module,
        "get_metadata",
        fake_get_metadata,
    )

    monkeypatch.setattr(
        retry_module.time,
        "sleep",
        lambda seconds: None,
    )

    with pytest.raises(
        MetadataNetworkError,
        match="Still offline",
    ):
        get_metadata_with_retry(
            "10.1038/nphys1170",
            max_attempts=3,
        )

    assert len(attempts) == 3


def test_retry_uses_exponential_backoff(
    monkeypatch,
):
    """Waiting periods should follow exponential backoff."""

    delays = []

    def fake_get_metadata(
        doi,
        *,
        mailto=None,
    ):
        raise RateLimitError("Rate limited")

    monkeypatch.setattr(
        retry_module,
        "get_metadata",
        fake_get_metadata,
    )

    monkeypatch.setattr(
        retry_module.time,
        "sleep",
        delays.append,
    )

    with pytest.raises(RateLimitError):
        get_metadata_with_retry(
            "10.1038/nphys1170",
            max_attempts=4,
            backoff_base=1.0,
        )

    assert delays == [
        1.0,
        2.0,
        4.0,
    ]


def test_retry_respects_custom_backoff_base(
    monkeypatch,
):
    """Custom backoff base should scale all delays."""

    delays = []

    def fake_get_metadata(
        doi,
        *,
        mailto=None,
    ):
        raise MetadataServiceError("Temporary server error")

    monkeypatch.setattr(
        retry_module,
        "get_metadata",
        fake_get_metadata,
    )

    monkeypatch.setattr(
        retry_module.time,
        "sleep",
        delays.append,
    )

    with pytest.raises(MetadataServiceError):
        get_metadata_with_retry(
            "10.1038/nphys1170",
            max_attempts=3,
            backoff_base=0.5,
        )

    assert delays == [
        0.5,
        1.0,
    ]


def test_retry_forwards_mailto(
    monkeypatch,
):
    """mailto should be forwarded on every attempt."""

    received = []

    def fake_get_metadata(
        doi,
        *,
        mailto=None,
    ):
        received.append(mailto)

        if len(received) == 1:
            raise MetadataNetworkError("Temporary failure")

        return _paper(doi)

    monkeypatch.setattr(
        retry_module,
        "get_metadata",
        fake_get_metadata,
    )

    monkeypatch.setattr(
        retry_module.time,
        "sleep",
        lambda seconds: None,
    )

    get_metadata_with_retry(
        "10.1038/nphys1170",
        mailto="test@example.com",
    )

    assert received == [
        "test@example.com",
        "test@example.com",
    ]


@pytest.mark.parametrize(
    ("max_attempts", "expected_exception"),
    [
        (0, ValueError),
        (-1, ValueError),
        (1.5, TypeError),
        ("3", TypeError),
        (True, TypeError),
    ],
)
def test_retry_rejects_invalid_max_attempts(
    max_attempts,
    expected_exception,
):
    """max_attempts must be a positive integer."""

    with pytest.raises(expected_exception):
        get_metadata_with_retry(
            "10.1038/nphys1170",
            max_attempts=max_attempts,
        )


@pytest.mark.parametrize(
    ("backoff_base", "expected_exception"),
    [
        (-1.0, ValueError),
        ("1.0", TypeError),
        (None, TypeError),
    ],
)
def test_retry_rejects_invalid_backoff_base(
    backoff_base,
    expected_exception,
):
    """backoff_base must be a non-negative number."""

    with pytest.raises(expected_exception):
        get_metadata_with_retry(
            "10.1038/nphys1170",
            backoff_base=backoff_base,
        )


@pytest.mark.parametrize(
    "backoff_base",
    [
        True,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_retry_rejects_unsafe_backoff_values(
    backoff_base,
):
    expected_exception = TypeError if isinstance(backoff_base, bool) else ValueError

    with pytest.raises(expected_exception):
        get_metadata_with_retry(
            "10.1038/nphys1170",
            backoff_base=backoff_base,
        )
