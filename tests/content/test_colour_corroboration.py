"""A repeated recognition must cover the same source ink, within its budget."""

from types import SimpleNamespace

import pytest

from aletheia_nexus.content.backends.rapid_images import read_image


@pytest.mark.parametrize(
    "case", ["same-region", "different-region", "single-scale", "script-conflict"]
)
def test_colour_completion_needs_two_source_aligned_scales(case):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new(
        "RGB", (2000, 1000) if case == "single-scale" else (400, 200), "white"
    )
    ImageDraw.Draw(image).rectangle((0, 0, image.width // 4, image.height), fill="red")
    detections = []

    def engine(prepared, *, use_det, use_cls):
        if not use_det:
            return SimpleNamespace(txts=None)
        detections.append(prepared.size)
        factor = prepared.width / image.width
        box = (100, 60, 180, 80)
        if len(detections) >= 3 and case == "different-region":
            box = (250, 120, 330, 140)
        x0, y0, x1, y1 = [v * factor for v in box]
        text = "18 h" if len(detections) == 1 else "18 h-1"
        if case == "script-conflict":
            text = ["10", "10² A", "102 A"][min(len(detections), 3) - 1]
        return SimpleNamespace(
            txts=[text],
            scores=[0.99],
            boxes=[[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]],
        )

    records = read_image(engine, image)
    complete = [
        r for r in records if r.get("method") == "rapidocr-colour-completed-reading"
    ]
    assert bool(complete) == (case == "same-region")
    original = records[0]
    assert original.get("alternative", False) == (case == "same-region")
    assert len(detections) <= 3
