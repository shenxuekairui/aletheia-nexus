"""Painted strips retain source pixels and cannot bridge unrelated panels."""

from types import SimpleNamespace

import pytest

from aletheia_nexus.content.backends.image_annotations import _join_painted_strips
from aletheia_nexus.content.image_tiles import vertical_tile_groups
from aletheia_nexus.content.models import PageLayout, PageObject
from aletheia_nexus.content.parser import _StructureStage


@pytest.mark.parametrize("count", [3, 17, 1000])
def test_thin_tiled_figures_keep_all_resources_and_complete_local_warning(count):
    objects = []
    for col, left in enumerate([0.1, 0.55]):
        for row in range(count):
            objects.append(
                PageObject(
                    "image",
                    f"column{col}-tile{row}",
                    300,
                    1,
                    (
                        left,
                        0.5 + row * 0.3 / count,
                        left + 0.3,
                        0.5 + (row + 1) * 0.3 / count,
                    ),
                )
            )
    blocks = [
        dict(
            id=f"b{i}",
            anchor_id=f"a{i}",
            page=1,
            kind="caption",
            text=f"Figure {i + 1}. Images.",
        )
        for i in range(2)
    ]
    context = SimpleNamespace(
        blocks=blocks,
        anchors=[
            dict(id=f"a{i}", bbox=[x, 0.46, x + 0.3, 0.48])
            for i, x in enumerate([0.1, 0.55])
        ],
        layouts={1: PageLayout(1, 600, 800, objects=tuple(objects))},
        warnings=[],
    )
    _StructureStage().run(context)
    assert context.unassociated_image_resources == 0
    for i, figure in enumerate(context.figures):
        assert {o["name"] for o in figure["source_objects"]} == {
            f"column{i}-tile{row}" for row in range(count)
        }
        assert context.warnings[i]["regions"] == [
            pytest.approx([0.1 + 0.45 * i, 0.5, 0.4 + 0.45 * i, 0.8])
        ]


def test_gaps_shifted_columns_and_overlapping_resources_do_not_form_tiles():
    boxes = [
        (0, 0.6, 0.4, 0.8),
        (0, 0.4, 0.4, 0.6),
        (0, 0.1, 0.4, 0.3),
        (0.01, 0.6, 0.41, 0.8),
        (0.5, 0.4, 0.9, 0.6),
        (0.5, 0.4, 0.9, 0.6),
        (0.5, 0.2, 0.9, 0.4),
    ]
    assert vertical_tile_groups(boxes, tolerance=1e-6) == [
        [0, 1],
        [2],
        [3],
        [4],
        [5],
        [6],
    ]


@pytest.mark.parametrize("height", [1, 5, 20])
def test_joined_source_pixels_keep_top_to_bottom_order_without_resampling(height):
    Image = pytest.importorskip("PIL.Image")
    images = [
        (
            str(i),
            Image.new("RGB", (80, height), color),
            (0, (2 - i) * height, 80, (3 - i) * height),
        )
        for i, color in enumerate(["red", "green", "blue"])
    ]
    joined = _join_painted_strips(list(reversed(images)), 1_000_000)
    assert len(joined) == 1
    name, image, bounds = joined[0]
    assert name == "0+1+2"
    assert image.size == (80, height * 3)
    assert image.tobytes() == b"".join(im.tobytes() for _, im, _ in images)
    assert bounds == (0, 0, 80, height * 3)
    assert len(_join_painted_strips(images, 80 * height * 2)) == 3


def test_pixel_sampling_disagreement_abstains_from_stitching():
    Image = pytest.importorskip("PIL.Image")
    images = [
        ("a", Image.new("L", (80, 20)), (0, 20, 80, 40)),
        ("b", Image.new("L", (80, 40)), (0, 0, 80, 20)),
    ]
    assert _join_painted_strips(images, 1_000_000) == images
