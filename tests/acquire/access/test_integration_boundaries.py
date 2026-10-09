"""Public/CNKI boundaries shared by the integrated acquisition entry points."""

from pathlib import Path

import pytest

from aletheia_nexus.acquire.access import BrowserAccessConfig
from aletheia_nexus.acquire.access.browser import browser_profile_dir
from aletheia_nexus.acquire.access.browser_engine import runtime
from aletheia_nexus.acquire.access.browser_route import _dedupe_candidates
from aletheia_nexus.acquire.access.cnki_provider import _transport_failure_code
from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.resolution.derivation import _dedupe_and_rank
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    DerivedFullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.urls import is_known_non_article_asset


def test_conflicting_browser_network_modes_rejected():
    with pytest.raises(ValueError, match="direct_connection"):
        browser_profile_dir(
            BrowserAccessConfig(direct_connection=True, use_system_proxy=True)
        )


@pytest.mark.parametrize(
    "url,excluded",
    [
        ("https://a.cnki.net/gw/api/get/pdf/ads/123", True),
        ("https://a.cnki.net/gw/api/get/pdf/ads/123?x=1", True),
        ("https://a.cnki.net/article.pdf", False),
        ("https://kns.cnki.net/pdf/123", False),
        ("https://publisher.example/gw/api/get/pdf/ads/article.pdf", False),
        ("https://a.cnki.net.evil.example/gw/api/get/pdf/ads/123", False),
    ],
)
def test_only_known_cnki_advertising_pdf_is_excluded(url, excluded):
    assert is_known_non_article_asset(url) is excluded
    candidate = FullTextCandidate(doi="10.1000/one", url=url, provenance=())
    assert bool(_dedupe_candidates([candidate], limit=1)) is not excluded
    derived = DerivedFullTextCandidate(
        candidate=candidate,
        parent_url=url,
        source_page_url=url,
        method=DerivationMethod.CITATION_PDF_URL,
    )
    assert bool(_dedupe_and_rank([derived])) is not excluded


def test_portable_runtime_versions_sort_numerically(monkeypatch, tmp_path):
    if runtime.os.name != "nt" and not runtime.sys.platform.startswith("linux"):
        pytest.skip("Only supported portable platforms")
    suffix = (
        "chrome-win64/chrome.exe"
        if runtime.os.name == "nt"
        else "chrome-linux64/chrome"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(runtime, "windows_browser_major", lambda p: 155)
    paths = []
    for version in ("155.0.9.1", "155.0.10.1"):
        path = (
            tmp_path / ".aletheia-nexus/browser-runtimes" / f"chrome-{version}" / suffix
        )
        path.parent.mkdir(parents=True)
        path.touch()
        paths.append(path)
    assert runtime.fixed_portable_browser() == paths[1]


@pytest.mark.parametrize(
    "message,code",
    [
        ("Timeout 45000ms exceeded", "timeout"),
        ("read ECONNRESET", "connection_reset"),
        ("getaddrinfo ENOTFOUND", "dns_error"),
        ("certificate has expired", "tls_error"),
        ("Target page, context or browser has been closed", "browser_closed"),
        ("connect ECONNREFUSED", "connection_refused"),
        ("Unexpected failure", "transport_error"),
    ],
)
def test_transport_diagnostics_do_not_disclose_credentials(message, code):
    assert (
        _transport_failure_code(
            RuntimeError(message + " https://example.test?token=private")
        )
        == code
    )
