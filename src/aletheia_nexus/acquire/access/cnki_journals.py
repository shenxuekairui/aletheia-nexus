"""Reviewed CNKI journal coverage, not learned per-paper download history.

Entries require a primary publisher/CNKI source explicitly documenting coverage
and ISSNs. Journal coverage is a routing hint, not proof that an individual paper
is present, entitled, or verified. Unknown journals retain ordinary routing.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndexedJournal:
    issns: tuple[str, ...]
    names: tuple[str, ...]
    evidence_url: str
    reviewed_on: str
    doi_patterns: tuple[str, ...] = ()
    doi_evidence_urls: tuple[str, ...] = ()


CNKI_INDEXED_JOURNALS = (
    IndexedJournal(
        issns=("1006-3471", "2993-074X"),
        names=("Journal of Electrochemistry", "电化学", "电化学（中英文）"),
        evidence_url="https://electrochem.xmu.edu.cn/CN/column/column1.shtml",
        reviewed_on="2026-10-10",
        doi_patterns=(r"10\.61558/2993-074x\.[0-9]+",),
        doi_evidence_urls=("https://electrochem.xmu.edu.cn/CN/Y2024/V30/I11",),
    ),
)


def _issn(value):
    if not isinstance(value, str):
        return None
    compact = value.strip().upper().replace("-", "")
    if not re.fullmatch(r"[0-9]{7}[0-9X]", compact):
        return None
    digits = [int(c) if c != "X" else 10 for c in compact]
    if sum(value * weight for value, weight in zip(digits, range(8, 0, -1))) % 11:
        return None
    return compact[:4] + "-" + compact[4:]


def cnki_indexed_journal(metadata):
    """Exact checked ISSN only: never substring/fuzzy title or DOI inference."""
    values = getattr(metadata, "issn", ()) or ()
    if not isinstance(values, (tuple, list)):
        return None
    observed = {_issn(value) for value in values}
    for journal in CNKI_INDEXED_JOURNALS:
        matches = observed.intersection(journal.issns)
        if matches:
            return min(matches), journal
    return None


def cnki_journal_from_doi(doi, metadata=None):
    """Cheap positive route hint from reviewed *journal* namespaces, not issuers.

    DOI strings have no universal coverage semantics. Require a full journal
    pattern, reject contradictory registered ISSNs, and leave unknowns alone.
    No network requests, history, or per-article allowlist are involved.
    """
    if not isinstance(doi, str):
        return None
    values = getattr(metadata, "issn", ()) or ()
    observed = (
        {value for item in values if (value := _issn(item)) is not None}
        if isinstance(values, (tuple, list))
        else set()
    )
    for journal in CNKI_INDEXED_JOURNALS:
        if any(
            re.fullmatch(pattern, doi.casefold()) for pattern in journal.doi_patterns
        ):
            if observed and not observed.intersection(journal.issns):
                continue
            return journal
    return None
