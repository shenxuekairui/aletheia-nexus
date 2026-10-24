"""A table's raster conditions must not silently disappear in native mode."""

from dataclasses import replace

import pytest

from aletheia_nexus.content.models import PageLayout, PageObject
from aletheia_nexus.content.parser import _table_raster_warnings


def sample():
    anchors = {
        "caption": dict(page=1, bbox=[0.1, 0.7, 0.9, 0.75]),
        "left": dict(page=1, bbox=[0.1, 0.1, 0.3, 0.3]),
        "right": dict(page=1, bbox=[0.6, 0.1, 0.9, 0.3]),
    }
    table = dict(
        id="t1",
        anchor_id="caption",
        caption_block_id="caption",
        cells=[dict(anchor_id="left"), dict(anchor_id="right")],
    )
    image = PageObject("image", "conditions", 100, 100, (0.2, 0.4, 0.8, 0.6))
    layout = PageLayout(page=1, width=600, height=800, lines=(), objects=(image,))
    return table, anchors, layout


def test_actual_table_image_has_its_own_bounded_notice():
    table, anchors, layout = sample()
    (warning,) = _table_raster_warnings(table, [], anchors, layout, set())
    assert warning["regions"] == [[0.2, 0.4, 0.8, 0.6]]
    assert warning["object_id"] == "t1" and warning["page"] == 1
    assert warning["code"] == "RASTER_REGION_TEXT_UNVERIFIED"
    assert "conditions or results" in warning["detail"]
    assert table["cells"] == [dict(anchor_id="left"), dict(anchor_id="right")]


def test_caption_extent_includes_diagram_wider_than_its_cell_text():
    table, anchors, layout = sample()
    anchors["right"]["bbox"][2] = 0.7
    (warning,) = _table_raster_warnings(table, [], anchors, layout, set())
    assert warning["regions"] == [[0.2, 0.4, 0.8, 0.6]]


@pytest.mark.parametrize(
    "box",
    [
        (0.2, 0.8, 0.8, 0.9),  # Above the table caption.
        (0.2, 0.01, 0.8, 0.09),  # Below the observed grid.
        (0.91, 0.4, 0.99, 0.6),  # Another column.
        (0.2, 0.4, 0.21, 0.41),  # Small decoration.
    ],
)
def test_unrelated_images_do_not_warn_the_table(box):
    table, anchors, layout = sample()
    layout = replace(layout, objects=(replace(layout.objects[0], bbox=box),))
    assert not _table_raster_warnings(table, [], anchors, layout, set())


def test_intervening_caption_or_existing_figure_notice_prevents_borrowing():
    table, anchors, layout = sample()
    anchors["other"] = dict(page=1, bbox=[0.1, 0.35, 0.8, 0.38])
    block = dict(id="other", anchor_id="other", page=1, kind="caption")
    assert not _table_raster_warnings(table, [block], anchors, layout, set())
    assert not _table_raster_warnings(table, [], anchors, layout, {(1, "conditions")})
    assert not _table_raster_warnings(
        {**table, "cells": []}, [], anchors, layout, set()
    )


def test_tiled_image_keeps_its_observed_extent_and_other_page_is_not_borrowed():
    table, anchors, layout = sample()
    first = replace(layout.objects[0], bbox=(0.2, 0.4, 0.8, 0.5))
    second = replace(first, name="conditions2", bbox=(0.2, 0.5, 0.8, 0.6))
    layout = replace(layout, objects=(first, second))
    (warning,) = _table_raster_warnings(table, [], anchors, layout, set())
    assert warning["regions"] == [[0.2, 0.4, 0.8, 0.6]]
    anchors["left"]["page"] = anchors["right"]["page"] = 2
    assert not _table_raster_warnings(table, [], anchors, layout, set())
