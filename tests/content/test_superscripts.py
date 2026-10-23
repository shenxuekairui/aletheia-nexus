"""Source-pixel recovery of missing unit exponents, with no assumed value."""

import subprocess

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.backends.superscripts import raised_glyph_box
from aletheia_nexus.content.backends.tesseract import (
    TesseractOcrBackend,
    TesseractOcrConfig,
    _parse_tsv,
)


def unit_image(raised=True, dot=False):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("L", (140, 100), 255)
    draw = ImageDraw.Draw(image)
    for x in (10, 32, 54):
        draw.rectangle((x, 30, x + 12, 59), fill=0)
    draw.rectangle((75, 40, 97, 59), fill=0)
    draw.rectangle(
        (99, 20 if raised else 40, 108, 22 if dot else (36 if raised else 59)), fill=0
    )
    return image


@pytest.mark.parametrize(
    "raised,dot,found",
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_only_actual_raised_component_is_selected(raised, dot, found):
    box = raised_glyph_box(unit_image(raised, dot), (10, 18, 110, 62))
    assert (box is not None) == found
    if found:
        assert box == (99, 20, 109, 37)


@pytest.mark.parametrize(
    "reading,confidence,expected",
    [("3", 96, "3.7A/m³"), ("2", 89, "3.7A/m"), ("'", 98, "3.7A/m")],
)
def test_unit_retry_reads_pixels_preserves_numbers_and_uncertainty(
    tmp_path, monkeypatch, reading, confidence, expected
):
    import aletheia_nexus.content.backends.tesseract as module

    monkeypatch.setattr(module, "_tool_version", lambda *a, **k: "test")
    monkeypatch.setattr(TesseractOcrBackend, "_traineddata_identity", lambda *a: {})
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    payload = header + "5\t1\t1\t1\t1\t1\t10\t18\t100\t44\t0\t3.7A/m\n"
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=header
            + f"5\t1\t1\t1\t1\t1\t20\t20\t30\t51\t{confidence}\t{reading}\n",
        )

    monkeypatch.setattr(module, "_run", run)
    backend = TesseractOcrBackend(TesseractOcrConfig(detect_orientation=False))
    lines = _parse_tsv(
        payload,
        page_number=1,
        page_width=700,
        page_height=500,
        image_width=140,
        image_height=100,
        engine_id="test",
    )
    output = backend._retry_unit_superscripts(unit_image(), payload, lines, tmp_path)
    assert output[0].text == expected
    assert output[0].uncertain
    assert output[0].x0 == lines[0].x0 and output[0].y1 == lines[0].y1
    assert len(calls) == 1
    assert not any("whitelist" in arg for arg in calls[0])
    if expected != "3.7A/m":
        assert output[1].text == "3.7A/m"
        assert output[1].content_region == "ocr-alternative"


@pytest.mark.parametrize("confidence", ["0", "invalid"])
def test_unit_without_raised_ink_does_not_invoke_ocr(tmp_path, monkeypatch, confidence):
    import aletheia_nexus.content.backends.tesseract as module

    monkeypatch.setattr(module, "_tool_version", lambda *a, **k: "test")
    monkeypatch.setattr(TesseractOcrBackend, "_traineddata_identity", lambda *a: {})
    backend = TesseractOcrBackend(TesseractOcrConfig(detect_orientation=False))
    monkeypatch.setattr(
        module, "_run", lambda *a, **k: pytest.fail("No visible exponent")
    )
    payload = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t18\t100\t44\t0\t3.7A/m\n"
    payload = payload.replace("\t0\t3.7A/m", f"\t{confidence}\t3.7A/m")
    lines = _parse_tsv(
        payload,
        page_number=1,
        page_width=140,
        page_height=100,
        image_width=140,
        image_height=100,
        engine_id="test",
    )
    assert (
        backend._retry_unit_superscripts(unit_image(False), payload, lines, tmp_path)
        == lines
    )


def test_painted_stencil_scan_is_an_image_but_unused_mask_is_not():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    mask = DecodedStreamObject()
    mask.set_data(b"\xff")
    mask.update(
        {
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/ImageMask"): BooleanObject(True),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/BitsPerComponent"): NumberObject(1),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Scan"): mask, NameObject("/Unused"): mask}
            )
        }
    )
    contents = DecodedStreamObject()
    contents.set_data(b"q 600 0 0 800 0 0 cm /Scan Do Q")
    page[NameObject("/Contents")] = contents
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert len(layout.objects) == 1
    assert layout.objects[0].name == "Scan"
    assert layout.objects[0].bbox == (0.0, 0.0, 1.0, 1.0)


def test_column_gutter_can_be_slightly_left_of_page_midpoint():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Courier"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F"): font})}
    )
    contents = DecodedStreamObject()
    contents.set_data(
        b"BT /F 10 Tf 50 700 Td (Left column value 12.5% and text to end) Tj ET BT /F 10 Tf 294 700 Td (Right column value 83%) Tj ET"
    )
    page[NameObject("/Contents")] = contents
    lines = LayoutPdfBackend().extract_page(page, 1).lines
    assert [line.text for line in lines] == [
        "Left column value 12.5% and text to end",
        "Right column value 83%",
    ]
