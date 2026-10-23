from dataclasses import replace

from aletheia_nexus.content.figure_labels import associate_keyed_labels
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
