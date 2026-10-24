from dataclasses import replace
from types import SimpleNamespace

import pytest

from aletheia_nexus.content.backends import rapid_vectors
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject


def native():
    return PageLayout(
        page=2,
        width=200,
        height=300,
        lines=(),
        objects=(PageObject("vector-text", "outlined", bbox=(0.2, 0.4, 0.7, 0.45)),),
    )


def recognize(monkeypatch, rows, layout=None):
    # Raster size differs from PDF display points; boxes use the top-left origin.
    image = SimpleNamespace(width=400, height=600)
    result = SimpleNamespace(
        boxes=[
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for _, _, (x0, y0, x1, y1) in rows
        ],
        txts=[r[0] for r in rows],
        scores=[r[1] for r in rows],
    )
    calls = []

    def engine(received, **kwargs):
        assert received is image and kwargs == dict(use_det=True, use_cls=True)
        calls.append(True)
        return result

    monkeypatch.setattr(rapid_vectors, "_engine", lambda: engine)
    monkeypatch.setattr(rapid_vectors.metadata, "version", lambda _: "fixture")
    return rapid_vectors.read_vector_annotations(image, layout or native()), calls


def test_outlined_units_and_adjacent_short_label_keep_literal_text_and_geometry(
    monkeypatch,
):
    lines, calls = recognize(
        monkeypatch,
        [
            ("−7.4 μA", 0.98, (80, 330, 280, 360)),
            ("6b", 0.96, (120, 310, 145, 329)),
            ("Unrelated", 0.99, (310, 30, 390, 50)),
            ("weak", 0.7, (90, 335, 150, 355)),
        ],
    )
    assert calls == [True]
    assert [line.text for line in lines] == ["−7.4 μA", "6b"]
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (40, 120, 140, 135)
    assert all(line.uncertain and line.content_region == "figure" for line in lines)
    assert lines[0].source_engines == ("rapidocr@fixture+vector-label",)


def test_clear_native_line_is_not_replaced_or_made_a_competing_reading(monkeypatch):
    existing = LayoutLine("−7.4 μA", 40, 120, 140, 135, 15)
    lines, _ = recognize(
        monkeypatch,
        [("74 mA", 0.99, (80, 330, 280, 360))],
        replace(native(), lines=(existing,)),
    )
    assert not lines and existing.text == "−7.4 μA"


def test_engine_numeric_scalars_satisfy_the_canonical_geometry_contract(monkeypatch):
    from fractions import Fraction

    from aletheia_nexus.content.models import validate_page_layout

    # Exercise non-builtin engine coordinates without requiring optional NumPy
    # in the native-only test installation. Real-model probes cover float32.
    lines, _ = recognize(
        monkeypatch,
        [("−7.4 μA", 0.98, tuple(Fraction(v) for v in (80, 330, 280, 360)))],
    )
    result = replace(native(), lines=lines)
    validate_page_layout(result, expected_page=2)
    assert lines[0].text == "−7.4 μA"
    assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (40, 120, 140, 135)
    assert all(
        type(value) is float
        for value in (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1)
    )


def test_image_without_unmapped_outlines_does_not_call_another_recognition_pass(
    monkeypatch,
):
    lines, calls = recognize(
        monkeypatch,
        [],
        replace(
            native(),
            objects=(PageObject("image", "photo", bbox=(0.2, 0.4, 0.7, 0.45)),),
        ),
    )
    assert not lines and not calls


@pytest.mark.parametrize("failure", [None, "exception", "invalid_geometry"])
def test_vector_recognition_failure_keeps_tesseract_result_and_is_disclosed(
    monkeypatch, failure
):
    from pathlib import Path
    from subprocess import CompletedProcess

    from pypdf import PdfWriter

    from aletheia_nexus.content.backends import tesseract
    from aletheia_nexus.content.models import PageRegion

    Image = pytest.importorskip("PIL.Image")
    backend = tesseract.TesseractOcrBackend(
        tesseract.TesseractOcrConfig(
            image_ocr="rapidocr", detect_orientation=False, deskew=False, binarize=False
        )
    )
    page = PdfWriter().add_blank_page(200, 300)
    renders = []

    def run(command, *, timeout):
        if command[0] == "pdftoppm":
            renders.append(command)
            Image.new("RGB", (400, 600), "white").save(command[-1] + ".png")
            return CompletedProcess(command, 0, "", "")
        assert Path(command[1]).name == "prepared.png"
        return CompletedProcess(
            command,
            0,
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t80\t330\t100\t30\t99\t7.4\n",
            "",
        )

    def read(image, layout):
        assert image.mode == "RGB" and image.size == (400, 600)
        if failure == "exception":
            raise RuntimeError("local model unavailable")
        return (
            LayoutLine(
                "−7.4 μA",
                40,
                120,
                float("nan") if failure == "invalid_geometry" else 140,
                135,
                15,
                extraction_method="rapidocr-vector-outline",
                content_region="figure",
                uncertain=True,
            ),
        )

    monkeypatch.setattr(tesseract, "_run", run)
    monkeypatch.setattr(rapid_vectors, "read_vector_annotations", read)
    monkeypatch.setattr(
        backend, "_retry_unit_superscripts", lambda image, payload, lines, root: lines
    )
    result = backend.extract_regions(
        page,
        2,
        (PageRegion("figure", (0.2, 0.4, 0.7, 0.45), "outlined"),),
        native_layout=native(),
    )
    assert len(renders) == 1
    assert [line.text for line in result.lines] == (
        ["7.4"] if failure else ["−7.4 μA", "7.4"]
    )
    assert any(w["code"] == "OCR_BACKEND_FAILED" for w in result.warnings) == bool(
        failure
    )
