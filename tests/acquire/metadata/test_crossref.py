import httpx
import pytest

import aletheia_nexus.acquire.metadata.crossref as crossref_module
from aletheia_nexus.acquire.metadata.crossref import (
    get_crossref_metadata,
    parse_crossref_work,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
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
    "publisher": (
        "Springer Science and Business Media LLC"
    ),
    "type": "journal-article",
    "volume": "5",
    "issue": "1",
    "page": "11-12",
    "URL": (
        "https://doi.org/10.1038/nphys1170"
    ),
}


def test_parse_crossref_complete_work():
    """A complete Crossref work should map into PaperMetadata."""

    paper = parse_crossref_work(
        SAMPLE_WORK
    )

    assert paper.doi == "10.1038/nphys1170"
    assert paper.title == "Measured measurement"

    assert paper.authors == (
        "Markus Aspelmeyer",
    )

    assert paper.journal == "Nature Physics"

    assert paper.issn == (
        "1745-2473",
        "1745-2481",
    )

    assert paper.published_date == "2009-01"
    assert paper.year == 2009

    assert (
        paper.publisher
        == "Springer Science and Business Media LLC"
    )

    assert paper.work_type == "journal-article"
    assert paper.volume == "5"
    assert paper.issue == "1"
    assert paper.pages == "11-12"

    assert (
        paper.url
        == "https://doi.org/10.1038/nphys1170"
    )


def test_parse_crossref_requires_doi():
    """DOI is required for a normalized work."""

    work = {
        **SAMPLE_WORK,
    }

    work.pop("DOI")

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


def test_parse_crossref_normalizes_doi():
    """Crossref DOI should be normalized."""

    work = {
        **SAMPLE_WORK,
        "DOI": "10.1038/NPHYS1170",
    }

    paper = parse_crossref_work(
        work
    )

    assert paper.doi == "10.1038/nphys1170"


def test_parse_crossref_allows_missing_authors():
    """Missing authors should become an empty tuple."""

    work = {
        **SAMPLE_WORK,
        "author": [],
    }

    paper = parse_crossref_work(
        work
    )

    assert paper.authors == ()


def test_parse_crossref_supports_literal_author_name():
    """Literal author names should be preserved."""

    work = {
        **SAMPLE_WORK,
        "author": [
            {
                "name": "Example Research Consortium",
            }
        ],
    }

    paper = parse_crossref_work(
        work
    )

    assert paper.authors == (
        "Example Research Consortium",
    )


def test_parse_crossref_rejects_invalid_author_shape():
    """Malformed author structures must not silently pass."""

    work = {
        **SAMPLE_WORK,
        "author": "not-a-list",
    }

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


def test_parse_crossref_rejects_wrong_title_shape():
    """A string title must not be mistaken for a list."""

    work = {
        **SAMPLE_WORK,
        "title": "Measured measurement",
    }

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


def test_parse_crossref_rejects_non_string_title():
    """Title list members must be strings."""

    work = {
        **SAMPLE_WORK,
        "title": [
            123,
        ],
    }

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


def test_parse_crossref_rejects_wrong_journal_shape():
    """Container titles must use the expected list form."""

    work = {
        **SAMPLE_WORK,
        "container-title": "Nature Physics",
    }

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


def test_parse_crossref_rejects_wrong_issn_shape():
    """ISSN should not silently accept malformed structures."""

    work = {
        **SAMPLE_WORK,
        "ISSN": "1745-2473",
    }

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


def test_parse_crossref_rejects_non_string_issn():
    """Every ISSN member must be text."""

    work = {
        **SAMPLE_WORK,
        "ISSN": [
            "1745-2473",
            123,
        ],
    }

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


@pytest.mark.parametrize(
    (
        "date_field",
        "expected_date",
    ),
    [
        (
            {
                "date-parts": [
                    [
                        2009,
                    ]
                ]
            },
            "2009",
        ),
        (
            {
                "date-parts": [
                    [
                        2009,
                        1,
                    ]
                ]
            },
            "2009-01",
        ),
        (
            {
                "date-parts": [
                    [
                        2009,
                        1,
                        5,
                    ]
                ]
            },
            "2009-01-05",
        ),
    ],
)
def test_parse_crossref_supports_date_precision(
    date_field,
    expected_date,
):
    """Crossref dates may contain year, month, or day precision."""

    work = {
        **SAMPLE_WORK,
        "published": date_field,
    }

    paper = parse_crossref_work(
        work
    )

    assert paper.published_date == expected_date
    assert paper.year == 2009


