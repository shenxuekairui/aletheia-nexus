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
    sources=(),
    request=None,
    **config,
):
    metadata = SimpleNamespace(
        title=metadata_title, journal=journal, publisher=publisher
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
