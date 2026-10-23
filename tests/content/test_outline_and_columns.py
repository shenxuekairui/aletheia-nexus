"""Independent shapes/layouts: no paper values or embedded sample fonts."""

import math

import pytest
from pypdf.generic import DecodedStreamObject, NameObject
from test_accuracy import symbol_page
from test_table_relations import glyph_line, line
from test_unit_mapping import CAPITAL, MU, polygon, program

from aletheia_nexus.content.backends.font_symbols import (
    _outlined_unit,
    mapped_outline_units,
)
from aletheia_nexus.content.backends.layout import LayoutPdfBackend
from aletheia_nexus.content.evidence import review_locations
from aletheia_nexus.content.models import PageLayout, PageObject, validate_page_layout
from aletheia_nexus.content.parser import _objects, _prepare_table_lines


def arc(cx, cy, rx, ry, start, stop):
    return [
        (
            round(cx + rx * math.cos(math.radians(t)), 2),
            round(cy + ry * math.sin(math.radians(t)), 2),
        )
        for t in [start + (stop - start) * i / 40 for i in range(41)]
    ]


def lower_m(thickness=65):
    result = []
    for x in [50, 350, 650]:
        result += polygon([(x, 0), (x + thickness, 0), (x + thickness, 410), (x, 410)])
    for cx in [232.5, 532.5]:
        result += polygon(
            arc(cx, 350, 182.5, 150, 0, 180)
            + arc(cx, 350, 182.5 - thickness, 150 - thickness, 180, 0)
        )
    return result


def celsius(letter="C"):
    ring = polygon(arc(130, 800, 105, 105, 0, 360))
    ring += polygon(arc(130, 800, 65, 65, 360, 0))
    end = {"C": (45, 315), "O": (0, 360)}[letter]
    return ring + polygon(
        arc(550, 450, 300, 360, *end) + arc(550, 450, 235, 295, *reversed(end))
    )


@pytest.mark.parametrize("factor", [0.5, 1, 2.4])
@pytest.mark.parametrize(
    "ops,expected",
    [
        (lower_m(), "m"),
        (lower_m(95), "m"),
        (celsius(), "℃"),
        (celsius("O"), None),
        (CAPITAL, None),
        (MU, None),
        (polygon([(0, 0), (500, 0), (500, 60), (70, 60), (70, 600), (0, 600)]), None),
    ],
)
def test_unit_shape_scales_without_using_a_mapping_label(factor, ops, expected):
    scaled = [
        (op, tuple((x * factor, y * factor) for x, y in points)) for op, points in ops
    ]
    assert _outlined_unit(scaled, 1000 * factor) == expected


def test_three_unconnected_stems_are_not_m():
    stems = sum(
        (
            polygon([(x, 0), (x + 65, 0), (x + 65, 480), (x, 480)])
            for x in [50, 350, 650]
        ),
        [],
    )
    assert _outlined_unit(stems, 1000) is None


def test_unsupported_font_program_does_not_discard_a_page():
    page = symbol_page(mapped=True, broken=True)
    assert mapped_outline_units(page) == {}
    assert LayoutPdfBackend().extract_page(page, 1).lines[0].text == "@"


@pytest.mark.parametrize(
    "ops,mapping,source,expected",
    [
        (
            lower_m(),
            "L",
            b"(24 A/) Tj /F1 12 Tf (m) Tj /FR 12 Tf (2; L = label)",
            "24 A/m2; L = label",
        ),
        (
            celsius(),
            "?",
            b"(at 36) Tj /F1 12 Tf (m) Tj /FR 12 Tf (; /) Tj /F1 12 Tf (m)",
            "at 36℃; /℃",
        ),
    ],
)
def test_corrected_custom_mapping_keeps_original_evidence(
    ops, mapping, source, expected
):
    integral = [
        (op, tuple((round(x), round(y)) for x, y in points)) for op, points in ops
    ]
    page = symbol_page(m_program=program(integral))
    font = page["/Resources"]["/Font"]["/F1"]
    cmap = DecodedStreamObject()
    cmap.set_data(
        f"begincmap 1 beginbfchar <6d> <{ord(mapping):04x}> endbfchar endcmap".encode()
    )
    font[NameObject("/ToUnicode")] = cmap
    stream = page["/Contents"]
    stream.set_data(b"BT /FR 12 Tf 50 700 Td " + source + b" Tj ET")
    original = stream.get_data()
    output = LayoutPdfBackend().extract_page(page, 1)
    assert expected in " ".join(x.text for x in output.lines)
    assert any(
        w["code"] == "NATIVE_UNIT_MAPPING_CORRECTED" and mapping in w["before"]
        for w in output.warnings
    )
    assert stream.get_data() == original


