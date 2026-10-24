"""Spaced source prose must not acquire a nearby figure's evidence."""

import pytest

from aletheia_nexus.content.captions import _caption_match
from aletheia_nexus.content.models import PageLayout, PageObject
from aletheia_nexus.content.parser import _objects


@pytest.mark.parametrize(
    "text",
    [
        "图 8(C) 给 出 了不同温度下的测量曲线。",
        "表 4 显 示 了所有实验结果。",
        "图 8为不同材料在2.5 A下的测量结果。其中，样品存在差异。",
        "图 8 为不同材料的变化 . 其 中，横轴表示时间。",
    ],
)
def test_spaced_caption_mentions_are_kept_as_prose(text):
    assert _caption_match(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "图 8 (C) 不同温度的测量曲线",
        "表 4 显示器件的实验参数",
        "图 8 为不同材料的测量结果",
        "图 8 不同材料的测量结果。其中，横轴表示时间。",
    ],
)
def test_real_descriptive_captions_remain_recognized(text):
    assert _caption_match(text)


def test_prose_mention_does_not_claim_an_unrelated_nearby_image():
    captions = [
        dict(
            id="a",
            anchor_id="aa",
            page=1,
            kind="caption",
            text="Figure 3. Measurements.",
        ),
        dict(
            id="b",
            anchor_id="ab",
            page=1,
            kind="caption",
            text="图 8(A) 给 出 了下一组测量结果。",
        ),
    ]
    anchors = [
        dict(id="aa", bbox=[0.1, 0.36, 0.8, 0.38]),
        dict(id="ab", bbox=[0.1, 0.2, 0.8, 0.22]),
    ]
    original = [b.copy() for b in captions]
    figures, _, unassociated = _objects(
        captions,
        anchors,
        {
            1: PageLayout(
                1,
                600,
                800,
                objects=(PageObject("image", "im", 500, 300, (0.1, 0.4, 0.8, 0.7)),),
            )
        },
    )
    assert [f["label"] for f in figures] == ["3"]
    assert unassociated == 0
    assert [b["text"] for b in captions] == [b["text"] for b in original]
