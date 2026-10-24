"""PDF WinAnsi aliases require an actual embedded glyph and honor overrides."""

import io

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject
from test_display_and_tables import array, dictionary, stream

from aletheia_nexus.content.backends import LayoutPdfBackend


def alias_page(*, code=129, difference=False, explicit=False, empty=False):
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "bullet", "period"])
    glyphs = {}
    for name in builder.font.getGlyphOrder():
        pen = T2CharStringPen(600, None)
        if name != ".notdef" and not (name == "bullet" and empty):
            y = 250 if name == "bullet" else 0
            pen.moveTo((200, y))
            pen.curveTo((145, y), (100, y + 45), (100, y + 100))
            pen.curveTo((100, y + 155), (145, y + 200), (200, y + 200))
            pen.curveTo((255, y + 200), (300, y + 155), (300, y + 100))
            pen.curveTo((300, y + 45), (255, y), (200, y))
            pen.closePath()
        glyphs[name] = pen.getCharString()
    builder.setupCFF("ANEncodingFixture", {}, glyphs, {})
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    program = stream(
        writer,
        builder.font["CFF "].compile(builder.font),
        Subtype=NameObject("/Type1C"),
    )
    font = dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/Type1"),
        BaseFont=NameObject("/ANEncodingFixture"),
        FirstChar=NumberObject(0),
        LastChar=NumberObject(255),
        Widths=array(*([600] * 256)),
        Encoding=dictionary(
            BaseEncoding=NameObject("/WinAnsiEncoding"),
            Differences=ArrayObject([NumberObject(code), NameObject("/period")])
            if difference
            else ArrayObject(),
        ),
        FontDescriptor=dictionary(
            Type=NameObject("/FontDescriptor"),
            FontName=NameObject("/ANEncodingFixture"),
            Flags=NumberObject(4),
            FontBBox=array(0, 0, 600, 800),
            Ascent=NumberObject(800),
            Descent=NumberObject(0),
            FontFile3=program,
        ),
    )
    if explicit:
        font[NameObject("/ToUnicode")] = stream(
            writer,
            f"begincmap 1 begincodespacerange <00> <ff> endcodespacerange 1 beginbfchar <{code:02x}> <0058> endbfchar endcmap".encode(),
        )
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=font))
    page[NameObject("/Contents")] = stream(
        writer, f"BT /F 12 Tf 50 700 Td <{code:02x}> Tj ET".encode()
    )
    return writer, page


@pytest.mark.parametrize("code", [127, 129, 141, 143, 144, 157])
def test_unused_winansi_codes_read_the_painted_bullet(code):
    writer, page = alias_page(code=code)
    before = io.BytesIO()
    writer.write(before)
    result = LayoutPdfBackend().extract_page(page, 1)
    assert result.lines[0].text == "•"
    notice = next(
        w for w in result.warnings if w["code"] == "NATIVE_GLYPH_MAPPING_CORRECTED"
    )
    assert notice["before"] == f"(cid:{code})" and notice["after"] == "•"
    after = io.BytesIO()
    writer.write(after)
    assert before.getvalue() == after.getvalue()


@pytest.mark.parametrize(
    "options,expected",
    [
        ({"difference": True}, "."),
        ({"explicit": True}, "X"),
        ({"empty": True}, "(cid:129)"),
    ],
)
def test_custom_or_explicit_mappings_and_unpainted_glyphs_are_not_replaced(
    options, expected
):
    _, page = alias_page(**options)
    result = LayoutPdfBackend().extract_page(page, 1)
    assert result.lines[0].text == expected
