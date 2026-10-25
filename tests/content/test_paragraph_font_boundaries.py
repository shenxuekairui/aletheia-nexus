"""Self-authored text layouts: font changes must not erase subsection boundaries."""

from pypdf import PdfWriter
from pypdf.generic import NameObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.models import PipelineContext
from aletheia_nexus.content.parser import ParserConfig, _NativeExtractionStage


def test_unknown_heading_weight_keeps_font_boundary_and_body_continuation():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    other_face = regular_font()
    # A different face without any bold/heading marker. Classification must
    # not depend on a publisher-specific font name or scientific vocabulary.
    other_face[NameObject("/BaseFont")] = NameObject("/Helvetica-Oblique")
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(R=regular_font(), H=other_face)
    )
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /H 12 Tf 50 700 Td (Sample treatment) Tj ET "
        b"BT /R 12 Tf 50 684 Td (The material was washed) Tj ET "
        b"BT /R 12 Tf 50 668 Td (and then dried.) Tj ET "
        b"BT /H 12 Tf 50 640 Td (Independent measurement) Tj ET "
        b"BT /R 12 Tf 50 624 Td (The signal was recorded.) Tj ET",
    )
    context = PipelineContext(
        source=None,
        reader=writer,
        config=ParserConfig(),
        created_at="2026-10-26T00:00:00+00:00",
        backend=LayoutPdfBackend(),
    )
    _NativeExtractionStage().run(context)
    assert not context.errors
    assert [b["text"] for b in context.blocks] == [
        "Sample treatment",
        "The material was washed and then dried.",
        "Independent measurement",
        "The signal was recorded.",
    ]
    # A font change is not an automatic claim that the line is a section title.
    assert all(b["kind"] == "paragraph" for b in context.blocks)
    assert all(b["anchor_id"] for b in context.blocks)


def test_inline_emphasis_and_small_symbols_keep_the_body_majority_font():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    emphasis = regular_font()
    emphasis[NameObject("/BaseFont")] = NameObject("/Helvetica-Bold")
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(R=regular_font(), E=emphasis)
    )
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /R 12 Tf 50 700 Td (Ordinary text with ) Tj "
        b"/E 12 Tf (one) Tj /R 12 Tf ( emphasized word) Tj ET "
        b"BT /R 12 Tf 50 684 Td (and a small marker ) Tj "
        b"/E 7 Tf 3 Ts (x) Tj ET",
    )
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert len(layout.lines) == 2
    assert {line.dominant_font for line in layout.lines} == {"Helvetica"}
