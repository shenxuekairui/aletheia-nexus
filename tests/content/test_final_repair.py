"""Visible glyph and table associations, using independent synthetic values."""

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.backends.font_symbols import _outline_symbol
from aletheia_nexus.content.models import LayoutLine
from aletheia_nexus.content.parser import (
    ParserConfig,
    _order_lines,
    _prepare_table_lines,
    _table_cells,
)


def polygon(points):
    return (
        [("moveTo", (points[0],))]
        + [("lineTo", (p,)) for p in points[1:]]
        + [("closePath", ())]
    )


@pytest.mark.parametrize("joined", [False, True])
def test_plus_minus_outline_and_inverted_negative_control(joined):
    stem_bottom = 40 if joined else 180
    plus = [
        (300, stem_bottom),
        (340, stem_bottom),
        (340, 300),
        (620, 300),
        (620, 340),
        (340, 340),
        (340, 640),
        (300, 640),
        (300, 340),
        (20, 340),
        (20, 300),
        (300, 300),
    ]
    if joined:
        points = [(20, 0), (620, 0), (620, 40), *plus[1:], (300, 40), (20, 40)]
        outline = polygon(points)
    else:
        outline = polygon(plus) + polygon([(20, 0), (620, 0), (620, 40), (20, 40)])
    assert _outline_symbol(outline, 1000) == "±"
    inverted = [(op, tuple((x, 640 - y) for x, y in points)) for op, points in outline]
    assert _outline_symbol(inverted, 1000) is None
    assert _outline_symbol(polygon(plus), 1000) is None


def native(content):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    return LayoutPdfBackend().extract_page(page, 1)


def test_large_decorative_glyph_does_not_absorb_adjacent_prose():
    layout = native(
        b"BT /F 32 Tf 40 680 Td (*) Tj ET "
        b"BT /F 10 Tf 70 700 Td (Conversion was 47.8% and) Tj ET "
        b"BT /F 10 Tf 70 689 Td (selectivity was 36.2%.) Tj ET"
    )
    assert any(line.text == "Conversion was 47.8% and" for line in layout.lines)
    assert any(line.text == "selectivity was 36.2%." for line in layout.lines)
    assert not any("47.8" in line.text and "36.2" in line.text for line in layout.lines)


def test_subscript_uses_nearby_baseline_despite_other_column_offset():
    layout = native(
        b"BT /F 10 Tf 30 702 Td (Left column.) Tj ET "
        b"BT /F 10 Tf 30 691 Td (Second left line.) Tj ET "
        b"BT /F 10 Tf 330 700 Td (H) Tj ET "
        b"BT /F 6.7 Tf 337.3 697.5 Td (2) Tj ET "
        b"BT /F 10 Tf 341 700 Td (O yield was 47.8%.) Tj ET "
        b"BT /F 10 Tf 330 689 Td (Figure 3 describes it.) Tj ET"
    )
    assert any("H2O yield was 47.8%" in line.text for line in layout.lines)
    assert any(line.text == "Figure 3 describes it." for line in layout.lines)


def test_competing_local_baselines_are_flagged():
    layout = native(
        b"BT /F 10 Tf 50 700 Td (A) Tj ET "
        b"BT /F 10 Tf 50 690 Td (B) Tj ET "
        b"BT /F 6 Tf 57 696.17 Td (2) Tj ET"
    )
    assert any(w["code"] == "NATIVE_AMBIGUOUS_GLYPH_ROW" for w in layout.warnings)
    assert any(line.uncertain and "2" in line.text for line in layout.lines)


def test_superscript_reference_run_stays_with_its_punctuation():
    layout = native(
        b"BT /F 10 Tf 50 711 Td (An unrelated upper sentence.) Tj ET "
        b"BT /F 10 Tf 50 700 Td (Result.) Tj ET "
        b"BT /F 6.7 Tf 82 704.4 Td (42-45) Tj ET"
    )
    assert any("Result." in line.text and "42-45" in line.text for line in layout.lines)
    assert any(line.text == "An unrelated upper sentence." for line in layout.lines)


def test_missing_glyph_remains_a_text_base_for_ocr_comparison():
    layout = native(
        b"BT /F 10 Tf 50 700 Td (\x00) Tj ET BT /F 7 Tf 57 700 Td (DATA) Tj ET"
    )
    assert any(
        "(cid:0)" in line.text and "DATA" in line.text and line.uncertain
        for line in layout.lines
    )


def test_single_column_multiline_caption_headers_and_decimal_comma_cells():
    def line(text, x, y, width=25):
        return LayoutLine(text, x, y, x + width, y + 6, 6)

    lines = [
        line("Table 4", 30, 750),
        line("Electrochemical reduction results with", 30, 741, 245),
        line("different electrodes and their efficiencies.", 30, 732, 245),
    ]
    for x, text in [(30, "Sample"), (110, "FE"), (180, "FE"), (250, "Current")]:
        lines.append(line(text, x, 718))
    lines.extend(
        [
            line("(A), %", 110, 709),
            line("(B), %", 180, 709),
            line("(mA/cm2)", 250, 700, 36),
        ]
    )
    for y, label, a, b, current in [
        (687, "Test-X", "14,2", "83,1", "18"),
        (676, "Test-Y", "23,1", "72,8", "20"),
        (665, "Test-Z", "31,0", "63,5", "22"),
    ]:
        lines.extend(
            line(t, x, y) for t, x in zip([label, a, b, current], [30, 110, 180, 250])
        )
    lines.extend(
        [
            line("Right column contains unrelated prose.", 320, 718, 240),
            line("The table should remain in the left column.", 320, 700, 240),
        ]
    )
    ordered = _order_lines(_prepare_table_lines(tuple(lines), 600), 600, ParserConfig())
    assert (
        ordered[0].text
        == "Table 4 Electrochemical reduction results with different electrodes and their efficiencies."
    )
    blocks, anchors = [], {}
    for i, item in enumerate(ordered):
        bid = str(i)
        blocks.append(
            dict(
                id=bid,
                anchor_id=bid,
                order=i,
                page=1,
                kind="caption" if i == 0 else "paragraph",
                text=item.text,
                content_region=item.content_region,
            )
        )
        anchors[bid] = dict(
            id=bid, bbox=[item.x0 / 600, item.y0 / 800, item.x1 / 600, item.y1 / 800]
        )
    cells, _, _ = _table_cells(blocks[0], blocks, anchors)
    a = next(c for c in cells if c["text"] == "14,2")
    b = next(c for c in cells if c["text"] == "83,1")
    assert a["row"] == b["row"] and a["column"] != b["column"]
    assert any("(A), %" in c["text"] and c["column"] == a["column"] for c in cells)
    assert any("(B), %" in c["text"] and c["column"] == b["column"] for c in cells)
    assert not any("unrelated" in c["text"] for c in cells)
