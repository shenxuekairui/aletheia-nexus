"""Figure ownership uses whole geometric groups, never a paper-specific layout."""

import pytest

from aletheia_nexus.content.models import PageLayout, PageObject
from aletheia_nexus.content.parser import _objects


def associate(caption_boxes, image_boxes, reverse=False):
    blocks = [
        dict(
            id=f"c{i}",
            anchor_id=f"a{i}",
            page=1,
            kind="caption",
            text=f"Fig. {i + 1}. Example.",
        )
        for i in range(len(caption_boxes))
    ]
    anchors = [dict(id=f"a{i}", bbox=box) for i, box in enumerate(caption_boxes)]
    images = [
        PageObject("image", f"im{i}", 300, 200, box)
        for i, box in enumerate(image_boxes)
    ]
    if reverse:
        blocks.reverse()
        images.reverse()
    figures, _, unassociated = _objects(
        blocks, anchors, {1: PageLayout(1, 600, 800, objects=tuple(images))}
    )
    return {
        f["caption_block_id"]: {o["name"] for o in f["source_objects"]} for f in figures
    }, unassociated


@pytest.mark.parametrize("reverse", [False, True])
def test_true_two_sided_ambiguity_keeps_caption_only(reverse):
    groups, unassociated = associate(
        [(0.1, 0.48, 0.8, 0.5)],
        [(0.1, 0.52, 0.8, 0.7), (0.1, 0.28, 0.8, 0.46)],
        reverse,
    )
    assert groups == {"c0": set()}
    assert unassociated == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_same_side_shared_group_has_no_first_caption_winner(reverse):
    groups, unassociated = associate(
        [(0.1, 0.35, 0.8, 0.37), (0.1, 0.38, 0.8, 0.4)],
        [(0.1, 0.42, 0.8, 0.6)],
        reverse,
    )
    assert groups == {"c0": set(), "c1": set()}
    assert unassociated == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_partial_ownership_does_not_trim_a_candidate_or_choose_its_other_side(reverse):
    groups, unassociated = associate(
        [(0.1, 0.5, 0.85, 0.52), (0.1, 0.67, 0.35, 0.69)],
        [(0.1, 0.55, 0.35, 0.65), (0.55, 0.55, 0.85, 0.65), (0.1, 0.37, 0.85, 0.47)],
        reverse,
    )
    assert groups == {"c0": set(), "c1": {"im0"}}
    assert unassociated == 2


def test_far_opposite_side_does_not_expand_original_seed_window():
    groups, _ = associate(
        [(0.1, 0.4, 0.8, 0.42)],
        [(0.1, 0.43, 0.8, 0.6), (0.1, 0.2, 0.8, 0.3)],
    )
    assert groups == {"c0": {"im0"}}


def test_image_overlapping_caption_remains_unassigned():
    groups, unassociated = associate([(0.1, 0.4, 0.8, 0.42)], [(0.1, 0.3, 0.8, 0.6)])
    assert groups == {"c0": set()}
    assert unassociated == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_side_by_side_figures_keep_separate_groups(reverse):
    groups, unassociated = associate(
        [(0.1, 0.4, 0.4, 0.42), (0.55, 0.4, 0.85, 0.42)],
        [(0.1, 0.44, 0.4, 0.7), (0.55, 0.44, 0.85, 0.7)],
        reverse,
    )
    assert groups == {"c0": {"im0"}, "c1": {"im1"}}
    assert unassociated == 0
