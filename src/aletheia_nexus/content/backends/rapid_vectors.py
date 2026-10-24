"""Read observed unmapped outlines with the already selected local image OCR."""

from __future__ import annotations

from importlib import metadata

from aletheia_nexus.content.backends.rapid_images import _engine
from aletheia_nexus.content.models import LayoutLine


def read_vector_annotations(image, native):
    regions = []
    for obj in native.objects:
        if obj.object_type != "vector-text" or not obj.bbox:
            continue
        x0, y0, x1, y1 = obj.bbox
        # Include the adjacent short label that the multi-outline detector may
        # not locate. One glyph-height of context does not join experiments.
        pad = min(x1 - x0, y1 - y0)
        regions.append(
            (max(0, x0 - pad), max(0, y0 - pad), min(1, x1 + pad), min(1, y1 + pad))
        )
    if not regions:
        return ()
    result = _engine()(image, use_det=True, use_cls=True)
    if result.boxes is None or result.txts is None:
        return ()
    native_boxes = [
        (
            line.x0 / native.width,
            line.y0 / native.height,
            line.x1 / native.width,
            line.y1 / native.height,
        )
        for line in native.lines
        if not line.uncertain
    ]
    lines = []
    for polygon, text, score in zip(result.boxes, result.txts, result.scores):
        if score < 0.85 or not text.strip():
            continue
        # Model polygons contain numeric scalars such as numpy.float32. Keep the
        # backend's canonical geometry contract and JSON output library-neutral.
        xs, ys = [float(p[0]) for p in polygon], [float(p[1]) for p in polygon]
        box = (
            min(xs) / image.width,
            1 - max(ys) / image.height,
            max(xs) / image.width,
            1 - min(ys) / image.height,
        )
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area <= 0:
            continue

        def overlap(other):
            return max(0, min(box[2], other[2]) - max(box[0], other[0])) * max(
                0, min(box[3], other[3]) - max(box[1], other[1])
            )

        if (
            not any(
                overlap(region)
                >= 0.35 * min(area, (region[2] - region[0]) * (region[3] - region[1]))
                for region in regions
            )
            or sum(overlap(other) for other in native_boxes) >= 0.35 * area
        ):
            continue
        lines.append(
            LayoutLine(
                text=text.strip(),
                x0=max(0, box[0]) * native.width,
                y0=max(0, box[1]) * native.height,
                x1=min(1, box[2]) * native.width,
                y1=min(1, box[3]) * native.height,
                font_size=max(
                    1,
                    min(
                        (box[2] - box[0]) * native.width,
                        (box[3] - box[1]) * native.height,
                    ),
                ),
                extraction_method="rapidocr-vector-outline",
                extraction_confidence=float(score),
                source_engines=(
                    f"rapidocr@{metadata.version('rapidocr')}+vector-label",
                ),
                content_region="figure",
                uncertain=True,
            )
        )
    return tuple(lines)
