"""A plot's blank interior is not a set of micrograph panels."""

from copy import deepcopy

import pytest

from aletheia_nexus.content.backends.image_panels import associate_scales, panel_boxes


def test_two_framed_plots_keep_interior_measurements_together():
    Image = pytest.importorskip("PIL.Image")
    Draw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("RGB", (800, 420), "white")
    draw = Draw.Draw(image)
    for left in (20, 440):
        draw.rectangle((left, 20, left + 320, 390), outline="black", width=2)
        for y in (80, 170, 260):
            draw.line((left + 1, y, left + 315, y + 40), fill="gray", width=2)
    boxes = panel_boxes(image)
    # In each frame, the separated peak labels remain in the same region.
    for left in (20, 440):
        containing = [
            b for b in boxes if b[0] <= left + 260 < b[2] and b[1] <= 80 < b[3]
        ]
        assert len(containing) == 1
        assert containing[0][1] <= 260 < containing[0][3]
    readings = [
        dict(text=f"{n} cm", box=(270, y, 315, y + 15), score=0.99)
        for n, y in ((710, 80), (720, 170), (730, 260))
    ]
    result = associate_scales(deepcopy(readings), image)
    assert not any(r.get("method") == "positioned-panel-length" for r in result)
    assert result == readings


@pytest.mark.parametrize("gutter", [8, 45, 90])
def test_real_wide_and_narrow_gutters_keep_printed_panel_names(gutter):
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (600 + gutter, 440), "gray")
    image.paste("white", (300, 0, 300 + gutter, 440))
    image.paste("white", (0, 210, image.width, 230))
    records = []
    for i, (x, y) in enumerate(
        ((0, 0), (300 + gutter, 0), (0, 230), (300 + gutter, 230))
    ):
        records.extend(
            [
                dict(
                    text=f"({chr(65 + i)})",
                    box=(x + 10, y + 10, x + 35, y + 30),
                    score=0.99,
                ),
                dict(
                    text=f"{3 + i} μm",
                    box=(x + 200, y + 170, x + 260, y + 190),
                    score=0.98,
                ),
            ]
        )
    result = associate_scales(records, image)
    assert {
        r["text"] for r in result if r.get("method") == "positioned-panel-length"
    } == {
        f"Panel ({chr(65 + i)}): length label {3 + i} μm; role unverified"
        for i in range(4)
    }


def test_large_white_margin_does_not_invent_a_second_panel():
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (500, 400), "white")
    image.paste("gray", (80, 40, 420, 360))
    assert panel_boxes(image) == [(0, 0, 500, 400)]


def test_detector_wavelength_is_not_promoted_to_a_scale_bar():
    Image = pytest.importorskip("PIL.Image")
    Draw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("RGB", (800, 420), "white")
    draw = Draw.Draw(image)
    for left in (20, 440):
        draw.rectangle((left, 20, left + 320, 390), outline="black", width=2)
        draw.line(
            (left + 1, 350, left + 180, 100, left + 315, 350), fill="gray", width=2
        )
    records = [
        dict(text="313 nm", box=(260, 45, 315, 60), score=0.99),
        dict(text="(a)", box=(25, 25, 45, 40), score=0.99),
    ]
    result = associate_scales(deepcopy(records), image)
    derived = [r for r in result if r.get("method") == "positioned-panel-length"]
    assert len(derived) == 1
    assert derived[0]["text"] == "Panel (a): length label 313 nm; role unverified"
    assert not any("scale" in r["text"] for r in result)
    source = next(r for r in result if r["text"] == "313 nm")
    assert source["box"] == records[0]["box"]
    assert source["alternative"] and source["association_source"]
