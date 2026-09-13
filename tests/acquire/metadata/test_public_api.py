from aletheia_nexus.acquire.metadata import (
    DoiAgency,
    MetadataError,
    MetadataLookupResult,
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    MetadataStatus,
    PaperMetadata,
    RateLimitError,
    UnsupportedAgencyError,
    get_doi_agency,
    get_metadata,
    get_metadata_batch,
    get_metadata_with_retry,
)


def test_public_metadata_api_is_importable():
    """The stable v0.3 metadata API should be importable from one place."""

    assert callable(get_doi_agency)
    assert callable(get_metadata)
    assert callable(get_metadata_with_retry)
    assert callable(get_metadata_batch)


def test_public_metadata_models_are_exposed():
    """Core metadata models should be part of the public API."""

    assert PaperMetadata is not None
    assert MetadataLookupResult is not None

    assert MetadataStatus.SUCCESS == "SUCCESS"
    assert DoiAgency.CROSSREF == "crossref"
    assert DoiAgency.DATACITE == "datacite"


def test_public_metadata_exceptions_share_common_base():
    """Metadata exceptions should retain a common catchable base class."""

    exception_types = [
        MetadataNetworkError,
        MetadataNotFoundError,
        MetadataParseError,
        MetadataRequestError,
        MetadataServiceError,
        RateLimitError,
        UnsupportedAgencyError,
    ]

    for exception_type in exception_types:
        assert issubclass(
            exception_type,
            MetadataError,
        )
