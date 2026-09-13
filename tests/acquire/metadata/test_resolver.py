import httpx
import pytest

import aletheia_nexus.acquire.metadata.resolver as resolver_module
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataServiceError,
    RateLimitError,
    UnsupportedAgencyError,
    MetadataRequestError,
)
from aletheia_nexus.acquire.metadata.resolver import (
    DoiAgency,
    get_doi_agency,
    get_metadata,
)
from aletheia_nexus.core.models import PaperMetadata


def _paper(doi: str) -> PaperMetadata:
    """Create simple metadata for resolver tests."""

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


@pytest.mark.parametrize(
    ("agency_id", "expected"),
    [
        ("crossref", DoiAgency.CROSSREF),
        ("datacite", DoiAgency.DATACITE),
    ],
)
def test_get_doi_agency_recognizes_supported_agencies(
    monkeypatch,
    agency_id,
    expected,
):
    """Supported agency IDs should map to DoiAgency values."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "message": {
                    "agency": {
                        "id": agency_id,
                    }
                }
            },
        )

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    assert (
        get_doi_agency("10.1038/nphys1170")
        == expected
    )


@pytest.mark.parametrize(
    ("status_code", "expected_exception"),
    [
        (404, MetadataNotFoundError),
        (429, RateLimitError),
        (400, MetadataRequestError),
        (503, MetadataServiceError),
    ],
)
def test_get_doi_agency_maps_http_errors(
    monkeypatch,
    status_code,
    expected_exception,
):
    """HTTP failures should map to Aletheia metadata exceptions."""

    def fake_get(*args, **kwargs):
        return httpx.Response(status_code)

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(expected_exception):
        get_doi_agency(
            "10.1038/nphys1170"
        )


@pytest.mark.parametrize(
    "network_exception",
    [
        httpx.TimeoutException(
            "Timed out",
            request=httpx.Request(
                "GET",
                "https://api.crossref.org",
            ),
        ),
        httpx.ConnectError(
            "Connection failed",
            request=httpx.Request(
                "GET",
                "https://api.crossref.org",
            ),
        ),
    ],
    ids=[
        "timeout",
        "connection-error",
    ],
)
def test_get_doi_agency_maps_network_errors(
    monkeypatch,
    network_exception,
):
    """Network failures should become MetadataNetworkError."""

    def fake_get(*args, **kwargs):
        raise network_exception

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataNetworkError):
        get_doi_agency(
            "10.1038/nphys1170"
        )


def test_get_doi_agency_rejects_invalid_json(
    monkeypatch,
):
    """Invalid JSON should become MetadataParseError."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            content=b"not valid json",
        )

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_doi_agency(
            "10.1038/nphys1170"
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "message": {},
        },
        {
            "message": {
                "agency": {},
            }
        },
    ],
)
def test_get_doi_agency_rejects_invalid_structure(
    monkeypatch,
    payload,
):
    """Missing agency fields should become MetadataParseError."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json=payload,
        )

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_doi_agency(
            "10.1038/nphys1170"
        )


def test_get_doi_agency_rejects_invalid_agency_type(
    monkeypatch,
):
    """Agency ID must be a string."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "message": {
                    "agency": {
                        "id": 123,
                    }
                }
            },
        )

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_doi_agency(
            "10.1038/nphys1170"
        )


