"""Independent layout variants: spans are evidence, never value imputation."""

from dataclasses import replace

import pytest
from test_table_generalization import cells_from

from aletheia_nexus.content.models import LayoutLine, PageLayout, validate_page_layout
from aletheia_nexus.content.parser import _prepare_table_lines
from aletheia_nexus.content.table_layout import (
    _entry_variant_spans,
    _table_local_warnings,
)


@pytest.mark.parametrize("prime", ["′", "'"])
def test_repeated_entry_references_link_only_the_blank_descriptive_cell(prime):
    cells = [dict(row=1, column=1, text="Entry")]
    for row, entry, label in [
        (2, "2", "Modifier-A"),
        (3, "2" + prime, None),
        (4, "7", "Modifier-B"),
        (5, "7" + prime, None),
    ]:
        cells.extend(
            [dict(row=row, column=1, text=entry), dict(row=row, column=3, text="45b")]
        )
        if label:
            cells.append(dict(row=row, column=2, text=label))
    _entry_variant_spans(cells)
    labels = [c for c in cells if c["column"] == 2]
    assert all(
        c["row_span"] == 2 and c["span_evidence"] == "explicit-entry-variant"
        for c in labels
    )
    assert len(cells) == 11  # No synthetic repeated values or source anchors.


@pytest.mark.parametrize(
    "reason", ["single-pair", "different-entry", "explicit-label", "not-entry-column"]
)
def test_primed_reference_never_fills_unrelated_blanks(reason):
    cells = [
        dict(row=1, column=1, text="Time" if reason == "not-entry-column" else "Entry")
    ]
    for row, entry, label in [
        (2, "2", "Modifier-A"),
        (3, "3′" if reason == "different-entry" else "2′", None),
        (4, "7", "Modifier-B"),
        (5, "7′", None),
    ]:
        if reason == "single-pair" and row >= 4:
            continue
        cells += [
            dict(row=row, column=1, text=entry),
            dict(row=row, column=3, text="45"),
        ]
        if label or reason == "explicit-label":
            cells.append(dict(row=row, column=2, text=label or "Other"))
    _entry_variant_spans(cells)
    assert all("row_span" not in c for c in cells)


@pytest.mark.parametrize("value", ["12.4", "− 12.4", "+ 12.4"])
def test_blank_row_label_is_a_local_gap_not_an_inferred_experiment(value):
    cells = []
    blocks, anchors = [], {}
    for row, label in [
        (1, "Electrode"),
        (2, "Group-A"),
        (3, None),
        (4, "Group-B"),
        (5, None),
    ]:
        for col, text in [
            (1, label),
            (2, "ratio" if row == 1 else "0.07"),
            (3, "ee" if row == 1 else value),
        ]:
            if text is None:
                continue
            bid = f"{row}-{col}"
            box = [col * 0.1, 1 - row * 0.1, col * 0.1 + 0.05, 1 - row * 0.1 + 0.02]
            cells.append(
                dict(
                    row=row,
                    column=col,
                    text=text,
                    block_id=bid,
                    anchor_id=bid,
                    bbox=box,
                )
            )
            blocks.append(dict(id=bid, page=1, anchor_id=bid, text=text))
            anchors[bid] = dict(bbox=box)
    warnings = _table_local_warnings(dict(id="t1", cells=cells), blocks, anchors)
    gaps = [w for w in warnings if w["code"] == "TABLE_ROW_CONTEXT_MISSING"]
    assert [(w["row"], w["columns"]) for w in gaps] == [(3, [1]), (5, [1])]
    assert all(w["anchor_id"] in anchors and w["page"] == 1 for w in gaps)
    assert all("row_span" not in c for c in cells)


def line(text, x, y, width=18, scale=1):
    return LayoutLine(
        text, x * scale, y * scale, (x + width) * scale, (y + 6) * scale, 6 * scale
    )


@pytest.mark.parametrize("scale", [0.7, 1, 1.6])
@pytest.mark.parametrize("group_size", [2, 3, 4])
def test_centered_conditions_and_multilevel_headers(scale, group_size):
    def cell(t, x, y, w=18):
        return line(t, x, y, w, scale)

    lines = [
        cell("Table 6. Paired measurements.", 40, 730, 400),
        cell("Response", 319, 715, 60),
        cell("Group", 40, 702),
        cell("Time", 140, 702),
        cell("Trial A", 270, 702, 58),
        cell("Trial B", 370, 702, 58),
    ]
    for group in range(2):
        ys = [688 - (group * group_size + i) * 10 for i in range(group_size)]
        lines.append(cell(str(group + 6), 40, sum(ys) / len(ys)))
        for i, y in enumerate(ys):
            lines += [
                cell(str(i + 1), 140, y),
                cell(str(20 + group * 10 + i), 290, y),
                cell(str(60 + group * 10 + i), 390, y),
            ]
    _, tables = cells_from(lines, 600 * scale, 800 * scale)
    cells, _, columns = tables[0]
    assert columns == 4
    assert next(c for c in cells if c["text"] == "Response")["column_span"] == 2
    shared = [c for c in cells if c["text"] in {"6", "7"} and c["column"] == 1]
    assert len(shared) == 2
    assert all(c["row_span"] == group_size for c in shared)
    assert len([c for c in cells if c["column"] == 3]) == 2 * group_size + 2


def test_top_aligned_sparse_values_do_not_fill_blanks():
    lines = [line("Table 2. Sparse observations.", 30, 730, 400)]
    lines += [
        line(t, x, 715)
        for t, x in zip(["Batch", "Time", "A", "B"], [30, 130, 280, 400])
    ]
    for i in range(6):
        y = 700 - 10 * i
        lines.extend(
            line(str(i + j), x, y) for j, x in [(1, 130), (20, 280), (60, 400)]
        )
        if i in {0, 3}:
            lines.append(line(str(i + 10), 30, y))
    _, tables = cells_from(lines)
    assert all("row_span" not in c for c in tables[0][0])


