from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import BrowserAccessConfig, PaperRequest
from aletheia_nexus.acquire.access.cnki_routing import cnki_route_reason


def reason(
    doi="10.1000/test",
    title=None,
    metadata_title=None,
    journal=None,
    publisher=None,
    issn=(),
    sources=(),
    request=None,
    **config,
):
    metadata = SimpleNamespace(
        title=metadata_title, journal=journal, publisher=publisher, issn=issn
    )
    return cnki_route_reason(
        doi=doi,
        metadata=metadata,
        expected_title=title,
        config=BrowserAccessConfig(**config),
        source_urls=sources,
        request=request,
    )


@pytest.mark.parametrize(
    "doi", ["10.13822/j.cnki.hxsj.2024.0476", "10.7503/cjcu20250333"]
)
def test_cnki_doi_families_are_strong_routing_evidence(doi):
    assert reason(doi=doi, metadata_title="English translation") == "cnki_doi_family"


def test_plain_english_failure_is_not_a_cnki_signal():
    assert reason(title="An English paper") is None


@pytest.mark.parametrize(
    "doi", ["10.1000/test", "10.1016/example", "10.1038/example", "10.1109/example"]
)
def test_user_translation_does_not_redirect_foreign_metadata(doi):
    assert (
        reason(
            doi=doi,
            title="用户给出的中文译名",
            metadata_title="Original English article",
        )
        is None
    )


def test_chinese_metadata_and_journal_but_not_translation_allow_cnki():
    assert reason(metadata_title="真实中文文献") == "chinese_metadata_title"
    assert (
        reason(metadata_title="English title", journal="高等学校化学学报")
        == "chinese_journal"
    )
    assert reason(title="待检索的中文文献") == "chinese_title_fallback"


@pytest.mark.parametrize(
    "url", ["https://cnki.net/article", "https://kns.cnki.net/article"]
)
def test_observed_cnki_source_is_authoritative(url):
    assert reason(metadata_title="English", sources=(url,)) == "observed_cnki_source"
    assert reason(sources=(url,), cnki_enabled=False) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://cnki.net.evil.example/article",
        "https://evil.example/cnki.net",
        "https://[broken",
    ],
)
def test_unrelated_or_invalid_sources_not_routed(url):
    assert reason(sources=(url,)) is None


def test_explicit_opt_in_and_record_id():
    assert (
        reason(title="English", cnki_search_all_titles=True)
        == "explicit_all_titles_opt_in"
    )
    assert (
        reason(request=PaperRequest(title="English", cnki_id="cnki:cjfd:test"))
        == "explicit_cnki_record"
    )
    assert reason(cnki_search_all_titles=True, cnki_enabled=False) is None


@pytest.mark.parametrize("issn", ["2993-074X", "2993074x", "1006-3471"])
def test_first_seen_english_article_routes_by_reviewed_issn_without_history(
    issn, monkeypatch
):
    from pathlib import Path

    monkeypatch.setattr(
        Path, "home", lambda: pytest.fail("Routing must not read history")
    )
    result = reason(
        doi="10.9999/previously-unseen",
        metadata_title="An English article",
        journal="Journal of Electrochemistry",
        issn=(issn,),
    )
    assert result.startswith("cnki_indexed_issn:")
    assert "https://electrochem.xmu.edu.cn/CN/column/column1.shtml" in result


@pytest.mark.parametrize(
    "issn", [(), ("2993-0740",), ("prefix2993-074X",), ("0028-0836",), "2993-074X"]
)
def test_missing_invalid_or_unlisted_issn_does_not_infer_cnki_from_english_name(issn):
    assert (
        reason(
            doi="10.61558/unseen",
            metadata_title="An English article",
            journal="Journal of Electrochemistry",
            issn=issn,
        )
        is None
    )


def test_indexed_issn_respects_disabled_provider():
    assert reason(issn=("2993-074X",), cnki_enabled=False) is None


def test_catalog_identifiers_have_valid_checksums_and_evidence():
    from aletheia_nexus.acquire.access.cnki_journals import CNKI_INDEXED_JOURNALS, _issn

    for journal in CNKI_INDEXED_JOURNALS:
        assert all(_issn(value) == value for value in journal.issns)
        assert journal.evidence_url.startswith("https://") and journal.reviewed_on
        assert not journal.doi_patterns or journal.doi_evidence_urls


@pytest.mark.parametrize(
    "doi",
    [
        "10.61558/2993-074X.3619",
        "10.61558/2993-074x.3495",
        "10.61558/2993-074X.123456789",
    ],
)
def test_reviewed_doi_journal_namespace_routes_without_title_issn_or_history(
    doi, monkeypatch
):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: pytest.fail("No history lookup"))
    result = cnki_route_reason(
        doi=doi, metadata=None, expected_title=None, config=BrowserAccessConfig()
    )
    assert result.startswith("cnki_journal_doi_pattern;")


@pytest.mark.parametrize(
    "doi",
    [
        "10.61558/other.3619",
        "10.9999/2993-074X.3619",
        "10.61558/2993-074X.",
        "10.61558/2993-074X.3619/supplement",
        "10.61558/2993-074X.3619extra",
        "10.61558/2993-0740.3619",
    ],
)
def test_doi_issuer_alone_or_similar_suffix_is_not_cnki_evidence(doi):
    assert reason(doi=doi, metadata_title="An English article") is None


def test_doi_hint_cannot_override_conflicting_issn_or_disable_switch():
    doi = "10.61558/2993-074X.3619"
    assert (
        reason(doi=doi, metadata_title="English article", issn=("0028-0836",)) is None
    )
    assert reason(doi=doi, cnki_enabled=False) is None
