"""Observed table columns, shared cells and local layout warnings.

These functions arrange source evidence; they do not infer scientific facts.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import replace

from aletheia_nexus.content.captions import (
    _CAPTION,
    _UNNUMBERED_TABLE_CAPTION,
    _caption_match,
    _is_table_caption,
)
from aletheia_nexus.content.models import LayoutLine

_CELL_NUMBER = re.compile(
    r"[−+±\-]?\d+(?:[.,]\s*\d+)?%?"
    r"(?:\s*[–—～~]\s*[−+\-]?\d+(?:[.,]\s*\d+)?%?)?"
)


_CELL_NUMBER_LIST = re.compile(
    rf"{_CELL_NUMBER.pattern}(?:\s*[,;]\s*{_CELL_NUMBER.pattern})+"
)


_CELL_ANNOTATED_NUMBER = re.compile(
    rf"{_CELL_NUMBER.pattern}\s*(?:\([A-Za-z]{{1,3}}\)|\([<>≤≥]*\d+(?:\.\d+)?\)|[A-Za-z*†‡]{{1,3}}|®)"
)


def _line_slice(line: LayoutLine, start: int, end: int) -> LayoutLine:
    while start < end and line.text[start].isspace():
        start += 1
    while end > start and line.text[end - 1].isspace():
        end -= 1
    glyphs = tuple(g for g in line.glyph_spans if g[0] >= start and g[1] <= end)
    return replace(
        line,
        text=line.text[start:end].strip(),
        x0=min(g[2] for g in glyphs),
        x1=max(g[3] for g in glyphs),
        glyph_spans=tuple((a - start, b - start, x0, x1) for a, b, x0, x1 in glyphs),
    )


def _aligned_table_fragments(line, reference):
    """Find whitespace cuts whose complete pieces occupy distinct columns.

    A long header can overhang its column, so a midpoint cut through words is
    not evidence. Compare whole pieces with the observed centers and edges.
    """
    if _caption_match(line.text) or re.match(
        r"Tab\.\s*(?:\d+|[IVXLCDM]+)\b", line.text
    ):
        return ()
    gaps = [
        (a[1], b[0])
        for a, b in zip(line.glyph_spans, line.glyph_spans[1:])
        if line.text[a[1] : b[0]].isspace() and b[2] - a[3] > line.font_size * 0.15
    ]
    if not gaps or len(gaps) > 24:
        return ()
    starts = [0, *(b for _, b in gaps)]
    ends = [*(a for a, _ in gaps), len(line.text)]
    choices = {}
    for start in range(len(starts)):
        for end in range(start, len(ends)):
            piece = _line_slice(line, starts[start], ends[end])
            distances = [
                min(
                    abs(piece.x0 - cell.x0),
                    abs(piece.x1 - cell.x1),
                    abs(piece.x0 + piece.x1 - cell.x0 - cell.x1) / 2,
                )
                for cell in reference
            ]
            matches = [
                i
                for i, distance in enumerate(distances)
                if distance <= line.font_size * 0.6
            ]
            if len(matches) == 1:
                choices[start, end] = (matches[0], distances[matches[0]], piece)
    best = {}

    def solve(start, previous):
        if start == len(starts):
            return (0, 0, ())
        if (start, previous) in best:
            return best[start, previous]
        answer = None
        for end in range(start, len(ends)):
            choice = choices.get((start, end))
            if choice is None or choice[0] <= previous:
                continue
            tail = solve(end + 1, choice[0])
            if tail is None:
                continue
            candidate = (tail[0] + 1, tail[1] - choice[1], (choice[2], *tail[2]))
            if answer is None or candidate[:2] > answer[:2]:
                answer = candidate
        best[start, previous] = answer
        return answer

    answer = solve(0, -1)
    return answer[2] if answer is not None and answer[0] >= 2 else ()


def _prepare_table_lines(
    lines: tuple[LayoutLine, ...], width: float, objects=(), height: float = 1
) -> tuple[LayoutLine, ...]:
    """Keep captioned numeric grids, including single-column tables, intact."""
    # A native line can contain a whole horizontal numeric row. Split only
    # when every token is numeric and actual glyph positions are available.
    expanded = []
    for line in lines:
        matches = list(_CELL_NUMBER.finditer(line.text))
        if (
            line.glyph_spans
            and len(matches) >= 3
            and not _CELL_NUMBER.sub("", line.text).strip()
        ):
            expanded.extend(_line_slice(line, m.start(), m.end()) for m in matches)
        else:
            expanded.append(line)
    lines = tuple(expanded)
    replacements = {}
    removed = set()
    for caption in lines:
        match = _CAPTION.match(caption.text.strip()) or _UNNUMBERED_TABLE_CAPTION.match(
            caption.text.strip()
        )
        if not _is_table_caption(match):
            continue
        descriptions = []
        if not _caption_match(caption.text):
            if caption.text[match.end() :].strip():
                continue
            previous = caption
            # A separately styled label can share its baseline with the first
            # caption sentence. Keep the following column's prose out.
            inline = [
                item
                for item in lines
                if 0 <= item.x0 - caption.x1 <= caption.font_size * 2
                and abs(item.y0 - caption.y0) <= caption.font_size * 0.5
                and len(item.text) > 15
            ]
            if len(inline) == 1:
                previous = inline[0]
                descriptions.append(previous)
            for _ in range(4):
                nearby = [
                    item
                    for item in lines
                    if item is not previous
                    and -1 <= previous.y0 - item.y1 <= caption.font_size * 1.5
                    and abs(item.x0 - caption.x0) <= caption.font_size
                    and len(item.text) > 15
                    and sum(c.isalpha() for c in item.text) > 10
                ]
                # Several successive caption lines may fit the vertical
                # window. Select the nearest baseline, retaining ambiguity
                # only for competing fragments on that same baseline.
                if nearby:
                    nearest = max(item.y1 for item in nearby)
                    nearby = [item for item in nearby if nearest - item.y1 < 1]
                if len(nearby) != 1:
                    break
                if any(
                    other is not nearby[0]
                    and abs(other.y0 - nearby[0].y0) < caption.font_size * 0.6
                    and other.x0 > nearby[0].x1 + caption.font_size
                    and (caption.x0 >= width * 0.48 or other.x1 <= width * 0.52)
                    for other in lines
                ):
                    break  # A row of separate headers starts the grid.
                previous = nearby[0]
                descriptions.append(previous)
            if not descriptions or not _caption_match(
                caption.text + " " + " ".join(item.text for item in descriptions)
            ):
                continue
        bottom = (descriptions[-1] if descriptions else caption).y0
        right = max(item.x1 for item in [caption, *descriptions])
        left_limit, right_limit = 0, width
        if right <= width * 0.52:
            right_limit = width * 0.52
        elif caption.x0 >= width * 0.48:
            left_limit = width * 0.48
        # A short caption can still label a page-wide grid. Require aligned
        # numeric cells beyond the column before expanding into adjacent prose.
        outside = [
            item
            for item in lines
            if 0 <= bottom - item.y1 <= caption.font_size * 12
            and item.content_region
            not in {"figure", "ocr-alternative", "native-alternative"}
            and (item.x0 < left_limit or item.x1 > right_limit)
            and _CELL_NUMBER.fullmatch(item.text.strip())
        ]
        adjacent_caption = any(
            _is_table_caption(_CAPTION.match(item.text.strip()))
            and (item.x0 < left_limit or item.x1 > right_limit)
            and min((cell.y0 for cell in outside), default=bottom) <= item.y0
            for item in lines
        )
        continued_column = any(
            a is not b
            and abs(a.x0 - b.x0) <= max(a.font_size, b.font_size)
            and max(a.font_size, b.font_size) * 0.6
            < abs(a.y0 - b.y0)
            < max(a.font_size, b.font_size) * 3
            and all(
                sum(
                    _CELL_NUMBER.fullmatch(c.text.strip()) is not None
                    and left_limit <= c.x0
                    and c.x1 <= right_limit
                    and abs(c.y0 - row.y0) < max(c.font_size, row.font_size) * 0.5
                    for c in lines
                )
                >= 2
                for row in (a, b)
            )
            for a in outside
            for b in outside
        )
        if not adjacent_caption and (
            continued_column
            or any(
                a is not b and abs(a.y0 - b.y0) < min(a.font_size, b.font_size) * 0.5
                for a in outside
                for b in outside
            )
        ):
            left_limit, right_limit = 0, width
        below = sorted(
            (
                item
                for item in lines
                if item.y1 <= bottom + 1
                and item.content_region
                not in {"figure", "ocr-alternative", "native-alternative"}
                and item.x0 >= left_limit
                and item.x1 <= right_limit
            ),
            key=lambda item: (-(item.y0 + item.y1) / 2, item.x0),
        )
        rows: list[list[LayoutLine]] = []
        for line in below:
            if rows and abs(
                (line.y0 + line.y1 - rows[-1][0].y0 - rows[-1][0].y1) / 2
            ) <= 0.5 * min(line.y1 - line.y0, rows[-1][0].y1 - rows[-1][0].y0):
                rows[-1].append(line)
            else:
                rows.append([line])
        grid = []
        last_dense_row = []
        header = []
        numeric_rows = []
        previous_y = bottom
        for row_index, row in enumerate(rows):
            top = max(item.y1 for item in row)
            size = max(item.font_size for item in row)
            # Bridge a real aligned image between the caption and grid, not
            # arbitrary whitespace. Earlier caption fragments are not headers.
            if not grid:
                for obj in sorted(
                    objects, key=lambda obj: -(obj.bbox or (0, 0, 0, 0))[3]
                ):
                    if (
                        obj.object_type == "image"
                        and obj.bbox
                        and left_limit <= obj.bbox[0] * width
                        and obj.bbox[2] * width <= right_limit
                        and top <= obj.bbox[1] * height
                        and 0
                        <= previous_y - obj.bbox[3] * height
                        <= caption.font_size * 4
                    ):
                        previous_y = obj.bbox[1] * height
                        header.clear()
            numeric = sum(
                bool(
                    _CELL_NUMBER.fullmatch(item.text.strip())
                    or _CELL_NUMBER_LIST.fullmatch(item.text.strip())
                )
                for item in row
            )
            if previous_y - top > size * 4:
                # Reaction schemes and thumbnails make data rows taller than
                # prose. Continue only when a repeated numeric grid proves
                # the row relationship; a large gap alone is not enough.
                aligned = sum(
                    bool(
                        _CELL_NUMBER.fullmatch(item.text.strip())
                        or _CELL_ANNOTATED_NUMBER.fullmatch(item.text.strip())
                    )
                    and any(
                        (
                            _CELL_NUMBER.fullmatch(cell.text.strip())
                            or _CELL_ANNOTATED_NUMBER.fullmatch(cell.text.strip())
                        )
                        and abs(item.x0 - cell.x0) <= size
                        for cell in last_dense_row
                    )
                    for item in row
                )
                if aligned < 2 or previous_y - top > size * 10:
                    break
            annotated = sum(
                bool(_CELL_ANNOTATED_NUMBER.fullmatch(item.text.strip()))
                for item in row
            )
            if len(row) < 3 or numeric + annotated < 2:
                if grid and all(len(item.text) < 80 for item in row):
                    # A wrapped label can start above the numeric baseline of
                    # a tall row. Keep it when the next row resumes the same
                    # columns and the label overlaps a known text column.
                    following = rows[row_index + 1 : row_index + 3]
                    if any(
                        len(next_row) >= 3
                        and sum(
                            bool(_CELL_NUMBER.fullmatch(c.text.strip()))
                            for c in next_row
                        )
                        >= 2
                        and 0 <= top - max(c.y1 for c in next_row) <= size * 1.5
                        and all(
                            any(abs(c.x0 - old.x0) <= size for old in last_dense_row)
                            for c in next_row
                        )
                        for next_row in following
                    ) and all(
                        any(abs(item.x0 - cell.x0) <= size for cell in last_dense_row)
                        for item in row
                    ):
                        grid.extend(row)
                        previous_y = min(item.y0 for item in row)
                        continue
                if (
                    grid
                    and numeric == len(row)
                    and previous_y - top <= size * 1.5
                    and all(
                        min(
                            cell.x0 for cell in [*grid, *(c for h in header for c in h)]
                        )
                        - size
                        <= item.x0
                        <= max(cell.x1 for cell in grid)
                        for item in row
                    )
                ):
                    # A shared condition may be vertically centered between
                    # dense data rows. Keep its original position for spans.
                    grid.extend(row)
                    previous_y = min(item.y0 for item in row)
                    continue
                if not grid and not any(_caption_match(item.text) for item in row):
                    header.append(row)
                    previous_y = min(item.y0 for item in row)
                    continue
                if (
                    grid
                    and previous_y - top <= size * 1.5
                    and all(
                        len(item.text) < 80
                        and (
                            any(c.isalpha() for c in item.text)
                            or _CELL_NUMBER.fullmatch(item.text.strip())
                            or re.fullmatch(r"\([^()]+\)", item.text)
                        )
                        and any(
                            min(
                                abs(item.x0 - cell.x0),
                                abs((item.x0 + item.x1 - cell.x0 - cell.x1) / 2),
                            )
                            <= size * 1.5
                            and item.x1
                            <= min(
                                (
                                    other.x0
                                    for other in last_dense_row
                                    if other.x0 > cell.x0 + size * 1.5
                                ),
                                default=right_limit,
                            )
                            + size * 0.5
                            for cell in [*last_dense_row, *numeric_rows[0]]
                        )
                        for item in row
                    )
                ):
                    grid.extend(row)
                    previous_y = min(item.y0 for item in row)
                    continue
                if grid and previous_y - top <= size * 1.5:
                    # A material/cooling group may be centered between dense
                    # rows, in a column absent from every individual data row.
                    # Require repeated positioned labels and a following row
                    # aligned with the existing numeric grid before continuing.
                    following = rows[row_index + 1 : row_index + 3]
                    resumes = any(
                        sum(
                            bool(_CELL_NUMBER.fullmatch(c.text.strip()))
                            for c in next_row
                        )
                        >= 2
                        and len(next_row) >= 3
                        and top - max(c.y1 for c in next_row) <= size * 3
                        and all(
                            any(
                                abs((c.x0 + c.x1 - old.x0 - old.x1) / 2) <= size
                                for old in last_dense_row
                            )
                            for c in next_row
                            if _CELL_NUMBER.fullmatch(c.text.strip())
                        )
                        for next_row in following
                    )
                    repeated = all(
                        len(item.text) <= 40
                        and not _caption_match(item.text)
                        and any(
                            other is not item
                            and len(other.text) <= 40
                            and abs(other.y0 - item.y0) > size * 2
                            and abs((other.x0 + other.x1 - item.x0 - item.x1) / 2)
                            <= size * 0.6
                            and not _caption_match(other.text)
                            for other_row in rows
                            for other in other_row
                        )
                        for item in row
                    )
                    if resumes and repeated:
                        grid.extend(row)
                        previous_y = min(item.y0 for item in row)
                        continue
                if grid and _interstitial_ocr_row(
                    row, last_dense_row, rows[row_index + 1 : row_index + 5], size
                ):
                    # Diagram lettering can sit between experiments in an
                    # otherwise aligned numeric grid. It remains a source
                    # block, but cannot terminate or become a numeric row.
                    continue
                break
            grid.extend(row)
            last_dense_row = row
            numeric_rows.append(row)
            previous_y = min(item.y0 for item in row)

        def aligned_columns(first, second):
            return len(first) == len(second) and all(
                min(abs(a.x0 - b.x0), abs((a.x0 + a.x1 - b.x0 - b.x1) / 2))
                <= max(a.font_size, b.font_size) * 1.5
                for a, b in zip(
                    sorted(first, key=lambda x: x.x0),
                    sorted(second, key=lambda x: x.x0),
                )
            )

        short_grid = (
            len(numeric_rows) == 2 and aligned_columns(*numeric_rows) and bool(header)
        )
        if (
            (len(numeric_rows) < 3 and not short_grid)
            or len(grid) < 6
            or max(item.x1 for item in grid) - min(item.x0 for item in grid)
            < max(item.font_size for item in grid) * 4
        ):
            continue
        # Repeated dense rows define column centers, not the length or count
        # of header fragments. Split multi-column headers using real glyphs.
        reference = list(max(numeric_rows, key=len))
        # Sparse group columns need not appear on a dense numeric row. Include
        # their repeated, separate painted positions before splitting headers.
        for item in grid:
            if len(item.text) > 40 or any(
                min(item.x1, c.x1) > max(item.x0, c.x0) for c in reference
            ):
                continue
            if any(
                other is not item
                and abs(item.y0 - other.y0) > item.font_size * 2
                and abs((item.x0 + item.x1 - other.x0 - other.x1) / 2)
                <= item.font_size * 0.6
                for other in grid
            ):
                reference.append(item)
        centers = sorted((x.x0 + x.x1) / 2 for x in reference)
        boundaries = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
        header_slices = {}
        for line in (item for row in header for item in row):
            if (
                not line.glyph_spans
                or len(line.text) > 100
                or re.match(r"Tab\.\s*(?:\d+|[IVXLCDM]+)\b", line.text)
            ):
                continue
            runs = []
            for g in line.glyph_spans:
                column = sum((g[2] + g[3]) / 2 > edge for edge in boundaries)
                if runs and runs[-1][0] == column:
                    runs[-1][2] = g[1]
                else:
                    runs.append([column, g[0], g[1]])
            # Splits must occur at actual whitespace. A centered group header
            # belongs to a span and must not be cut through a word.
            if len(runs) > 1 and all(
                line.text[a[2] : b[1]].isspace() for a, b in zip(runs, runs[1:])
            ):
                pieces = tuple(_line_slice(line, a, b) for _, a, b in runs)
                if all(
                    abs((piece.x0 + piece.x1) / 2 - centers[column])
                    <= line.font_size * 0.6
                    for (column, _, _), piece in zip(runs, pieces)
                ):
                    header_slices[id(line)] = tuple(
                        replace(piece, content_region="table-cell") for piece in pieces
                    )
        for line in [*(item for row in header for item in row), *grid]:
            replacements[id(line)] = replace(line, content_region="table-cell")
        replacements.update(header_slices)
        # A left-aligned heading or a label followed by a value need not be
        # centered on the numeric reference cell. Cut at wide *painted* gaps,
        # then require every resulting piece to align with a distinct column.
        # This also handles pairs of numbers; ordinary word spaces, grouped
        # digits and centered spanning headings remain a single cell.
        reference = sorted(reference, key=lambda item: item.x0)
        for line in [*(item for row in header for item in row), *grid]:
            if re.match(r"Tab\.\s*(?:\d+|[IVXLCDM]+)\b", line.text):
                continue
            gaps = [
                (a[1], b[0])
                for a, b in zip(line.glyph_spans, line.glyph_spans[1:])
                if line.text[a[1] : b[0]].isspace()
                and b[2] - a[3] >= line.font_size * 0.75
            ]
            if not gaps:
                continue
            starts = [0, *(b for _, b in gaps)]
            ends = [*(a for a, _ in gaps), len(line.text)]
            pieces = [_line_slice(line, a, b) for a, b in zip(starts, ends)]
            columns = []
            for piece in pieces:
                matches = [
                    index
                    for index, cell in enumerate(reference)
                    if min(
                        abs(piece.x0 - cell.x0),
                        abs(piece.x1 - cell.x1),
                        abs(piece.x0 + piece.x1 - cell.x0 - cell.x1) / 2,
                    )
                    <= line.font_size * 0.6
                ]
                if len(matches) != 1:
                    break
                columns.append(matches[0])
            if len(columns) == len(pieces) and all(
                a < b for a, b in zip(columns, columns[1:])
            ):
                replacements[id(line)] = tuple(
                    replace(piece, content_region="table-cell") for piece in pieces
                )
        for line in (item for row in header for item in row):
            if len(line.text) > 100:
                continue
            # Preserve centered parent headings above multiple child headers.
            lower = [item for row in header for item in row if item.y1 < line.y0]
            parent = any(
                abs((a.x0 + a.x1 + b.x0 + b.x1) / 4 - (line.x0 + line.x1) / 2)
                <= line.font_size * 0.6
                and line.x0 <= (a.x0 + a.x1) / 2
                and line.x1 >= (b.x0 + b.x1) / 2
                for a in lower
                for b in lower
                if a.x1 < b.x0
            )
            if not parent:
                previous = replacements.get(id(line), line)
                parts = previous if isinstance(previous, tuple) else (previous,)
                replacements[id(line)] = tuple(
                    replace(piece, content_region="table-cell")
                    for part in parts
                    for piece in (_aligned_table_fragments(part, reference) or (part,))
                )
        if descriptions:
            replacements[id(caption)] = replace(
                caption,
                text=caption.text + " " + " ".join(item.text for item in descriptions),
                x0=min(item.x0 for item in [caption, *descriptions]),
                y0=descriptions[-1].y0,
                x1=right,
                uncertain=any(item.uncertain for item in [caption, *descriptions]),
                extraction_confidence=min(
                    item.extraction_confidence for item in [caption, *descriptions]
                ),
                source_engines=tuple(
                    dict.fromkeys(
                        engine
                        for item in [caption, *descriptions]
                        for engine in item.source_engines
                    )
                ),
            )
            removed.update(id(item) for item in descriptions)
        # Reading order follows the observed grid, not the length of its title.
        # Keep the original caption box; it remains an exact source anchor.
        if left_limit == 0 and right_limit == width:
            replacements[id(caption)] = replace(
                replacements.get(id(caption), caption),
                content_region="spanning-table-caption",
            )
    return tuple(
        part
        for item in lines
        if id(item) not in removed
        for part in (
            replacements[id(item)]
            if isinstance(replacements.get(id(item)), tuple)
            else (replacements.get(id(item), item),)
        )
    )


def _interstitial_ocr_row(row, previous, following, size):
    """Recognize extra OCR ink only inside a stable gap between data columns."""

    def numeric(item):
        return bool(
            _CELL_NUMBER.fullmatch(item.text.strip())
            or _CELL_ANNOTATED_NUMBER.fullmatch(item.text.strip())
        )

    if not previous or not all(
        "ocr" in item.extraction_method
        and len(item.text) <= 32
        and item.text.strip()
        and not numeric(item)
        and not _caption_match(item.text)
        for item in row
    ):
        return False
    old_numeric = [item for item in previous if numeric(item)]
    if len(old_numeric) < 2:
        return False
    for candidate in following:
        if any(len(item.text) > 80 or _caption_match(item.text) for item in candidate):
            return False
        values = [item for item in candidate if numeric(item)]
        if len(values) < 2:
            continue
        if (
            len(values) != len(old_numeric)
            or max(item.y1 for item in row) - max(item.y1 for item in candidate)
            > size * 10
            or not all(
                abs(a.x0 - b.x0) <= size
                for a, b in zip(
                    sorted(old_numeric, key=lambda item: item.x0),
                    sorted(values, key=lambda item: item.x0),
                )
            )
        ):
            return False

        # Both experiments must leave the same horizontal interval empty.
        def within_gap(item, cells):
            ordered = sorted(cells, key=lambda cell: cell.x0)
            return any(
                left.x1 + size < item.x0 and item.x1 < right.x0 - size
                for left, right in zip(ordered, ordered[1:])
            )

        return all(
            within_gap(item, previous) and within_gap(item, candidate) for item in row
        )
    return False


def _table_cells(
    caption: dict[str, object],
    blocks: list[dict[str, object]],
    anchors: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], int, int]:
    candidates: list[tuple[dict[str, object], dict[str, object]]] = []
    caption_order = int(caption["order"])
    page = caption["page"]
    for block in blocks:
        if int(block["order"]) <= caption_order or block["page"] != page:
            continue
        if block["kind"] in {"heading", "caption", "reference"}:
            break
        if block.get("content_region") in {"ocr-alternative", "native-alternative"}:
            continue
        if (
            block.get("content_region") == "table-cell"
            and candidates
            and candidates[0][0].get("content_region") != "table-cell"
        ):
            # The layout stage found a bounded grid below intervening prose
            # or an illustration. Those earlier fragments are not its cells.
            candidates.clear()
        if (
            caption.get("content_region") == "spanning-table-caption"
            and block.get("content_region") != "table-cell"
        ):
            if candidates:
                break
            continue
        if (
            candidates
            and candidates[0][0].get("content_region") == "table-cell"
            and block.get("content_region") != "table-cell"
        ):
            break
        if (
            len(candidates) >= 6
            and len(str(block["text"])) > 160
            and int(block.get("line_count", 1)) >= 2
        ):
            break
        anchor = anchors[str(block["anchor_id"])]
        if anchor["bbox"] is None:
            continue
        if len(candidates) >= 6 and int(block.get("line_count", 1)) >= 2:
            # A full-width paragraph after narrow cells is body/notes, not an
            # extra table row. It remains in canonical text with its anchor.
            left = min(float(a["bbox"][0]) for _, a in candidates)
            right = max(float(a["bbox"][2]) for _, a in candidates)
            box = anchor["bbox"]
            if (
                len(str(block["text"])) > 40
                and right - left >= 0.2
                and float(box[0]) <= left + 0.015
                and float(box[2]) >= right - 0.015
            ):
                break
        candidates.append((block, anchor))
        if len(candidates) >= 1000:
            break

    rows: list[list[tuple[dict[str, object], dict[str, object]]]] = []
    for block, anchor in sorted(
        candidates,
        key=lambda pair: (
            -float(pair[1]["bbox"][1]),
            float(pair[1]["bbox"][0]),
        ),
    ):
        center_y = (float(anchor["bbox"][1]) + float(anchor["bbox"][3])) / 2
        row = next(
            (
                item
                for item in rows
                if abs(
                    (float(item[0][1]["bbox"][1]) + float(item[0][1]["bbox"][3])) / 2
                    - center_y
                )
                <= (
                    0.55
                    * min(
                        float(anchor["bbox"][3]) - float(anchor["bbox"][1]),
                        float(item[0][1]["bbox"][3]) - float(item[0][1]["bbox"][1]),
                    )
                    + 1e-6
                )
            ),
            None,
        )
        if row is None:
            rows.append([(block, anchor)])
        else:
            row.append((block, anchor))
    # Two lines of a text cell can straddle the numeric baseline of a tall
    # experiment row. Both fragments must bracket that baseline, occupy an
    # otherwise empty column, and be closer to it than to any other data row.
    # Retain both original blocks/anchors; only their row association changes.
    removed = set()
    for index in range(1, len(rows) - 1):
        row = rows[index]
        if (
            len(row) < 3
            or sum(bool(_CELL_NUMBER.fullmatch(str(b["text"]).strip())) for b, _ in row)
            < 2
        ):
            continue
        above, below = rows[index - 1], rows[index + 1]
        if len(above) != 1 or len(below) != 1:
            continue
        if not all(
            re.search(r"[A-Za-z\u3400-\u9fff]", str(part[0][0]["text"]))
            for part in (above, below)
        ):
            continue
        a, b = above[0][1]["bbox"], below[0][1]["bbox"]
        height = min(a[3] - a[1], b[3] - b[1])
        mid = statistics.median((p[1]["bbox"][1] + p[1]["bbox"][3]) / 2 for p in row)
        ay, by = (a[1] + a[3]) / 2, (b[1] + b[3]) / 2
        if not (
            by < mid < ay
            and ay - by <= 2.4 * height
            and abs((ay + by) / 2 - mid) <= height * 0.35
            and min(a[2], b[2]) - max(a[0], b[0]) > 0.6 * min(a[2] - a[0], b[2] - b[0])
            and all(
                min(box[2], c[1]["bbox"][2]) <= max(box[0], c[1]["bbox"][0])
                for box in (a, b)
                for c in row
            )
        ):
            continue
        other_centers = [
            statistics.median((p[1]["bbox"][1] + p[1]["bbox"][3]) / 2 for p in other)
            for other in rows
            if other is not row and len(other) >= 3
        ]
        if any(
            abs(y - other) <= abs(y - mid) + height * 0.5
            for y in (ay, by)
            for other in other_centers
        ):
            continue
        row.extend([*above, *below])
        removed.update((index - 1, index + 1))
    rows = [row for index, row in enumerate(rows) if index not in removed]

    # A wrapped text header may occupy an otherwise empty line. Join it only
    # to a neighbouring aligned text cell, never combine two dense numeric rows.
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        if (
            len(row) != 1
            or not index
            or not re.search(r"[A-Za-z]|^\([^()]+\)$", str(row[0][0]["text"]))
        ):
            continue
        box = row[0][1]["bbox"]
        for block, anchor in rows[index - 1]:
            other = anchor["bbox"]
            if (
                re.search(r"[A-Za-z]", str(block["text"]))
                and 0 <= other[1] - box[1] <= 1.2 * (box[3] - box[1]) + 1e-6
                and min(box[2], other[2]) - max(box[0], other[0])
                > 0.6 * min(box[2] - box[0], other[2] - other[0])
            ):
                rows[index - 1].extend(row)
                rows.pop(index)
                break

    def aligned_singleton(row):
        box = row[0][1]["bbox"]
        for other in rows:
            if other is row or len(other) < 2:
                continue
            boxes = [anchor["bbox"] for _, anchor in other]
            if any(
                min(box[2], b[2]) - max(box[0], b[0])
                > 0.6 * min(box[2] - box[0], b[2] - b[0])
                for b in boxes
            ):
                return True
            # A group heading can sit wholly in the gap between its children.
            if all(b[3] < box[1] for b in boxes) and any(
                abs((a[0] + a[2] + b[0] + b[2]) / 4 - (box[0] + box[2]) / 2)
                <= (box[3] - box[1]) * 0.6
                for a in boxes
                for b in boxes
                if a[2] < b[0]
            ):
                return True
        return False

    def numeric_fragment_between_rows(row):
        block, anchor = row[0]
        text = str(block["text"]).strip()
        if not re.fullmatch(r"[−+\-\d.,;%\s]+", text) or not any(
            c.isdigit() for c in text
        ):
            return False
        center = (anchor["bbox"][1] + anchor["bbox"][3]) / 2
        other_centers = [
            (other[0][1]["bbox"][1] + other[0][1]["bbox"][3]) / 2
            for other in rows
            if len(other) >= 2
        ]
        if (
            other_centers
            and min(other_centers) < center < max(other_centers)
            and aligned_singleton(row)
        ):
            # A multiline numeric fragment can straddle two rows. Dropping it
            # loses searchable evidence; merging it into either row invents a
            # relationship. Retain the positioned fragment and flag it.
            block["uncertain"] = True
            return True
        return False

    rows = [
        row
        for row in rows
        if len(row) >= 2
        or (row[0][0].get("content_region") == "table-cell" and aligned_singleton(row))
        or numeric_fragment_between_rows(row)
    ]
    if len(rows) < 2:
        return [], 0, 0

    # Choose column positions once for the whole table. Empty group-label cells
    # must not shift every numeric value one column left on subsequent rows.
    def row_columns(row):
        columns = []
        for pair in sorted(row, key=lambda p: float(p[1]["bbox"][0])):
            box = pair[1]["bbox"]
            if not any(
                min(box[2], c[2]) - max(box[0], c[0])
                > 0.6 * min(box[2] - box[0], c[2] - c[0])
                for c in columns
            ):
                columns.append(box)
        return columns

    dense = [
        row
        for row in rows
        if sum(bool(_CELL_NUMBER.fullmatch(str(b["text"]).strip())) for b, _ in row)
        >= 2
    ]
    first_data_y = max(
        ((a["bbox"][1] + a["bbox"][3]) / 2 for row in dense for _, a in row),
        default=0,
    )

    def repeated_group(pair):
        block, anchor = pair
        box = anchor["bbox"]
        if (
            block.get("content_region") != "table-cell"
            or len(str(block["text"])) > 40
            or (box[1] + box[3]) / 2 > first_data_y
        ):
            return False
        return any(
            other is not block
            and len(str(other["text"])) <= 40
            and abs((a["bbox"][1] + a["bbox"][3] - box[1] - box[3]) / 2)
            > (box[3] - box[1]) * 2
            and abs((a["bbox"][0] + a["bbox"][2] - box[0] - box[2]) / 2)
            <= (box[3] - box[1]) * 0.6
            for row in rows
            for other, a in row
        )

    column_boxes = (
        row_columns(
            [
                pair
                for row in rows
                for pair in row
                if _CELL_NUMBER.fullmatch(str(pair[0]["text"]).strip())
                or (row in dense and len(str(pair[0]["text"])) < 80)
                or repeated_group(pair)
            ]
        )
        if dense
        else max((row_columns(row) for row in rows), key=len)
    )
    column_boxes.sort(key=lambda box: (box[0] + box[2]) / 2)
    column_count = len(column_boxes)
    cells: list[dict[str, object]] = []
    for row_index, row in enumerate(rows, start=1):
        for block, anchor in sorted(row, key=lambda pair: float(pair[1]["bbox"][0])):
            x0, _, x1, _ = anchor["bbox"]
            column_index = (
                min(
                    range(column_count),
                    key=lambda i: (
                        -max(
                            0, min(x1, column_boxes[i][2]) - max(x0, column_boxes[i][0])
                        )
                        / max(
                            1e-9, min(x1 - x0, column_boxes[i][2] - column_boxes[i][0])
                        ),
                        abs(x0 - column_boxes[i][0]),
                    ),
                )
                + 1
            )
            # Keep each original block, including both lines of a header. Two
            # vertically stacked fragments at the same x occupy one column.
            cells.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "text": block["text"],
                    "block_id": block["id"],
                    "anchor_id": anchor["id"],
                    "bbox": anchor["bbox"],
                }
            )
    cells, row_count = _table_spans(cells, len(rows), column_boxes)
    _entry_variant_spans(cells)
    return cells, row_count, column_count


def _entry_variant_spans(cells):
    """Associate a blank label only through repeated explicit primed entry IDs.

    Ordinary blanks, including top-aligned shared-looking conditions, are not
    sufficient. The source entry reference is recorded; values are never copied.
    """
    grouped = {}
    for cell in cells:
        grouped.setdefault(cell["row"], []).append(cell)
    entry_columns = {
        c["column"]
        for c in cells
        if c["row"] <= 2
        and c["text"].strip().casefold().rstrip(".")
        in {"entry", "run", "no", "序号", "编号"}
    }
    for column in entry_columns:
        pairs = []
        for row, group in grouped.items():
            entries = [c for c in group if c["column"] == column]
            previous = grouped.get(row - 1, [])
            if len(entries) != 1:
                continue
            match = re.fullmatch(r"(\d+)[′'″]+", entries[0]["text"].strip())
            if match and any(
                c["column"] == column and c["text"].strip() == match[1]
                for c in previous
            ):
                pairs.append((previous, group))
        if len(pairs) < 2:
            continue
        for previous, group in pairs:
            for cell in previous:
                if (
                    cell["column"] != column
                    and cell.get("row_span", 1) == 1
                    and cell.get("column_span", 1) == 1
                    and len(cell["text"]) <= 80
                    and re.search(r"[A-Za-z\u3400-\u9fff]", cell["text"])
                    and not _CELL_ANNOTATED_NUMBER.fullmatch(cell["text"].strip())
                    and not any(c["column"] == cell["column"] for c in group)
                ):
                    cell.update(row_span=2, span_evidence="explicit-entry-variant")


def _table_spans(cells, row_count, column_boxes):
    """Record centered group extents without copying values into blank cells.

    Geometric spans remain uncertain evidence. A value at the top of a run of
    blanks is not proof of a shared condition; repeated, centered groups are.
    """
    centers = [(b[0] + b[2]) / 2 for b in column_boxes]

    def numeric(cell):
        return bool(_CELL_NUMBER.fullmatch(str(cell["text"]).strip()))

    grouped = {
        row: [c for c in cells if c["row"] == row] for row in range(1, row_count + 1)
    }
    numeric_counts = {
        col: sum(numeric(c) and c["column"] == col for c in cells)
        for col in range(1, len(centers) + 1)
    }
    frequent = {
        col
        for col, count in numeric_counts.items()
        if count >= max(numeric_counts.values(), default=0) * 0.6
    }
    data = [
        r
        for r, group in grouped.items()
        if sum(map(numeric, group)) >= 3
        and sum(numeric(c) and c["column"] in frequent for c in group)
        >= min(3, len(frequent))
    ]
    if len(data) < 2:
        return cells, row_count
    ys = {
        r: statistics.median(
            (c["bbox"][1] + c["bbox"][3]) / 2 for c in grouped[r] if numeric(c)
        )
        for r in data
    }
    first_y = ys[data[0]]
    shared = {}
    for column in range(1, len(centers) + 1):
        column_cells = [
            c
            for c in cells
            if c["column"] == column
            and (c["bbox"][1] + c["bbox"][3]) / 2
            <= first_y + (c["bbox"][3] - c["bbox"][1]) * 0.5
        ]
        if not 2 <= len(column_cells) < len(data):
            continue
        column_cells.sort(key=lambda c: -(c["bbox"][1] + c["bbox"][3]) / 2)
        cy = [(c["bbox"][1] + c["bbox"][3]) / 2 for c in column_cells]
        edges = [
            float("inf"),
            *[(a + b) / 2 for a, b in zip(cy, cy[1:])],
            float("-inf"),
        ]
        spans = []
        for i, c in enumerate(column_cells):
            group = [r for r in data if edges[i] >= ys[r] > edges[i + 1]]
            if (
                len(group) < 2
                or abs(statistics.mean(ys[r] for r in group) - cy[i])
                > (c["bbox"][3] - c["bbox"][1]) * 0.5
            ):
                break
            spans.append((c, group))
        else:
            for c, group in spans:
                shared[id(c)] = group
    # Remove only rows consisting wholly of shared labels between data rows.
    removed = {
        r
        for r, group in grouped.items()
        if r not in data and group and all(id(c) in shared for c in group)
    }
    renumber = {
        old: i + 1 for i, old in enumerate(r for r in grouped if r not in removed)
    }
    for c in cells:
        if id(c) in shared:
            span = shared[id(c)]
            c.update(
                row=renumber[span[0]],
                row_span=renumber[span[-1]] - renumber[span[0]] + 1,
                span_evidence="centered-repeated-groups",
            )
        else:
            c["row"] = renumber[c["row"]]
    first_data = renumber[data[0]]
    # Resolve lower group headings first. An upper heading must use leaf
    # positions, not the center of a group already spanning those leaves.
    for c in sorted(cells, key=lambda cell: -cell["row"]):
        if c["row"] >= first_data:
            continue
        box = c["bbox"]
        center = (box[0] + box[2]) / 2
        tolerance = (box[3] - box[1]) * 0.6
        siblings = [x for x in cells if x is not c and x["row"] == c["row"]]
        candidates = []
        for a in range(len(centers)):
            for b in range(a + 1, len(centers)):
                if any(
                    centers[a] - tolerance
                    < (x["bbox"][0] + x["bbox"][2]) / 2
                    < centers[b] + tolerance
                    for x in siblings
                ):
                    continue
                children = [
                    x
                    for x in cells
                    if c["row"] < x["row"] < first_data
                    and a + 1 <= x["column"] <= b + 1
                    and x.get("column_span", 1) == 1
                ]
                if len({x["column"] for x in children}) != b - a + 1:
                    continue
                child_centers = [
                    statistics.median(
                        (x["bbox"][0] + x["bbox"][2]) / 2
                        for x in children
                        if x["column"] == column
                    )
                    for column in (a + 1, b + 1)
                ]
                distance = min(
                    abs((centers[a] + centers[b]) / 2 - center),
                    abs(statistics.mean(child_centers) - center),
                )
                if distance > tolerance:
                    continue
                # A label already centered on a leaf column is not a group
                # unless its painted width actually covers several children.
                if min(abs(center - x) for x in centers) <= tolerance and not (
                    box[0] <= centers[a] and box[2] >= centers[b]
                ):
                    continue
                candidates.append((distance, a, b))
        if candidates:
            _, a, b = min(candidates)
            c.update(
                column=a + 1, column_span=b - a + 1, span_evidence="centered-header"
            )
    return cells, len(renumber)


def _table_local_warnings(table, blocks, anchors):
    """Flag observable column collisions or nearby omitted numeric rows."""
    cells = table.get("cells", [])
    if not cells:
        return []
    by_id = {b["id"]: b for b in blocks}
    positioned = [(c, anchors[c["anchor_id"]]["bbox"]) for c in cells]
    positioned = [(c, box) for c, box in positioned if box]
    warnings = []
    data_rows = {}
    for c in cells:
        numeric_text = re.sub(r"(?<=[−+±\-])\s+(?=\d)", "", c["text"].strip())
        if (
            _CELL_NUMBER.fullmatch(numeric_text)
            or _CELL_ANNOTATED_NUMBER.fullmatch(numeric_text)
            or re.fullmatch(r"\d+[′'″]+", c["text"].strip())
        ):
            data_rows.setdefault(c["row"], []).append(c)
    data_rows = {r: group for r, group in data_rows.items() if len(group) >= 2}
    label_columns = {
        c["column"]
        for c in cells
        if c["row"] in data_rows
        and len(c["text"]) <= 80
        and re.search(r"[A-Za-z\u3400-\u9fff]", c["text"])
        and not _CELL_ANNOTATED_NUMBER.fullmatch(c["text"].strip())
    }
    for row, group in data_rows.items():
        missing = [
            col
            for col in label_columns
            if not any(
                c["column"] <= col < c["column"] + c.get("column_span", 1)
                and c["row"] <= row < c["row"] + c.get("row_span", 1)
                for c in cells
            )
        ]
        if missing:
            cell = group[0]
            warnings.append(
                {
                    "code": "TABLE_ROW_CONTEXT_MISSING",
                    "object_id": table["id"],
                    "anchor_id": cell["anchor_id"],
                    "page": by_id[cell["block_id"]]["page"],
                    "bbox": anchors[cell["anchor_id"]]["bbox"],
                    "row": row,
                    "columns": missing,
                    "detail": "This numeric row has blank label/condition cells without a supported span; do not inherit another experiment's labels automatically.",
                }
            )
    for c, box in positioned:
        collision = any(
            other is not c
            and other["row"] == c["row"]
            and other["column"] == c["column"]
            and other_box[0] - box[2] > 1.5 * (box[3] - box[1])
            and abs((other_box[1] + other_box[3] - box[1] - box[3]) / 2)
            < 0.5 * (box[3] - box[1])
            for other, other_box in positioned
        )
        if collision:
            warnings.append(
                {
                    "code": "TABLE_COLUMN_COLLISION",
                    "object_id": table["id"],
                    "anchor_id": c["anchor_id"],
                    "page": by_id[c["block_id"]]["page"],
                    "bbox": box,
                    "detail": "Separated cells occupy the same table row and column; inspect this local header/column association.",
                }
            )
    numbers = [
        (c, box) for c, box in positioned if _CELL_NUMBER.fullmatch(c["text"].strip())
    ]
    if len(numbers) < 3:
        return warnings
    bottom = min(box[1] for _, box in numbers)
    height = sorted(box[3] - box[1] for _, box in numbers)[len(numbers) // 2]
    page = by_id[cells[0]["block_id"]]["page"]
    members = {c["block_id"] for c in cells}
    outside = [
        (b, anchors[b["anchor_id"]]["bbox"])
        for b in blocks
        if b["id"] not in members
        and b["page"] == page
        and not str(b.get("content_region", "")).endswith("alternative")
        and _CELL_NUMBER.fullmatch(str(b["text"]).strip())
    ]
    nearby = [
        (b, box)
        for b, box in outside
        if box
        and 0 < bottom - box[1] <= height * 3
        and any(
            abs((box[0] + box[2] - nb[0] - nb[2]) / 2) < height for _, nb in numbers
        )
    ]
    for b, box in nearby:
        peers = [
            (other, ob)
            for other, ob in nearby
            if abs((ob[1] + ob[3] - box[1] - box[3]) / 2) < height * 0.6
        ]
        if len(peers) >= 3:
            warnings.append(
                {
                    "code": "TABLE_CONTINUATION_UNRESOLVED",
                    "object_id": table["id"],
                    "anchor_id": b["anchor_id"],
                    "page": page,
                    "bbox": box,
                    "detail": "Nearby aligned numeric cells are outside the table; inspect possible truncated continuation.",
                }
            )
            break
    return warnings
