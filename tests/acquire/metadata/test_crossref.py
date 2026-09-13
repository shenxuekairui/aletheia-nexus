import httpx
import pytest

from aletheia_nexus.acquire.metadata.crossref import (
    get_crossref_metadata,
    parse_crossref_work,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataServiceError,
    RateLimitError,
    MetadataRequestError,
)


SAMPLE_WORK = {
    "DOI": "10.1038/nphys1170",
    "title": ["Measured measurement"],
    "author": [
        {
            "given": "Markus",
            "family": "Aspelmeyer",
        }
    ],
    "container-title": ["Nature Physics"],
    "ISSN": [
        "1745-2473",
        "1745-2481",
    ],
    "published": {
        "date-parts": [[2009, 1]]
    },
    "publisher": "Springer Science and Business Media LLC",
    "type": "journal-article",
    "volume": "5",
    "issue": "1",
    "page": "11-12",
    "URL": "https://doi.org/10.1038/nphys1170",
}


def test_parse_crossref_work():
    paper = parse_crossref_work(SAMPLE_WORK)

    assert paper.doi == "10.1038/nphys1170"
    assert paper.title == "Measured measurement"
    assert paper.authors == ("Markus Aspelmeyer",)
    assert paper.journal == "Nature Physics"
    assert paper.issn == ("1745-2473", "1745-2481")
    assert paper.published_date == "2009-01"
    assert paper.year == 2009
    assert paper.volume == "5"
    assert paper.issue == "1"
    assert paper.pages == "11-12"


def test_missing_required_doi():
    work = SAMPLE_WORK.copy()
    work.pop("DOI")

    with pytest.raises(MetadataParseError):
        parse_crossref_work(work)


def test_crossref_success(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "message": SAMPLE_WORK,
            },
        )

    monkeypatch.setattr(
        httpx,
        "get",
        fake_get,
    )

    paper = get_crossref_metadata(
        "10.1038/nphys1170"
    )

    assert paper.doi == "10.1038/nphys1170"
    assert paper.title == "Measured measurement"


def test_crossref_not_found(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(404)

    monkeypatch.setattr(
        httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataNotFoundError):
        get_crossref_metadata(
            "10.9999/not-real-doi"
        )


def test_crossref_rate_limit(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(429)

    monkeypatch.setattr(
        httpx,
        "get",
        fake_get,
    )

    with pytest.raises(RateLimitError):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )


def test_crossref_server_error(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(503)

    monkeypatch.setattr(
        httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataServiceError):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )


def test_crossref_timeout(monkeypatch):
    def fake_get(*args, **kwargs):
        request = httpx.Request(
            "GET",
            "https://api.crossref.org",
        )

        raise httpx.TimeoutException(
            "Timed out",
            request=request,
        )

    monkeypatch.setattr(
        httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataNetworkError):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )


def test_crossref_invalid_json(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            content=b"not valid json",
        )

    monkeypatch.setattr(
        httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )


def test_crossref_invalid_structure(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(
            200,
            json={
                "unexpected": "data",
            },
        )

    monkeypatch.setattr(
        httpx,
        "get",
        fake_get,
    )

    with pytest.raises(MetadataParseError):
        get_crossref_metadata(
            "10.1038/nphys1170"
        )