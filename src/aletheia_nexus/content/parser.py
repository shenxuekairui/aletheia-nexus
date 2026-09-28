"""Composable scientific-document parsing pipeline."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from pypdf import PdfReader

from aletheia_nexus.content.backends import ExtractionBackend, NativePdfBackend
from aletheia_nexus.content.diagnostics import safe_exception_detail
from aletheia_nexus.content.gate import ParserInput
from aletheia_nexus.content.geometry import PageGeometry
from aletheia_nexus.content.models import (
    LayoutLine,
    PageLayout,
    PipelineContext,
    validate_page_layout,
)
from aletheia_nexus.content.pipeline import ParserPipeline
from aletheia_nexus.content.schema import (
    PARSED_DOCUMENT_SCHEMA,
    compute_parsed_artifact_id,
)
from aletheia_nexus.core.identifiers.doi import extract_dois

PARSER_NAME = "structured-pdf-pipeline"
PARSER_VERSION = "2.5.0"

_HEADING_NUMBER = re.compile(
    r"^(?:(?P<numbered>[1-9]\d*(?:\.\d+){1,4})[.)]?"
    r"|(?P<integer>[1-9]\d*)[.)]|(?P<bare>[1-9]))"
    r"\s+(?=[^\W\d_]{2})",
    re.UNICODE,
)
_HEADING_ROMAN = re.compile(r"^(?P<number>[IVXLCDM]+|[A-Z])[.)]\s+(?=\S)")
_REFERENCE = re.compile(
    r"^(?:\[(?P<bracket>\d{1,3})\]\s+|\((?P<paren>\d{1,3})\)\s*|"
    r"(?P<plain>\d{1,3})[.)]?\s+)"
)
_BRACKET_REFERENCE_ENTRY = re.compile(r"\[(?P<label>\d{1,3})\]\s+")
_PLAIN_REFERENCE_ENTRY = re.compile(
    r"(?<!\S)(?P<label>\d{1,3})[.)]?\s+"
    r"(?=(?:[A-Z][\w'’\-]+(?:,\s*|\s+)[A-Z]{1,4}\.?"
    r"|(?:[A-Z]\.\s*){1,4}[A-Z][\w'’\-]+))"
)
_PAREN_REFERENCE_ENTRY = re.compile(r"\((?P<label>\d{1,3})\)\s*")
_REFERENCE_YEAR = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b", re.IGNORECASE)
_AUTHOR_REFERENCE = re.compile(
    r"^\d+[.)]?\s+(?:"
    r"(?:[^,\s]+\s+)*[^,\s]+,\s+[A-Z](?:[.\s]|$)"
    r"|(?:[^,\s]+\s+)*[A-Z]{1,4},\s+[A-Z][a-z]"
    r"|[^\s]+\s+[A-Z]{1,4}\.\s+[A-Z]"
    r")"
)
_YEAR_AUTHOR_REFERENCE = re.compile(
    r"^(?:\d+[.)]?|\(\d+\))\s*[A-Z][\w'’\-]+\s+[A-Z]{1,4}\.?\s+\d{4}\b"
)
_UNNUMBERED_AUTHOR_START = re.compile(r"^[A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]*){1,4}\s*,")
_AFFILIATION_HINT = re.compile(
    r"\b(?:centre|center|cnrs|collaboration|department|faculty|institute|"
    r"laboratory|laboratoire|school|universit(?:y|é)|university)\b",
    re.IGNORECASE,
)
_AFFILIATION_COUNTRY = re.compile(r";\s*[A-Z][\w -]+[.;]?$", re.UNICODE)
_CITATION = re.compile(r"\[(\d+(?:\s*[-,]\s*\d+)*)\]")
_CAPTION = re.compile(
    r"^(?P<kind>fig(?:ure)?|table)\.?\s*"
    r"(?P<label>(?:[A-Z]?\d+(?:[A-Za-z](?=$|\s|[,;:.|\-]))?"
    r"|[IVXLCDM]+(?=$|\s|[,;:.|\-])))",
    re.IGNORECASE,
)
_GLUED_TABLE_CAPTION = re.compile(
    r"(?<=[a-z])(?P<kind>table)\s*(?P<label>\d+(?:[A-Za-z])?)(?=\s|$)",
    re.IGNORECASE,
)
_CAPTION_MENTION = re.compile(
    r"^(?:clearly\s+)?(?:show(?:s|ed)?|present(?:s|ed)?|illustrat(?:e|es|ed)|"
    r"summari[sz](?:e|es|ed)|list(?:s|ed)?|represent(?:s|ed)?|provide(?:s|d)|"
    r"depict(?:s|ed)?|demonstrat(?:e|es|ed)|compare(?:s|d)|report(?:s|ed)?|"
    r"give(?:s)?|contain(?:s|ed)?|display(?:s|ed)?|indicat(?:e|es|ed)|"
    r"plot(?:s|ted)?|highlight(?:s|ed)?|reveal(?:s|ed)?|correspond(?:s|ed)?|"
    r"regard(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)
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
_EQUATION = re.compile(r"(?:[=≈≤≥±∑∫√→←]|\b(?:sin|cos|log|exp)\s*\(|^[A-Za-z]\s*=)")
_MATH_GLYPH = re.compile(r"[αβγδεϵζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ]", re.UNICODE)
_PAGE_LABEL = re.compile(
    r"^(?:[-–—]\s*)?\d+(?:\s*of\s*\d+)*(?:\s*[-–—])?$", re.IGNORECASE
)
_SEMANTIC_SECTIONS = {
    "abstract": "abstract",
    "introduction": "introduction",
    "background": "background",
    "methods": "methods",
    "materials and methods": "methods",
    "methodology": "methods",
    "experimental methods": "methods",
    "experimental method": "methods",
    "method": "methods",
    "results": "results",
    "discussion": "discussion",
    "results and discussion": "results-discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "references": "references",
    "bibliography": "references",
    "acknowledgments": "acknowledgments",
    "acknowledgements": "acknowledgments",
}
_POST_REFERENCE_HEADINGS = (
    "additional information",
    "affiliation",
    "appendix",
    "author contribution",
    "author information",
    "author response",
    "authors' contribution",
    "competing interest",
    "conflict of interest",
    "data availability",
    "decision letter",
    "ethics statement",
    "publisher's note",
    "supplementary information",
)


@dataclass(frozen=True)
class ParserConfig:
    """Versioned layout, quality, and resource-budget controls."""

    heading_font_ratio: float = 1.35
    min_text_characters: int = 20
    column_split_ratio: float = 0.5
    merge_paragraph_lines: bool = True
    max_pages: int = 2000
    max_blocks: int = 200_000
    max_text_characters: int = 20_000_000

    def __post_init__(self) -> None:
        if isinstance(self.heading_font_ratio, bool) or not isinstance(
            self.heading_font_ratio, (int, float)
        ):
            raise ValueError("heading_font_ratio must be a number")
        if not math.isfinite(self.heading_font_ratio):
            raise ValueError("heading_font_ratio must be finite")
        if self.heading_font_ratio <= 1:
            raise ValueError("heading_font_ratio must be greater than 1")
        if isinstance(self.min_text_characters, bool) or not isinstance(
            self.min_text_characters, int
        ):
            raise ValueError("min_text_characters must be an integer")
        if self.min_text_characters < 0:
            raise ValueError("min_text_characters cannot be negative")
        if isinstance(self.column_split_ratio, bool) or not isinstance(
            self.column_split_ratio, (int, float)
        ):
            raise ValueError("column_split_ratio must be a number")
        if not math.isfinite(self.column_split_ratio):
            raise ValueError("column_split_ratio must be finite")
        if not 0.25 <= self.column_split_ratio <= 0.75:
            raise ValueError("column_split_ratio must be between 0.25 and 0.75")
        if not isinstance(self.merge_paragraph_lines, bool):
            raise ValueError("merge_paragraph_lines must be a boolean")
        for name in ("max_pages", "max_blocks", "max_text_characters"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    def as_dict(self) -> dict[str, object]:
        return {
            "column_split_ratio": self.column_split_ratio,
            "heading_font_ratio": self.heading_font_ratio,
            "max_blocks": self.max_blocks,
            "max_pages": self.max_pages,
            "max_text_characters": self.max_text_characters,
            "merge_paragraph_lines": self.merge_paragraph_lines,
            "min_text_characters": self.min_text_characters,
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _order_lines(
    lines: tuple[LayoutLine, ...], width: float, config: ParserConfig
) -> list[LayoutLine]:
    """Use spanning lines as bands, then read left column before right column."""

    if len(lines) < 3 or width <= 0:
        return sorted(lines, key=lambda item: (-item.y0, item.x0))
    spanning = sorted(
        (line for line in lines if line.x1 - line.x0 >= width * 0.58),
        key=lambda item: (-item.y0, item.x0),
    )
    spanning_ids = {id(line) for line in spanning}
    narrow = [line for line in lines if id(line) not in spanning_ids]

    def ordered_region(region: list[LayoutLine]) -> list[LayoutLine]:
        if not region:
            return []
        split = width * config.column_split_ratio
        left = [line for line in region if (line.x0 + line.x1) / 2 < split]
        right = [line for line in region if (line.x0 + line.x1) / 2 >= split]
        left_substantial = sum(len(line.text) > 12 for line in left)
        right_substantial = sum(len(line.text) > 12 for line in right)
        if (
            len(left) >= 2
            and len(right) >= 2
            and left_substantial >= 2
            and right_substantial >= 2
        ):
            return sorted(left, key=lambda item: (-item.y0, item.x0)) + sorted(
                right, key=lambda item: (-item.y0, item.x0)
            )
        return sorted(region, key=lambda item: (-item.y0, item.x0))

    result: list[LayoutLine] = []
    upper = float("inf")
    for boundary in spanning:
        region = [line for line in narrow if boundary.y0 <= line.y0 < upper]
        result.extend(ordered_region(region))
        result.append(boundary)
        upper = boundary.y0
    result.extend(ordered_region([line for line in narrow if line.y0 < upper]))
    return result


def _heading_level(text: str) -> int:
    match = _HEADING_NUMBER.match(text)
    if match:
        number = (
            match.group("numbered") or match.group("integer") or match.group("bare")
        )
        return min(number.count(".") + 1, 5)
    if _HEADING_ROMAN.match(text):
        return 2
    normalized = _strip_heading_number(text)
    return 1 if normalized in _SEMANTIC_SECTIONS else 2


def _strip_heading_number(text: str) -> str:
    stripped = re.sub(r"^[■◆●▪*]+\s*", "", text.strip())
    return (
        re.sub(
            r"^(?:[1-9]\d*(?:\.\d+){1,4}[.)]?|[1-9]\d*[.)]|[1-9]"
            r"|(?:[IVXLCDM]+|[A-Z])[.)])\s+",
            "",
            stripped,
        )
        .strip()
        .casefold()
    )


def _semantic_section(text: str) -> str | None:
    return _SEMANTIC_SECTIONS.get(_strip_heading_number(text))


def _kind(line: LayoutLine, median_font: float, heading_font_ratio: float) -> str:
    text = line.text.strip()
    if _caption_match(text):
        return "caption"
    if _is_author_reference(text):
        return "reference"
    short = len(text) <= 120 and len(text.split()) <= 14
    known_heading = _semantic_section(text) is not None
    numbered_heading = _HEADING_NUMBER.match(text) is not None
    roman_heading = _HEADING_ROMAN.match(text) is not None
    math_glyph_count = len(_MATH_GLYPH.findall(text))
    if len(text) <= 160 and math_glyph_count >= 2:
        return "equation"
    equation_like = bool(_EQUATION.search(text))
    if (
        not known_heading
        and not numbered_heading
        and not roman_heading
        and len(text) <= 160
        and equation_like
    ):
        return "equation"
    font_heading = line.font_size >= median_font * heading_font_ratio or (
        line.bold and line.font_size >= median_font * 1.02
    )
    heading_letters = [character for character in text if character.isalpha()]
    uppercase_heading = bool(heading_letters) and (
        sum(character.isupper() for character in heading_letters) / len(heading_letters)
        >= 0.8
    )
    numbered_heading_evidence = (
        numbered_heading or roman_heading
    ) and uppercase_heading
    if (
        short
        and _looks_like_heading_text(text)
        and (font_heading or known_heading or numbered_heading_evidence)
    ):
        return "heading"
    if len(text) <= 160 and equation_like:
        return "equation"
    return "paragraph"


def _is_author_reference(text: str) -> bool:
    author_evidence = (
        _AUTHOR_REFERENCE.match(text) is not None
        or _YEAR_AUTHOR_REFERENCE.match(text) is not None
    )
    return (
        author_evidence
        and not _AFFILIATION_HINT.search(text[:80])
        and not _AFFILIATION_COUNTRY.search(text)
    )


def _is_unnumbered_reference_start(text: str) -> bool:
    return _UNNUMBERED_AUTHOR_START.match(text.strip()) is not None


def _looks_like_unnumbered_reference(text: str) -> bool:
    normalized = text.casefold()
    return _is_unnumbered_reference_start(text) or (
        _REFERENCE_YEAR.search(text) is not None
        and ("doi" in normalized or "pmid" in normalized)
    )


def _caption_match(text: str) -> re.Match[str] | None:
    """Return a caption prefix only when the remainder reads like a caption."""

    stripped = text.strip()
    match = _CAPTION.match(stripped)
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
    if (
        not description
        and "continued" not in stripped.casefold()
        and not stripped.isupper()
        and not stripped.endswith((".", ":"))
    ):
        return None
    if _CAPTION_MENTION.match(description):
        return None
    if _CAPTION_PANEL_CITATION.match(description):
        return None
    panel = _CAPTION_PANEL.match(description)
    if panel is not None and _CAPTION_MENTION.match(description[panel.end() :]):
        return None
    if match.group("label")[-1].isalpha() and _CAPTION_SUFFIX_MENTION.match(
        description
    ):
        return None
    if _CAPTION_JOINED_SUFFIX_MENTION.match(description):
        return None
    if _CAPTION_CROSS_REFERENCE.match(description):
        return None
    if _CAPTION_PROSE_REFERENCE.search(description):
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


def _looks_like_heading_text(text: str) -> bool:
    letters = sum(character.isalpha() for character in text)
    digits = sum(character.isdigit() for character in text)
    if letters < 3 or letters / max(len(text), 1) < 0.4:
        return False
    if digits > max(1, letters // 4):
        return False
    if text.endswith((".", ";", ",")) or text.count(",") >= 2:
        return False
    lowered = text.casefold()
    return not any(marker in lowered for marker in ("http://", "https://", "@"))


def _furniture_key(text: str) -> str:
    normalized = " ".join(text.casefold().split())
    return re.sub(r"\d+", "#", normalized)


def _page_furniture_keys(layouts: dict[int, PageLayout]) -> set[str]:
    pages_by_key: dict[str, set[int]] = {}
    for page_number, layout in layouts.items():
        if layout.height <= 0:
            continue
        for line in layout.lines:
            near_margin = (
                line.y0 / layout.height < 0.08 or line.y1 / layout.height > 0.92
            )
            if not near_margin or len(line.text) > 160:
                continue
            pages_by_key.setdefault(_furniture_key(line.text), set()).add(page_number)
    return {key for key, pages in pages_by_key.items() if len(pages) >= 2}


def _is_page_furniture(
    line: LayoutLine, layout: PageLayout, repeated_keys: set[str]
) -> bool:
    if layout.height <= 0:
        return False
    if line.y0 / layout.height < 0.1 or line.y1 / layout.height > 0.9:
        if _furniture_key(line.text) in repeated_keys or _PAGE_LABEL.fullmatch(
            " ".join(line.text.split())
        ):
            return True
    return False


def _bbox(line: LayoutLine, width: float, height: float) -> list[float] | None:
    if width <= 0 or height <= 0:
        return None
    return [
        round(max(0.0, min(1.0, line.x0 / width)), 6),
        round(max(0.0, min(1.0, line.y0 / height)), 6),
        round(max(0.0, min(1.0, line.x1 / width)), 6),
        round(max(0.0, min(1.0, line.y1 / height)), 6),
    ]


def _line_column(line: LayoutLine, width: float, split_ratio: float) -> int:
    if line.x1 - line.x0 >= width * 0.58:
        return -1
    return int((line.x0 + line.x1) / 2 >= width * split_ratio)


def _can_merge(
    previous: LayoutLine,
    current: LayoutLine,
    *,
    width: float,
    split_ratio: float,
) -> bool:
    if len(previous.text.split()) <= 2 and len(current.text.split()) <= 2:
        return False
    if _line_column(previous, width, split_ratio) != _line_column(
        current, width, split_ratio
    ):
        return False
    vertical_gap = previous.y0 - current.y1
    if vertical_gap < -max(previous.font_size, current.font_size) * 0.25:
        return False
    if vertical_gap > max(previous.font_size, current.font_size) * 1.8:
        return False
    return abs(previous.x0 - current.x0) <= max(18.0, width * 0.06)


def _can_merge_heading(
    previous: LayoutLine, current: LayoutLine, *, width: float
) -> bool:
    if _semantic_section(previous.text) or _semantic_section(current.text):
        return False
    if _HEADING_NUMBER.match(previous.text) or _HEADING_NUMBER.match(current.text):
        return False
    if _HEADING_ROMAN.match(previous.text) or _HEADING_ROMAN.match(current.text):
        return False
    if previous.bold != current.bold:
        return False
    size_ratio = max(previous.font_size, current.font_size) / min(
        previous.font_size, current.font_size
    )
    if size_ratio > 1.12:
        return False
    vertical_gap = previous.y0 - current.y1
    if not -previous.font_size * 0.2 <= vertical_gap <= previous.font_size * 1.1:
        return False
    return abs(previous.x0 - current.x0) <= max(24.0, width * 0.08)


def _union_bbox(first: list[float], second: list[float]) -> list[float]:
    return [
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    ]


class _NativeExtractionStage:
    name = "layout-extraction-and-block-assembly"

    def run(self, context: PipelineContext) -> None:
        config = context.config
        backend = context.backend
        reader = context.reader
        text_characters = 0
        page_total = len(reader.pages)
        if page_total > config.max_pages:
            context.warnings.append(
                {
                    "code": "PAGE_LIMIT_REACHED",
                    "detail": f"parsed {config.max_pages} of {page_total} pages",
                }
            )
            context.stopped_early = True

        for page_index, page in enumerate(reader.pages[: config.max_pages], start=1):
            try:
                layout = backend.extract_page(page, page_index)
                validate_page_layout(layout, expected_page=page_index)
                expected = PageGeometry.from_page(page)
                if not (
                    math.isclose(layout.width, expected.width, abs_tol=0.01)
                    and math.isclose(layout.height, expected.height, abs_tol=0.01)
                    and layout.rotation == expected.rotation
                ):
                    raise ValueError(
                        "backend page dimensions/rotation differ from canonical geometry"
                    )
                if layout.media_box is not None and any(
                    not math.isclose(actual, wanted, abs_tol=0.01)
                    for actual, wanted in zip(layout.media_box, expected.media_box)
                ):
                    raise ValueError("backend MediaBox differs from source page")
                if layout.crop_box is not None and any(
                    not math.isclose(actual, wanted, abs_tol=0.01)
                    for actual, wanted in zip(layout.crop_box, expected.crop_box)
                ):
                    raise ValueError("backend CropBox differs from source page")
                layout = replace(
                    layout,
                    media_box=expected.media_box,
                    crop_box=expected.crop_box,
                    rotation=expected.rotation,
                )
            except Exception as exc:
                context.errors.append(
                    {
                        "code": "PAGE_EXTRACTION_FAILED",
                        "detail": (
                            f"page {page_index}: {type(exc).__name__}: "
                            f"{safe_exception_detail(exc)}"
                        ),
                        "page": page_index,
                        "stage": "layout-extraction",
                        "backend": f"{backend.name}@{backend.version}",
                        "degraded": False,
                    }
                )
                continue
            context.layouts[page_index] = layout
            context.warnings.extend(layout.warnings)
            if not layout.lines:
                context.warnings.append(
                    {
                        "code": "PAGE_WITHOUT_TEXT",
                        "detail": (f"page {page_index} has no extractable native text"),
                    }
                )
        repeated_furniture = _page_furniture_keys(context.layouts)
        for page_index, layout in sorted(context.layouts.items()):
            if not layout.lines:
                continue
            median_font = statistics.median(line.font_size for line in layout.lines)
            previous_line: LayoutLine | None = None
            previous_kind: str | None = None
            for line in _order_lines(layout.lines, layout.width, config):
                line_engines = line.source_engines or (
                    f"{backend.name}@{backend.version}",
                )
                if _is_page_furniture(line, layout, repeated_furniture):
                    context.suppressed_page_furniture += 1
                    previous_line = None
                    previous_kind = None
                    continue
                kind = _kind(line, median_font, config.heading_font_ratio)
                will_merge_paragraph = (
                    config.merge_paragraph_lines
                    and kind == previous_kind == "paragraph"
                    and previous_line is not None
                    and _can_merge(
                        previous_line,
                        line,
                        width=layout.width,
                        split_ratio=config.column_split_ratio,
                    )
                )
                will_merge_heading = (
                    kind == previous_kind == "heading"
                    and previous_line is not None
                    and _can_merge_heading(
                        previous_line,
                        line,
                        width=layout.width,
                    )
                )
                will_merge = will_merge_paragraph or will_merge_heading
                projected_characters = (
                    text_characters + len(line.text) + int(will_merge)
                )
                if projected_characters > config.max_text_characters:
                    context.warnings.append(
                        {
                            "code": "TEXT_LIMIT_REACHED",
                            "detail": (
                                "parser stopped before exceeding "
                                f"{config.max_text_characters} text characters"
                            ),
                        }
                    )
                    context.stopped_early = True
                    return

                if will_merge:
                    block = context.blocks[-1]
                    anchor = context.anchors[-1]
                    block["text"] = f"{block['text']} {line.text}"
                    block["line_count"] = int(block["line_count"]) + 1
                    block["uncertain"] = bool(block["uncertain"] or line.uncertain)
                    block["extraction_confidence"] = min(
                        float(block["extraction_confidence"]),
                        line.extraction_confidence,
                    )
                    block["source_engines"] = list(
                        dict.fromkeys([*block["source_engines"], *line_engines])
                    )
                    agreements = [
                        value
                        for value in (
                            block.get("engine_agreement"),
                            line.engine_agreement,
                        )
                        if value is not None
                    ]
                    block["engine_agreement"] = (
                        min(float(value) for value in agreements)
                        if agreements
                        else None
                    )
                    if block["extraction_method"] != line.extraction_method:
                        block["extraction_method"] = "mixed-positioned-text"
                    if block["content_region"] != line.content_region:
                        block["content_region"] = "mixed"
                    anchor["text_evidence"] = block["text"]
                    anchor["span"] = {"start": 0, "end": len(block["text"])}
                    next_bbox = _bbox(line, layout.width, layout.height)
                    if anchor["bbox"] is not None and next_bbox is not None:
                        anchor["bbox"] = _union_bbox(anchor["bbox"], next_bbox)
                    else:
                        anchor["bbox"] = None
                        anchor["bbox_precision"] = None
                        anchor["anchored"] = False
                    text_characters = projected_characters
                    previous_line = line
                    continue

                if len(context.blocks) >= config.max_blocks:
                    context.warnings.append(
                        {
                            "code": "BLOCK_LIMIT_REACHED",
                            "detail": (
                                "parser stopped before exceeding "
                                f"{config.max_blocks} blocks"
                            ),
                        }
                    )
                    context.stopped_early = True
                    return

                block_id = f"b{len(context.blocks) + 1:06d}"
                anchor_id = f"a{len(context.anchors) + 1:06d}"
                bbox = _bbox(line, layout.width, layout.height)
                context.blocks.append(
                    {
                        "id": block_id,
                        "kind": kind,
                        "text": line.text,
                        "object_ref": None,
                        "order": len(context.blocks) + 1,
                        "page": page_index,
                        "anchor_id": anchor_id,
                        "extraction_method": line.extraction_method,
                        "extraction_confidence": line.extraction_confidence,
                        "source_engines": list(line_engines),
                        "engine_agreement": line.engine_agreement,
                        "content_region": line.content_region,
                        "uncertain": line.uncertain or kind == "equation",
                        "line_count": 1,
                    }
                )
                context.anchors.append(
                    {
                        "id": anchor_id,
                        "block_id": block_id,
                        "page": page_index,
                        "bbox": bbox,
                        "coordinate_system": layout.coordinate_system,
                        "bbox_precision": "estimated" if bbox is not None else None,
                        "text_evidence": line.text,
                        "span": {"start": 0, "end": len(line.text)},
                        "anchored": bbox is not None,
                    }
                )
                text_characters = projected_characters
                previous_line = line
                previous_kind = kind


def _sections(blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    stack: list[tuple[int, str]] = []
    current: dict[str, object] | None = None
    for block in blocks:
        if block["kind"] == "heading":
            level = _heading_level(str(block["text"]))
            while stack and stack[-1][0] >= level:
                stack.pop()
            identifier = f"s{len(sections) + 1:05d}"
            semantic_type = _semantic_section(str(block["text"]))
            current = {
                "id": identifier,
                "parent_id": stack[-1][1] if stack else None,
                "heading": block["text"],
                "level": level,
                "order": len(sections) + 1,
                "heading_block_id": block["id"],
                "block_ids": [block["id"]],
                "semantic_type": semantic_type,
                "semantic_type_confidence": 1.0 if semantic_type else 0.0,
                "hierarchy_inferred": not bool(
                    _HEADING_NUMBER.match(str(block["text"]))
                    or _HEADING_ROMAN.match(str(block["text"]))
                ),
            }
            sections.append(current)
            stack.append((level, identifier))
        elif current is not None:
            current["block_ids"].append(block["id"])
    return sections


def _citation_labels(value: str) -> list[str]:
    labels: list[str] = []
    for citation in _CITATION.findall(value):
        for part in re.split(r"\s*,\s*", citation):
            if "-" in part:
                start, end = (int(item.strip()) for item in part.split("-", 1))
                if 0 <= end - start <= 25:
                    labels.extend(str(item) for item in range(start, end + 1))
            else:
                labels.append(part.strip())
    return labels


def _mark_bibliography_blocks(blocks: list[dict[str, object]]) -> None:
    """Use an explicit References heading to disambiguate numbered entries."""

    reference_heading_indices = [
        index
        for index, block in enumerate(blocks)
        if block["kind"] == "heading"
        and _semantic_section(str(block["text"])) == "references"
    ]
    if not reference_heading_indices:
        _mark_inferred_bracketed_bibliography(blocks)
        return

    first_heading_index = reference_heading_indices[0]
    first_heading_page = int(blocks[first_heading_index]["page"])
    later_reference_page = (
        min(int(blocks[index]["page"]) for index in reference_heading_indices[1:])
        if len(reference_heading_indices) > 1
        else None
    )
    in_bibliography = False
    unnumbered_bibliography = False
    for index, block in enumerate(blocks):
        page = int(block["page"])
        semantic_type = (
            _semantic_section(str(block["text"]))
            if block["kind"] == "heading"
            else None
        )
        if index == first_heading_index:
            in_bibliography = True
            continue
        if index < first_heading_index:
            match = _REFERENCE.match(str(block["text"]))
            if (
                page == first_heading_page
                and match is not None
                and match.group("bracket") is not None
            ):
                block["kind"] = "reference"
            elif page != first_heading_page and block["kind"] == "reference":
                block["kind"] = "paragraph"
            continue
        if later_reference_page is not None and page >= later_reference_page:
            in_bibliography = False
        if not in_bibliography:
            if block["kind"] == "reference":
                block["kind"] = "paragraph"
            continue
        text = str(block["text"])
        match = _REFERENCE.match(text)
        contextual_reference = (
            _BRACKET_REFERENCE_ENTRY.search(text) is not None
            or _PAREN_REFERENCE_ENTRY.search(text) is not None
            or (match is not None and _is_author_reference(text))
            or _looks_like_unnumbered_reference(text)
        )
        if contextual_reference:
            block["kind"] = "reference"
            if _looks_like_unnumbered_reference(text) and match is None:
                unnumbered_bibliography = True
            continue
        normalized = _strip_heading_number(text)
        if semantic_type is not None or (
            len(normalized) <= 80 and normalized.startswith(_POST_REFERENCE_HEADINGS)
        ):
            in_bibliography = False
            continue
        if block["kind"] == "heading":
            block["kind"] = "paragraph"
        if in_bibliography and unnumbered_bibliography:
            block["kind"] = "reference"
        elif block["kind"] == "reference":
            block["kind"] = "paragraph"


def _mark_inferred_bracketed_bibliography(
    blocks: list[dict[str, object]],
) -> None:
    """Recognize an end-of-document bracketed bibliography without a heading."""

    if not blocks:
        return
    max_page = max(int(block["page"]) for block in blocks)
    minimum_page = max(1, math.ceil(max_page * 0.55))
    candidates: list[tuple[dict[str, object], int, int]] = []
    for block in blocks:
        match = _REFERENCE.match(str(block["text"]))
        if (
            match is not None
            and match.group("bracket") is not None
            and int(block["page"]) >= minimum_page
        ):
            candidates.append((block, int(block["page"]), int(match.group("bracket"))))
    start_index = next(
        (index for index, (_, _, label) in enumerate(candidates) if label <= 3), None
    )
    if start_index is None:
        return
    segment: list[tuple[dict[str, object], int, int]] = []
    previous_page: int | None = None
    for candidate in candidates[start_index:]:
        if previous_page is not None and candidate[1] > previous_page + 1:
            break
        segment.append(candidate)
        previous_page = candidate[1]
    if len(segment) < 3:
        return
    start_page = segment[0][1]
    end_page = segment[-1][1]
    for block in blocks:
        if (
            start_page <= int(block["page"]) <= end_page
            and _BRACKET_REFERENCE_ENTRY.search(str(block["text"])) is not None
        ):
            block["kind"] = "reference"


def _reference_segments(text: str) -> list[tuple[str, str]]:
    first = _REFERENCE.match(text)
    if first is None:
        candidates = [
            (match.start(), pattern)
            for pattern in (
                _BRACKET_REFERENCE_ENTRY,
                _PAREN_REFERENCE_ENTRY,
                _PLAIN_REFERENCE_ENTRY,
            )
            if (match := pattern.search(text)) is not None
        ]
        if not candidates:
            return []
        pattern = min(candidates, key=lambda item: item[0])[1]
    else:
        pattern = (
            _BRACKET_REFERENCE_ENTRY
            if first.group("bracket")
            else (
                _PAREN_REFERENCE_ENTRY
                if first.group("paren")
                else _PLAIN_REFERENCE_ENTRY
            )
        )
    matches = list(pattern.finditer(text))
    if not matches:
        if first is None:
            return []
        label = first.group("bracket") or first.group("paren") or first.group("plain")
        return [(label, text)]
    return [
        (
            match.group("label"),
            text[match.start() : matches[index + 1].start()].strip()
            if index + 1 < len(matches)
            else text[match.start() :].strip(),
        )
        for index, match in enumerate(matches)
    ]


def _references(blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    by_label: dict[str, dict[str, object]] = {}
    by_doi: dict[str, dict[str, object]] = {}
    resolved_block_ids: set[str] = set()
    current_unnumbered: dict[str, object] | None = None
    unnumbered_count = 0

    def add_unnumbered(
        block: dict[str, object], raw_text: str, doi: str | None
    ) -> dict[str, object]:
        nonlocal unnumbered_count
        if doi is not None and doi in by_doi:
            return by_doi[doi]
        unnumbered_count += 1
        label = f"author-year-{unnumbered_count:04d}"
        item = {
            "id": f"r{len(references) + 1:05d}",
            "label": label,
            "block_id": block["id"],
            "anchor_id": block["anchor_id"],
            "raw_text": raw_text,
            "doi": doi,
            "doi_candidates": [doi] if doi is not None else [],
            "cited_by_block_ids": [],
            "resolved": True,
            "ambiguous": False,
        }
        references.append(item)
        by_label[label] = item
        if doi is not None:
            by_doi[doi] = item
        return item

    for block in blocks:
        if block["kind"] != "reference":
            continue
        segments = _reference_segments(str(block["text"]))
        if not segments:
            text = str(block["text"])
            dois = extract_dois(text)
            if current_unnumbered is not None and dois:
                combined = f"{current_unnumbered['raw_text']} {text}"
                current_unnumbered["raw_text"] = combined
                current_unnumbered["doi"] = dois[0]
                current_unnumbered["doi_candidates"] = [dois[0]]
                by_doi.setdefault(dois[0], current_unnumbered)
                for doi in dois[1:]:
                    add_unnumbered(block, text, doi)
                current_unnumbered = None
            elif dois:
                for doi in dois:
                    add_unnumbered(block, text, doi)
                current_unnumbered = None
            elif _is_unnumbered_reference_start(text):
                current_unnumbered = add_unnumbered(block, text, None)
            elif current_unnumbered is not None:
                combined = f"{current_unnumbered['raw_text']} {block['text']}"
                current_unnumbered["raw_text"] = combined
            resolved_block_ids.add(str(block["id"]))
            continue
        current_unnumbered = None
        for label, raw_text in segments:
            existing = by_label.get(label)
            if existing is not None:
                if existing["raw_text"] != raw_text:
                    existing["ambiguous"] = True
                continue
            dois = extract_dois(raw_text)
            item = {
                "id": f"r{len(references) + 1:05d}",
                "label": label,
                "block_id": block["id"],
                "anchor_id": block["anchor_id"],
                "raw_text": raw_text,
                "doi": dois[0] if len(dois) == 1 else None,
                "doi_candidates": dois,
                "cited_by_block_ids": [],
                "resolved": True,
                "ambiguous": len(dois) > 1,
            }
            references.append(item)
            by_label[label] = item
        resolved_block_ids.add(str(block["id"]))

    unresolved: dict[str, dict[str, object]] = {}
    for block in blocks:
        if str(block["id"]) in resolved_block_ids:
            continue
        for label in _citation_labels(str(block["text"])):
            item = by_label.get(label) or unresolved.get(label)
            if item is None:
                item = {
                    "id": f"r{len(references) + 1:05d}",
                    "label": label,
                    "block_id": None,
                    "anchor_id": None,
                    "raw_text": None,
                    "doi": None,
                    "doi_candidates": [],
                    "cited_by_block_ids": [],
                    "resolved": False,
                    "ambiguous": False,
                }
                references.append(item)
                unresolved[label] = item
            if block["id"] not in item["cited_by_block_ids"]:
                item["cited_by_block_ids"].append(block["id"])
    return references


def _anchor_map(
    anchors: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {str(item["id"]): item for item in anchors}


def _table_cells(
    caption: dict[str, object],
    blocks: list[dict[str, object]],
    anchors: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], int, int]:
    candidates: list[tuple[dict[str, object], dict[str, object]]] = []
    caption_order = int(caption["order"])
    page = caption["page"]
    for block in blocks:
        if int(block["order"]) <= caption_order or block["page"] != page:
            continue
        if block["kind"] in {"heading", "caption", "reference"}:
            break
        anchor = anchors[str(block["anchor_id"])]
        if anchor["bbox"] is None:
            continue
        candidates.append((block, anchor))
        if len(candidates) >= 40:
            break

    rows: list[list[tuple[dict[str, object], dict[str, object]]]] = []
    for block, anchor in sorted(
        candidates,
        key=lambda pair: (
            -float(pair[1]["bbox"][1]),
            float(pair[1]["bbox"][0]),
        ),
    ):
        center_y = (float(anchor["bbox"][1]) + float(anchor["bbox"][3])) / 2
        row = next(
            (
                item
                for item in rows
                if abs(
                    (float(item[0][1]["bbox"][1]) + float(item[0][1]["bbox"][3])) / 2
                    - center_y
                )
                <= 0.0125
            ),
            None,
        )
        if row is None:
            rows.append([(block, anchor)])
        else:
            row.append((block, anchor))
    rows = [row for row in rows if len(row) >= 2]
    if len(rows) < 2:
        return [], 0, 0
    column_count = max(len(row) for row in rows)
    cells: list[dict[str, object]] = []
    for row_index, row in enumerate(rows, start=1):
        for column_index, (block, anchor) in enumerate(
            sorted(row, key=lambda pair: float(pair[1]["bbox"][0])), start=1
        ):
            cells.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "text": block["text"],
                    "block_id": block["id"],
                    "anchor_id": anchor["id"],
                    "bbox": anchor["bbox"],
                }
            )
    return cells, len(rows), column_count


def _meaningful_image(image: object) -> bool:
    bbox = getattr(image, "bbox", None)
    if bbox is None:
        return False
    width = max(0.0, float(bbox[2]) - float(bbox[0]))
    height = max(0.0, float(bbox[3]) - float(bbox[1]))
    return width >= 0.04 and height >= 0.03 and width * height >= 0.003


def _image_caption_distance(
    image: object, caption_bbox: list[float] | None
) -> float | None:
    image_bbox = getattr(image, "bbox", None)
    if image_bbox is None or caption_bbox is None:
        return None
    horizontal_overlap = max(
        0.0,
        min(float(image_bbox[2]), caption_bbox[2])
        - max(float(image_bbox[0]), caption_bbox[0]),
    )
    narrower_width = min(
        float(image_bbox[2]) - float(image_bbox[0]),
        caption_bbox[2] - caption_bbox[0],
    )
    if narrower_width <= 0 or horizontal_overlap / narrower_width < 0.15:
        return None
    if float(image_bbox[3]) < caption_bbox[1]:
        distance = caption_bbox[1] - float(image_bbox[3])
    elif caption_bbox[3] < float(image_bbox[1]):
        distance = float(image_bbox[1]) - caption_bbox[3]
    else:
        distance = 0.0
    return distance if distance <= 0.2 else None


def _objects(
    blocks: list[dict[str, object]],
    anchors: list[dict[str, object]],
    layouts: dict[int, PageLayout],
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    figures: list[dict[str, object]] = []
    tables: list[dict[str, object]] = []
    anchor_by_id = _anchor_map(anchors)
    associated_images: set[tuple[int, str]] = set()
    by_block = {str(item["id"]): item for item in blocks}

    for block in blocks:
        match = _caption_match(str(block["text"]))
        if block["kind"] != "caption" or match is None:
            continue
        is_figure = match.group("kind").lower().startswith("fig")
        collection = figures if is_figure else tables
        prefix = "f" if is_figure else "t"
        identifier = f"{prefix}{len(collection) + 1:05d}"
        item: dict[str, object] = {
            "id": identifier,
            "label": match.group("label"),
            "caption": block["text"],
            "caption_block_id": block["id"],
            "anchor_id": block["anchor_id"],
            "object_block_ids": [],
            "uncertain": True,
            "evidence_status": "caption-observed",
            "interpretation_status": "not-interpreted",
        }
        if is_figure:
            images = [
                value
                for value in layouts[int(block["page"])].objects
                if value.object_type == "image" and _meaningful_image(value)
            ]
            caption_bbox = anchor_by_id[str(block["anchor_id"])]["bbox"]
            positioned = [
                (distance, image)
                for image in images
                if (distance := _image_caption_distance(image, caption_bbox))
                is not None
            ]
            closest = min((distance for distance, _ in positioned), default=None)
            linked_images = [
                image
                for distance, image in positioned
                if closest is not None and distance <= closest + 0.03
            ]
            item["source_objects"] = [
                {
                    "name": image.name,
                    "page": block["page"],
                    "width": image.width,
                    "height": image.height,
                    "bbox": list(image.bbox) if image.bbox else None,
                }
                for image in linked_images
            ]
            if len(linked_images) == 1:
                item["association"] = "caption+single-page-image"
                item["evidence_status"] = "caption-and-region-observed"
                associated_images.add((int(block["page"]), linked_images[0].name))
            elif linked_images:
                item["association"] = "caption+positioned-page-images"
                item["evidence_status"] = "caption-and-region-observed"
                associated_images.update(
                    (int(block["page"]), image.name) for image in linked_images
                )
            else:
                item["association"] = "caption-only"
        else:
            cells, row_count, column_count = _table_cells(block, blocks, anchor_by_id)
            item["cells"] = cells
            item["row_count"] = row_count
            item["column_count"] = column_count
            item["object_block_ids"] = list(
                dict.fromkeys(str(cell["block_id"]) for cell in cells)
            )
            if cells:
                item["association"] = "caption+positioned-cells"
                item["evidence_status"] = "caption-and-cell-evidence-observed"
                # Cell structure is heuristic evidence, not a semantic guarantee.
                item["uncertain"] = True
            else:
                item["association"] = "caption-only"
        collection.append(item)
        by_block[str(block["id"])]["object_ref"] = identifier

    meaningful_images = {
        (page_number, image.name)
        for page_number, layout in layouts.items()
        for image in layout.objects
        if image.object_type == "image" and _meaningful_image(image)
    }
    return figures, tables, len(meaningful_images - associated_images)


class _StructureStage:
    name = "sections-references-and-objects"

    def run(self, context: PipelineContext) -> None:
        _mark_bibliography_blocks(context.blocks)
        _deduplicate_caption_blocks(context.blocks)
        context.sections = _sections(context.blocks)
        context.references = _references(context.blocks)
        (
            context.figures,
            context.tables,
            context.unassociated_image_resources,
        ) = _objects(context.blocks, context.anchors, context.layouts)


class _QualityStage:
    name = "quality-classification"

    def run(self, context: PipelineContext) -> None:
        config = context.config
        character_count = sum(len(str(block["text"])) for block in context.blocks)
        if character_count < config.min_text_characters:
            context.warnings.append(
                {
                    "code": "SPARSE_TEXT",
                    "detail": (
                        f"only {character_count} native-text characters were "
                        "extracted; an alternate/OCR backend is required"
                    ),
                }
            )
        anchored = sum(bool(item["anchored"]) for item in context.anchors)
        unresolved_references = sum(
            not bool(item["resolved"]) for item in context.references
        )
        confidences = [
            float(item.get("extraction_confidence", 1.0)) for item in context.blocks
        ]
        ocr_blocks = [
            item
            for item in context.blocks
            if "ocr" in str(item.get("extraction_method", "")).casefold()
            or any(
                "ocr" in str(engine).casefold() or "tesseract" in str(engine).casefold()
                for engine in item.get("source_engines", [])
            )
        ]
        review_codes = {"OCR_ENGINE_DISAGREEMENT", "OCR_ORIENTATION_UNCERTAIN"}
        context.quality = {
            "page_coverage": {
                "parsed": len(context.layouts),
                "total": context.source.page_count,
                "ratio": round(len(context.layouts) / context.source.page_count, 6),
            },
            "anchor_coverage": {
                "anchored": anchored,
                "total": len(context.blocks),
                "ratio": (
                    round(anchored / len(context.blocks), 6) if context.blocks else 0.0
                ),
            },
            "text_characters": character_count,
            "section_count": len(context.sections),
            "reference_count": len(context.references),
            "unresolved_reference_count": unresolved_references,
            "figure_count": len(context.figures),
            "figures_with_region_evidence": sum(
                item.get("evidence_status") == "caption-and-region-observed"
                for item in context.figures
            ),
            "table_count": len(context.tables),
            "tables_with_cells": sum(
                bool(item.get("cells")) for item in context.tables
            ),
            "suppressed_page_furniture": context.suppressed_page_furniture,
            "unassociated_image_resources": (context.unassociated_image_resources),
            "ocr_supplemented_blocks": len(ocr_blocks),
            "ocr_consensus_blocks": sum(
                item.get("extraction_method") == "ocr-consensus"
                or len(item.get("source_engines", [])) > 1
                for item in ocr_blocks
            ),
            "mean_extraction_confidence": (
                round(sum(confidences) / len(confidences), 6) if confidences else 0.0
            ),
            "manual_review_required": any(
                item["code"] in review_codes for item in context.warnings
            ),
            "stopped_early": context.stopped_early,
        }
        informational_warnings = {
            "OCR_TRIGGERED",
            "OCR_TEXT_SUPPLEMENTED",
            "OCR_ORIENTATION_CORRECTED",
            "OCR_DESKEW_APPLIED",
        }
        blocking_warnings = [
            item
            for item in context.warnings
            if item["code"] not in informational_warnings
        ]
        if context.errors and not context.blocks:
            context.status = "FAILED"
        elif (
            context.errors
            or blocking_warnings
            or context.stopped_early
            or not context.blocks
        ):
            context.status = "PARTIAL"
        else:
            context.status = "PARSED"


def _document(context: PipelineContext, pipeline: ParserPipeline) -> dict[str, object]:
    source = context.source
    config = context.config
    backend = context.backend
    backend_identity = {"name": backend.name, "version": backend.version}
    if hasattr(backend, "execution_identity"):
        backend_identity["components"] = backend.execution_identity
    execution_payload = {
        "backend": backend_identity,
        "configuration": config.as_dict(),
        "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
        "stages": list(pipeline.stage_names),
    }
    execution_fingerprint = hashlib.sha256(
        json.dumps(execution_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    document = {
        "schema": PARSED_DOCUMENT_SCHEMA,
        "created_at": context.created_at,
        "parser": {
            "name": PARSER_NAME,
            "version": PARSER_VERSION,
            "backend": backend_identity,
            "pipeline_stages": list(pipeline.stage_names),
            "configuration": config.as_dict(),
            "configuration_fingerprint": config.fingerprint,
            "execution_fingerprint": execution_fingerprint,
        },
        "source": {
            "artifact_id": f"an:source:sha256:{source.pdf_sha256}",
            "doi": source.doi,
            "pdf_sha256": source.pdf_sha256,
            "acquisition_sidecar_sha256": source.sidecar_sha256,
            "page_count": source.page_count,
            "acquisition_schema": source.acquisition_schema,
            "locators": {},
        },
        "status": context.status,
        "warnings": context.warnings,
        "errors": context.errors,
        "quality": context.quality,
        "pages": [
            {
                "page": page_number,
                "width": layout.width,
                "height": layout.height,
                "rotation": layout.rotation,
                "media_box": list(layout.media_box) if layout.media_box else None,
                "crop_box": list(layout.crop_box) if layout.crop_box else None,
                "coordinate_system": layout.coordinate_system,
            }
            for page_number, layout in sorted(context.layouts.items())
        ],
        "sections": context.sections,
        "blocks": context.blocks,
        "anchors": context.anchors,
        "references": context.references,
        "figures": context.figures,
        "tables": context.tables,
    }
    document["artifact_id"] = compute_parsed_artifact_id(document)
    return document


def parse_pdf(
    source: ParserInput,
    *,
    created_at: str,
    config: ParserConfig,
    backend: ExtractionBackend | None = None,
) -> dict[str, object]:
    """Run a request-local pipeline over an already gated PDF."""

    selected_backend = backend or NativePdfBackend()
    reader = PdfReader(source.pdf_path, strict=False)
    context = PipelineContext(
        source=source,
        reader=reader,
        config=config,
        created_at=created_at,
        backend=selected_backend,
    )
    pipeline = ParserPipeline(
        (_NativeExtractionStage(), _StructureStage(), _QualityStage())
    )
    pipeline.run(context)
    return _document(context, pipeline)
