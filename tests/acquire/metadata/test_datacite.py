import httpx
import pytest

import aletheia_nexus.acquire.metadata.datacite as datacite_module
from aletheia_nexus.acquire.metadata.datacite import (
    get_datacite_metadata,
    parse_datacite_attributes,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataServiceError,
    RateLimitError,
    MetadataRequestError,
)


SAMPLE_ATTRIBUTES = {
    "doi": "10.5281/zenodo.31780",
    "titles": [
        {
            "title": "Doi Myths... Busted",
        }
    ],
    "creators": [
        {
            "givenName": "Geoffrey",
            "familyName": "Bilder",
            "name": "Bilder, Geoffrey",
        },
        {
            "givenName": "Martin",
            "familyName": "Fenner",
            "name": "Fenner, Martin",
        },
    ],
    "publisher": "Zenodo",
    "publicationYear": 2015,
    "dates": [
        {
            "date": "2015-10-04",
            "dateType": "Issued",
        }
    ],
    "types": {
        "resourceType": "Presentation",
        "resourceTypeGeneral": "Audiovisual",
    },
    "url": "https://zenodo.org/record/31780",
    "container": {
        "title": "Example Container",
        "identifier": "1234-5678",
        "identifierType": "ISSN",
        "volume": "12",
        "issue": "3",
        "firstPage": "11",
    },
}


def test_parse_datacite_complete_record():
    """A complete DataCite record should map into PaperMetadata."""

    paper = parse_datacite_attributes(
        SAMPLE_ATTRIBUTES
    )

    assert paper.doi == "10.5281/zenodo.31780"
    assert paper.title == "Doi Myths... Busted"

    assert paper.authors == (
        "Geoffrey Bilder",
        "Martin Fenner",
    )

    assert paper.journal == "Example Container"
    assert paper.issn == ("1234-5678",)

    assert paper.published_date == "2015-10-04"
    assert paper.year == 2015

    assert paper.publisher == "Zenodo"
    assert paper.work_type == "Presentation"

    assert paper.volume == "12"
    assert paper.issue == "3"
    assert paper.pages == "11"

    assert (
        paper.url
        == "https://zenodo.org/record/31780"
    )


def test_parse_datacite_normalizes_doi():
    """DOI values returned by DataCite should be normalized."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "doi": "10.5281/ZENODO.31780",
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.doi == "10.5281/zenodo.31780"


def test_parse_datacite_creator_falls_back_to_name():
    """Creator name should work even without given/family components."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "creators": [
            {
                "name": "DataCite Metadata Working Group",
            }
        ],
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.authors == (
        "DataCite Metadata Working Group",
    )


def test_parse_datacite_allows_missing_creators():
    """A DataCite object may legitimately have no usable creators."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "creators": [],
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.authors == ()


def test_parse_datacite_supports_publisher_object():
    """Structured publisher objects should yield their name."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "publisher": {
            "name": "DataCite",
        },
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.publisher == "DataCite"


def test_parse_datacite_prefers_issued_date():
    """Issued date should be preferred over publicationYear alone."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "publicationYear": 2014,
        "dates": [
            {
                "date": "2015-10-04",
                "dateType": "Issued",
            }
        ],
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.published_date == "2015-10-04"
    assert paper.year == 2015


def test_parse_datacite_falls_back_to_publication_year():
    """publicationYear should be used when no Issued date exists."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "dates": [],
        "publicationYear": 2015,
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.published_date == "2015"
    assert paper.year == 2015


def test_parse_datacite_prefers_specific_resource_type():
    """Specific resourceType should beat the general resource type."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "types": {
            "resourceType": "Presentation",
            "resourceTypeGeneral": "Audiovisual",
        },
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.work_type == "Presentation"


def test_parse_datacite_falls_back_to_general_resource_type():
    """resourceTypeGeneral should be used when resourceType is absent."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "types": {
            "resourceTypeGeneral": "Dataset",
        },
    }

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.work_type == "Dataset"


def test_parse_datacite_allows_missing_container():
    """Container information is optional for many DataCite objects."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
    }
    attributes.pop("container")

    paper = parse_datacite_attributes(
        attributes
    )

    assert paper.journal is None
    assert paper.issn == ()
    assert paper.volume is None
    assert paper.issue is None
    assert paper.pages is None


def test_parse_datacite_requires_doi():
    """A record without its required DOI cannot become PaperMetadata."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
    }
    attributes.pop("doi")

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(
            attributes
        )


