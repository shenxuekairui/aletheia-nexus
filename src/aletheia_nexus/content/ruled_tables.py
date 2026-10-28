"""Use printed table rules to bound cells without guessing blank-cell values."""

from __future__ import annotations

from dataclasses import replace

from aletheia_nexus.content.captions import _is_table_caption


def table_bounds(caption, objects, width, height):
    below = _below_caption_bounds(caption, objects, width, height)
    above = _above_caption_bounds(caption, objects, width, height)
    # Rules on both sides do not establish which table this caption labels.
    return None if below and above else below or above


def _above_caption_bounds(caption, objects, width, height):
    """Accept a lower caption only with a nearby, physically closed grid."""
    rules = [o.bbox for o in objects if o.object_type == "horizontal-rule" and o.bbox]
    top = getattr(caption, "y1", caption.y0 + caption.font_size) / height
    left = caption.x0 / width
    nearby = [
        b
        for b in rules
        if 0 <= b[1] - top <= caption.font_size * 4 / height
        and b[0] - 0.02 <= left <= b[2]
        and b[2] - b[0] > 0.2
    ]
    if not nearby:
        return None
    bottom = min(nearby, key=lambda b: b[1])
    aligned = sorted(
        (
            b
            for b in rules
            if abs(b[0] - bottom[0]) < 0.003
            and abs(b[2] - bottom[2]) < 0.003
            and b[1] >= bottom[1]
        ),
        key=lambda b: b[1],
    )
    selected = [bottom]
    for rule in aligned[1:]:
        if rule[1] - selected[-1][3] > caption.font_size * 8 / height:
            break
        selected.append(rule)
    if len(selected) < 3:
        return None
    low, high = bottom[1], selected[-1][3]
    if not all(
        any(
            o.object_type == "vertical-rule"
            and o.bbox
            and abs((o.bbox[0] + o.bbox[2]) / 2 - x) < 0.003
            and o.bbox[1] <= low + 0.003
            and o.bbox[3] >= high - 0.003
            for o in objects
        )
        for x in (bottom[0], bottom[2])
    ):
        return None
    return bottom[0], low, bottom[2], high


def _below_caption_bounds(caption, objects, width, height):
    rules = [o.bbox for o in objects if o.object_type == "horizontal-rule" and o.bbox]
    if not rules:
        return None
    bottom = caption.y0 / height
    left = caption.x0 / width
    candidates = [
        b
        for b in rules
        if 0 <= bottom - b[3] <= caption.font_size * 8 / height
        and b[0] - 0.02 <= left <= b[2]
        and b[2] - b[0] > 0.2
    ]
    if not candidates:
        return None
    top = max(candidates, key=lambda b: b[3])
    aligned = sorted(
        [
            b
            for b in rules
            if abs(b[0] - top[0]) < 0.01
            and abs(b[2] - top[2]) < 0.01
            and b[3] <= top[3] + 0.001
        ],
        key=lambda b: -b[3],
    )
    if len(aligned) < 3:
        return None
    # The header separator must follow nearby. A distant page-footer rule is
    # not a table boundary. Subsequent full-width rules delimit body rows.
    borders = [
        o.bbox
        for o in objects
        if o.object_type == "vertical-rule"
        and o.bbox
        and abs(o.bbox[3] - top[3]) < 0.003
        and (abs(o.bbox[0] - top[0]) < 0.003 or abs(o.bbox[2] - top[2]) < 0.003)
    ]
    if top[1] - aligned[1][3] > caption.font_size * 5 / height and not all(
        any(
            abs((b[0] + b[2]) / 2 - x) < 0.003 and b[1] <= aligned[-1][1] + 0.003
            for b in borders
        )
        for x in (top[0], top[2])
    ):
        # A tall wrapped header needs printed sides extending to the bottom,
        # not just a distant horizontal footer sharing its width.
        return None
    if len(borders) >= 2:
        end = max(b[1] for b in borders)
        selected = [b for b in aligned if b[1] >= end - 0.003]
    else:
        selected = aligned[:3]
    if len(selected) < 3:
        return None
    return top[0], selected[-1][1], top[2], top[3]


def prepare_ruled_tables(lines, layout, caption_match, split_fragments):
    replacements = {}
    for caption in lines:
        match = caption_match(caption.text)
        if not _is_table_caption(match):
            continue
        box = table_bounds(caption, layout.objects, layout.width, layout.height)
        if box is None:
            continue
        x0, y0, x1, y1 = box
        if any(
            other is not caption
            and caption_match(other.text)
            and y1 < other.y0 / layout.height < caption.y0 / layout.height
            for other in lines
        ):
            continue
        inside = [
            line
            for line in lines
            if line.content_region
            not in {"figure", "ocr-alternative", "native-alternative"}
            and x0 - 0.002 <= (line.x0 + line.x1) / 2 / layout.width <= x1 + 0.002
            and y0 <= (line.y0 + line.y1) / 2 / layout.height <= y1
        ]
        if len(inside) < 6:
            continue
        separators = [
            o.bbox[3]
            for o in layout.objects
            if o.object_type == "horizontal-rule"
            and o.bbox
            and abs(o.bbox[0] - x0) < 0.01
            and abs(o.bbox[2] - x1) < 0.01
            and y0 < o.bbox[3] < y1 - 0.002
        ]
        header_bottom = max(separators, default=y1)
        header = [
            line
            for line in inside
            if (line.y0 + line.y1) / 2 / layout.height > header_bottom
        ]
        references = []
        for line in sorted(header, key=lambda line: line.x0):
            if not any(
                abs(line.x0 - other.x0) < line.font_size for other in references
            ):
                references.append(line)
        replacements[id(caption)] = (
            replace(
                caption,
                content_region="spanning-table-caption"
                if x0 < 0.45 and x1 > 0.55
                else caption.content_region,
            ),
        )
        for line in inside:
            pieces = (
                split_fragments(line, references)
                if len(references) >= 2
                and line not in header
                and line.glyph_spans
                and not line.extraction_method.endswith("+painted-cell")
                else ()
            )
            replacements[id(line)] = tuple(
                replace(piece, content_region="table-cell")
                for piece in (pieces or (line,))
            )
    return tuple(
        piece for line in lines for piece in replacements.get(id(line), (line,))
    )


