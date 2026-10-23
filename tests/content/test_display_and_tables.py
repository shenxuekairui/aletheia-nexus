"""Synthetic visible-source regressions; no private paper values or files."""

import io
import math

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from aletheia_nexus.content.backends import AdaptiveOcrBackend, LayoutPdfBackend
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject
from aletheia_nexus.content.parser import (
    ParserConfig,
    _order_lines,
    _prepare_table_lines,
    _table_cells,
)


def dictionary(**values):
    return DictionaryObject(
        {NameObject("/" + key): value for key, value in values.items()}
    )


def array(*values):
    return ArrayObject([NumberObject(value) for value in values])


def stream(writer, data, **values):
    obj = DecodedStreamObject()
    obj.update(dictionary(**values))
    obj.set_data(data)
    return writer._add_object(obj)


def regular_font():
    return dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/Type1"),
        BaseFont=NameObject("/Helvetica"),
    )


@pytest.mark.parametrize("nested", [False, True])
def test_form_nonzero_bbox_clips_hidden_prose_but_preserves_visible_text(nested):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    resources = dictionary(Font=dictionary(F=regular_font()))
    form = stream(
        writer,
        b"BT /F 10 Tf 110 320 Td (VISIBLE) Tj 0 180 Td (HIDDEN OLD VALUE) Tj ET",
        Type=NameObject("/XObject"),
        Subtype=NameObject("/Form"),
        BBox=array(100, 300, 300, 400),
        Resources=resources,
    )
    if nested:
        form = stream(
            writer,
            b"q 1 0 0 1 10 20 cm /Child Do Q",
            Type=NameObject("/XObject"),
            Subtype=NameObject("/Form"),
            BBox=array(100, 300, 400, 600),
            Resources=dictionary(XObject=dictionary(Child=form)),
        )
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(F=regular_font()), XObject=dictionary(Form=form)
    )
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /F 10 Tf 50 600 Td (CURRENT VALUE) Tj ET q 1 0 0 1 20 -30 cm /Form Do Q",
    )
    layout = LayoutPdfBackend().extract_page(page, 1)
    text = " ".join(line.text for line in layout.lines)
    assert "VISIBLE" in text and "CURRENT VALUE" in text and "HIDDEN" not in text
    assert not any(line.uncertain for line in layout.lines)
    assert any(w["code"] == "NATIVE_CLIPPED_TEXT_OMITTED" for w in layout.warnings)


