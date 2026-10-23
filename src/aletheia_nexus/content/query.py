"""Small, explicit literal query semantics for scientific text."""

from __future__ import annotations

import re
import unicodedata


def normalize_search_text(text: str) -> str:
    """Normalize only the search view; canonical evidence is never rewritten."""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = re.sub(r"(?<=[a-z])-\s*\n\s*(?=[a-z])", "", value)
    value = " ".join(value.split())
    value = re.sub(r"(?<=\d)\s+%", "%", value)
    value = re.sub(r"[−–—⎯]", "-", value)
    value = re.sub(r"(?<=[+-])\s+(?=\d)", "", value)
    value = re.sub(r"(?<=\d)[∙⋅](?=\d)", ".", value)
    # PDF extractors often insert spaces between individual Chinese glyphs.
    return re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", value)


def query_terms(query: str, *, exact: bool = False) -> tuple[str, ...]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if exact:
        return (normalize_search_text(query),)
    if query.count('"') % 2:
        raise ValueError("unclosed quoted phrase in query")
    terms = [
        normalize_search_text(a or b)
        for a, b in re.findall(r'"([^"]+)"|([^\s"]+)', query)
    ]
    if not terms:
        raise ValueError("query must contain text")
    return tuple(dict.fromkeys(terms))


def match_score(
    text: str, terms: tuple[str, ...], *, mode: str = "and"
) -> float | None:
    if mode not in {"and", "or"}:
        raise ValueError("query mode must be and or or")
    normalized = normalize_search_text(text)
    matches = sum(_contains_term(normalized, term) for term in terms)
    if not matches or (mode == "and" and matches != len(terms)):
        return None
    phrase_bonus = 2 if " ".join(terms) in normalized else 0
    return round(
        phrase_bonus + matches / len(terms) + matches / max(len(normalized), 1), 6
    )


def _contains_term(text: str, term: str) -> bool:
    """Match whole numeric magnitudes; an explicitly supplied sign must match."""
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?%?", term):
        return term in text
    for match in re.finditer(r"(?<![\d.])" + re.escape(term) + r"(?![\d.])", text):
        before = text[: match.start()]
        if before.endswith(("-", "+")) and term.startswith(("-", "+")):
            continue
        # Do not match a mantissa inside a larger scientific-notation value.
        if re.match(r"e[+-]?\d", text[match.end() :]):
            continue
        if re.search(r"\de[+-]?$", before):
            continue
        return True
    return False
