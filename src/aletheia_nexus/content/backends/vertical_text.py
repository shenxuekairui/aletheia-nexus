"""Retain vertical native axis labels as readable text with their source box."""

from __future__ import annotations

import re
import statistics
from collections import defaultdict

from aletheia_nexus.content.models import LayoutLine

_SUPERSCRIPT = str.maketrans("0123456789+-−", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻")


def _baseline(char):
    return getattr(char, "an_text_origin", char.matrix[4:6])[0]


def _join_raised_numbers(runs):
    """Associate a short raised run only with one physically adjacent base."""
    additions, removed, raised = defaultdict(list), set(), set()
    proposals = []
    for index, (upwards, script) in enumerate(runs):
        text = "".join(c.get_text() for c in script).strip()
        if not re.fullmatch(r"[+−-]?\d{1,3}", text):
            continue
        size = statistics.median(c.x1 - c.x0 for c in script)
        start = min(c.y0 if upwards else -c.y1 for c in script)
        end = max(c.y1 if upwards else -c.y0 for c in script)
        baseline = statistics.median(_baseline(c) for c in script)
        candidates = []
        for other, (direction, base) in enumerate(runs):
            if other == index or direction != upwards:
                continue
            if not any(c.get_text().isalpha() for c in base):
                continue
            base_size = statistics.median(c.x1 - c.x0 for c in base)
            shift = (statistics.median(_baseline(c) for c in base) - baseline) * (
                1 if upwards else -1
            )
            if not (
                0.4 <= size / base_size <= 0.8 and 0.15 <= shift / base_size <= 0.8
            ):
                continue
            preceding = [
                c
                for c in base
                if c.get_text().strip()
                and (c.y0 if upwards else -c.y1) < start
                and -0.2 * base_size
                <= start - (c.y1 if upwards else -c.y0)
                <= base_size * 0.6
            ]
            if not preceding:
                continue
            # An independent neighbouring label is not a script in this line.
            if any(
                (c.y0 if upwards else -c.y1) >= start
                and (c.y0 if upwards else -c.y1) < end - base_size * 0.25
                and c.get_text().strip()
                for c in base
            ):
                continue
            candidates.append(other)
        if len(candidates) == 1:
            proposals.append((index, candidates[0], start, end))
    for index, target, start, end in proposals:
        if any(
            other != index
            and other_target == target
            and min(end, other_end) > max(start, other_start)
            for other, other_target, other_start, other_end in proposals
        ):
            continue
        script = runs[index][1]
        additions[target].extend(script)
        removed.add(index)
        raised.update(id(c) for c in script)
    return [
        (
            direction,
            sorted(chars + additions[i], key=lambda c: c.y0, reverse=not direction),
        )
        for i, (direction, chars) in enumerate(runs)
        if i not in removed
    ], raised


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
            groups[(round(_baseline(char), 1), b > 0)].append(char)
    all_runs = []
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
        all_runs.extend((upwards, run) for run in runs)
    all_runs, raised = _join_raised_numbers(all_runs)
    consumed = set()
    lines = []
    for upwards, run in all_runs:
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
            if previous and gap > char.size * 0.13 and id(char) not in raised:
                parts.append(" ")
            parts.append(
                char.get_text().translate(_SUPERSCRIPT)
                if id(char) in raised
                else char.get_text()
            )
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
