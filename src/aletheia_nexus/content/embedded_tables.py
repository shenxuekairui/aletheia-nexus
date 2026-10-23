"""Bound captionless numeric tables by their three painted horizontal rules.

Headers, repeated numeric columns and unique row proximity are all required.
The resulting cells describe observed layout, not confirmed experiment data.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import replace

from aletheia_nexus.content.table_layout import _CELL_ANNOTATED_NUMBER, _CELL_NUMBER


def _center(line):
    return (line.x0 + line.x1) / 2, (line.y0 + line.y1) / 2


def embedded_grids(lines, layout):
    rules = sorted(
        (
            o.bbox
            for o in layout.objects
            if o.object_type == "horizontal-rule" and o.bbox
        ),
        key=lambda b: -b[3],
    )
    groups = []
    for top in rules:
        if top[2] - top[0] < 0.15:
            continue
        aligned = [
            b
            for b in rules
            if b[3] <= top[3]
            and abs(b[0] - top[0]) < 0.003
            and abs(b[2] - top[2]) < 0.003
        ]
        if len(aligned) < 3:
            continue
        _, separator, bottom = aligned[:3]
        x0, x1 = top[0] * layout.width, top[2] * layout.width
        y0, yh, y1 = (
            bottom[3] * layout.height,
            separator[3] * layout.height,
            top[1] * layout.height,
        )
        inside = [
            line
            for line in lines
            if not line.content_region.endswith("alternative")
            and x0 <= _center(line)[0] <= x1
            and y0 < _center(line)[1] < y1
        ]
        if len(inside) < 9 or any(len(line.text) > 100 for line in inside):
            continue
        size = statistics.median(line.font_size for line in inside)
        header = sorted(
            (line for line in inside if _center(line)[1] > yh), key=lambda item: item.x0
        )
        if (
            not size <= y1 - yh <= size * 4
            or len(header) < 3
            or any(
                not re.search(r"[A-Za-z\u3400-\u9fff]", line.text) for line in header
            )
            or any(a.x1 >= b.x0 for a, b in zip(header, header[1:]))
            or max(_center(item)[1] for item in header)
            - min(_center(item)[1] for item in header)
            > size
        ):
            continue
        centers = [_center(line)[0] for line in header]

        def column(line):
            cx, _ = _center(line)
            distances = sorted((abs(cx - x), i) for i, x in enumerate(centers))
            if distances[1][0] - distances[0][0] < size * 0.5:
                return None
            col = distances[0][1]
            # Overhanging centered labels are valid; crossing a neighbour's
            # center is not enough evidence to assign a unique column.
            if any(line.x0 < x < line.x1 for i, x in enumerate(centers) if i != col):
                return None
            return col

        body = [line for line in inside if _center(line)[1] < yh]
        numeric = sorted(
            (
                line
                for line in body
                if _CELL_NUMBER.fullmatch(line.text.strip())
                or _CELL_ANNOTATED_NUMBER.fullmatch(line.text.strip())
            ),
            key=lambda item: -_center(item)[1],
        )
        rows = []
        for line in numeric:
            if (
                rows
                and abs(
                    _center(line)[1]
                    - statistics.mean(_center(item)[1] for item in rows[-1])
                )
                < size * 0.6
            ):
                rows[-1].append(line)
            else:
                rows.append([line])
        dense = [
            row for row in rows if len({column(item) for item in row} - {None}) >= 2
        ]
        if len(dense) < 2:
            continue
        # At least two numeric columns recur in every data row. A lone number
        # elsewhere is a condition, not a new experiment or a copied value.
        common = set.intersection(
            *({column(item) for item in row} - {None} for row in dense)
        )
        if len(common) < 2:
            continue
        row_centers = [
            statistics.mean(_center(item)[1] for item in row) for row in dense
        ]
        if any(a - b < size * 1.2 for a, b in zip(row_centers, row_centers[1:])):
            continue
        cells = [(line, 1, i + 1) for i, line in enumerate(header)]
        for line in body:
            col = column(line)
            distances = sorted(
                (abs(_center(line)[1] - y), i) for i, y in enumerate(row_centers)
            )
            if (
                col is None
                or distances[0][0] > size * 2
                or distances[1][0] - distances[0][0] < size * 0.35
            ):
                break
            cells.append((line, distances[0][1] + 2, col + 1))
        else:
            if any(id(line) in old["members"] for line in inside for old in groups):
                continue
            groups.append(
                dict(
                    cells=cells,
                    members={id(item) for item in inside},
                    row_count=len(dense) + 1,
                    column_count=len(header),
                    bbox=[top[0], bottom[3], top[2], top[1]],
                )
            )
    return groups


def prepare_embedded_tables(lines, layout):
    members = {
        member for grid in embedded_grids(lines, layout) for member in grid["members"]
    }
    return tuple(
        replace(line, content_region="table-cell") if id(line) in members else line
        for line in lines
    )


def append_embedded_tables(tables, blocks, anchors, layouts):
    occupied = {c["block_id"] for table in tables for c in table.get("cells", [])}
    for page, layout in layouts.items():
        candidates = [
            b
            for b in blocks
            if b["page"] == page and b.get("content_region") == "table-cell"
        ]
        for grid in embedded_grids(layout.lines, layout):
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
                if len(matches) != 1 or matches[0]["id"] in occupied:
                    break
                block = matches[0]
                cells.append(
                    dict(
                        block_id=block["id"],
                        anchor_id=block["anchor_id"],
                        text=block["text"],
                        row=row,
                        column=col,
                        bbox=anchors[block["anchor_id"]]["bbox"],
                        span_evidence="painted-rules-and-aligned-columns",
                    )
                )
            else:
                first = cells[0]
                # Retain the existing anchor-reference field for consumers,
                # explicitly saying this is a header anchor and no caption.
                tables.append(
                    dict(
                        id=f"t{len(tables) + 1:05d}",
                        label="",
                        caption="",
                        caption_block_id=first["block_id"],
                        anchor_id=first["anchor_id"],
                        caption_source="header-anchor-no-caption",
                        association="painted-rules+positioned-cells",
                        evidence_status="rule-and-cell-evidence-observed",
                        interpretation_status="not-interpreted",
                        uncertain=True,
                        cells=cells,
                        row_count=grid["row_count"],
                        column_count=grid["column_count"],
                        object_block_ids=[c["block_id"] for c in cells],
                        bbox=grid["bbox"],
                    )
                )
                occupied.update(c["block_id"] for c in cells)
