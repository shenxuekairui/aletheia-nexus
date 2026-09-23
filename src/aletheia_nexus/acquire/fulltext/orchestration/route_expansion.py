import json
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlsplit

from aletheia_nexus.acquire.discovery.hosts import refine_host_type
from aletheia_nexus.acquire.discovery.models import CandidateUrlType, FullTextCandidate
from aletheia_nexus.acquire.fulltext.resolution.models import (
    ResolutionStatus,
    RouteResolutionResult,
)
from aletheia_nexus.acquire.fulltext.resolution.parser import HtmlLink, parse_html
from aletheia_nexus.acquire.fulltext.urls import normalize_derived_url
from aletheia_nexus.core.identifiers.doi import normalize_doi


class RouteExpansionMethod(StrEnum):
    """Explainable way v0.5.2 derived another page-like acquisition route."""

    REDIRECT_TARGET = "REDIRECT_TARGET"
    META_REFRESH = "META_REFRESH"
    CITATION_HTML_URL = "CITATION_HTML_URL"
    CANONICAL = "CANONICAL"
    JSON_LD_ARTICLE_URL = "JSON_LD_ARTICLE_URL"
    SEMANTIC_ARTICLE_LINK = "SEMANTIC_ARTICLE_LINK"
    TARGET_DOI_LINK = "TARGET_DOI_LINK"


@dataclass(frozen=True, slots=True)
class ExpandedRouteCandidate:
    """One bounded page-route expansion with provenance and priority."""

    candidate: FullTextCandidate
    parent_url: str
    source_page_url: str
    method: RouteExpansionMethod
    evidence: tuple[str, ...]
    priority: int


_HTML_META_NAMES = {
    "citation_fulltext_html_url",
    "citation_abstract_html_url",
    "citation_public_url",
    "og:url",
}
_ARTICLE_LINK_TERMS = (
    "view article",
    "read article",
    "article page",
    "full text",
    "full-text",
    "view full text",
    "read full text",
    "open manuscript",
    "view open manuscript",
    "publisher version",
    "continue to article",
    "go to article",
)
_NON_ARTICLE_ROUTE_TERMS = (
    "advertisement",
    "advertising",
    "altmetric",
    "citation export",
    "download citation",
    "export citation",
    "reference manager",
    "references",
    "rights and permissions",
    "permissions",
    "copyright",
    "crossmark",
    "metrics",
    "share article",
    "bibtex",
    "refman",
)
_NON_ARTICLE_ROUTE_URL_TERMS = (
    "doubleclick.net/",
    "/gampad/",
    "crossmark.crossref.org/",
    "copyright.com/",
    "/references/",
    "/reference/",
    "/citations/",
    "/citation/",
    "format=refman",
    "format=bibtex",
    "format=ris",
    "/metrics/",
    "/altmetric/",
)
_REDIRECT_QUERY_KEYS = {
    "redirect",
    "redirect_url",
    "redirect_uri",
    "destination",
    "dest",
    "target_url",
}
_PDF_PATH_RE = re.compile(r"(?:\.pdf(?:$|[?#])|/pdf(?:/|$)|/articlepdf(?:/|$))", re.I)
_NON_PAGE_RESOURCE_RE = re.compile(
    r"\.(?:png|jpe?g|gif|svg|webp|ico|css|js|mjs|map|zip|gz|tar|docx?|xlsx?|"
    r"pptx?|csv|tsv|xml|json)(?:$|[?#])",
    re.I,
)
_META_REFRESH_URL_RE = re.compile(r"(?:^|;)\s*url\s*=\s*(.+?)\s*$", re.I)
_METHOD_PRIORITY = {
    RouteExpansionMethod.REDIRECT_TARGET: 1000,
    RouteExpansionMethod.META_REFRESH: 980,
    RouteExpansionMethod.CITATION_HTML_URL: 940,
    RouteExpansionMethod.CANONICAL: 900,
    RouteExpansionMethod.JSON_LD_ARTICLE_URL: 860,
    RouteExpansionMethod.SEMANTIC_ARTICLE_LINK: 800,
    RouteExpansionMethod.TARGET_DOI_LINK: 760,
}
_EXPANDABLE_STATUSES = {
    ResolutionStatus.RESOLVED,
    ResolutionStatus.NO_FILE_CANDIDATES,
}


def _normalize_route_url(value: str, *, base_url: str) -> str | None:
    normalized = normalize_derived_url(value, base_url=base_url)
    if normalized is None:
        return None
    decoded = unquote(normalized)
    if _PDF_PATH_RE.search(decoded) or _NON_PAGE_RESOURCE_RE.search(decoded):
        return None
    return normalized


