from dataclasses import replace

import pytest

from aletheia_nexus.acquire.discovery import crossref
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    FullTextVersion,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.metadata.crossref import parse_crossref_work
from aletheia_nexus.acquire.metadata.exceptions import MetadataNetworkError


def _work():
    return {
        "DOI": "10.1000/target",
        "title": ["Target Article"],
        "URL": "https://doi.org/10.1000/target",
        "resource": {"primary": {"URL": "https://publisher.example/article"}},
        "link": [
            {
                "URL": "https://files.example/opaque",
                "content-type": "application/pdf",
                "content-version": "vor",
                "intended-application": "text-mining",
            }
        ],
    }


def test_optional_links_survive_metadata_and_become_typed_candidates():
    metadata = parse_crossref_work(_work())
    assert metadata.links[0].intended_application == "text-mining"
    assert metadata.links[0].content_type == "application/pdf"
    assert metadata.links[1].relation == "primary"
    candidates = crossref.candidates_from_metadata(metadata)
    assert [c.url_type for c in candidates] == [
        CandidateUrlType.PDF,
        CandidateUrlType.LANDING_PAGE,
    ]
    assert candidates[0].version == FullTextVersion.PUBLISHED
    assert candidates[0].access_type == AccessType.UNKNOWN
    assert candidates[0].provenance == (DiscoveryProvider.CROSSREF,)


@pytest.mark.parametrize("links", [None, 7, {}, [None, {}, {"URL": []}]])
def test_bad_optional_links_do_not_break_bibliography(links):
    work = _work()
    work.update(link=links, resource={"primary": None})
    metadata = parse_crossref_work(work)
    assert metadata.title == "Target Article"
    assert metadata.links == ()


def test_filters_non_pdf_apis_restricted_purposes_and_unsafe_urls():
    work = _work()
    work["resource"] = {"primary": {"URL": work["URL"]}}
    work["link"] += [
        {"URL": "https://files.example/only.xml", "content-type": "text/xml"},
        {"URL": "https://files.example/text", "content-type": "text/plain"},
        {
            "URL": "https://files.example/check.pdf",
            "intended-application": "similarity-checking",
        },
        {"URL": "javascript:download()", "content-type": "application/pdf"},
        {"URL": "https://user:secret@files.example/file.pdf"},
        {"URL": "file:///tmp/file.pdf"},
        {"URL": "https://files.example/opaque#top", "content-type": "application/pdf"},
    ]
    candidates = crossref.candidates_from_metadata(parse_crossref_work(work))
    assert [c.url for c in candidates] == ["https://files.example/opaque"]


def test_unspecified_pdf_and_html_links_remain_candidates():
    work = _work()
    work["link"] = [
        {"URL": "https://files.example/doi/pdf/opaque", "content-type": "unspecified"},
        {
            "URL": "https://files.example/article",
            "content-type": "text/html; charset=UTF-8",
        },
        {"URL": "https://files.example/download"},
    ]
    candidates = crossref.candidates_from_metadata(parse_crossref_work(work))
    types = {c.url: c.url_type for c in candidates}
    assert types["https://files.example/doi/pdf/opaque"] == CandidateUrlType.PDF
    assert types["https://files.example/article"] == CandidateUrlType.LANDING_PAGE
    assert types["https://files.example/download"] == CandidateUrlType.UNKNOWN


def test_reuses_metadata_without_fetch_and_excludes_seen_redirects(monkeypatch):
    monkeypatch.setattr(
        crossref,
        "get_crossref_metadata",
        lambda *a, **k: pytest.fail("duplicate lookup"),
    )
    metadata = parse_crossref_work(_work())
    result, reused = crossref.discover_crossref_supplement(
        metadata.doi,
        metadata=metadata,
        excluded_urls=["https://files.example/opaque#page=1"],
    )
    assert result.attempts == 0
    assert reused is metadata
    assert [c.url for c in result.candidates] == ["https://publisher.example/article"]


@pytest.mark.parametrize(
    "options",
    [
        {"allow_lookup": False},
        {"metadata_error": "earlier lookup failed"},
        {"limit": 0},
    ],
)
def test_disabled_failed_or_budget_exhausted_never_looks_up(monkeypatch, options):
    monkeypatch.setattr(
        crossref,
        "get_crossref_metadata",
        lambda *a, **k: pytest.fail("unneeded lookup"),
    )
    result, _ = crossref.discover_crossref_supplement("10.1000/target", **options)
    assert result.status == ProviderDiscoveryStatus.SKIPPED
    assert result.attempts == 0


def test_fallback_lookup_is_one_request_even_when_network_fails(monkeypatch):
    calls = []

    def lookup(*args, **kwargs):
        calls.append(args)
        raise MetadataNetworkError("offline")

    monkeypatch.setattr(crossref, "get_crossref_metadata", lookup)
    result, _ = crossref.discover_crossref_supplement("10.1000/target")
    assert result.status == ProviderDiscoveryStatus.NETWORK_ERROR
    assert result.candidates == ()
    assert result.attempts == len(calls) == 1


def test_mismatched_doi_never_produces_candidates():
    metadata = replace(parse_crossref_work(_work()), doi="10.1000/other")
    result, _ = crossref.discover_crossref_supplement(
        "10.1000/target", metadata=metadata
    )
    assert result.status == ProviderDiscoveryStatus.PARSE_ERROR
    assert result.candidates == ()


def test_bounded_supplement_and_empty_existing_metadata(monkeypatch):
    work = _work()
    work["link"] = [{"URL": f"https://files.example/{n}.pdf"} for n in range(20)]
    metadata = parse_crossref_work(work)
    for limit, expected in [(99, 4), (2, 2)]:
        result, _ = crossref.discover_crossref_supplement(
            metadata.doi, metadata=metadata, limit=limit
        )
        assert len(result.candidates) == expected
    monkeypatch.setattr(
        crossref, "get_crossref_metadata", lambda *a, **k: pytest.fail("repeat lookup")
    )
    result, _ = crossref.discover_crossref_supplement(
        metadata.doi, metadata=replace(metadata, links=())
    )
    assert result.status == ProviderDiscoveryStatus.NO_CANDIDATES
