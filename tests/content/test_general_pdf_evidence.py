"""Independent synthetic regressions for scientific PDF evidence recovery."""

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject, NumberObject
from test_display_and_tables import array, dictionary, regular_font, stream
from test_unit_mapping import MU, polygon

from aletheia_nexus.content.backends import LayoutPdfBackend
from aletheia_nexus.content.backends.font_symbols import _OutlineContours
from aletheia_nexus.content.backends.glyph_readings import geometric_reading
from aletheia_nexus.content.models import LayoutLine, PageObject
from aletheia_nexus.content.parser import (
    ParserConfig,
    _associate_figure_labels,
    _order_lines,
    _prepare_table_lines,
)


def test_nested_images_resolve_resources_transforms_clips_and_repeated_placements():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    picture = stream(
        writer,
        bytes([255, 0, 0]) * 4,
        Type=NameObject("/XObject"),
        Subtype=NameObject("/Image"),
        Width=NumberObject(2),
        Height=NumberObject(2),
        ColorSpace=NameObject("/DeviceRGB"),
        BitsPerComponent=NumberObject(8),
    )
    inner = stream(
        writer,
        b"q 80 0 0 40 0 0 cm /I Do Q",
        Type=NameObject("/XObject"),
        Subtype=NameObject("/Form"),
        BBox=array(0, 0, 60, 40),
        Matrix=array(1, 0, 0, 1, 10, 20),
        Resources=dictionary(XObject=dictionary(I=picture)),
    )
    outer = stream(
        writer,
        b"q 2 0 0 2 0 0 cm /Inner Do Q",
        Type=NameObject("/XObject"),
        Subtype=NameObject("/Form"),
        BBox=array(0, 0, 300, 300),
        Resources=dictionary(XObject=dictionary(Inner=inner)),
    )
    page[NameObject("/Resources")] = dictionary(XObject=dictionary(F=outer))
    page[NameObject("/Contents")] = stream(
        writer, b"q 1 0 0 1 40 100 cm /F Do Q q 1 0 0 1 300 400 cm /F Do Q"
    )
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert len(layout.objects) == 2
    assert [x.name for x in layout.objects] == ["F/Inner/I", "F/Inner/I#2"]
    assert layout.objects[0].bbox == (0.1, 0.175, 0.3, 0.275)
    assert layout.objects[1].bbox == (0.533333, 0.55, 0.733333, 0.65)


def test_trailing_pdf_spaces_do_not_expand_numeric_cell_into_other_column():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /F 10 Tf 210 700 Td (0                                                   ) Tj ET",
    )
    line = LayoutPdfBackend().extract_page(page, 1).lines[0]
    assert line.text == "0"
    assert 210 < line.x1 < 220
    assert line.x0 == 210


def test_polygonized_mu_and_straight_letters_are_not_confused():
    pen = _OutlineContours()
    for op, points in MU:
        getattr(pen, op)(*points)
    flattened = polygon(pen.contours[0])
    assert geometric_reading(flattened, 1000) == "μ"
    h = polygon(
        [
            (0, 0),
            (0, 600),
            (80, 600),
            (80, 350),
            (420, 350),
            (420, 600),
            (500, 600),
            (500, 0),
            (420, 0),
            (420, 270),
            (80, 270),
            (80, 0),
        ]
    )
    assert geometric_reading(h, 1000) is None
    greater = polygon(
        [(80, 70), (560, 300), (80, 530), (80, 450), (400, 300), (80, 150)]
    )
    less = [(op, tuple((640 - x, y) for x, y in pts)) for op, pts in greater]
    bar = polygon([(80, -40), (560, -40), (560, 0), (80, 0)])
    assert geometric_reading(greater, 1000) == ">"
    assert geometric_reading(less, 1000) == "<"
    assert geometric_reading(greater + bar, 1000) == "≥"
    assert geometric_reading(less + bar, 1000) == "≤"


