"""Keep repeated, explicitly keyed figure measurements with aligned labels."""

from __future__ import annotations

import re
import statistics
from dataclasses import replace

_METRIC = re.compile(r"(?P<key>[A-Za-z][A-Za-z /]{0,18})\s*[:=]\s*[−+\-]?\d")
_RESULT = re.compile(
    r"[<≤>≥−+\-]?\d+(?:\.\d+)?\s*%\s*[A-Za-z]+\s*[,;]\s*"
    r"[<≤>≥−+\-]?\d+(?:\.\d+)?\s*%\s*[A-Za-z]+\s*[*†‡a-z]?"
)


def associate_percentage_results(lines):
    """Keep printed result lines under a repeated row of short source labels.

    Multiple results and their footnote markers remain separate lines. This
    does not assert that the results use the same experimental conditions.
    """
    available = [
        line
        for line in lines
        if not line.content_region.endswith("alternative")
        and line.content_region != "table-cell"
    ]
    values = [line for line in available if _RESULT.fullmatch(line.text.strip())]
    removed, output = set(), []
    for seed in values:
        if id(seed) in removed:
            continue
        size = seed.font_size
        row = sorted(
            (line for line in values if abs(line.y0 - seed.y0) < size * 0.6),
            key=lambda line: line.x0,
        )
        if len(row) < 2 or any(a.x1 >= b.x0 for a, b in zip(row, row[1:])):
            continue
        centers = [(line.x0 + line.x1) / 2 for line in row]
        groups = []
        for index, value in enumerate(row):
            spacing = min(
                abs(x - centers[index])
                for other, x in enumerate(centers)
                if other != index
            )

            def aligned(line):
                return abs(
                    (line.x0 + line.x1) / 2 - centers[index]
                ) < spacing * 0.25 and not any(
                    line.x0 < x < line.x1
                    for other, x in enumerate(centers)
                    if other != index
                )

            labels = [
                line
                for line in available
                if aligned(line)
                and -0.2 * size <= line.y0 - value.y1 <= size * 1.5
                and re.fullmatch(r"[A-Za-z]+\d+[A-Za-z]?", line.text.strip())
                and not any(
                    other is not value
                    and other.x0 <= centers[index] <= other.x1
                    and value.y0 + size * 0.6 < other.y0
                    and other.y1 <= line.y0 + size * 0.2
                    for other in values
                )
            ]
            if len(labels) != 1:
                break
            selected = [labels[0], value]
            for _ in range(2):
                following = [
                    line
                    for line in values
                    if line not in selected
                    and aligned(line)
                    and -0.2 * size <= selected[-1].y0 - line.y1 <= size * 1.2
                ]
                if not following:
                    break
                if len(following) != 1:
                    selected = []
                    break
                selected.append(following[0])
            if not selected:
                break
            groups.append(selected)
        if (
            len(groups) != len(row)
            or max(g[0].y0 for g in groups) - min(g[0].y0 for g in groups) > size
        ):
            continue
        members = [line for group in groups for line in group]
        if len({id(line) for line in members}) != len(members) or any(
            id(line) in removed for line in members
        ):
            continue
        for selected in groups:
            removed.update(id(line) for line in selected)
            output.append(
                replace(
                    selected[0],
                    text="\n".join(line.text for line in selected),
                    x0=min(line.x0 for line in selected),
                    y0=min(line.y0 for line in selected),
                    x1=max(line.x1 for line in selected),
                    y1=max(line.y1 for line in selected),
                    content_region="figure",
                    extraction_method="positioned-percentage-result-labels",
                    extraction_confidence=min(
                        line.extraction_confidence for line in selected
                    ),
                    source_engines=tuple(
                        dict.fromkeys(
                            e for line in selected for e in line.source_engines
                        )
                    ),
                    engine_agreement=None,
                    uncertain=True,
                    glyph_spans=(),
                )
            )
    return tuple(
        [line for line in lines if id(line) not in removed]
        + output
        + [
            replace(line, content_region="native-alternative", uncertain=True)
            for line in lines
            if id(line) in removed
        ]
    )


