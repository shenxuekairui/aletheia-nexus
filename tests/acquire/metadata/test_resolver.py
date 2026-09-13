import pytest

import aletheia_nexus.acquire.metadata.resolver as resolver_module
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataParseError,
    UnsupportedAgencyError,
)
from aletheia_nexus.acquire.metadata.resolver import (
    DoiAgency,
    get_doi_agency,
    get_metadata,
)
from aletheia_nexus.core.models import PaperMetadata


def _paper(
    doi: str,
) -> PaperMetadata:
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
        (
            "crossref",
            DoiAgency.CROSSREF,
        ),
        (
            "datacite",
            DoiAgency.DATACITE,
        ),
        (
            "CROSSREF",
            DoiAgency.CROSSREF,
        ),
    ],
)
def test_get_doi_agency_recognizes_supported_agencies(
    monkeypatch,
    agency_id,
    expected,
):
    monkeypatch.setattr(
        resolver_module,
        "get_json",
        lambda *args, **kwargs: {
            "message": {
                "agency": {
                    "id": agency_id,
                }
            }
        },
    )

    assert get_doi_agency("10.1038/nphys1170") == expected


def test_get_doi_agency_builds_correct_request(
    monkeypatch,
):
    captured = {}

    def fake_get_json(
        url,
        **kwargs,
    ):
        captured["url"] = url
        captured.update(kwargs)

        return {
            "message": {
                "agency": {
                    "id": "crossref",
                }
            }
        }

    monkeypatch.setattr(
        resolver_module,
        "get_json",
        fake_get_json,
    )

    agency = get_doi_agency(
        "https://doi.org/10.1038/NPHYS1170",
        mailto="test@example.com",
    )

    assert agency == DoiAgency.CROSSREF

    assert captured["url"].endswith("/works/10.1038%2Fnphys1170/agency")

    assert captured["params"] == {
        "mailto": "test@example.com",
    }

    assert captured["mailto"] == "test@example.com"


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
        {
            "message": {
                "agency": {
                    "id": 123,
                }
            }
        },
    ],
)
def test_get_doi_agency_rejects_invalid_structure(
    monkeypatch,
    payload,
):
    monkeypatch.setattr(
        resolver_module,
        "get_json",
        lambda *args, **kwargs: payload,
    )

    with pytest.raises(MetadataParseError):
        get_doi_agency("10.1038/nphys1170")


def test_get_doi_agency_rejects_unsupported_agency(
    monkeypatch,
):
    monkeypatch.setattr(
        resolver_module,
        "get_json",
        lambda *args, **kwargs: {
            "message": {
                "agency": {
                    "id": "medra",
                }
            }
        },
    )

    with pytest.raises(UnsupportedAgencyError):
        get_doi_agency("10.1038/nphys1170")


def test_get_doi_agency_preserves_transport_errors(
    monkeypatch,
):
    def fake_get_json(
        *args,
        **kwargs,
    ):
        raise MetadataNetworkError("Test transport failure")

    monkeypatch.setattr(
        resolver_module,
        "get_json",
        fake_get_json,
    )

    with pytest.raises(
        MetadataNetworkError,
        match="Test transport failure",
    ):
        get_doi_agency("10.1038/nphys1170")


def test_get_metadata_routes_to_crossref(
    monkeypatch,
):
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

    def should_not_be_called(
        *args,
        **kwargs,
    ):
        raise AssertionError("DataCite should not be called")

    monkeypatch.setattr(
        resolver_module,
        "get_datacite_metadata",
        should_not_be_called,
    )

    paper = get_metadata("10.1038/nphys1170")

    assert paper.doi == "10.1038/nphys1170"


def test_get_metadata_routes_to_datacite(
    monkeypatch,
):
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

    def should_not_be_called(
        *args,
        **kwargs,
    ):
        raise AssertionError("Crossref should not be called")

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        should_not_be_called,
    )

    paper = get_metadata("10.5281/zenodo.31780")

    assert paper.doi == "10.5281/zenodo.31780"


def test_get_metadata_normalizes_before_routing(
    monkeypatch,
):
    received = []

    def fake_get_doi_agency(
        doi,
        *,
        mailto=None,
    ):
        received.append(("agency", doi))

        return DoiAgency.CROSSREF

    def fake_crossref(
        doi,
        *,
        mailto=None,
    ):
        received.append(("crossref", doi))

        return _paper(doi)

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        fake_get_doi_agency,
    )

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        fake_crossref,
    )

    paper = get_metadata("https://doi.org/10.1038/NPHYS1170")

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
    received = []

    def fake_get_doi_agency(
        doi,
        *,
        mailto=None,
    ):
        received.append(("agency", mailto))

        return DoiAgency.CROSSREF

    def fake_crossref(
        doi,
        *,
        mailto=None,
    ):
        received.append(("crossref", mailto))

        return _paper(doi)

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        fake_get_doi_agency,
    )

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        fake_crossref,
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


def test_get_metadata_rejects_invalid_doi_before_routing(
    monkeypatch,
):
    def should_not_be_called(
        *args,
        **kwargs,
    ):
        raise AssertionError("Routing should not start for an invalid DOI")

    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        should_not_be_called,
    )

    with pytest.raises(ValueError):
        get_metadata("not a doi")


def test_get_metadata_preserves_provider_errors(
    monkeypatch,
):
    monkeypatch.setattr(
        resolver_module,
        "get_doi_agency",
        lambda doi, mailto=None: DoiAgency.CROSSREF,
    )

    def fake_crossref(
        doi,
        *,
        mailto=None,
    ):
        raise MetadataNetworkError("Provider failure")

    monkeypatch.setattr(
        resolver_module,
        "get_crossref_metadata",
        fake_crossref,
    )

    with pytest.raises(
        MetadataNetworkError,
        match="Provider failure",
    ):
        get_metadata("10.1038/nphys1170")
