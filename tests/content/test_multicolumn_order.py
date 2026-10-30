"""Self-authored layouts: a page midpoint must not split a physical column."""

from dataclasses import asdict, replace

import pytest

from aletheia_nexus.content.models import LayoutLine
from aletheia_nexus.content.parser import ParserConfig, _order_lines, _prose_columns


def column(x, width=145, count=4, y=700):
    return [
        LayoutLine(
            f"Continuous prose in column {x}, line {i}.",
            x,
            y - i * 12,
            x + width,
            y - i * 12 + 9,
            9,
        )
        for i in range(count)
    ]


@pytest.mark.parametrize(
    "positions,width", [((35, 215, 395), 145), ((25, 170, 315, 460), 115)]
)
def test_multiple_columns_keep_short_tail_with_its_own_paragraph(positions, width):
    columns = [column(x, width) for x in positions]
    columns[1][2] = replace(columns[1][2], x1=positions[1] + 25)
    lines = [line for row in zip(*columns) for line in row]
    original = {id(line): asdict(line) for line in lines}
    ordered = _order_lines(tuple(lines), 600, ParserConfig())
    assert ordered == [line for part in columns for line in part]
    assert {id(line): asdict(line) for line in ordered} == original


def test_spanning_heading_stays_above_off_center_columns():
    left, right = column(35, 95), column(155, 190)
    heading = LayoutLine("A full-width section heading", 35, 725, 555, 737, 12)
    ordered = _order_lines(tuple(left + right + [heading]), 600, ParserConfig())
    assert ordered == [heading, *left, *right]


@pytest.mark.parametrize("region", ["figure", "table-cell", "spanning-table-caption"])
def test_visual_regions_are_not_reclassified_as_prose_columns(region):
    lines = [replace(line, content_region=region) for line in column(35) + column(215)]
    assert _prose_columns(lines) is None


def test_side_labels_and_nonoverlapping_sections_do_not_define_columns():
    assert _prose_columns(column(35) + column(215) + column(395, count=1)) is None
    assert _prose_columns(column(35) + column(215, y=500)) is None
    crossing = LayoutLine("A line crossing the supposed gutter", 35, 750, 370, 759, 9)
    assert _prose_columns(column(35) + column(215) + [crossing]) is None


def test_two_column_caption_does_not_interleave_three_column_body_below():
    body = [
        replace(line, dominant_font="Prose")
        for x in (35, 215, 395)
        for line in column(x, y=600)
    ]
    captions = [
        LayoutLine(
            "Caption text continued across this half of the figure.",
            x,
            y,
            x + 250,
            y + 8,
            8,
            dominant_font="Caption",
        )
        for x in (35, 305)
        for y in (650, 640)
    ]
    labels = [LayoutLine("Plot label", 230, 720, 300, 728, 8, content_region="figure")]
    lines = captions + labels + body
    before = {id(line): asdict(line) for line in lines}
    ordered = _order_lines(tuple(lines), 600, ParserConfig())
    body_ids = {id(line) for line in body}
    assert [line for line in ordered if id(line) in body_ids] == body
    assert {id(line): asdict(line) for line in ordered} == before
