"""Painted lettering is evidence even when a PDF contains no image object."""

from dataclasses import replace

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject
from test_display_and_tables import array, dictionary, regular_font, stream

from aletheia_nexus.content.backends import AdaptiveOcrBackend, LayoutPdfBackend
from aletheia_nexus.content.backends.tesseract import _native_gap_readings
from aletheia_nexus.content.backends.vector_text import vector_text_regions
from aletheia_nexus.content.models import LayoutLine, PageLayout


@pytest.mark.parametrize("vertical", [False, True])
def test_runs_are_local_and_do_not_cross_whitespace_or_native_text(vertical):
    boxes = []
    for left in (20, 180):
        for i in range(5):
            box = (left + i * 5, 100, left + i * 5 + 3, 106)
            if vertical:
                box = (box[1], box[0], box[3], box[2])
            boxes.append((box, True))
    regions = vector_text_regions(boxes, [], 600, 800)
    assert len(regions) == 2
    assert all(obj.object_type == "vector-text" for obj in regions)
    a, b = regions
    axis = 1 if vertical else 0
    assert a.bbox[axis + 2] < b.bbox[axis]
    cover = LayoutLine("Mapped native label", 0, 0, 600, 800, 10)
    assert vector_text_regions(boxes, [cover], 600, 800) == ()
    assert vector_text_regions(boxes[:3], [], 600, 800) == ()
    assert vector_text_regions([(box, False) for box, _ in boxes], [], 600, 800) == ()


@pytest.mark.parametrize("nested", [False, True])
def test_pdf_outlines_trigger_scoped_ocr_without_native_prose_replacement(nested):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    resources = dictionary(Font=dictionary(F=regular_font()))
    prose = b"BT /F 12 Tf 50 700 Td (Native conditions: 7.2 mM at 18 C. Complete source sentence retained.) Tj 0 -20 Td (A separate native sentence keeps this page above the sparse-text threshold.) Tj ET "
    # Four self-authored filled E outlines: real painted paths, no fake font
    # mapping and no raster image. Separate straight rules must not trigger.
    letters = b""
    for x in (40, 48, 56, 64):
        letters += f"q 1 0 0 1 {x} 200 cm 0 0 m 5 0 l 5 1 l 1 1 l 1 3 l 4 3 l 4 4 l 1 4 l 1 6 l 5 6 l 5 7 l 0 7 l h f Q ".encode()
    if nested:
        form = stream(
            writer,
            letters + b"q 1 0 0 1 0 400 cm " + letters + b"Q",
            Type=NameObject("/XObject"),
            Subtype=NameObject("/Form"),
            BBox=array(30, 190, 80, 220),
            Resources=dictionary(),
        )
        resources[NameObject("/XObject")] = dictionary(Drawing=form)
        letters = b"/Drawing Do "
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = stream(
        writer, prose + letters + b"40 180 m 160 180 l S 40 170 120 1 re f"
    )
    native = LayoutPdfBackend().extract_page(page, 1)
    regions = [obj for obj in native.objects if obj.object_type == "vector-text"]
    assert len(regions) == 1
    assert regions[0].bbox[1] < 0.25 < regions[0].bbox[3]
    assert (
        len([w for w in native.warnings if w["code"] == "VECTOR_TEXT_UNVERIFIED"]) == 1
    )

    class Native:
        def extract_page(self, page, number):
            return native

    class Ocr:
        name, version = "fixture-ocr", "1"
        called = False

        def extract_regions(self, page, number, regions, *, native_layout):
            self.called = True
            assert len(regions) == 1
            assert regions[0].bbox[3] < 0.3
            return replace(
                native,
                lines=(
                    LayoutLine(
                        "EEEE", 40, 200, 69, 207, 7, extraction_method="fixture-ocr"
                    ),
                ),
                objects=(),
                warnings=(),
            )

        def extract_page(self, page, number):
            pytest.fail("unrelated native prose must not trigger a full OCR pass")

    ocr = Ocr()
    result = AdaptiveOcrBackend(
        native_backend=Native(), ocr_backends=(ocr,)
    ).extract_page(page, 1)
    assert ocr.called
    assert any(line.text == native.lines[0].text for line in result.lines)
    added = next(line for line in result.lines if line.text == "EEEE")
    assert added.content_region == "figure" and added.uncertain
    assert any(
        w["code"] == "OCR_TRIGGERED" and "unmapped-vector-text" in w["detail"]
        for w in result.warnings
    )


def test_straight_table_rules_do_not_make_vector_text_candidates():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Contents")] = stream(
        writer, b"40 100 300 1 re f 40 130 300 1 re f 40 160 300 1 re f"
    )
    result = LayoutPdfBackend().extract_page(page, 1)
    assert not any(obj.object_type == "vector-text" for obj in result.objects)
    assert not any(w["code"] == "VECTOR_TEXT_UNVERIFIED" for w in result.warnings)


def test_ocr_words_do_not_join_widely_separated_experiments():
    line = LayoutLine(
        "A 12 +/- 2 mM B 35%",
        20,
        200,
        315,
        210,
        10,
        glyph_spans=(
            (0, 1, 20, 25),
            (2, 4, 32, 42),
            (5, 8, 45, 55),
            (9, 10, 58, 63),
            (11, 13, 66, 80),
            (14, 15, 280, 285),
            (16, 19, 292, 315),
        ),
    )
    layout = PageLayout(1, 600, 800)
    readings = _native_gap_readings(line, layout, layout)
    assert [r.text for r in readings] == ["A 12 +/- 2 mM", "B 35%"]
    assert [(r.x0, r.x1) for r in readings] == [(20, 80), (280, 315)]
    assert all(r.uncertain for r in readings)