def associate_keyed_labels(lines):
    """Group a short label above repeated keyed measurements in separate columns.

    No value is inferred from a plot. Ambiguous headers, competing columns and
    missing repeated measurement keys keep their original individual readings.
    """
    available = [
        line
        for line in lines
        if not line.content_region.endswith("alternative")
        and line.content_region != "table-cell"
    ]
    metrics = [
        (line, m["key"].strip().casefold())
        for line in available
        if len(line.text) <= 60 and (m := _METRIC.match(line.text.strip()))
    ]
    removed, groups = set(), []
    for seed, key in metrics:
        if id(seed) in removed:
            continue
        cy = (seed.y0 + seed.y1) / 2
        row = sorted(
            (
                line
                for line, other_key in metrics
                if other_key == key
                and abs((line.y0 + line.y1) / 2 - cy) < seed.font_size * 0.6
                and 0.65 < line.font_size / seed.font_size < 1.5
            ),
            key=lambda line: line.x0,
        )
        if len(row) < 2 or any(a.x1 >= b.x0 for a, b in zip(row, row[1:])):
            continue
        centers = [(line.x0 + line.x1) / 2 for line in row]
        size = statistics.median(line.font_size for line in row)
        chosen = []
        for i, value in enumerate(row):
            spacing = min(abs(x - centers[i]) for j, x in enumerate(centers) if i != j)

            def aligned(line):
                return abs(
                    (line.x0 + line.x1) / 2 - centers[i]
                ) < spacing * 0.3 and not any(
                    line.x0 <= x <= line.x1 for j, x in enumerate(centers) if j != i
                )

            labels = [
                line
                for line in available
                if line not in row
                and aligned(line)
                and -0.2 * size <= line.y0 - value.y1 <= size * 1.5
                and len(line.text.strip()) <= 30
                and len(line.text.split()) <= 3
                and not _METRIC.match(line.text.strip())
                and re.search(r"[A-Za-z]", line.text)
                and re.search(r"\d", line.text)
            ]
            if len(labels) != 1:
                break
            lower = [
                (line, other_key)
                for line, other_key in metrics
                if other_key != key
                and aligned(line)
                and -0.2 * size <= value.y0 - line.y1 <= size * 1.5
            ]
            if len(lower) != 1:
                break
            chosen.append((labels[0], value, lower[0]))
        if len(chosen) != len(row) or len({lower[1] for _, _, lower in chosen}) != 1:
            continue
        if (
            max(label.y0 for label, _, _ in chosen)
            - min(label.y0 for label, _, _ in chosen)
            > size
        ):
            continue
        members = [
            line
            for label, value, (lower, _) in chosen
            for line in (label, value, lower)
        ]
        if len({id(line) for line in members}) != len(members) or any(
            id(line) in removed for line in members
        ):
            continue
        for label, value, (lower, _) in chosen:
            selected = [label, value, lower]
            removed.update(id(line) for line in selected)
            groups.append(
                replace(
                    value,
                    text="; ".join(line.text for line in selected),
                    x0=min(line.x0 for line in selected),
                    y0=min(line.y0 for line in selected),
                    x1=max(line.x1 for line in selected),
                    y1=max(line.y1 for line in selected),
                    content_region="figure",
                    extraction_method="positioned-keyed-figure-labels",
                    extraction_confidence=min(
                        line.extraction_confidence for line in selected
                    ),
                    engine_agreement=None,
                    source_engines=tuple(
                        dict.fromkeys(
                            e for line in selected for e in line.source_engines
                        )
                    ),
                    uncertain=True,
                    glyph_spans=(),
                )
            )
    return tuple(
        [line for line in lines if id(line) not in removed]
        + groups
        + [
            replace(line, content_region="native-alternative", uncertain=True)
            for line in lines
            if id(line) in removed
        ]
    )
