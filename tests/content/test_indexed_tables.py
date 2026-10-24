"""Explicit index/header grids with nonnumeric and multiline result cells."""

from dataclasses import replace

from pypdf import PdfWriter
from pypdf.generic import NameObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.indexed_tables import indexed_grids
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.models import LayoutLine, PageLayout
from aletheia_nexus.content.service import parse_document


def layout():
    data = [
        ("Table 6. Comparison of experimental conditions.", 45, 500),
        ("unrelated diagram label", 200, 350),
        ("Entry", 45, 160),
        ("Variation from the standard", 180, 160),
        ("Results", 420, 160),
        ("with catalyst Q", 200, 151),
        ("1", 45, 130),
        ("Unchanged", 220, 130),
        ("42% yield, 88% ee", 400, 130),
        ("2", 45, 110),
        ("No electricity", 210, 110),
        ("nd", 430, 110),
        ("3", 45, 90),
        ("Different anode", 210, 90),
        ("63% yield, 91% ee", 400, 90),
        ("4", 45, 70),
        ("Different electrolyte", 200, 70),
        ("57% yield, 89% ee", 400, 70),
    ]
    return PageLayout(
        page=1,
        width=600,
        height=800,
        lines=tuple(
            LayoutLine(text, x, y, x + len(text) * 4, y + 8, 8) for text, x, y in data
        ),
    )


def test_numeric_results_and_nd_use_the_printed_experiment_index():
    page = layout()
    (grid,) = indexed_grids(page.lines, page)
    cells = {line.text: (row, col) for line, row, col in grid["cells"]}
    assert cells["with catalyst Q"] == (1, 2)
    assert cells["nd"] == (3, 3)
    assert cells["Different electrolyte"] == (5, 2)
    assert "unrelated diagram label" not in cells


def test_missing_caption_missing_result_and_broken_index_abstain():
    page = layout()
    assert not indexed_grids(page.lines[1:], page)
    assert not indexed_grids(
        tuple(line for line in page.lines if line.text != "nd"), page
    )
    broken = tuple(
        replace(line, text="6") if line.text == "4" else line for line in page.lines
    )
    assert not indexed_grids(broken, page)


def test_footnoted_indexes_retain_the_complete_grid_and_literal_markers():
    page = layout()
    suffixes = {"2": "2 b", "3": "3b, c", "4": "4†, ‡"}
    lines = tuple(
        replace(line, text=suffixes.get(line.text, line.text)) for line in page.lines
    )
    (grid,) = indexed_grids(lines, page)
    cells = {line.text: (row, col) for line, row, col in grid["cells"]}
    assert grid["row_count"] == 5
    assert cells["2 b"] == (3, 1)
    assert cells["3b, c"] == (4, 1)
    assert cells["4†, ‡"] == (5, 1)
    assert cells["57% yield, 89% ee"] == (5, 3)


def test_markers_cannot_hide_a_broken_index_or_missing_experiment_cell():
    page = layout()
    lines = tuple(
        replace(line, text="6b") if line.text == "4" else line for line in page.lines
    )
    assert not indexed_grids(lines, page)
    lines = tuple(
        replace(line, text="4b") if line.text == "4" else line
        for line in page.lines
        if line.text != "57% yield, 89% ee"
    )
    assert not indexed_grids(lines, page)


def test_concentration_and_product_names_do_not_become_experiment_indexes():
    page = layout()
    for number in ("2", "4"):
        for suffix in (" mM", "product", ".0", "b2"):
            lines = tuple(
                replace(line, text=number + suffix) if line.text == number else line
                for line in page.lines
            )
            assert not indexed_grids(lines, page)


def test_numeric_product_header_remains_separate_from_yield():
    data = [
        ("Table 8. Products.", 40, 300),
        ("Entry", 40, 250),
        ("Substrate", 150, 250),
        ("9", 280, 250),
        ("Yield (%)", 360, 250),
    ]
    for row, (product, value) in enumerate(
        (("9a", "31"), ("9b", "47"), ("-", "nr")), 1
    ):
        y = 250 - row * 20
        data.extend(
            [
                (f"{row}b", 40, y),
                (f"S{row}", 150, y),
                (product, 280, y),
                (value, 360, y),
            ]
        )
    lines = tuple(
        LayoutLine(text, x, y, x + len(text) * 4, y + 8, 8) for text, x, y in data
    )
    page = PageLayout(page=1, width=600, height=800, lines=lines)
    (grid,) = indexed_grids(lines, page)
    cells = {line.text: (row, col) for line, row, col in grid["cells"]}
    assert grid["column_count"] == 4
    assert cells["9"] == (1, 3)
    assert cells["9a"] == (2, 3)
    assert cells["31"] == (2, 4)
    assert cells["nr"] == (4, 4)


def test_wrapped_numeric_footnote_below_grid_does_not_extend_indexes():
    page = layout()
    lines = (
        *page.lines,
        LayoutLine("a Standard conditions and measurement method.", 45, 52, 440, 60, 8),
        LayoutLine("25 mM substrate, room temperature.", 45, 42, 440, 50, 8),
        LayoutLine("25 °C", 45, 42, 68, 50, 8),
    )
    (grid,) = indexed_grids(lines, page)
    assert grid["row_count"] == 5
    assert all(line.y0 >= 70 for line, _, _ in grid["cells"])


def test_intervening_caption_cannot_be_borrowed():
    page = layout()
    lines = (*page.lines, LayoutLine("Fig. 8. A separate image.", 45, 300, 180, 308, 8))
    assert not indexed_grids(lines, page)


def test_low_page_experiment_index_is_not_suppressed_as_page_furniture(tmp_path):
    source = layout()
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    commands = []
    for line in source.lines:
        commands.append(
            f"BT /F 8 Tf {line.x0} {line.y0} Td ({line.text}) Tj ET".encode()
        )
    page[NameObject("/Contents")] = stream(writer, b"\n".join(commands))
    pdf = tmp_path / "indexed.pdf"
    writer.write(pdf)
    doc = parse_document(
        register_local_pdf(
            pdf, output_dir=tmp_path / "library", title="Indexed grid fixture"
        ),
        backend=LayoutPdfBackend(),
    ).document
    (table,) = doc["tables"]
    cells = {cell["text"]: cell for cell in table["cells"]}
    assert cells["4"]["row"] == cells["57% yield, 89% ee"]["row"] == 5
    assert cells["with catalyst Q"]["row"] == 1
    assert "unrelated diagram label" not in cells
    assert any("unrelated diagram label" in block["text"] for block in doc["blocks"])
