"""Caption boundaries use page layout, without paper-specific text or answers."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.models import LayoutLine, PageLayout, PipelineContext
from aletheia_nexus.content.parser import (
    ParserConfig,
    _can_merge_caption,
    _NativeExtractionStage,
    _objects,
)


def line(text, y, *, right=550, size=9, **kwargs):
    return LayoutLine(
        text,
        50,
        y,
        right,
        y + size,
        size,
        dominant_font="Fixture-Regular",
        **kwargs,
    )


def assemble(lines, *, scale=1, config=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600 * scale, height=800 * scale)
    layout = PageLayout(1, 600 * scale, 800 * scale, lines=tuple(lines))
    backend = SimpleNamespace(
        name="caption-fixture", version="1", extract_page=lambda *_: layout
    )
    context = PipelineContext(
        source=None,
        reader=SimpleNamespace(pages=[page]),
        backend=backend,
        config=config or ParserConfig(),
        created_at="2026-01-01T00:00:00Z",
    )
    _NativeExtractionStage().run(context)
    assert not context.errors
    return context


def body_style():
    # Independent body text establishes the dominant page style.
    return line(
        "A separate paragraph explains the surrounding observations. " * 8, 100, size=10
    )


@pytest.mark.parametrize("scale", [0.7, 1.6])
def test_caption_keeps_short_formula_tail_but_not_following_same_font_prose(scale):
    lines = [
        line("Figure 1. Recorded signals and their plotted comparison with", 600),
        line("the reference measurement. The relation is defined by", 589),
        line("E = k × t.", 578, right=150),
        line("This is a separate body paragraph after the completed caption.", 567),
        body_style(),
    ]
    scaled = [
        replace(
            item,
            x0=item.x0 * scale,
            x1=item.x1 * scale,
            y0=item.y0 * scale,
            y1=item.y1 * scale,
            font_size=item.font_size * scale,
        )
        for item in lines
    ]
    context = assemble(scaled, scale=scale)
    caption, body, _ = context.blocks
    assert caption["text"] == " ".join(item.text for item in lines[:3])
    assert caption["kind"] == "caption" and caption["line_count"] == 3
    assert caption["uncertain"]  # Formula classification is not silently erased.
    assert body["text"] == lines[3].text and body["kind"] == "paragraph"
    anchor = context.anchors[0]
    assert anchor["text_evidence"] == caption["text"]
    assert anchor["span"] == {"start": 0, "end": len(caption["text"])}
    assert anchor["bbox"] == pytest.approx(
        [50 / 600, 578 / 800, 550 / 600, 609 / 800], abs=1e-6
    )
    figures, _, _ = _objects(context.blocks, context.anchors, context.layouts)
    assert len(figures) == 1 and figures[0]["caption"] == caption["text"]


@pytest.mark.parametrize(
    "change",
    [
        {"font_size": 10, "y1": 599},
        {"dominant_font": "Other-Regular"},
        {"content_region": "table-cell"},
        {"content_region": "figure"},
        {"extraction_method": "ocr"},
        {"x0": 320, "x1": 590},
        {"x1": 590},
        {"y0": 570, "y1": 579},
    ],
)
def test_caption_does_not_cross_font_column_region_or_spacing_boundary(change):
    first = line("Figure 2. Overview of the recorded observations.", 600)
    next_line = replace(
        line("This line belongs to another layout region.", 589), **change
    )
    assert not _can_merge_caption(first, first, next_line, median_font=10)


def test_unknown_font_and_table_captions_do_not_gain_inferred_continuations():
    first = line("Figure 3. Overview of the recorded observations.", 600)
    continuation = line("Additional text without reliable font metadata.", 589)
    unknown = [replace(item, dominant_font=None) for item in (first, continuation)]
    assert len(assemble(unknown).blocks) == 2
    assert not _can_merge_caption(
        replace(first, text="Table 3. Measurements."),
        first,
        continuation,
        median_font=10,
    )


def test_new_caption_is_a_boundary_even_with_matching_line_style():
    lines = [
        line("Figure 4. The first illustrated comparison.", 600),
        line("Figure 5. A separate illustrated comparison.", 589),
    ]
    context = assemble(lines)
    assert [b["text"] for b in context.blocks] == [item.text for item in lines]


def test_caption_merge_respects_text_limit_without_partially_appending_a_line():
    first = line("Figure 6. First part of a continued caption with", 600)
    continuation = line("more information from the same original caption.", 589)
    context = assemble(
        [first, continuation, body_style()],
        config=ParserConfig(max_text_characters=len(first.text) + 2),
    )
    assert context.stopped_early
    assert (
        context.blocks[0]["text"] == context.anchors[0]["text_evidence"] == first.text
    )


def test_same_style_caption_and_prose_remain_separate_without_independent_style_evidence():
    first = line("Figure 7. Comparison of the measured signal and reference.", 600)
    tail = line("The last caption line ends here.", 589, right=460)
    body = line("The following paragraph uses the very same layout style.", 578)
    context = assemble([first, tail, body])
    assert context.blocks[0]["text"] == first.text
    assert all(b["kind"] != "caption" for b in context.blocks[1:])


def test_prose_reference_cannot_replace_a_caption_after_continuation_is_joined():
    first = line(
        "Scheme 8. The stages of the illustrated process and its constituent parts", 600
    )
    continuation = line(
        "are presented for comparison with the reference.", 589, right=420
    )
    reference = line(
        "Scheme 8. Notably, the comparison informs our discussion.", 450, size=10
    )
    context = assemble([first, continuation, reference, body_style()])
    figures, _, _ = _objects(context.blocks, context.anchors, context.layouts)
    assert len(figures) == 1
    assert figures[0]["caption"] == first.text + " " + continuation.text
    assert any(
        b["kind"] == "paragraph" and reference.text in b["text"] for b in context.blocks
    )


def test_demoted_duplicate_caption_start_remains_a_continuation_boundary():
    first = line(
        "Figure 9. Comparison of all the recorded measurements and plotted reference values.",
        600,
    )
    duplicate = line("Figure 9. A shorter repeated reference.", 589)
    context = assemble([first, duplicate, body_style()])
    assert context.blocks[0]["text"] == first.text
    assert context.blocks[1]["text"] == duplicate.text
    assert context.blocks[1]["kind"] == "paragraph"
