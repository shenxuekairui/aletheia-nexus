"""Bounded PDF publication evidence for bibliographic acquisition.

Logo-only mastheads need not be OCR-readable when a fully constrained CNKI
record is independently linked to the PDF by its declared DOI, article number,
or year/issue plus consecutive printed page labels and document length.
"""

import re
import unicodedata

from aletheia_nexus.core.paper_request import (
    bibliographic_fields_match,
    compact_bibliography,
    journal_aliases,
)


def journal_in_text(journal: str | None, text: str) -> bool:
    if not journal:
        return False
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()
    for name in journal_aliases(journal):
        needle = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).casefold()
        for match in re.finditer(re.escape(needle), normalized):
            # Do not treat a prefix of an explicitly different edition or
            # institutional name as the requested journal's short masthead.
            qualifier = re.match(r"\([^()]{1,100}\)", normalized[match.end() :])
            if (
                qualifier
                and re.search(r"[^\W\d_]", qualifier[0])
                and not bibliographic_fields_match(
                    "journal", journal, name + qualifier[0]
                )
            ):
                continue
            return True
    return False


def year_in_text(year: int | None, text: str) -> bool:
    if not year:
        return False
    text = unicodedata.normalize("NFKC", text)
    # A DOI suffix (or a URL) containing 2026 is not publication-year evidence.
    text = re.sub(r"(?im)\bdoi\s*[:：][^\n]*", "", text)
    text = re.sub(r"(?i)https?://\S+|10\s*\.\s*\d{4,9}\s*/[^\n]+", "", text)
    # Preserve spaces between year and issue ("2026 04"); accept a dotted
    # masthead date ("2026.05") after excluding DOI/URL spans above.
    digits = r"\s*".join(str(year))
    return bool(re.search(rf"(?<!\d){digits}(?!\d)", text))


def _short_margin(text: str) -> bool:
    return bool(
        text
        and len(compact_bibliography(text)) <= 160
        and not re.search(r"(?i)references|参考文献|[\[［]\s*\d+|[①-⑳]", text)
    )


def margin_publication_match(inspection, journal, year) -> int | None:
    for page in inspection.page_margins[:3]:
        for text in (page.header, page.footer):
            if (
                _short_margin(text)
                and journal_in_text(journal, text)
                and year_in_text(year, text)
            ):
                return page.page_number
    return None


def _year_issue(text, year, issue):
    if not issue or not str(issue).isdigit() or not _short_margin(text):
        return False
    value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    return bool(re.search(rf"(?<!\d){year}年?第?0*{int(issue)}期", value))


def _page_range(value):
    match = re.fullmatch(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*", value or "")
    if match and 0 < int(match[1]) <= int(match[2]):
        return int(match[1]), int(match[2])
    return None


def _printed_page(margins, number):
    # Only a standalone page label, never a year, citation, or a body number.
    return any(
        re.fullmatch(r"\d{1,5}", normalized := compact_bibliography(line))
        and int(normalized) == number
        for line in margins.footer.splitlines()
    )


def _article_number_matches(front, observed, inspection, pages):
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", front))
    text = re.sub(r"[‐‑‒–—⁃−]", "-", text)
    numbers = re.findall(
        r"文章编号[^\d]{0,5}(\d{4}-\d{3}[\dXx])\((\d{4})\)"
        r"(\d{1,3})-(\d{1,5})-(\d{1,3})(?!\d)",
        text,
    )
    if len(numbers) != 1:
        return False
    issn, year, issue, start, length = numbers[0]
    digits = [10 if c.upper() == "X" else int(c) for c in issn if c != "-"]
    return bool(
        sum(d * w for d, w in zip(digits, range(8, 0, -1))) % 11 == 0
        and int(year) == observed.year
        and observed.issue
        and observed.issue.isdigit()
        and int(issue) == int(observed.issue)
        and int(start) == pages[0]
        and int(length) == pages[1] - pages[0] + 1
        and inspection.report.page_count == int(length)
    )


def corroborated_cnki_record(*, target, observed, inspection, front, declared_dois):
    """Return the independent link, not merely the selected candidate's ID.

    This fallback requires caller-specified title, authors, journal and year,
    all confirmed by a stable CNKI record. The caller additionally requires
    exact first-page title/authors and rejects every bibliographic conflict.
    """
    if not (
        observed
        and observed.cnki_id
        and target.title
        and target.authors
        and target.journal
        and target.year
        and compact_bibliography(observed.title or "")
        == compact_bibliography(target.title)
        and all(
            compact_bibliography(a)
            in {compact_bibliography(b) for b in observed.authors}
            for a in target.authors
        )
        and observed.journal
        and bibliographic_fields_match("journal", target.journal, observed.journal)
        and observed.year == target.year
    ):
        return None
    if observed.doi and tuple(declared_dois) == (observed.doi,):
        return "Constrained CNKI record linked by matching declared PDF DOI"

    pages = _page_range(observed.pages)
    if not pages:
        return None
    if _article_number_matches(front, observed, inspection, pages):
        return (
            "Constrained CNKI record linked by PDF article number (year, issue, pages)"
        )
    margins = {p.page_number: p for p in inspection.page_margins[:3]}
    if (
        inspection.report.page_count == pages[1] - pages[0] + 1
        and inspection.report.page_count >= 2
        and 1 in margins
        and 2 in margins
        and _printed_page(margins[1], pages[0])
        and _printed_page(margins[2], pages[0] + 1)
        and any(
            _year_issue(text, observed.year, observed.issue)
            for page in margins.values()
            for text in (page.header, page.footer)
        )
    ):
        return "Constrained CNKI record linked by PDF margin year/issue and consecutive page labels"
    return None
