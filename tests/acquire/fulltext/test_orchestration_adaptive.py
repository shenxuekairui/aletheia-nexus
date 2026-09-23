from dataclasses import replace

from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    HostType,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    DocumentRole,
)
from aletheia_nexus.acquire.fulltext.orchestration import service
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    RouteCandidateOrigin,
)
from aletheia_nexus.acquire.fulltext.orchestration.route_expansion import (
    ExpandedRouteCandidate,
    RouteExpansionMethod,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    DerivedFullTextCandidate,
    ResolutionStatus,
    RetrievedPage,
    RouteResolutionResult,
)


def _candidate(
    url: str,
    *,
    url_type: CandidateUrlType = CandidateUrlType.LANDING_PAGE,
    host_type: HostType = HostType.UNKNOWN,
    access_type: AccessType = AccessType.UNKNOWN,
) -> FullTextCandidate:
    return FullTextCandidate(
        doi="10.1000/target",
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=url_type,
        host_type=host_type,
        access_type=access_type,
    )


def _discovery(*candidates: FullTextCandidate) -> DiscoveryResult:
    return DiscoveryResult(
        doi="10.1000/target",
        candidates=tuple(candidates),
        providers=(
            ProviderDiscoveryResult(
                provider=DiscoveryProvider.OPENALEX,
                status=(
                    ProviderDiscoveryStatus.SUCCESS
                    if candidates
                    else ProviderDiscoveryStatus.NO_CANDIDATES
                ),
                candidates=tuple(candidates),
            ),
            ProviderDiscoveryResult(
                provider=DiscoveryProvider.UNPAYWALL,
                status=ProviderDiscoveryStatus.SKIPPED,
                candidates=(),
            ),
        ),
    )


def _page_result(
    candidate: FullTextCandidate, *, status=ResolutionStatus.NO_FILE_CANDIDATES
):
    html = "<html><body>bridge</body></html>"
    return RouteResolutionResult(
        source_candidate=candidate,
        status=status,
        page=RetrievedPage(
            requested_url=candidate.url,
            final_url=candidate.url,
            http_status=200,
            content_type="text/html",
            text=html,
            size_bytes=len(html),
        ),
        attempts=1,
    )


def test_page_expansion_is_followed_until_verified(monkeypatch, tmp_path):
    start = _candidate("https://bridge.example/start")
    second = replace(start, url="https://publisher.example/article")
    pdf = replace(
        second,
        url="https://publisher.example/article.pdf",
        url_type=CandidateUrlType.PDF,
    )
    calls: list[str] = []

    def resolve(candidate, **kwargs):
        calls.append(candidate.url)
        if candidate.url == second.url:
            derived = DerivedFullTextCandidate(
                candidate=pdf,
                parent_url=second.url,
                source_page_url=second.url,
                method=DerivationMethod.CITATION_PDF_URL,
                role_hint=DocumentRole.ARTICLE,
                evidence=("citation_pdf_url",),
                priority=100,
            )
            return RouteResolutionResult(
                source_candidate=candidate,
                status=ResolutionStatus.RESOLVED,
                candidates=(derived,),
                page=_page_result(candidate).page,
                attempts=1,
            )
        return _page_result(candidate)

    def expand(*, parent, resolution, max_candidates):
        if parent.url != start.url:
            return ()
        return (
            ExpandedRouteCandidate(
                candidate=second,
                parent_url=start.url,
                source_page_url=start.url,
                method=RouteExpansionMethod.CANONICAL,
                evidence=("canonical",),
                priority=900,
            ),
        )

    monkeypatch.setattr(service, "resolve_full_text_route", resolve)
    monkeypatch.setattr(service, "derive_route_expansions", expand)
    monkeypatch.setattr(
        service,
        "acquire_direct_pdf",
        lambda candidate, **kwargs: AcquisitionResult(
            candidate=candidate,
            status=AcquisitionStatus.VERIFIED,
        ),
    )

    result = service.acquire_from_discovery(
        _discovery(start),
        output_dir=tmp_path,
        use_doi_resolver_fallback=False,
    )

    assert result.status == FullTextAcquisitionStatus.VERIFIED
    assert calls == [start.url, second.url]
    assert result.route_expansions_enqueued == 1
    assert result.route_attempts[1].origin == RouteCandidateOrigin.PAGE_EXPANSION
    assert result.route_attempts[1].depth == 1
    assert result.route_attempts[1].parent_url == start.url
    assert result.route_attempts[1].expansion_method == "CANONICAL"


