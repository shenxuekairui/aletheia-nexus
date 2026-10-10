from dataclasses import replace

import pytest

from aletheia_nexus.acquire.fulltext.bibliographic import (
    validate_bibliographic_identity,
)
from aletheia_nexus.acquire.fulltext.models import IdentityStatus, PdfValidationReport
from aletheia_nexus.acquire.fulltext.validation import PdfInspection
from aletheia_nexus.core.paper_request import PaperRequest

TITLE = "Accurate identification of scientific articles without digital identifiers"
REQUEST = PaperRequest(
    title=TITLE, authors=("Alice Chen",), journal="Journal of Testing", year=2024
)
TEXT = TITLE + "\nAlice Chen\nJournal of Testing 2024\nAbstract\nOriginal research."


def validate(target=REQUEST, observed=REQUEST, text=TEXT, doi=""):
    inspection = PdfInspection(
        PdfValidationReport(True, True, True, 1, False), TITLE, text, text
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
    assert result.policy == "cnki_bibliographic/v3"
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
def test_missing_pdf_evidence_never_verifies(removed):
    assert validate(text=TEXT.replace(removed, "")).status != IdentityStatus.MATCH


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


def test_known_doi_cannot_fall_back_to_title_alone():
    request = replace(REQUEST, doi="10.1000/target")
    assert (
        validate(target=request, observed=REQUEST, doi=request.doi).status
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