def test_rounded_equal_sign_is_read_from_ink_not_misleading_character_map():
    def pill(y):
        return [
            ("moveTo", ((90, y),)),
            ("lineTo", ((610, y),)),
            ("curveTo", ((640, y), (640, y + 48), (610, y + 48))),
            ("lineTo", ((90, y + 48),)),
            ("curveTo", ((60, y + 48), (60, y), (90, y))),
            ("closePath", ()),
        ]

    assert geometric_reading(pill(90) + pill(290), 1000) == "="
    # A separated pair of short strokes or a fraction slash is not an equals.
    shifted = [(op, tuple((x + 300, y) for x, y in pts)) for op, pts in pill(290)]
    assert geometric_reading(pill(90) + shifted, 1000) != "="
    slash = polygon([(100, 0), (150, 0), (560, 700), (510, 700)])
    assert geometric_reading(slash + pill(290), 1000) != "="


def test_margin_tick_inside_a_figure_is_not_a_page_number():
    from dataclasses import replace

    from aletheia_nexus.content.models import PageLayout
    from aletheia_nexus.content.parser import _is_page_furniture

    layout = PageLayout(page=2, width=600, height=800, lines=())
    tick = LayoutLine("80", 400, 755, 420, 765, 10, content_region="figure")
    assert not _is_page_furniture(tick, layout, {"80"})
    assert _is_page_furniture(replace(tick, content_region="body"), layout, {"80"})


def test_spanning_figure_labels_do_not_interleave_with_prose_columns():
    from aletheia_nexus.content.models import PageLayout
    from aletheia_nexus.content.parser import _order_layout_lines

    figure = PageObject(object_type="image", name="scheme", bbox=(0.05, 0.6, 0.95, 0.9))

    def line(text, x, y, region="body"):
        return LayoutLine(text, x, y, x + 100, y + 10, 10, content_region=region)

    lines = (
        line("upper left", 40, 690, "figure"),
        line("upper right", 340, 690, "figure"),
        line("lower left", 40, 510, "figure"),
        line("lower right", 340, 510, "figure"),
        line("left prose begins here", 40, 440),
        line("left prose continues", 40, 420),
        line("right prose begins here", 340, 440),
        line("right prose continues", 340, 420),
    )
    layout = PageLayout(page=1, width=600, height=800, lines=lines, objects=(figure,))
    result = _order_layout_lines(lines, layout, ParserConfig())
    assert [r.text for r in result[:4]] == [
        "upper left",
        "upper right",
        "lower left",
        "lower right",
    ]


def test_small_transposed_table_retains_deviations_and_rightmost_material():
    def line(text, x, y, w=45):
        return LayoutLine(text, x, y, x + w, y + 8, 8)

    lines = [line("Table 2", 30, 720), line("Particle size summary", 30, 710, 210)]
    lines += [
        line(t, x, 690, w)
        for t, x, w in [
            ("Property", 30, 50),
            ("Untreated", 160, 55),
            ("Basic treatment", 260, 85),
            ("Acidic treatment", 420, 95),
        ]
    ]
    for label, y, vals in [
        ("Diameter (nm)", 670, ["2.4", "2.1", "2.2"]),
        ("Deviation", 650, ["±0.4", "±0.2", "±0.3"]),
    ]:
        lines.append(line(label, 30, y, 90))
        lines += [line(t, x, y) for t, x in zip(vals, [160, 260, 420])]
    lines.append(line("An unrelated paragraph follows the table.", 30, 620, 240))
    prepared = _prepare_table_lines(tuple(lines), 600)
    cells = [x.text for x in prepared if x.content_region == "table-cell"]
    assert all(t in cells for t in ["Acidic treatment", "2.2", "±0.3", "Deviation"])
    assert not any("unrelated" in t for t in cells)


