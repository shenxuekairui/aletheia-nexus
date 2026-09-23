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
_AUXILIARY_TEXT_LEAD_TERMS = (
    "reporting summary",
    "peer review file",
    "transparent peer review",
    "peer review information",
    "editorial decision",
    "decision letter",
    "author checklist",
    "reviewer comments",
)
_SUPPLEMENT_FILENAME = re.compile(
    r"(?:^|[_.-])(si|supp|supplement|supplementary)(?:[_.-]|$)",
    re.IGNORECASE,
)
_NON_MAIN_TEXT_LEAD_CHARS = 400
_TITLE_TEXT_LEAD_TOKENS = 200
_TITLE_TEXT_WINDOW_THRESHOLD = 0.85
_TITLE_TEXT_MIN_TOKENS = 8


def _normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _compact_title(value: str) -> str:
    return _normalize_title(value).replace(" ", "")


def _semantic_context(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"[_.-]+", " ", value)
    return " ".join(value.split())


def _title_score(
    expected_title: str, inspection: PdfInspection
) -> tuple[float, str | None, bool]:
    """Return conservative title evidence for identity fallback.

    Exact normalized title occurrence in inspected text is strong evidence. If
    that is absent, only the dedicated PDF metadata title is compared. General
    token overlap across whole pages is intentionally not used for verification
    because scientific vocabulary can recur outside the actual title.
    """

    expected = _normalize_title(expected_title)
    if not expected:
        return 0.0, None, False

    text = _normalize_title(inspection.extracted_text)
    observed_tokens = text.split()[:_TITLE_TEXT_LEAD_TOKENS]
    text_lead = " ".join(observed_tokens)
    if expected in text_lead:
        return 1.0, "Expected title found in inspected PDF text", True

    # Some older publisher PDFs extract their first-page columns out of visual
    # order, putting the actual title hundreds of tokens after the body text.
    # An exact title on page one is still front-matter evidence; do not extend
    # this fallback to later pages, where a reference title could be mistaken
    # for the article's own title.
    if expected in _normalize_title(inspection.first_page_text):
        return 1.0, "Expected title found on PDF first page", True
    # Some ACS PDFs fuse every word of the heading during text extraction.
    # A long exact compact match on page one is still strong front-matter
    # evidence, unlike loose token overlap elsewhere in the document.
    compact_expected = _compact_title(expected_title)
    if len(compact_expected) >= 40 and compact_expected in _compact_title(
        inspection.first_page_text
    ):
        return 1.0, "Expected title found on PDF first page", True

    # PDF text extraction often separates chemical subscripts/superscripts and
    # inserts line-break tokens inside an otherwise exact article title. Search
    # only the beginning of the document (where the title belongs), using a
    # bounded near-length window. This avoids matching a cited paper title deep
    # in the references while recovering typography-heavy chemistry titles.
    expected_tokens = expected.split()
    if len(expected_tokens) >= _TITLE_TEXT_MIN_TOKENS:
        best = 0.0
        for length in range(
            max(1, len(expected_tokens) - 4),
            len(expected_tokens) + 7,
        ):
            for start in range(max(0, len(observed_tokens) - length + 1)):
                window = " ".join(observed_tokens[start : start + length])
                best = max(best, SequenceMatcher(None, expected, window).ratio())
        if best >= _TITLE_TEXT_WINDOW_THRESHOLD:
            return (
                best,
                f"Expected title closely matched PDF text lead (similarity={best:.3f})",
                True,
            )

    if inspection.metadata_title:
        metadata_title = _normalize_title(inspection.metadata_title)
        score = SequenceMatcher(None, expected, metadata_title).ratio()
        return score, f"PDF metadata title similarity={score:.3f}", False

    return 0.0, None, False


def _non_main_evidence(
    source_url: str,
    inspection: PdfInspection,
    *,
    expected_title: str | None = None,
) -> str | None:
    basename = PurePosixPath(unquote(urlsplit(source_url).path)).name.lower()
    normalized_basename = _semantic_context(basename)
    if _SUPPLEMENT_FILENAME.search(basename) or any(
        term in normalized_basename for term in _SUPPLEMENT_TERMS
    ):
        return f"Supplement-like source filename: {basename}"
    if any(term in normalized_basename for term in _AUXILIARY_TERMS):
        return f"Auxiliary-document source filename: {basename}"

    metadata_title = _semantic_context(inspection.metadata_title or "")
    if any(term in metadata_title for term in _SUPPLEMENT_TERMS):
        return "Supplement marker found in PDF metadata title"
    if any(term in metadata_title for term in _AUXILIARY_TERMS):
        return "Auxiliary-document marker found in PDF metadata title"

    text_lead = _semantic_context(inspection.extracted_text[:_NON_MAIN_TEXT_LEAD_CHARS])
    if any(term in text_lead for term in _SUPPLEMENT_TERMS):
        # Some publisher article PDFs render navigation labels such as
        # "Supporting Information" in the first-page header. Do not let that
        # one label override complete main-article front matter: the expected
        # title plus an Abstract section. Filename and metadata supplement
        # signals above remain authoritative.
        article_lead = _semantic_context(inspection.extracted_text[:2_000])
        expected = _normalize_title(expected_title or "")
        compact_expected = _compact_title(expected_title or "")
        lead_title = _normalize_title(inspection.extracted_text[:2_000])
        main_article_front_matter = bool(
            expected
            and (
                expected in lead_title
                or (
                    len(compact_expected) >= 40
                    and compact_expected in lead_title.replace(" ", "")
                )
            )
            and re.search(r"\babstract\b", article_lead)
        )
        if not main_article_front_matter:
            return "Supplement marker found at the beginning of the PDF"
    if any(term in text_lead for term in _AUXILIARY_TEXT_LEAD_TERMS):
        return "Auxiliary-document marker found at the beginning of the PDF"

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
    first_page_doi_match = normalized_doi in extract_dois(inspection.first_page_text)
    locked_encrypted = (
        inspection.report.encrypted and inspection.report.page_count is None
    )

    if doi_match:
        evidence.append("Target DOI found in inspected PDF text")

    title_similarity: float | None = None
    title_match = False
    if expected_title is not None:
        if not isinstance(expected_title, str):
            raise TypeError("expected_title must be a string or None")
        if expected_title.strip():
            title_similarity, title_evidence, title_from_text = _title_score(
                expected_title,
                inspection,
            )
            title_threshold = _TITLE_TEXT_WINDOW_THRESHOLD if title_from_text else 0.92
            title_match = title_similarity >= title_threshold and not locked_encrypted
            if title_evidence:
                evidence.append(title_evidence)

    non_main_evidence = _non_main_evidence(
        source_url,
        inspection,
        expected_title=expected_title,
    )
    if non_main_evidence:
        evidence.append(non_main_evidence)

    if locked_encrypted:
        identity_status = IdentityStatus.UNKNOWN
        evidence.append(
            "Encrypted PDF could not be opened; metadata alone is insufficient "
            "for scholarly identity verification"
        )
    elif first_page_doi_match or title_match:
        identity_status = IdentityStatus.MATCH
    else:
        identity_status = IdentityStatus.UNKNOWN
        if doi_match:
            evidence.append(
                "Target DOI appears outside PDF first page without matching title"
            )
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

    if non_main_evidence:
        # DocumentRole.SUPPLEMENT is the existing v0.5 umbrella for a valid
        # scholarly PDF that is clearly not the main article. This includes
        # supplementary information and auxiliary files such as reporting
        # summaries, peer-review files and source-data documents.
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