def mapped_cid_page(*, ring=True, context=True, gid_map=False):
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "paint"])
    builder.setupCharacterMap({0x6BC5: "paint"})
    empty = TTGlyphPen(None)
    pen = TTGlyphPen(None)
    if ring:
        for radius in [130, 95]:
            pen.moveTo((180 + radius, 560))
            for i in range(8):
                angle = (i + 0.5) * math.pi / 4
                end = (i + 1) * math.pi / 4
                pen.qCurveTo(
                    (
                        round(180 + radius * math.cos(angle) / math.cos(math.pi / 8)),
                        round(560 + radius * math.sin(angle) / math.cos(math.pi / 8)),
                    ),
                    (
                        round(180 + radius * math.cos(end)),
                        round(560 + radius * math.sin(end)),
                    ),
                )
            pen.closePath()
    else:
        pen.moveTo((0, 0))
        pen.lineTo((500, 0))
        pen.lineTo((500, 700))
        pen.lineTo((0, 700))
        pen.closePath()
    builder.setupGlyf({".notdef": empty.glyph(), "paint": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (400, 0), "paint": (400, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-1000)
    builder.setupNameTable({"familyName": "ANTemp", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    data = io.BytesIO()
    builder.font.save(data)
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    descendant = dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/CIDFontType2"),
        BaseFont=NameObject("/ANTemp"),
        CIDSystemInfo=dictionary(),
        DW=NumberObject(400),
        FontDescriptor=dictionary(
            Type=NameObject("/FontDescriptor"),
            FontName=NameObject("/ANTemp"),
            Flags=NumberObject(4),
            FontBBox=array(0, -1000, 600, 800),
            Ascent=NumberObject(800),
            Descent=NumberObject(-1000),
            FontFile2=stream(writer, data.getvalue()),
        ),
    )
    cid = 3 if gid_map else 1
    if gid_map:
        descendant[NameObject("/CIDToGIDMap")] = stream(writer, b"\0\0\0\0\0\0\0\1")
    cmap = f"begincmap 1 begincodespacerange <0000> <ffff> endcodespacerange 1 beginbfchar <{cid:04x}> <6bc5> endbfchar endcmap".encode()
    font = dictionary(
        Type=NameObject("/Font"),
        Subtype=NameObject("/Type0"),
        BaseFont=NameObject("/ANTemp"),
        Encoding=NameObject("/Identity-H"),
        DescendantFonts=ArrayObject([descendant]),
        ToUnicode=stream(writer, cmap),
    )
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(F=regular_font(), S=font)
    )
    content = f"BT /S 10 Tf 69 700 Td <{cid:04x}> Tj ET".encode()
    if context:
        content += b" BT /F 10 Tf 50 700 Td (23) Tj 25 0 Td (C) Tj ET"
    page[NameObject("/Contents")] = stream(writer, content)
    output = io.BytesIO()
    writer.write(output)
    return PdfReader(output).pages[0]


@pytest.mark.parametrize("gid_map", [False, True])
def test_cid_degree_mapping_recovered_with_temperature_context_and_flag(gid_map):
    page = mapped_cid_page(gid_map=gid_map)
    original = page["/Contents"].get_data()
    layout = LayoutPdfBackend().extract_page(page, 1)
    line = next(line for line in layout.lines if "23" in line.text)
    assert "°C" in line.text.replace(" ", "") and line.uncertain
    assert any(
        w["code"] == "NATIVE_DEGREE_MAPPING_CORRECTED"
        and w["original_mappings"] == ["毅"]
        for w in layout.warnings
    )
    assert page["/Contents"].get_data() == original


@pytest.mark.parametrize(("ring", "context"), [(False, True), (True, False)])
def test_cid_mapping_is_not_changed_without_shape_and_temperature_evidence(
    ring, context
):
    layout = LayoutPdfBackend().extract_page(
        mapped_cid_page(ring=ring, context=context), 1
    )
    assert any("毅" in line.text for line in layout.lines)
    assert not any(
        w["code"] == "NATIVE_DEGREE_MAPPING_CORRECTED" for w in layout.warnings
    )


@pytest.mark.parametrize("header", [False, True])
def test_spanning_table_keeps_dense_rows_and_empty_group_column(header):
    def line(text, x, y, width=35):
        return LayoutLine(text, x, y, x + width, y + 6, 6)

    lines = [
        line("Table 7", 30, 740),
        line("Electrolysis results for three electrodes.", 30, 731, 240),
    ]
    for y, label, values in [
        (716, "Time (h)", ["1", "3", "5"]),
        (707, "Yield (%)", ["21.3", "42.5", "64.7"]),
        (698, "Efficiency (%)", ["91.2", "82.3", "73.4"]),
    ]:
        lines.append(line(label, 150, y, 80))
        lines.extend(line(value, x, y) for x, value in zip([290, 410, 530], values))
    lines.append(line("Electrode A", 30, 707, 90))
    if header:
        lines[:2] = [
            replace_line
            for replace_line in (
                line("Table 7", 30, 765),
                line("Electrolysis results for three electrodes.", 30, 756, 240),
                line("maximum", 450, 745),
                line("Electrode", 30, 734),
                line("Metric", 150, 734),
                line("First", 290, 734),
                line("Second", 410, 734),
                line("Third", 530, 734),
            )
        ]
    lines.append(line("Following prose paragraph.", 30, 660, 220))
    prepared = _prepare_table_lines(tuple(lines), 600)
    ordered = _order_lines(prepared, 600, ParserConfig())
    blocks = []
    anchors = {}
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
    assert blocks[0]["text"] == "Table 7 Electrolysis results for three electrodes."
    cells, rows, columns = _table_cells(blocks[0], blocks, anchors)
    assert (rows, columns) == (4 if header else 3, 5)
    assert {c["column"] for c in cells if c["text"] in {"3", "42.5", "82.3"}} == {4}
    assert {c["row"] for c in cells if c["text"] in {"Yield (%)", "42.5"}} == {
        3 if header else 2
    }
    assert all("Following prose" not in c["text"] for c in cells)


@pytest.mark.parametrize("ring", [False, True])
def test_winansi_digit_corrected_only_when_embedded_outline_is_degree(ring):
    pen = T2CharStringPen(400, None)
    if ring:
        for radius in (130, 95):
            x, y = 180, 560
            k = radius * 0.55228475
            pen.moveTo((x + radius, y))
            pen.curveTo((x + radius, y + k), (x + k, y + radius), (x, y + radius))
            pen.curveTo((x - k, y + radius), (x - radius, y + k), (x - radius, y))
            pen.curveTo((x - radius, y - k), (x - k, y - radius), (x, y - radius))
            pen.curveTo((x + k, y - radius), (x + radius, y - k), (x + radius, y))
            pen.closePath()
    else:
        pen.moveTo((150, 0))
        pen.lineTo((220, 0))
        pen.lineTo((220, 700))
        pen.lineTo((150, 700))
        pen.closePath()
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder([".notdef", "one"])
    builder.setupCharacterMap({49: "one"})
    builder.setupCFF(
        "ANDigit",
        {},
        {
            ".notdef": T2CharStringPen(400, None).getCharString(),
            "one": pen.getCharString(),
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
        BaseFont=NameObject("/ANDigit"),
        Encoding=NameObject("/WinAnsiEncoding"),
        FirstChar=NumberObject(49),
        LastChar=NumberObject(49),
        Widths=array(400),
        FontDescriptor=dictionary(
            Type=NameObject("/FontDescriptor"),
            FontName=NameObject("/ANDigit"),
            Flags=NumberObject(34),
            FontBBox=array(0, 0, 400, 700),
            Ascent=NumberObject(700),
            Descent=NumberObject(0),
            FontFile3=stream(writer, data.getvalue(), Subtype=NameObject("/Type1C")),
        ),
    )
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(F=regular_font(), S=font)
    )
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /F 10 Tf 50 700 Td (23) Tj /S 10 Tf 19 0 Td (1) Tj /F 10 Tf 6 0 Td (C) Tj ET",
    )
    layout = LayoutPdfBackend().extract_page(page, 1)
    text = " ".join(line.text for line in layout.lines)
    assert ("°" in text) == ring
    assert (
        any(w["code"] == "NATIVE_DEGREE_MAPPING_CORRECTED" for w in layout.warnings)
        == ring
    )


def test_legacy_premerged_numeric_cell_remains_in_table_evidence():
    blocks = [
        dict(
            id="cap",
            anchor_id="cap",
            order=0,
            page=1,
            kind="caption",
            text="Table 1 Results",
        )
    ]
    anchors = {"cap": dict(id="cap", bbox=[0.1, 0.8, 0.8, 0.82])}
    for i, (text, box) in enumerate(
        [
            ("entry", [0.1, 0.75, 0.2, 0.76]),
            ("yield", [0.5, 0.75, 0.6, 0.76]),
            ("A", [0.1, 0.70, 0.2, 0.71]),
            ("93 85", [0.5, 0.685, 0.6, 0.715]),
            ("B", [0.1, 0.68, 0.2, 0.69]),
            ("82", [0.5, 0.68, 0.6, 0.69]),
        ],
        1,
    ):
        bid = str(i)
        blocks.append(
            dict(id=bid, anchor_id=bid, order=i, page=1, kind="paragraph", text=text)
        )
        anchors[bid] = dict(id=bid, bbox=box)
    cells, _, _ = _table_cells(blocks[0], blocks, anchors)
    assert any(c["text"] == "93 85" for c in cells)


def test_rotated_margin_notice_excluded_but_interior_axis_and_upright_text_stay():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /F 8 Tf 0 1 -1 0 570 300 Tm (MARGIN NOTICE) Tj ET "
        b"BT /F 8 Tf 0 1 -1 0 120 300 Tm (AXIS) Tj ET "
        b"BT /F 8 Tf 560 200 Td (VALUE) Tj ET",
    )
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert not any(line.x0 > 550 and line.y0 > 250 for line in layout.lines)
    assert any(line.x0 < 150 and line.y0 > 250 for line in layout.lines)
    assert any("VALUE" in line.text for line in layout.lines)


