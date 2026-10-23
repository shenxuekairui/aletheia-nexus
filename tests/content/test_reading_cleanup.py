"""Review burden must decrease without losing scientific disagreements."""

from dataclasses import replace

import pytest

from aletheia_nexus.content.backends import AdaptiveOcrBackend
from aletheia_nexus.content.backends.readings import corroborate_chinese
from aletheia_nexus.content.evidence import review_locations
from aletheia_nexus.content.models import LayoutLine, PageLayout


def line(text, engine="native", **kwargs):
    return LayoutLine(text, 20, 400, 500, 420, 12, source_engines=(engine,), **kwargs)


def page(*lines):
    return PageLayout(page=1, width=600, height=800, lines=lines)


def test_chinese_repair_requires_native_and_other_model_and_retains_audit():
    native = page(line("电流效率达\x00\x00%以上"))
    first = page(line("电 流 歼 率 达 80%以上，1200 A/m²", "best"))
    second = page(line("电流效率达80多以上，1200 A/吃", "fast"))
    layouts, warnings = corroborate_chinese(native, [first, second])
    assert layouts[0].lines[0].text == "电 流 效 率 达 80%以上，1200 A/m²"
    assert layouts[0].lines[0].uncertain
    assert warnings[0]["before"] == first.lines[0].text
    assert warnings[0]["other_readings"] == [second.lines[0].text]
    assert layouts[1] == second


@pytest.mark.parametrize(
    "reason",
    [
        "no-native",
        "no-other-model",
        "same-model",
        "retry-same-model",
        "different-row",
        "low-confidence",
        "contradictory-votes",
        "repeated-window",
    ],
)
def test_chinese_repair_does_not_infer_from_dictionary_or_ambiguous_evidence(reason):
    native = page(line("电流效率达80%"))
    first = page(line("电流歼率达80%", "best"))
    second = page(line("电流效率达80%", "fast"))
    if reason == "no-native":
        native = page()
    elif reason == "no-other-model":
        second = page()
    elif reason in {"same-model", "retry-same-model"}:
        second = page(
            replace(
                second.lines[0],
                source_engines=(
                    "best+line-retry" if reason.startswith("retry") else "best",
                ),
            )
        )
    elif reason == "different-row":
        second = page(replace(second.lines[0], y0=300, y1=320))
    elif reason == "low-confidence":
        second = page(replace(second.lines[0], extraction_confidence=0.6))
    elif reason == "contradictory-votes":
        second = page(*second.lines, line("电流歼率达80%", "fast"))
    elif reason == "repeated-window":
        native = page(line("电流效率达80%，电流效率达90%"))
    layouts, warnings = corroborate_chinese(native, [first, second])
    assert layouts[0] == first
    assert not warnings


def test_corroboration_never_changes_digits_units_or_negation_without_han_context():
    first = page(line("效率80.90%，1200 A/m²，不增产", "best"))
    other = "效率80.85%，1200 A/m2，增产"
    layouts, warnings = corroborate_chinese(
        page(line(other)), [first, page(line(other, "fast"))]
    )
    assert layouts[0] == first
    assert not warnings


def test_exact_reading_coalesces_provenance_without_clearing_uncertainty():
    first = line(
        "electrolysis yielded 80%", "best", uncertain=True, content_region="figure"
    )
    second = replace(
        first,
        text="electrolysis yielded 80 %",
        source_engines=("fast",),
        content_region="ocr-alternative",
        y0=398,
        y1=420,
    )
    merged, _ = AdaptiveOcrBackend()._merge(page(), [page(first, second)])
    assert len(merged) == 1
    assert set(merged[0].source_engines) == {"best", "fast"}
    assert merged[0].uncertain


def test_ocr_cannot_replace_a_font_verified_unit_due_to_an_unrelated_ligature():
    text = "7.4 μm \ue103ber"
    native = replace(
        page(line(text, uncertain=True)),
        warnings=({"code": "NATIVE_UNIT_MAPPING_CORRECTED", "after": text},),
    )
    merged, warnings = AdaptiveOcrBackend()._merge(
        native, [page(line("7.4 pm fiber", "ocr", extraction_confidence=0.99))]
    )
    primary = [row for row in merged if not row.content_region.endswith("alternative")]
    assert [row.text for row in primary] == [text]
    assert any(row.text == "7.4 pm fiber" and row.uncertain for row in merged)
    assert any(w["code"] == "OCR_ENGINE_DISAGREEMENT" for w in warnings)


@pytest.mark.parametrize(
    "first,second",
    [
        ("1 2", "12"),
        ("80.90%", "80.85%"),
        ("1200 A/m²", "1200 A/m"),
        ("90 mA", "90 MA"),
        ("-1.4 V", "1.4 V"),
        ("Co", "CO"),
        ("mA", "MA"),
        ("(R)-catalyst", "(S)-catalyst"),
        ("with additive", "without additive"),
    ],
)
def test_cleanup_retains_scientific_disagreements(first, second):
    merged, _ = AdaptiveOcrBackend()._merge(
        page(), [page(line(first, "best")), page(line(second, "fast"))]
    )
    assert {r.text for r in merged} == {first, second}
    assert all(r.uncertain for r in merged)


