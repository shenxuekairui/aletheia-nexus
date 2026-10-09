from dataclasses import replace

import pytest

from aletheia_nexus.acquire.discovery.models import DiscoveryResult
from aletheia_nexus.acquire.fulltext.models import IdentityStatus
from aletheia_nexus.acquire.fulltext.orchestration import service
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    TitleSource,
)
from aletheia_nexus.acquire.fulltext.resolution.models import PageIdentityReport
from aletheia_nexus.acquire.metadata.titles import (
    page_validation_title,
    validation_title,
)
from aletheia_nexus.core.models import PaperMetadata

DOI = "10.1038/35104620"
ORIGINAL = "Materials for fuel-cell technologies"
TRANSLATION = "燃料电池技术的材料"


def metadata(**changes):
    return replace(
        PaperMetadata(
            doi=DOI,
            title=ORIGINAL,
            authors=(),
            journal=None,
            issn=(),
            published_date=None,
            year=None,
            publisher=None,
            work_type=None,
            volume=None,
            issue=None,
            pages=None,
            url=None,
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "requested,registered,expected",
    [
        (None, ORIGINAL, ORIGINAL),
        (TRANSLATION, ORIGINAL, ORIGINAL),
        ("Wrong English title", ORIGINAL, "Wrong English title"),
        ("中文题名", "不同的中文题名", "中文题名"),
        (TRANSLATION, None, TRANSLATION),
        (TRANSLATION, "123", TRANSLATION),
    ],
)
def test_only_missing_or_cross_language_titles_use_original(
    requested, registered, expected
):
    assert validation_title(requested, registered) == expected


@pytest.mark.parametrize(
    "dois,match,expected",
    [
        ((DOI,), True, ORIGINAL),
        (("10.1000/wrong",), False, TRANSLATION),
        ((DOI, "10.1000/other"), True, TRANSLATION),
        ((), False, TRANSLATION),
    ],
)
def test_page_title_requires_unique_matching_doi(dois, match, expected):
    identity = PageIdentityReport(
        status=IdentityStatus.MATCH,
        doi_match=match,
        metadata_dois=dois,
        metadata_title=ORIGINAL,
    )
    assert page_validation_title(DOI, TRANSLATION, identity) == expected


@pytest.mark.parametrize(
    "registered,expected,source",
    [
        (metadata(), ORIGINAL, TitleSource.METADATA),
        (None, TRANSLATION, TitleSource.USER),
        (metadata(doi="10.1000/wrong"), TRANSLATION, TitleSource.USER),
        (metadata(title="中文登记题名"), TRANSLATION, TitleSource.USER),
    ],
)
def test_translated_input_resolves_metadata_but_keeps_shared_pipeline(
    monkeypatch, tmp_path, registered, expected, source
):
    discovery = DiscoveryResult(doi=DOI, candidates=(), providers=())
    monkeypatch.setattr(service, "discover_full_text", lambda *a, **k: discovery)
    monkeypatch.setattr(service, "_metadata_lookup", lambda *a, **k: (registered, None))

    def acquire(value, **kwargs):
        assert kwargs["expected_title"] == expected
        return MultiRouteAcquisitionResult(
            doi=DOI,
            discovery=value,
            status=FullTextAcquisitionStatus.NO_CANDIDATES,
            expected_title=expected,
        )

    monkeypatch.setattr(service, "acquire_from_discovery", acquire)
    result = service.acquire_full_text(
        DOI, output_dir=tmp_path, expected_title=TRANSLATION
    )
    assert result.expected_title == expected and result.title_source == source
    assert result.requested_title == TRANSLATION


def test_no_auto_metadata_remains_off_for_translated_title(monkeypatch, tmp_path):
    discovery = DiscoveryResult(doi=DOI, candidates=(), providers=())
    monkeypatch.setattr(service, "discover_full_text", lambda *a, **k: discovery)
    monkeypatch.setattr(
        service, "_metadata_lookup", lambda *a, **k: pytest.fail("metadata disabled")
    )
    result = service.acquire_full_text(
        DOI,
        output_dir=tmp_path,
        expected_title=TRANSLATION,
        auto_metadata=False,
        use_doi_resolver_fallback=False,
    )
    assert result.expected_title == TRANSLATION
