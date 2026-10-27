"""Self-authored painted borders; source fragments are not numerical guesses."""

from collections import Counter

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.closed_table_cells import prepare_closed_table_cells
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.service import parse_document


def segmented_page(
    scale=1, *, closed=True, caption="Table 1. Wrapped instrument readings"
):
    writer = PdfWriter()
    page = writer.add_blank_page(600 * scale, 800 * scale)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    commands = [f"{scale} 0 0 {scale} 0 0 cm".encode()]
    stroke = 1.4
    xs, ys = [50, 350, 382, 414], [540, 580, 625, 660, 700]
    for y in ys:
        for left, right in zip(xs, xs[1:]):
            if y == 660 and left == 50:
                continue  # First header spans both physical header rows.
            commands.append(
                f"{left + stroke} {y} {right - left - stroke} {stroke} re f".encode()
            )
    for x in xs:
        if x == 414 and not closed:
            continue
        for low, high in zip(ys, ys[1:]):
            if x == 382 and low == 660:
                continue  # Shared measurement header.
            commands.append(
                f"{x} {low + stroke} {stroke} {high - low - stroke - 0.1} re f".encode()
            )
    for text, x, y, size in [
        (caption, 50, 735, 12),
        ("Object", 60, 670, 12),
        ("Readings", 355, 680, 10),
        ("X", 358, 640, 10),
        ("Y", 390, 640, 10),
        ("Alpha item", 60, 606, 12),
        ("12.", 358, 606, 12),
        ("34.", 390, 606, 12),
        ("3", 358, 589, 12),
        ("5", 390, 589, 12),
        ("Beta item", 60, 563, 12),
        ("67.", 358, 563, 12),
        ("89.", 390, 563, 12),
        ("8", 358, 546, 12),
        ("1", 390, 546, 12),
        ("Only source layout is asserted.", 50, 515, 10),
    ]:
        commands.append(f"BT /F {size} Tf {x} {y} Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream(writer, b"\n".join(commands))
    return writer, page


@pytest.mark.parametrize("scale", [0.75, 1.25])
def test_segmented_grid_keeps_wrapped_readings_in_their_physical_cells(tmp_path, scale):
    writer, page = segmented_page(scale)
    native = LayoutPdfBackend().extract_page(page, 1)
    prepared = prepare_closed_table_cells(native)
    assert prepared is not native
    assert Counter(
        c for line in native.lines for c in line.text if not c.isspace()
    ) == Counter(c for line in prepared.lines for c in line.text if not c.isspace())
    pdf = tmp_path / "segmented.pdf"
    writer.write(pdf)
    registered = register_local_pdf(
        pdf, output_dir=tmp_path / "library", title="Wrapped readings fixture"
    )
    doc = parse_document(registered).document
    assert not doc["errors"]
    table = doc["tables"][0]
    cells = {c["text"]: c for c in table["cells"]}
    assert (table["row_count"], table["column_count"]) == (4, 3)
    assert cells["Object"]["row_span"] == 2
    assert cells["Readings"]["column_span"] == 2
    for texts, position in [
        (("12.", "3"), (3, 2)),
        (("34.", "5"), (3, 3)),
        (("67.", "8"), (4, 2)),
        (("89.", "1"), (4, 3)),
    ]:
        for text in texts:
            assert (cells[text]["row"], cells[text]["column"]) == position
    assert len({(c["row"], c["column"]) for c in table["cells"]}) == 10
    assert all(c["span_evidence"] == "painted-pdf-grid" for c in table["cells"])
    assert not any("12.3" in b["text"] for b in doc["blocks"])
    assert not any("Only source" in c["text"] for c in table["cells"])


def test_open_side_is_not_completed_into_a_closed_grid():
    _, page = segmented_page(closed=False)
    native = LayoutPdfBackend().extract_page(page, 1)
    assert prepare_closed_table_cells(native) is native
