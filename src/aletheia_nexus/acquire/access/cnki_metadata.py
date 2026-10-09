"""Observed citation fields and stable CNKI identifiers, without opaque tokens."""

import re
from urllib.parse import parse_qs, urlsplit

from aletheia_nexus.core.identifiers.doi import extract_dois
from aletheia_nexus.core.paper_request import (
    PaperRequest,
    bibliographic_field_key,
    compact_bibliography,
)


def cnki_record_id(url: str) -> str | None:
    parts = urlsplit(url)
    if not (
        parts.hostname == "cnki.net" or (parts.hostname or "").endswith(".cnki.net")
    ):
        return None
    query = {key.casefold(): values for key, values in parse_qs(parts.query).items()}
    database = (query.get("dbcode") or [""])[0]
    filename = (query.get("filename") or [""])[0]
    if re.fullmatch(r"[A-Za-z0-9_]+", database) and re.fullmatch(
        r"[A-Za-z0-9_.-]+", filename
    ):
        return f"cnki:{database}:{filename}".casefold()
    return None


def detail_dois(page) -> tuple[str, ...]:
    """Only citation fields or a DOI-labelled article metadata row, not references."""
    found = []
    for selector in (
        "meta[name='citation_doi']",
        "meta[name='dc.Identifier' i]",
        "meta[name='DC.Identifier.DOI' i]",
    ):
        nodes = page.locator(selector)
        for index in range(min(nodes.count(), 10)):
            found.extend(extract_dois(nodes.nth(index).get_attribute("content") or ""))
    nodes = page.locator(".row li")
    for index in range(min(nodes.count(), 40)):
        text = nodes.nth(index).inner_text().strip()
        if re.match(r"^DOI\s*[：:]", text, re.I):
            found.extend(extract_dois(text))
    return tuple(dict.fromkeys(found))


def detail_bibliography(page, *, fallback_title: str) -> PaperRequest:
    def values(selectors):
        found = []
        for selector in selectors:
            nodes = page.locator(selector)
            for index in range(min(nodes.count(), 30)):
                node = nodes.nth(index)
                value = node.get_attribute("content") or node.inner_text()
                if value and value.strip():
                    found.append(value.strip())
            if found:
                break
        return tuple(dict.fromkeys(found))

    def first(*selectors):
        found = values(selectors)
        return found[0] if found else None

    title = (
        first(
            "meta[name='citation_title']", "meta[name='dc.Title' i]", ".wx-tit h1", "h1"
        )
        or fallback_title
    )
    authors = values(
        (
            "meta[name='citation_author']",
            "meta[name='dc.Creator' i]",
            "#authorpart span",
            ".author:first-of-type span a",
        )
    )
    authors = tuple(re.sub(r"[\d\s,*，]+$", "", a) for a in authors)
    authors = tuple(a for a in authors if a)
    doi_values = detail_dois(page)
    date = (
        first(
            "meta[name='citation_publication_date']",
            "meta[name='citation_date']",
            "meta[name='dc.Date' i]",
        )
        or ""
    )
    year = re.search(r"\b(?:19|20)\d{2}\b", date)
    first_page = first("meta[name='citation_firstpage']")
    last_page = first("meta[name='citation_lastpage']")
    record = cnki_record_id(page.url)
    if not record:
        database, filename = (
            page.locator("#paramdbcode"),
            page.locator("#param-filename"),
        )
        if database.count() and filename.count():
            db, file = (
                database.first.get_attribute("value"),
                filename.first.get_attribute("value"),
            )
            if (
                db
                and file
                and re.fullmatch(r"[A-Za-z0-9_]+", db)
                and re.fullmatch(r"[A-Za-z0-9_.-]+", file)
            ):
                record = f"cnki:{db}:{file}".casefold()
    if not record:
        for selector in ("meta[name='citation_abstract_html_url']", "a#pdfDown"):
            nodes = page.locator(selector)
            if nodes.count():
                node = nodes.first
                record = cnki_record_id(
                    node.get_attribute("content") or node.get_attribute("href") or ""
                )
                if record:
                    break
    journal = first("meta[name='citation_journal_title']", "meta[name='dc.Source' i]")
    volume, issue = (
        first("meta[name='citation_volume']"),
        first("meta[name='citation_issue']"),
    )
    pages = first_page + "-" + last_page if first_page and last_page else first_page
    # Current kcms2 exposes publication data in its header, not citation metas.
    header = first(".top-tip") or ""
    publication = re.match(
        r"^(.+?)\s*[.。]\s*((?:19|20)\d{2})\s*[,，]?\s*(\d+)?\s*[（(]\s*(\d+)\s*[）)]\s*[:：]?\s*([\d]+(?:\s*[-–—]\s*[\d]+)?)?",
        header,
    )
    if publication:
        journal = journal or publication[1].strip()
        year = year or re.search(r"\d{4}", publication[2])
        volume, issue = volume or publication[3], issue or publication[4]
        pages = pages or publication[5]
    return PaperRequest(
        doi=doi_values[0] if len(doi_values) == 1 else None,
        title=title,
        authors=authors,
        journal=journal,
        year=int(year[0]) if year else None,
        volume=volume,
        issue=issue,
        pages=pages,
        cnki_id=record,
    )


def conflicting_fields(target: PaperRequest, observed: PaperRequest) -> tuple[str, ...]:
    fields = []
    for field in ("doi", "journal", "year", "volume", "issue", "pages", "cnki_id"):
        wanted, actual = getattr(target, field), getattr(observed, field)
        if (
            wanted
            and actual
            and bibliographic_field_key(field, wanted)
            != bibliographic_field_key(field, actual)
        ):
            fields.append(field)
    if target.authors and observed.authors:
        actual = {compact_bibliography(a) for a in observed.authors}
        if not all(compact_bibliography(a) in actual for a in target.authors):
            fields.append("authors")
    return tuple(fields)
