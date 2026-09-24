"""Publisher hooks stay narrow and never replace shared PDF verification."""

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport
from aletheia_nexus.acquire.access.publisher_adapters import (
    adapter_for_url,
    canonical_pdf_route,
)


def test_adapter_selection_is_exact_host_and_safe_port():
    assert adapter_for_url("https://ieeexplore.ieee.org/document/1").name == "ieee"
    assert adapter_for_url("https://ieeexplore.ieee.org.evil.test/document/1").name == (
        "generic"
    )
    assert adapter_for_url("https://ieeexplore.ieee.org:8443/document/1").name == (
        "generic"
    )
    assert adapter_for_url("https://user@ieeexplore.ieee.org/document/1").name == (
        "generic"
    )


def test_doi_resolver_adapter_requires_matching_publisher_prefix():
    assert adapter_for_url("https://doi.org/10.1021/jacs.6c03536").name == ("generic")
    assert (
        adapter_for_url(
            "https://doi.org/10.1021/jacs.6c03536",
            doi="10.1021/jacs.6c03536",
        ).name
        == "acs"
    )
    assert (
        canonical_pdf_route(
            "10.1038/s41586-026-11008-2",
            "https://doi.org/10.1021/jacs.6c03536",
        )
        is None
    )
    assert canonical_pdf_route("10.1021/example", "https://[invalid") is None


def test_rsc_and_sciencedirect_open_pdf_in_tab_before_extra_request():
    assert adapter_for_url(
        "https://pubs.rsc.org/en/content/articlepdf/2026/ta/example"
    ).prefer_browser_pdf_navigation()
    assert adapter_for_url(
        "https://www.sciencedirect.com/science/article/pii/example/pdfft"
    ).prefer_browser_pdf_navigation()
    assert not adapter_for_url(
        "https://pubs.rsc.org.evil.test/articlepdf/example"
    ).prefer_browser_pdf_navigation()
    assert not adapter_for_url(
        "https://pubs.acs.org/doi/pdf/10.1021/example"
    ).prefer_browser_pdf_navigation()


def test_thieme_entitlement_hook_only_applies_to_its_abstract_page():
    adapter = adapter_for_url(
        "https://www.thieme-connect.com/products/ejournals/abstract/10.1055/a-test"
    )
    report = ChallengeReport(kind=ChallengeKind.NONE)
    from urllib.parse import urlsplit

    abstract = urlsplit(
        "https://www.thieme-connect.com/products/ejournals/abstract/10.1055/a-test"
    )
    pdf = urlsplit(
        "https://www.thieme-connect.com/products/ejournals/pdf/10.1055/a-test.pdf"
    )
    assert adapter.refine_non_pdf_challenge(abstract, "Buy Article", report).kind == (
        ChallengeKind.ENTITLEMENT
    )
    assert adapter.refine_non_pdf_challenge(pdf, "Buy Article", report) == report
