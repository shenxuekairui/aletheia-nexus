"""Recover an explicitly headed experiment grid below a captioned diagram."""

from __future__ import annotations

import re
from dataclasses import replace

from aletheia_nexus.content.captions import _CAPTION, _caption_match, _is_table_caption

_INDEX = re.compile(r"(\d{1,3})(?:\s*[a-z*†‡](?:\s*,\s*[a-z*†‡])*)?")


def _index_number(text):
    match = _INDEX.fullmatch(text.strip())
    return int(match[1]) if match else None


def _join_inline_table_captions(lines):
    """Join a uniquely adjacent styled title before choosing a grid strategy."""
    replacements, removed = {}, set()
    for caption in lines:
        match = _CAPTION.match(caption.text.strip())
        if (
            not _is_table_caption(match)
            or caption.text[match.end() :].strip(" .:")
            or caption.content_region.endswith("alternative")
        ):
            continue
        inline = [
            item
            for item in lines
            if item is not caption
            and not item.content_region.endswith("alternative")
            and 0 <= item.x0 - caption.x1 <= caption.font_size * 2
            and abs(item.y0 - caption.y0) <= caption.font_size * 0.5
            and len(item.text) > 15
        ]
        if len(inline) != 1:
            continue
        description = inline[0]
        text = caption.text + " " + description.text
        if not _caption_match(text) or id(description) in removed:
            continue
        offset = len(caption.text) + 1
        replacements[id(caption)] = replace(
            caption,
            text=text,
            y0=min(caption.y0, description.y0),
            x1=description.x1,
            y1=max(caption.y1, description.y1),
            uncertain=caption.uncertain or description.uncertain,
            extraction_confidence=min(
                caption.extraction_confidence, description.extraction_confidence
            ),
            source_engines=tuple(
                dict.fromkeys((*caption.source_engines, *description.source_engines))
            ),
            glyph_spans=(
                *caption.glyph_spans,
                *(
                    (a + offset, b + offset, x0, x1)
                    for a, b, x0, x1 in description.glyph_spans
                ),
            )
            if caption.glyph_spans and description.glyph_spans
            else (),
        )
        removed.add(id(description))
    return tuple(
        replacements.get(id(line), line) for line in lines if id(line) not in removed
    )


def indexed_grids(lines, layout):
    primary = [
        line
        for line in _join_inline_table_captions(lines)
        if not line.content_region.endswith("alternative")
    ]
    captions = [
        line for line in primary if _is_table_caption(_caption_match(line.text))
    ]
    grids = []
    for head in primary:
        if not re.fullmatch(r"(?i:entry|run|trial|no\.?|序号|编号)", head.text.strip()):
            continue
        size = head.font_size
        above = [
            cap for cap in captions if cap.y0 > head.y1 and cap.x0 <= head.x0 + size
        ]
        if not above:
            continue
        caption = min(above, key=lambda line: line.y0)
        if any(
            _caption_match(line.text) and head.y1 < line.y0 < caption.y0
            for line in primary
        ):
            continue
        # Two painted rules bracketing this header delimit its width. This
        # excludes prose in an adjacent column without relying on title length.
        rules = [
            o.bbox
            for o in layout.objects
            if o.object_type == "horizontal-rule" and o.bbox
        ]
        bounds = [
            top
            for top in rules
            if 0 <= top[1] * layout.height - head.y1 <= size * 2
            and abs(top[0] * layout.width - head.x0) <= size
            and any(
                0 <= head.y0 - bottom[3] * layout.height <= size * 2
                and abs(top[0] - bottom[0]) * layout.width < size * 0.3
                and abs(top[2] - bottom[2]) * layout.width < size * 0.3
                for bottom in rules
            )
        ]
        right = min((b[2] * layout.width for b in bounds), default=layout.width)
        headers = sorted(
            (
                line
                for line in primary
                if line.x0 >= head.x0 - 1
                and line.x1 <= right + 1
                and abs(line.y0 - head.y0) < size * 0.6
                and (
                    re.search(r"[A-Za-z\u3400-\u9fff]", line.text)
                    or re.fullmatch(r"\d{1,3}", line.text.strip())
                )
            ),
            key=lambda line: line.x0,
        )
        if (
            len(headers) < 3
            or headers[0] is not head
            or any(a.x1 >= b.x0 for a, b in zip(headers, headers[1:]))
        ):
            continue
        centers = [(line.x0 + line.x1) / 2 for line in headers]
        # A full-width line below the grid is a boundary, including wrapped
        # footnotes whose later lines begin with a number or a concentration.
        bottom = max(
            (
                line.y1
                for line in primary
                if line.y1 < head.y0
                and line.x0 <= head.x0 + size
                and line.x1 > centers[1]
            ),
            default=0,
        )
        indexes = sorted(
            (
                line
                for line in primary
                if line.y1 < head.y0
                and line.y0 >= bottom
                and abs(line.x0 - head.x0) < size
                and re.match(r"\d", line.text.strip())
            ),
            key=lambda line: -line.y0,
        )
        run = []
        discontinuous = False
        for line in indexes:
            if not run:
                if head.y0 - line.y1 > size * 4:
                    break
            elif run[-1].y0 - line.y1 > size * 4:
                break
            if _index_number(line.text) is None or (
                run and _index_number(line.text) != _index_number(run[-1].text) + 1
            ):
                discontinuous = True
                break
            run.append(line)
        if len(run) < 3 or discontinuous:
            continue
        row_centers = [(line.y0 + line.y1) / 2 for line in run]
        top = max(header.y1 for header in headers)
        inside = [
            line
            for line in primary
            if head.x0 - size <= (line.x0 + line.x1) / 2 <= centers[-1] + size * 5
            and run[-1].y0 - size * 0.4 <= (line.y0 + line.y1) / 2 <= top
        ]
        cells = []
        for line in inside:
            if len(line.text) > 120:
                break
            cy = (line.y0 + line.y1) / 2
            columns = [
                col
                for col, header in enumerate(headers)
                if line.x0 < header.x1 and header.x0 < line.x1
            ]
            # A wide left-aligned header must not pull its short values into
            # the preceding index column. Ambiguous overlap still abstains.
            if not columns:
                cx = (line.x0 + line.x1) / 2
                distances = sorted((abs(cx - x), col) for col, x in enumerate(centers))
                if distances[1][0] - distances[0][0] < size or any(
                    line.x0 < x < line.x1
                    for col, x in enumerate(centers)
                    if col != distances[0][1]
                ):
                    break
                columns = [distances[0][1]]
            if len(columns) != 1:
                break
            col = columns[0] + 1
            if cy > run[0].y1 + size * 0.3:
                row = 1
            else:
                ys = sorted((abs(cy - y), row) for row, y in enumerate(row_centers))
                if ys[0][0] > size * 1.2 or ys[1][0] - ys[0][0] < size * 0.35:
                    break
                row = ys[0][1] + 2
            cells.append((line, row, col))
        else:
            # Every indexed row needs actual content under every header.
            # A numbered prose list or an absent result does not meet this.
            if any(
                {col for _, r, col in cells if r == row}
                != set(range(1, len(headers) + 1))
                for row in range(2, len(run) + 2)
            ):
                continue
            grids.append(
                dict(
                    caption=caption,
                    cells=cells,
                    row_count=len(run) + 1,
                    column_count=len(headers),
                )
            )
    return grids


