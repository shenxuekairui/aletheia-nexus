"""Geometry-driven mixed scripts; values and font names are synthetic."""

import io

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject
from test_display_and_tables import array, dictionary, stream
from test_table_generalization import cells_from

from aletheia_nexus.content.backends import AdaptiveOcrBackend, LayoutPdfBackend
from aletheia_nexus.content.backends.font_symbols import displaced_glyph_bounds
from aletheia_nexus.content.models import LayoutLine, PageLayout
from aletheia_nexus.content.parser import _prepare_table_lines


def mixed_page(descent, scale=1, shift=0, gid_map=False):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    fonts = {}
    for label, mappings, lower in [("C", "电极", -200), ("L", "A72-2", descent)]:
        names = [".notdef", *[f"g{i}" for i in range(len(mappings))]]
        builder = FontBuilder(1000, isTTF=True)
        builder.setupGlyphOrder(names)
        builder.setupCharacterMap(
            {ord(t): names[i + 1] for i, t in enumerate(mappings)}
        )
        glyphs = {".notdef": TTGlyphPen(None).glyph()}
        for i, name in enumerate(names[1:]):
            pen = TTGlyphPen(None)
            bottom, top = (400, 800) if label == "L" and i == 4 else (0, 700)
            for op, p in [
                (pen.moveTo, (0, bottom)),
                (pen.lineTo, (450, bottom)),
                (pen.lineTo, (450, top)),
                (pen.lineTo, (0, top)),
            ]:
                op(p)
            pen.closePath()
            glyphs[name] = pen.glyph()
        builder.setupGlyf(glyphs)
        builder.setupHorizontalMetrics({n: (500, 0) for n in names})
        builder.setupHorizontalHeader(ascent=900, descent=lower)
        builder.setupNameTable(
            {"familyName": f"Geometry{label}", "styleName": "Regular"}
        )
        builder.setupOS2()
        builder.setupPost()
        builder.setupMaxp()
        data = io.BytesIO()
        builder.font.save(data)
        desc = dictionary(
            Type=NameObject("/Font"),
            Subtype=NameObject("/CIDFontType2"),
            BaseFont=NameObject(f"/Geometry{label}"),
            CIDSystemInfo=dictionary(),
            DW=NumberObject(500),
            FontDescriptor=dictionary(
                Type=NameObject("/FontDescriptor"),
                FontName=NameObject(f"/Geometry{label}"),
                Flags=NumberObject(4),
                FontBBox=array(0, lower, 500, 900),
                Ascent=NumberObject(900),
                Descent=NumberObject(lower),
                FontFile2=stream(writer, data.getvalue()),
            ),
        )
        offset = 8 if gid_map else 0
        if gid_map:
            desc[NameObject("/CIDToGIDMap")] = stream(
                writer,
                b"\0\0" * offset
                + b"".join(i.to_bytes(2, "big") for i in range(len(names))),
            )
        cmap = f"begincmap 1 begincodespacerange <0000> <ffff> endcodespacerange {len(mappings)} beginbfchar "
        cmap += (
            " ".join(
                f"<{i + 1 + offset:04x}> <{ord(t):04x}>" for i, t in enumerate(mappings)
            )
            + " endbfchar endcmap"
        )
        fonts[NameObject(f"/{label}")] = dictionary(
            Type=NameObject("/Font"),
            Subtype=NameObject("/Type0"),
            BaseFont=NameObject(f"/Geometry{label}"),
            Encoding=NameObject("/Identity-H"),
            DescendantFonts=ArrayObject([desc]),
            ToUnicode=stream(writer, cmap.encode()),
        )
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(**{str(k)[1:]: v for k, v in fonts.items()})
    )

    def text(font, ids, x, y, size=10):
        codes = "".join(f"{i + offset:04x}" for i in ids)
        return f"BT /{font} {size * scale} Tf {x * scale + shift} {y * scale} Td <{codes}> Tj ET "

    content = text("C", [1, 2], 40, 300) + text("L", [1], 50, 300)
    content += text("L", [2, 3], 150, 280) + text("L", [2, 3], 150, 267)
    content += text("L", [1], 40, 240) + text("L", [4, 3], 45, 244, 6)
    # Same Unicode 2 with a different CID/painted vertical position.
    content += text("L", [5], 200, 220)
    page[NameObject("/Contents")] = stream(writer, content.encode())
    return page


