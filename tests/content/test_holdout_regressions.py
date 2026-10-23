"""Self-authored fixtures for faults found in held-out scientific documents."""

import io
from types import SimpleNamespace

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.backends.font_symbols import (
    _cff_zero_glyph,
    _outline_symbol,
)
from aletheia_nexus.content.parser import _table_cells


def zero_encoded_page(mapped=False):
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "arbitrary", "other"])
    glyphs = {}
    for name in builder.font.getGlyphOrder():
        pen = T2CharStringPen(600, None)
        if name != ".notdef":
            pen.moveTo((50, 230))
            for point in [(550, 230), (550, 270), (50, 270)]:
                pen.lineTo(point)
            pen.closePath()
        glyphs[name] = pen.getCharString()
    builder.setupCFF("ANZero", {}, glyphs, {})
    top = builder.font["CFF "].cff.topDictIndex[0]
    top.Encoding = [".notdef"] * 256
    top.Encoding[0], top.Encoding[65] = "arbitrary", "other"
    program = DecodedStreamObject()
    program.set_data(builder.font["CFF "].compile(builder.font))
    program[NameObject("/Subtype")] = NameObject("/Type1C")
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    definition = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/ANZero"),
            NameObject("/FirstChar"): NumberObject(0),
            NameObject("/LastChar"): NumberObject(65),
            NameObject("/Widths"): ArrayObject([NumberObject(600)] * 66),
            NameObject("/FontDescriptor"): DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/FontDescriptor"),
                    NameObject("/FontName"): NameObject("/ANZero"),
                    NameObject("/Flags"): NumberObject(4),
                    NameObject("/FontBBox"): ArrayObject(
                        [NumberObject(x) for x in [0, 0, 800, 800]]
                    ),
                    NameObject("/Ascent"): NumberObject(800),
                    NameObject("/Descent"): NumberObject(0),
                    NameObject("/FontFile3"): writer._add_object(program),
                }
            ),
        }
    )
    cmap = DecodedStreamObject()
    code, text = (b"00", b"0058") if mapped else (b"41", b"0041")
    cmap.set_data(
        b"begincmap 1 begincodespacerange <00> <ff> endcodespacerange "
        b"1 beginbfchar <" + code + b"> <" + text + b"> endbfchar endcmap"
    )
    definition[NameObject("/ToUnicode")] = writer._add_object(cmap)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): definition})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td <00> Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    # Exercise the ordinary saved-PDF path as well as the embedded font reader.
    output = io.BytesIO()
    writer.write(output)
    return PdfReader(output).pages[0]


def test_embedded_code_zero_recovers_only_missing_mapping():
    line = LayoutPdfBackend().extract_page(zero_encoded_page(), 1).lines[0]
    assert line.text == "−"
    assert line.uncertain
    mapped = LayoutPdfBackend().extract_page(zero_encoded_page(mapped=True), 1)
    assert mapped.lines[0].text == "X"


@pytest.mark.parametrize("codes", [b"\x00\x00", b"\x41\x42", b"\x00"])
def test_ambiguous_or_truncated_cff_encoding_has_no_zero_reading(codes):
    top = SimpleNamespace(rawDict={"Encoding": 2}, charset=[".notdef", "a", "b"])
    assert _cff_zero_glyph(b"xx\x00\x02" + codes, top) is None


def ring(cx, cy, radius):
    k = radius * 0.5523
    return [
        ("moveTo", ((cx + radius, cy),)),
        ("curveTo", ((cx + radius, cy + k), (cx + k, cy + radius), (cx, cy + radius))),
        ("curveTo", ((cx - k, cy + radius), (cx - radius, cy + k), (cx - radius, cy))),
        ("curveTo", ((cx - radius, cy - k), (cx - k, cy - radius), (cx, cy - radius))),
        ("curveTo", ((cx + k, cy - radius), (cx + radius, cy - k), (cx + radius, cy))),
        ("closePath", ()),
    ]


def test_degree_ring_distinguished_from_baseline_or_centered_circle():
    assert _outline_symbol(ring(180, 560, 130) + ring(180, 560, 95), 1000) == "°"
    assert _outline_symbol(ring(180, 250, 130) + ring(180, 250, 95), 1000) is None
    assert _outline_symbol(ring(300, 340, 330) + ring(300, 340, 280), 1000) is None


def test_two_line_table_header_shares_column_and_prose_is_not_a_row():
    blocks, anchors = [], {}

    def cell(text, box, line_count=1):
        bid = str(len(blocks) + 1)
        block = dict(
            id=bid,
            anchor_id=bid,
            order=len(blocks) + 1,
            page=1,
            kind="paragraph",
            text=text,
            line_count=line_count,
        )
        blocks.append(block)
        anchors[bid] = dict(id=bid, bbox=box)

    caption = dict(order=0, page=1)
    cell("Material", [0.1, 0.82, 0.19, 0.83])
    cell("Concentration", [0.25, 0.825, 0.36, 0.835])
    cell("mol/L", [0.26, 0.815, 0.35, 0.825])
    cell("Efficiency %", [0.4, 0.82, 0.5, 0.83])
    for y, material, concentration, efficiency in [
        (0.78, "Alpha", "0.007", "82.1"),
        (0.74, "Beta", "0.009", "91.2"),
    ]:
        cell(material, [0.1, y, 0.19, y + 0.01])
        cell(concentration, [0.27, y, 0.34, y + 0.01])
        cell(efficiency, [0.43, y, 0.48, y + 0.01])
    cell(
        "This paragraph explains the observed trend after the table; it is not a measurement row.",
        [0.1, 0.66, 0.5, 0.70],
        line_count=2,
    )
    cells, rows, columns = _table_cells(caption, blocks, anchors)
    assert (rows, columns) == (3, 3)
    assert {c["column"] for c in cells if c["text"] in {"Concentration", "mol/L"}} == {
        2
    }
    assert {
        c["column"] for c in cells if c["text"] in {"Efficiency %", "82.1", "91.2"}
    } == {3}
    assert all("paragraph" not in c["text"] for c in cells)
    assert blocks[-1]["text"].startswith("This paragraph")
