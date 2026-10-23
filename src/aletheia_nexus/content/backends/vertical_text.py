"""Retain vertical native axis labels as readable text with their source box."""

from __future__ import annotations

import statistics
from collections import defaultdict

from aletheia_nexus.content.models import LayoutLine


def vertical_lines(glyphs, width, height, engine, suspicious=lambda text: False):
    groups = defaultdict(list)
    for char in glyphs:
        a, b, c, d, x, y = char.matrix
        if (
            abs(a) < 1e-6
            and abs(d) < 1e-6
            and b * c < 0
            and width * 0.08 < char.x0 < width * 0.92
        ):
            groups[(round(x, 1), b > 0)].append(char)
    consumed = set()
    lines = []
    for (_, upwards), chars in groups.items():
        chars.sort(key=lambda c: c.y0, reverse=not upwards)
        runs = [[]]
        for char in chars:
            previous = runs[-1][-1] if runs[-1] else None
            gap = (
                (char.y0 - previous.y1 if upwards else previous.y0 - char.y1)
                if previous
                else 0
            )
            if previous and gap > max(char.size, previous.size) * 2:
                runs.append([])
            runs[-1].append(char)
        for run in runs:
            if len(run) < 2:
                continue
            parts = []
            for i, char in enumerate(run):
                previous = run[i - 1] if i else None
                gap = (
                    (char.y0 - previous.y1 if upwards else previous.y0 - char.y1)
                    if previous
                    else 0
                )
                if previous and gap > char.size * 0.13:
                    parts.append(" ")
                parts.append(char.get_text())
            text = "".join(parts).strip()
            if not text:
                continue
            ink = [c for c in run if c.get_text().strip()]
            lines.append(
                LayoutLine(
                    text=text,
                    x0=max(0, min(c.x0 for c in ink)),
                    y0=max(0, min(c.y0 for c in ink)),
                    x1=min(width, max(c.x1 for c in ink)),
                    y1=min(height, max(c.y1 for c in ink)),
                    font_size=statistics.median(c.size for c in ink),
                    extraction_method="pdfminer-vertical-glyphs",
                    source_engines=(engine,),
                    content_region="figure",
                    uncertain=suspicious(text)
                    or any(hasattr(c, "original_reading") for c in run),
                )
            )
            consumed.update(id(c) for c in run)
    return lines, consumed
