"""Nested script geometry must not create extra experimental rows or columns."""

from types import SimpleNamespace

from pypdf import PdfWriter
from pypdf.generic import NameObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.backends.layout import (
    _attach_inline_glyphs,
    _attach_nested_scripts,
    _ordered_glyphs,
)


def glyph(text, x, y, size, width=3, height=None, origin=None):
    return SimpleNamespace(
        x0=x,
        x1=x + width,
        y0=y,
        y1=y + (height if height is not None else size),
        size=size,
        matrix=(1, 0, 0, 1, x, y),
        an_text_origin=(x, y if origin is None else origin),
        get_text=lambda: text,
    )


def test_nested_numeric_scripts_join_one_local_label_and_keep_charge_order():
    root = [
        glyph("Q", 90, 200, 10),
        glyph("S", 101, 197, 6),
        glyph("O", 105, 197, 6),
        glyph("-", 113, 197, 6),
        glyph("N", 117, 197, 6),
        glyph(",", 120, 197, 6, width=2),
    ]
    digit = glyph("4", 109.2, 195, 3, width=1.5)
    charge = glyph("-", 109, 201, 3, width=1.5, height=0.2)
    initial = glyph("2", 122, 197, 6)
    unrelated = glyph("73", 250, 180, 10, width=12)
    rows = [root, [digit], [charge], [initial], [unrelated]]
    assert not _attach_nested_scripts(rows)
    assert "".join(c.get_text() for c in _ordered_glyphs(root)) == "QSO4--N,2"
    assert rows[-1] == [unrelated]
    assert sum(len(row) for row in rows) == 10


def test_competing_local_bases_and_full_size_values_are_not_joined():
    source = glyph("2", 120, 200, 6)
    roots = [
        [glyph("A", 100, 200, 10), glyph("N", 116, 200, 6)],
        [glyph("B", 100, 202, 10), glyph("M", 116, 200, 6)],
    ]
    rows = [*roots, [source]]
    assert _attach_nested_scripts(rows) == {id(source)}
    assert rows[-1] == [source]
    regular = glyph("7", 120, 200, 10)
    rows = [roots[0], [regular]]
    assert not _attach_nested_scripts(rows)
    assert rows[-1] == [regular]


def test_inline_repair_leaves_empty_rows_without_breaking_nested_scripts():
    root = [glyph("A", 100, 200, 10), glyph("C", 106, 200, 10)]
    letter = glyph("B", 103, 200, 10)
    digit = glyph("2", 110, 199, 5)
    rows = [[], root, [letter], [digit], []]
    assert not _attach_inline_glyphs(rows)
    assert rows[2] == []
    assert not _attach_nested_scripts(rows)
    assert "".join(c.get_text() for c in _ordered_glyphs(root)) == "ABC2"
    assert rows[0] == rows[2] == rows[3] == rows[4] == []
    assert sum(map(len, rows)) == 4


def test_empty_rows_do_not_change_competing_base_ambiguity():
    digit = glyph("2", 120, 200, 6)
    roots = [
        [glyph("A", 100, 200, 10), glyph("N", 116, 200, 6)],
        [glyph("B", 100, 202, 10), glyph("M", 116, 200, 6)],
    ]
    rows = [[], roots[0], [], roots[1], [digit], []]
    assert _attach_nested_scripts(rows) == {id(digit)}
    assert rows[4] == [digit]
    assert sum(map(len, rows)) == 5


def test_connected_measurement_or_distant_digit_stays_in_its_own_row():
    base = [glyph("Q", 90, 200, 10), glyph("N", 117, 197, 6)]
    measurement = [glyph("2", 122, 197, 6), glyph("V", 125, 197, 6)]
    distant = [glyph("3", 160, 197, 6)]
    rows = [base, measurement, distant]
    assert not _attach_nested_scripts(rows)
    assert rows == [base, measurement, distant]


def test_painted_nested_scripts_preserve_formula_order_and_separate_value():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))

    def text(value, x, y, size):
        return f"BT /F {size} Tf {x} {y} Td ({value}) Tj ET ".encode()

    contents = (
        text("Q", 100, 300, 12)
        + text("SO", 109, 297, 7)
        + text("-", 119, 301, 4)
        + text("4", 119.1, 295, 4)
        + text("-N,", 122, 297, 7)
        + text("2", 134, 297, 7)
        + text("/mg", 144, 300, 12)
        + text("73", 109, 280, 12)
    )
    page[NameObject("/Contents")] = stream(writer, contents)
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert ["".join(line.text.split()) for line in layout.lines] == [
        "QSO4--N,2/mg",
        "73",
    ]
    assert page["/Contents"].get_data() == contents
