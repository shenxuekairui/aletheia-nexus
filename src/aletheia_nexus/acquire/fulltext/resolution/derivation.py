import json
import re
from dataclasses import replace
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from aletheia_nexus.acquire.discovery.hosts import refine_host_type
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
    HostType,
)
from aletheia_nexus.acquire.fulltext.models import DocumentRole
from aletheia_nexus.acquire.fulltext.resolution.models import (
    DerivationMethod,
    DerivedFullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.resolution.parser import HtmlLink, ParsedHtml
from aletheia_nexus.acquire.fulltext.urls import derive_https_url, normalize_derived_url

_CITATION_PDF_META = {
    "citation_pdf_url",
    "bepress_citation_pdf_url",
    "eprints.document_url",
    "pdf_url",
}
_SUPPLEMENT_TERMS = (
    "supporting information",
    "supplementary information",
    "supplemental information",
    "supplementary material",
    "supplemental material",
    "supporting material",
)
_AUXILIARY_TERMS = (
    "reporting summary",
    "peer review file",
    "transparent peer review",
    "peer review information",
    "source data",
    "editorial decision",
    "decision letter",
    "author checklist",
    "reviewer comments",
)
_ARTICLE_LINK_TERMS = (
    "download pdf",
    "view pdf",
    "article pdf",
    "full text pdf",
    "full-text pdf",
    "pdf full text",
    "download full text",
)
_SUPPLEMENT_FILENAME = re.compile(
    r"(?:^|[_.-])(si|supp|supplement|supplementary)(?:[_.-]|$)",
    re.IGNORECASE,
)
_METHOD_PRIORITY = {
    DerivationMethod.DIRECT_PDF_RESPONSE: 1000,
    DerivationMethod.CITATION_PDF_URL: 920,
    DerivationMethod.META_PDF_URL: 880,
    DerivationMethod.LINK_PDF: 840,
    DerivationMethod.JSON_LD_PDF: 800,
    DerivationMethod.ANCHOR_DOWNLOAD: 760,
    DerivationMethod.EMBEDDED_PDF: 720,
    DerivationMethod.PDF_URL_PATTERN: 640,
    DerivationMethod.HTTPS_UPGRADE: 620,
}


def _looks_like_pdf_url(value: str) -> bool:
    parts = urlsplit(value)
    path = unquote(parts.path).lower()
    query = parts.query.lower()
    return (
        path.endswith(".pdf")
        or "/pdf/" in path
        or path.endswith("/pdf")
        or "/articlepdf/" in path
        or "format=pdf" in query
        or "type=pdf" in query
        or "download=pdf" in query
    )


def _role_hint(
    link: HtmlLink | None, url: str, *, article_signal: bool
) -> DocumentRole:
    basename = PurePosixPath(unquote(urlsplit(url).path)).name.lower()
    raw_context = " ".join(
        value.lower()
        for value in (
            link.text if link else "",
            link.title_attr if link and link.title_attr else "",
            basename,
        )
        if value
    )
    context = re.sub(r"[_.-]+", " ", raw_context)
    if any(
        term in context for term in _SUPPLEMENT_TERMS
    ) or _SUPPLEMENT_FILENAME.search(basename):
        return DocumentRole.SUPPLEMENT
    if any(term in context for term in _AUXILIARY_TERMS):
        # v0.5's role model distinguishes main article from non-main scholarly
        # files. Auxiliary files therefore share the conservative SUPPLEMENT role
        # so orchestration will skip them by default rather than validate them as
        # possible main articles.
        return DocumentRole.SUPPLEMENT
    if article_signal or any(term in context for term in _ARTICLE_LINK_TERMS):
        return DocumentRole.ARTICLE
    return DocumentRole.UNKNOWN


def _host_type_for_derived(
    url: str,
    parent: FullTextCandidate,
    *,
    source_page_url: str,
) -> HostType:
    derived_host = (urlsplit(url).hostname or "").lower()
    source_host = (urlsplit(source_page_url).hostname or "").lower()
    original_host = (urlsplit(parent.url).hostname or "").lower()

    reported = HostType.UNKNOWN
    if derived_host and derived_host == original_host:
        reported = parent.host_type
    elif (
        derived_host
        and derived_host == source_host
        and parent.host_type
        in {
            HostType.PUBLISHER,
            HostType.REPOSITORY,
        }
    ):
        reported = parent.host_type
    return refine_host_type(url, reported)


def _candidate(
    *,
    parent: FullTextCandidate,
    url: str,
    source_page_url: str | None,
    method: DerivationMethod,
    role_hint: DocumentRole,
    evidence: str,
) -> DerivedFullTextCandidate:
    host_type = _host_type_for_derived(
        url,
        parent,
        source_page_url=source_page_url or parent.url,
    )
    bonus = 100 if role_hint == DocumentRole.ARTICLE else 0
    penalty = 500 if role_hint == DocumentRole.SUPPLEMENT else 0
    if urlsplit(url).scheme.lower() == "https":
        bonus += 20

    return DerivedFullTextCandidate(
        candidate=FullTextCandidate(
            doi=parent.doi,
            url=url,
            provenance=parent.provenance,
            url_type=CandidateUrlType.PDF,
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
        role_hint=role_hint,
        evidence=(evidence,),
        priority=_METHOD_PRIORITY[method] + bonus - penalty,
    )


def derive_direct_pdf_response(
    parent: FullTextCandidate,
    *,
    final_url: str,
) -> DerivedFullTextCandidate:
    """Represent a landing/unknown route that directly returned PDF bytes."""

    normalized = normalize_derived_url(final_url, base_url=parent.url)
    if normalized is None:
        raise ValueError("final_url is not a usable HTTP(S) URL")
    return _candidate(
        parent=parent,
        url=normalized,
        source_page_url=normalized,
        method=DerivationMethod.DIRECT_PDF_RESPONSE,
        role_hint=DocumentRole.UNKNOWN,
        evidence="Route response begins with a PDF header marker",
    )


def _json_ld_pdf_urls(payload: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        return ()

    found: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str) and value.strip() and value not in found:
            found.append(value.strip())

    def visit(node: object, *, pdf_context: bool = False) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, pdf_context=pdf_context)
            return
        if not isinstance(node, dict):
            return

        media_type = " ".join(
            str(node.get(key, ""))
            for key in ("fileFormat", "encodingFormat", "contentType")
        ).lower()
        local_pdf = pdf_context or "pdf" in media_type

        for key, value in node.items():
            lowered = str(key).lower()
            if lowered in {"contenturl", "downloadurl"}:
                if local_pdf or (isinstance(value, str) and _looks_like_pdf_url(value)):
                    add(value)
            elif lowered == "url" and local_pdf:
                add(value)
            elif lowered in {"encoding", "associatedmedia", "distribution"}:
                visit(value, pdf_context=local_pdf)
            elif isinstance(value, (dict, list)):
                visit(value, pdf_context=local_pdf)

    visit(parsed)
    return tuple(found)


def _merge_role(left: DocumentRole, right: DocumentRole) -> DocumentRole:
    if left == right:
        return left
    if left == DocumentRole.UNKNOWN:
        return right
    if right == DocumentRole.UNKNOWN:
        return left
    return DocumentRole.UNKNOWN


def _dedupe_and_rank(
    candidates: list[DerivedFullTextCandidate],
) -> tuple[DerivedFullTextCandidate, ...]:
    merged: dict[str, DerivedFullTextCandidate] = {}
    order: list[str] = []

    for item in candidates:
        key = item.candidate.url
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            order.append(key)
            continue

        role = _merge_role(existing.role_hint, item.role_hint)
        evidence = tuple(dict.fromkeys(existing.evidence + item.evidence))
        chosen = existing if existing.priority >= item.priority else item
        merged[key] = replace(
            chosen,
            role_hint=role,
            evidence=evidence,
            priority=max(existing.priority, item.priority),
        )

    position = {url: index for index, url in enumerate(order)}
    return tuple(
        sorted(
            merged.values(),
            key=lambda item: (-item.priority, position[item.candidate.url]),
        )
    )


def _with_https_upgrades(
    candidates: list[DerivedFullTextCandidate],
) -> list[DerivedFullTextCandidate]:
    output = list(candidates)
    existing_urls = {item.candidate.url for item in candidates}
    for item in candidates:
        https_url = derive_https_url(item.candidate.url)
        if https_url is None or https_url in existing_urls:
            continue
        existing_urls.add(https_url)
        output.append(
            _candidate(
                parent=item.candidate,
                url=https_url,
                source_page_url=item.source_page_url,
                method=DerivationMethod.HTTPS_UPGRADE,
                role_hint=item.role_hint,
                evidence=f"HTTPS upgrade derived from {item.candidate.url}",
            )
        )
    return output


def derive_https_upgrade(
    parent: FullTextCandidate,
) -> tuple[DerivedFullTextCandidate, ...]:
    """Derive an explicit HTTPS alternative for an HTTP direct-file candidate."""

    if parent.url_type != CandidateUrlType.PDF:
        return ()
    https_url = derive_https_url(parent.url)
    if https_url is None:
        return ()
    return (
        _candidate(
            parent=parent,
            url=https_url,
            source_page_url=None,
            method=DerivationMethod.HTTPS_UPGRADE,
            role_hint=DocumentRole.UNKNOWN,
            evidence=f"HTTPS upgrade derived from provider-reported HTTP PDF {parent.url}",
        ),
    )


def derive_pdf_candidates(
    *,
    parent: FullTextCandidate,
    parsed: ParsedHtml,
    source_page_url: str,
) -> tuple[DerivedFullTextCandidate, ...]:
    """Derive explainable PDF candidates from generic scholarly HTML signals."""

    effective_base = source_page_url
    if parsed.base_href:
        normalized_base = normalize_derived_url(
            parsed.base_href,
            base_url=source_page_url,
        )
        if normalized_base:
            effective_base = normalized_base

    derived: list[DerivedFullTextCandidate] = []

    for key, value in parsed.metadata:
        if key not in _CITATION_PDF_META:
            continue
        url = normalize_derived_url(value, base_url=effective_base)
        if not url:
            continue
        method = (
            DerivationMethod.CITATION_PDF_URL
            if key in {"citation_pdf_url", "bepress_citation_pdf_url"}
            else DerivationMethod.META_PDF_URL
        )
        derived.append(
            _candidate(
                parent=parent,
                url=url,
                source_page_url=source_page_url,
                method=method,
                role_hint=DocumentRole.ARTICLE,
                evidence=f"Page metadata {key} exposed a PDF route",
            )
        )

    for payload in parsed.json_ld:
        for raw_url in _json_ld_pdf_urls(payload):
            url = normalize_derived_url(raw_url, base_url=effective_base)
            if not url:
                continue
            derived.append(
                _candidate(
                    parent=parent,
                    url=url,
                    source_page_url=source_page_url,
                    method=DerivationMethod.JSON_LD_PDF,
                    role_hint=DocumentRole.UNKNOWN,
                    evidence="JSON-LD scholarly/media metadata exposed a PDF route",
                )
            )

    for link in parsed.links:
        url = normalize_derived_url(link.url, base_url=effective_base)
        if not url:
            continue
        type_is_pdf = (link.type_attr or "").lower() == "application/pdf"
        url_is_pdf = _looks_like_pdf_url(url)
        anchor_context = " ".join(
            value.lower() for value in (link.text, link.title_attr or "") if value
        )
        semantic_pdf = any(term in anchor_context for term in _ARTICLE_LINK_TERMS)
        semantic_supplement = any(term in anchor_context for term in _SUPPLEMENT_TERMS)
        semantic_auxiliary = any(term in anchor_context for term in _AUXILIARY_TERMS)

        method: DerivationMethod | None = None
        article_signal = False
        if link.tag == "link" and (
            type_is_pdf or ("alternate" in link.rel and url_is_pdf)
        ):
            method = DerivationMethod.LINK_PDF
            article_signal = True
        elif link.tag in {"iframe", "embed", "object"} and (type_is_pdf or url_is_pdf):
            method = DerivationMethod.EMBEDDED_PDF
        elif link.tag == "a" and (semantic_pdf or link.download):
            method = DerivationMethod.ANCHOR_DOWNLOAD
            article_signal = (
                semantic_pdf and not semantic_supplement and not semantic_auxiliary
            )
        elif url_is_pdf:
            method = DerivationMethod.PDF_URL_PATTERN

        if method is None:
            continue

        role = _role_hint(link, url, article_signal=article_signal)
        derived.append(
            _candidate(
                parent=parent,
                url=url,
                source_page_url=source_page_url,
                method=method,
                role_hint=role,
                evidence=(
                    f"HTML <{link.tag}> exposed a PDF-like route"
                    + (f" with text '{link.text[:120]}'" if link.text else "")
                ),
            )
        )

    return _dedupe_and_rank(_with_https_upgrades(derived))
