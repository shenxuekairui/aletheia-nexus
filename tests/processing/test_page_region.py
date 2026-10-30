"""Regions refer to displayed CropBox pixels, including nonzero origins/rotation."""

import io
import shutil
import struct

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, RectangleObject

from aletheia_nexus.processing.materials import render_page, render_page_region
from aletheia_nexus.processing.provider import ProcessingError


@pytest.mark.parametrize(
    "region",
    [
        [],
        [0, 0, 0, 1],
        [0, 0, 2, 1],
        [0.9, 0, 0.1, 1],
        [0, -0.1, 1, 1],
        [0, 0, True, 1],
        [0, 0, float("nan"), 1],
    ],
)
def test_invalid_region_never_invokes_renderer(region, monkeypatch):
    import aletheia_nexus.processing.materials as module

    def unexpected(*args, **kwargs):
        raise AssertionError("Invalid region must not render a source")

    monkeypatch.setattr(module, "render_page", unexpected)
    with pytest.raises(ProcessingError, match="invalid_page_region"):
        render_page_region(None, 1, region)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_region_matches_actual_full_page_pixels_and_provenance(tmp_path, rotation):
    if not shutil.which("pdftoppm"):
        pytest.skip("Poppler page renderer unavailable")
    Image = pytest.importorskip("PIL.Image")
    pdf = tmp_path / "nonzero-cropbox.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(300, 220)
    page.cropbox = RectangleObject((50, 30, 250, 190))
    page.rotate(rotation)
    stream = DecodedStreamObject()
    stream.set_data(b"1 0 0 rg 50 30 100 160 re f 0 0 1 rg 150 30 100 160 re f")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(pdf)
    original = pdf.read_bytes()
    full = Image.open(io.BytesIO(render_page(pdf, 1, scale=3200))).convert("RGB")
    view = render_page_region(pdf, 1, [0.1, 0.15, 0.7, 0.85])
    left, top, width, height = view["crop_pixels_xywh"]
    cropped = Image.open(io.BytesIO(view["bytes"])).convert("RGB")
    assert cropped.size == (width, height)
    assert view["full_render_size"] == list(full.size)
    assert view["coordinates"] == "displayed-cropbox-normalized-top-left"
    assert view["requested_region"] == [0.1, 0.15, 0.7, 0.85]
    for x in (width // 4, 3 * width // 4):
        for y in (height // 4, 3 * height // 4):
            assert cropped.getpixel((x, y)) == full.getpixel((left + x, top + y))
    assert struct.unpack(">II", view["bytes"][16:24]) == (width, height)
    assert pdf.read_bytes() == original