def explicit_grid_cells(caption, blocks, anchors, layout):
    anchor = anchors[caption["anchor_id"]]["bbox"]

    # Reuse the same caption-to-rule bound in normalized page coordinates.
    class Positioned:
        x0 = anchor[0] * layout.width
        y0 = anchor[1] * layout.height
        y1 = anchor[3] * layout.height
        font_size = max(1, (anchor[3] - anchor[1]) * layout.height)

    box = table_bounds(Positioned(), layout.objects, layout.width, layout.height)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    if any(
        other is not caption
        and other["page"] == caption["page"]
        and other["kind"] == "caption"
        and y1 < anchors[other["anchor_id"]]["bbox"][1] < anchor[1]
        for other in blocks
    ):
        return None
    tol = 0.002
    hs = [
        o.bbox
        for o in layout.objects
        if o.object_type == "horizontal-rule"
        and o.bbox
        and y0 - tol < o.bbox[1] < y1 + tol
        and x0 - tol < o.bbox[0] < x1
    ]
    vs = [
        o.bbox
        for o in layout.objects
        if o.object_type == "vertical-rule"
        and o.bbox
        and x0 - tol < (o.bbox[0] + o.bbox[2]) / 2 < x1 + tol
        and o.bbox[1] <= y1
        and o.bbox[3] >= y0
    ]

    def unique(values):
        out = []
        for v in sorted(values):
            if not out or v - out[-1] > tol:
                out.append(v)
        return out

    xs = unique([x0, x1, *[(b[0] + b[2]) / 2 for b in vs]])
    ys = unique([y0, y1, *[(b[1] + b[3]) / 2 for b in hs]])
    if len(xs) < 3 or len(ys) < 3:
        return None
    # Only a closed grid authorizes geometric cell and span assignments.
    if not all(
        any(
            abs((b[0] + b[2]) / 2 - x) < tol and b[1] <= y0 + tol and b[3] >= y1 - tol
            for b in vs
        )
        for x in [xs[0], xs[-1]]
    ):
        return None
    cells = []
    for block in blocks:
        if (
            block["page"] != caption["page"]
            or block.get("content_region") != "table-cell"
        ):
            continue
        a = anchors[block["anchor_id"]]["bbox"]
        cx = (a[0] + a[2]) / 2
        cy = (a[1] + a[3]) / 2
        if not x0 <= cx <= x1 or not y0 <= cy <= y1:
            continue
        below = [
            (b[1] + b[3]) / 2
            for b in hs
            if b[0] - tol <= cx <= b[2] + tol and (b[1] + b[3]) / 2 < cy
        ]
        above = [
            (b[1] + b[3]) / 2
            for b in hs
            if b[0] - tol <= cx <= b[2] + tol and (b[1] + b[3]) / 2 > cy
        ]
        lefts = [
            (b[0] + b[2]) / 2
            for b in vs
            if b[1] - tol <= cy <= b[3] + tol and (b[0] + b[2]) / 2 < cx
        ]
        rights = [
            (b[0] + b[2]) / 2
            for b in vs
            if b[1] - tol <= cy <= b[3] + tol and (b[0] + b[2]) / 2 > cx
        ]
        if not all([below, above, lefts, rights]):
            return None
        low, high, left, right = max(below), min(above), max(lefts), min(rights)
        xi = min(range(len(xs)), key=lambda i: abs(xs[i] - left))
        xj = min(range(len(xs)), key=lambda i: abs(xs[i] - right))
        yi = min(range(len(ys)), key=lambda i: abs(ys[i] - low))
        yj = min(range(len(ys)), key=lambda i: abs(ys[i] - high))
        cell = dict(
            text=block["text"],
            block_id=block["id"],
            anchor_id=block["anchor_id"],
            bbox=a,
            row=len(ys) - yj,
            column=xi + 1,
            span_evidence="painted-pdf-grid",
        )
        if xj - xi > 1:
            cell["column_span"] = xj - xi
        if yj - yi > 1:
            cell["row_span"] = yj - yi
        cells.append(cell)
    return (cells, len(ys) - 1, len(xs) - 1) if len(cells) >= 6 else None