def test_multiline_caption_and_tall_rows_keep_all_columns_and_final_missing_value():
    def line(text, x, y, w=35):
        return LayoutLine(text=text, x0=x, y0=y, x1=x + w, y1=y + 8, font_size=8)

    lines = [
        line("Table 3", 40, 720),
        line("Measured conversion and selectivity", 40, 710, 510),
        line("under the stated conditions", 40, 700, 180),
    ]
    lines += [
        line(s, x, 680, w)
        for s, x, w in [
            ("Run", 40, 30),
            ("Catalyst", 120, 65),
            ("Yield (%)", 400, 55),
            ("ee (%)", 510, 40),
        ]
    ]
    for i, y in enumerate([645, 600, 555, 510], 1):
        lines += [
            line(str(i), 40, y),
            line(f"Material {i}", 120, y, 80),
            line(str(40 + i) if i < 4 else "–", 400, y),
            line(f"{20 + i} (S)", 510, y, 40),
        ]
    lines += [line("This is unrelated prose after the table.", 40, 460, 500)]
    # OCR of a reaction thumbnail sits between native data rows. It is a
    # separate image reading, not a table boundary or a new numeric column.
    from dataclasses import replace

    lines += [replace(line("HO", 300, 578), content_region="figure", uncertain=True)]
    prepared = _prepare_table_lines(tuple(lines), 600)
    caption = next(
        line for line in prepared if line.content_region == "spanning-table-caption"
    )
    assert "stated conditions" in caption.text and "Run" not in caption.text
    cells = [line for line in prepared if line.content_region == "table-cell"]
    assert len(cells) == 20
    ordered = _order_lines(prepared, 600, ParserConfig())
    assert [line.text for line in ordered if line.content_region == "table-cell"][
        -4:
    ] == [
        "4",
        "Material 4",
        "–",
        "24 (S)",
    ]
    assert any(item.text.startswith("This is unrelated") for item in ordered)
    assert (
        next(item for item in prepared if item.text == "HO").content_region == "figure"
    )


def test_vertical_native_label_is_readable_and_margin_copyright_is_omitted():
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    page[NameObject("/Resources")] = dictionary(Font=dictionary(F=regular_font()))
    page[NameObject("/Contents")] = stream(
        writer,
        b"BT /F 10 Tf 0 1 -1 0 200 300 Tm (Response rate) Tj ET "
        b"BT /F 10 Tf 0 -1 1 0 580 700 Tm (Downloaded copyright) Tj ET",
    )
    layout = LayoutPdfBackend().extract_page(page, 1)
    assert [line.text for line in layout.lines] == ["Response rate"]
    assert layout.lines[0].y0 < layout.lines[0].y1


def test_figure_value_pairing_uses_geometry_not_numeric_sorting():
    values = [
        LayoutLine(t, x, 410, x + 20, 420, 10)
        for t, x in [("27%", 100), ("83%", 200), ("12%", 300)]
    ]
    labels = [
        LayoutLine(t, x, 280, x + 20, 290, 10)
        for t, x in [("alpha", 100), ("beta", 200), ("gamma", 300)]
    ]
    objects = [PageObject("image", "chart", bbox=(0.1, 0.375, 0.9, 0.9))]

    def pair(items):
        return [
            line.text
            for line in _associate_figure_labels(tuple(items), objects, 400, 800)
            if line.extraction_method == "positioned-figure-label-value"
        ]

    assert pair(values + labels) == ["alpha: 27%", "beta: 83%", "gamma: 12%"]
    assert pair(values + labels[:2]) == []
    assert (
        pair(values + labels + [LayoutLine("ambiguous", 200, 280, 220, 290, 10)]) == []
    )


def test_image_ocr_configuration_is_explicit_and_part_of_identity():
    import pytest

    from aletheia_nexus.content.backends import TesseractOcrBackend, TesseractOcrConfig

    with pytest.raises(ValueError, match="image_ocr"):
        TesseractOcrConfig(image_ocr="guessed-engine")
    assert (
        TesseractOcrBackend(TesseractOcrConfig()).execution_identity["configuration"][
            "image_ocr"
        ]
        == "tesseract"
    )


