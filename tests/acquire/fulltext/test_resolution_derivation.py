from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.fulltext.models import DocumentRole
from aletheia_nexus.acquire.fulltext.resolution.derivation import (
    derive_https_upgrade,
    derive_pdf_candidates,
)
from aletheia_nexus.acquire.fulltext.resolution.models import DerivationMethod
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html


def _parent(url="https://example.org/article"):
    return FullTextCandidate(
        doi="10.1000/example",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX, DiscoveryProvider.UNPAYWALL),
        url_type=CandidateUrlType.LANDING_PAGE,
        access_type=AccessType.OPEN_ACCESS,
        version=FullTextVersion.PUBLISHED,
        host_type=HostType.PUBLISHER,
        license="cc-by",
        source_name="Example Journal",
        is_best=True,
    )


def test_citation_pdf_url_is_high_priority_article_candidate():
    parsed = parse_html(
        '<meta name="citation_pdf_url" content="/paper.pdf">'
        '<a href="/supp_si.pdf">Supporting Information</a>'
    )

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    assert candidates[0].candidate.url == "https://example.org/paper.pdf"
    assert candidates[0].method == DerivationMethod.CITATION_PDF_URL
    assert candidates[0].role_hint == DocumentRole.ARTICLE
    assert candidates[-1].role_hint == DocumentRole.SUPPLEMENT


def test_nature_style_auxiliary_pdfs_are_non_main_hints():
    parsed = parse_html(
        '<a href="/reporting-summary.pdf">Reporting Summary (download PDF)</a>'
        '<a href="/peer-review.pdf">Transparent Peer Review file (download PDF)</a>'
        '<a href="/source-data.pdf">Source Data (download PDF)</a>'
        '<a href="/supplement.pdf">Supplementary Information (download PDF)</a>'
    )

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )
    roles = {item.candidate.url: item.role_hint for item in candidates}

    assert roles["https://example.org/reporting-summary.pdf"] == DocumentRole.SUPPLEMENT
    assert roles["https://example.org/peer-review.pdf"] == DocumentRole.SUPPLEMENT
    assert roles["https://example.org/source-data.pdf"] == DocumentRole.SUPPLEMENT
    assert roles["https://example.org/supplement.pdf"] == DocumentRole.SUPPLEMENT


def test_auxiliary_filename_is_detected_even_without_anchor_text():
    parsed = parse_html('<a href="/reporting-summary.pdf">file</a>')

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    assert candidates[0].role_hint == DocumentRole.SUPPLEMENT


def test_relative_urls_honor_html_base_href():
    parsed = parse_html(
        '<base href="https://cdn.example.org/files/">'
        '<a href="paper.pdf">Download PDF</a>'
    )

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    assert candidates[0].candidate.url == "https://cdn.example.org/files/paper.pdf"


def test_duplicate_pdf_routes_merge_evidence():
    parsed = parse_html(
        '<meta name="citation_pdf_url" content="https://example.org/paper.pdf">'
        '<a href="https://example.org/paper.pdf">Download PDF</a>'
    )

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    same = [item for item in candidates if item.candidate.url.endswith("paper.pdf")]
    assert len(same) == 1
    assert len(same[0].evidence) == 2


def test_json_ld_pdf_is_extracted():
    parsed = parse_html(
        '<script type="application/ld+json">'
        '{"encoding":{"contentUrl":"/paper.pdf","fileFormat":"application/pdf"}}'
        "</script>"
    )

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    assert any(item.method == DerivationMethod.JSON_LD_PDF for item in candidates)


def test_inline_script_pdf_path_is_derived_without_publisher_specific_logic():
    parsed = parse_html(
        '<script>window.documentState={"pdfPath":"/iel7/123/456/05366888.pdf"};</script>'
    )

    candidates = derive_pdf_candidates(
        parent=_parent("https://ieeexplore.ieee.org/document/5366888/"),
        parsed=parsed,
        source_page_url="https://ieeexplore.ieee.org/document/5366888/",
    )

    assert len(candidates) == 1
    assert (
        candidates[0].candidate.url
        == "https://ieeexplore.ieee.org/iel7/123/456/05366888.pdf"
    )
    assert candidates[0].method == DerivationMethod.PDF_URL_PATTERN
    assert candidates[0].role_hint == DocumentRole.UNKNOWN
    assert "<script>" in candidates[0].evidence[0]


def test_inline_script_supplement_filename_keeps_non_main_role():
    parsed = parse_html(
        '<script>window.state={"file":"/files/supplement.pdf"};</script>'
    )

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    assert len(candidates) == 1
    assert candidates[0].role_hint == DocumentRole.SUPPLEMENT


def test_embedded_pdf_is_extracted():
    parsed = parse_html('<embed src="/paper" type="application/pdf">')

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    assert candidates[0].method == DerivationMethod.EMBEDDED_PDF
    assert candidates[0].candidate.url == "https://example.org/paper"


def test_javascript_mailto_and_fragment_links_are_ignored():
    parsed = parse_html(
        '<a href="javascript:void(0)">Download PDF</a>'
        '<a href="mailto:a@example.org">PDF</a>'
        '<a href="#pdf">PDF</a>'
    )

    assert (
        derive_pdf_candidates(
            parent=_parent(),
            parsed=parsed,
            source_page_url="https://example.org/article",
        )
        == ()
    )


def test_http_extracted_pdf_also_derives_https_alternative():
    parsed = parse_html(
        '<meta name="citation_pdf_url" content="http://files.example.org/a.pdf">'
    )

    candidates = derive_pdf_candidates(
        parent=_parent(),
        parsed=parsed,
        source_page_url="https://example.org/article",
    )

    urls = {item.candidate.url for item in candidates}
    assert "http://files.example.org/a.pdf" in urls
    assert "https://files.example.org/a.pdf" in urls
    assert any(item.method == DerivationMethod.HTTPS_UPGRADE for item in candidates)


def test_provider_http_pdf_can_be_upgraded_without_hiding_original_route():
    parent = FullTextCandidate(
        doi="10.1000/example",
        url="http://repo.example.org/paper.pdf",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
        host_type=HostType.REPOSITORY,
    )

    upgraded = derive_https_upgrade(parent)

    assert len(upgraded) == 1
    assert upgraded[0].candidate.url == "https://repo.example.org/paper.pdf"
    assert upgraded[0].parent_url == parent.url
    assert upgraded[0].method == DerivationMethod.HTTPS_UPGRADE
