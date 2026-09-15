import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from aletheia_nexus.acquire.fulltext.models import (
    DocumentRole,
    IdentityStatus,
    IdentityValidationReport,
)
from aletheia_nexus.acquire.fulltext.validation import PdfInspection
from aletheia_nexus.core.identifiers.doi import extract_dois, normalize_doi

_SUPPLEMENT_TERMS = (
    "supporting information",
    "supplementary information",
    "supplemental information",
    "supplementary material",
    "supplemental material",
)
_SUPPLEMENT_FILENAME = re.compile(
    r"(?:^|[_.-])(si|supp|supplement|supplementary)(?:[_.-]|$)",
    re.IGNORECASE,
)


def _normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _title_score(
    expected_title: str, inspection: PdfInspection
) -> tuple[float, str | None]:
    """Return conservative title evidence for identity fallback.

    Exact normalized title occurrence in inspected text is strong evidence. If
    that is absent, only the dedicated PDF metadata title is compared. General
    token overlap across whole pages is intentionally not used for verification
    because scientific vocabulary can recur outside the actual title.
    """

    expected = _normalize_title(expected_title)
    if not expected:
        return 0.0, None

    text = _normalize_title(inspection.extracted_text)
    if expected in text:
        return 1.0, "Expected title found in inspected PDF text"

    if inspection.metadata_title:
        metadata_title = _normalize_title(inspection.metadata_title)
        score = SequenceMatcher(None, expected, metadata_title).ratio()
        return score, f"PDF metadata title similarity={score:.3f}"

    return 0.0, None


def _supplement_evidence(source_url: str, inspection: PdfInspection) -> str | None:
    basename = PurePosixPath(unquote(urlsplit(source_url).path)).name.lower()
    if _SUPPLEMENT_FILENAME.search(basename):
        return f"Supplement-like source filename: {basename}"

    metadata_title = (inspection.metadata_title or "").strip().lower()
    if any(term in metadata_title for term in _SUPPLEMENT_TERMS):
        return "Supplement marker found in PDF metadata title"

    text_prefix = " ".join(inspection.extracted_text[:1200].lower().split())
    if any(term in text_prefix for term in _SUPPLEMENT_TERMS):
        return "Supplement marker found near the beginning of the PDF"

    return None


def validate_paper_identity(
    *,
    target_doi: str,
    source_url: str,
    inspection: PdfInspection,
    expected_title: str | None = None,
) -> IdentityValidationReport:
    """Conservatively validate scholarly identity and document role."""

    normalized_doi = normalize_doi(target_doi)
    evidence: list[str] = []
    extracted_dois = tuple(extract_dois(inspection.extracted_text))
    doi_match = normalized_doi in extracted_dois

    if doi_match:
        evidence.append("Target DOI found in inspected PDF text")

    title_similarity: float | None = None
    title_match = False
    if expected_title is not None:
        if not isinstance(expected_title, str):
            raise TypeError("expected_title must be a string or None")
        if expected_title.strip():
            title_similarity, title_evidence = _title_score(expected_title, inspection)
            title_match = title_similarity >= 0.92
            if title_evidence:
                evidence.append(title_evidence)

    supplement_evidence = _supplement_evidence(source_url, inspection)
    if supplement_evidence:
        evidence.append(supplement_evidence)

    if doi_match or title_match:
        identity_status = IdentityStatus.MATCH
    else:
        identity_status = IdentityStatus.UNKNOWN
        if (
            extracted_dois
            and expected_title
            and inspection.metadata_title
            and title_similarity is not None
            and title_similarity < 0.25
        ):
            identity_status = IdentityStatus.MISMATCH
            evidence.append(
                "Different DOI evidence plus strongly conflicting PDF metadata title"
            )

    if supplement_evidence:
        document_role = DocumentRole.SUPPLEMENT
    elif identity_status == IdentityStatus.MATCH:
        document_role = DocumentRole.ARTICLE
    else:
        document_role = DocumentRole.UNKNOWN

    return IdentityValidationReport(
        status=identity_status,
        document_role=document_role,
        doi_match=doi_match,
        title_similarity=title_similarity,
        evidence=tuple(evidence),
    )