def test_panel_scales_use_grid_locations_without_inventing_missing_letters():
    import pytest

    Image = pytest.importorskip("PIL.Image")
    from aletheia_nexus.content.backends.image_panels import associate_scales

    image = Image.new("L", (620, 420), 90)
    image.paste(255, (305, 0, 315, 420))
    image.paste(255, (0, 205, 620, 215))

    def record(text, x, y):
        return dict(text=text, score=0.97, box=(x, y, x + 40, y + 15))

    readings = [
        record("75 nm", 240, 170),
        record("4 μm", 550, 170),
        record("2 mm", 240, 380),
        record("900 nm", 550, 380),
    ]
    result = associate_scales(readings, image)
    paired = [r["text"] for r in result if r.get("method") == "positioned-panel-length"]
    assert set(paired) == {
        "Panel (row 1, column 1): length label 75 nm; role unverified",
        "Panel (row 1, column 2): length label 4 μm; role unverified",
        "Panel (row 2, column 1): length label 2 mm; role unverified",
        "Panel (row 2, column 2): length label 900 nm; role unverified",
    }
    assert all(r.get("alternative") for r in readings)
    conflict = [record("8 nm", 240, 170), record("9 nm", 240, 190)]
    assert not any(
        r.get("method") == "positioned-panel-length"
        for r in associate_scales(conflict, image)
    )


def test_image_axes_keep_printed_order_and_reject_ambiguous_titles():
    from aletheia_nexus.content.backends.image_axes import associate_axes

    def r(t, b):
        return dict(text=t, score=0.99, box=b)

    records = [
        r("Response intensity", (20, 60, 30, 150)),
        r("Applied charge", (90, 220, 220, 230)),
    ]
    records += [
        r(t, (35, y, 45, y + 10)) for t, y in [("9-", 30), ("4", 100), ("1", 180)]
    ]
    records += [
        r(t, (x, 200, x + 10, 210)) for t, x in [("6", 70), ("3", 140), ("-2", 210)]
    ]
    out = associate_axes(records)
    pairs = [r["text"] for r in out if r.get("method") == "positioned-axis-label-ticks"]
    assert pairs == [
        "Y axis: Response intensity; printed ticks: 9, 4, 1",
        "X axis: Applied charge; printed ticks: 6, 3, -2",
    ]
    for item in records:
        item.pop("alternative", None)
    records.append(r("Competing title", (90, 222, 220, 232)))
    assert not any(
        r.get("method") == "positioned-axis-label-ticks"
        for r in associate_axes(records)
    )


def test_backend_alternative_never_hides_its_primary_derived_reading():
    from dataclasses import replace

    from aletheia_nexus.content.backends import AdaptiveOcrBackend
    from aletheia_nexus.content.models import PageLayout

    native = PageLayout(page=1, width=600, height=800, lines=())
    raw = LayoutLine(
        "8 um", 100, 200, 150, 210, 10, content_region="ocr-alternative", uncertain=True
    )
    primary = replace(
        raw,
        text="Panel (z): length label 8 μm; role unverified",
        content_region="figure",
        extraction_method="positioned-panel-length",
    )
    lines, _ = AdaptiveOcrBackend()._merge(
        native, [replace(native, lines=(raw, primary))]
    )
    assert [x.text for x in lines if not x.content_region.endswith("alternative")] == [
        primary.text
    ]
    assert any(
        x.text == raw.text and x.content_region == "ocr-alternative" for x in lines
    )


