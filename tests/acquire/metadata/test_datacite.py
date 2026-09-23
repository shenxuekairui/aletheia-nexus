import pytest

import aletheia_nexus.acquire.metadata.datacite as datacite_module
from aletheia_nexus.acquire.metadata.datacite import (
    get_datacite_metadata,
    parse_datacite_attributes,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataParseError,
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
    "relatedItems": [
        {
            "relationType": "IsPublishedIn",
            "relatedItemType": "Journal",
            "titles": [
                {
                    "title": "Physics Letters B",
                }
            ],
            "volume": "776",
            "issue": "4",
            "firstPage": "249",
            "lastPage": "264",
            "relatedItemIdentifier": {
                "relatedItemIdentifier": "0370-2693",
                "relatedItemIdentifierType": "ISSN",
            },
        }
    ],
    "container": {
        "title": "Legacy Example Journal",
        "identifier": "1234-5678",
        "identifierType": "ISSN",
        "volume": "12",
        "issue": "3",
        "firstPage": "11",
        "lastPage": "18",
    },
}


def test_parse_datacite_complete_record():
    """A complete DataCite record should map into PaperMetadata."""

    paper = parse_datacite_attributes(SAMPLE_ATTRIBUTES)

    assert paper.doi == "10.5281/zenodo.31780"
    assert paper.title == "Doi Myths... Busted"

    assert paper.authors == (
        "Geoffrey Bilder",
        "Martin Fenner",
    )

    assert paper.published_date == "2015-10-04"
    assert paper.year == 2015

    assert paper.publisher == "Zenodo"
    assert paper.work_type == "Presentation"

    assert paper.journal == "Physics Letters B"
    assert paper.issn == ("0370-2693",)

    assert paper.volume == "776"
    assert paper.issue == "4"
    assert paper.pages == "249-264"

    assert paper.url == "https://zenodo.org/record/31780"


def test_parse_datacite_normalizes_doi():
    """DataCite DOI values should be normalized."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "doi": "10.5281/ZENODO.31780",
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.doi == "10.5281/zenodo.31780"


def test_datacite_prefers_related_items_over_container():
    """
    Modern IsPublishedIn metadata should take priority
    over legacy container metadata.
    """

    paper = parse_datacite_attributes(SAMPLE_ATTRIBUTES)

    assert paper.journal == "Physics Letters B"
    assert paper.issn == ("0370-2693",)
    assert paper.volume == "776"
    assert paper.issue == "4"
    assert paper.pages == "249-264"

    assert paper.journal != "Legacy Example Journal"


def test_datacite_falls_back_to_container():
    """
    Legacy container metadata should remain supported
    when IsPublishedIn is unavailable.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [],
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.journal == "Legacy Example Journal"

    assert paper.issn == ("1234-5678",)

    assert paper.volume == "12"
    assert paper.issue == "3"
    assert paper.pages == "11-18"


def test_datacite_does_not_mix_publication_sources():
    """
    Publication fields must come from one coherent source.

    A partial IsPublishedIn record must not be combined
    with page information from the legacy container.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [
            {
                "relationType": "IsPublishedIn",
                "titles": [
                    {
                        "title": "Modern Journal",
                    }
                ],
                "firstPage": "249",
            }
        ],
        "container": {
            "title": "Legacy Journal",
            "firstPage": "11",
            "lastPage": "18",
        },
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.journal == "Modern Journal"
    assert paper.pages == "249"


def test_datacite_empty_related_item_falls_back_to_container():
    """
    An empty IsPublishedIn record should not block
    a useful legacy container fallback.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [
            {
                "relationType": "IsPublishedIn",
            }
        ],
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.journal == "Legacy Example Journal"


