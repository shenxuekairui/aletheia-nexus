import pytest

from aletheia_nexus.acquire.discovery.exceptions import DiscoveryParseError
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.discovery.openalex import discover_openalex


def test_discover_openalex_parses_locations(monkeypatch):
    payload = {
        "doi": "https://doi.org/10.1000/test",
        "best_oa_location": {
            "id": "pmh:repo:1",
            "pdf_url": "https://repo.example.org/paper.pdf",
        },
        "locations": [
            {
                "id": "pmh:repo:1",
                "is_oa": True,
                "landing_page_url": "https://repo.example.org/item/1",
                "pdf_url": "https://repo.example.org/paper.pdf",
                "license": "cc-by",
                "version": "acceptedVersion",
                "source": {
                    "display_name": "Example Repository",
                    "type": "repository",
                },
            }
        ],
    }

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.openalex.get_json",
        lambda *args, **kwargs: payload,
    )

    result = discover_openalex("10.1000/test")

    assert len(result) == 2
    assert result[0].url_type == CandidateUrlType.PDF
    assert result[0].access_type == AccessType.OPEN_ACCESS
    assert result[0].version == FullTextVersion.ACCEPTED
    assert result[0].host_type == HostType.REPOSITORY
    assert result[0].source_name == "Example Repository"
    assert result[0].is_best is True


def test_discover_openalex_normalizes_wrapped_candidate_url(monkeypatch):
    clean_url = "https://doi.org/10.1038/nphys1170"
    payload = {
        "doi": "10.1038/nphys1170",
        "best_oa_location": None,
        "locations": [
            {
                "is_oa": False,
                "landing_page_url": f"[{clean_url}]({clean_url})",
                "pdf_url": None,
                "license": None,
                "version": "publishedVersion",
                "source": {
                    "display_name": "Nature Physics",
                    "type": "journal",
                },
            }
        ],
    }

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.openalex.get_json",
        lambda *args, **kwargs: payload,
    )

    result = discover_openalex("10.1038/nphys1170")

    assert result[0].url == clean_url


def test_discover_openalex_rejects_invalid_candidate_url(monkeypatch):
    payload = {
        "doi": "10.1000/test",
        "best_oa_location": None,
        "locations": [
            {
                "is_oa": False,
                "landing_page_url": "not-a-url",
                "pdf_url": None,
                "version": "publishedVersion",
                "source": {"display_name": "Example Journal", "type": "journal"},
            }
        ],
    }

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.openalex.get_json",
        lambda *args, **kwargs: payload,
    )

    with pytest.raises(DiscoveryParseError):
        discover_openalex("10.1000/test")


def test_discover_openalex_rejects_identity_mismatch(monkeypatch):
    payload = {
        "doi": "https://doi.org/10.1000/other",
        "best_oa_location": None,
        "locations": [],
    }

    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.openalex.get_json",
        lambda *args, **kwargs: payload,
    )

    with pytest.raises(DiscoveryParseError):
        discover_openalex("10.1000/test")
