"""Composable scientific-document parsing pipeline."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass, replace

from pypdf import PdfReader

from aletheia_nexus.content.backends import ExtractionBackend, LayoutPdfBackend
from aletheia_nexus.content.captions import (
    _caption_match,
    _deduplicate_caption_blocks,
)
from aletheia_nexus.content.diagnostics import safe_exception_detail
from aletheia_nexus.content.embedded_tables import (
    append_embedded_tables,
    prepare_embedded_tables,
)
from aletheia_nexus.content.figure_labels import (
    associate_keyed_labels,
    associate_percentage_results,
)
from aletheia_nexus.content.gate import ParserInput
from aletheia_nexus.content.geometry import PageGeometry
from aletheia_nexus.content.image_tiles import union_box, vertical_tile_groups
from aletheia_nexus.content.indexed_tables import (
    prepare_indexed_tables,
    repair_indexed_tables,
)
from aletheia_nexus.content.models import (
    LayoutLine,
    PageLayout,
    PipelineContext,
    validate_page_layout,
)
from aletheia_nexus.content.pipeline import ParserPipeline
from aletheia_nexus.content.ruled_tables import (
    explicit_grid_cells,
    prepare_ruled_tables,
)
from aletheia_nexus.content.schema import (
    PARSED_DOCUMENT_SCHEMA,
    compute_parsed_artifact_id,
)
from aletheia_nexus.content.table_layout import (
    _aligned_table_fragments,
    _prepare_table_lines,
    _table_cells,
    _table_local_warnings,
)
from aletheia_nexus.core.identifiers.doi import extract_dois

PARSER_NAME = "structured-pdf-pipeline"
PARSER_VERSION = "3.10.12"

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
_EQUATION = re.compile(r"(?:[=≈≤≥±∑∫√→←]|\b(?:sin|cos|log|exp)\s*\(|^[A-Za-z]\s*=)")
_MATH_GLYPH = re.compile(r"[αβγδεϵζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ]", re.UNICODE)
_PAGE_LABEL = re.compile(
    r"^(?:[-–—]\s*)?\d+(?:\s*of\s*\d+)*(?:\s*[-–—])?$", re.IGNORECASE
)
_SEMANTIC_SECTIONS = {
    "摘要": "abstract",
    "引言": "introduction",
    "实验": "methods",
    "实验部分": "methods",
    "试验方法": "methods",
    "实验方法": "methods",
    "材料与方法": "methods",
    "结果与讨论": "results-discussion",
    "结果和讨论": "results-discussion",
    "结论": "conclusion",
    "参考文献": "references",
    "致谢": "acknowledgments",
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


def _associate_figure_labels(lines, objects, width, height):
    """Keep explicitly printed percentage labels with their aligned categories.

    This reads printed labels, never estimates bar heights or plot values.
    Only a complete, unique set of spatial column matches is emitted. Original
    fragments remain alternative evidence and derived associations stay flagged.
    """
    removed = set()
    pairs = []
    for obj in objects:
        if obj.object_type != "image" or not obj.bbox:
            continue
        x0, y0, x1, y1 = (
            obj.bbox[0] * width,
            obj.bbox[1] * height,
            obj.bbox[2] * width,
            obj.bbox[3] * height,
        )
        values = [
            line
            for line in lines
            if line.content_region not in {"ocr-alternative", "native-alternative"}
            and re.fullmatch(r"[−+\-]?\d+(?:\.\d+)?\s*%", line.text.strip())
            and x0 <= line.x0 < line.x1 <= x1
            and y0 <= line.y0 <= y1
        ]
        values.sort(key=lambda line: (line.x0 + line.x1) / 2)
        if len(values) < 3:
            continue
        centers = [(line.x0 + line.x1) / 2 for line in values]
        if any(
            b - a < max(line.font_size for line in values) * 2
            for a, b in zip(centers, centers[1:])
        ):
            continue
        labels = []
        originals = []
        for line in lines:
            if (
                line.content_region in {"ocr-alternative", "native-alternative"}
                or not -line.font_size * 0.5 <= y0 - line.y1 <= line.font_size * 2
                or line.x1 < centers[0]
                or line.x0 > centers[-1]
            ):
                continue
            for part in _aligned_table_fragments(line, values) or (line,):
                labels.append(part)
                originals.append(line)
        matches = []
        used = set()
        for i, value in enumerate(values):
            spacing = min(
                (abs(c - centers[i]) for j, c in enumerate(centers) if j != i)
            )
            near = [
                j
                for j, label in enumerate(labels)
                if abs((label.x0 + label.x1) / 2 - centers[i]) < spacing * 0.3
            ]
            if len(near) != 1 or near[0] in used:
                break
            used.add(near[0])
            matches.append((value, labels[near[0]], originals[near[0]]))
        if len(matches) != len(values):
            continue
        if (
            max(label.y0 for _, label, _ in matches)
            - min(label.y0 for _, label, _ in matches)
            > max(label.font_size for _, label, _ in matches) * 0.6
        ):
            continue
        for value, label, original in matches:
            removed.update((id(value), id(original)))
            pairs.append(
                replace(
                    value,
                    text=f"{label.text}: {value.text}",
                    x0=min(label.x0, value.x0),
                    y0=min(label.y0, value.y0),
                    x1=max(label.x1, value.x1),
                    y1=max(label.y1, value.y1),
                    content_region="figure",
                    extraction_method="positioned-figure-label-value",
                    source_engines=tuple(
                        dict.fromkeys((*label.source_engines, *value.source_engines))
                    ),
                    uncertain=True,
                    glyph_spans=(),
                )
            )
    return tuple(
        [line for line in lines if id(line) not in removed]
        + pairs
        + [
            replace(line, content_region="native-alternative", uncertain=True)
            for line in lines
            if id(line) in removed
        ]
    )


def _sort_spatial_lines(lines):
    """Order aligned figure labels left-to-right despite OCR box jitter."""
    ordered = sorted(lines, key=lambda line: (-line.y0, line.x0))
    result = []
    i = 0
    while i < len(ordered):
        first = ordered[i]
        row = [first]
        i += 1
        if first.content_region == "figure":
            while i < len(ordered):
                other = ordered[i]
                h = min(first.y1 - first.y0, other.y1 - other.y0)
                if (
                    other.content_region != "figure"
                    or h <= 0
                    or max(first.y1 - first.y0, other.y1 - other.y0) > h * 1.6
                    or abs(first.y0 + first.y1 - other.y0 - other.y1) > h
                ):
                    break
                row.append(other)
                i += 1
        result.extend(sorted(row, key=lambda line: line.x0))
    return result


def _order_layout_lines(lines, layout, config):
    """Keep a spanning source image together across prose columns."""
    for obj in sorted(layout.objects, key=lambda o: -(o.bbox[3] if o.bbox else 0)):
        if obj.object_type != "image" or obj.bbox is None:
            continue
        x0, y0, x1, y1 = obj.bbox
        if x1 - x0 < 0.58 or (x1 - x0) * (y1 - y0) > 0.65:
            continue
        left, right = x0 * layout.width, x1 * layout.width
        bottom, top = y0 * layout.height, y1 * layout.height
        band = [
            line
            for line in lines
            if line.content_region == "figure"
            and left - 1 <= (line.x0 + line.x1) / 2 <= right + 1
            and bottom - 1 <= (line.y0 + line.y1) / 2 <= top + 1
        ]
        if len(band) < 2:
            continue
        selected = {id(line) for line in band}
        rest = tuple(line for line in lines if id(line) not in selected)
        return [
            *_order_layout_lines(
                tuple(line for line in rest if line.y0 >= top), layout, config
            ),
            *_sort_spatial_lines(band),
            *_order_layout_lines(
                tuple(line for line in rest if bottom < line.y0 < top), layout, config
            ),
            *_order_layout_lines(
                tuple(line for line in rest if line.y0 <= bottom), layout, config
            ),
        ]
    return _order_lines(lines, layout.width, config)


def _order_lines(
    lines: tuple[LayoutLine, ...], width: float, config: ParserConfig
) -> list[LayoutLine]:
    """Use spanning lines as bands, then read left column before right column."""

    captions = [
        line for line in lines if line.content_region == "spanning-table-caption"
    ]
    if captions:
        caption = max(captions, key=lambda item: item.y1)
        next_caption_top = max(
            (
                line.y1
                for line in lines
                if line.y1 < caption.y0 and _caption_match(line.text)
            ),
            default=float("-inf"),
        )
        table = [
            line
            for line in lines
            if line.content_region == "table-cell"
            and line.y1 <= caption.y0 + 1
            and line.y0 >= next_caption_top
        ]
        # Spanning table rows are a single reading band, never two prose columns.
        band = [caption]
        for line in sorted(table, key=lambda item: -item.y1):
            band.append(line)
        top, bottom = max(item.y1 for item in band), min(item.y0 for item in band)
        selected = {id(item) for item in band}
        rest = tuple(item for item in lines if id(item) not in selected)
        return [
            *_order_lines(
                tuple(item for item in rest if item.y0 >= top), width, config
            ),
            *sorted(band, key=lambda item: (-round((item.y0 + item.y1) / 2), item.x0)),
            *_order_lines(
                tuple(item for item in rest if bottom < item.y0 < top), width, config
            ),
            *_order_lines(
                tuple(item for item in rest if item.y0 <= bottom), width, config
            ),
        ]
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
        left_substantial = sum(
            len(line.text) > 12 or line.content_region == "table-cell" for line in left
        )
        right_substantial = sum(
            len(line.text) > 12 or line.content_region == "table-cell" for line in right
        )
        if (
            len(left) >= 2
            and len(right) >= 2
            and left_substantial >= 2
            and right_substantial >= 2
        ):
            return _sort_spatial_lines(left) + _sort_spatial_lines(right)
        return _sort_spatial_lines(region)

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
    if line.content_region == "table-cell":
        return "paragraph"
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
    if layout.height <= 0 or line.content_region in {
        "table-cell",
        "spanning-table-caption",
        "figure",
    }:
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
    if (
        previous.content_region == "table-cell"
        or current.content_region == "table-cell"
        or previous.content_region != current.content_region
        or previous.extraction_method != current.extraction_method
    ):
        return False
    chinese_prose = all(
        len(re.findall(r"[\u3400-\u9fff]", line.text)) >= 8
        for line in (previous, current)
    )
    if (
        not chinese_prose
        and len(previous.text.split()) <= 2
        and len(current.text.split()) <= 2
    ):
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
            median_font = statistics.median(
                size
                for line in layout.lines
                for size in [line.font_size] * max(1, len(line.text.strip()))
            )
            previous_line: LayoutLine | None = None
            previous_kind: str | None = None
            prepared_lines = _associate_figure_labels(
                layout.lines, layout.objects, layout.width, layout.height
            )
            ordinary = tuple(
                line
                for line in prepared_lines
                if line.content_region not in {"ocr-alternative", "native-alternative"}
            )
            ordinary = _prepare_table_lines(
                ordinary, layout.width, layout.objects, layout.height
            )
            ordinary = prepare_ruled_tables(
                ordinary, layout, _caption_match, _aligned_table_fragments
            )
            ordinary = prepare_embedded_tables(ordinary, layout)
            ordinary = prepare_indexed_tables(ordinary, layout)
            ordinary = associate_keyed_labels(ordinary)
            ordinary = associate_percentage_results(ordinary)
            alternatives = tuple(
                line
                for line in prepared_lines
                if line.content_region in {"ocr-alternative", "native-alternative"}
            )
            ordered = [
                *_order_layout_lines(ordinary, layout, config),
                *_order_lines(alternatives, layout.width, config),
            ]
            for line in ordered:
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
            # Extracted text can merge citations into malformed chains such
            # as [10-12-11]. Retain that text, but do not invent reference links
            # or let one malformed range abort an otherwise readable article.
            match = re.fullmatch(r"\s*(\d{1,9})(?:\s*-\s*(\d{1,9}))?\s*", part)
            if match is None:
                continue
            if match[2] is not None:
                start, end = int(match[1]), int(match[2])
                if 0 <= end - start <= 25:
                    labels.extend(str(item) for item in range(start, end + 1))
            else:
                labels.append(match[1])
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


def _positioned_image_groups(layout):
    images = [o for o in layout.objects if o.object_type == "image" and o.bbox]
    result = []
    for indices in vertical_tile_groups([i.bbox for i in images], tolerance=2e-6):
        members = [images[i] for i in indices]
        region = replace(members[0], bbox=union_box([i.bbox for i in members]))
        if _meaningful_image(region):
            result.append((region, members))
    return result


def _table_raster_warnings(table, blocks, anchors, layout, associated):
    """Disclose actual image regions between a table caption and its cells."""
    caption = anchors[table["anchor_id"]]
    boxes = [
        anchors[cell["anchor_id"]]["bbox"]
        for cell in table.get("cells", [])
        if anchors[cell["anchor_id"]]["page"] == caption["page"]
    ]
    if not boxes or not caption["bbox"]:
        return []
    grid = union_box(boxes)
    bottom, top = grid[3], caption["bbox"][1]
    left = min(grid[0], caption["bbox"][0])
    right = max(grid[2], caption["bbox"][2])
    if bottom >= top or any(
        block["page"] == caption["page"]
        and block["kind"] == "caption"
        and block["id"] != table["caption_block_id"]
        and (box := anchors[block["anchor_id"]]["bbox"])
        and bottom < (box[1] + box[3]) / 2 < top
        for block in blocks
    ):
        return []
    regions = [
        list(region.bbox)
        for region, members in _positioned_image_groups(layout)
        if not any((caption["page"], image.name) in associated for image in members)
        and left <= region.bbox[0] < region.bbox[2] <= right
        and bottom <= region.bbox[1] < region.bbox[3] <= top
    ]
    if not regions:
        return []
    return [
        {
            "code": "RASTER_REGION_TEXT_UNVERIFIED",
            "page": caption["page"],
            "anchor_id": table["anchor_id"],
            "object_id": table["id"],
            "regions": regions,
            "detail": "Raster regions between this table caption and its observed cells may contain untranscribed experimental conditions or results. Recognized cells and partial image labels do not establish image-text coverage; inspect these original regions.",
        }
    ]


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
    image_groups = {
        page: _positioned_image_groups(layout) for page, layout in layouts.items()
    }

    for block in blocks:
        match = _caption_match(str(block["text"]))
        if block["kind"] != "caption" or match is None:
            continue
        is_figure = match.group("kind").lower().startswith(
            ("fig", "scheme")
        ) or match.group("kind") in {"图", "图式"}
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
            groups = image_groups[int(block["page"])]
            images = [region for region, _ in groups]
            members_by_name = {region.name: members for region, members in groups}
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
            # A multi-row figure has panels farther from its caption than the
            # nearest row. Follow only aligned, closely spaced image columns;
            # an intervening caption ends the group.
            for _ in images:
                added = []
                for image in images:
                    if image in linked_images or not image.bbox:
                        continue
                    a = image.bbox
                    for neighbour in linked_images:
                        b = neighbour.bbox
                        if not b:
                            continue
                        overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
                        gap = max(0, a[1] - b[3], b[1] - a[3])
                        separated = any(
                            other["page"] == block["page"]
                            and other["kind"] == "caption"
                            and (box := anchor_by_id[other["anchor_id"]]["bbox"])
                            and min(a[3], b[3])
                            < (box[1] + box[3]) / 2
                            < max(a[1], b[1])
                            for other in blocks
                        )
                        if (
                            0.002 < gap <= 0.04
                            and overlap >= 0.8 * max(a[2] - a[0], b[2] - b[0])
                            and not separated
                        ):
                            added.append(image)
                            break
                if not added:
                    break
                linked_images.extend(added)
            # A PDF can store one figure as hundreds of adjacent one-pixel
            # strips. Associate the observed contiguous region, but retain
            # every original resource and its location in the evidence.
            linked_images = [
                member
                for image in linked_images
                for member in members_by_name[image.name]
            ]
            item["source_objects"] = [
                {
                    "name": image.name,
                    "page": block["page"],
                    "width": image.width,
                    "height": image.height,
                    "bbox": list(image.bbox) if image.bbox else None,
                    "text_completeness": "not-verified",
                }
                for image in linked_images
            ]
            for source in item["source_objects"]:
                box = source["bbox"]
                source["annotation_block_ids"] = [
                    str(candidate["id"])
                    for candidate in blocks
                    if candidate["page"] == block["page"]
                    and any(
                        str(engine).endswith("+image-label")
                        for engine in candidate.get("source_engines", [])
                    )
                    and not str(candidate.get("content_region", "")).endswith(
                        "alternative"
                    )
                    and (label_box := anchor_by_id[candidate["anchor_id"]]["bbox"])
                    and box
                    and box[0] <= (label_box[0] + label_box[2]) / 2 <= box[2]
                    and box[1] <= (label_box[1] + label_box[3]) / 2 <= box[3]
                ]
            item["object_block_ids"] = list(
                dict.fromkeys(
                    bid
                    for source in item["source_objects"]
                    for bid in source["annotation_block_ids"]
                )
            )
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
            explicit = explicit_grid_cells(
                block, blocks, anchor_by_id, layouts[int(block["page"])]
            )
            cells, row_count, column_count = explicit or _table_cells(
                block, blocks, anchor_by_id
            )
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

    append_embedded_tables(tables, blocks, anchor_by_id, layouts)
    repair_indexed_tables(tables, blocks, anchor_by_id, layouts)
    meaningful_images = {
        (page_number, image.name)
        for page_number, groups in image_groups.items()
        for _, members in groups
        for image in members
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
        anchors = {a["id"]: a for a in context.anchors}
        associated = {
            (obj["page"], obj["name"])
            for figure in context.figures
            for obj in figure.get("source_objects", [])
        }
        for table in context.tables:
            context.warnings.extend(
                _table_local_warnings(table, context.blocks, anchors)
            )
            context.warnings.extend(
                _table_raster_warnings(
                    table,
                    context.blocks,
                    anchors,
                    context.layouts[anchors[table["anchor_id"]]["page"]],
                    associated,
                )
            )
        for figure in context.figures:
            objects = figure.get("source_objects", [])
            if objects:
                boxes = [obj["bbox"] for obj in objects]
                regions = [
                    list(union_box([boxes[i] for i in group]))
                    for group in vertical_tile_groups(boxes, tolerance=2e-6)
                ]
                context.warnings.append(
                    {
                        "code": "RASTER_REGION_TEXT_UNVERIFIED",
                        "page": objects[0]["page"],
                        "anchor_id": figure["anchor_id"],
                        "object_id": figure["id"],
                        "regions": regions,
                        "detail": "Image regions may contain untranscribed values, units or scale bars. Caption/panel labels do not establish image-text coverage; inspect these original regions.",
                    }
                )


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
        review_codes = {
            "IMAGE_LABEL_UNRESOLVED",
            "TABLE_COLUMN_COLLISION",
            "TABLE_CONTINUATION_UNRESOLVED",
            "TABLE_ROW_CONTEXT_MISSING",
            "OCR_ENGINE_DISAGREEMENT",
            "OCR_ORIENTATION_UNCERTAIN",
            "NATIVE_GLYPH_UNCERTAIN",
            "IMAGE_DOMINANT_PAGE",
            "RASTER_REGION_TEXT_UNVERIFIED",
            "VECTOR_TEXT_UNVERIFIED",
        }
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
            )
            or any(block.get("uncertain", False) for block in context.blocks),
            "stopped_early": context.stopped_early,
        }
        informational_warnings = {
            "RASTER_REGION_TEXT_UNVERIFIED",
            "MARGIN_TEXT_OMITTED",
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
            "title": source.title,
            "article_id": source.article_id
            or (
                "doi:" + source.doi
                if source.doi
                else f"an:source:sha256:{source.pdf_sha256}"
            ),
            "document_role": source.document_role,
            "identity_basis": source.identity_basis,
            "parent": source.parent,
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

    selected_backend = backend or LayoutPdfBackend()
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
