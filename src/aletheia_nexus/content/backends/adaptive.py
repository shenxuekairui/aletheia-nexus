"""Native-first, selectively triggered OCR and specialist extraction."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

from aletheia_nexus.content.backends.base import (
    ExtractionBackend,
    RegionExtractionBackend,
)
from aletheia_nexus.content.backends.layout import LayoutPdfBackend
from aletheia_nexus.content.backends.readings import (
    corroborate_chinese,
    literal_reading_key,
    recover_word_glyphs,
)
from aletheia_nexus.content.diagnostics import safe_exception_detail
from aletheia_nexus.content.models import (
    LayoutLine,
    PageLayout,
    PageRegion,
    validate_page_layout,
)

_FORMULA_TEXT = re.compile(r"(?:[=≈≤≥±∑∫√→←]|[αβγδεϵζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ])")
_LAYOUT_ASSOCIATIONS = {
    "printed-bar-label-association",
    "positioned-panel-scale",
    "positioned-panel-length",
    "positioned-axis-label-ticks",
}


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
    # OCR inserts spaces between Chinese glyphs and between numbers and units.
    # Compare positioned readings without these segmentation-only differences.
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def _native_supported_label(first, second, native_words):
    """Select an existing OCR label when native text resolves only I/l ambiguity.

    Numbers are excluded. No new spelling is manufactured, and the competing
    OCR reading remains reviewable. Native text containing both forms cannot
    resolve the ambiguity.
    """
    if re.search(r"\d", first.text + second.text):
        return None

    def words(text):
        return re.findall(r"[A-Za-z]+", text)

    def shape(word):
        return word.replace("I", "|").replace("l", "|").casefold()

    a, b = words(first.text), words(second.text)
    if sorted(map(shape, a)) != sorted(map(shape, b)):
        return None
    different = set(a) ^ set(b)
    keys = {shape(w) for w in different if len(w) >= 4}
    if len(keys) != 1:
        return None
    key = next(iter(keys))
    supported = {w for w in native_words if shape(w) == key}
    if len(supported) != 1:
        return None
    word = next(iter(supported))
    if (word in a) == (word in b):
        return None
    return first if word in a else second


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


def _punctuation_overlaps_native_glyph(line, box, existing, native):
    """Locate a partial glyph reading without promoting it to a new cell.

    Tiny punctuation OCR boxes can include mostly vertical whitespace. Require
    actual vertical overlap and horizontal containment within one known glyph;
    spaces between glyphs and detached signs are not matching evidence. The
    normal disagreement path retains the complete native and raw OCR readings.
    """
    if line.text.strip() not in {".", ",", ":", ";"} or existing.uncertain:
        return False
    if min(box[3], existing.y1 / native.height) <= max(
        box[1], existing.y0 / native.height
    ):
        return False
    return any(
        not existing.text[start:end].isspace()
        and left / native.width <= box[0] < box[2] <= right / native.width
        for start, end, left, right in existing.glyph_spans
    )


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
    if any(line.uncertain for line in layout.lines):
        reasons.append("uncertain-native-glyphs")
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
    if any(obj.object_type == "vector-text" for obj in layout.objects):
        reasons.append("unmapped-vector-text")
    return reasons


def _similar(first: str, second: str, threshold: float) -> bool:
    # Missing/privately mapped glyphs can hide a meaningful chemical symbol.
    # Fuzzy agreement must not discard the OCR reading that recovers it.
    if any(
        c == "\ufffd" or unicodedata.category(c) in {"Cc", "Cs", "Co"}
        for c in first + second
    ) and _normalized_text(first) != _normalized_text(second):
        return False
    if _agreement(first, second) < threshold:
        return False

    # A nearly identical sentence may still disagree on a unit, sign or '%'.
    # In numeric evidence, only spacing and sentence-ending punctuation may be
    # ignored when suppressing an alternative reading. Preserve case (mA != MA).
    # Unit-only headers, chemical labels and negation can be meaningful even
    # without digits (mA/MA, Co/CO, R/S). Fuzzy spelling is not corroboration.
    return literal_reading_key(first).rstrip(".,;:!。；，！") == literal_reading_key(
        second
    ).rstrip(".,;:!。；，！") and _number_signature(first) == _number_signature(second)


def _agreement(first: str, second: str) -> float:
    left = _normalized_text(first)
    right = _normalized_text(second)
    if not left or not right:
        return 0.0
    return (
        1.0
        if left == right
        else SequenceMatcher(None, left, right, autojunk=False).ratio()
    )


def _number_signature(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).replace("−", "-")
    return [
        re.sub(r"\s+", "", number)
        for number in re.findall(r"[+\-]?\s*\d+(?:\.\d+)?", normalized)
    ]


def _fits_damaged_native(native: str, reading: str) -> bool:
    """Use surviving text and one placeholder per missing native glyph.

    This ranks complete OCR readings; it never fills a missing value itself.
    A match supports character count, not the identity of an unknown digit.
    """
    native = literal_reading_key(native)
    reading = literal_reading_key(reading)
    missing = {"\x00", "\ufffd"}
    if (
        not any(c in missing for c in native)
        or sum(c.isalnum() for c in native if c not in missing) < 8
        or not any(c.isdigit() for c in reading)
        or any(c in missing for c in reading)
    ):
        return False
    pattern = "".join("." if c in missing else re.escape(c) for c in native)
    return re.fullmatch(pattern, reading) is not None


def _engine_id(backend: object) -> str:
    return (
        getattr(backend, "evidence_engine_id", None)
        or f"{getattr(backend, 'name')}@{getattr(backend, 'version')}"
    )


def _preserves_visible_native(native: str, reading: str) -> bool:
    """Require surviving text in order; unknown glyphs are not a spelling rule."""
    left = literal_reading_key(native)
    right = literal_reading_key(reading)
    left, right = left.removesuffix("."), right.removesuffix(".")
    parts = re.split(r"[\x00\ufffd\ue000-\uf8ff]+", left)
    cursor = 0
    for index, part in enumerate(parts):
        if not part:
            continue
        found = right.find(part, cursor)
        if found < 0 or (index == 0 and found != 0):
            return False
        cursor = found + len(part)
    return not parts[-1] or cursor == len(right)


def _backend_execution_identity(backend: object) -> dict[str, object]:
    identity: dict[str, object] = {
        "name": str(getattr(backend, "name")),
        "version": str(getattr(backend, "version")),
    }
    components = getattr(backend, "execution_identity", None)
    if components is not None:
        identity["components"] = components
    return identity


def _optional_failure_reason(exc: Exception) -> str:
    detail = str(exc).casefold()
    if isinstance(exc, TimeoutError) or "timed out" in detail:
        return "TIMEOUT"
    if "raster budget exceeded" in detail or "resource limit" in detail:
        return "RESOURCE_LIMIT"
    if "executable is unavailable" in detail or "optional dependencies" in detail:
        return "DEPENDENCY_UNAVAILABLE"
    if isinstance(exc, ValueError):
        return "INVALID_OUTPUT"
    return "BACKEND_ERROR"


def _local_glyph_context(
    line: LayoutLine, layout: PageLayout
) -> list[tuple[float, float]]:
    """Use exact native glyph provenance to OCR only the affected word context."""
    if any(
        c == "\ufffd" or unicodedata.category(c) in {"Cc", "Cs", "Co"}
        for c in line.text
    ):
        # This line is still unreadable, unlike a font-verified recovered unit.
        # A tiny word crop can truncate the only useful OCR reading of it.
        return []
    warning = next(
        (
            w
            for w in layout.warnings
            if w["code"] == "NATIVE_GLYPH_CONTEXT"
            and w.get("after") == line.text
            and w.get("bbox") == [line.x0, line.y0, line.x1, line.y1]
        ),
        None,
    )
    if warning is None or not line.glyph_spans:
        return []
    if any(
        not any(a <= offset < b for a, b, _, _ in line.glyph_spans)
        for offset in warning["text_offsets"]
    ):
        return []  # Missing provenance cannot justify a smaller OCR scope.
    words = list(re.finditer(r"\S+", line.text))
    selected = set()
    for index, word in enumerate(words):
        if any(
            word.start() <= offset < word.end() for offset in warning["text_offsets"]
        ):
            selected.update(range(max(0, index - 1), min(len(words), index + 2)))
    runs = []
    for index in sorted(selected):
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    regions = []
    for run in runs:
        begin, end = words[run[0]].start(), words[run[-1]].end()
        glyphs = [
            (x0, x1) for a, b, x0, x1 in line.glyph_spans if a < end and b > begin
        ]
        if glyphs:
            regions.append(
                (
                    min(g[0] for g in glyphs) / layout.width,
                    max(g[1] for g in glyphs) / layout.width,
                )
            )
    return regions


class AdaptiveOcrBackend:
    """Preserve native text and add OCR only where positioned evidence is absent."""

    name = "adaptive-native-ocr"
    version = "1.10.4"

    def __init__(
        self,
        *,
        native_backend: ExtractionBackend | None = None,
        ocr_backends: Sequence[ExtractionBackend] = (),
        specialist_backends: Sequence[RegionExtractionBackend] = (),
        config: AdaptiveOcrConfig | None = None,
    ) -> None:
        self.native_backend = native_backend or LayoutPdfBackend()
        self.ocr_backends = tuple(ocr_backends)
        self.specialist_backends = tuple(specialist_backends)
        self.config = config or AdaptiveOcrConfig()

    @property
    def execution_identity(self) -> dict[str, object]:
        return {
            "native": _backend_execution_identity(self.native_backend),
            "ocr": [_backend_execution_identity(item) for item in self.ocr_backends],
            "specialists": [
                _backend_execution_identity(item) for item in self.specialist_backends
            ],
            "config": asdict(self.config),
        }

    def extract_page(self, page: Any, page_number: int) -> PageLayout:
        native = self.native_backend.extract_page(page, page_number)
        validate_page_layout(native, expected_page=page_number)
        reasons = _trigger_reasons(native, self.config)
        # When a localized glyph is the only OCR trigger, compare that region.
        # Sparse, damaged and image-heavy pages still receive full-page OCR.
        glyph_check_only = reasons == ["uncertain-native-glyphs"]
        local_ocr_regions = []
        if reasons and set(reasons) <= {
            "uncertain-native-glyphs",
            "unanchored-image-text-candidate",
            "unmapped-vector-text",
        }:
            # The trigger is local on a text-rich native page. Mask readable
            # prose *before recognition*, so unrelated OCR errors are never
            # manufactured as competing readings. Keep every painted image,
            # including images with a few native labels, and every damaged line.
            local_ocr_regions.extend(
                PageRegion("figure", item.bbox, "painted image needs local OCR")
                for item in native.objects
                if item.object_type in {"image", "vector-text"}
                and item.bbox is not None
                and _area(item.bbox) > 0
            )
            for line in native.lines:
                if line.uncertain:
                    x0, y0, x1, y1 = _line_bbox(line, native)
                    pad = (y1 - y0) * 0.35
                    spans = _local_glyph_context(line, native)
                    for left, right in spans or [(x0, x1)]:
                        local_ocr_regions.append(
                            PageRegion(
                                "text",
                                (
                                    max(0, left - pad),
                                    max(0, y0 - pad),
                                    min(1, right + pad),
                                    min(1, y1 + pad),
                                ),
                                "uncertain native glyphs need local OCR",
                            )
                        )
        regions = [
            *_image_regions_without_text(native, self.config),
            *_formula_regions(native),
        ]
        warnings = list(native.warnings)
        candidate_layouts: list[PageLayout] = []

        def add_optional(
            backend: object, extract, *, glyph_check: bool = False
        ) -> None:
            engine = _engine_id(backend)
            try:
                extracted = extract()
                validate_page_layout(extracted, expected_page=page_number)
                if not (
                    math.isclose(extracted.width, native.width, abs_tol=0.01)
                    and math.isclose(extracted.height, native.height, abs_tol=0.01)
                ):
                    raise ValueError(
                        "backend page dimensions differ from native geometry"
                    )
            except Exception as exc:
                warnings.append(
                    {
                        "code": "OPTIONAL_BACKEND_FAILED",
                        "detail": (
                            f"page {page_number}: {engine}: {type(exc).__name__}: "
                            f"{safe_exception_detail(exc)}"
                        ),
                        "page": page_number,
                        "stage": "optional-extraction",
                        "backend": engine,
                        "reason": _optional_failure_reason(exc),
                        "degraded": True,
                    }
                )
                return
            if glyph_check:
                boxes = [
                    _line_bbox(line, native) for line in native.lines if line.uncertain
                ]
                # A chart can have a few native labels yet still need OCR for
                # other visible values. Preserve its readings and conflicts.
                boxes.extend(
                    item.bbox
                    for item in native.objects
                    if item.object_type == "image"
                    and item.bbox is not None
                    and _area(item.bbox) >= self.config.unanchored_image_min_area
                )
                original_count = len(extracted.lines)
                extracted = replace(
                    extracted,
                    lines=tuple(
                        line
                        for line in extracted.lines
                        if any(
                            _overlap(_line_bbox(line, extracted), box)
                            >= self.config.bbox_overlap_threshold
                            for box in boxes
                        )
                    ),
                )
                warnings.append(
                    {
                        "code": "OCR_GLYPH_CHECK_SCOPED",
                        "page": page_number,
                        "detail": f"{engine}: retained {len(extracted.lines)} of {original_count} OCR lines overlapping uncertain native glyphs or images; no other OCR trigger on this page",
                    }
                )
            warnings.extend(extracted.warnings)
            candidate_layouts.append(extracted)

        # Small panel labels can fall below the full-page image-area trigger.
        # Read only supported footer regions, without another full-page pass.
        if any(obj.object_type == "image" for obj in native.objects):
            for backend in self.ocr_backends:
                read_labels = getattr(backend, "extract_image_annotations", None)
                if callable(read_labels):
                    add_optional(
                        backend,
                        lambda read_labels=read_labels: read_labels(page, page_number),
                    )

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
                extract_regions = getattr(backend, "extract_regions", None)
                if local_ocr_regions and callable(extract_regions):
                    add_optional(
                        backend,
                        lambda extract_regions=extract_regions: extract_regions(
                            page,
                            page_number,
                            tuple(local_ocr_regions),
                            native_layout=native,
                        ),
                    )
                    continue
                add_optional(
                    backend,
                    lambda backend=backend: backend.extract_page(page, page_number),
                    glyph_check=glyph_check_only,
                )

        for region in regions:
            for backend in self.specialist_backends:
                if region.region_type not in backend.supported_regions:
                    continue

                def extract_region(backend=backend, region=region):
                    extracted = backend.extract_region(page, page_number, region)
                    return replace(
                        extracted,
                        lines=tuple(
                            replace(line, content_region=region.region_type)
                            for line in extracted.lines
                        ),
                    )

                add_optional(
                    backend,
                    extract_region,
                )

        lines, merge_warnings = self._merge(native, candidate_layouts)
        warnings.extend(merge_warnings)
        if not native.lines and lines:
            # A successful OCR-only extraction has handled the image-only input.
            # Keep OCR_TRIGGERED and any actual engine/quality warnings.
            warnings = [w for w in warnings if w["code"] != "IMAGE_DOMINANT_PAGE"]
        return replace(native, lines=lines, warnings=tuple(warnings))

    def _merge(
        self, native: PageLayout, candidate_layouts: Sequence[PageLayout]
    ) -> tuple[tuple[LayoutLine, ...], list[dict[str, object]]]:
        native_lines = list(native.lines)
        supplements: list[LayoutLine] = []
        native_words = set(
            re.findall(r"[A-Za-z]{4,}", " ".join(line.text for line in native.lines))
        )
        candidate_layouts, warnings = corroborate_chinese(
            native, list(candidate_layouts)
        )
        image_boxes = [
            obj.bbox
            for obj in native.objects
            if obj.object_type == "image" and obj.bbox is not None
        ]
        native_first = (
            sum(len(line.text.strip()) for line in native.lines)
            >= self.config.min_native_characters
            and _union_area(image_boxes) < self.config.image_coverage_trigger
        )
        image_regions = [
            obj.bbox
            for obj in native.objects
            if obj.object_type == "image"
            and obj.bbox is not None
            and self.config.unanchored_image_min_area
            <= _area(obj.bbox)
            < self.config.image_coverage_trigger
        ]
        image_regions.extend(
            obj.bbox
            for obj in native.objects
            if obj.object_type == "vector-text" and obj.bbox is not None
        )

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
                if line.content_region in {"ocr-alternative", "native-alternative"}:
                    # A backend may preserve the raw OCR behind an explicitly
                    # derived reading. Such evidence cannot become a primary
                    # merely because it arrived before that reading.
                    supplements.append(line)
                    continue
                if line.extraction_method in _LAYOUT_ASSOCIATIONS:
                    # A relationship spans multiple printed labels. Its box is
                    # evidence scope, not the extent of one competing text line.
                    # Keep it uncertain and compare OCR against its individual
                    # source readings below, never against the relationship text.
                    supplements.append(replace(line, uncertain=True))
                    continue
                covering = [
                    existing
                    for existing in native.lines
                    if _overlap(line_box, _line_bbox(existing, native))
                    >= self.config.bbox_overlap_threshold
                ]
                if (
                    native_first
                    and line.content_region in {"body", "ocr-alternative"}
                    and covering
                    and all(
                        not existing.uncertain
                        and _suspicious_character_ratio((existing,)) == 0
                        for existing in covering
                    )
                ):
                    intersections = [
                        (
                            max(line_box[0], b[0]),
                            max(line_box[1], b[1]),
                            min(line_box[2], b[2]),
                            min(line_box[3], b[3]),
                        )
                        for b in (_line_bbox(existing, native) for existing in covering)
                    ]
                    if _union_area(intersections) >= _area(line_box) * 0.8:
                        # OCR was requested for gaps/uncertain glyphs on this
                        # born-digital page. Do not turn readable native prose
                        # into conflicts merely because the page-wide OCR ran.
                        # Image-dominant scans never take this path.
                        continue

                # OCR can combine table fragments or two native lines. Compare
                # their full spatially corresponding reading before declaring
                # disagreement with just one of those fragments.
                contained = [
                    (index, existing)
                    for index, existing in enumerate(native_lines)
                    if line_box[0]
                    <= (existing.x0 + existing.x1) / (2 * native.width)
                    <= line_box[2]
                    and line_box[1]
                    <= (existing.y0 + existing.y1) / (2 * native.height)
                    <= line_box[3]
                ]
                contained.sort(
                    key=lambda item: (
                        -round(
                            (item[1].y0 + item[1].y1)
                            / (2 * max(line.font_size * 0.5, 1))
                        ),
                        item[1].x0,
                    )
                )
                joined = " ".join(existing.text for _, existing in contained)
                if len(contained) > 1 and _similar(
                    joined, line.text, self.config.text_similarity_threshold
                ):
                    for index, existing in contained:
                        native_lines[index] = replace(
                            existing,
                            source_engines=tuple(
                                dict.fromkeys(
                                    existing.source_engines + line.source_engines
                                )
                            ),
                            engine_agreement=_agreement(joined, line.text),
                        )
                    continue
                if line.content_region == "body" and any(
                    _overlap(line_box, region) >= self.config.bbox_overlap_threshold
                    for region in image_regions
                ):
                    # Chart OCR often misses small tick signs despite a high
                    # reported score. Keep it separate from prose/measurements.
                    line = replace(line, content_region="figure", uncertain=True)

                native_match = max(
                    (
                        (index, existing)
                        for index, existing in enumerate(native_lines)
                        if _overlap(line_box, _line_bbox(existing, native))
                        >= self.config.bbox_overlap_threshold
                        or _punctuation_overlaps_native_glyph(
                            line, line_box, existing, native
                        )
                    ),
                    key=lambda item: (
                        _overlap(line_box, _line_bbox(item[1], native)),
                        _agreement(item[1].text, line.text),
                    ),
                    default=None,
                )
                if native_match is not None:
                    index, existing = native_match
                    original = native.lines[index]
                    native_box = _line_bbox(existing, native)
                    comparable_area = (
                        0.5 <= _area(line_box) / max(_area(native_box), 1e-12) <= 2
                    )
                    covers_native_line = (
                        max(
                            0,
                            min(line_box[2], native_box[2])
                            - max(line_box[0], native_box[0]),
                        )
                        / max(native_box[2] - native_box[0], 1e-12)
                        >= 0.8
                    )
                    recovered, substitutions = recover_word_glyphs(existing, line)
                    if (
                        substitutions
                        and existing.uncertain
                        and confidence >= 0.9
                        and comparable_area
                        and covers_native_line
                        and _number_signature(existing.text)
                        == _number_signature(line.text)
                        and _agreement(existing.text, line.text) >= 0.9
                    ):
                        native_lines[index] = replace(
                            existing,
                            text=recovered,
                            extraction_method="native-local-ocr-glyph-recovery",
                            source_engines=tuple(
                                dict.fromkeys(
                                    existing.source_engines + line.source_engines
                                )
                            ),
                            glyph_spans=(),
                            uncertain=True,
                        )
                        supplements.extend(
                            (
                                replace(
                                    existing,
                                    content_region="native-alternative",
                                    uncertain=True,
                                ),
                                replace(
                                    line,
                                    content_region="ocr-alternative",
                                    uncertain=True,
                                ),
                            )
                        )
                        for start, end, letters in substitutions:
                            span = next(
                                s for s in existing.glyph_spans if s[0] <= start < s[1]
                            )
                            warnings.append(
                                {
                                    "code": "OCR_GLYPH_WORD_RECOVERED",
                                    "page": native.page,
                                    "bbox": [
                                        span[2] / native.width,
                                        existing.y0 / native.height,
                                        span[3] / native.width,
                                        existing.y1 / native.height,
                                    ],
                                    "detail": "An explicit missing native letter glyph is filled from one positioned OCR word with unchanged surrounding letters. All other native text is preserved; the original and complete OCR remain alternatives.",
                                    "before": existing.text[start:end],
                                    "after": letters,
                                    "native_text": existing.text,
                                    "ocr_text": line.text,
                                }
                            )
                        continue
                    if (
                        existing.text != original.text
                        and confidence >= 0.8
                        and comparable_area
                        and covers_native_line
                        and _fits_damaged_native(original.text, line.text)
                        and not _fits_damaged_native(original.text, existing.text)
                    ):
                        # A lost repeated digit can survive as separate missing
                        # glyphs in the PDF. Prefer the whole OCR reading that
                        # also fits these positions and every surviving letter.
                        # Both readings remain uncertain, even at high scores.
                        native_lines[index] = replace(line, uncertain=True)
                        supplements.append(
                            replace(
                                existing,
                                content_region="ocr-alternative",
                                uncertain=True,
                            )
                        )
                        warnings.append(
                            {
                                "code": "OCR_PRIMARY_RECOVERED",
                                "detail": f"page {native.page}: OCR primary now matches surviving native text and missing-glyph count near bbox {tuple(round(v, 3) for v in line_box)}",
                            }
                        )
                    elif (
                        _suspicious_character_ratio((existing,))
                        > self.config.max_suspicious_character_ratio
                        and _suspicious_character_ratio((line,)) == 0
                        and confidence >= 0.8
                        and comparable_area
                        and covers_native_line
                        and (
                            _number_signature(existing.text)
                            == _number_signature(line.text)
                            or _fits_damaged_native(existing.text, line.text)
                        )
                        and _agreement(existing.text, line.text) >= 0.5
                        and _preserves_visible_native(existing.text, line.text)
                        and not any(
                            warning.get("code") == "NATIVE_UNIT_MAPPING_CORRECTED"
                            and _normalized_text(str(warning.get("after", "")))
                            == _normalized_text(existing.text)
                            for warning in native.warnings
                        )
                    ):
                        # A corrupt hidden text layer must not remain the main
                        # reading when positioned OCR recovers readable text.
                        # Keep the original explicitly as an alternative.
                        native_lines[index] = replace(line, uncertain=True)
                        supplements.append(
                            replace(
                                existing,
                                uncertain=True,
                                content_region="native-alternative",
                            )
                        )
                        warnings.append(
                            {
                                "code": "OCR_PRIMARY_RECOVERED",
                                "detail": f"page {native.page}: readable OCR replaces a corrupt primary text line; original retained near bbox {tuple(round(v, 3) for v in line_box)}",
                            }
                        )
                    elif _similar(
                        existing.text,
                        line.text,
                        self.config.text_similarity_threshold,
                    ) and _number_signature(existing.text) == _number_signature(
                        line.text
                    ):
                        native_lines[index] = replace(
                            existing,
                            source_engines=tuple(
                                dict.fromkeys(
                                    existing.source_engines + line.source_engines
                                )
                            ),
                            extraction_confidence=existing.extraction_confidence,
                            engine_agreement=_agreement(existing.text, line.text),
                            content_region=(
                                line.content_region
                                if line.content_region != "body"
                                else existing.content_region
                            ),
                        )
                    else:
                        native_lines[index] = replace(existing, uncertain=True)
                        # Preserve both readings when they disagree. Dropping OCR
                        # here hides recovered signs/numbers in a corrupt text layer.
                        supplements.append(
                            replace(
                                line, uncertain=True, content_region="ocr-alternative"
                            )
                        )
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

                supplement_match = max(
                    (
                        (index, existing)
                        for index, existing in enumerate(supplements)
                        if existing.extraction_method not in _LAYOUT_ASSOCIATIONS
                        if not existing.content_region.endswith("alternative")
                        or existing.extraction_method.endswith("+association-source")
                        if _overlap(line_box, _line_bbox(existing, native))
                        >= self.config.bbox_overlap_threshold
                    ),
                    key=lambda item: (
                        _agreement(item[1].text, line.text),
                        _overlap(line_box, _line_bbox(item[1], native)),
                    ),
                    default=None,
                )
                if supplement_match is None:
                    supplements.append(line)
                    continue
                index, existing = supplement_match
                supported = _native_supported_label(existing, line, native_words)
                if supported is not None:
                    rejected = line if supported is existing else existing
                    supplements[index] = replace(supported, uncertain=True)
                    supplements.append(
                        replace(
                            rejected, uncertain=True, content_region="ocr-alternative"
                        )
                    )
                    warnings.append(
                        {
                            "code": "OCR_LABEL_NATIVE_CORROBORATED",
                            "page": native.page,
                            "bbox": list(_line_bbox(supported, native)),
                            "detail": "Selected an existing OCR label whose I/l spelling is unique in native page text; competing reading retained.",
                            "selected": supported.text,
                            "alternative": rejected.text,
                        }
                    )
                    continue
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
                        extraction_method=(
                            existing.extraction_method
                            if existing.extraction_method.endswith(
                                "+association-source"
                            )
                            else "ocr-consensus"
                        ),
                        content_region=(
                            existing.content_region
                            if existing.extraction_method.endswith(
                                "+association-source"
                            )
                            else preferred.content_region
                        ),
                        extraction_confidence=preferred.extraction_confidence,
                        engine_agreement=_agreement(existing.text, line.text),
                        source_engines=tuple(
                            dict.fromkeys(existing.source_engines + line.source_engines)
                        ),
                        uncertain=existing.uncertain or line.uncertain,
                    )
                else:
                    warnings.append(
                        {
                            "code": "OCR_ENGINE_DISAGREEMENT",
                            "page": native.page,
                            "bbox": list(line_box),
                            "detail": (
                                f"page {native.page}: OCR engines disagree near bbox "
                                f"{tuple(round(v, 3) for v in line_box)}"
                            ),
                        }
                    )
                    supplements[index] = replace(existing, uncertain=True)
                    supplements.append(
                        replace(line, uncertain=True, content_region="ocr-alternative")
                    )

        if supplements:
            warnings.append(
                {
                    "code": "OCR_TEXT_SUPPLEMENTED",
                    "detail": f"page {native.page}: retained {len(supplements)} OCR gap/alternative lines",
                }
            )
        # Coalesce exact positioned readings even when one took the primary or
        # figure path. Do not fold case, superscripts, signs or number spacing.
        unique: list[LayoutLine] = []
        removed = 0
        for line in native_lines + supplements:
            box = _line_bbox(line, native)
            duplicate = next(
                (
                    i
                    for i, old in enumerate(unique)
                    if re.sub(r"\s+", "", old.text) == re.sub(r"\s+", "", line.text)
                    and _number_signature(old.text) == _number_signature(line.text)
                    and _overlap(box, _line_bbox(old, native)) >= 0.85
                    and 0.5
                    <= _area(box) / max(_area(_line_bbox(old, native)), 1e-12)
                    <= 2
                ),
                None,
            )
            if duplicate is None:
                unique.append(line)
                continue
            old = unique[duplicate]
            preferred = (
                line
                if old.content_region.endswith("alternative")
                and not line.content_region.endswith("alternative")
                else old
            )
            unique[duplicate] = replace(
                preferred,
                source_engines=tuple(
                    dict.fromkeys(old.source_engines + line.source_engines)
                ),
                uncertain=old.uncertain or line.uncertain,
            )
            removed += 1
        if removed:
            warnings.append(
                {
                    "code": "OCR_DUPLICATE_COALESCED",
                    "detail": f"page {native.page}: coalesced {removed} exact positioned readings; source engines and uncertainty retained",
                }
            )
        # Identical conflicts from two engines are one review location. The
        # coalesced alternative above still retains both engine identities.
        seen_conflicts = set()
        distinct_warnings = []
        for warning in warnings:
            if warning.get("code") == "OCR_ENGINE_DISAGREEMENT":
                key = warning.get("detail")
                if key in seen_conflicts:
                    continue
                seen_conflicts.add(key)
            distinct_warnings.append(warning)
        return tuple(unique), distinct_warnings
