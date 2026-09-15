from aletheia_nexus.acquire.fulltext.identity import validate_paper_identity
from aletheia_nexus.acquire.fulltext.models import (
    DocumentRole,
    IdentityStatus,
    PdfValidationReport,
)
from aletheia_nexus.acquire.fulltext.validation import PdfInspection


def _inspection(*, text="", title=None):
    return PdfInspection(
        report=PdfValidationReport(
            valid_pdf=True,
            magic_bytes_ok=True,
            parseable=True,
            page_count=3,
            encrypted=False,
        ),
        metadata_title=title,
        extracted_text=text,
    )


def test_exact_doi_match_verifies_article_identity():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        inspection=_inspection(text="Article DOI: 10.1000/xyz123"),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE
    assert result.doi_match is True


def test_metadata_title_can_verify_when_doi_is_absent():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        expected_title="Electrocatalytic Water Activation at Interfaces",
        inspection=_inspection(
            title="Electrocatalytic Water Activation at Interfaces",
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE
    assert result.title_similarity == 1.0


def test_supplement_marker_blocks_article_role_even_when_doi_matches():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/xyz123_si_001.pdf",
        inspection=_inspection(text="10.1000/xyz123"),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.SUPPLEMENT


def test_insufficient_evidence_remains_unknown():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        inspection=_inspection(text="Some unrelated readable text"),
    )

    assert result.status == IdentityStatus.UNKNOWN
    assert result.document_role == DocumentRole.UNKNOWN


def test_strong_conflicting_doi_and_title_evidence_can_mark_mismatch():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        expected_title="Electrocatalytic Water Activation at Interfaces",
        inspection=_inspection(
            text="DOI: 10.9999/unrelated-paper",
            title="Genomics of Marine Microorganisms",
        ),
    )

    assert result.status == IdentityStatus.MISMATCH
    assert result.document_role == DocumentRole.UNKNOWN