def _candidate(
    *,
    parent: FullTextCandidate,
    url: str,
    source_page_url: str,
    method: RouteExpansionMethod,
    evidence: str,
) -> ExpandedRouteCandidate:
    host_type = refine_host_type(url, parent.host_type)
    bonus = 10 if urlsplit(url).scheme.lower() == "https" else 0
    return ExpandedRouteCandidate(
        candidate=FullTextCandidate(
            doi=parent.doi,
            url=url,
            provenance=parent.provenance,
            url_type=CandidateUrlType.LANDING_PAGE,
            access_type=parent.access_type,
            version=parent.version,
            host_type=host_type,
            license=parent.license,
            source_name=parent.source_name,
            is_best=parent.is_best,
        ),
        parent_url=parent.url,
        source_page_url=source_page_url,
        method=method,
        evidence=(evidence,),
        priority=_METHOD_PRIORITY[method] + bonus,
    )


def _embedded_redirect_target(url: str) -> str | None:
    """Return an explicit HTTP(S) target embedded in a redirect-wrapper query."""

    parts = urlsplit(url)
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        if key.lower() not in _REDIRECT_QUERY_KEYS:
            continue
        target = _normalize_route_url(value, base_url=url)
        if target and target != url:
            return target
    return None


def _json_ld_article_urls(payload: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        return ()

    found: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned and cleaned not in found:
                found.append(cleaned)
            return
        if isinstance(value, list):
            for item in value:
                add(item)
            return
        if isinstance(value, dict):
            for key in ("@id", "url"):
                add(value.get(key))

    def visit(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return

        raw_type = node.get("@type")
        if isinstance(raw_type, str):
            types = [raw_type.lower()]
        elif isinstance(raw_type, list):
            types = [str(item).lower() for item in raw_type]
        else:
            types = []

        if any("article" in value for value in types):
            for key in ("url", "mainEntityOfPage", "sameAs"):
                add(node.get(key))

        for value in node.values():
            if isinstance(value, (dict, list)):
                visit(value)

    visit(parsed)
    return tuple(found)


def _anchor_context(link: HtmlLink) -> str:
    return " ".join(
        value.lower() for value in (link.text, link.title_attr or "") if value
    )


def _is_article_like_target_doi_link(
    url: str,
    *,
    context: str,
    target_doi: str,
) -> bool:
    """Accept weak DOI-bearing anchors only when they still look article-directed.

    A target DOI can appear in ads, citation exports, Crossmark, rights/permissions,
    metrics and other scholarly utilities. Those links are useful metadata links but
    not acquisition routes. For this weakest expansion signal, require the DOI in
    the URL path or explicit article/full-text anchor semantics, and reject known
    non-article semantics generically.
    """

    decoded_url = unquote(url).lower()
    decoded_path = unquote(urlsplit(url).path).lower()
    lowered_context = context.lower()

    if target_doi not in decoded_url:
        return False
    if any(term in lowered_context for term in _NON_ARTICLE_ROUTE_TERMS):
        return False
    if any(term in decoded_url for term in _NON_ARTICLE_ROUTE_URL_TERMS):
        return False

    doi_in_path = target_doi in decoded_path
    semantic_article_link = any(term in lowered_context for term in _ARTICLE_LINK_TERMS)
    return doi_in_path or semantic_article_link


def _add_with_redirect_target(
    items: list[ExpandedRouteCandidate],
    item: ExpandedRouteCandidate,
) -> None:
    """Add a route and, when explicit, its embedded redirect destination first."""

    target = _embedded_redirect_target(item.candidate.url)
    if target:
        wrapper = replace(item.candidate, url=item.candidate.url)
        items.append(
            _candidate(
                parent=wrapper,
                url=target,
                source_page_url=item.source_page_url,
                method=RouteExpansionMethod.REDIRECT_TARGET,
                evidence=f"{item.method.value} route contained an explicit redirect target",
            )
        )
    items.append(item)


def _dedupe_and_rank(
    items: list[ExpandedRouteCandidate],
    *,
    source_page_url: str,
    parent_url: str,
    max_candidates: int,
) -> tuple[ExpandedRouteCandidate, ...]:
    blocked = {source_page_url, parent_url}
    merged: dict[str, ExpandedRouteCandidate] = {}
    order: list[str] = []
    for item in items:
        url = item.candidate.url
        if url in blocked:
            continue
        existing = merged.get(url)
        if existing is None:
            merged[url] = item
            order.append(url)
            continue
        evidence = tuple(dict.fromkeys(existing.evidence + item.evidence))
        chosen = existing if existing.priority >= item.priority else item
        merged[url] = ExpandedRouteCandidate(
            candidate=chosen.candidate,
            parent_url=chosen.parent_url,
            source_page_url=chosen.source_page_url,
            method=chosen.method,
            evidence=evidence,
            priority=max(existing.priority, item.priority),
        )

    position = {url: index for index, url in enumerate(order)}
    ranked = sorted(
        merged.values(),
        key=lambda item: (-item.priority, position[item.candidate.url]),
    )
    return tuple(ranked[:max_candidates])


def derive_route_expansions(
    *,
    parent: FullTextCandidate,
    resolution: RouteResolutionResult,
    max_candidates: int = 4,
) -> tuple[ExpandedRouteCandidate, ...]:
    """Derive a small set of high-confidence next-hop routes from one page.

    This intentionally is not a crawler. Only strong generic scholarly/navigation
    signals are followed and the caller must enforce global dedupe and hop limits.
    """

    if not isinstance(max_candidates, int) or isinstance(max_candidates, bool):
        raise TypeError("max_candidates must be an integer")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")
    if resolution.status not in _EXPANDABLE_STATUSES:
        return ()
    page = resolution.page
    if page is None or page.text is None or page.is_pdf_response:
        return ()

    parsed = parse_html(page.text)
    source_page_url = page.final_url
    effective_base = source_page_url
    if parsed.base_href:
        normalized_base = _normalize_route_url(
            parsed.base_href, base_url=source_page_url
        )
        if normalized_base:
            effective_base = normalized_base

    target_doi = normalize_doi(parent.doi).lower()
    items: list[ExpandedRouteCandidate] = []

    source_redirect = _embedded_redirect_target(source_page_url)
    if source_redirect:
        _add_with_redirect_target(
            items,
            _candidate(
                parent=replace(parent, url=source_page_url),
                url=source_redirect,
                source_page_url=source_page_url,
                method=RouteExpansionMethod.REDIRECT_TARGET,
                evidence="Final page URL contained an explicit redirect target",
            ),
        )

    for key, value in parsed.metadata:
        if key == "refresh":
            match = _META_REFRESH_URL_RE.search(value)
            if match:
                url = _normalize_route_url(match.group(1), base_url=effective_base)
                if url:
                    _add_with_redirect_target(
                        items,
                        _candidate(
                            parent=parent,
                            url=url,
                            source_page_url=source_page_url,
                            method=RouteExpansionMethod.META_REFRESH,
                            evidence="HTML meta refresh exposed a next-hop route",
                        ),
                    )
            continue
        if key not in _HTML_META_NAMES:
            continue
        url = _normalize_route_url(value, base_url=effective_base)
        if url:
            _add_with_redirect_target(
                items,
                _candidate(
                    parent=parent,
                    url=url,
                    source_page_url=source_page_url,
                    method=RouteExpansionMethod.CITATION_HTML_URL,
                    evidence=f"Page metadata {key} exposed an article route",
                ),
            )

    for link in parsed.links:
        url = _normalize_route_url(link.url, base_url=effective_base)
        if not url:
            continue
        context = _anchor_context(link)
        item: ExpandedRouteCandidate | None = None
        if link.tag == "link" and "canonical" in link.rel:
            item = _candidate(
                parent=parent,
                url=url,
                source_page_url=source_page_url,
                method=RouteExpansionMethod.CANONICAL,
                evidence="HTML canonical link exposed a more specific article route",
            )
        elif link.tag == "a" and any(term in context for term in _ARTICLE_LINK_TERMS):
            item = _candidate(
                parent=parent,
                url=url,
                source_page_url=source_page_url,
                method=RouteExpansionMethod.SEMANTIC_ARTICLE_LINK,
                evidence=(
                    "Article/full-text anchor exposed a next-hop route"
                    + (f" with text '{link.text[:120]}'" if link.text else "")
                ),
            )
        elif link.tag == "a" and _is_article_like_target_doi_link(
            url,
            context=context,
            target_doi=target_doi,
        ):
            item = _candidate(
                parent=parent,
                url=url,
                source_page_url=source_page_url,
                method=RouteExpansionMethod.TARGET_DOI_LINK,
                evidence=(
                    "Anchor URL contained the target DOI and passed article-route filtering"
                ),
            )
        if item is not None:
            _add_with_redirect_target(items, item)

    for payload in parsed.json_ld:
        for raw_url in _json_ld_article_urls(payload):
            url = _normalize_route_url(raw_url, base_url=effective_base)
            if url:
                _add_with_redirect_target(
                    items,
                    _candidate(
                        parent=parent,
                        url=url,
                        source_page_url=source_page_url,
                        method=RouteExpansionMethod.JSON_LD_ARTICLE_URL,
                        evidence="Article JSON-LD exposed an article route",
                    ),
                )

    return _dedupe_and_rank(
        items,
        source_page_url=source_page_url,
        parent_url=parent.url,
        max_candidates=max_candidates,
    )