def test_route_depth_limit_prevents_unbounded_page_chains(monkeypatch, tmp_path):
    start = _candidate("https://example.org/0")
    route1 = replace(start, url="https://example.org/1")
    route2 = replace(start, url="https://example.org/2")

    monkeypatch.setattr(
        service,
        "resolve_full_text_route",
        lambda candidate, **kwargs: _page_result(candidate),
    )

    def expand(*, parent, resolution, max_candidates):
        mapping = {start.url: route1, route1.url: route2}
        target = mapping.get(parent.url)
        if target is None:
            return ()
        return (
            ExpandedRouteCandidate(
                candidate=target,
                parent_url=parent.url,
                source_page_url=parent.url,
                method=RouteExpansionMethod.CANONICAL,
                evidence=("canonical",),
                priority=900,
            ),
        )

    monkeypatch.setattr(service, "derive_route_expansions", expand)

    result = service.acquire_from_discovery(
        _discovery(start),
        output_dir=tmp_path,
        max_route_depth=1,
        use_doi_resolver_fallback=False,
    )

    assert [attempt.candidate.url for attempt in result.route_attempts] == [
        start.url,
        route1.url,
    ]
    assert result.max_route_depth_reached == 1


def test_open_repository_route_is_attempted_before_plain_resolver(
    monkeypatch, tmp_path
):
    resolver = _candidate("https://doi.org/10.1000/target", host_type=HostType.RESOLVER)
    repository = _candidate(
        "https://repo.example.org/item",
        host_type=HostType.REPOSITORY,
        access_type=AccessType.OPEN_ACCESS,
    )
    order: list[str] = []

    def resolve(candidate, **kwargs):
        order.append(candidate.url)
        return _page_result(candidate)

    monkeypatch.setattr(service, "resolve_full_text_route", resolve)
    monkeypatch.setattr(service, "derive_route_expansions", lambda **kwargs: ())

    service.acquire_from_discovery(
        _discovery(resolver, repository),
        output_dir=tmp_path,
        use_doi_resolver_fallback=False,
    )

    assert order == [repository.url, resolver.url]


def test_mixed_blocked_and_no_file_route_is_not_overstated(monkeypatch, tmp_path):
    blocked = _candidate("https://blocked.example/article")
    accessible = _candidate("https://accessible.example/article")

    def resolve(candidate, **kwargs):
        if candidate.url == blocked.url:
            return RouteResolutionResult(
                source_candidate=candidate,
                status=ResolutionStatus.ACCESS_BLOCKED,
                error="blocked",
                attempts=1,
            )
        return _page_result(candidate)

    monkeypatch.setattr(service, "resolve_full_text_route", resolve)
    monkeypatch.setattr(service, "derive_route_expansions", lambda **kwargs: ())

    result = service.acquire_from_discovery(
        _discovery(blocked, accessible),
        output_dir=tmp_path,
        use_doi_resolver_fallback=False,
    )

    assert result.status == FullTextAcquisitionStatus.NO_CANDIDATES


def test_all_access_barriers_preserve_auth_required(monkeypatch, tmp_path):
    blocked = _candidate("https://blocked.example/article")
    auth = _candidate("https://auth.example/article")

    def resolve(candidate, **kwargs):
        status = (
            ResolutionStatus.AUTH_REQUIRED
            if candidate.url == auth.url
            else ResolutionStatus.ACCESS_BLOCKED
        )
        return RouteResolutionResult(
            source_candidate=candidate,
            status=status,
            error=status.value,
            attempts=1,
        )

    monkeypatch.setattr(service, "resolve_full_text_route", resolve)
    monkeypatch.setattr(service, "derive_route_expansions", lambda **kwargs: ())

    result = service.acquire_from_discovery(
        _discovery(blocked, auth),
        output_dir=tmp_path,
        use_doi_resolver_fallback=False,
    )

    assert result.status == FullTextAcquisitionStatus.AUTH_REQUIRED
