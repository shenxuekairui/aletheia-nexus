"""Canonical page geometry shared by native, raster, and OCR extraction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

CANONICAL_COORDINATE_SYSTEM = "pdf-cropbox-display-bottom-left-normalized/v1"


@dataclass(frozen=True)
class PageGeometry:
    """Map PDF user-space evidence into the displayed CropBox coordinate space."""

    media_box: tuple[float, float, float, float]
    crop_box: tuple[float, float, float, float]
    rotation: int
    width: float
    height: float

    @classmethod
    def from_page(cls, page: Any) -> "PageGeometry":
        media = tuple(float(value) for value in page.mediabox)
        crop = tuple(float(value) for value in page.cropbox)
        if len(media) != 4 or len(crop) != 4:
            raise ValueError("page boxes must contain four coordinates")
        if not all(math.isfinite(value) for value in (*media, *crop)):
            raise ValueError("page boxes must contain finite coordinates")
        left, bottom, right, top = crop
        raw_width = right - left
        raw_height = top - bottom
        if raw_width <= 0 or raw_height <= 0:
            raise ValueError("CropBox must have positive dimensions")
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        if rotation not in {0, 90, 180, 270}:
            raise ValueError("page rotation must be a multiple of 90 degrees")
        width, height = (
            (raw_height, raw_width)
            if rotation in {90, 270}
            else (raw_width, raw_height)
        )
        return cls(media, crop, rotation, width, height)

    def point(self, x: float, y: float) -> tuple[float, float]:
        """Transform one PDF user-space point into displayed CropBox points."""

        left, bottom, right, top = self.crop_box
        raw_width = right - left
        raw_height = top - bottom
        u, v = x - left, y - bottom
        if self.rotation == 0:
            return u, v
        if self.rotation == 90:
            return v, raw_width - u
        if self.rotation == 180:
            return raw_width - u, raw_height - v
        return raw_height - v, u

    def box_points(
        self, box: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = box
        points = (
            self.point(x0, y0),
            self.point(x0, y1),
            self.point(x1, y0),
            self.point(x1, y1),
        )
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    def normalized_box_from_points(
        self, points: Iterable[tuple[float, float]]
    ) -> tuple[float, float, float, float]:
        transformed = [self.point(x, y) for x, y in points]
        if not transformed:
            raise ValueError("bbox needs at least one point")
        xs = [point[0] / self.width for point in transformed]
        ys = [point[1] / self.height for point in transformed]
        return _normalized_box((min(xs), min(ys), max(xs), max(ys)))


def _normalized_box(
    box: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    values = tuple(max(0.0, min(1.0, float(value))) for value in box)
    return values[0], values[1], values[2], values[3]


def raster_bbox_to_canonical(
    box: tuple[float, float, float, float],
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float]:
    """Map a top-left raster bbox to canonical displayed-page coordinates."""

    if image_width < 1 or image_height < 1:
        raise ValueError("raster dimensions must be positive")
    left, top, right, bottom = box
    return _normalized_box(
        (
            left / image_width,
            1 - bottom / image_height,
            right / image_width,
            1 - top / image_height,
        )
    )