def test_printed_bar_values_follow_legend_colours_not_value_order():
    from copy import deepcopy

    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")

    from aletheia_nexus.content.backends.image_bars import associate_bars

    image = Image.new("RGB", (500, 400), "white")
    draw = ImageDraw.Draw(image)

    def r(text, box):
        return dict(text=text, box=box, score=0.99)

    records = [r("Alpha", (340, 20, 390, 40)), r("Beta", (340, 48, 380, 68))]
    draw.rectangle((300, 20, 337, 40), fill=(0, 140, 90))
    draw.rectangle((300, 48, 337, 68), fill=(180, 40, 150))
    expected = []
    for i, cx in enumerate([90, 190, 290]):
        records.append(r(f"Group{i}", (cx - 20, 350, cx + 20, 370)))
        # Values and left/right series ordering differ in each category.
        pairs = [("8", 100, (0, 140, 90), "Alpha"), ("91", 200, (180, 40, 150), "Beta")]
        if i == 1:
            pairs.reverse()
        for dx, (value, y, colour, _) in zip([-15, 15], pairs):
            x = cx + dx
            records.append(r(value, (x - 8, y - 20, x + 8, y)))
            draw.rectangle((x - 10, y + 1, x + 10, 340), fill=colour)
        expected.append(
            f"Group{i}: " + "; ".join(f"{label} {v}" for v, _, _, label in pairs)
        )
    result = associate_bars(deepcopy(records), image)
    assert [
        r["text"] for r in result if r.get("method") == "printed-bar-label-association"
    ] == expected
    # A missing printed value must not be reconstructed from bar height.
    missing = [r for r in records if r["text"] != "91"]
    assert not any(
        r.get("method") == "printed-bar-label-association"
        for r in associate_bars(missing, image)
    )
    grey = image.convert("L").convert("RGB")
    assert not any(
        r.get("method") == "printed-bar-label-association"
        for r in associate_bars(deepcopy(records), grey)
    )


def test_touching_micrograph_panels_keep_fragmented_units_and_raw_readings():
    Image = pytest.importorskip("PIL.Image")

    from aletheia_nexus.content.backends.image_panels import (
        associate_scales,
        join_length_fragments,
    )

    image = Image.new("RGB", (600, 400), "gray")

    def r(text, x, y, w=30):
        return dict(text=text, score=0.99, box=(x, y, x + w, y + 20))

    records = [
        r("a", 260, 10),
        r("b", 560, 10),
        r("c", 260, 210),
        r("d", 560, 210),
        r("7", 100, 160, 10),
        r("nm", 113, 160),
        r("6 um", 410, 160),
        r("12 nm", 100, 360),
        r("8 um", 410, 360),
    ]
    result = associate_scales(join_length_fragments(records), image)
    assert {
        r["text"] for r in result if r.get("method") == "positioned-panel-length"
    } == {
        "Panel (a): length label 7 nm; role unverified",
        "Panel (b): length label 6 um; role unverified",
        "Panel (c): length label 12 nm; role unverified",
        "Panel (d): length label 8 um; role unverified",
    }
    assert records[4]["alternative"] and records[5]["alternative"]


def test_existing_ocr_label_needs_unique_native_support_for_i_l_choice():
    from dataclasses import replace

    from aletheia_nexus.content.backends.adaptive import _native_supported_label

    a = LayoutLine("Signal vs CaCI", 0, 0, 30, 10, 10)
    b = replace(a, text="Signal vs CaCl")
    assert _native_supported_label(a, b, {"CaCl"}) is b
    assert _native_supported_label(a, b, {"CaCl", "CaCI"}) is None
    assert _native_supported_label(a, b, set()) is None
    assert (
        _native_supported_label(
            replace(a, text=a.text + " 9"), replace(b, text=b.text + " 8"), {"CaCl"}
        )
        is None
    )
    assert (
        _native_supported_label(a, replace(b, text="Signal vs NaCl"), {"NaCl"}) is None
    )


def test_open_chart_markers_do_not_become_degree_signs():
    triangle = polygon([(0, 0), (450, 780), (900, 0)]) + polygon(
        [(85, 48), (815, 48), (450, 682)]
    )
    square = polygon([(0, 0), (0, 700), (700, 700), (700, 0)]) + polygon(
        [(50, 50), (650, 50), (650, 650), (50, 650)]
    )
    assert geometric_reading(triangle, 1000) == "△"
    assert geometric_reading(square, 1000) == "□"
    small = [
        (op, tuple(tuple(v * 0.4 for v in point) for point in points))
        for op, points in square
    ]
    assert geometric_reading(small, 1000) is None