def test_parse_crossref_rejects_invalid_date_parts():
    """Malformed date-parts should become a parse error."""

    work = {
        **SAMPLE_WORK,
        "published": {
            "date-parts": [
                [
                    "2009",
                    1,
                ]
            ]
        },
    }

    with pytest.raises(
        MetadataParseError
    ):
        parse_crossref_work(
            work
        )


def test_get_crossref_metadata_success(
    monkeypatch,
):
    """A successful Crossref response should return metadata."""

    def fake_get(
        *args,
        **kwargs,
    ):
        return httpx.Response(
            200,
            json={
                "message": SAMPLE_WORK,
            },
        )

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        fake_get,
    )

    paper = get_crossref_metadata(
        "10.1038/nphys1170"
    )

    assert paper.doi == "10.1038/nphys1170"
    assert paper.title == "Measured measurement"


@pytest.mark.parametrize(
    (
        "status_code",
        "expected_exception",
    ),
    [
        (
            404,
            MetadataNotFoundError,
        ),
        (
            429,
            RateLimitError,
        ),
        (
            400,
            MetadataRequestError,
        ),
        (
            403,
            MetadataRequestError,
        ),
        (
            503,
            MetadataServiceError,
        ),
    ],
)
def test_get_crossref_metadata_maps_http_errors(
    monkeypatch,
    status_code,
    expected_exception,
):
    """HTTP errors should map to stable Aletheia exceptions."""

    def fake_get(
        *args,
        **kwargs,
    ):
        return httpx.Response(
            status_code
        )

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(
        expected_exception
    ):
        get_crossref_metadata(
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
def test_get_crossref_metadata_maps_network_errors(
    monkeypatch,
    network_exception,
):
    """Transport failures should become MetadataNetworkError."""

    def fake_get(
        *args,
        **kwargs,
    ):
        raise network_exception

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(
        MetadataNetworkError
    ):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )


def test_get_crossref_metadata_rejects_invalid_json(
    monkeypatch,
):
    """HTTP success with invalid JSON is a parse failure."""

    def fake_get(
        *args,
        **kwargs,
    ):
        return httpx.Response(
            200,
            content=b"not valid json",
        )

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(
        MetadataParseError
    ):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )


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
        {
            "unexpected": "data",
        },
    ],
)
def test_get_crossref_metadata_rejects_invalid_structure(
    monkeypatch,
    payload,
):
    """Malformed Crossref structures should be rejected."""

    def fake_get(
        *args,
        **kwargs,
    ):
        return httpx.Response(
            200,
            json=payload,
        )

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        fake_get,
    )

    with pytest.raises(
        MetadataParseError
    ):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )


def test_get_crossref_metadata_normalizes_before_request(
    monkeypatch,
):
    """DOI should be normalized before building the request URL."""

    captured = {}

    def fake_get(
        url,
        **kwargs,
    ):
        captured["url"] = url

        return httpx.Response(
            200,
            json={
                "message": SAMPLE_WORK,
            },
        )

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        fake_get,
    )

    get_crossref_metadata(
        "https://doi.org/10.1038/NPHYS1170"
    )

    assert captured["url"].endswith(
        "/works/10.1038%2Fnphys1170"
    )


def test_get_crossref_metadata_sends_mailto(
    monkeypatch,
):
    """Contact email should be sent as the Crossref mailto parameter."""

    captured = {}

    def fake_get(
        *args,
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return httpx.Response(
            200,
            json={
                "message": SAMPLE_WORK,
            },
        )

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        fake_get,
    )

    get_crossref_metadata(
        "10.1038/nphys1170",
        mailto="test@example.com",
    )

    assert captured["params"] == {
        "mailto": "test@example.com",
    }


def test_get_crossref_metadata_rejects_invalid_input_before_network(
    monkeypatch,
):
    """Invalid DOI should fail before HTTP is attempted."""

    def should_not_be_called(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "Crossref should not be contacted "
            "for an invalid DOI"
        )

    monkeypatch.setattr(
        crossref_module.httpx,
        "get",
        should_not_be_called,
    )

    with pytest.raises(
        ValueError
    ):
        get_crossref_metadata(
            "not a doi"
        )