def test_bare_table_mention_without_numeric_grid_is_not_promoted():
    lines = (
        LayoutLine("Table 7", 30, 740, 65, 746, 6),
        LayoutLine(
            "Describes the measurements in the next section.", 30, 731, 280, 737, 6
        ),
    )
    assert _prepare_table_lines(lines, 600) == lines


@pytest.mark.parametrize(
    ("sparse", "image"), [(False, False), (True, False), (False, True)]
)
@pytest.mark.parametrize(
    "warning_code", ["NATIVE_DEGREE_MAPPING_CORRECTED", "NATIVE_AMBIGUOUS_GLYPH_ROW"]
)
def test_glyph_only_ocr_check_does_not_add_unrelated_candidates(
    sparse, image, warning_code
):
    class Backend:
        name = "fixture"
        version = "1"

        def __init__(self, lines):
            self.lines = lines

        def extract_page(self, page, number):
            return PageLayout(
                number,
                600,
                800,
                lines=self.lines,
                warnings=(
                    {
                        "code": warning_code,
                        "detail": "verified synthetic ring correction",
                        "after": "23 °C",
                        "bbox": [50, 700, 95, 710],
                    },
                ),
                objects=(PageObject("image", "chart", bbox=(0.05, 0.2, 0.6, 0.4)),)
                if image
                else (),
            )

    native = [LayoutLine("23 °C", 50, 700, 95, 710, 10, uncertain=True)]
    if image:
        native.append(LayoutLine("Axis label", 50, 300, 150, 310, 10))
    if not sparse:
        native.append(
            LayoutLine(
                "Readable native paragraph with enough text to avoid sparse-page OCR. "
                * 2,
                50,
                400,
                500,
                410,
                10,
            )
        )
    ocr = (
        LayoutLine("23 C", 50, 700, 95, 710, 10),
        LayoutLine("UNRELATED OCR ERROR", 50, 250, 300, 260, 10),
    )
    layout = AdaptiveOcrBackend(
        native_backend=Backend(tuple(native)), ocr_backends=(Backend(ocr),)
    ).extract_page(None, 1)
    assert any("23 C" in line.text and line.uncertain for line in layout.lines)
    assert any("UNRELATED" in line.text for line in layout.lines) == (sparse or image)
    assert any(w["code"] == "OCR_GLYPH_CHECK_SCOPED" for w in layout.warnings) == (
        not sparse
    )
