from dataclasses import replace

import pytest

from aletheia_nexus.acquire.fulltext.bibliographic import (
    validate_bibliographic_identity,
)
from aletheia_nexus.acquire.fulltext.models import IdentityStatus, PdfValidationReport
from aletheia_nexus.acquire.fulltext.validation import PdfInspection, PdfPageMargins
from aletheia_nexus.core.paper_request import PaperRequest, bibliographic_field_key

TITLE = "Accurate identification of scientific articles without digital identifiers"
REQUEST = PaperRequest(
    title=TITLE, authors=("Alice Chen",), journal="Journal of Testing", year=2024
)
TEXT = TITLE + "\nAlice Chen\nJournal of Testing 2024\nAbstract\nOriginal research."


def validate(target=REQUEST, observed=REQUEST, text=TEXT, doi="", margins=(), pages=1):
    inspection = PdfInspection(
        PdfValidationReport(True, True, True, pages, False), TITLE, text, text, margins
    )
    return validate_bibliographic_identity(
        target=target,
        observed=observed,
        resolved_doi=doi,
        inspection=inspection,
        source_url="https://kns.cnki.net/article.pdf",
    )


def test_no_doi_identity_uses_independent_pdf_evidence():
    result = validate()
    assert result.status == IdentityStatus.MATCH
    assert not result.doi_match
    assert result.policy == "cnki_bibliographic/v5"
    assert REQUEST.article_id.startswith("bibliographic:")


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", TITLE + " revisited"),
        ("authors", ("Bob Li",)),
        ("journal", "Another Journal"),
        ("year", 2023),
    ],
)
def test_candidate_bibliography_cannot_replace_requested_identity(field, value):
    assert (
        validate(observed=replace(REQUEST, **{field: value})).status
        == IdentityStatus.MISMATCH
    )


@pytest.mark.parametrize("removed", [TITLE, "Alice Chen", "Journal of Testing", "2024"])
@pytest.mark.parametrize("doi", [None, "10.1000/target"])
def test_missing_pdf_evidence_never_verifies(removed, doi):
    assert (
        validate(
            target=replace(REQUEST, doi=doi),
            text=TEXT.replace(removed, ""),
            doi=doi or "",
        ).status
        != IdentityStatus.MATCH
    )


def test_bare_title_can_use_observed_bibliography_only_with_pdf_confirmation():
    assert validate(target=PaperRequest(title=TITLE)).status == IdentityStatus.MATCH
    assert (
        validate(
            target=PaperRequest(title=TITLE), observed=PaperRequest(title=TITLE)
        ).status
        != IdentityStatus.MATCH
    )


def test_discovered_doi_is_not_proof_of_selected_candidate():
    assert (
        validate(
            target=PaperRequest(title=TITLE),
            observed=PaperRequest(title=TITLE, doi="10.1000/discovered"),
            doi="10.1000/discovered",
            text="DOI: 10.1000/discovered",
        ).status
        != IdentityStatus.MATCH
    )


def test_reference_doi_and_citation_never_verify_no_doi_target():
    assert (
        validate(text="Other article\nReferences\n" + TEXT).status
        != IdentityStatus.MATCH
    )


def test_known_doi_can_use_complete_bibliography_but_not_title_alone():
    request = replace(REQUEST, doi="10.1000/target")
    report = validate(target=request, observed=REQUEST, doi=request.doi)
    assert report.status == IdentityStatus.MATCH
    assert not report.doi_match
    assert not report.declared_dois
    assert any("without DOI confirmation" in e for e in report.evidence)
    assert (
        validate(target=request, observed=REQUEST, text=TITLE, doi=request.doi).status
        != IdentityStatus.MATCH
    )
    assert (
        validate(target=request, observed=request, doi=request.doi).status
        == IdentityStatus.MATCH
    )
    assert (
        validate(
            target=request,
            observed=request,
            text=TEXT + "\nDOI: 10.1000/wrong",
            doi=request.doi,
        ).status
        == IdentityStatus.MISMATCH
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("doi", "10.1000/wrong"),
        ("authors", ("Bob Li",)),
        ("journal", "Other Journal"),
        ("year", 2023),
    ],
)
def test_complete_pdf_bibliography_does_not_override_detail_conflicts(field, value):
    request = replace(REQUEST, doi="10.1000/target")
    assert (
        validate(
            target=request, observed=replace(REQUEST, **{field: value}), doi=request.doi
        ).status
        == IdentityStatus.MISMATCH
    )


def test_known_doi_bibliographic_fallback_requires_consistent_detail_title():
    request = replace(REQUEST, doi="10.1000/target")
    assert (
        validate(
            target=request,
            observed=replace(REQUEST, title=TITLE + " revisited"),
            doi=request.doi,
        ).status
        != IdentityStatus.MATCH
    )


def test_known_doi_bibliographic_fallback_ignores_reference_only_evidence():
    request = replace(REQUEST, doi="10.1000/target")
    assert (
        validate(
            target=request, text="Another article\nReferences\n" + TEXT, doi=request.doi
        ).status
        != IdentityStatus.MATCH
    )


