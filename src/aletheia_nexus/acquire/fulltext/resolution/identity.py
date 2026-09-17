import re
import unicodedata
from difflib import SequenceMatcher

from aletheia_nexus.acquire.fulltext.models import IdentityStatus
from aletheia_nexus.acquire.fulltext.resolution.models import (
    PageIdentityReport,
    PageType,
)
from aletheia_nexus.acquire.fulltext.resolution.parser import ParsedHtml
from aletheia_nexus.core.identifiers.doi import extract_dois, normalize_doi

_DOI_META_NAMES = (
    "citation_doi",
    "dc.identifier",
    "dc.identifier.doi",
    "prism.doi",
    "bepress_citation_doi",
)
_TITLE_META_NAMES = (
    "citation_title",
    "dc.title",
    "bepress_citation_title",
    "og:title",
    "twitter:title",
)
_CHALLENGE_TERMS = (
    "verify you are human",
    "verify that you're not a robot",
    "verify that you are not a robot",
    "checking your browser",
    "captcha",
    "cloudflare",
    "attention required",
    "robot check",
    "security check",
)
_ACCESS_DENIED_TERMS = (
    "access denied",
    "request blocked",
    "forbidden",
    "you don't have permission",
    "you do not have permission",
)
_STRONG_LOGIN_TERMS = (
    "access through your institution",
    "sign in to access",
    "log in to access",
    "purchase article",
    "purchase pdf",
    "subscribe to read",
)
_WEAK_LOGIN_TERMS = (
    "institutional access",
    "get access",
)


def _normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _first_metadata_title(parsed: ParsedHtml) -> str | None:
    for name in _TITLE_META_NAMES:
        values = parsed.metadata_values(name)
        for value in values:
            if value.strip():
                return value.strip()
    return parsed.title.strip() if parsed.title and parsed.title.strip() else None


def _metadata_dois(parsed: ParsedHtml) -> tuple[str, ...]:
    found: list[str] = []
    for name in _DOI_META_NAMES:
        for value in parsed.metadata_values(name):
            extracted = extract_dois(value)
            for doi in extracted:
                if doi not in found:
                    found.append(doi)
            if extracted:
                continue
            try:
                normalized = normalize_doi(value)
            except (TypeError, ValueError):
                continue
            if normalized not in found:
                found.append(normalized)

    for link in parsed.links:
        if link.tag == "link" and "canonical" in link.rel:
            for doi in extract_dois(link.url):
                if doi not in found:
                    found.append(doi)
    return tuple(found)


def validate_page_identity(
    *,
    target_doi: str,
    parsed: ParsedHtml,
    expected_title: str | None = None,
) -> PageIdentityReport:
    """Conservatively determine whether a page represents the requested paper.

    A generic bridge, challenge, or repository page can have a title that looks
    nothing like the paper. Title disagreement alone is therefore insufficient
    for a mismatch. Explicit scholarly DOI metadata pointing to another work is
    required before route resolution emits ``MISMATCH``.
    """

    normalized_doi = normalize_doi(target_doi)
    metadata_dois = _metadata_dois(parsed)
    doi_match = normalized_doi in metadata_dois
    metadata_title = _first_metadata_title(parsed)
    evidence: list[str] = []

    if doi_match:
        evidence.append("Target DOI found in page-level scholarly metadata")

    title_similarity: float | None = None
    title_match = False
    if expected_title is not None:
        if not isinstance(expected_title, str):
            raise TypeError("expected_title must be a string or None")
        expected = _normalize_title(expected_title)
        if expected and metadata_title:
            observed = _normalize_title(metadata_title)
            title_similarity = SequenceMatcher(None, expected, observed).ratio()
            title_match = title_similarity >= 0.92
            evidence.append(f"Page title similarity={title_similarity:.3f}")

    if doi_match:
        status = IdentityStatus.MATCH
    elif metadata_dois:
        status = IdentityStatus.MISMATCH
        evidence.append("Page-level DOI metadata points to a different work")
    elif title_match:
        status = IdentityStatus.MATCH
    else:
        status = IdentityStatus.UNKNOWN

    return PageIdentityReport(
        status=status,
        doi_match=doi_match,
        title_similarity=title_similarity,
        metadata_dois=metadata_dois,
        metadata_title=metadata_title,
        evidence=tuple(evidence),
    )


def classify_page_type(parsed: ParsedHtml, identity: PageIdentityReport) -> PageType:
    """Classify page semantics without overstating ambiguous access failures."""

    text = " ".join(
        part
        for part in (
            parsed.title or "",
            parsed.visible_text[:100_000],
        )
        if part
    ).lower()

    # Strong block/challenge language describes the response we actually received
    # and takes precedence over stale or copied scholarly metadata on that page.
    if any(term in text for term in _CHALLENGE_TERMS):
        return PageType.CHALLENGE
    if any(term in text for term in _ACCESS_DENIED_TERMS):
        return PageType.ACCESS_DENIED

    # Explicit access-boundary language describes the current response even when
    # scholarly metadata correctly identifies the requested paper.
    if any(term in text for term in _STRONG_LOGIN_TERMS):
        return PageType.LOGIN

    # Once the page identity is positively established, weak account/navigation
    # controls such as a generic "Get access" link must not turn the article into
    # a login page.
    if identity.status == IdentityStatus.MATCH:
        return PageType.ARTICLE

    if any(term in text for term in _WEAK_LOGIN_TERMS):
        return PageType.LOGIN
    if parsed.metadata_values("citation_title", "citation_doi"):
        return PageType.ARTICLE
    if text.strip():
        return PageType.GENERIC
    return PageType.UNKNOWN
