"""Table layout variants independent of paper identifiers and measurements."""

import pytest

from aletheia_nexus.content.models import LayoutLine, PageLayout
from aletheia_nexus.content.parser import (
    ParserConfig,
    _is_page_furniture,
    _order_lines,
    _prepare_table_lines,
    _table_cells,
)


def cells_from(lines, width=600, height=800):
    ordered = _order_lines(
        _prepare_table_lines(tuple(lines), width), width, ParserConfig()
    )
    layout = PageLayout(page=1, width=width, height=height)
    ordered = [item for item in ordered if not _is_page_furniture(item, layout, {"#"})]
    blocks, anchors = [], {}
    for i, line in enumerate(ordered):
        bid = str(i)
        blocks.append(
            dict(
                id=bid,
                anchor_id=bid,
                page=1,
                order=i,
                kind="caption"
                if line.text.startswith(("Table", "Figure"))
                else "paragraph",
                text=line.text,
                content_region=line.content_region,
            )
        )
        anchors[bid] = dict(
            id=bid,
            bbox=[line.x0 / width, line.y0 / height, line.x1 / width, line.y1 / height],
        )
    captions = [b for b in blocks if b["text"].startswith("Table")]
    return blocks, [_table_cells(b, blocks, anchors) for b in captions]


@pytest.mark.parametrize("scale", [0.6, 1.0, 1.8])
@pytest.mark.parametrize("caption_width", [120, 340, 440])
@pytest.mark.parametrize("bottom", [40, 500])
def test_caption_grid_and_integer_cells_survive_scale_position_and_title_length(
    scale, caption_width, bottom
):
    def line(text, x, y, width=30):
        return LayoutLine(
            text, x * scale, y * scale, (x + width) * scale, (y + 7) * scale, 7 * scale
        )

    lines = [
        line("Table 2. Measured performance.", 30, bottom + 62, caption_width),
        line("Left column discussion.", 30, bottom + 95, 240),
        line("Figure 4. Separate figure caption.", 330, bottom + 95, 230),
        line("8", 290, 10),
    ]
    for y, row in [
        (bottom + 43, ["Material", "Current", "Yield", "Efficiency"]),
        (bottom + 28, ["Sample A", "27", "68", "94"]),
        (bottom + 14, ["Sample B", "29", "63", "89"]),
        (bottom, ["Sample C", "31", "59", "82"]),
    ]:
        lines.extend(line(t, x, y) for t, x in zip(row, [30, 180, 340, 530]))
    blocks, tables = cells_from(lines, 600 * scale, 800 * scale)
    cells, rows, columns = tables[0]
    assert (rows, columns) == (4, 4)
    assert {(c["row"], c["column"], c["text"]) for c in cells} >= {
        (1, 2, "Current"),
        (1, 3, "Yield"),
        (1, 4, "Efficiency"),
        (2, 1, "Sample A"),
        (2, 2, "27"),
        (2, 3, "68"),
        (2, 4, "94"),
        (4, 2, "31"),
        (4, 3, "59"),
        (4, 4, "82"),
    }
    assert not any(b["text"] == "8" for b in blocks)
    assert blocks.index(
        next(b for b in blocks if b["text"].startswith("Figure"))
    ) < blocks.index(next(b for b in blocks if b["text"].startswith("Table")))


def test_many_header_lines_and_wrapped_cells_have_no_fixed_count_limit():
    def line(t, x, y, w=24):
        return LayoutLine(t, x, y, x + w, y + 6, 6)

    lines = [line("Table 5. Measurements by sample.", 30, 760, 250)]
    # Five stacked header lines and twelve columns, beyond the former 3/8 limits.
    for y in [748, 740, 732, 724, 716]:
        lines.extend(
            line(f"H{column}", x, y) for column, x in enumerate(range(30, 570, 45))
        )
    for y in [703, 680, 657]:
        lines.extend(
            line(str(column + 2), x, y) for column, x in enumerate(range(30, 570, 45))
        )
        lines.extend(line("note", x, y - 8) for x in [30, 75, 120, 165])
    prepared = _prepare_table_lines(tuple(lines), 600)
    assert all(
        item.content_region == "table-cell"
        for item in prepared
        if not item.text.startswith("Table")
    )


def test_side_by_side_single_column_tables_remain_separate():
    lines = []
    for offset, label in [(0, "1"), (300, "2")]:

        def line(t, x, y, w=25):
            return LayoutLine(t, x + offset, y, x + offset + w, y + 6, 6)

        lines.append(line(f"Table {label}. Measured results.", 30, 740, 230))
        for y, row in [
            (725, ["Sample", "Yield", "FE"]),
            (712, ["A", "12", "89"]),
            (699, ["B", "23", "78"]),
            (686, ["C", "34", "67"]),
        ]:
            lines.extend(line(t, x, y) for t, x in zip(row, [30, 140, 240]))
    _, tables = cells_from(lines)
    assert len(tables) == 2
    assert all((rows, cols) == (4, 3) for _, rows, cols in tables)
