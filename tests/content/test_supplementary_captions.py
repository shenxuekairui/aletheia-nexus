"""Supplement labels retain the normal caption/prose and namespace boundaries."""

from copy import deepcopy

import pytest

from aletheia_nexus.content.captions import (
    _caption_description,
    _caption_match,
    _deduplicate_caption_blocks,
)
from aletheia_nexus.content.models import PageLayout
from aletheia_nexus.content.parser import _objects


@pytest.mark.parametrize(
    ("text", "kind", "label", "description"),
    [
        ("Supplementary Figure 2. XRD patterns.", "Figure", "2", "XRD patterns."),
        ("Supplementary Fig. S3 | Optical images.", "Fig", "S3", "Optical images."),
        (
            "SUPPLEMENTARY TABLE IV. Sample parameters",
            "TABLE",
            "IV",
            "Sample parameters",
        ),
        (
            "Supplementary  Table 1. Concentrations (μmol L−1)",
            "Table",
            "1",
            "Concentrations (μmol L−1)",
        ),
    ],
)
def test_supplementary_caption_preserves_label_and_description(
    text, kind, label, description
):
    match = _caption_match(text)
    assert match is not None
    assert match.group("kind") == kind
    assert match.group("label") == label
    assert _caption_description(text, match) == description


@pytest.mark.parametrize(
    "text",
    [
        "Supplementary Figure 6 shows the measured response.",
        "Supplementary Figure 6 displays the measured response.",
        "Supplementary Fig. 6 (a) illustrates the response.",
        "Supplementary Table 2 lists the parameters.",
        "Supplementary Figure 1, 2 and 3.",
        "Supplementary Figure 1 and Supplementary Table 2 show the data.",
        "Supplementary Figures 1–3 show the data.",
        "Supplementary Figure 1–3 are compared below.",
        "Supplementary Table II–IV provide the parameters.",
    ],
)
def test_supplementary_prose_and_reference_lists_are_not_captions(text):
    assert _caption_match(text) is None


def test_combined_pdf_keeps_main_and_supplementary_number_namespaces():
    texts = [
        "Figure 1. Sample micrographs.",
        "Supplementary Figure 1. Sample micrographs.",
        "Supplementary Figure 1.Sample micrographs.",
        "Table 1. Sample parameters.",
        "Supplementary Table 1.",
    ]
    blocks = [
        dict(
            id=f"b{i}",
            anchor_id=f"a{i}",
            page=1,
            order=i + 1,
            kind="caption",
            text=text,
        )
        for i, text in enumerate(texts)
    ]
    original = deepcopy(blocks)
    _deduplicate_caption_blocks(blocks)
    assert [b["kind"] for b in blocks] == [
        "caption",
        "caption",
        "paragraph",
        "caption",
        "caption",
    ]
    assert [b["text"] for b in blocks] == texts
    assert [{**b, "kind": "caption"} for b in blocks] == original
    anchors = [dict(id=f"a{i}", bbox=[0.1, 0.1, 0.8, 0.2]) for i in range(len(texts))]
    figures, tables, _ = _objects(blocks, anchors, {1: PageLayout(1, 600, 800)})
    assert [f["label"] for f in figures] == ["1", "1"]
    assert [f["caption"] for f in figures] == texts[:2]
    assert [t["caption"] for t in tables] == texts[3:]