def glyph_line(parts, y):
    text, spans = "", []
    for word, center in parts:
        if text:
            text += " "
        start = center - len(word) * 1.5
        for i, char in enumerate(word):
            offset = len(text)
            text += char
            if not char.isspace():
                spans.append((offset, offset + 1, start + i * 3, start + (i + 1) * 3))
    return LayoutLine(
        text, spans[0][2], y, spans[-1][3], y + 6, 6, glyph_spans=tuple(spans)
    )


def test_native_column_slices_preserve_centered_group_header():
    lines = [
        line("Table 3. Measurement matrix.", 30, 740, 500),
        glyph_line([("Shared response", 350)], 727),
        glyph_line([("Time", 100), ("Result A", 300), ("Result B", 400)], 715),
    ]
    for i, y in enumerate([700, 691, 682]):
        lines.append(glyph_line([(str(i + 1), 100), ("23", 300), ("74", 400)], y))
    prepared = _prepare_table_lines(tuple(lines), 600)
    texts = [x.text for x in prepared]
    assert "Shared response" in texts
    assert "Result A" in texts and "Result B" in texts
    assert "Time Result A Result B" not in texts
    for item in prepared:
        validate_page_layout(PageLayout(1, 600, 800, lines=(item,)))


def test_sparse_mean_row_stays_separate_from_measurements():
    lines = [line("Table 9. Time series.", 270, 740, 230)]
    for y, title, numbers in [
        (725, "t/h", ["1", "2", "3"]),
        (713, "W/%", ["21", "31", "41"]),
        (701, "η/%", ["81", "71", "61"]),
    ]:
        lines.append(line(title, 280, y))
        lines += [line(n, x, y) for n, x in zip(numbers, [340, 410, 480])]
    lines += [line("平均", 270, 689, 38), line("0.17", 410, 689)]
    lines.append(line("Unrelated footer", 270, 620, 200))
    prepared = _prepare_table_lines(tuple(lines), 600)
    assert next(x for x in prepared if x.text == "平均").content_region == "table-cell"
    assert next(x for x in prepared if x.text == "0.17").content_region == "table-cell"
    assert prepared[-1].content_region == "body"


def test_invalid_glyph_offsets_are_rejected():
    item = glyph_line([("Unit", 50)], 700)
    validate_page_layout(PageLayout(1, 600, 800, lines=(item,)))
    with pytest.raises(ValueError, match="glyph spans"):
        validate_page_layout(
            PageLayout(
                1, 600, 800, lines=(replace(item, glyph_spans=((0, 9, 40, 50),)),)
            )
        )


def test_zero_advance_combining_glyph_is_valid_text():
    item = LayoutLine(
        "a\u0301",
        40,
        700,
        45,
        706,
        6,
        glyph_spans=((0, 1, 40, 45), (1, 2, 45, 45)),
    )
    validate_page_layout(PageLayout(1, 600, 800, lines=(item,)))


def test_numeric_lists_keep_their_own_table_rows():
    lines = [line("Table 7. Screening.", 30, 740, 490)]
    lines += [
        line("Run", 35, 725),
        line("Treatment", 110, 725, 120),
        line("Responses", 450, 725, 65),
    ]
    for index, values in enumerate(["71", "62, 67, 59", "0, 0", "58; 69"]):
        y = 710 - index * 10
        lines += [
            line(str(index + 1), 35, y),
            line("Different material", 110, y, 160),
            line(values, 450, y, 65),
        ]
    prepared = _prepare_table_lines(tuple(lines), 600)
    for value in ["71", "62, 67, 59", "0, 0", "58; 69"]:
        assert (
            next(x for x in prepared if x.text == value).content_region == "table-cell"
        )
    _, tables = cells_from(lines)
    cells = tables[0][0]
    assert (
        len(
            {
                c["row"]
                for c in cells
                if c["text"] in {"71", "62, 67, 59", "0, 0", "58; 69"}
            }
        )
        == 4
    )


def test_three_header_levels_use_leaf_positions():
    lines = [
        line("Table 8. Paired response.", 30, 740, 480),
        line("Overall response", 347, 728, 110),
        line("R/%", 390, 717, 20),
        line("Time", 50, 707),
        line("Type A", 330, 707, 40),
        line("Type B", 430, 707, 40),
    ]
    for index, y in enumerate([696, 686, 676]):
        lines += [
            line(str(index + 1), 50, y),
            line(str(21 + index), 332, y),
            line(str(65 + index), 432, y),
        ]
    _, tables = cells_from(lines)
    for text in ["R/%", "Overall response"]:
        cell = next(c for c in tables[0][0] if c["text"] == text)
        assert cell["column"] == 2
        assert cell["column_span"] == 2


def test_ambiguous_numeric_fragment_is_retained_and_flagged():
    # The large blank region stands for a reaction diagram above the grid.
    # It intentionally prevents the early dense-grid detector from taking over.
    lines = [
        line("Table 2. Reaction screening.", 30, 740, 400),
        line("Run", 30, 570),
        line("Response", 300, 570, 80),
        line("1", 30, 555),
        line("2", 30, 543),
        line("3", 30, 531),
        line("zero", 300, 531, 40),
        LayoutLine("57 63, 61", 300, 543, 355, 561, 6),
        line("999", 300, 480),
    ]
    blocks, tables = cells_from(lines)
    values = [c["text"] for c in tables[0][0]]
    assert "57 63, 61" in values
    assert "999" not in values
    assert next(b for b in blocks if b["text"] == "57 63, 61")["uncertain"]
