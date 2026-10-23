"""Self-authored glyphs: numeric units, cross-column signs, unresolved signs."""

import io
from types import SimpleNamespace

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)
from test_accuracy import symbol_page
from test_display_and_tables import array, dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.backends.font_symbols import _mapped_m_outline
from aletheia_nexus.content.backends.layout import _attach_symbols, suspicious_text


def polygon(points):
    return [
        ("moveTo", (points[0],)),
        *[("lineTo", (p,)) for p in points[1:]],
        ("closePath", ()),
    ]


CAPITAL = polygon(
    [
        (0, 0),
        (0, 600),
        (100, 600),
        (300, 100),
        (500, 600),
        (600, 600),
        (600, 0),
        (520, 0),
        (520, 450),
        (330, 0),
        (270, 0),
        (80, 450),
        (80, 0),
    ]
)
MU = [
    ("moveTo", ((70, -220),)),
    ("lineTo", ((70, 500),)),
    ("lineTo", ((150, 500),)),
    ("lineTo", ((150, 100),)),
    ("curveTo", ((150, 50), (210, 10), (260, 10))),
    ("curveTo", ((320, 10), (400, 50), (400, 100))),
    ("lineTo", ((400, 500),)),
    ("lineTo", ((480, 500),)),
    ("lineTo", ((480, 0),)),
    ("lineTo", ((400, 0),)),
    ("lineTo", ((400, 20),)),
    ("curveTo", ((350, -40), (200, -40), (150, 0))),
    ("lineTo", ((150, -220),)),
    ("curveTo", ((130, -240), (90, -240), (70, -220))),
    ("closePath", ()),
]


def program(ops):
    result = [0, 650, "hsbw"]
    x = y = 0
    for op, points in ops:
        for nx, ny in points:
            result.extend([nx - x, ny - y])
            x, y = nx, ny
        result.append(
            {
                "moveTo": "rmoveto",
                "lineTo": "rlineto",
                "curveTo": "rrcurveto",
                "closePath": "closepath",
            }[op]
        )
    return [*result, "endchar"]


@pytest.mark.parametrize(("outline", "reading"), [(CAPITAL, "M"), (MU, "μ")])
def test_mapped_numeric_unit_uses_painted_outline_and_preserves_original(
    outline, reading
):
    assert _mapped_m_outline(outline, 1000) == reading
    page = symbol_page(m_program=program(outline))
    original = page["/Contents"].get_data()
    layout = LayoutPdfBackend().extract_page(page, 1)
    text = " ".join(line.text for line in layout.lines)
    assert ("0.4M" in text) if reading == "M" else ("3.7 μm" in text)
    assert "m prose" in text and "5 mm" in text
    warnings = [
        w for w in layout.warnings if w["code"] == "NATIVE_UNIT_MAPPING_CORRECTED"
    ]
    assert warnings and "m prose" in warnings[0]["before"]
    assert all(line.uncertain for line in layout.lines)
    assert page["/Contents"].get_data() == original


@pytest.mark.parametrize(
    "outline",
    [
        polygon([(0, 0), (80, 0), (80, 600), (0, 600)]),
        polygon(
            [
                (0, 600),
                (100, 600),
                (300, 0),
                (500, 600),
                (600, 600),
                (350, -20),
                (250, -20),
            ]
        ),
        [
            ("moveTo", ((0, 0),)),
            ("curveTo", ((0, 600), (250, 600), (250, 0))),
            ("curveTo", ((250, 600), (600, 600), (600, 0))),
            ("closePath", ()),
        ],
        [(op, tuple((x, 600 - y) for x, y in run)) for op, run in CAPITAL],
    ],
)
def test_other_letters_are_not_unit_m_corrections(outline):
    assert _mapped_m_outline(outline, 1000) is None


