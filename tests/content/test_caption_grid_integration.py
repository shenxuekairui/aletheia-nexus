"""Styled captions and left-aligned cells must reach the existing table stages."""

from dataclasses import replace

import pytest

from aletheia_nexus.content.indexed_tables import indexed_grids
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject
from aletheia_nexus.content.table_layout import _prepare_table_lines


def grid_page(*, scale=1, ruled=False, adjacent_prose=False):
    data = [
        ("Table 7", 40, 740, 72, 748),
        ("Comparison of alternative experimental conditions", 80, 739, 295, 750),
        ("unrelated reaction diagram text", 90, 650, 220, 660),
        ("Entry", 40, 590, 65, 598),
        ("Deviation from the standard procedure", 90, 590, 218, 598),
        ("Yield (%)", 250, 590, 295, 600),
    ]
    for row, condition, value in [
        (1, "None", "41"),
        (2, "Solvent P/Q/R", "12/23/34"),
        (3, "Without electricity", "nd"),
    ]:
        y = 590 - row * 20
        data.extend(
            [
                (str(row), 40, y, 44, y + 8),
                (condition, 90, y, 90 + len(condition) * 4, y + 8),
                (value, 250, y, 250 + len(value) * 4, y + 8),
            ]
        )
    data.append(
        ("a Conditions and measurement method stay separate.", 40, 510, 295, 518)
    )
    if adjacent_prose:
        data.append(("An unrelated paragraph in the other column.", 320, 594, 575, 604))
    return PageLayout(
        page=1,
        width=600 * scale,
        height=800 * scale,
        lines=tuple(
            LayoutLine(text, *(v * scale for v in box), 8 * scale)
            for text, *box in data
        ),
        objects=tuple(
            PageObject(
                "horizontal-rule",
                str(i),
                bbox=(40 / 600, y / 800, 300 / 600, (y + 1) / 800),
            )
            for i, y in enumerate((607, 585))
        )
        if ruled
        else (),
    )


@pytest.mark.parametrize("scale", [0.75, 1.6])
@pytest.mark.parametrize("ruled", [False, True])
def test_styled_caption_and_wide_header_keep_short_cells_in_their_column(scale, ruled):
    page = grid_page(scale=scale, ruled=ruled, adjacent_prose=ruled)
    prepared = _prepare_table_lines(page.lines, page.width, page.objects, page.height)
    (grid,) = indexed_grids(prepared, page)
    assert grid["row_count"] == 4 and grid["column_count"] == 3
    cells = {line.text: (row, col) for line, row, col in grid["cells"]}
    assert cells["None"] == (2, 2)
    assert cells["12/23/34"] == (3, 3)
    assert cells["Without electricity"] == (4, 2)
    assert cells["nd"] == (4, 3)
    assert not any(
        "unrelated" in text or "measurement method" in text for text in cells
    )
    caption = grid["caption"]
    assert caption.text == "Table 7 Comparison of alternative experimental conditions"
    assert caption.y1 == 750 * scale  # Full description, not the shorter label box.


def test_centered_header_retains_left_aligned_values_without_text_overlap():
    page = grid_page()
    lines = tuple(
        replace(line, text="Solvent", x0=140, x1=170)
        if line.text == "Deviation from the standard procedure"
        else replace(line, x0=120, x1=120 + len(line.text) * 4)
        if line.text in {"None", "Solvent P/Q/R", "Without electricity"}
        else line
        for line in page.lines
    )
    (grid,) = indexed_grids(lines, page)
    cells = {line.text: (row, col) for line, row, col in grid["cells"]}
    assert cells["None"] == (2, 2)
    assert cells["Without electricity"] == (4, 2)


@pytest.mark.parametrize(
    "problem", ["two_descriptions", "distant_description", "body_mention"]
)
def test_caption_assembly_rejects_ambiguous_or_unrelated_text(problem):
    page = grid_page()
    lines = list(page.lines)
    if problem == "two_descriptions":
        lines.append(replace(lines[1], text="A competing description on the same line"))
    elif problem == "distant_description":
        lines[1] = replace(lines[1], x0=330, x1=590)
    else:
        lines[1] = replace(lines[1], text="shows alternative experimental conditions")
    prepared = _prepare_table_lines(tuple(lines), page.width, page.objects, page.height)
    assert not indexed_grids(prepared, page)
    assert all(any(line.text in out.text for out in prepared) for line in lines)


@pytest.mark.parametrize(
    "problem", ["crosses_headers", "missing_result", "broken_index"]
)
def test_grid_recovery_still_rejects_ambiguous_or_incomplete_experiments(problem):
    page = grid_page(ruled=True, adjacent_prose=True)
    lines = list(page.lines)
    if problem == "crosses_headers":
        i = next(i for i, line in enumerate(lines) if line.text == "None")
        lines[i] = replace(lines[i], x0=60, x1=100)
    elif problem == "missing_result":
        lines = [line for line in lines if line.text != "nd"]
    else:
        lines = [
            replace(line, text="8") if line.text == "3" else line for line in lines
        ]
    prepared = _prepare_table_lines(tuple(lines), page.width, page.objects, page.height)
    assert not indexed_grids(prepared, page)


def test_final_table_assembly_uses_the_same_styled_caption_as_preparation(tmp_path):
    from pathlib import Path

    from aletheia_nexus.content.service import parse_document

    class Backend:
        name = "styled-caption-fixture"
        version = "1"

        def extract_page(self, page, page_number):
            return replace(grid_page(ruled=True, adjacent_prose=True), page=page_number)

    result = parse_document(
        Path(__file__).parents[2]
        / "benchmarks"
        / "v07_fixtures"
        / "native_article.pdf",
        "10.5555/an.v07.native",
        output_path=tmp_path / "result.json",
        backend=Backend(),
    ).document
    assert len(result["tables"]) == len(result["pages"])
    for table in result["tables"]:
        cells = {cell["text"]: cell for cell in table["cells"]}
        assert cells["None"]["column"] == 2
        assert cells["12/23/34"]["row"] == cells["Solvent P/Q/R"]["row"] == 3
        assert cells["nd"]["column"] == 3
        assert table["row_count"] == 4 and table["column_count"] == 3
