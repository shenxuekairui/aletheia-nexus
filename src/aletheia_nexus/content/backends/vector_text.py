"""Locate repeated small painted outlines that have no native text mapping.

This does not recognize letters or infer experimental data. The boxes only
route existing OCR and disclose bounded gaps in native-only extraction.
"""

from __future__ import annotations

from aletheia_nexus.content.models import PageObject

MAX_VECTOR_CANDIDATES = 5000
MAX_VECTOR_COMPARISONS = 250000


class VectorTextLimitError(ValueError):
    """Preserve the uninspected region when dense drawings exhaust the scan."""

    def __init__(self, candidates, width, height, reason):
        super().__init__(reason)
        boxes = [box for box, _ in candidates]
        self.region = PageObject(
            "vector-text",
            "vector-text-scan-limit",
            bbox=(
                max(0, min(b[0] for b in boxes)) / width,
                max(0, min(b[1] for b in boxes)) / height,
                min(width, max(b[2] for b in boxes)) / width,
                min(height, max(b[3] for b in boxes)) / height,
            ),
        )


def vector_text_regions(shapes, lines, width, height):
    """Find horizontal/vertical runs of filled, glyph-sized PDF paths.

    Requiring several aligned complex outlines excludes isolated chart markers,
    straight table rules and ordinary stroked molecular bonds. Real native text
    at the same position already supplies a mapping and needs no extra pass.
    Shapes and text use the displayed CropBox coordinate system.
    """
    candidates = []
    for box, complex_path in shapes:
        x0, y0, x1, y1 = box
        if not (0.25 <= x1 - x0 <= 20 and 0.25 <= y1 - y0 <= 20):
            continue
        if max(x1 - x0, y1 - y0) < 2:
            continue
        area = (x1 - x0) * (y1 - y0)
        if any(
            max(0, min(x1, line.x1) - max(x0, line.x0))
            * max(0, min(y1, line.y1) - max(y0, line.y0))
            >= area * 0.6
            for line in lines
        ):
            continue
        candidates.append((box, complex_path))
    if len(candidates) > MAX_VECTOR_CANDIDATES:
        raise VectorTextLimitError(
            candidates,
            width,
            height,
            f"{len(candidates)} candidate outlines exceed the scan limit",
        )
    regions = []
    comparisons = 0
    for vertical in (False, True):
        along, cross = (1, 0) if vertical else (0, 1)
        remaining = set(range(len(candidates)))
        # Neighbour runs follow actual path bounds; no linguistic or chemical
        # dictionary, paper identity or expected numeric value participates.
        ordered = sorted(remaining, key=lambda i: candidates[i][0][along])
        neighbours = {i: [] for i in ordered}
        for position, i in enumerate(ordered):
            a = candidates[i][0]
            ah = a[cross + 2] - a[cross]
            for next_position in range(position + 1, len(ordered)):
                j = ordered[next_position]
                b = candidates[j][0]
                if b[along] - a[along + 2] > 24:
                    break
                comparisons += 1
                if comparisons > MAX_VECTOR_COMPARISONS:
                    raise VectorTextLimitError(
                        candidates,
                        width,
                        height,
                        "candidate outline comparisons exceed the scan limit",
                    )
                bh = b[cross + 2] - b[cross]
                overlap = min(a[cross + 2], b[cross + 2]) - max(a[cross], b[cross])
                if (
                    min(ah, bh) >= max(ah, bh) * 0.4
                    and overlap >= min(ah, bh) * 0.6
                    and max(0, b[along] - a[along + 2]) <= max(ah, bh) * 1.2
                ):
                    neighbours[i].append(j)
                    neighbours[j].append(i)
        for first in ordered:
            if first not in remaining:
                continue
            group, pending = [], [first]
            remaining.remove(first)
            while pending:
                current = pending.pop()
                group.append(current)
                for other in neighbours[current]:
                    if other in remaining:
                        remaining.remove(other)
                        pending.append(other)
            if len(group) < 4 or sum(candidates[i][1] for i in group) < 2:
                continue
            boxes = [candidates[i][0] for i in group]
            bounds = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            if bounds[along + 2] - bounds[along] < 2 * (
                bounds[cross + 2] - bounds[cross]
            ):
                continue
            pad = (bounds[cross + 2] - bounds[cross]) * 0.2
            box = (
                max(0, bounds[0] - pad) / width,
                max(0, bounds[1] - pad) / height,
                min(width, bounds[2] + pad) / width,
                min(height, bounds[3] + pad) / height,
            )
            if box not in regions:
                regions.append(box)
    return tuple(
        PageObject("vector-text", f"vector-text-{index}", bbox=box)
        for index, box in enumerate(sorted(regions), 1)
    )
