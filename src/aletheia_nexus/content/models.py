"""Typed intermediate representation shared by parser backends and stages."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from aletheia_nexus.content.geometry import CANONICAL_COORDINATE_SYSTEM


@dataclass(frozen=True)
class LayoutLine:
    """One positioned native-text line before semantic block assembly."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    extraction_method: str = "pypdf-content-stream"
    extraction_confidence: float = 1.0
    source_engines: tuple[str, ...] = ()
    engine_agreement: float | None = None
    content_region: str = "body"
    uncertain: bool = False
    bold: bool = False


@dataclass(frozen=True)
class PageObject:
    """A non-text PDF object that can be linked without extracting its bytes."""

    object_type: str
    name: str
    width: int | None = None
    height: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PageRegion:
    """A normalized page region routed to a specialized extractor."""

    region_type: str
    bbox: tuple[float, float, float, float]
    reason: str


@dataclass(frozen=True)
class PageLayout:
    """Backend-neutral page output consumed by parser stages."""

    page: int
    width: float
    height: float
    coordinate_system: str = CANONICAL_COORDINATE_SYSTEM
    media_box: tuple[float, float, float, float] | None = None
    crop_box: tuple[float, float, float, float] | None = None
    rotation: int = 0
    lines: tuple[LayoutLine, ...] = ()
    objects: tuple[PageObject, ...] = ()
    warnings: tuple[dict[str, object], ...] = ()


def validate_page_layout(layout: object, *, expected_page: int | None = None) -> None:
    """Fail closed on malformed extraction-backend geometry or provenance."""

    if not isinstance(layout, PageLayout):
        raise ValueError("backend output must be a PageLayout")
    if (
        isinstance(layout.page, bool)
        or not isinstance(layout.page, int)
        or layout.page < 1
    ):
        raise ValueError("page number must be a positive integer")
    if expected_page is not None and layout.page != expected_page:
        raise ValueError("backend returned a different page number")
    if layout.coordinate_system != CANONICAL_COORDINATE_SYSTEM:
        raise ValueError("backend returned an unsupported coordinate system")
    if (
        any(isinstance(value, bool) for value in (layout.width, layout.height))
        or not all(
            isinstance(value, (int, float)) for value in (layout.width, layout.height)
        )
        or not all(
            math.isfinite(float(value)) for value in (layout.width, layout.height)
        )
        or layout.width <= 0
        or layout.height <= 0
    ):
        raise ValueError("page dimensions must be positive finite numbers")
    if layout.rotation not in {0, 90, 180, 270}:
        raise ValueError("page rotation must be 0, 90, 180, or 270")
    for label, box in (("media_box", layout.media_box), ("crop_box", layout.crop_box)):
        if box is not None and (
            len(box) != 4
            or any(isinstance(value, bool) for value in box)
            or not all(isinstance(value, (int, float)) for value in box)
            or not all(math.isfinite(float(value)) for value in box)
            or box[2] <= box[0]
            or box[3] <= box[1]
        ):
            raise ValueError(f"{label} must be a finite ordered rectangle")
    for index, line in enumerate(layout.lines):
        values = (line.x0, line.y0, line.x1, line.y1, line.font_size)
        if (
            not isinstance(line.text, str)
            or not line.text.strip()
            or any(isinstance(value, bool) for value in values)
            or not all(isinstance(value, (int, float)) for value in values)
            or not all(math.isfinite(float(value)) for value in values)
            or line.x0 < 0
            or line.y0 < 0
            or line.x1 <= line.x0
            or line.y1 <= line.y0
            or line.x1 > layout.width + 1e-6
            or line.y1 > layout.height + 1e-6
            or line.font_size <= 0
        ):
            raise ValueError(f"lines[{index}] has invalid canonical geometry")
        if (
            isinstance(line.extraction_confidence, bool)
            or not isinstance(line.extraction_confidence, (int, float))
            or not math.isfinite(float(line.extraction_confidence))
            or not 0 <= line.extraction_confidence <= 1
        ):
            raise ValueError(f"lines[{index}] has invalid confidence")
        if line.engine_agreement is not None and (
            isinstance(line.engine_agreement, bool)
            or not isinstance(line.engine_agreement, (int, float))
            or not math.isfinite(float(line.engine_agreement))
            or not 0 <= line.engine_agreement <= 1
        ):
            raise ValueError(f"lines[{index}] has invalid engine agreement")
        if not isinstance(line.extraction_method, str) or not line.extraction_method:
            raise ValueError(f"lines[{index}] needs an extraction method")
        if (
            not isinstance(line.source_engines, tuple)
            or any(
                not isinstance(item, str) or not item for item in line.source_engines
            )
            or len(line.source_engines) != len(set(line.source_engines))
        ):
            raise ValueError(f"lines[{index}] has invalid source engines")
        if not isinstance(line.content_region, str) or not line.content_region:
            raise ValueError(f"lines[{index}] has invalid content region")
        if not isinstance(line.uncertain, bool) or not isinstance(line.bold, bool):
            raise ValueError(f"lines[{index}] has invalid boolean provenance")
    for index, item in enumerate(layout.objects):
        if (
            not isinstance(item.object_type, str)
            or not item.object_type
            or not isinstance(item.name, str)
            or not item.name
        ):
            raise ValueError(f"objects[{index}] needs a type and name")
        for label, value in (("width", item.width), ("height", item.height)):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"objects[{index}].{label} must be positive")
        if item.bbox is None:
            continue
        if (
            len(item.bbox) != 4
            or any(isinstance(value, bool) for value in item.bbox)
            or not all(isinstance(value, (int, float)) for value in item.bbox)
            or not all(math.isfinite(float(value)) for value in item.bbox)
            or not 0 <= item.bbox[0] < item.bbox[2] <= 1
            or not 0 <= item.bbox[1] < item.bbox[3] <= 1
        ):
            raise ValueError(f"objects[{index}] has invalid normalized bbox")
    for index, warning in enumerate(layout.warnings):
        if not isinstance(warning, dict) or not all(
            isinstance(warning.get(key), str) and warning.get(key)
            for key in ("code", "detail")
        ):
            raise ValueError(f"warnings[{index}] needs code and detail strings")


@dataclass
class PipelineContext:
    """Mutable per-request state; no state is shared between parser runs."""

    source: object
    reader: object
    config: object
    created_at: str
    backend: object
    layouts: dict[int, PageLayout] = field(default_factory=dict)
    blocks: list[dict[str, object]] = field(default_factory=list)
    anchors: list[dict[str, object]] = field(default_factory=list)
    sections: list[dict[str, object]] = field(default_factory=list)
    references: list[dict[str, object]] = field(default_factory=list)
    figures: list[dict[str, object]] = field(default_factory=list)
    tables: list[dict[str, object]] = field(default_factory=list)
    quality: dict[str, object] = field(default_factory=dict)
    status: str = "FAILED"
    warnings: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    stopped_early: bool = False
    suppressed_page_furniture: int = 0
    unassociated_image_resources: int = 0
