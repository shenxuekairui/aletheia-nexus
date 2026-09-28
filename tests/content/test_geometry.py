import pytest

from aletheia_nexus.content.backends.tesseract import _prepared_bbox_to_canonical
from aletheia_nexus.content.geometry import PageGeometry


class _Box(tuple):
    @property
    def left(self):
        return self[0]

    @property
    def bottom(self):
        return self[1]

    @property
    def right(self):
        return self[2]

    @property
    def top(self):
        return self[3]


class _Page(dict):
    mediabox = _Box((0, 0, 800, 1000))
    cropbox = _Box((100, 200, 700, 900))


@pytest.mark.parametrize(
    ("rotation", "expected_size", "point", "expected"),
    [
        (0, (600, 700), (100, 200), (0, 0)),
        (90, (700, 600), (100, 200), (0, 600)),
        (180, (600, 700), (100, 200), (600, 700)),
        (270, (700, 600), (100, 200), (700, 0)),
    ],
)
def test_cropbox_origin_and_page_rotation_share_one_display_space(
    rotation, expected_size, point, expected
):
    page = _Page({"/Rotate": rotation})
    geometry = PageGeometry.from_page(page)

    assert (geometry.width, geometry.height) == expected_size
    assert geometry.point(*point) == expected


def test_ocr_orientation_and_deskew_bbox_maps_back_to_original_raster():
    bbox = _prepared_bbox_to_canonical(
        (100, 200, 300, 260),
        prepared_width=800,
        prepared_height=600,
        original_width=600,
        original_height=800,
        orientation_rotation=90,
        deskew_angle=0,
    )

    assert bbox == pytest.approx((1 / 3, 0.125, 13 / 30, 0.375))


def test_page_geometry_rejects_non_finite_boxes():
    page = _Page()
    page.cropbox = _Box((0, 0, float("nan"), 10))
    with pytest.raises(ValueError, match="finite"):
        PageGeometry.from_page(page)
