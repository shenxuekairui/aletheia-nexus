"""Partial glyph OCR must not become a new table condition."""

from dataclasses import replace

import pytest
from test_table_generalization import cells_from
from test_table_relations import glyph_line, line

from aletheia_nexus.content.backends import AdaptiveOcrBackend
from aletheia_nexus.content.models import LayoutLine, PageLayout


@pytest.mark.parametrize("scale", [0.7, 1, 1.6])
@pytest.mark.parametrize(
    "labels,mark,dy", [(("82.4", "97.6"), ":", -5), (("Tin", "Nickel"), ".", 5)]
)
def test_partial_glyph_punctuation_keeps_native_shared_conditions(
    scale, labels, mark, dy
):
    native = [line("Table 2. Shared conditions.", 30, 750, 500)]
    native += [
        line(t, x, 735)
        for t, x in zip(["Group", "Time", "A", "B"], [50, 150, 300, 400])
    ]
    for group, label in enumerate(labels):
        native.append(glyph_line([(label, 60)], 710 - group * 40))
        for i in range(4):
            y = 725 - (group * 4 + i) * 10
            native += [
                line(str(v), x, y)
                for v, x in zip([i + 1, 20 + i, 60 + i], [150, 300, 400])
            ]
    label = next(item for item in native if item.text == labels[0])
    glyph = label.glyph_spans[1]
    ocr = LayoutLine(
        mark,
        glyph[2] + 0.2,
        label.y0 + dy,
        glyph[3] - 0.2,
        label.y1 + dy,
        6,
        extraction_method="page-ocr",
        content_region="body",
    )

    def scaled(item):
        return replace(
            item,
            x0=item.x0 * scale,
            y0=item.y0 * scale,
            x1=item.x1 * scale,
            y1=item.y1 * scale,
            font_size=item.font_size * scale,
            glyph_spans=tuple(
                (a, b, x * scale, z * scale) for a, b, x, z in item.glyph_spans
            ),
        )

    page = PageLayout(
        page=1, width=600 * scale, height=800 * scale, lines=tuple(map(scaled, native))
    )
    merged, warnings = AdaptiveOcrBackend()._merge(
        page, [replace(page, lines=(scaled(ocr),))]
    )
    _, tables = cells_from(merged, page.width, page.height)
    shared = [c for c in tables[0][0] if c["text"] in labels]
    assert len(shared) == 2
    assert all(c.get("row_span") == 4 for c in shared)
    raw = next(item for item in merged if item.text == mark)
    assert raw.content_region == "ocr-alternative"
    assert (raw.x0, raw.y0, raw.x1, raw.y1) == (
        ocr.x0 * scale,
        ocr.y0 * scale,
        ocr.x1 * scale,
        ocr.y1 * scale,
    )
    assert any(w["code"] == "OCR_ENGINE_DISAGREEMENT" for w in warnings)


@pytest.mark.parametrize(
    "case",
    [
        "separate-row",
        "between-glyphs",
        "outside-word",
        "minus",
        "plus-minus",
        "footnote",
        "digit",
        "damaged-native",
    ],
)
def test_fragment_rule_cannot_consume_distinct_symbols_or_damaged_native(case):
    native = glyph_line([("AB", 100)], 300)
    ocr = LayoutLine(
        ".", native.x0 + 0.2, 305, native.x0 + 1, 311, 6, extraction_method="page-ocr"
    )
    if case == "separate-row":
        ocr = replace(ocr, y0=307, y1=313)
    elif case == "between-glyphs":
        native = replace(
            native, glyph_spans=((0, 1, 90, 94), (1, 2, 102, 106)), x0=90, x1=106
        )
        ocr = replace(ocr, x0=98, x1=99)
    elif case == "outside-word":
        ocr = replace(ocr, x0=native.x1 + 1, x1=native.x1 + 2)
    elif case == "damaged-native":
        native = replace(native, uncertain=True)
    else:
        ocr = replace(
            ocr,
            text={"minus": "−", "plus-minus": "±", "footnote": "*", "digit": "7"}[case],
        )
    page = PageLayout(page=1, width=600, height=800, lines=(native,))
    merged, _ = AdaptiveOcrBackend()._merge(page, [replace(page, lines=(ocr,))])
    assert any(
        item.text == ocr.text and not item.content_region.endswith("alternative")
        for item in merged
    )
