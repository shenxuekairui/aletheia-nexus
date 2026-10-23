"""Physical table boundaries and text order, independent of paper samples."""

from pypdf import PdfWriter
from pypdf.generic import NameObject, NumberObject
from test_display_and_tables import dictionary, regular_font, stream

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.models import LayoutLine
from aletheia_nexus.content.parser import _caption_match, _sort_spatial_lines
from aletheia_nexus.content.service import parse_document


def test_painted_grid_preserves_multiline_cells_and_merged_header(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    drawing = [
        b"50 600 430 100 re S",
        b"50 680 m 480 680 l S",
        b"50 640 m 480 640 l S",
        b"180 600 m 180 700 l S",
        b"300 600 m 300 680 l S",
    ]
    for text, x, y in [
        ("Table. Measurements", 50, 720),
        ("Material", 60, 686),
        ("Results", 200, 686),
        ("A", 60, 665),
        ("slow", 190, 665),
        ("17", 310, 665),
        ("heated", 190, 650),
        ("B", 60, 625),
        ("fast", 190, 625),
        ("23", 310, 625),
    ]:
        drawing.append(f"BT /F 10 Tf {x} {y} Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream(writer, b"\n".join(drawing))
    pdf = tmp_path / "sample.pdf"
    writer.write(pdf)
    registered = register_local_pdf(
        pdf, output_dir=tmp_path / "library", title="Grid fixture"
    )
    doc = parse_document(registered, backend=LayoutPdfBackend()).document
    assert len(doc["tables"]) == 1
    table = doc["tables"][0]
    cells = {c["text"]: c for c in table["cells"]}
    assert cells["Results"]["column_span"] == 2
    assert (cells["slow"]["row"], cells["slow"]["column"]) == (2, 2)
    assert (cells["heated"]["row"], cells["heated"]["column"]) == (2, 2)
    assert (cells["23"]["row"], cells["23"]["column"]) == (3, 3)
    assert all(c["span_evidence"] == "painted-pdf-grid" for c in table["cells"])


def test_painted_rules_ignore_unpainted_paths_and_clip_transforms():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Contents")] = stream(
        writer,
        b"50 500 300 100 re n "
        b"q 1 0 0 1 40 100 cm 0 0 100 100 re W n "
        b"-20 40 m 200 40 l S Q "
        b"40 200 m 90 200 l 140 200 l S",
    )
    rules = LayoutPdfBackend().extract_page(page, 1).objects
    horizontal = [r for r in rules if r.object_type == "horizontal-rule"]
    assert len(horizontal) == 2
    assert all(0.06 < r.bbox[0] < 0.07 and 0.23 < r.bbox[2] < 0.24 for r in horizontal)
    assert not any(r.object_type == "vertical-rule" for r in rules)


def test_caption_parenthetical_cross_reference_and_figure_row_jitter():
    assert _caption_match("Table 3. Reaction results (structures see Figure 8)")
    assert _caption_match("Table. Experimental results")
    assert not _caption_match("The results in Table 3 show a decrease.")
    lines = [
        LayoutLine(t, x, y, x + 30, y + 8, 8, content_region="figure")
        for t, x, y in [
            ("11%", 20, 100),
            ("27%", 70, 102),
            ("32%", 120, 99),
            ("second row", 20, 70),
        ]
    ]
    assert [line.text for line in _sort_spatial_lines(lines)] == [
        "11%",
        "27%",
        "32%",
        "second row",
    ]


def test_table_caption_and_grid_separated_by_a_reaction_image(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    img = stream(
        writer,
        b"\x80",
        Type=NameObject("/XObject"),
        Subtype=NameObject("/Image"),
        Width=NumberObject(1),
        Height=NumberObject(1),
        ColorSpace=NameObject("/DeviceGray"),
        BitsPerComponent=NumberObject(8),
    )
    page[NameObject("/Resources")] = dictionary(
        Font=dictionary(F=regular_font()), XObject=dictionary(I=img)
    )
    drawing = [b"q 240 0 0 140 40 540 cm /I Do Q"]
    for text, x, y in [
        ("Table 7", 40, 710),
        ("Comparison of reaction", 79, 710),
        ("conditions and isolated products", 40, 698),
        ("Unrelated prose in the other column", 330, 698),
        ("Entry", 40, 520),
        ("Additive", 100, 520),
        ("Yield (%)", 220, 520),
        ("1", 40, 500),
        ("Salt A", 100, 500),
        ("37", 220, 500),
        ("2", 40, 480),
        ("Salt B", 100, 480),
        ("58", 220, 480),
        ("Reaction temperature was held constant.", 40, 450),
    ]:
        escaped = text.replace("(", r"\(").replace(")", r"\)")
        drawing.append(f"BT /F 10 Tf {x} {y} Td ({escaped}) Tj ET".encode())
    page[NameObject("/Contents")] = stream(writer, b"\n".join(drawing))
    pdf = tmp_path / "illustrated-table.pdf"
    writer.write(pdf)
    registered = register_local_pdf(
        pdf, output_dir=tmp_path / "library", title="Illustrated table"
    )
    doc = parse_document(registered, backend=LayoutPdfBackend()).document
    table = next(t for t in doc["tables"] if t["label"] == "7")
    assert "Comparison of reaction" in table["caption"]
    cells = {c["text"]: c for c in table["cells"]}
    assert cells["Salt A"]["row"] == cells["37"]["row"]
    assert cells["Salt B"]["row"] == cells["58"]["row"]
    assert cells["37"]["column"] == cells["58"]["column"] == 3
    assert not any("Unrelated" in c["text"] for c in table["cells"])


def test_two_ruled_tables_in_adjacent_columns_remain_separate(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    drawing = []
    for x, label, name, numbers in [
        (40, "1", "Left", (17, 26)),
        (330, "2", "Right", (43, 61)),
    ]:
        for y in [680, 660, 600]:
            drawing.append(f"{x} {y} m {x + 230} {y} l S".encode())
        rows = [
            (f"Table {label}. {name} measurements", x, 700),
            ("Entry", x, 667),
            ("Condition", x + 70, 667),
            ("Yield", x + 170, 667),
        ]
        for n, value in enumerate(numbers, 1):
            y = 660 - n * 20
            rows += [
                (str(n), x, y),
                (f"{name} {n}", x + 70, y),
                (str(value), x + 170, y),
            ]
        for text, xpos, y in rows:
            drawing.append(f"BT /F 10 Tf {xpos} {y} Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream(writer, b"\n".join(drawing))
    pdf = tmp_path / "adjacent.pdf"
    writer.write(pdf)
    registered = register_local_pdf(
        pdf, output_dir=tmp_path / "library", title="Adjacent table fixture"
    )
    doc = parse_document(registered, backend=LayoutPdfBackend()).document
    for label, own, other in [("1", "Left", "Right"), ("2", "Right", "Left")]:
        table = next(t for t in doc["tables"] if t["label"] == label)
        assert table["column_count"] == 3
        assert any(own in c["text"] for c in table["cells"])
        assert not any(other in c["text"] for c in table["cells"])
