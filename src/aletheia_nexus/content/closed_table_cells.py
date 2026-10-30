"""Split native lines at observed closed-grid borders, retaining source readings."""

from __future__ import annotations

from dataclasses import replace

from aletheia_nexus.content.captions import _caption_match, _is_table_caption
from aletheia_nexus.content.ruled_tables import table_bounds
from aletheia_nexus.content.table_layout import _line_slice


def _joined_rules(layout):
    """Account for cell-by-cell painted borders at their observed stroke width."""
    others = [
        o
        for o in layout.objects
        if o.object_type not in {"horizontal-rule", "vertical-rule"}
    ]
    rules = [
        o
        for o in layout.objects
        if o.object_type in {"horizontal-rule", "vertical-rule"}
    ]
    output = []
    for kind in ("horizontal-rule", "vertical-rule"):
        axis = 1 if kind == "horizontal-rule" else 0
        along = 1 - axis
        scale = layout.height if axis else layout.width
        length = layout.width if axis else layout.height
        groups = []
        for obj in sorted(
            (o for o in rules if o.object_type == kind),
            key=lambda o: (o.bbox[axis] + o.bbox[axis + 2]) / 2,
        ):
            center = (obj.bbox[axis] + obj.bbox[axis + 2]) / 2
            if (
                not groups
                or abs(
                    center
                    - (groups[-1][0].bbox[axis] + groups[-1][0].bbox[axis + 2]) / 2
                )
                * scale
                > 0.5
            ):
                groups.append([])
            groups[-1].append(obj)
        for group in groups:
            merged = []
            for obj in sorted(group, key=lambda o: o.bbox[along]):
                b = obj.bbox
                thickness = (
                    min(
                        b[axis + 2] - b[axis],
                        merged[-1].bbox[axis + 2] - merged[-1].bbox[axis],
                    )
                    * scale
                    if merged
                    else 0
                )
                if merged and (b[along] - merged[-1].bbox[along + 2]) * length <= max(
                    0.75, thickness + 0.15
                ):
                    a = merged[-1]
                    merged[-1] = replace(
                        a,
                        bbox=(
                            min(a.bbox[0], b[0]),
                            min(a.bbox[1], b[1]),
                            max(a.bbox[2], b[2]),
                            max(a.bbox[3], b[3]),
                        ),
                    )
                else:
                    merged.append(obj)
            output.extend(merged)
    return tuple([*others, *output])


def prepare_closed_table_cells(layout):
    """Use a closed grid only when native glyphs actually cross cell boundaries.

    Wrapped text stays in separate source fragments with the same physical cell
    coordinates. No decimal, chemical formula, unit or blank value is completed.
    Without sufficient native geometry the existing layout is retained.
    """
    if not any(_is_table_caption(_caption_match(line.text)) for line in layout.lines):
        return layout
    objects = _joined_rules(layout)
    replacements, consumed = {}, set()
    for caption in layout.lines:
        match = _caption_match(caption.text)
        if not _is_table_caption(match):
            continue
        box = table_bounds(caption, objects, layout.width, layout.height)
        if box is None:
            continue
        x0, y0, x1, y1 = box
        tol = 0.002
        hs = [
            o.bbox
            for o in objects
            if o.object_type == "horizontal-rule"
            and y0 - tol < o.bbox[1] < y1 + tol
            and x0 - tol < o.bbox[0] < x1
        ]
        vs = [
            o.bbox
            for o in objects
            if o.object_type == "vertical-rule"
            and x0 - tol < (o.bbox[0] + o.bbox[2]) / 2 < x1 + tol
            and o.bbox[1] <= y1
            and o.bbox[3] >= y0
        ]
        if not all(
            any(
                abs((b[0] + b[2]) / 2 - x) < tol
                and b[1] <= y0 + tol
                and b[3] >= y1 - tol
                for b in vs
            )
            for x in (x0, x1)
        ):
            continue

        def cell(x, y):
            below = [
                (b[1] + b[3]) / 2
                for b in hs
                if b[0] - tol <= x <= b[2] + tol and (b[1] + b[3]) / 2 < y
            ]
            above = [
                (b[1] + b[3]) / 2
                for b in hs
                if b[0] - tol <= x <= b[2] + tol and (b[1] + b[3]) / 2 > y
            ]
            left = [
                (b[0] + b[2]) / 2
                for b in vs
                if b[1] - tol <= y <= b[3] + tol and (b[0] + b[2]) / 2 < x
            ]
            right = [
                (b[0] + b[2]) / 2
                for b in vs
                if b[1] - tol <= y <= b[3] + tol and (b[0] + b[2]) / 2 > x
            ]
            return (
                (max(left), max(below), min(right), min(above))
                if all((below, above, left, right))
                else None
            )

        selected, pieces = [], []
        crossing = False
        for line in layout.lines:
            if id(line) in consumed or line.content_region in {
                "figure",
                "ocr-alternative",
                "native-alternative",
            }:
                continue
            y = (line.y0 + line.y1) / 2 / layout.height
            if not y0 < y < y1 or not (
                x0 - tol < line.x0 / layout.width and line.x1 / layout.width < x1 + tol
            ):
                continue
            if not line.glyph_spans:
                break
            keys = [
                cell((a + b) / 2 / layout.width, y) for _, _, a, b in line.glyph_spans
            ]
            if any(k is None for k in keys):
                break
            fragments = []
            start = 0
            while start < len(keys):
                end = start + 1
                while end < len(keys) and keys[end] == keys[start]:
                    end += 1
                begin, finish = line.glyph_spans[start][0], line.glyph_spans[end - 1][1]
                if line.text[begin:finish].strip():
                    fragments.append(_line_slice(line, begin, finish))
                start = end
            if "".join("".join(p.text.split()) for p in fragments) != "".join(
                line.text.split()
            ):
                break
            selected.append(line)
            crossing |= len(set(keys)) > 1
            pieces.extend(
                replace(
                    p,
                    content_region="table-cell",
                    extraction_method=p.extraction_method + "+painted-cell",
                )
                for p in fragments
            )
        else:
            if crossing and len(pieces) >= 6:
                replacements[id(selected[0])] = tuple(pieces)
                consumed.update(id(line) for line in selected)
    if not consumed:
        return layout
    lines = tuple(
        piece
        for line in layout.lines
        for piece in (
            replacements.get(id(line), ()) if id(line) in consumed else (line,)
        )
    )
    return replace(layout, lines=lines, objects=objects)
