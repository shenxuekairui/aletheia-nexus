"""An embedded encoded capital can disprove a case-only Unicode mapping."""

import io

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject
from test_display_and_tables import array, dictionary, stream

from aletheia_nexus.content.backends import LayoutPdfBackend


def case_page(*, mapped="n", same_outline=False, empty=False, difference=False):
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "N", "n"])
    glyphs = {}
    for name in builder.font.getGlyphOrder():
        pen = T2CharStringPen(600, None)
        if name != ".notdef" and not (empty and name == "N"):
            height = 700 if name == "N" or same_outline else 450
            pen.moveTo((50, 0))
            pen.lineTo((50, height))
            pen.lineTo((120, height))
            pen.lineTo((450, 100))
            pen.lineTo((450, height))
            pen.lineTo((520, height))
            pen.lineTo((520, 0))
            pen.lineTo((450, 0))
            pen.lineTo((120, height - 100))
            pen.lineTo((120, 0))
            pen.closePath()
        glyphs[name] = pen.getCharString()
    builder.setupCFF("ANCaseFixture", {}, glyphs, {})
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    font = dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/Type1"),
        BaseFont=NameObject("/ANCaseFixture"),
        FirstChar=NumberObject(0),
        LastChar=NumberObject(255),
        Widths=array(*([600] * 256)),
        Encoding=dictionary(
            BaseEncoding=NameObject("/WinAnsiEncoding"),
            Differences=ArrayObject([NumberObject(78), NameObject("/n")])
            if difference
            else ArrayObject(),
        ),
        FontDescriptor=dictionary(
            Type=NameObject("/FontDescriptor"),
            FontName=NameObject("/ANCaseFixture"),
            Flags=NumberObject(4),
            FontBBox=array(0, 0, 600, 800),
            Ascent=NumberObject(800),
            Descent=NumberObject(0),
            FontFile3=stream(
                writer,
                builder.font["CFF "].compile(builder.font),
                Subtype=NameObject("/Type1C"),
            ),
        ),
        ToUnicode=stream(
            writer,
            f"begincmap 1 begincodespacerange <00> <ff> endcodespacerange 2 beginbfchar <4e> <{ord(mapped):04x}> <6e> <006e> endbfchar endcmap".encode(),
        ),
    )
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=font))
    page[NameObject("/Contents")] = stream(writer, b"BT /F 12 Tf 50 700 Td (Nn) Tj ET")
    return writer, page


def test_case_repair_retains_lowercase_and_original_mapping_without_touching_source():
    writer, page = case_page()
    before = io.BytesIO()
    writer.write(before)
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert layout.lines[0].text == "Nn"
    notices = [
        w for w in layout.warnings if w["code"] == "NATIVE_GLYPH_MAPPING_CORRECTED"
    ]
    assert any(
        w["before"] == "nn"
        and w["after"] == "Nn"
        and w["bbox"]
        and {"before": "n", "after": "N"} in w["corrections"]
        for w in notices
    )
    after = io.BytesIO()
    writer.write(after)
    assert before.getvalue() == after.getvalue()


@pytest.mark.parametrize(
    "options,expected",
    [
        ({"same_outline": True}, "nn"),
        ({"empty": True}, "nn"),
        ({"difference": True}, "nn"),
        ({"mapped": "ν"}, "νn"),
        ({"mapped": "N"}, "Nn"),
    ],
)
def test_unproven_case_or_different_character_mapping_is_not_replaced(
    options, expected
):
    _, page = case_page(**options)
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert layout.lines[0].text == expected
    assert not any(
        w["code"] == "NATIVE_GLYPH_MAPPING_CORRECTED" for w in layout.warnings
    )