def test_datacite_ignores_unrelated_related_items():
    """
    Related items with another relation type should not
    be interpreted as publication-container metadata.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [
            {
                "relationType": "IsSupplementTo",
                "titles": [
                    {
                        "title": "Unrelated Work",
                    }
                ],
            }
        ],
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.journal == "Legacy Example Journal"


def test_datacite_allows_missing_publication_info():
    """
    DataCite objects such as datasets or presentations
    may legitimately have no journal information.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [],
    }

    attributes.pop("container")

    paper = parse_datacite_attributes(attributes)

    assert paper.journal is None
    assert paper.issn == ()
    assert paper.volume is None
    assert paper.issue is None
    assert paper.pages is None


@pytest.mark.parametrize(
    (
        "first_page",
        "last_page",
        "expected",
    ),
    [
        (
            "11",
            None,
            "11",
        ),
        (
            None,
            "18",
            "18",
        ),
        (
            "11",
            "11",
            "11",
        ),
        (
            "11",
            "18",
            "11-18",
        ),
    ],
)
def test_datacite_page_range_variants(
    first_page,
    last_page,
    expected,
):
    """Different legitimate page combinations should be supported."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [],
        "container": {
            "title": "Example Journal",
            "firstPage": first_page,
            "lastPage": last_page,
        },
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.pages == expected


def test_datacite_creator_falls_back_to_literal_name():
    """Organizations may provide only a literal creator name."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "creators": [
            {
                "name": ("DataCite Metadata Working Group"),
            }
        ],
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.authors == ("DataCite Metadata Working Group",)


def test_datacite_allows_missing_creators():
    """No usable creators should produce an empty tuple."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "creators": [],
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.authors == ()


def test_datacite_supports_publisher_object():
    """Structured publisher objects should yield their name."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "publisher": {
            "name": "DataCite",
        },
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.publisher == "DataCite"


def test_datacite_prefers_issued_date():
    """Issued date should take priority over publicationYear."""

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

    paper = parse_datacite_attributes(attributes)

    assert paper.published_date == "2015-10-04"
    assert paper.year == 2015


def test_datacite_falls_back_to_publication_year():
    """publicationYear should be used when Issued date is absent."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "dates": [],
        "publicationYear": 2015,
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.published_date == "2015"
    assert paper.year == 2015


def test_datacite_prefers_specific_resource_type():
    """
    resourceType should take priority over
    resourceTypeGeneral when both are present.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "types": {
            "resourceType": "Presentation",
            "resourceTypeGeneral": "Audiovisual",
        },
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.work_type == "Presentation"


def test_datacite_falls_back_to_general_resource_type():
    """
    resourceTypeGeneral should be used when
    no specific resourceType is available.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "types": {
            "resourceTypeGeneral": "Dataset",
        },
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.work_type == "Dataset"


@pytest.mark.parametrize(
    (
        "field",
        "invalid_value",
    ),
    [
        (
            "titles",
            "not-a-list",
        ),
        (
            "creators",
            "not-a-list",
        ),
        (
            "dates",
            "not-a-list",
        ),
        (
            "types",
            "not-an-object",
        ),
        (
            "relatedItems",
            "not-a-list",
        ),
    ],
)
def test_datacite_rejects_invalid_shapes(
    field,
    invalid_value,
):
    """
    Malformed fields that participate directly
    in parsing should fail clearly.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        field: invalid_value,
    }

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(attributes)


def test_datacite_rejects_invalid_publication_year_when_used():
    """
    publicationYear must be valid when it is actually
    required as the publication-date fallback.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "dates": [],
        "publicationYear": "2015",
    }

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(attributes)


def test_datacite_ignores_invalid_publication_year_when_unused():
    """
    A malformed fallback publicationYear should not destroy
    otherwise valid metadata when a valid Issued date exists.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "publicationYear": "2015",
        "dates": [
            {
                "date": "2015-10-04",
                "dateType": "Issued",
            }
        ],
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.published_date == "2015-10-04"
    assert paper.year == 2015