def test_left_aligned_headers_and_mixed_cells_use_painted_gaps():
    lines = [line("Table 4. Cycle results.", 30, 740, 450)]
    lines.append(
        glyph_line([("Input mass", 115), ("Output mass", 215), ("Yield", 320)], 725)
    )
    for row, y in enumerate([710, 699, 688]):
        if row == 1:
            lines.append(glyph_line([("Run 7", 55), ("8.3", 115)], y))
            lines.extend(
                glyph_line([(text, center)], y)
                for text, center in [("10.7", 215), ("128.9", 320)]
            )
        else:
            lines.extend(
                glyph_line([(text, center)], y)
                for text, center in [
                    (f"Run {row}", 55),
                    ("8.3", 115),
                    ("10.7", 215),
                    ("128.9", 320),
                ]
            )
    prepared = _prepare_table_lines(tuple(lines), 600)
    texts = [x.text for x in prepared]
    assert "Run 7" in texts and "Input mass" in texts and "Output mass" in texts
    assert all("Run 7 8.3" not in t for t in texts)
    for item in prepared:
        validate_page_layout(PageLayout(1, 600, 800, lines=(item,)))


def test_alternative_conflicts_share_a_location_but_keep_both_readings():
    def block(name, text, box, page=1):
        return dict(
            id=name,
            text=text,
            evidence={"bbox": box},
            page=page,
            content_region="ocr-alternative",
            uncertain=True,
        )

    blocks = [
        block("a", "5 μm", [0.1, 0.5, 0.3, 0.52]),
        block("b", "5 mm", [0.101, 0.501, 0.299, 0.521]),
        block("c", "5 μm", [0.1, 0.53, 0.3, 0.55]),
        block("d", "5 μm", [0.1, 0.5, 0.3, 0.52], 2),
    ]
    groups = review_locations(dict(blocks=blocks))
    assert [g["block_ids"] for g in groups] == [["a", "b"], ["c"], ["d"]]
    assert all(g["uncertain"] for g in groups)


def test_figure_includes_aligned_upper_panels_but_stops_at_another_caption():
    objects = tuple(
        PageObject("image", f"im{i}", 300, 200, box)
        for i, box in enumerate(
            [
                (0.1, 0.4, 0.35, 0.53),
                (0.5, 0.4, 0.75, 0.53),
                (0.1, 0.54, 0.35, 0.67),
                (0.5, 0.54, 0.75, 0.67),
                (0.1, 0.69, 0.35, 0.82),
            ]
        )
    )
    captions = [
        dict(id="cap", anchor_id="a", page=1, kind="caption", text="Figure 1. Images."),
        dict(
            id="other",
            anchor_id="b",
            page=1,
            kind="caption",
            text="Figure 2. Separate image.",
        ),
    ]
    anchors = [
        dict(id="a", bbox=[0.1, 0.36, 0.75, 0.38]),
        dict(id="b", bbox=[0.1, 0.673, 0.75, 0.683]),
    ]
    figures, _, _ = _objects(
        captions, anchors, {1: PageLayout(1, 600, 800, objects=objects)}
    )
    assert {o["name"] for o in figures[0]["source_objects"]} == {
        "im0",
        "im1",
        "im2",
        "im3",
    }
