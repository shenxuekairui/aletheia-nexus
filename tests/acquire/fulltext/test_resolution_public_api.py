from aletheia_nexus.acquire.fulltext import (
    DerivationMethod,
    DerivedFullTextCandidate,
    PageIdentityReport,
    PageType,
    ResolutionStatus,
    RetrievedPage,
    RouteResolutionResult,
    resolve_full_text_route,
)


def test_resolution_symbols_are_exposed_from_fulltext_package():
    assert ResolutionStatus.RESOLVED.value == "RESOLVED"
    assert PageType.ARTICLE.value == "ARTICLE"
    assert DerivationMethod.CITATION_PDF_URL.value == "CITATION_PDF_URL"
    assert DerivedFullTextCandidate is not None
    assert PageIdentityReport is not None
    assert RetrievedPage is not None
    assert RouteResolutionResult is not None
    assert callable(resolve_full_text_route)
