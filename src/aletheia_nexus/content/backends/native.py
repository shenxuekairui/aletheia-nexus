"""pypdf native-text and resource backend."""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from aletheia_nexus.content.geometry import PageGeometry
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject


@dataclass
class _Fragment:
    text: str
    x: float
    y: float
    font_size: float
    bold: bool


def _font_is_bold(font_dictionary: dict[str, object] | None) -> bool:
    if not font_dictionary:
        return False
    names = [str(font_dictionary.get("/BaseFont", ""))]
    descriptor = _dereference(font_dictionary.get("/FontDescriptor"))
    if hasattr(descriptor, "get"):
        names.append(str(descriptor.get("/FontName", "")))
    normalized = " ".join(names).casefold()
    return any(
        marker in normalized
        for marker in ("bold", "black", "heavy", "semibold", "demi")
    )


def _matrix(tm: list[float], cm: list[float]) -> list[float]:
    return [
        tm[0] * cm[0] + tm[1] * cm[2],
        tm[0] * cm[1] + tm[1] * cm[3],
        tm[2] * cm[0] + tm[3] * cm[2],
        tm[2] * cm[1] + tm[3] * cm[3],
        tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
        tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
    ]


def _text_lines(page: Any, geometry: PageGeometry) -> tuple[LayoutLine, ...]:
    fragments: list[_Fragment] = []

    def visitor(
        text: str,
        cm: list[float],
        tm: list[float],
        font_dictionary: dict[str, object] | None,
        font_size: float,
    ) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        combined = _matrix(tm, cm)
        x, y = combined[4], combined[5]
        scale = math.hypot(combined[2], combined[3]) or math.hypot(
            combined[0], combined[1]
        )
        effective_size = font_size * (scale or 1.0)
        if not all(value == value for value in (x, y, effective_size)):
            return
        fragments.append(
            _Fragment(
                text=cleaned,
                x=float(x),
                y=float(y),
                font_size=max(float(effective_size), 1.0),
                bold=_font_is_bold(font_dictionary),
            )
        )

    page.extract_text(visitor_text=visitor)
    fragments.sort(key=lambda item: (-item.y, item.x, item.text))

    rows: list[list[_Fragment]] = []
    current_row: list[_Fragment] = []
    current_y = 0.0
    for fragment in fragments:
        tolerance = max(2.0, fragment.font_size * 0.45)
        if current_row and abs(current_y - fragment.y) > tolerance:
            rows.append(current_row)
            current_row = []
        current_row.append(fragment)
        if len(current_row) == 1:
            current_y = fragment.y
        else:
            current_y += (fragment.y - current_y) / len(current_row)
    if current_row:
        rows.append(current_row)

    segmented_rows: list[list[_Fragment]] = []
    page_left = float(page.cropbox.left)
    page_width = float(page.cropbox.width)
    column_boundary = page_left + page_width * 0.5
    for row in rows:
        row.sort(key=lambda item: item.x)
        segment: list[_Fragment] = []
        right_edge = None
        for fragment in row:
            crossed_column_boundary = (
                segment
                and segment[0].x < page_left + page_width * 0.4
                and fragment.x >= column_boundary
            )
            if (
                segment
                and right_edge is not None
                and (
                    crossed_column_boundary
                    or fragment.x - right_edge > max(24.0, fragment.font_size * 3)
                )
            ):
                segmented_rows.append(segment)
                segment = []
            segment.append(fragment)
            right_edge = fragment.x + fragment.font_size * 0.45 * len(fragment.text)
        if segment:
            segmented_rows.append(segment)

    lines: list[LayoutLine] = []
    for row in segmented_rows:
        text_parts: list[str] = []
        right_edge = None
        for fragment in row:
            estimated_width = max(fragment.font_size * 0.45 * len(fragment.text), 1)
            if (
                right_edge is not None
                and fragment.x - right_edge > fragment.font_size * 0.2
            ):
                text_parts.append(" ")
            text_parts.append(fragment.text)
            right_edge = fragment.x + estimated_width
        font_size = max(item.font_size for item in row)
        x0 = min(item.x for item in row)
        x1 = max(item.x + item.font_size * 0.45 * len(item.text) for item in row)
        raw_y = min(item.y for item in row)
        x0, y0, x1, y1 = geometry.box_points(
            (x0, raw_y - font_size * 0.25, x1, raw_y + font_size)
        )
        x0 = max(0.0, min(geometry.width, x0))
        y0 = max(0.0, min(geometry.height, y0))
        x1 = max(0.0, min(geometry.width, x1))
        y1 = max(0.0, min(geometry.height, y1))
        if x1 <= x0 or y1 <= y0:
            continue
        lines.append(
            LayoutLine(
                text="".join(text_parts).strip(),
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                font_size=font_size,
                extraction_confidence=1.0,
                source_engines=("pypdf-native-layout@2.2.0",),
                bold=(
                    sum(len(item.text) for item in row if item.bold)
                    >= sum(len(item.text) for item in row) / 2
                ),
            )
        )
    return tuple(lines)


def _dereference(value: Any) -> Any:
    return value.get_object() if hasattr(value, "get_object") else value


def _page_objects(page: Any, geometry: PageGeometry) -> tuple[PageObject, ...]:
    """Record images actually painted on a page, without decoding their bytes."""

    from aletheia_nexus.content.backends.pdf_images import painted_images

    objects = []
    occurrences = {}
    for path, value, matrix, visible, full in painted_images(page):
        bbox = geometry.normalized_box_from_points(
            ((visible[0], visible[1]), (visible[2], visible[3]))
        )
        base_name = "/".join(name.lstrip("/") for name in path)
        occurrence = occurrences.get(base_name, 0) + 1
        occurrences[base_name] = occurrence
        name = base_name if occurrence == 1 else f"{base_name}#{occurrence}"
        objects.append(
            PageObject(
                object_type="image",
                name=name,
                width=int(value["/Width"]),
                height=int(value["/Height"]),
                bbox=tuple(round(item, 6) for item in bbox),
            )
        )
    from aletheia_nexus.content.backends.pdf_rules import painted_rules

    return (*objects, *painted_rules(page, geometry))


class NativePdfBackend:
    """Extract native PDF text and auditable page-resource metadata."""

    name = "pypdf-native-layout"
    version = "2.4.0"

    @property
    def execution_identity(self) -> dict[str, object]:
        try:
            pypdf_version = metadata.version("pypdf")
        except metadata.PackageNotFoundError:
            pypdf_version = "unavailable"
        return {"runtime_dependencies": {"pypdf": pypdf_version}}

    def extract_page(self, page: Any, page_number: int) -> PageLayout:
        from dataclasses import replace

        from aletheia_nexus.content.backends.layout import suspicious_text

        geometry = PageGeometry.from_page(page)
        lines = tuple(
            replace(line, uncertain=True, extraction_confidence=0.5)
            if suspicious_text(line.text)
            else line
            for line in _text_lines(page, geometry)
        )
        return PageLayout(
            page=page_number,
            width=geometry.width,
            height=geometry.height,
            media_box=geometry.media_box,
            crop_box=geometry.crop_box,
            rotation=geometry.rotation,
            lines=lines,
            objects=_page_objects(page, geometry),
            warnings=(
                {
                    "code": "NATIVE_GLYPH_UNCERTAIN",
                    "detail": f"page {page_number}: native text contains missing/ambiguous glyphs",
                    "page": page_number,
                },
            )
            if any(line.uncertain for line in lines)
            else (),
        )
