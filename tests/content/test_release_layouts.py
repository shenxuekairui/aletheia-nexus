"""Unseen synthetic layouts for nested groups and source-image annotations."""

from dataclasses import replace

import pytest
from test_table_generalization import cells_from
from test_table_relations import line

from aletheia_nexus.content.backends.image_annotations import LENGTH_LABEL, footer_band
from aletheia_nexus.content.parser import (
    _aligned_table_fragments,
    _caption_match,
    _table_local_warnings,
)


@pytest.mark.parametrize("scale", [0.65, 1, 1.7])
@pytest.mark.parametrize("count", [3, 4, 5])
def test_nested_conditions_keep_all_measurements_without_phantom_rows(scale, count):
    def cell(t, x, y, w=18):
        return line(t, x, y, w, scale)

    lines = [cell("Table 8. Observed time series.", 30, 760, 450)]
    lines.extend(
        cell(t, x, 740)
        for t, x in zip(
            ["Material", "Current", "Cold", "Warm", "Time", "Yield", "FE"],
            [30, 100, 170, 240, 330, 420, 520],
        )
    )
    for g, material in enumerate(["Alloy X", "Alloy Y"]):
        ys = [720 - (g * count * 2 + j) * 12 for j in range(count * 2)]
        for text, x in [(material, 30), (str(217 + 41 * g), 100)]:
            lines.append(cell(text, x, sum(ys) / len(ys)))
        for sub in range(2):
            group = ys[sub * count : (sub + 1) * count]
            for text, x in [("/" if sub == 0 else "16", 170), ("23～26", 240)]:
                lines.append(cell(text, x, sum(group) / len(group)))
            for i, y in enumerate(group):
                lines.extend(
                    cell(t, x, y)
                    for t, x in [
                        (str((i + 1) * 7), 330),
                        (f"0.{g}{sub}{i + 1}", 420),
                        (str(91 - g * 4 - sub * 2 - i), 520),
                    ]
                )
    _, tables = cells_from(lines, 600 * scale, 800 * scale)
    cells, rows, columns = tables[0]
    assert columns == 7
    assert rows == 1 + 4 * count
    assert [c["row_span"] for c in cells if c["text"].startswith("Alloy")] == [
        2 * count
    ] * 2
    assert [c["row_span"] for c in cells if c["text"] == "23～26"] == [count] * 4
    assert len([c for c in cells if c["column"] == 7]) == 1 + 4 * count


def test_header_alignment_does_not_split_ordinary_word_spaces():
    # Two almost equal spaces: only the complete first phrase aligns a column.
    text = "Mass fraction Result"
    spans = []
    x = 30.0
    for offset, char in enumerate(text):
        if not char.isspace():
            spans.append((offset, offset + 1, x, x + 3))
        x += 3 if not char.isspace() else 2
    header = replace(line(text, 30, 700, x - 30), glyph_spans=tuple(spans))
    reference = [line("0.75", 43, 680, 12), line("86", 78, 680, 12)]
    result = _aligned_table_fragments(header, reference)
    assert [r.text for r in result] == ["Mass fraction", "Result"]
    assert not _caption_match("表5比较了不同条件下的结果")
    assert _caption_match("表5 不同条件下的结果比较")


def test_adjacent_table_caption_inside_midpoint_tolerance_stays_separate():
    # The right caption starts just inside the 52% tolerance for the left
    # column, but extends into the right column. Neither grid spans the page.
    lines = [
        line("Table 3. First measurements.", 30, 740, 250),
        line("Table 9. Second measurements.", 306, 740, 250),
    ]
    for offset in [0, 276]:
        for y, values in [
            (720, ["Sample", "Rate", "Yield", "FE"]),
            (700, ["X", "14", "42", "86"]),
            (680, ["Y", "17", "48", "91"]),
            (660, ["Z", "19", "53", "94"]),
        ]:
            lines.extend(
                line(t, x + offset, y, 25) for t, x in zip(values, [30, 110, 190, 250])
            )
    _, tables = cells_from(lines)
    assert len(tables) == 2
    for cells, rows, columns in tables:
        assert (rows, columns) == (4, 4)
        assert len(cells) == 16