def test_minus_and_degree_follow_their_local_column_baseline():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject(name): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject(font),
                        }
                    )
                    for name, font in [("/FR", "/Helvetica"), ("/FS", "/Helvetica")]
                }
            )
        }
    )
    symbol_font = page["/Resources"]["/Font"]["/FS"]
    symbol_font[NameObject("/FontDescriptor")] = DictionaryObject(
        {NameObject("/Descent"): NumberObject(0)}
    )
    cmap = DecodedStreamObject()
    cmap.set_data(b"begincmap 2 beginbfchar <2d> <2212> <b0> <00b0> endbfchar endcmap")
    symbol_font[NameObject("/ToUnicode")] = cmap
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /FR 10 Tf 50 704 Td (Other column text) Tj ET BT /FR 10 Tf 340 700 Td (at ) Tj /FS 10 Tf (-) Tj /FR 10 Tf (0.6 V and 45 ) Tj /FS 10 Tf <b0> Tj /FR 10 Tf (C for 3 h) Tj ET"
    )
    page[NameObject("/Contents")] = stream
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert any("at −0.6 V and 45 °C for 3 h" == line.text for line in layout.lines), [
        line.text for line in layout.lines
    ]
    assert all(line.text not in {"−", "°"} for line in layout.lines)


def test_unresolved_symbol_and_competing_rows_are_flagged():
    def char(x, y):
        return SimpleNamespace(
            x0=x, x1=x + 5, y0=y, y1=y + 10, size=10, matrix=(1, 0, 0, 1, x, y + 2)
        )

    rows = [[char(20, 100)], [char(20, 108)]]
    symbol = char(15, 104)
    flagged = _attach_symbols(rows, [symbol])
    assert flagged == {0, 1, 2} and rows[-1] == [symbol]


@pytest.mark.parametrize("outline,corrected", [(MU, True), (CAPITAL, False)])
def test_cff_prefix_mapping_uses_glyph_not_expected_unit(outline, corrected):
    pen = T2CharStringPen(650, None)
    for op, points in outline:
        getattr(pen, op)(*points)
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "m"])
    builder.setupCharacterMap({109: "m"})
    builder.setupCFF(
        "ANPrefix",
        {},
        {
            ".notdef": T2CharStringPen(650, None).getCharString(),
            "m": pen.getCharString(),
        },
        {},
    )
    data = io.BytesIO()
    builder.font["CFF "].cff.compile(data, builder.font)
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    font = dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/Type1"),
        BaseFont=NameObject("/ANPrefix"),
        Encoding=NameObject("/WinAnsiEncoding"),
        FirstChar=NumberObject(109),
        LastChar=NumberObject(109),
        Widths=array(650),
        FontDescriptor=dictionary(
            Type=NameObject("/FontDescriptor"),
            FontName=NameObject("/ANPrefix"),
            Flags=NumberObject(34),
            FontBBox=array(0, -240, 650, 700),
            Ascent=NumberObject(700),
            Descent=NumberObject(-240),
            FontFile3=stream(writer, data.getvalue(), Subtype=NameObject("/Type1C")),
        ),
    )
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(F=regular_font(), S=font)
    )
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /F 10 Tf 50 700 Td (7.2 ) Tj /S 10 Tf (m) Tj /F 10 Tf (m; 85 ng ) Tj /S 10 Tf (m) Tj /F 10 Tf (L; 5 mm; 10 mL) Tj ET",
    )
    layout = LayoutPdfBackend().extract_page(page, 1)
    text = " ".join(x.text for x in layout.lines)
    assert ("7.2 μm" in text) == corrected
    assert ("85 ng μL" in text) == corrected
    assert "5 mm; 10 mL" in text


@pytest.mark.parametrize(
    "text,flag",
    [
        ("20 / \u0837", True),
        ("\u0301 missing base", True),
        ("cafe\u0301", False),
        ("μm and μL", False),
        ("25 °C", False),
    ],
)
def test_detached_combining_mark_is_reported_without_changing_text(text, flag):
    assert suspicious_text(text) == flag