def test_parse_datacite_rejects_malformed_doi():
    """Malformed DOI metadata should be reported as a parse failure."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "doi": "not a doi",
    }

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(
            attributes
        )


def test_get_datacite_metadata_success(
    monkeypatch,
):
    """A successful API response should return normalized metadata."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "data": {
                    "attributes": SAMPLE_ATTRIBUTES,
                }
            },
        )

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        fake_get,
    )

    paper = get_datacite_metadata(
        "10.5281/zenodo.31780"
    )

    assert paper.doi == "10.5281/zenodo.31780"
    assert paper.title == "Doi Myths... Busted"


@pytest.mark.parametrize(
    ("status_code", "expected_exception"),
    [
        (404, MetadataNotFoundError),
        (429, RateLimitError),
        (400, MetadataRequestError),
        (503, MetadataServiceError),
    ],
)
def test_get_datacite_metadata_maps_http_errors(
    monkeypatch,
    status_code,
    expected_exception,
):
    """HTTP failures should map to Aletheia metadata exceptions."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            status_code
        )

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(expected_exception):
        get_datacite_metadata(
            "10.5281/zenodo.31780"
        )


@pytest.mark.parametrize(
    "network_exception",
    [
        httpx.TimeoutException(
            "Timed out",
            request=httpx.Request(
                "GET",
                "https://api.datacite.org",
            ),
        ),
        httpx.ConnectError(
            "Connection failed",
            request=httpx.Request(
                "GET",
                "https://api.datacite.org",
            ),
        ),
    ],
    ids=[
        "timeout",
        "connection-error",
    ],
)
def test_get_datacite_metadata_maps_network_errors(
    monkeypatch,
    network_exception,
):
    """Transport failures should become MetadataNetworkError."""

    def fake_get(*args, **kwargs):
        raise network_exception

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataNetworkError):
        get_datacite_metadata(
            "10.5281/zenodo.31780"
        )


def test_get_datacite_metadata_rejects_invalid_json(
    monkeypatch,
):
    """Successful HTTP status with invalid JSON is still a parse failure."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            content=b"not valid json",
        )

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_datacite_metadata(
            "10.5281/zenodo.31780"
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "data": {},
        },
        {
            "data": {
                "attributes": None,
            }
        },
        {
            "data": {
                "attributes": [],
            }
        },
    ],
)
def test_get_datacite_metadata_rejects_invalid_structure(
    monkeypatch,
    payload,
):
    """Malformed JSON:API response structure should be rejected."""

    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json=payload,
        )

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_datacite_metadata(
            "10.5281/zenodo.31780"
        )


def test_get_datacite_metadata_normalizes_before_request(
    monkeypatch,
):
    """Raw DOI input should be normalized before building the request URL."""

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url

        return httpx.Response(
            200,
            json={
                "data": {
                    "attributes": SAMPLE_ATTRIBUTES,
                }
            },
        )

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        fake_get,
    )

    get_datacite_metadata(
        "https://doi.org/10.5281/ZENODO.31780"
    )

    assert captured["url"].endswith(
        "/dois/10.5281%2Fzenodo.31780"
    )


def test_get_datacite_metadata_sends_mailto_in_user_agent(
    monkeypatch,
):
    """Contact email should be included in the DataCite User-Agent."""

    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)

        return httpx.Response(
            200,
            json={
                "data": {
                    "attributes": SAMPLE_ATTRIBUTES,
                }
            },
        )

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        fake_get,
    )

    get_datacite_metadata(
        "10.5281/zenodo.31780",
        mailto="test@example.com",
    )

    user_agent = captured["headers"]["User-Agent"]

    assert "Aletheia-Nexus" in user_agent
    assert "test@example.com" in user_agent


def test_get_datacite_metadata_rejects_invalid_input_before_network(
    monkeypatch,
):
    """Invalid DOI input should fail before any HTTP request is made."""

    def should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "DataCite should not be contacted for an invalid DOI"
        )

    monkeypatch.setattr(
        datacite_module.httpx,
        "get",
        should_not_be_called,
    )

    with pytest.raises(ValueError):
        get_datacite_metadata(
            "not a doi"
        )