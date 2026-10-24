import pytest

from aletheia_nexus.content.backends.image_vertical import (
    _preserves_fragments,
    read_vertical_labels,
)


@pytest.mark.parametrize(
    "reading,fragments",
    [
        ("production rate", ["(ml min1)", "production rate (", "H"]),
        ("volume", ["(ml)", "H2 volume"]),
        ("Current (mA)", ["Current (MA)"]),
        ("Potential vs reference (mV)", ["Potential", "VS reference (MV)"]),
        ("Potential vs Ag/AgCl (mV)", ["Potential", "VS Ag/AgCI (mV)"]),
        ("Current 10 A", ["Current 10−4 A"]),
        ("Current 102 A", ["Current 10² A"]),
        ("Current 10⁴ A", ["Current 10⁻⁴ A"]),
        ("Current 05 mA", ["Current 0.5 mA"]),
        ("Current 210³ A", ["Current 2×10³ A"]),
    ],
)
def test_shorter_crop_cannot_remove_observed_scientific_characters(reading, fragments):
    assert not _preserves_fragments(reading, fragments)


def test_fragmented_crop_can_keep_complete_label_in_either_reading_direction():
    assert _preserves_fragments("Hydrogen volume (mL)", ["(mL)", "Hydrogen volume"])
    assert _preserves_fragments("Current (mA cm−2)", ["Current", "(mA cm-2)"])


@pytest.mark.parametrize("reference", ["Ag/AgCI", "reference"])
def test_reference_operator_case_does_not_discard_a_complete_vertical_label(reference):
    assert _preserves_fragments(
        f"E vs {reference} / mV", ["mV", f"{reference} /", "VS", "E"]
    )


def test_truncated_crop_keeps_all_original_primary_fragments():
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (500, 400), "white")
    records = [
        dict(text="(mL)", box=(20, 30, 40, 80), score=0.99),
        dict(text="Volume", box=(20, 79, 40, 170), score=0.99),
    ]
    out = read_vertical_labels(
        records,
        image,
        lambda _: [dict(text="Volume", score=0.999, box=(0, 0, 120, 20))],
    )
    assert out == records
    assert not any(r.get("alternative") for r in out)


@pytest.mark.parametrize(
    "first,second",
    [
        ("Current (mA)", "Current (MA)"),
        ("Current 0.5 mA", "Current 05 mA"),
        ("Current 10⁻⁴ A", "Current 10⁴ A"),
    ],
)
def test_competing_complete_vertical_readings_preserve_scientific_differences(
    first, second
):
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (500, 400), "white")
    original = dict(text="Current", box=(20, 30, 40, 150), score=0.91)
    reads = iter([first, second])
    out = read_vertical_labels(
        [original],
        image,
        lambda _: [dict(text=next(reads), score=0.99, box=(0, 0, 150, 20))],
    )
    assert out == [original]
    assert not original.get("alternative")
