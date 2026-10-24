"""Printed grids embedded in a figure must not become prose paragraphs."""

from dataclasses import replace

from pypdf import PdfWriter
from pypdf.generic import NameObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.corpus import content_units
from aletheia_nexus.content.embedded_tables import embedded_grids
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject
from aletheia_nexus.content.service import parse_document


def layout():
    rows = [
        ("Run", 65, 685),
        ("Treatment", 130, 685),
        ("Yield", 260, 685),
        ("Selectivity", 330, 685),
        ("1", 65, 655),
        ("Salt A", 130, 655),
        ("37%", 260, 655),
        ("91%", 330, 655),
        ("2", 65, 625),
        ("Salt B", 130, 630),
        ("ligand R", 130, 620),
        ("58%", 260, 625),
        ("93%", 330, 625),
        ("3", 65, 590),
        ("Salt C", 130, 597),
        ("ligand S", 130, 587),
        ("72%", 260, 590),
        ("89%", 330, 590),
    ]
    return PageLayout(
        page=1,
        width=600,
        height=800,
        lines=tuple(
            LayoutLine(text, x, y, x + len(text) * 4, y + 8, 8) for text, x, y in rows
        ),
        objects=tuple(
            PageObject(
                "horizontal-rule",
                f"r{i}",
                bbox=(50 / 600, y / 800, 390 / 600, (y + 0.5) / 800),
            )
            for i, y in enumerate((700, 675, 570))
        ),
    )


def test_repeated_columns_keep_wrapped_conditions_with_their_rows():
    page = layout()
    (grid,) = embedded_grids(page.lines, page)
    cells = {line.text: (row, col) for line, row, col in grid["cells"]}
    assert cells["Salt B"] == cells["ligand R"] == (3, 2)
    assert cells["Salt C"] == cells["ligand S"] == (4, 2)
    assert cells["58%"] == (3, 3)
    assert cells["93%"] == (3, 4)


def test_rules_or_numbers_alone_do_not_create_a_table():
    page = layout()
    assert not embedded_grids(page.lines, replace(page, objects=page.objects[:2]))
    lines = tuple(
        replace(line, text=str(i)) if line.y0 > 675 else line
        for i, line in enumerate(page.lines)
    )
    assert not embedded_grids(lines, page)
    assert not embedded_grids(tuple(line for line in page.lines if line.y0 > 645), page)


def test_halfway_condition_does_not_get_assigned_to_a_neighbour():
    page = layout()
    lines = (*page.lines, LayoutLine("ambiguous", 130, 640, 166, 648, 8))
    assert not embedded_grids(lines, page)


def test_adjacent_prose_and_next_panel_do_not_enter_bounded_grid():
    page = layout()
    lines = (
        *page.lines,
        LayoutLine("next panel 48%", 60, 540, 140, 548, 8),
        LayoutLine("unrelated 17%", 430, 625, 500, 633, 8),
    )
    (grid,) = embedded_grids(lines, page)
    assert len(grid["cells"]) == len(page.lines)


def test_real_pdf_without_table_caption_preserves_cells_and_search_context(tmp_path):
    source = layout()
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    commands = [f"50 {y} m 390 {y} l S".encode() for y in (700, 675, 570)]
    for line in source.lines:
        commands.append(
            f"BT /F 8 Tf {line.x0} {line.y0} Td ({line.text}) Tj ET".encode()
        )
    commands.append(
        b"BT /F 8 Tf 50 540 Td (Fig. 3. Control experiments and other panels.) Tj ET"
    )
    page[NameObject("/Contents")] = stream(writer, b"\n".join(commands))
    pdf = tmp_path / "embedded.pdf"
    writer.write(pdf)
    doc = parse_document(
        register_local_pdf(
            pdf, output_dir=tmp_path / "library", title="Embedded grid fixture"
        ),
        backend=LayoutPdfBackend(),
    ).document
    (table,) = doc["tables"]
    assert table["caption"] == ""
    assert table["caption_source"] == "header-anchor-no-caption"
    assert table["evidence_status"] == "rule-and-cell-evidence-observed"
    assert table["interpretation_status"] == "not-interpreted"
    cells = {c["text"]: c for c in table["cells"]}
    assert cells["ligand R"]["row"] == cells["58%"]["row"]
    assert cells["ligand S"]["row"] == cells["72%"]["row"]
    assert all("Salt B Salt C" not in b["text"] for b in doc["blocks"])
    unit = next(u for u in content_units(doc) if u["kind"] == "table")
    row = next(r for r in unit["row_contexts"] if "58%" in r["text"])
    assert all(
        t in row["text"] for t in ("Yield", "Selectivity", "Salt B", "ligand R", "93%")
    )
    assert "Salt C" not in row["text"]