@pytest.mark.parametrize("scan", [False, True])
def test_local_triggers_route_ink_regions_but_scans_use_full_page(scan):
    from aletheia_nexus.content.models import PageObject

    clean = line("Native method with complete units and enough text. " * 3)
    damaged = replace(line("Damaged \ufffd glyph", uncertain=True), y0=300, y1=320)
    native = replace(
        page(clean, damaged),
        objects=(
            PageObject(
                "image", "chart", bbox=(0, 0, 1, 1) if scan else (0.1, 0.1, 0.8, 0.3)
            ),
            PageObject("image", "small chemical scheme", bbox=(0.8, 0.1, 0.9, 0.2)),
        ),
    )
    calls = []

    class Native:
        name, version = "native", "1"

        def extract_page(self, _page, _number):
            return native

    class Ocr:
        name, version = "ocr", "1"

        def extract_page(self, _page, _number):
            calls.append("full")
            return page()

        def extract_regions(self, _page, _number, regions):
            calls.extend(regions)
            return page()

    AdaptiveOcrBackend(native_backend=Native(), ocr_backends=(Ocr(),)).extract_page(
        None, 1
    )
    if scan:
        assert calls == ["full"]
    else:
        assert len(calls) == 3
        assert calls[0].bbox == (0.1, 0.1, 0.8, 0.3)
        assert calls[1].bbox == (0.8, 0.1, 0.9, 0.2)
        assert calls[2].bbox[1] < 300 / 800 < 320 / 800 < calls[2].bbox[3]
        assert calls[2].bbox[3] < 400 / 800  # Clean native method is not submitted.


def block(id, box, region="body", page=1, text="80.90%"):
    return {
        "id": id,
        "page": page,
        "text": text,
        "uncertain": True,
        "content_region": region,
        "evidence": {"bbox": box},
    }


def test_glyph_context_does_not_reread_unrelated_clear_numbers():
    from aletheia_nexus.content.backends.adaptive import _local_glyph_context

    text = "Loading 0.125 was held constant while the measured rate was 8 ± 2 units."
    reading = replace(
        line(text, uncertain=True),
        glyph_spans=tuple((i, i + 1, 20 + i * 5, 25 + i * 5) for i in range(len(text))),
    )
    warning = dict(
        code="NATIVE_GLYPH_CONTEXT",
        after=text,
        bbox=[reading.x0, reading.y0, reading.x1, reading.y1],
        text_offsets=[text.index("±")],
        detail="Unmapped source glyph",
    )
    layout = replace(page(reading), warnings=(warning,))
    ranges = _local_glyph_context(reading, layout)
    assert ranges == [
        (
            (20 + text.index("8 ± 2") * 5) / 600,
            (20 + (text.index("8 ± 2") + 5) * 5) / 600,
        )
    ]
    assert ranges[0][0] > (20 + text.index("0.125") * 5) / 600
    assert _local_glyph_context(replace(reading, glyph_spans=()), layout) == []
    # Same text elsewhere does not authorize applying this line's coordinates.
    assert _local_glyph_context(replace(reading, y0=100, y1=120), layout) == []


def test_review_groups_preserve_every_block_and_separate_original_conflicts():
    entry = {
        "blocks": [
            block("chinese", [0.1, 0.6, 0.9, 0.7]),
            block("ocr", [0.2, 0.61, 0.8, 0.69], "ocr-alternative", text="80.85%"),
            block("english", [0.1, 0.3, 0.9, 0.4], text="80.85%"),
            block("next-page", [0.2, 0.61, 0.8, 0.69], "ocr-alternative", page=2),
        ]
    }
    groups = review_locations(entry)
    assert [g["block_ids"] for g in groups] == [
        ["chinese", "ocr"],
        ["english"],
        ["next-page"],
    ]
    assert all(g["uncertain"] for g in groups)
    assert entry["blocks"][1]["text"] == "80.85%"
    difference = groups[0]["reading_differences"][0]
    assert difference["changes"] == [{"primary": "80.90%", "alternative": "80.85%"}]
    assert groups[0]["primary_block_ids"] == ["chinese"]
    assert groups[0]["alternative_block_ids"] == ["ocr"]


def test_figure_group_does_not_absorb_prose_or_full_scanned_pages():
    entry = {
        "blocks": [
            block("axis1", [0.2, 0.2, 0.3, 0.3], "figure"),
            block("axis2", [0.4, 0.2, 0.5, 0.3], "ocr-alternative"),
            block("prose", [0.1, 0.1, 0.6, 0.6]),
        ],
        "figures": [
            {"id": "f1", "source_objects": [{"page": 1, "bbox": [0.1, 0.1, 0.6, 0.6]}]}
        ],
    }
    groups = review_locations(entry)
    assert [g["block_ids"] for g in groups] == [["axis1", "axis2"], ["prose"]]
    assert groups[0]["kind"] == "figure"
    entry["figures"][0]["source_objects"][0]["bbox"] = [0, 0, 1, 1]
    assert all(g["kind"] == "text" for g in review_locations(entry))


def test_table_review_keeps_headers_cells_and_alternatives_together_per_page():
    entry = {
        "blocks": [
            block("header", [0.1, 0.6, 0.9, 0.7], text="Yield %"),
            block("cell", [0.1, 0.5, 0.2, 0.6], text="64"),
            block("ocr", [0.1, 0.5, 0.2, 0.6], "ocr-alternative", text="84"),
            block("continued", [0.1, 0.5, 0.2, 0.6], page=2),
            block("body-conflict", [0.1, 0.8, 0.9, 0.9], text="Yield was 65%."),
        ],
        "tables": [
            {"id": "table", "block_ids": ["header", "cell", "ocr", "continued"]}
        ],
    }
    groups = review_locations(entry)
    assert [g["block_ids"] for g in groups] == [
        ["header", "cell", "ocr"],
        ["continued"],
        ["body-conflict"],
    ]
    assert [g["kind"] for g in groups] == ["table", "table", "text"]
    assert all(g["uncertain"] for g in groups)
    assert entry["blocks"][1]["text"] == "64"
    assert entry["blocks"][2]["text"] == "84"
    assert groups[0]["reading_differences"][0]["changes"] == [
        {"primary": "64", "alternative": "84"}
    ]
    assert not groups[2]["reading_differences"]  # real prose conflict stays separate