@pytest.mark.parametrize("dark", [False, True])
def test_footer_detection_polarity_and_isolated_text(dark):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("L", (300, 200), 0 if dark else 255)
    draw = ImageDraw.Draw(image)
    # No literal scale/value raster is used to establish the band geometry.
    for x in range(80, 150, 9):
        draw.rectangle((x, 185, x + 3, 192), fill=255 if dark else 0)
    band, box = footer_band(image)
    assert box == (0, 184, 300, 194)
    assert band.getpixel((0, 0)) == 255
    assert footer_band(Image.new("L", (300, 200), 128)) is None
    assert footer_band(Image.new("L", (30, 20), 255)) is None


@pytest.mark.parametrize("text", ["2.75 nm", "11.0um", "450 μm", "3 mm", "9.5 cm"])
def test_length_labels_preserve_literal_units(text):
    assert LENGTH_LABEL.fullmatch(text)


@pytest.mark.parametrize("text", ["x500", "15kV", "5.00rm", "200", "2mL", "3mm2"])
def test_non_length_labels_are_not_guessed(text):
    assert not LENGTH_LABEL.fullmatch(text)


@pytest.mark.parametrize(
    "text,confidence,accepted,warning",
    [
        ("8.25 nm", 96, True, False),
        ("8.25 nm", 25, False, True),
        ("> 8.25 nm", 96, False, False),
        ("Dark > 8.25 nm > 17 nm", 96, False, False),
    ],
)
def test_image_ocr_preserves_complete_band_condition(
    monkeypatch, text, confidence, accepted, warning
):
    from types import SimpleNamespace

    from pypdf import PdfWriter

    from aletheia_nexus.content.backends import image_annotations, tesseract

    Image = pytest.importorskip("PIL.Image")
    image = Image.new("L", (300, 200), 255)
    page = PdfWriter().add_blank_page(600, 800)
    monkeypatch.setattr(
        image_annotations,
        "upright_images",
        lambda *a: [("Panel", image, (40, 100, 340, 300))],
    )
    monkeypatch.setattr(
        image_annotations,
        "footer_band",
        lambda *a: (image.crop((0, 180, 300, 190)), (0, 180, 300, 190)),
    )
    payload = "level\ttext\tconf\tleft\ttop\twidth\theight\n" + "\n".join(
        f"5\t{word}\t{confidence}\t{20 + i * 80}\t24\t60\t20"
        for i, word in enumerate(text.split())
    )
    monkeypatch.setattr(
        tesseract, "_run", lambda *a, **kw: SimpleNamespace(stdout=payload)
    )
    backend = object.__new__(tesseract.TesseractOcrBackend)
    backend.config = tesseract.TesseractOcrConfig()
    backend.evidence_engine_id = "test-ocr"
    result = backend.extract_image_annotations(page, 1)
    assert [item.text for item in result.lines] == ([text] if accepted else [])
    assert bool(result.warnings) is warning


def test_column_collision_and_omitted_row_have_local_anchors():
    cells, blocks, anchors = [], [], {}
    for i, (text, row, col, box) in enumerate(
        [
            ("Header A", 1, 1, [0.1, 0.8, 0.18, 0.81]),
            ("Header B", 1, 1, [0.3, 0.8, 0.38, 0.81]),
            ("4", 2, 1, [0.1, 0.78, 0.12, 0.79]),
            ("25", 2, 2, [0.3, 0.78, 0.32, 0.79]),
            ("86", 2, 3, [0.5, 0.78, 0.52, 0.79]),
            ("8", 3, 1, [0.1, 0.76, 0.12, 0.77]),
            ("29", 3, 2, [0.3, 0.76, 0.32, 0.77]),
            ("81", 3, 3, [0.5, 0.76, 0.52, 0.77]),
        ]
    ):
        key = str(i)
        blocks.append(
            dict(id=key, anchor_id=key, page=1, text=text, content_region="body")
        )
        anchors[key] = dict(bbox=box)
        if row < 3:
            cells.append(
                dict(block_id=key, anchor_id=key, text=text, row=row, column=col)
            )
    table = dict(id="t1", cells=cells)
    warnings = _table_local_warnings(table, blocks, anchors)
    assert {w["code"] for w in warnings} == {
        "TABLE_COLUMN_COLLISION",
        "TABLE_CONTINUATION_UNRESOLVED",
    }
    assert all(w["anchor_id"] in anchors and w["bbox"] for w in warnings)
    cells[1]["column"] = 2
    assert not _table_local_warnings(table, blocks[:5], anchors)
