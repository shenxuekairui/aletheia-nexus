import pytest

import aletheia_nexus.acquire.metadata.crossref as crossref_module
from aletheia_nexus.acquire.metadata.crossref import (
    get_crossref_metadata,
    parse_crossref_work,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataParseError,
)

SAMPLE_WORK = {
    "DOI": "10.1038/nphys1170",
    "title": [
        "Measured measurement",
    ],
    "author": [
        {
            "given": "Markus",
            "family": "Aspelmeyer",
        }
    ],
    "container-title": [
        "Nature Physics",
    ],
    "ISSN": [
        "1745-2473",
        "1745-2481",
    ],
    "published": {
        "date-parts": [
            [
                2009,
                1,
            ]
        ]
    },
    "publisher": ("Springer Science and Business Media LLC"),
    "type": "journal-article",
    "volume": "5",
    "issue": "1",
    "page": "11-12",
    "URL": "https://doi.org/10.1038/nphys1170",
}


def test_parse_crossref_complete_work():
    """A complete Crossref work should map into PaperMetadata."""

    paper = parse_crossref_work(SAMPLE_WORK)

    assert paper.doi == "10.1038/nphys1170"
    assert paper.title == "Measured measurement"
    assert paper.authors == ("Markus Aspelmeyer",)
    assert paper.journal == "Nature Physics"
    assert paper.issn == (
        "1745-2473",
        "1745-2481",
    )
    assert paper.published_date == "2009-01"
    assert paper.year == 2009
    assert paper.publisher == "Springer Science and Business Media LLC"
    assert paper.work_type == "journal-article"
    assert paper.volume == "5"
    assert paper.issue == "1"
    assert paper.pages == "11-12"
    assert paper.url == "https://doi.org/10.1038/nphys1170"


def test_parse_crossref_normalizes_doi():
    work = {
        **SAMPLE_WORK,
        "DOI": "10.1038/NPHYS1170",
    }

    paper = parse_crossref_work(work)

    assert paper.doi == "10.1038/nphys1170"


def test_parse_crossref_allows_missing_authors():
    work = {
        **SAMPLE_WORK,
        "author": [],
    }

    paper = parse_crossref_work(work)

    assert paper.authors == ()


def test_parse_crossref_supports_literal_author_name():
    work = {
        **SAMPLE_WORK,
        "author": [
            {
                "name": "Example Research Consortium",
            }
        ],
    }

    paper = parse_crossref_work(work)

    assert paper.authors == ("Example Research Consortium",)


@pytest.mark.parametrize(
    ("date_parts", "expected_date"),
    [
        ([2009], "2009"),
        ([2009, 1], "2009-01"),
        ([2009, 1, 5], "2009-01-05"),
    ],
)
def test_parse_crossref_supports_date_precision(
    date_parts,
    expected_date,
):
    work = {
        **SAMPLE_WORK,
        "published": {
            "date-parts": [
                date_parts,
            ]
        },
    }

    paper = parse_crossref_work(work)

    assert paper.published_date == expected_date
    assert paper.year == 2009


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        (
            "title",
            "Measured measurement",
        ),
        (
            "container-title",
            "Nature Physics",
        ),
        (
            "ISSN",
            "1745-2473",
        ),
        (
            "author",
            "Markus Aspelmeyer",
        ),
        (
            "publisher",
            123,
        ),
        (
            "volume",
            5,
        ),
        (
            "published",
            [],
        ),
    ],
)
def test_parse_crossref_rejects_invalid_field_shapes(
    field,
    invalid_value,
):
    """Malformed service data must not silently become wrong metadata."""

    work = {
        **SAMPLE_WORK,
        field: invalid_value,
    }

    with pytest.raises(MetadataParseError):
        parse_crossref_work(work)


def test_parse_crossref_requires_doi():
    work = {
        **SAMPLE_WORK,
    }

    work.pop("DOI")

    with pytest.raises(MetadataParseError):
        parse_crossref_work(work)


def test_parse_crossref_rejects_non_object():
    with pytest.raises(MetadataParseError):
        parse_crossref_work("not-an-object")


def test_get_crossref_metadata_uses_transport(
    monkeypatch,
):
    """Provider should build the request and delegate HTTP to transport."""

    captured = {}

    def fake_get_json(
        url,
        **kwargs,
    ):
        captured["url"] = url
        captured.update(kwargs)

        return {
            "message": SAMPLE_WORK,
        }

    monkeypatch.setattr(
        crossref_module,
        "get_json",
        fake_get_json,
    )

    paper = get_crossref_metadata(
        "https://doi.org/10.1038/NPHYS1170",
        mailto="test@example.com",
    )

    assert paper.doi == "10.1038/nphys1170"

    assert captured["url"].endswith("/works/10.1038%2Fnphys1170")

    assert captured["params"] == {
        "mailto": "test@example.com",
    }

    assert captured["mailto"] == "test@example.com"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "message": None,
        },
        {
            "message": [],
        },
    ],
)
def test_get_crossref_metadata_rejects_invalid_structure(
    monkeypatch,
    payload,
):
    monkeypatch.setattr(
        crossref_module,
        "get_json",
        lambda *args, **kwargs: payload,
    )

    with pytest.raises(MetadataParseError):
        get_crossref_metadata("10.1038/nphys1170")


def test_get_crossref_metadata_preserves_transport_errors(
    monkeypatch,
):
    """Transport errors should propagate without being rewritten."""

    def fake_get_json(
        *args,
        **kwargs,
    ):
        raise MetadataNetworkError("Test network failure")

    monkeypatch.setattr(
        crossref_module,
        "get_json",
        fake_get_json,
    )

    with pytest.raises(
        MetadataNetworkError,
        match="Test network failure",
    ):
        get_crossref_metadata("10.1038/nphys1170")


def test_get_crossref_metadata_rejects_invalid_doi_before_transport(
    monkeypatch,
):
    def should_not_be_called(
        *args,
        **kwargs,
    ):
        raise AssertionError("Transport should not run for an invalid DOI")

    monkeypatch.setattr(
        crossref_module,
        "get_json",
        should_not_be_called,
    )

    with pytest.raises(ValueError):
        get_crossref_metadata("not a doi")
