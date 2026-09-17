from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    HostType,
)
from aletheia_nexus.acquire.fulltext.orchestration.route_expansion import (
    RouteExpansionMethod,
    derive_route_expansions,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    ResolutionStatus,
    RetrievedPage,
    RouteResolutionResult,
)


def _candidate(url="https://bridge.example.org/article") -> FullTextCandidate:
    return FullTextCandidate(
        doi="10.1000/example",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.LANDING_PAGE,
        host_type=HostType.RESOLVER,
    )


def _resolution(
    parent: FullTextCandidate,
    html: str,
    *,
    final_url: str | None = None,
    status: ResolutionStatus = ResolutionStatus.NO_FILE_CANDIDATES,
):
    page = RetrievedPage(
        requested_url=parent.url,
        final_url=final_url or parent.url,
        http_status=200,
        content_type="text/html",
        text=html,
        size_bytes=len(html.encode()),
    )
    return RouteResolutionResult(
        source_candidate=parent,
        status=status,
        page=page,
        attempts=1,
    )


def test_canonical_and_meta_refresh_are_high_confidence_routes():
    parent = _candidate()
    result = _resolution(
        parent,
        '<meta http-equiv="refresh" content="0; URL=https://publisher.example.org/paper">'
        '<link rel="canonical" href="https://publisher.example.org/article">',
    )

    routes = derive_route_expansions(parent=parent, resolution=result)

    assert [item.method for item in routes[:2]] == [
        RouteExpansionMethod.META_REFRESH,
        RouteExpansionMethod.CANONICAL,
    ]
    assert routes[0].candidate.url == "https://publisher.example.org/paper"


def test_scholarly_json_ld_article_url_is_followed():
    parent = _candidate()
    result = _resolution(
        parent,
        '<script type="application/ld+json">'
        '{"@type":"ScholarlyArticle","url":"https://publisher.example.org/full"}'
        "</script>",
    )

    routes = derive_route_expansions(parent=parent, resolution=result)

    assert len(routes) == 1
    assert routes[0].method == RouteExpansionMethod.JSON_LD_ARTICLE_URL
    assert routes[0].candidate.url == "https://publisher.example.org/full"


def test_nested_json_ld_people_and_images_are_not_article_routes():
    parent = _candidate()
    result = _resolution(
        parent,
        '<script type="application/ld+json">'
        '{"@type":"ScholarlyArticle",'
        '"url":"https://publisher.example.org/article",'
        '"author":[{"@type":"Person","url":"https://orcid.org/0000-0001"}],'
        '"image":{"@type":"ImageObject","url":"https://publisher.example.org/logo.png"}}'
        "</script>",
    )

    routes = derive_route_expansions(parent=parent, resolution=result)

    assert [item.candidate.url for item in routes] == [
        "https://publisher.example.org/article"
    ]


def test_semantic_full_text_and_open_manuscript_links_are_followed():
    parent = _candidate()
    result = _resolution(
        parent,
        '<a href="/full">View full text</a>'
        '<a href="/manuscript">View Open Manuscript</a>',
    )

    routes = derive_route_expansions(parent=parent, resolution=result)
    urls = {item.candidate.url for item in routes}

    assert "https://bridge.example.org/full" in urls
    assert "https://bridge.example.org/manuscript" in urls
    assert all(
        item.method == RouteExpansionMethod.SEMANTIC_ARTICLE_LINK for item in routes
    )


def test_redirect_wrapper_exposes_direct_target_before_wrapper():
    parent = _candidate()
    target = "https://publisher.example.org/article?id=123"
    wrapped = (
        "https://bridge.example.org/go?"
        "Redirect=https%3A%2F%2Fpublisher.example.org%2Farticle%3Fid%3D123"
    )
    result = _resolution(parent, f'<a href="{wrapped}">View article</a>')

    routes = derive_route_expansions(parent=parent, resolution=result)

    assert routes[0].method == RouteExpansionMethod.REDIRECT_TARGET
    assert routes[0].candidate.url == target
    assert routes[0].parent_url == wrapped
    assert any(item.candidate.url == wrapped for item in routes)


def test_target_doi_link_is_followed_but_other_doi_is_not():
    parent = _candidate()
    result = _resolution(
        parent,
        '<a href="https://publisher.example.org/doi/full/10.1000/example">target</a>'
        '<a href="https://publisher.example.org/doi/full/10.2000/other">reference</a>',
    )

    routes = derive_route_expansions(parent=parent, resolution=result)

    assert len(routes) == 1
    assert routes[0].method == RouteExpansionMethod.TARGET_DOI_LINK
    assert "10.1000/example" in routes[0].candidate.url


def test_target_doi_in_query_requires_article_semantics():
    parent = _candidate()
    result = _resolution(
        parent,
        '<a href="https://utility.example.org/lookup?doi=10.1000%2Fexample">utility</a>'
        '<a href="https://publisher.example.org/open?doi=10.1000%2Fexample">View article</a>',
    )

    routes = derive_route_expansions(parent=parent, resolution=result)

    assert len(routes) == 1
    assert routes[0].candidate.url.startswith("https://publisher.example.org/open?")
    assert routes[0].method == RouteExpansionMethod.SEMANTIC_ARTICLE_LINK


def test_non_article_target_doi_utilities_are_not_expanded():
    parent = _candidate()
    result = _resolution(
        parent,
        '<a href="https://pubads.example.org/jump?doi=10.1000%2Fexample">Ad</a>'
        '<a href="https://citation.example.org/v2/references/10.1000/example?format=refman">References</a>'
        '<a href="https://rights.example.org/?contentID=10.1000%2Fexample">Rights and permissions</a>'
        '<a href="https://crossmark.crossref.org/dialog/?doi=10.1000%2Fexample">Crossmark</a>',
    )

    assert derive_route_expansions(parent=parent, resolution=result) == ()


def test_pdf_and_static_assets_are_not_page_expansions():
    parent = _candidate()
    result = _resolution(
        parent,
        '<link rel="canonical" href="/paper.pdf">'
        '<a href="/download.pdf">View article</a>'
        '<a href="/logo.png">View article</a>',
    )

    assert derive_route_expansions(parent=parent, resolution=result) == ()


def test_access_boundary_pages_are_not_expanded():
    parent = _candidate()
    result = _resolution(
        parent,
        '<a href="https://publisher.example.org/article">View article</a>',
        status=ResolutionStatus.AUTH_REQUIRED,
    )

    assert derive_route_expansions(parent=parent, resolution=result) == ()


def test_source_and_parent_urls_are_not_requeued():
    parent = _candidate("https://bridge.example.org/start")
    result = _resolution(
        parent,
        '<link rel="canonical" href="https://bridge.example.org/final">'
        '<a href="https://bridge.example.org/start">View article</a>',
        final_url="https://bridge.example.org/final",
    )

    assert derive_route_expansions(parent=parent, resolution=result) == ()


def test_expansion_count_is_bounded_and_ranked():
    parent = _candidate()
    result = _resolution(
        parent,
        '<meta name="citation_fulltext_html_url" content="/meta">'
        '<link rel="canonical" href="/canonical">'
        '<a href="/one">View article</a>'
        '<a href="/two">Full text</a>',
    )

    routes = derive_route_expansions(
        parent=parent,
        resolution=result,
        max_candidates=2,
    )

    assert len(routes) == 2
    assert routes[0].method == RouteExpansionMethod.CITATION_HTML_URL
    assert routes[1].method == RouteExpansionMethod.CANONICAL
