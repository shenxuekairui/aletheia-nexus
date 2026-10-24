"""Self-authored PDFs with same-named fonts and incompatible character maps."""

import io

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject
from test_display_and_tables import array, dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend


def cid_font(writer, *, equals):
    names = [".notdef", "painted"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({32: "painted"})
    pen = TTGlyphPen(None)
    if equals:
        for y in (180, 380):
            pen.moveTo((60, y))
            pen.lineTo((560, y))
            pen.lineTo((560, y + 45))
            pen.lineTo((60, y + 45))
            pen.closePath()
    builder.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "painted": pen.glyph()})
    builder.setupHorizontalMetrics({n: (600, 0) for n in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "SharedName", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    data = io.BytesIO()
    builder.font.save(data)
    # Deliberately share the standard font's name. CID 32 is independent of
    # its ASCII byte 32. The equals outline has a defective space ToUnicode.
    descriptor = dictionary(
        Type=NameObject("/FontDescriptor"),
        FontName=NameObject("/Helvetica"),
        Flags=NumberObject(4),
        FontBBox=array(0, -200, 600, 800),
        Ascent=NumberObject(800),
        Descent=NumberObject(-200),
        FontFile2=stream(writer, data.getvalue()),
    )
    descendant = dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/CIDFontType2"),
        BaseFont=NameObject("/Helvetica"),
        CIDSystemInfo=dictionary(),
        DW=NumberObject(600),
        FontDescriptor=descriptor,
        CIDToGIDMap=stream(writer, b"\0\0" * 32 + b"\0\1"),
    )
    return dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/Type0"),
        BaseFont=NameObject("/Helvetica"),
        Encoding=NameObject("/Identity-H"),
        DescendantFonts=ArrayObject([descendant]),
        ToUnicode=stream(
            writer,
            b"begincmap 1 begincodespacerange <0000> <ffff> endcodespacerange "
            b"1 beginbfchar <0020> <0020> endbfchar endcmap",
        ),
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_same_font_name_does_not_share_space_or_outline_corrections(reverse, nested):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    normal = regular_font()
    blank = cid_font(writer, equals=False)
    equals = cid_font(writer, equals=True)
    resources = [("R", normal), ("B", blank), ("E", equals)]
    if reverse:
        resources.reverse()
    page[NameObject("/Resources")] = dictionary(Font=dictionary(**dict(resources)))
    body = b"BT /R 12 Tf 50 700 Td (A 3.6 mM) Tj ET "
    body += b"BT /R 12 Tf 50 660 Td (Q) Tj /B 12 Tf <0020> Tj /R 12 Tf (R) Tj ET "
    equation = b"BT /R 12 Tf 50 620 Td (Q) Tj /E 12 Tf <0020> Tj /R 12 Tf (R) Tj ET "
    if nested:
        page["/Resources"][NameObject("/XObject")] = dictionary(
            F=stream(
                writer,
                equation,
                Type=NameObject("/XObject"),
                Subtype=NameObject("/Form"),
                BBox=array(0, 0, 600, 800),
                Resources=dictionary(Font=dictionary(R=normal, E=equals)),
            )
        )
        body += b"/F Do"
    else:
        body += equation
    page[NameObject("/Contents")] = stream(writer, body)
    original = io.BytesIO()
    writer.write(original)
    layout = LayoutPdfBackend().extract_page(page, 1)
    text = [line.text for line in layout.lines]
    assert "A 3.6 mM" in text
    assert "Q R" in text
    assert any(line.replace(" ", "") == "Q=R" for line in text)
    corrections = [
        w for w in layout.warnings if w["code"] == "NATIVE_GLYPH_MAPPING_CORRECTED"
    ]
    assert corrections and all("3.6" not in w["after"] for w in corrections)
    after = io.BytesIO()
    writer.write(after)
    assert original.getvalue() == after.getvalue()
