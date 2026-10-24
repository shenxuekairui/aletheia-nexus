"""Source geometry must keep a rotated exponent with its own unit label."""

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend


def extract(content):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    page[NameObject("/Contents")] = stream(writer, content)
    return LayoutPdfBackend().extract_page(page, 1)


@pytest.mark.parametrize("direction", [1, -1])
@pytest.mark.parametrize("scale", [0.7, 1, 1.5])
@pytest.mark.parametrize("exponent,expected", [("-7", "⁻⁷"), ("+2", "⁺²"), ("3", "³")])
def test_rotated_exponents_keep_sign_value_and_following_unit(
    direction, scale, exponent, expected
):
    layout = extract(
        f"q 0 {direction * scale} {-direction * scale} 0 200 400 cm "
        f"BT /F 10 Tf 1 0 0 1 0 0 Tm (Flux 10) Tj "
        f"/F 6 Tf 4 Ts ({exponent}) Tj /F 10 Tf 0 Ts ( A) Tj ET Q".encode()
    )
    assert [line.text for line in layout.lines] == [f"Flux 10{expected} A"]
    assert layout.lines[0].content_region == "figure"


def test_rotated_unit_exponents_do_not_merge_across_axes():
    content = b""
    for x, exponent in [(200, -2), (400, -3)]:
        content += (
            f"q 0 1 -1 0 {x} 300 cm BT /F 10 Tf 1 0 0 1 0 0 Tm (Rate m) Tj "
            f"/F 6 Tf 4 Ts ({exponent}) Tj ET Q "
        ).encode()
    layout = extract(content)
    assert [line.text for line in sorted(layout.lines, key=lambda line: line.x0)] == [
        "Rate m⁻²",
        "Rate m⁻³",
    ]


@pytest.mark.parametrize("size,rise", [(10, 4), (6, -4)])
def test_equal_size_or_lower_annotation_does_not_become_an_exponent(size, rise):
    layout = extract(
        f"q 0 1 -1 0 200 300 cm BT /F 10 Tf 1 0 0 1 0 0 Tm (Rate m) Tj "
        f"/F {size} Tf {rise} Ts (-7) Tj ET Q".encode()
    )
    assert not any("⁻⁷" in line.text for line in layout.lines)
    assert any("-7" in line.text for line in layout.lines)


def test_competing_bases_or_overlapping_scripts_stay_separate():
    from types import SimpleNamespace

    from aletheia_nexus.content.backends.vertical_text import _join_raised_numbers

    def glyph(text, baseline, start, size, advance=5):
        return SimpleNamespace(
            get_text=lambda: text,
            x0=baseline - size,
            x1=baseline,
            y0=start,
            y1=start + advance,
            matrix=(0, 1, -1, 0, baseline, start),
        )

    base = [glyph("m", 200, 300, 10), glyph("A", 200, 320, 10)]
    competing = [glyph("n", 202, 300, 10), glyph("B", 202, 320, 10)]
    script = [glyph("2", 197, 305, 6)]
    runs = [(True, base), (True, competing), (True, script)]
    result, raised = _join_raised_numbers(runs)
    assert result == runs and not raised
    other_script = [glyph("3", 196, 305, 6)]
    runs = [(True, base), (True, script), (True, other_script)]
    result, raised = _join_raised_numbers(runs)
    assert result == runs and not raised