def test_known_doi_bibliographic_fallback_does_not_promote_multiple_declared_dois():
    request = replace(REQUEST, doi="10.1000/target")
    report = validate(
        target=request,
        text=TEXT + "\nDOI: 10.1000/target\nDOI: 10.1000/other",
        doi=request.doi,
    )
    assert report.status != IdentityStatus.MATCH


@pytest.mark.parametrize(
    "field,value",
    [
        ("volume", "42"),
        ("issue", "3"),
        ("pages", "11-20"),
        ("cnki_id", "cnki:cjfd:testing20240301"),
    ],
)
def test_additional_constraints_require_confirmation(field, value):
    request = replace(REQUEST, **{field: value})
    assert validate(target=request).status != IdentityStatus.MATCH
    assert validate(target=request, observed=request).status == IdentityStatus.MATCH


def test_cnki_record_and_authors_can_verify_when_publication_fields_absent():
    request = PaperRequest(
        title=TITLE, authors=("Alice Chen",), cnki_id="cnki:cjfd:testing20240301"
    )
    assert validate(target=request, observed=request).status == IdentityStatus.MATCH
    assert (
        validate(target=request, observed=replace(request, cnki_id=None)).status
        != IdentityStatus.MATCH
    )


def test_request_key_preserves_constraints_without_fake_dois():
    assert REQUEST.doi is None
    assert REQUEST.key == replace(REQUEST, title="  " + TITLE.upper() + "  ").key
    assert REQUEST.key != replace(REQUEST, year=2023).key
    assert REQUEST.key != replace(REQUEST, authors=("Bob Li",)).key
    assert (
        PaperRequest(doi="https://doi.org/10.1000/ABC").article_id == "doi:10.1000/abc"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"doi": "fake"},
        {"title": ""},
        {"title": TITLE, "authors": "Alice"},
        {"title": TITLE, "year": True},
        {"title": TITLE, "cnki_id": "https://cnki.net/"},
    ],
)
def test_invalid_requests_rejected(kwargs):
    with pytest.raises((ValueError, TypeError)):
        PaperRequest(**kwargs)


@pytest.mark.parametrize(
    "short,full",
    [
        ("舞台研究", "舞台研究（东江艺术学院学报）"),
        ("理论探索", "理论探索(示例大学学报)"),
        ("跨文化论丛", "跨文化论丛（东江传媒学院学报）"),
    ],
)
def test_institutional_apposition_matches_main_title_in_both_directions(short, full):
    for wanted, actual in ((short, full), (full, short)):
        target = replace(REQUEST, journal=wanted)
        observed = replace(REQUEST, journal=actual)
        assert (
            validate(target, observed, TEXT.replace(REQUEST.journal, short)).status
            == IdentityStatus.MATCH
        )


def test_journal_subtitles_are_not_generically_stripped():
    for name in ("测试学报", "测试学报(自然科学版)", "测试学报(社会科学版)"):
        assert bibliographic_field_key("journal", name) != bibliographic_field_key(
            "journal", "测试学报(医学版)"
        )
    assert (
        validate(observed=replace(REQUEST, journal="Journal of Testing Letters")).status
        == IdentityStatus.MISMATCH
    )
    target = replace(REQUEST, journal="理论探索（甲方大学学报）")
    observed = replace(REQUEST, journal="理论探索（乙方大学学报）")
    assert validate(target=target, observed=observed).status == IdentityStatus.MISMATCH


@pytest.mark.parametrize(
    "requested,printed",
    [
        ("测试学报", "测试学报（自然科学版）"),
        ("理论探索（甲方大学学报）", "理论探索（乙方大学学报）"),
        ("Journal of Testing", "Journal of Testing (Medical Edition)"),
    ],
)
def test_pdf_explicitly_different_edition_is_not_a_short_name(requested, printed):
    assert (
        validate(
            target=replace(REQUEST, journal=requested),
            observed=None,
            text=TEXT.replace(REQUEST.journal, printed),
        ).status
        != IdentityStatus.MATCH
    )


@pytest.mark.parametrize(
    "issn,year,issue,start,length",
    [
        ("1234-5679", 2011, 1, 101, 3),
        ("2049-3630", 2027, 12, 1007, 9),
    ],
)
def test_article_number_rule_is_independent_of_specific_journal_and_year(
    issn, year, issue, start, length
):
    target = replace(REQUEST, year=year, issue=str(issue))
    observed = replace(
        target, pages=f"{start}-{start + length - 1}", cnki_id="cnki:cjfq:synthetic"
    )
    text = (
        TITLE
        + f"\nAlice Chen\n文章编号:{issn}({year}){issue:02d}-{start:04d}-{length:02d}"
    )
    assert validate(target, observed, text, pages=length).status == IdentityStatus.MATCH