def test_get_doi_agency_rejects_unsupported_agency(
    monkeypatch,
):
    """Known but unsupported agencies should not appear as NOT_FOUND."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "message": {
                    "agency": {
                        "id": "medra",
                    }
                }
            },
        )

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(UnsupportedAgencyError):
        get_doi_agency(
            "10.1038/nphys1170"
        )


def test_get_doi_agency_sends_mailto(
    monkeypatch,
):
    """mailto should be forwarded to the Crossref agency request."""

    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)

        return httpx.Response(
            200,
            json={
                "message": {
                    "agency": {
                        "id": "crossref",
                    }
                }
            },
        )

    monkeypatch.setattr(
        resolver_module.httpx,
        "get",
        fake_get,
    )

    get_doi_agency(
        "10.1038/nphys1170",
        mailto="test@example.com",
    )

    assert captured["params"] == {
        "mailto": "test@example.com",
    }


def test_get_metadata_routes_only_to_crossref(
    monkeypatch,
):
    """Crossref DOI should call Crossref and not DataCite."""

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        lambda doi, mailto=None: DoiAgency.CROSSREF,
    )

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        lambda doi, mailto=None: _paper(doi),
    )

    def should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "DataCite should not be called"
        )

    monkeypatch.setattr(
        resolver_module,
        "get_datacite_metadata",
        should_not_be_called,
    )

    paper = get_metadata(
        "10.1038/nphys1170"
    )

    assert paper.doi == "10.1038/nphys1170"


def test_get_metadata_routes_only_to_datacite(
    monkeypatch,
):
    """DataCite DOI should call DataCite and not Crossref."""

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        lambda doi, mailto=None: DoiAgency.DATACITE,
    )

    monkeypatch.setattr(
        resolver_module,
        "get_datacite_metadata",
        lambda doi, mailto=None: _paper(doi),
    )

    def should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "Crossref should not be called"
        )

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        should_not_be_called,
    )

    paper = get_metadata(
        "10.5281/zenodo.31780"
    )

    assert paper.doi == "10.5281/zenodo.31780"


def test_get_metadata_normalizes_doi_before_routing(
    monkeypatch,
):
    """Resolver should pass normalized DOI values downstream."""

    received = []

    def fake_get_doi_agency(
        doi,
        *,
        mailto=None,
    ):
        received.append(
            ("agency", doi)
        )

        return DoiAgency.CROSSREF

    def fake_get_crossref_metadata(
        doi,
        *,
        mailto=None,
    ):
        received.append(
            ("crossref", doi)
        )

        return _paper(doi)

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        fake_get_doi_agency,
    )

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        fake_get_crossref_metadata,
    )

    paper = get_metadata(
        "https://doi.org/10.1038/NPHYS1170"
    )

    assert paper.doi == "10.1038/nphys1170"

    assert received == [
        (
            "agency",
            "10.1038/nphys1170",
        ),
        (
            "crossref",
            "10.1038/nphys1170",
        ),
    ]


def test_get_metadata_forwards_mailto(
    monkeypatch,
):
    """mailto should reach both agency lookup and metadata provider."""

    received = []

    def fake_get_doi_agency(
        doi,
        *,
        mailto=None,
    ):
        received.append(
            ("agency", mailto)
        )

        return DoiAgency.CROSSREF

    def fake_get_crossref_metadata(
        doi,
        *,
        mailto=None,
    ):
        received.append(
            ("crossref", mailto)
        )

        return _paper(doi)

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        fake_get_doi_agency,
    )

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        fake_get_crossref_metadata,
    )

    get_metadata(
        "10.1038/nphys1170",
        mailto="test@example.com",
    )

    assert received == [
        (
            "agency",
            "test@example.com",
        ),
        (
            "crossref",
            "test@example.com",
        ),
    ]


def test_get_metadata_rejects_invalid_doi_before_network(
    monkeypatch,
):
    """Invalid DOI input should fail before agency lookup."""

    def should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "Network routing should not start for an invalid DOI"
        )

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        should_not_be_called,
    )

    with pytest.raises(ValueError):
        get_metadata(
            "not a doi"
        )


def test_get_metadata_preserves_provider_errors(
    monkeypatch,
):
    """Provider errors should propagate to the caller unchanged."""

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        lambda doi, mailto=None: DoiAgency.CROSSREF,
    )

    def fake_get_crossref_metadata(
        doi,
        *,
        mailto=None,
    ):
        raise MetadataNetworkError(
            "Test network error"
        )

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        fake_get_crossref_metadata,
    )

    with pytest.raises(
        MetadataNetworkError,
        match="Test network error",
    ):
        get_metadata(
            "10.1038/nphys1170"
        )