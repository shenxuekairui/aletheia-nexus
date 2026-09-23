from aletheia_nexus.acquire.fulltext.identity import validate_paper_identity
from aletheia_nexus.acquire.fulltext.models import (
    DocumentRole,
    IdentityStatus,
    PdfValidationReport,
)
from aletheia_nexus.acquire.fulltext.validation import PdfInspection


def _inspection(
    *, text="", title=None, encrypted=False, page_count=3, first_page_text=None
):
    return PdfInspection(
        report=PdfValidationReport(
            valid_pdf=True,
            magic_bytes_ok=True,
            parseable=True,
            page_count=page_count,
            encrypted=encrypted,
        ),
        metadata_title=title,
        extracted_text=text,
        first_page_text=text if first_page_text is None else first_page_text,
    )


def test_exact_doi_match_verifies_article_identity():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        inspection=_inspection(
            text="Article DOI: 10.1000/xyz123",
            first_page_text="Article DOI: 10.1000/xyz123",
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE
    assert result.doi_match is True


def test_doi_only_in_later_pages_does_not_verify_cited_article():
    result = validate_paper_identity(
        target_doi="10.1000/target",
        source_url="https://example.org/other-paper.pdf",
        inspection=_inspection(
            text=(
                "A different paper DOI 10.9999/other. "
                "References include DOI 10.1000/target."
            ),
            first_page_text="A different paper DOI 10.9999/other.",
        ),
    )

    assert result.doi_match is True
    assert result.status == IdentityStatus.UNKNOWN
    assert result.document_role == DocumentRole.UNKNOWN


def test_later_page_doi_with_exact_first_page_title_still_verifies():
    title = "Electrochemical Transformation of Carbon Dioxide at Copper Interfaces"
    result = validate_paper_identity(
        target_doi="10.1000/target",
        source_url="https://example.org/paper.pdf",
        expected_title=title,
        inspection=_inspection(
            text=f"{title} ABSTRACT: Results. DOI 10.1000/target",
            first_page_text=f"{title} ABSTRACT: Results.",
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE


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


def test_title_lead_matching_tolerates_split_chemical_formula_typography():
    result = validate_paper_identity(
        target_doi="10.1000/chemistry",
        source_url="https://example.org/main.pdf",
        expected_title=(
            "Appraisal of Ce1-yGdyO2-y/2 electrolytes for IT-SOFC operation at 500°C"
        ),
        inspection=_inspection(
            text=(
                "Appraisal of Ce1 y Gd y O2 y 2 electrolytes for IT SOFC "
                "operation at 500 C Authors and affiliations"
            ),
            title="Elsevier main.pdf",
            first_page_text="",
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE
    assert result.title_similarity is not None
    assert result.title_similarity >= 0.85
    assert any("text lead" in item for item in result.evidence)


def test_similar_title_in_late_reference_text_does_not_verify_identity():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/main.pdf",
        expected_title="Electrocatalytic Water Activation at Interfaces",
        inspection=_inspection(
            text=(
                ("Unrelated article body words " * 80)
                + " Electrocatalytic Water Activation at Interfaces"
            ),
            first_page_text="Unrelated article body words " * 80,
        ),
    )

    assert result.status == IdentityStatus.UNKNOWN
    assert result.document_role == DocumentRole.UNKNOWN


def test_exact_title_late_in_first_page_extraction_verifies_identity():
    title = "Materials for fuel-cell technologies"
    first_page = "Unrelated column extraction order " * 230 + title
    result = validate_paper_identity(
        target_doi="10.1038/35104620",
        source_url="https://www.nature.com/articles/35104620.pdf",
        expected_title=title,
        inspection=_inspection(text=first_page, first_page_text=first_page),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE
    assert "Expected title found on PDF first page" in result.evidence


def test_exact_title_on_later_page_still_does_not_verify_identity():
    title = "Materials for fuel-cell technologies"
    result = validate_paper_identity(
        target_doi="10.1038/35104620",
        source_url="https://www.nature.com/articles/35104620.pdf",
        expected_title=title,
        inspection=_inspection(
            text="Unrelated article body " * 100 + title,
            first_page_text="Unrelated article body " * 100,
        ),
    )

    assert result.status == IdentityStatus.UNKNOWN


def test_locked_encrypted_pdf_cannot_be_verified_from_metadata_title_alone():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        expected_title="Electrocatalytic Water Activation at Interfaces",
        inspection=_inspection(
            title="Electrocatalytic Water Activation at Interfaces",
            encrypted=True,
            page_count=None,
        ),
    )

    assert result.status == IdentityStatus.UNKNOWN
    assert result.document_role == DocumentRole.UNKNOWN
    assert result.title_similarity == 1.0
    assert any("Encrypted PDF" in item for item in result.evidence)


def test_supplement_marker_blocks_article_role_even_when_doi_matches():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/xyz123_si_001.pdf",
        inspection=_inspection(text="10.1000/xyz123"),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.SUPPLEMENT


def test_auxiliary_filename_blocks_article_role_even_when_doi_matches():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/reporting-summary.pdf",
        inspection=_inspection(text="10.1000/xyz123"),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.SUPPLEMENT
    assert any("Auxiliary-document" in item for item in result.evidence)


def test_auxiliary_metadata_title_blocks_article_role():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/file.pdf",
        inspection=_inspection(
            text="10.1000/xyz123",
            title="Transparent Peer Review File",
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.SUPPLEMENT


def test_auxiliary_text_lead_blocks_article_role():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/file.pdf",
        inspection=_inspection(
            text="Reporting Summary for this article. DOI 10.1000/xyz123",
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.SUPPLEMENT


def test_source_data_phrase_in_article_text_does_not_force_non_main_role():
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        inspection=_inspection(
            text=(
                "Article DOI: 10.1000/xyz123. Source data were collected from "
                "three independent experiments and analyzed statistically."
            )
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE


def test_article_is_not_marked_supplement_for_late_supporting_information_phrase():
    text = (
        "Article DOI: 10.1000/xyz123 "
        + "A" * 500
        + " Supporting Information is available online."
    )
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/paper.pdf",
        inspection=_inspection(text=text),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE


def test_article_navigation_supporting_information_label_does_not_override_front_matter():
    title = (
        "Tunable Hydrated Channels in Covalent Organic Framework Membrane "
        "for Seawater Desalination"
    )
    result = validate_paper_identity(
        target_doi="10.1021/acsnano.5c01551",
        source_url="https://pubs.acs.org/article-pdf/nn5c01551.pdf",
        expected_title=title,
        inspection=_inspection(
            text=(
                f"ACS Nano ARTICLE {title} Authors Cite This Supporting Information "
                "ABSTRACT Nanofiltration and reverse osmosis are pressure-driven "
                "membrane desalination processes. DOI 10.1021/acsnano.5c01551"
            )
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE


def test_fused_acs_title_and_supporting_information_nav_are_main_article():
    title = (
        "Electrosynthesis of Ethylene Glycol from Methanol via Oxidative C-C Coupling"
    )
    result = validate_paper_identity(
        target_doi="10.1021/jacs.6c03536",
        source_url="https://pubs.acs.org/jacsat/article-pdf/ja6c03536.pdf",
        expected_title=title,
        inspection=_inspection(
            text=(
                "ElectrosynthesisofEthyleneGlycolfromMethanolviaOxidative "
                "C−CCoupling Authors Cite This Supporting Information "
                "ABSTRACT: Ethylene glycol is a commodity chemical. "
                "DOI 10.1021/jacs.6c03536"
            ),
            first_page_text=(
                "ElectrosynthesisofEthyleneGlycolfromMethanolviaOxidative "
                "C−CCoupling Authors Cite This Supporting Information "
                "ABSTRACT: Ethylene glycol is a commodity chemical. "
                "DOI 10.1021/jacs.6c03536"
            ),
            title="ja6c03536 1..10",
        ),
    )

    assert result.status == IdentityStatus.MATCH
    assert result.document_role == DocumentRole.ARTICLE
    assert result.title_similarity == 1.0


def test_true_supplement_heading_without_article_abstract_remains_supplement():
    title = "Target Main Article"
    result = validate_paper_identity(
        target_doi="10.1000/xyz123",
        source_url="https://example.org/file.pdf",
        expected_title=title,
        inspection=_inspection(
            text=(
                f"Supporting Information {title} Experimental details and "
                "additional figures DOI 10.1000/xyz123"
            )
        ),
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
