from dataclasses import replace

from aletheia_nexus.content.figure_labels import (
    associate_keyed_labels,
    associate_percentage_results,
)
from aletheia_nexus.content.models import LayoutLine


def labels():
    return tuple(
        LayoutLine(text, x, y, x + w, y + 8, 8, source_engines=("fixture",))
        for text, x, y, w in [
            ("ion A2", 20, 120, 28),
            ("ion B4", 110, 120, 28),
            ("m/z = 317.25", 10, 110, 52),
            ("m/z = 438.17", 100, 110, 52),
            ("error: -1.3 ppm", 6, 100, 60),
            ("error: +0.4 ppm", 96, 100, 60),
        ]
    )


def test_keyed_values_and_signed_error_stay_with_each_unique_label():
    original = labels()
    output = associate_keyed_labels(original)
    primary = [
        line for line in output if not line.content_region.endswith("alternative")
    ]
    assert [line.text for line in primary] == [
        "ion A2; m/z = 317.25; error: -1.3 ppm",
        "ion B4; m/z = 438.17; error: +0.4 ppm",
    ]
    alternatives = [
        line for line in output if line.content_region.endswith("alternative")
    ]
    assert [line.text for line in alternatives] == [line.text for line in original]
    assert all(
        line.uncertain and line.source_engines == ("fixture",) for line in output
    )


def test_missing_or_competing_labels_do_not_authorize_grouping():
    original = labels()
    assert associate_keyed_labels(original[1:]) == original[1:]
    competitor = LayoutLine("ion Z8", 22, 128, 50, 136, 8)
    ambiguous = (*original, competitor)
    assert associate_keyed_labels(ambiguous) == ambiguous


def test_different_measurement_keys_or_a_neighbouring_column_do_not_merge():
    original = labels()
    changed = (*original[:-1], replace(original[-1], text="width: +0.4 ppm"))
    assert associate_keyed_labels(changed) == changed
    changed = (*original[:-1], replace(original[-1], x0=30, x1=130))
    assert associate_keyed_labels(changed) == changed


def test_table_cells_and_low_confidence_are_preserved():
    original = tuple(replace(line, content_region="table-cell") for line in labels())
    assert associate_keyed_labels(original) == original
    original = (replace(labels()[0], extraction_confidence=0.4), *labels()[1:])
    output = associate_keyed_labels(original)
    primary = next(
        line
        for line in output
        if line.extraction_method == "positioned-keyed-figure-labels"
    )
    assert primary.extraction_confidence == 0.4
    assert primary.engine_agreement is None


def results():
    return tuple(
        LayoutLine(text, x, y, x + w, y + 8, 8)
        for text, x, y, w in [
            ("K2", 45, 120, 10),
            ("K4", 145, 120, 10),
            ("23% yield, 87% ee", 15, 110, 70),
            ("41% yield, 93% ee", 115, 110, 70),
            ("48% yield, 89% ee*", 13, 100, 74),
            ("52% yield, 95% ee*", 113, 100, 74),
        ]
    )


def test_footnoted_result_stays_distinct_under_the_printed_label():
    source = results()
    output = associate_percentage_results(source)
    primary = [
        line for line in output if not line.content_region.endswith("alternative")
    ]
    assert [line.text for line in primary] == [
        "K2\n23% yield, 87% ee\n48% yield, 89% ee*",
        "K4\n41% yield, 93% ee\n52% yield, 95% ee*",
    ]
    assert [
        line.text for line in output if line.content_region.endswith("alternative")
    ] == [line.text for line in source]
    assert all(line.uncertain for line in output)


def test_percentage_result_requires_unique_label_and_separate_columns():
    source = results()
    ambiguous = (*source, replace(source[0], text="K9", y0=128, y1=136))
    assert associate_percentage_results(ambiguous) == ambiguous
    crossing = tuple(
        replace(line, x0=40, x1=160) if line is source[3] else line for line in source
    )
    assert associate_percentage_results(crossing) == crossing
    table = tuple(replace(line, content_region="table-cell") for line in source)
    assert associate_percentage_results(table) == table


def test_number_first_product_labels_staggered_results_keep_multiple_footnotes():
    source = list(results())
    source[0] = replace(source[0], text="7b")
    source[1] = replace(source[1], text="7cd")
    for i in [1, 3, 5]:
        source[i] = replace(source[i], y0=source[i].y0 + 6, y1=source[i].y1 + 6)
    source[5] = replace(source[5], text="52% yield, 95% ee†,‡")
    output = associate_percentage_results(tuple(source))
    groups = [
        r.text
        for r in output
        if r.extraction_method == "positioned-percentage-result-labels"
    ]
    assert "7b\n23% yield, 87% ee\n48% yield, 89% ee*" in groups
    assert "7cd\n41% yield, 93% ee\n52% yield, 95% ee†,‡" in groups
    assert [r.text for r in output if r.content_region.endswith("alternative")] == [
        r.text for r in source
    ]


def test_intervening_product_label_stops_following_result_assignment():
    source = results()
    intervening = replace(source[0], text="8a", y0=109, y1=117)
    output = associate_percentage_results((*source, intervening))
    assert not any("K2\n23% yield, 87% ee\n48%" in r.text for r in output)
    assert any(
        r.text == "48% yield, 89% ee*" and not r.content_region.endswith("alternative")
        for r in output
    )


def test_separate_product_rows_cannot_be_joined_as_footnote_variants():
    source = results()[:4]
    next_row = tuple(
        replace(
            r,
            text=r.text.replace("K2", "8a").replace("K4", "8b"),
            y0=r.y0 - 16,
            y1=r.y1 - 16,
        )
        for r in source
    )
    output = associate_percentage_results((*source, *next_row))
    groups = [
        r.text
        for r in output
        if r.extraction_method == "positioned-percentage-result-labels"
    ]
    assert len(groups) == 4
    assert all(t.count("yield") == 1 for t in groups)
