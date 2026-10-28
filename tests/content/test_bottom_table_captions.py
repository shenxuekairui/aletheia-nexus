"""Lower captions must not turn the following discussion into table cells."""

from dataclasses import replace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.evidence import build_evidence_pack
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject
from aletheia_nexus.content.ruled_tables import table_bounds
from aletheia_nexus.content.service import parse_document


def grid_page(scale=1, *, closed=True):
    lines = [
        ("Table 4. Comparison of measured responses.", 60, 570, 310),
        ("Treatment", 65, 690, 65),
        ("Response", 230, 690, 65),
        ("Unit", 400, 690, 35),
        ("Sample P", 65, 650, 60),
        ("47", 230, 650, 15),
        ("mV", 400, 650, 20),
        ("Sample Q", 65, 610, 60),
        ("83", 230, 610, 15),
        ("mV", 400, 610, 20),
        (
            "The discussion following the table concerns a separate experiment.",
            60,
            530,
            470,
        ),
        (
            "Its conditions must not be assigned to the preceding measured rows.",
            60,
            515,
            470,
        ),
    ]
    objects = [
        PageObject("horizontal-rule", str(y), bbox=(0.1, y / 800, 0.9, (y + 0.2) / 800))
        for y in (590, 630, 670, 710)
    ]
    if closed:
        objects.extend(
            PageObject(
                "vertical-rule",
                str(x),
                bbox=(x / 600, 590 / 800, (x + 0.2) / 600, 710 / 800),
            )
            for x in (60, 220, 380, 540)
        )
    return PageLayout(
        page=1,
        width=600 * scale,
        height=800 * scale,
        lines=tuple(
            LayoutLine(
                t, x * scale, y * scale, (x + w) * scale, (y + 8) * scale, 8 * scale
            )
            for t, x, y, w in lines
        ),
        objects=tuple(objects),
    )


def parse_layout(tmp_path, layout):
    class Backend:
        name = "bottom-caption-fixture"
        version = "1"

        def extract_page(self, page, page_number):
            return (
                replace(layout, page=page_number)
                if page_number == 1
                else PageLayout(
                    page=page_number, width=layout.width, height=layout.height
                )
            )

    writer = PdfWriter()
    writer.add_blank_page(layout.width, layout.height)
    source = tmp_path / "source.pdf"
    writer.write(source)
    pdf = register_local_pdf(
        source, output_dir=tmp_path / "library", title="Synthetic table layout"
    )
    return parse_document(pdf, backend=Backend()).document


@pytest.mark.parametrize("scale", [0.65, 1, 1.7])
def test_closed_grid_above_caption_preserves_rows_and_excludes_discussion(
    tmp_path, scale
):
    doc = parse_layout(tmp_path, grid_page(scale))
    assert doc["tables"]
    for table in doc["tables"]:
        assert (table["row_count"], table["column_count"]) == (3, 3)
        cells = {c["text"]: c for c in table["cells"]}
        assert cells["Sample P"]["row"] == cells["47"]["row"] == 2
        assert cells["Sample Q"]["row"] == cells["83"]["row"] == 3
        assert cells["47"]["column"] == cells["83"]["column"] == 2
        assert not any("discussion" in c["text"] for c in table["cells"])
    assert any("discussion" in b["text"] for b in doc["blocks"])
    pack = build_evidence_pack(tmp_path)
    assert pack["included"][0]["tables"]
    assert all(
        t["complete_context"] for item in pack["included"] for t in item["tables"]
    )


def test_caption_followed_by_overlapping_prose_is_unresolved_and_retained(tmp_path):
    page = grid_page(closed=False)
    # Long native paragraphs often overlap vertically, yielding apparent rows
    # but only one horizontal column. This is not an observed grid.
    prose = [
        LayoutLine(
            "The first explanatory paragraph contains observations from another experiment.",
            60,
            530,
            520,
            550,
            8,
        ),
        LayoutLine(
            "An overlapping continuation describes a separate result and its limitations.",
            65,
            532,
            525,
            548,
            8,
        ),
        LayoutLine(
            "The next explanatory paragraph does not contain a table row or a cell value.",
            60,
            490,
            520,
            510,
            8,
        ),
        LayoutLine(
            "Another overlapping continuation preserves the ordinary reading order.",
            65,
            492,
            525,
            508,
            8,
        ),
    ]
    page = replace(page, lines=(page.lines[0], *prose), objects=())
    doc = parse_layout(tmp_path, page)
    assert doc["tables"] and all(not t["cells"] for t in doc["tables"])
    assert any(w["code"] == "TABLE_STRUCTURE_UNRESOLVED" for w in doc["warnings"])
    assert doc["quality"]["manual_review_required"]
    assert any("explanatory paragraph" in b["text"] for b in doc["blocks"])
    pack = build_evidence_pack(tmp_path)
    assert pack["included"][0]["tables"]
    assert all(
        not t["complete_context"] for item in pack["included"] for t in item["tables"]
    )


@pytest.mark.parametrize("problem", ["no_sides", "distant", "broken_side"])
def test_lower_caption_rules_need_a_nearby_closed_grid(problem):
    page = grid_page()
    caption = page.lines[0]
    if problem == "no_sides":
        page = replace(page, objects=page.objects[:4])
    elif problem == "distant":
        caption = replace(caption, y0=400, y1=408)
    else:
        page = replace(
            page,
            objects=tuple(
                replace(o, bbox=(o.bbox[0], 0.8, o.bbox[2], o.bbox[3]))
                if o.object_type == "vertical-rule" and o.name == "60"
                else o
                for o in page.objects
            ),
        )
    assert table_bounds(caption, page.objects, page.width, page.height) is None