def prepare_indexed_tables(lines, layout):
    joined = _join_inline_table_captions(lines)
    grids = indexed_grids(joined, layout)
    if not grids:
        return lines
    members = {id(line) for grid in grids for line, _, _ in grid["cells"]}
    return tuple(
        replace(line, content_region="table-cell") if id(line) in members else line
        for line in joined
    )


def repair_indexed_tables(tables, blocks, anchors, layouts):
    for page, layout in layouts.items():
        candidates = [
            b
            for b in blocks
            if b["page"] == page and b.get("content_region") == "table-cell"
        ]
        for grid in indexed_grids(layout.lines, layout):
            cap = grid["caption"]
            targets = [
                table
                for table in tables
                if any(
                    b["id"] == table["caption_block_id"]
                    and b["page"] == page
                    and abs(anchors[b["anchor_id"]]["bbox"][3] - cap.y1 / layout.height)
                    < 0.000002
                    for b in blocks
                )
            ]
            if len(targets) != 1:
                continue
            cells = []
            for line, row, col in grid["cells"]:
                box = [
                    line.x0 / layout.width,
                    line.y0 / layout.height,
                    line.x1 / layout.width,
                    line.y1 / layout.height,
                ]
                matches = [
                    b
                    for b in candidates
                    if b["text"] == line.text
                    and all(
                        abs(a - v) < 0.000002
                        for a, v in zip(anchors[b["anchor_id"]]["bbox"], box)
                    )
                ]
                if len(matches) != 1:
                    break
                block = matches[0]
                cells.append(
                    dict(
                        block_id=block["id"],
                        anchor_id=block["anchor_id"],
                        bbox=anchors[block["anchor_id"]]["bbox"],
                        text=block["text"],
                        row=row,
                        column=col,
                        span_evidence="printed-index-and-aligned-headers",
                    )
                )
            else:
                targets[0].update(
                    cells=cells,
                    row_count=grid["row_count"],
                    column_count=grid["column_count"],
                    object_block_ids=list(
                        dict.fromkeys(
                            [
                                *targets[0].get("object_block_ids", []),
                                *(c["block_id"] for c in cells),
                            ]
                        )
                    ),
                    association="caption+positioned-cells",
                    evidence_status="caption-and-cell-evidence-observed",
                )
