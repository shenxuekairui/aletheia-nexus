"""CNKI evidence policy shared by file persistence and offline validation."""

import re
from dataclasses import replace

from aletheia_nexus.acquire.fulltext.identity import validate_paper_identity
from aletheia_nexus.acquire.fulltext.models import DocumentRole, IdentityStatus
from aletheia_nexus.acquire.fulltext.publication import (
    corroborated_cnki_record,
    journal_in_text,
    margin_publication_match,
    year_in_text,
)
from aletheia_nexus.core.identifiers.doi import extract_pdf_dois
from aletheia_nexus.core.paper_request import (
    PaperRequest,
    bibliographic_fields_match,
    compact_bibliography,
)

BIBLIOGRAPHIC_POLICY = "cnki_bibliographic/v5"


def validate_bibliographic_identity(
    *,
    target: PaperRequest,
    observed: PaperRequest | None,
    resolved_doi: str,
    inspection,
    source_url: str,
):
    report = validate_paper_identity(
        target_doi=resolved_doi,
        expected_title=target.title,
        inspection=inspection,
        source_url=source_url,
        allow_missing_doi=True,
    )
    evidence = list(report.evidence)
    status = report.status
    front = re.split(
        r"(?im)^\s*(?:references\b|参考文献)", inspection.first_page_text, maxsplit=1
    )[0]
    compact = compact_bibliography(front)
    title = compact_bibliography(target.title or "")
    exact_title = bool(len(title) >= 12 and title in compact)
    authors = target.authors or (observed.authors if observed else ())
    authors_match = bool(authors) and all(
        compact_bibliography(a) in compact for a in authors
    )
    journal = target.journal or (observed.journal if observed else None)
    year = target.year or (observed.year if observed else None)
    publication_match = journal_in_text(journal, front) and year_in_text(year, front)
    margin_page = margin_publication_match(inspection, journal, year)
    record_link = corroborated_cnki_record(
        target=target,
        observed=observed,
        inspection=inspection,
        front=front,
        declared_dois=report.declared_dois,
    )
    bibliographic_match = bool(
        exact_title
        and authors_match
        and (
            publication_match
            or margin_page
            or record_link
            or (target.cnki_id and observed and target.cnki_id == observed.cnki_id)
        )
        and (observed is None or compact_bibliography(observed.title or "") == title)
    )
    if exact_title:
        evidence.append("Exact requested title found in PDF front matter")
    if authors_match:
        evidence.append("Expected authors found in PDF front matter")
    if publication_match:
        evidence.append("Journal and year found in PDF front matter")
    if margin_page:
        evidence.append(f"Journal and year found in PDF page {margin_page} margin")
    if record_link and exact_title and authors_match:
        evidence.append(record_link)

    # Caller constraints are hard when both sides provide a field. Missing
    # fields never become positive evidence. Never silently replace the query.
    conflicts = []
    if observed:
        for field in ("doi", "journal", "year", "volume", "issue", "pages", "cnki_id"):
            wanted, actual = getattr(target, field), getattr(observed, field)
            if (
                wanted
                and actual
                and not bibliographic_fields_match(field, wanted, actual)
            ):
                conflicts.append(field)
        if target.authors and observed.authors:
            actual = {compact_bibliography(a) for a in observed.authors}
            if not all(compact_bibliography(a) in actual for a in target.authors):
                conflicts.append("authors")
        if not target.doi and compact_bibliography(observed.title or "") != title:
            conflicts.append("title")
    if target.authors and not authors_match:
        evidence.append("Requested authors not confirmed in PDF front matter")
        status = IdentityStatus.UNKNOWN
    if conflicts:
        evidence.append("Conflicting bibliographic fields: " + ", ".join(conflicts))
        status = IdentityStatus.MISMATCH
    if report.status == IdentityStatus.MISMATCH:
        status = IdentityStatus.MISMATCH
    elif not conflicts:
        if target.doi:
            # A supplied DOI must not disable the complete bibliographic path.
            # Missing DOI evidence differs from a conflicting DOI, rejected above.
            doi_in_front = target.doi in extract_pdf_dois(front) and (
                target.doi in report.declared_dois or exact_title
            )
            detail_doi = observed and observed.doi == target.doi
            if not doi_in_front and not (detail_doi and exact_title and authors_match):
                if bibliographic_match:
                    status = IdentityStatus.MATCH
                    evidence.append(
                        "Exact PDF title, authors, and publication evidence verify the article without DOI confirmation"
                    )
                else:
                    status = IdentityStatus.UNKNOWN
                    evidence.append(
                        "Missing DOI confirmation requires exact PDF title, authors, and publication evidence or a corroborated CNKI record"
                    )
        else:
            # A candidate DOI alone is insufficient. A fully constrained record
            # may instead be linked to exact PDF title/authors with independent
            # DOI/article-number/pagination evidence when a masthead is graphical.
            if not bibliographic_match:
                status = IdentityStatus.UNKNOWN
                evidence.append(
                    "Title-only identity requires exact PDF title, authors, and publication evidence or a corroborated CNKI record"
                )
            elif report.status != IdentityStatus.UNKNOWN or not report.declared_dois:
                status = IdentityStatus.MATCH
    if len(report.declared_dois) > 1:
        status = IdentityStatus.UNKNOWN
    missing = []
    for field in ("journal", "year", "volume", "issue", "pages", "cnki_id"):
        wanted = getattr(target, field)
        if not wanted:
            continue
        confirmed_detail = (
            observed
            and getattr(observed, field)
            and bibliographic_fields_match(field, wanted, getattr(observed, field))
        )
        confirmed_pdf = (
            journal_in_text(str(wanted), front)
            if field == "journal"
            else year_in_text(wanted, front)
            if field == "year"
            else False
        ) or (field in {"journal", "year"} and bool(margin_page))
        if not (confirmed_detail or confirmed_pdf):
            missing.append(field)
    if missing and status != IdentityStatus.MISMATCH:
        status = IdentityStatus.UNKNOWN
        evidence.append(
            "Unconfirmed requested bibliographic fields: " + ", ".join(missing)
        )
    role = (
        report.document_role
        if report.document_role == DocumentRole.SUPPLEMENT
        else (
            DocumentRole.ARTICLE
            if status == IdentityStatus.MATCH
            else DocumentRole.UNKNOWN
        )
    )
    return replace(
        report,
        status=status,
        document_role=role,
        policy=BIBLIOGRAPHIC_POLICY,
        evidence=tuple(evidence),
    )
