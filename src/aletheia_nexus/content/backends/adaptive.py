"""Native-first, selectively triggered OCR and specialist extraction."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

from aletheia_nexus.content.backends.base import (
    ExtractionBackend,
    RegionExtractionBackend,
)
from aletheia_nexus.content.backends.native import NativePdfBackend
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageRegion

_FORMULA_TEXT = re.compile(r"(?:[=≈≤≥±∑∫√→←]|[αβγδεϵζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ])")


@dataclass(frozen=True)
class AdaptiveOcrConfig:
    """Evidence thresholds for selective OCR and coordinate-level fusion."""

    min_native_characters: int = 80
    max_suspicious_character_ratio: float = 0.02
    image_coverage_trigger: float = 0.65
    unanchored_image_min_area: float = 0.04
    bbox_overlap_threshold: float = 0.35
    text_similarity_threshold: float = 0.82
    min_ocr_confidence: float = 0.55

    def __post_init__(self) -> None:
        if self.min_native_characters < 0:
            raise ValueError("min_native_characters cannot be negative")
        for name in (
            "max_suspicious_character_ratio",
            "image_coverage_trigger",
            "unanchored_image_min_area",
            "bbox_overlap_threshold",
            "text_similarity_threshold",
            "min_ocr_confidence",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _line_bbox(
    line: LayoutLine, layout: PageLayout
) -> tuple[float, float, float, float]:
    if layout.width <= 0 or layout.height <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        max(0.0, min(1.0, line.x0 / layout.width)),
        max(0.0, min(1.0, line.y0 / layout.height)),
        max(0.0, min(1.0, line.x1 / layout.width)),
        max(0.0, min(1.0, line.y1 / layout.height)),
    )


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    intersection = _area(
        (
            max(first[0], second[0]),
            max(first[1], second[1]),
            min(first[2], second[2]),
            min(first[3], second[3]),
        )
    )
    denominator = min(_area(first), _area(second))
    return intersection / denominator if denominator else 0.0


def _union_area(boxes: Iterable[tuple[float, float, float, float]]) -> float:
    """Calculate clipped rectangle union area without double counting."""

    clipped = [
        (
            max(0.0, min(1.0, box[0])),
            max(0.0, min(1.0, box[1])),
            max(0.0, min(1.0, box[2])),
            max(0.0, min(1.0, box[3])),
        )
        for box in boxes
        if _area(box) > 0
    ]
    xs = sorted({value for box in clipped for value in (box[0], box[2])})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (box[1], box[3]) for box in clipped if box[0] < right and box[2] > left
        )
        covered = 0.0
        start = end = None
        for lower, upper in intervals:
            if start is None:
                start, end = lower, upper
            elif lower > end:
                covered += end - start
                start, end = lower, upper
            else:
                end = max(end, upper)
        if start is not None:
            covered += end - start
        total += (right - left) * covered
    return min(total, 1.0)


def _suspicious_character_ratio(lines: Sequence[LayoutLine]) -> float:
    text = "".join(line.text for line in lines)
    if not text:
        return 0.0
    suspicious = sum(
        character == "\ufffd" or unicodedata.category(character) in {"Cc", "Cs", "Co"}
        for character in text
    )
    return suspicious / len(text)


def _image_regions_without_text(
    layout: PageLayout, config: AdaptiveOcrConfig
) -> list[PageRegion]:
    line_boxes = [_line_bbox(line, layout) for line in layout.lines]
    result: list[PageRegion] = []
    for item in layout.objects:
        if item.object_type != "image" or item.bbox is None:
            continue
        if _area(item.bbox) < config.unanchored_image_min_area:
            continue
        if any(_overlap(item.bbox, line_box) >= 0.1 for line_box in line_boxes):
            continue
        nearby = (
            [
                line.text.casefold()
                for line in layout.lines
                if min(
                    abs((line.y0 + line.y1) / (2 * layout.height) - item.bbox[1]),
                    abs((line.y0 + line.y1) / (2 * layout.height) - item.bbox[3]),
                )
                <= 0.15
            ]
            if layout.height > 0
            else []
        )
        joined = " ".join(nearby)
        if "table" in joined:
            region_type = "table"
        elif any(marker in joined for marker in ("fig", "chart", "graph")):
            region_type = "figure"
        else:
            region_type = "figure"
        result.append(
            PageRegion(
                region_type=region_type,
                bbox=item.bbox,
                reason="painted image region has no overlapping native text anchor",
            )
        )
    return result


def _formula_regions(layout: PageLayout) -> list[PageRegion]:
    result: list[PageRegion] = []
    for line in layout.lines:
        if len(line.text) > 200 or _FORMULA_TEXT.search(line.text) is None:
            continue
        bbox = _line_bbox(line, layout)
        if _area(bbox) == 0:
            continue
        result.append(
            PageRegion(
                region_type="formula",
                bbox=bbox,
                reason="native line contains mathematical notation",
            )
        )
    return result


def _trigger_reasons(layout: PageLayout, config: AdaptiveOcrConfig) -> list[str]:
    reasons: list[str] = []
    native_characters = sum(len(line.text.strip()) for line in layout.lines)
    if native_characters < config.min_native_characters:
        reasons.append("sparse-native-text")
    if (
        _suspicious_character_ratio(layout.lines)
        > config.max_suspicious_character_ratio
    ):
        reasons.append("suspicious-native-characters")
    image_boxes = [
        item.bbox
        for item in layout.objects
        if item.object_type == "image" and item.bbox is not None
    ]
    if _union_area(image_boxes) >= config.image_coverage_trigger:
        reasons.append("image-dominant-page")
    if _image_regions_without_text(layout, config):
        reasons.append("unanchored-image-text-candidate")
    return reasons


def _similar(first: str, second: str, threshold: float) -> bool:
    left = _normalized_text(first)
    right = _normalized_text(second)
    if not left or not right:
        return False
    return (
        left == right
        or SequenceMatcher(None, left, right, autojunk=False).ratio() >= threshold
    )


def _engine_id(backend: object) -> str:
    return f"{getattr(backend, 'name')}@{getattr(backend, 'version')}"


class AdaptiveOcrBackend:
    """Preserve native text and add OCR only where positioned evidence is absent."""

    name = "adaptive-native-ocr"
    version = "1.0.0"

    def __init__(
        self,
        *,
        native_backend: ExtractionBackend | None = None,
        ocr_backends: Sequence[ExtractionBackend] = (),
        specialist_backends: Sequence[RegionExtractionBackend] = (),
        config: AdaptiveOcrConfig | None = None,
    ) -> None:
        self.native_backend = native_backend or NativePdfBackend()
        self.ocr_backends = tuple(ocr_backends)
        self.specialist_backends = tuple(specialist_backends)
        self.config = config or AdaptiveOcrConfig()

    @property
    def execution_identity(self) -> dict[str, object]:
        return {
            "native": _engine_id(self.native_backend),
            "ocr": [_engine_id(item) for item in self.ocr_backends],
            "specialists": [_engine_id(item) for item in self.specialist_backends],
            "config": self.config.__dict__,
        }

    def extract_page(self, page: Any, page_number: int) -> PageLayout:
        native = self.native_backend.extract_page(page, page_number)
        reasons = _trigger_reasons(native, self.config)
        regions = [
            *_image_regions_without_text(native, self.config),
            *_formula_regions(native),
        ]
        warnings = list(native.warnings)
        candidate_layouts: list[PageLayout] = []

        if reasons and not self.ocr_backends:
            warnings.append(
                {
                    "code": "OCR_RECOMMENDED",
                    "detail": f"page {page_number}: {', '.join(reasons)}; no OCR engine configured",
                }
            )
        elif reasons:
            warnings.append(
                {
                    "code": "OCR_TRIGGERED",
                    "detail": f"page {page_number}: {', '.join(reasons)}",
                }
            )
            for backend in self.ocr_backends:
                candidate_layouts.append(backend.extract_page(page, page_number))

        for region in regions:
            for backend in self.specialist_backends:
                if region.region_type not in backend.supported_regions:
                    continue
                extracted = backend.extract_region(page, page_number, region)
                candidate_layouts.append(
                    replace(
                        extracted,
                        lines=tuple(
                            replace(line, content_region=region.region_type)
                            for line in extracted.lines
                        ),
                    )
                )

        lines, merge_warnings = self._merge(native, candidate_layouts)
        warnings.extend(merge_warnings)
        return replace(native, lines=lines, warnings=tuple(warnings))

    def _merge(
        self, native: PageLayout, candidate_layouts: Sequence[PageLayout]
    ) -> tuple[tuple[LayoutLine, ...], list[dict[str, str]]]:
        native_lines = list(native.lines)
        supplements: list[LayoutLine] = []
        warnings: list[dict[str, str]] = []

        for layout in candidate_layouts:
            for raw_line in layout.lines:
                confidence = max(0.0, min(1.0, raw_line.extraction_confidence))
                if confidence < self.config.min_ocr_confidence:
                    continue
                engines = raw_line.source_engines or (raw_line.extraction_method,)
                line = replace(
                    raw_line,
                    extraction_confidence=confidence,
                    source_engines=tuple(dict.fromkeys(engines)),
                    uncertain=raw_line.uncertain or confidence < 0.85,
                )
                line_box = _line_bbox(line, layout)

                native_match = next(
                    (
                        (index, existing)
                        for index, existing in enumerate(native_lines)
                        if _overlap(line_box, _line_bbox(existing, native))
                        >= self.config.bbox_overlap_threshold
                    ),
                    None,
                )
                if native_match is not None:
                    index, existing = native_match
                    if _similar(
                        existing.text,
                        line.text,
                        self.config.text_similarity_threshold,
                    ):
                        native_lines[index] = replace(
                            existing,
                            source_engines=tuple(
                                dict.fromkeys(
                                    existing.source_engines + line.source_engines
                                )
                            ),
                            extraction_confidence=max(
                                existing.extraction_confidence, confidence
                            ),
                            content_region=(
                                line.content_region
                                if line.content_region != "body"
                                else existing.content_region
                            ),
                        )
                    else:
                        warnings.append(
                            {
                                "code": "OCR_ENGINE_DISAGREEMENT",
                                "detail": (
                                    f"page {native.page}: OCR disagrees with native text "
                                    f"near bbox {tuple(round(v, 3) for v in line_box)}"
                                ),
                            }
                        )
                    continue

                supplement_match = next(
                    (
                        (index, existing)
                        for index, existing in enumerate(supplements)
                        if _overlap(line_box, _line_bbox(existing, native))
                        >= self.config.bbox_overlap_threshold
                    ),
                    None,
                )
                if supplement_match is None:
                    supplements.append(line)
                    continue
                index, existing = supplement_match
                if _similar(
                    existing.text, line.text, self.config.text_similarity_threshold
                ):
                    preferred = (
                        line
                        if line.extraction_confidence > existing.extraction_confidence
                        else existing
                    )
                    supplements[index] = replace(
                        preferred,
                        extraction_method="ocr-consensus",
                        extraction_confidence=min(
                            1.0,
                            max(
                                existing.extraction_confidence,
                                line.extraction_confidence,
                            )
                            + 0.1,
                        ),
                        source_engines=tuple(
                            dict.fromkeys(existing.source_engines + line.source_engines)
                        ),
                        uncertain=False,
                    )
                else:
                    warnings.append(
                        {
                            "code": "OCR_ENGINE_DISAGREEMENT",
                            "detail": (
                                f"page {native.page}: OCR engines disagree near bbox "
                                f"{tuple(round(v, 3) for v in line_box)}"
                            ),
                        }
                    )
                    if line.extraction_confidence > existing.extraction_confidence:
                        supplements[index] = replace(line, uncertain=True)

        if supplements:
            warnings.append(
                {
                    "code": "OCR_TEXT_SUPPLEMENTED",
                    "detail": f"page {native.page}: added {len(supplements)} non-overlapping OCR lines",
                }
            )
        return tuple(native_lines + supplements), warnings
