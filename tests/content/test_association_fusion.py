"""Relation evidence and its component readings have different spatial scopes."""

from dataclasses import replace

import pytest

from aletheia_nexus.content.backends import AdaptiveOcrBackend
from aletheia_nexus.content.models import LayoutLine, PageLayout


def line(text, box, *, method="image-reading", alternative=False, score=0.98):
    return LayoutLine(
        text,
        *box,
        10,
        extraction_method=method,
        extraction_confidence=score,
        source_engines=(method,),
        content_region="ocr-alternative" if alternative else "figure",
        uncertain=True,
    )


@pytest.mark.parametrize(
    "method",
    [
        "printed-bar-label-association",
        "positioned-axis-label-ticks",
        "positioned-panel-scale",
    ],
)
def test_relationship_does_not_compete_with_overlapping_legends_or_other_relations(
    method,
):
    page = PageLayout(page=1, width=600, height=800)
    legend = line("Alpha", (100, 400, 150, 410))
    first = line("Observed group one", (90, 200, 350, 420), method=method)
    second = replace(first, text="Observed group two")
    output, warnings = AdaptiveOcrBackend()._merge(
        page, [replace(page, lines=(legend, first, second))]
    )
    assert [x.text for x in output if not x.content_region.endswith("alternative")] == [
        legend.text,
        first.text,
        second.text,
    ]
    assert all(x.uncertain for x in output)
    assert not any(w["code"] == "OCR_ENGINE_DISAGREEMENT" for w in warnings)


@pytest.mark.parametrize("text", ["37.2", "372", "-37.2", "37.2 mL"])
def test_secondary_ocr_compares_with_the_actual_source_of_a_relation(text):
    page = PageLayout(page=1, width=600, height=800)
    source = line(
        "37.2",
        (100, 250, 130, 260),
        method="image-reading+association-source",
        alternative=True,
    )
    relation = line(
        "Sample C: Alpha 37.2; Beta 19",
        (80, 200, 400, 420),
        method="printed-bar-label-association",
    )
    ocr = line(text, (101, 249, 131, 261), method="page-ocr", score=0.88)
    other = line("37.2", (450, 250, 480, 260), method="page-ocr")
    output, warnings = AdaptiveOcrBackend()._merge(
        page,
        [replace(page, lines=(source, relation)), replace(page, lines=(ocr, other))],
    )
    primary = [x for x in output if not x.content_region.endswith("alternative")]
    assert [x.text for x in primary] == [relation.text, other.text]
    assert primary[-1].x0 == other.x0
    if text == source.text:
        raw = next(x for x in output if x.x0 < 200 and x.text == source.text)
        assert set(raw.source_engines) == {source.extraction_method, "page-ocr"}
        assert not any(w["code"] == "OCR_ENGINE_DISAGREEMENT" for w in warnings)
    else:
        assert any(
            x.text == text and x.content_region == "ocr-alternative" for x in output
        )
        warning = next(w for w in warnings if w["code"] == "OCR_ENGINE_DISAGREEMENT")
        assert warning["page"] == 1
        assert warning["bbox"] == pytest.approx(
            [101 / 600, 249 / 800, 131 / 600, 261 / 800]
        )


def test_unrelated_alternative_does_not_suppress_a_new_primary_reading():
    page = PageLayout(page=1, width=600, height=800)
    old = line("7.3", (100, 250, 130, 260), alternative=True)
    current = line("73", (100, 250, 130, 260), method="page-ocr")
    output, _ = AdaptiveOcrBackend()._merge(page, [replace(page, lines=(old, current))])
    assert [x.text for x in output if not x.content_region.endswith("alternative")] == [
        "73"
    ]
