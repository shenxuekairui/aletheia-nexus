"""Caption recognition and duplicate evidence handling, shared by layout stages."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_CAPTION = re.compile(
    r"^(?P<kind>fig(?:ure)?|scheme|table|图式|图|表)\.?\s*"
    r"(?P<label>(?:[A-Z]?\d+(?:[A-Za-z](?=$|\s|[,;:.|\-]))?"
    r"|[IVXLCDM]+(?=$|\s|[,;:.|\-])))",
    re.IGNORECASE,
)


_GLUED_TABLE_CAPTION = re.compile(
    r"(?<=[a-z])(?P<kind>table)\s*(?P<label>\d+(?:[A-Za-z])?)(?=\s|$)",
    re.IGNORECASE,
)


_UNNUMBERED_TABLE_CAPTION = re.compile(
    r"^(?P<kind>table|таблица|表)(?P<label>)[.。:]\s+(?=\S)", re.IGNORECASE
)


_CAPTION_MENTION = re.compile(
    r"^(?:比较了|显示了|表明了|列出了|给出了)|"
    r"^(?:clearly\s+)?(?:show(?:s|ed)?|present(?:s|ed)?|illustrat(?:e|es|ed)|"
    r"summari[sz](?:e|es|ed)|list(?:s|ed)?|represent(?:s|ed)?|provide(?:s|d)|"
    r"depict(?:s|ed)?|demonstrat(?:e|es|ed)|compare(?:s|d)|report(?:s|ed)?|"
    r"give(?:s)?|contain(?:s|ed)?|display(?:s|ed)?|indicat(?:e|es|ed)|"
    r"plot(?:s|ted)?|highlight(?:s|ed)?|reveal(?:s|ed)?|correspond(?:s|ed)?|"
    r"regard(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)

_CHINESE_PROSE_REFERENCE = re.compile(r"^为.+?[.。]\s*(?:其中|此外|由此)[,，]")


_CAPTION_PANEL_CITATION = re.compile(r"^\([A-Za-z0-9]+\)\s*\[\d")


_CAPTION_PANEL = re.compile(r"^\([A-Za-z0-9]+\)\s*")


_CAPTION_SUFFIX_MENTION = re.compile(r"^on\b", re.IGNORECASE)


_CAPTION_JOINED_SUFFIX_MENTION = re.compile(r"^[A-Za-z]on\b", re.IGNORECASE)


_CAPTION_CROSS_REFERENCE = re.compile(
    r"^(?:\)|and\b|(?:figure\s+)?supplements?\s+\d+(?:[a-z]|\s*[–—-]\s*\d+)?"
    r"(?:\s*[),]|\s*(?:and|for|in|into|provide|see)\b|\s*$)|"
    r"(?:we|this|these|our)\b)",
    re.IGNORECASE,
)


_CAPTION_PROSE_REFERENCE = re.compile(
    r"\b(?:is shown as|shown in|see\s+(?:the\s+)?figure|required\s+\d|"
    r"provide(?:s|d)?\s+(?:a\s+)?rigorous\s+validation)\b",
    re.IGNORECASE,
)


_CAPTION_SENTENCE = re.compile(
    r"^(?:the\b.*?\b(?:is|are|was|were|has|have)\b|"
    r"(?:\S+\s+){0,3}(?:is|are|was|were)\b)",
    re.IGNORECASE,
)


_CAPTION_CONTAMINATION = re.compile(
    r"\b(?:be concluded|however|in addition|it\s*can)\b", re.IGNORECASE
)


def _caption_match(text: str) -> re.Match[str] | None:
    """Return a caption prefix only when the remainder reads like a caption."""

    stripped = unicodedata.normalize("NFKC", text).strip()
    match = _CAPTION.match(stripped)
    if match is None:
        match = _UNNUMBERED_TABLE_CAPTION.match(stripped)
    if match is None:
        match = _GLUED_TABLE_CAPTION.search(stripped)
    if match is None:
        return None
    if (
        match.start() == 0
        and match.end() < len(stripped)
        and stripped[match.end()].islower()
    ):
        return None
    if match.start() > 0:
        before = stripped[: match.start()]
        after = stripped[match.end() :].lstrip()
        if (
            not after
            or not (after[0].isupper() or after[0].isdigit())
            or re.search(r"[.!?]\s", before)
        ):
            return None
    remainder = stripped[match.end() :].lstrip()
    if remainder.startswith((",", ";")):
        return None
    description = _caption_description(stripped, match)
    # Character spacing in a Chinese PDF must not turn a sentence such as
    # "给 出 了" into a new figure caption. Only recognition sees this view;
    # original text and source geometry remain unchanged.
    description = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", description)
    if (
        not description
        and "continued" not in stripped.casefold()
        and not stripped.isupper()
        and not stripped.endswith((".", ":"))
    ):
        return None
    if _CAPTION_MENTION.match(description) or _CHINESE_PROSE_REFERENCE.match(
        description
    ):
        return None
    if _CAPTION_PANEL_CITATION.match(description):
        return None
    panel = _CAPTION_PANEL.match(description)
    if panel is not None and _CAPTION_MENTION.match(description[panel.end() :]):
        return None
    if (
        match.group("label")
        and match.group("label")[-1].isalpha()
        and _CAPTION_SUFFIX_MENTION.match(description)
    ):
        return None
    if _CAPTION_JOINED_SUFFIX_MENTION.match(description):
        return None
    if _CAPTION_CROSS_REFERENCE.match(description):
        return None
    if _CAPTION_PROSE_REFERENCE.search(re.sub(r"\([^()]*\)", "", description)):
        return None
    return match


def _caption_description(text: str, match: re.Match[str]) -> str:
    stripped = text.strip()
    before = stripped[: match.start()].strip(".:|-–— ")
    after = stripped[match.end() :].lstrip(".:|-–— ")
    return " ".join(part for part in (before, after) if part)


def _caption_comparison_text(text: str, match: re.Match[str]) -> str:
    description = _caption_description(text, match)
    normalized = unicodedata.normalize("NFKD", description).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _caption_quality(text: str, match: re.Match[str]) -> tuple[int, int, int, int]:
    description = _caption_description(text, match)
    marker = match.group("kind")
    marker_count = len(re.findall(rf"\b{re.escape(marker)}", text, re.IGNORECASE))
    return (
        -int(_CAPTION_SENTENCE.search(description) is not None),
        -int(_CAPTION_CONTAMINATION.search(description) is not None),
        -marker_count,
        len(_caption_comparison_text(text, match)),
    )


def _deduplicate_caption_blocks(blocks: list[dict[str, object]]) -> None:
    """Keep one semantic caption for duplicated PDF text-layer evidence."""

    descriptive_keys: set[tuple[str, str]] = set()
    for block in blocks:
        if block["kind"] != "caption":
            continue
        text = str(block["text"])
        match = _caption_match(text)
        if match is None:
            continue
        description = _caption_description(text, match).casefold()
        if description and "continued" not in description:
            descriptive_keys.add(
                (match.group("kind").casefold(), match.group("label").casefold())
            )
    for block in blocks:
        if block["kind"] != "caption":
            continue
        text = str(block["text"])
        match = _caption_match(text)
        if match is None:
            continue
        key = (match.group("kind").casefold(), match.group("label").casefold())
        if key in descriptive_keys and not _caption_description(text, match):
            block["kind"] = "paragraph"

    kept: dict[tuple[str, str], list[dict[str, object]]] = {}
    for block in blocks:
        if block["kind"] != "caption":
            continue
        text = str(block["text"])
        match = _caption_match(text)
        if match is None:
            continue
        key = (match.group("kind").casefold(), match.group("label").casefold())
        description = _caption_description(text, match).casefold()
        if "continued" in description or "supplement" in description:
            kept.setdefault(key, []).append(block)
            continue
        comparison = _caption_comparison_text(text, match)
        duplicate: dict[str, object] | None = None
        for candidate in kept.get(key, []):
            candidate_text = str(candidate["text"])
            candidate_match = _caption_match(candidate_text)
            if candidate_match is None:
                continue
            candidate_description = _caption_description(
                candidate_text, candidate_match
            ).casefold()
            if "continued" in candidate_description or "supplement" in (
                candidate_description
            ):
                continue
            page_distance = abs(int(block["page"]) - int(candidate["page"]))
            candidate_comparison = _caption_comparison_text(
                candidate_text, candidate_match
            )
            minimum_length = min(len(comparison), len(candidate_comparison))
            similar = (
                minimum_length >= 12
                and (
                    comparison in candidate_comparison
                    or candidate_comparison in comparison
                )
            ) or (
                minimum_length >= 30
                and SequenceMatcher(
                    None, comparison, candidate_comparison, autojunk=False
                ).ratio()
                >= 0.72
            )
            if page_distance == 0 or (page_distance == 1 and similar):
                duplicate = candidate
                break
        if duplicate is None:
            kept.setdefault(key, []).append(block)
            continue
        duplicate_text = str(duplicate["text"])
        duplicate_match = _caption_match(duplicate_text)
        if duplicate_match is not None and _caption_quality(
            text, match
        ) > _caption_quality(duplicate_text, duplicate_match):
            duplicate["kind"] = "paragraph"
            kept[key].remove(duplicate)
            kept[key].append(block)
        else:
            block["kind"] = "paragraph"
