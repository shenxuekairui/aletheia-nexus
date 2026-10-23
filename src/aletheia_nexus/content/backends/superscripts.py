"""Locate painted, detached superscripts at the end of an OCR unit token."""

from __future__ import annotations

import statistics


def raised_glyph_box(image, box):
    """Return a small raised component, never an exponent inferred from a unit.

    Work inside the observed word box. A normal baseline digit, a dot, nearby
    prose and ink from another line must not be turned into a unit exponent.
    The caller still has to recognize the isolated glyph without a whitelist.
    """
    left, top, right, bottom = box
    crop = image.crop(box).convert("L")
    pixels = crop.load()
    seen = set()
    components = []
    for y in range(crop.height):
        for x in range(crop.width):
            if (x, y) in seen or pixels[x, y] > 127:
                continue
            pending = [(x, y)]
            seen.add((x, y))
            points = []
            while pending:
                a, b = pending.pop()
                points.append((a, b))
                for nx in range(max(0, a - 1), min(crop.width, a + 2)):
                    for ny in range(max(0, b - 1), min(crop.height, b + 2)):
                        if (nx, ny) not in seen and pixels[nx, ny] <= 127:
                            seen.add((nx, ny))
                            pending.append((nx, ny))
            if len(points) >= 5:
                components.append(
                    (
                        min(p[0] for p in points),
                        min(p[1] for p in points),
                        max(p[0] for p in points) + 1,
                        max(p[1] for p in points) + 1,
                    )
                )
    if len(components) < 3:
        return None
    # Use the taller letters/numbers as the baseline, excluding the raised ink.
    tallest = max(y1 - y0 for _, y0, _, y1 in components)
    body = [c for c in components if c[3] - c[1] >= tallest * 0.75]
    if len(body) < 2:
        return None
    height = statistics.median(c[3] - c[1] for c in body)
    baseline = statistics.median(c[3] for c in body)
    candidates = [
        c
        for c in components
        if c[0] >= crop.width * 0.7
        and 0.3 * height <= c[3] - c[1] <= 0.7 * height
        and c[3] <= baseline - 0.3 * height
        and c[1] >= baseline - 1.6 * height
        and c[2] - c[0] >= 0.15 * height
        # The preceding unit letter must be on the baseline and adjacent.
        and any(
            -height * 0.15 <= c[0] - p[2] <= height * 0.35
            and abs(p[3] - baseline) <= height * 0.2
            and p[3] - p[1] >= height * 0.45
            for p in components
        )
    ]
    if len(candidates) != 1:
        return None
    x0, y0, x1, y1 = candidates[0]
    return left + x0, top + y0, left + x1, top + y1
