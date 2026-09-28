"""Composable scientific-document parsing pipeline."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass

from pypdf import PdfReader

from aletheia_nexus.content.backends import ExtractionBackend, NativePdfBackend
from aletheia_nexus.content.gate import ParserInput
from aletheia_nexus.content.models import LayoutLine, PageLayout, PipelineContext
from aletheia_nexus.content.pipeline import ParserPipeline
from aletheia_nexus.content.schema import PARSED_DOCUMENT_SCHEMA
from aletheia_nexus.core.identifiers.doi import extract_dois

PARSER_NAME = "structured-pdf-pipeline"
PARSER_VERSION = "2.1.0"

_HEADING_NUMBER = re.compile(
    r"^(?:(?P<numbered>[1-9]\d*(?:\.\d+){1,4})[.)]?"
    r"|(?P<integer>[1-9]\d*)[.)]|(?P<bare>[1-9]))"
    r"\s+(?=[^\W\d_]{2})",
    re.UNICODE,
)
_HEADING_ROMAN = re.compile(r"^(?P<number>[IVXLCDM]+|[A-Z])[.)]\s+(?=\S)")
_REFERENCE = re.compile(r"^(?:\[(?P<bracket>\d+)\]|(?P<plain>\d+)[.)]?)\s+")
_BRACKETED_REFERENCE = re.compile(r"^\[\d+\]\s+")
_AUTHOR_REFERENCE = re.compile(
    r"^\d+[.)]?\s+(?:"
    r"(?:[^,\s]+\s+)*[^,\s]+,\s+[A-Z](?:[.\s]|$)"
    r"|(?:[^,\s]+\s+)*[A-Z]{1,4},\s+[A-Z][a-z]"
    r"|[^\s]+\s+[A-Z]{1,4}\.\s+[A-Z]"
    r")"
)
_CITATION = re.compile(r"\[(\d+(?:\s*[-,]\s*\d+)*)\]")
_CAPTION = re.compile(
    r"^(?P<kind>fig(?:ure)?|table)\.?\s*"
    r"(?P<label>(?:[A-Z]?\d+[A-Za-z]?|[IVXLCDM]+))\s*[:.|\-]?\s*",
    re.IGNORECASE,
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
    return (
        re.sub(
            r"^(?:[1-9]\d*(?:\.\d+){1,4}[.)]?|[1-9]\d*[.)]|[1-9]"
            r"|(?:[IVXLCDM]+|[A-Z])[.)])\s+",
            "",
            text,
        )
        .strip()
        .casefold()
    )


def _semantic_section(text: str) -> str | None:
    return _SEMANTIC_SECTIONS.get(_strip_heading_number(text))


def _kind(line: LayoutLine, median_font: float, heading_font_ratio: float) -> str:
    text = line.text.strip()
    if _CAPTION.match(text):
        return "caption"
    if _BRACKETED_REFERENCE.match(text) or _AUTHOR_REFERENCE.match(text):
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
    if (
        short
        and _looks_like_heading_text(text)
        and (font_heading or known_heading or numbered_heading or roman_heading)
    ):
        return "heading"
    if len(text) <= 160 and equation_like:
        return "equation"
    return "paragraph"


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
    name = "native-layout-and-block-assembly"

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
            except Exception as exc:
                context.errors.append(
                    {
                        "code": "PAGE_EXTRACTION_FAILED",
                        "detail": (f"page {page_index}: {type(exc).__name__}: {exc}"),
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
                        "coordinate_system": "pdf-bottom-left-normalized",
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

    in_bibliography = False
    for block in blocks:
        semantic_type = (
            _semantic_section(str(block["text"]))
            if block["kind"] == "heading"
            else None
        )
        if semantic_type == "references":
            in_bibliography = True
            continue
        if not in_bibliography:
            continue
        if semantic_type is not None:
            in_bibliography = False
            continue
        if _REFERENCE.match(str(block["text"])):
            block["kind"] = "reference"
        elif block["kind"] == "heading":
            block["kind"] = "paragraph"


def _references(
    blocks: list[dict[str, object]], sections: list[dict[str, object]]
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    by_label: dict[str, dict[str, object]] = {}
    bibliography_blocks = {
        str(block_id)
        for section in sections
        if section.get("semantic_type") == "references"
        for block_id in section["block_ids"]
    }
    resolved_block_ids: set[str] = set()
    for block in blocks:
        match = _REFERENCE.match(str(block["text"]))
        if (
            block["kind"] != "reference" and str(block["id"]) not in bibliography_blocks
        ) or match is None:
            continue
        label = match.group("bracket") or match.group("plain")
        dois = extract_dois(str(block["text"]))
        item = {
            "id": f"r{len(references) + 1:05d}",
            "label": label,
            "block_id": block["id"],
            "anchor_id": block["anchor_id"],
            "raw_text": block["text"],
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
        match = _CAPTION.match(str(block["text"]))
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
            "resolved": True,
            "uncertain": True,
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
                associated_images.add((int(block["page"]), linked_images[0].name))
            elif linked_images:
                item["association"] = "caption+positioned-page-images"
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
                item["uncertain"] = False
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
        context.sections = _sections(context.blocks)
        context.references = _references(context.blocks, context.sections)
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
        unresolved_figures = sum(not bool(item["resolved"]) for item in context.figures)
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
            "unresolved_figure_count": unresolved_figures,
            "table_count": len(context.tables),
            "tables_with_cells": sum(
                bool(item.get("cells")) for item in context.tables
            ),
            "suppressed_page_furniture": context.suppressed_page_furniture,
            "unassociated_image_resources": (context.unassociated_image_resources),
            "stopped_early": context.stopped_early,
        }
        if context.errors and not context.blocks:
            context.status = "FAILED"
        elif (
            context.errors
            or context.warnings
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
    execution_payload = {
        "backend": {"name": backend.name, "version": backend.version},
        "configuration": config.as_dict(),
        "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
        "stages": list(pipeline.stage_names),
    }
    execution_fingerprint = hashlib.sha256(
        json.dumps(execution_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "schema": PARSED_DOCUMENT_SCHEMA,
        "created_at": context.created_at,
        "parser": {
            "name": PARSER_NAME,
            "version": PARSER_VERSION,
            "backend": {"name": backend.name, "version": backend.version},
            "pipeline_stages": list(pipeline.stage_names),
            "configuration": config.as_dict(),
            "configuration_fingerprint": config.fingerprint,
            "execution_fingerprint": execution_fingerprint,
        },
        "source": {
            "doi": source.doi,
            "pdf_sha256": source.pdf_sha256,
            "acquisition_sidecar_sha256": source.sidecar_sha256,
            "page_count": source.page_count,
            "acquisition_schema": source.acquisition_schema,
            "pdf_path": str(source.pdf_path),
            "acquisition_sidecar_path": str(source.sidecar_path),
        },
        "status": context.status,
        "warnings": context.warnings,
        "errors": context.errors,
        "quality": context.quality,
        "sections": context.sections,
        "blocks": context.blocks,
        "anchors": context.anchors,
        "references": context.references,
        "figures": context.figures,
        "tables": context.tables,
    }


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