def test_second_page_masthead_confirms_publication_without_scanning_body():
    text = TEXT.replace("Journal of Testing 2024", "")
    margins = (PdfPageMargins(2, "Journal of Testing\n2024 03期", "022"),)
    result = validate(text=text, margins=margins)
    assert result.status == IdentityStatus.MATCH
    assert "Journal and year found in PDF page 2 margin" in result.evidence
    assert (
        validate(text=text + "\nReferences\nJournal of Testing 2024").status
        != IdentityStatus.MATCH
    )
    assert (
        validate(
            text=text, margins=(PdfPageMargins(2, "[1] Journal of Testing 2024"),)
        ).status
        != IdentityStatus.MATCH
    )


@pytest.mark.parametrize("year_text", ["2024.05", "2024 05期", "2 0 2 4年第5期"])
def test_publication_year_accepts_masthead_formats(year_text):
    assert validate(text=TEXT.replace("2024", year_text)).status == IdentityStatus.MATCH


@pytest.mark.parametrize(
    "identifier",
    [
        "DOI: 10.1000/2024",
        "10.1000/2024",
        "10 . 1000 /2024",
        "https://example.org/2024",
    ],
)
def test_doi_or_url_year_is_not_publication_year(identifier):
    assert (
        validate(text=TEXT.replace("2024", "") + "\n" + identifier).status
        != IdentityStatus.MATCH
    )


def _constrained_record(**fields):
    return replace(
        REQUEST, issue="3", pages="21-27", cnki_id="cnki:cjfq:test202403001", **fields
    )


def test_logo_only_journal_uses_independently_matching_pdf_doi():
    observed = _constrained_record(doi="10.1000/logo")
    text = TITLE + "\nAlice Chen\nDOI: 10.1000/logo"
    result = validate(observed=observed, text=text, doi=observed.doi)
    assert result.status == IdentityStatus.MATCH
    assert any("linked by matching declared PDF DOI" in e for e in result.evidence)
    assert (
        validate(
            observed=observed,
            text=text.replace("Alice Chen", "Bob Li"),
            doi=observed.doi,
        ).status
        != IdentityStatus.MATCH
    )
    assert (
        validate(
            observed=observed,
            text=text.replace(TITLE, "Unrelated article"),
            doi=observed.doi,
        ).status
        != IdentityStatus.MATCH
    )
    assert (
        validate(
            observed=observed,
            text=TITLE + "\nAlice Chen\nReferences\nDOI: 10.1000/logo",
            doi=observed.doi,
        ).status
        != IdentityStatus.MATCH
    )


@pytest.mark.parametrize(
    "field,value",
    [("journal", None), ("year", None), ("authors", ()), ("cnki_id", None)],
)
def test_selected_doi_does_not_rescue_incomplete_record(field, value):
    observed = replace(_constrained_record(doi="10.1000/logo"), **{field: value})
    text = TITLE + "\nAlice Chen\nDOI: 10.1000/logo"
    assert (
        validate(observed=observed, text=text, doi=observed.doi).status
        != IdentityStatus.MATCH
    )


@pytest.mark.parametrize(
    "field,value", [("journal", None), ("year", None), ("authors", ())]
)
def test_selected_record_does_not_supply_missing_caller_constraints(field, value):
    observed = _constrained_record(doi="10.1000/logo")
    text = TITLE + "\nAlice Chen\nDOI: 10.1000/logo"
    assert (
        validate(
            target=replace(REQUEST, **{field: value}),
            observed=observed,
            text=text,
            doi=observed.doi,
        ).status
        != IdentityStatus.MATCH
    )


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "wrong_issue",
        "wrong_start",
        "wrong_count",
        "invalid_issn",
        "reference_only",
    ],
)
def test_article_number_correlates_issue_pagination_and_pdf_length(mutation):
    observed = _constrained_record()
    number = "【文章编号】１２３４⁃５６７９（２０２４）０３⁃００２１⁃０７"
    if mutation == "wrong_issue":
        number = number.replace("０３", "０４")
    if mutation == "wrong_start":
        number = number.replace("００２１", "００２２")
    if mutation == "wrong_count":
        number = number.replace("０７", "０８")
    if mutation == "invalid_issn":
        number = number.replace("５６７９", "５６７０")
    if mutation == "reference_only":
        number = "References\n" + number
    result = validate(
        observed=observed, text=TITLE + "\nAlice Chen\n" + number, pages=7
    )
    assert (result.status == IdentityStatus.MATCH) == (mutation is None)


@pytest.mark.parametrize(
    "mutation",
    [None, "wrong_year", "wrong_issue", "wrong_page", "wrong_count", "no_record"],
)
def test_margin_year_issue_and_consecutive_pages_link_logo_only_pdf(mutation):
    observed = _constrained_record()
    header = "2024年第3期"
    footer = "022"
    pages = 7
    if mutation == "wrong_year":
        header = "2023年第3期"
    if mutation == "wrong_issue":
        header = "2024年第4期"
    if mutation == "wrong_page":
        footer = "023"
    if mutation == "wrong_count":
        pages = 8
    if mutation == "no_record":
        observed = replace(observed, cnki_id=None)
    margins = (PdfPageMargins(1, "", "021"), PdfPageMargins(2, header, footer))
    result = validate(
        observed=observed, text=TITLE + "\nAlice Chen", margins=margins, pages=pages
    )
    assert (result.status == IdentityStatus.MATCH) == (mutation is None)