def test_datacite_rejects_invalid_container_when_used():
    """
    container must be valid when no usable IsPublishedIn
    metadata is available.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [],
        "container": "not-an-object",
    }

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(attributes)


def test_datacite_ignores_invalid_container_when_unused():
    """
    A malformed legacy container should not destroy
    a valid modern IsPublishedIn record.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "container": "not-an-object",
    }

    paper = parse_datacite_attributes(attributes)

    assert paper.journal == "Physics Letters B"
    assert paper.pages == "249-264"


def test_datacite_rejects_malformed_related_item_entry():
    """Each relatedItems member must be an object."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [
            "not-an-object",
        ],
    }

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(attributes)


def test_datacite_rejects_malformed_related_identifier():
    """
    relatedItemIdentifier must have a valid object
    structure when publication metadata uses it.
    """

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "relatedItems": [
            {
                "relationType": "IsPublishedIn",
                "titles": [
                    {
                        "title": "Example Journal",
                    }
                ],
                "relatedItemIdentifier": ("not-an-object"),
            }
        ],
    }

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(attributes)


def test_datacite_requires_doi():
    """A DataCite record must contain a DOI."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
    }

    attributes.pop("doi")

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(attributes)


def test_datacite_rejects_invalid_doi():
    """Malformed DOI data should become a parse error."""

    attributes = {
        **SAMPLE_ATTRIBUTES,
        "doi": "not a doi",
    }

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(attributes)


@pytest.mark.parametrize(
    "invalid_attributes",
    [
        None,
        [],
        "not-an-object",
    ],
)
def test_datacite_rejects_non_object_attributes(
    invalid_attributes,
):
    """Top-level DataCite attributes must be an object."""

    with pytest.raises(MetadataParseError):
        parse_datacite_attributes(invalid_attributes)


def test_get_datacite_metadata_uses_transport(
    monkeypatch,
):
    """
    DataCite provider should delegate HTTP behavior
    to the shared transport layer.
    """

    captured = {}

    def fake_get_json(
        url,
        **kwargs,
    ):
        captured["url"] = url
        captured.update(kwargs)

        return {
            "data": {
                "attributes": SAMPLE_ATTRIBUTES,
            }
        }

    monkeypatch.setattr(
        datacite_module,
        "get_json",
        fake_get_json,
    )

    paper = get_datacite_metadata(
        "https://doi.org/10.5281/ZENODO.31780",
        mailto="test@example.com",
    )

    assert paper.doi == "10.5281/zenodo.31780"

    assert captured["url"].endswith("/dois/10.5281%2Fzenodo.31780")

    assert captured["mailto"] == "test@example.com"


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
    """
    A successful HTTP response with an invalid DataCite
    JSON structure must still fail parsing.
    """

    monkeypatch.setattr(
        datacite_module,
        "get_json",
        lambda *args, **kwargs: payload,
    )

    with pytest.raises(MetadataParseError):
        get_datacite_metadata("10.5281/zenodo.31780")


def test_get_datacite_metadata_preserves_transport_errors(
    monkeypatch,
):
    """Transport errors should propagate unchanged."""

    def fake_get_json(
        *args,
        **kwargs,
    ):
        raise MetadataNetworkError("Test network failure")

    monkeypatch.setattr(
        datacite_module,
        "get_json",
        fake_get_json,
    )

    with pytest.raises(
        MetadataNetworkError,
        match="Test network failure",
    ):
        get_datacite_metadata("10.5281/zenodo.31780")


def test_get_datacite_metadata_rejects_invalid_doi_before_transport(
    monkeypatch,
):
    """
    Invalid DOI input must fail before making
    any network request.
    """

    def should_not_be_called(
        *args,
        **kwargs,
    ):
        raise AssertionError("Transport should not run for an invalid DOI")

    monkeypatch.setattr(
        datacite_module,
        "get_json",
        should_not_be_called,
    )

    with pytest.raises(ValueError):
        get_datacite_metadata("not a doi")
