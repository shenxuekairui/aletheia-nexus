import pytest

from aletheia_nexus.acquire.discovery.exceptions import DiscoveryParseError
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.discovery.unpaywall import discover_unpaywall


def test_discover_unpaywall_parses_pdf_and_landing_page(monkeypatch):
    payload = {
        "doi": "10.1000/test",
        "oa_locations": [
            {
                "url_for_pdf": "https://example.org/paper.pdf",
                "url_for_landing_page": "https://example.org/article",
                "url": "https://example.org/paper.pdf",
                "version": "publishedVersion",
                "host_type": "publisher",
                "license": "cc-by",
                "is_best": True,
            }
        ],
    }

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.unpaywall.get_json",
        lambda *args, **kwargs: payload,
    )

    result = discover_unpaywall("10.1000/TEST", email="person@example.org")

    assert len(result) == 2
    assert result[0].url_type == CandidateUrlType.PDF
    assert result[0].version == FullTextVersion.PUBLISHED
    assert result[0].host_type == HostType.PUBLISHER
    assert result[0].license == "cc-by"
    assert result[0].is_best is True
    assert result[1].url_type == CandidateUrlType.LANDING_PAGE


def test_discover_unpaywall_normalizes_wrapped_candidate_url(monkeypatch):
    clean_url = "https://example.org/paper.pdf"
    payload = {
        "doi": "10.1000/test",
        "oa_locations": [
            {
                "url_for_pdf": f"[{clean_url}]({clean_url})",
                "url_for_landing_page": None,
                "url": clean_url,
                "version": "publishedVersion",
                "host_type": "publisher",
                "is_best": True,
            }
        ],
    }

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.unpaywall.get_json",
        lambda *args, **kwargs: payload,
    )

    result = discover_unpaywall("10.1000/test", email="person@example.org")

    assert result[0].url == clean_url


def test_discover_unpaywall_rejects_invalid_candidate_url(monkeypatch):
    payload = {
        "doi": "10.1000/test",
        "oa_locations": [
            {
                "url_for_pdf": "javascript:alert(1)",
                "url_for_landing_page": None,
                "version": "publishedVersion",
                "host_type": "publisher",
            }
        ],
    }

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.unpaywall.get_json",
        lambda *args, **kwargs: payload,
    )

    with pytest.raises(DiscoveryParseError):
        discover_unpaywall("10.1000/test", email="person@example.org")
