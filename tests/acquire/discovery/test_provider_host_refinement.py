from aletheia_nexus.acquire.discovery.models import HostType
from aletheia_nexus.acquire.discovery.openalex import discover_openalex
from aletheia_nexus.acquire.discovery.unpaywall import discover_unpaywall


def test_openalex_refines_resolver_and_index_routes(monkeypatch):
    payload = {
        "doi": "10.1000/test",
        "best_oa_location": None,
        "locations": [
            {
                "is_oa": False,
                "landing_page_url": "https://doi.org/10.1000/test",
                "pdf_url": None,
                "version": "publishedVersion",
                "source": {"display_name": "Example Journal", "type": "journal"},
            },
            {
                "is_oa": False,
                "landing_page_url": "https://pubmed.ncbi.nlm.nih.gov/12345",
                "pdf_url": None,
                "version": "publishedVersion",
                "source": {"display_name": "PubMed", "type": "repository"},
            },
        ],
    }
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.openalex.get_json",
        lambda *args, **kwargs: payload,
    )

    result = discover_openalex("10.1000/test")

    assert result[0].host_type == HostType.RESOLVER
    assert result[1].host_type == HostType.INDEX


def test_unpaywall_refines_handle_route_to_resolver(monkeypatch):
    payload = {
        "doi": "10.1000/test",
        "oa_locations": [
            {
                "url_for_pdf": "https://hdl.handle.net/10379/15835",
                "url_for_landing_page": None,
                "version": "submittedVersion",
                "host_type": "repository",
                "is_best": True,
            }
        ],
    }
    monkeypatch.setattr(
        "aletheia_nexus.acquire.discovery.unpaywall.get_json",
        lambda *args, **kwargs: payload,
    )

    result = discover_unpaywall("10.1000/test", email="person@example.org")

    assert result[0].host_type == HostType.RESOLVER
