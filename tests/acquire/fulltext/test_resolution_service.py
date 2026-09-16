from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import IdentityStatus
from aletheia_nexus.acquire.fulltext.resolution import service
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    PageType,
    ResolutionStatus,
    RetrievedPage,
)


def _candidate(
    url_type=CandidateUrlType.LANDING_PAGE, url="https://example.org/article"
):
    return FullTextCandidate(
        doi="10.1000/target",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=url_type,
    )


def _page(text, *, final_url="https://example.org/article", is_pdf=False):
    return RetrievedPage(
        requested_url="https://example.org/article",
        final_url=final_url,
        http_status=200,
        content_type="application/pdf" if is_pdf else "text/html",
        text=None if is_pdf else text,
        size_bytes=100,
        is_pdf_response=is_pdf,
        body_truncated=is_pdf,
    )


def test_matching_article_page_resolves_citation_pdf(monkeypatch):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: _page(
            '<meta name="citation_doi" content="10.1000/target">'
            '<meta name="citation_pdf_url" content="/paper.pdf">'
        ),
    )

    result = service.resolve_full_text_route(_candidate(), expected_title="Target")

    assert result.status == ResolutionStatus.RESOLVED
    assert result.page_type == PageType.ARTICLE
    assert result.identity is not None
    assert result.identity.status == IdentityStatus.MATCH
    assert result.candidates[0].candidate.url == "https://example.org/paper.pdf"


def test_page_with_explicit_different_doi_is_stopped_before_derivation(monkeypatch):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: _page(
            '<meta name="citation_doi" content="10.1000/other">'
            '<meta name="citation_pdf_url" content="/wrong.pdf">'
        ),
    )

    result = service.resolve_full_text_route(_candidate())

    assert result.status == ResolutionStatus.PAGE_MISMATCH
    assert result.candidates == ()


def test_challenge_page_returns_access_blocked(monkeypatch):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: _page("Checking your browser - verify you are human"),
    )

    result = service.resolve_full_text_route(_candidate())

    assert result.status == ResolutionStatus.ACCESS_BLOCKED
    assert result.page_type == PageType.CHALLENGE


def test_challenge_page_precedes_unrelated_title_identity_evidence(monkeypatch):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: _page(
            "<title>Attention Required</title>Checking your browser - verify you are human"
        ),
    )

    result = service.resolve_full_text_route(
        _candidate(),
        expected_title="Target scientific paper with an unrelated title",
    )

    assert result.status == ResolutionStatus.ACCESS_BLOCKED
    assert result.page_type == PageType.CHALLENGE
    assert result.identity is not None
    assert result.identity.status == IdentityStatus.UNKNOWN


def test_explicit_login_page_returns_auth_required(monkeypatch):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: _page(
            "Access through your institution to read this article"
        ),
    )

    result = service.resolve_full_text_route(_candidate())

    assert result.status == ResolutionStatus.AUTH_REQUIRED
    assert result.page_type == PageType.LOGIN


def test_matching_article_with_explicit_access_boundary_returns_auth_required(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: _page(
            '<meta name="citation_doi" content="10.1000/target">'
            '<meta name="citation_title" content="Target Paper">'
            "<body>Access through your institution to read this article</body>"
        ),
    )

    result = service.resolve_full_text_route(
        _candidate(), expected_title="Target Paper"
    )

    assert result.status == ResolutionStatus.AUTH_REQUIRED
    assert result.page_type == PageType.LOGIN
    assert result.identity is not None
    assert result.identity.status == IdentityStatus.MATCH
    assert result.candidates == ()


def test_direct_pdf_response_becomes_derived_candidate(monkeypatch):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: _page(
            None,
            final_url="https://cdn.example.org/paper.pdf",
            is_pdf=True,
        ),
    )

    result = service.resolve_full_text_route(_candidate())

    assert result.status == ResolutionStatus.RESOLVED
    assert result.page_type == PageType.PDF_RESPONSE
    assert result.candidates[0].method == DerivationMethod.DIRECT_PDF_RESPONSE
    assert result.candidates[0].candidate.url == "https://cdn.example.org/paper.pdf"


def test_unsupported_non_text_content_is_explicit(monkeypatch):
    monkeypatch.setattr(
        service,
        "retrieve_page",
        lambda *args, **kwargs: RetrievedPage(
            requested_url="https://example.org/article",
            final_url="https://example.org/article",
            http_status=200,
            content_type="application/zip",
            text=None,
            size_bytes=10,
        ),
    )

    result = service.resolve_full_text_route(_candidate())

    assert result.status == ResolutionStatus.INVALID_CONTENT


def test_http_pdf_route_derives_https_without_network(monkeypatch):
    def should_not_fetch(*args, **kwargs):
        raise AssertionError("PDF route resolution must not download the file")

    monkeypatch.setattr(service, "retrieve_page", should_not_fetch)

    result = service.resolve_full_text_route(
        _candidate(CandidateUrlType.PDF, "http://repo.example.org/paper.pdf")
    )

    assert result.status == ResolutionStatus.RESOLVED
    assert result.attempts == 0
    assert result.candidates[0].candidate.url == "https://repo.example.org/paper.pdf"


def test_https_pdf_route_has_no_additional_resolution_work(monkeypatch):
    def should_not_fetch(*args, **kwargs):
        raise AssertionError("PDF route resolution must not download the file")

    monkeypatch.setattr(service, "retrieve_page", should_not_fetch)

    result = service.resolve_full_text_route(
        _candidate(CandidateUrlType.PDF, "https://repo.example.org/paper.pdf")
    )

    assert result.status == ResolutionStatus.NO_FILE_CANDIDATES
    assert result.candidates == ()