@pytest.mark.parametrize("scale,shift", [(0.6, 80), (1, 0), (1.5, 15)])
@pytest.mark.parametrize("gid_map", [False, True])
def test_displaced_font_merges_scripts_but_preserves_repeated_rows_and_exponents(
    scale, shift, gid_map
):
    page = mixed_page(-1100, scale, shift, gid_map)
    original = page["/Contents"].get_data()
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert any(item.text == "电极A" for item in layout.lines)
    values = [item for item in layout.lines if item.text == "72"]
    assert len(values) == 2 and abs(values[0].y0 - values[1].y0) == pytest.approx(
        13 * scale
    )
    assert any(item.text.replace(" ", "") == "A-2" for item in layout.lines)
    raised = next(item for item in layout.lines if item.text == "2")
    assert raised.y0 == pytest.approx(224 * scale)
    assert page["/Contents"].get_data() == original


def test_normal_font_boxes_are_unchanged():
    assert not displaced_glyph_bounds(mixed_page(-200))


def test_symbol_only_han_mappings_do_not_prove_displaced_normal_text():
    page = mixed_page(-1100)
    font = page["/Resources"]["/Font"]["/L"]
    cmap = font["/ToUnicode"]
    data = cmap.get_data()
    for code, han in [("0041", "7532"), ("0037", "4e59"), ("0032", "4e19")]:
        data = data.replace(f"<{code}>".encode(), f"<{han}>".encode())
    cmap.set_data(data)
    assert not displaced_glyph_bounds(page)


@pytest.mark.parametrize("conflict", [False, True])
def test_corrected_boxes_corroborate_ocr_without_deleting_repeated_rows(conflict):
    page = mixed_page(-1100)
    native = LayoutPdfBackend().extract_page(page, 1)
    ocr = PageLayout(
        page=1,
        width=600,
        height=800,
        lines=tuple(
            LayoutLine(
                "73" if conflict and y == 280 else "72",
                150,
                y,
                160,
                y + 7,
                10,
                source_engines=("synthetic-ocr",),
                extraction_method="ocr",
            )
            for y in [280, 267]
        ),
    )
    merged, _ = AdaptiveOcrBackend()._merge(native, [ocr])
    primary = [
        item for item in merged if not item.content_region.endswith("alternative")
    ]
    assert sum(item.text == "72" for item in primary) == 2
    if conflict:
        assert any(item.text == "73" for item in merged)
        assert any(item.uncertain and item.text == "72" for item in primary)
    else:
        assert not any(item.uncertain for item in primary)


@pytest.mark.parametrize("scale", [0.65, 1, 1.7])
def test_two_data_rows_use_header_alignment_and_keep_identical_values(scale):
    def line(t, x, y, w):
        return LayoutLine(
            t, x * scale, y * scale, (x + w) * scale, (y + 8) * scale, 8 * scale
        )

    lines = [line("Table 8. Mixed electrode measurements.", 200, 100, 180)]
    for y, row in [
        (83, ["参数", "电极A", "电极B", "电极C"]),
        (65, ["电流/mA·cm−2", "72", "84", "96"]),
        (47, ["电荷/C", "72", "84", "96"]),
    ]:
        lines.extend(
            line(t, x, y, w)
            for t, x, w in zip(row, [40, 200, 360, 520], [80, 30, 30, 30])
        )
    _, tables = cells_from(lines, 600 * scale, 800 * scale)
    cells, rows, columns = tables[0]
    assert (rows, columns) == (3, 4)
    assert [(c["row"], c["column"]) for c in cells if c["text"] == "72"] == [
        (2, 2),
        (3, 2),
    ]
    # A distant aligned footer is not a wrapped table-cell continuation.
    footer = line("https://archive.example", 40, 17, 90)
    prepared = _prepare_table_lines(tuple([*lines, footer]), 600 * scale)
    assert prepared[-1].content_region == "body"
    # No matching header: two unrelated numeric rows do not prove a grid.
    prepared = _prepare_table_lines(tuple([lines[0], *lines[5:]]), 600 * scale)
    assert not any(item.content_region == "table-cell" for item in prepared)
