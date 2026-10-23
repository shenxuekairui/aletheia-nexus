"""Image rereading must complete evidence, never replace a conflicting value."""

from copy import deepcopy

import pytest

from aletheia_nexus.content.backends.image_axes import associate_axes
from aletheia_nexus.content.backends.image_readings import (
    complete_edge_scripts,
    ink_colour,
    merge_complete_reading,
    normalize_formula_scripts,
    reread_formula_markup,
)


def r(text, box=(30, 30, 110, 50), score=0.99):
    return dict(text=text, box=box, score=score)


@pytest.mark.parametrize("original", [">0.4", "≤0.4", "0.4 mA", "0.4%", "0.4a"])
def test_numeric_margin_crop_cannot_drop_measurement_qualifiers(original):
    from aletheia_nexus.content.backends.image_tick_crops import read_tick_margins

    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (2400, 1000), "white")
    records = [r(str(i), (600, 40 + i * 30, 630, 60 + i * 30)) for i in range(6)]
    full = r(original, (2100, 300, 2180, 340))
    records.append(full)
    # The same source digits are recognized in two right-margin crop scales.
    reads = iter(
        [
            [],
            [],
            [],
            [],
            [r("0.4", (66, 150, 106, 170))],
            [r("0.4", (79.2, 180, 127.2, 204))],
        ]
    )
    output = read_tick_margins(records, image, lambda _: next(reads), lambda _: None)
    assert not full.get("alternative")
    crop = next(item for item in output if item["text"] == "0.4")
    assert crop["alternative"]
    assert crop["box"] == pytest.approx(full["box"], abs=1)


def test_numeric_margin_can_add_a_missing_tick_without_replacing_another_number():
    from aletheia_nexus.content.backends.image_tick_crops import read_tick_margins

    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (2400, 1000), "white")
    for old, allowed in [(None, True), ("-0.4", False), ("0.7", False)]:
        records = [r(str(i), (600, 40 + i * 30, 630, 60 + i * 30)) for i in range(6)]
        if old is not None:
            records.append(r(old, (2100, 300, 2180, 340)))
        reads = iter(
            [
                [],
                [],
                [],
                [],
                [r("0.4", (66, 150, 106, 170))],
                [r("0.4", (79.2, 180, 127.2, 204))],
            ]
        )
        output = read_tick_margins(
            records, image, lambda _: next(reads), lambda _: None
        )
        assert (
            any(
                item["text"] == "0.4" and not item.get("alternative") for item in output
            )
            is allowed
        )
        if old is not None:
            assert not next(item for item in output if item["text"] == old).get(
                "alternative"
            )


@pytest.mark.parametrize("offset", [0, 40])
def test_panel_corner_requires_real_gutters_scale_and_two_agreeing_readings(
    monkeypatch, offset
):
    from aletheia_nexus.content.backends import image_panels as panels

    Image = pytest.importorskip("PIL.Image")
    im = Image.new("RGB", (440, 240), "gray")
    monkeypatch.setattr(
        panels,
        "panel_boxes",
        lambda _: [(offset, 0, offset + 180, 200), (240, 0, 420, 200)],
    )
    records = [
        r("40 nm", (offset + 100, 170, offset + 170, 190)),
        r("O", (offset + 5, 5, offset + 35, 40), 0.65),
    ]
    panels.read_panel_markers(records, im, lambda _: ("b)", 0.98))
    assert records[1]["alternative"]
    assert records[-1]["text"] == "b)"
    associated = panels.associate_scales(records, im)
    assert any(x["text"] == "Panel (b): scale 40 nm" for x in associated)
    # The unscaled second panel gets no invented sequential marker.
    assert sum(x.get("method") == "rapidocr-panel-corner-reading" for x in records) == 1


@pytest.mark.parametrize(
    "readings",
    [
        [("b)", 0.98), ("d)", 0.98)],
        [("b)", 0.98), ("b)", 0.7)],
        [("3)", 0.99), ("3)", 0.99)],
    ],
)
def test_panel_corner_abstains_on_confidence_or_reading_conflict(monkeypatch, readings):
    from aletheia_nexus.content.backends import image_panels as panels

    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(
        panels, "panel_boxes", lambda _: [(0, 0, 200, 200), (210, 0, 410, 200)]
    )
    records = [r("40 nm", (100, 170, 170, 190))]
    responses = iter(readings)
    assert (
        panels.read_panel_markers(
            records, Image.new("RGB", (420, 200)), lambda _: next(responses)
        )
        == records
    )
    assert len(records) == 1


def test_completion_preserves_conflicting_digits_units_and_exponents():
    for original, complete, allowed in [
        ("18 h", "18 h-1", True),
        ("18 h-2", "18 h-1", False),
        ("18 m", "18 h-1", False),
        ("18 h", "19 h-1", False),
        ("76% X (18 h", "76% X (18 h-1), 51 ee%", True),
        ("76% X (18 h", "77% X (18 h-1), 51 ee%", False),
        ("18 h", "18 h", False),
    ]:
        records = [r(original)]
        assert merge_complete_reading(records, r(complete)) is allowed
        assert records[0].get("alternative", False) is allowed
    records = [r("18 h"), r("19 h")]
    assert not merge_complete_reading(records, r("18 h-1"))
    assert not merge_complete_reading([r("18 h")], r("18 h-1", (150, 30, 230, 50)))


def test_edge_scripts_need_two_matching_crops_and_only_append_scripts():
    Image = pytest.importorskip("PIL.Image")
    im = Image.new("RGB", (300, 100), "white")
    for old, new, allowed in [
        ("17 s", "17 s-2", True),
        ("CaSO", "CaSO4", True),
        ("17 s", "71 s-2", False),
        ("17 s", "17 ms-2", False),
    ]:
        records = [r(old)]
        complete_edge_scripts(records, im, lambda crop: (new, 0.98))
        assert records[0].get("alternative", False) is allowed
    reads = iter([("17 s-2", 0.98), ("17 s-1", 0.98)])
    records = [r("17 s")]
    complete_edge_scripts(records, im, lambda crop: next(reads))
    assert not records[0].get("alternative")


def test_ink_colour_does_not_name_background_or_mix_competing_colours():
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    Image = pytest.importorskip("PIL.Image")
    im = Image.new("RGB", (100, 40), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((10, 10, 20, 25), fill="red")
    assert ink_colour(im, (0, 0, 100, 40)) == "red"
    d.rectangle((50, 10, 60, 25), fill="blue")
    assert ink_colour(im, (0, 0, 100, 40)) is None
    im = Image.new("RGB", (100, 40), "blue")
    d = ImageDraw.Draw(im)
    d.rectangle((10, 10, 20, 25), fill="white")
    assert ink_colour(im, (0, 0, 100, 40)) is None


def test_two_y_axes_keep_titles_and_all_printed_ticks():
    records = [
        r("rate", (10, 60, 20, 100)),
        r("ee", (190, 65, 200, 95)),
        r("concentration", (60, 185, 160, 200)),
    ]
    for x in [30, 170]:
        records += [
            r(str(v), (x, y, x + 15, y + 10))
            for v, y in [(90, 20), (60, 60), (30, 100), (0, 140)]
        ]
    records += [
        r(str(v), (x, 165, x + 15, 175)) for v, x in [(1, 60), (2, 100), (3, 140)]
    ]
    output = associate_axes(deepcopy(records))
    derived = [
        x["text"] for x in output if x.get("method") == "positioned-axis-label-ticks"
    ]
    assert "Y axis: rate; printed ticks: 90, 60, 30, 0" in derived
    assert "Y axis: ee; printed ticks: 90, 60, 30, 0" in derived
    # Competing vertical titles do not authorize choosing one silently.
    ambiguous = associate_axes([*deepcopy(records), r("flux", (11, 60, 21, 100))])
    assert not any(x.get("method") == "positioned-axis-label-ticks" for x in ambiguous)


def test_nonmonotonic_y_ticks_get_a_local_gap_without_guessing_signs():
    records = [r("rate", (10, 60, 20, 100)), r("concentration", (60, 185, 160, 200))]
    records += [
        r(str(v), (30, y, 45, y + 10))
        for v, y in [(40, 30), (30, 65), (-10, 100), (0, 135)]
    ]
    records += [
        r(str(v), (x, 165, x + 15, 175)) for v, x in [(1, 60), (2, 100), (3, 140)]
    ]
    output = associate_axes(records)
    warning = next(x for x in output if x.get("warning"))
    assert warning["warning"] == "IMAGE_AXIS_TICK_ORDER_CONFLICT"
    assert "40, 30, -10, 0" in warning["text"]
    assert "unresolved tick order" in warning["text"]
    original = next(x for x in output if x["text"] == "-10")
    assert not original.get("alternative")


def test_formula_markup_needs_repeated_source_confirmation():
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    Image = pytest.importorskip("PIL.Image")
    assert normalize_formula_scripts("Fe_2O_3") == "Fe2O3"
    assert normalize_formula_scripts("Fe2}O{3") == "Fe2O3"
    assert normalize_formula_scripts("foo_bar2") is None
    assert normalize_formula_scripts("Fe_2O_4") != "Fe2O3"
    im = Image.new("RGB", (150, 80), "white")
    ImageDraw.Draw(im).rectangle((40, 35, 100, 45), fill="black")
    records = [r("Fe_2O_3", score=0.74)]
    reread_formula_markup(records, im, lambda crop: ("Fe2}O{3", 0.75))
    assert records[0]["alternative"]
    assert records[-1]["text"] == "Fe2O3" and records[-1]["score"] == 0.74
    records = [r("Fe_2O_3", score=0.74)]
    reread_formula_markup(records, im, lambda crop: ("Fe2}O{4", 0.75))
    assert len(records) == 1 and not records[0].get("alternative")


def test_crop_consensus_recovers_weak_text_without_changing_confident_numbers():
    Image = pytest.importorskip("PIL.Image")

    from aletheia_nexus.content.backends.image_readings import reread_uncertain_lines

    image = Image.new("RGB", (400, 100), "white")

    def record(text, score):
        return dict(text=text, score=score, box=(20, 20, 180, 40))

    weak = record("8 yld", 0.64)
    out = reread_uncertain_lines([weak], image, lambda crop: ("88% yield", 0.99))
    assert weak["alternative"] and out[-1]["text"] == "88% yield"
    strong = record("18% yield", 0.92)
    out = reread_uncertain_lines([strong], image, lambda crop: ("88% yield", 0.99))
    assert out == [strong] and not strong.get("alternative")
    typo = record("3 mo1%", 0.91)
    out = reread_uncertain_lines([typo], image, lambda crop: ("3 mol%", 0.99))
    assert typo["alternative"] and out[-1]["text"] == "3 mol%"
    ambiguous = record("8 yld", 0.64)
    readings = iter([("88% yield", 0.99), ("83% yield", 0.99)] * 2)
    out = reread_uncertain_lines([ambiguous], image, lambda crop: next(readings))
    assert out == [ambiguous] and not ambiguous.get("alternative")


@pytest.mark.parametrize(
    ("original", "alternative"), [("500 mm", "500 nm"), ("2.5 nm", "2.5 μm")]
)
@pytest.mark.parametrize("crop_score", [0.92, 0.99])
def test_scale_unit_crop_conflict_is_local_evidence_not_a_replacement(
    original, alternative, crop_score
):
    Image = pytest.importorskip("PIL.Image")

    from aletheia_nexus.content.backends.image_readings import reread_uncertain_lines

    image = Image.new("RGB", (400, 100), "white")
    old = r(original, box=(20, 20, 180, 40), score=0.93)
    readings = iter([(alternative, crop_score)] * 4)
    out = reread_uncertain_lines([old], image, lambda crop: next(readings))
    assert len(out) == 2 and not old.get("alternative")
    assert out[1]["alternative"] and out[1]["text"] == alternative
    assert out[1]["box"] == old["box"]
    assert out[1]["warning"] == "IMAGE_SCALE_UNIT_CONFLICT"


@pytest.mark.parametrize(
    "readings",
    [
        [("600 nm", 0.98)] * 4,  # A different number is not a unit ambiguity.
        [("500 nm", 0.89)] * 2,  # Weak crop readings cannot establish a conflict.
        [("500 nm", 0.96), ("500 μm", 0.96)] * 2,
        [("500 mm", 0.96)] * 4,
    ],
)
def test_scale_crop_disagreement_needs_same_value_and_corroborated_unit(readings):
    Image = pytest.importorskip("PIL.Image")

    from aletheia_nexus.content.backends.image_readings import reread_uncertain_lines

    image = Image.new("RGB", (400, 100), "white")
    old = r("500 mm", box=(20, 20, 180, 40), score=0.93)
    responses = iter(readings)
    assert reread_uncertain_lines([old], image, lambda crop: next(responses)) == [old]
    assert not old.get("alternative")


def test_horizontal_dual_y_titles_keep_their_separate_printed_ticks():
    from aletheia_nexus.content.backends.image_axes import associate_axes

    def r(text, box):
        return dict(text=text, box=box, score=0.99)

    records = [
        r("Intensity (a.u.)", (10, 0, 100, 15)),
        r("ee (%)", (340, 0, 390, 15)),
        r("Concentration", (140, 250, 290, 265)),
    ]
    records += [
        r(str(t), (25, y, 45, y + 10)) for t, y in [(8, 30), (4, 100), (0, 180)]
    ]
    records += [
        r(str(t), (355, y, 375, y + 10)) for t, y in [(70, 30), (35, 100), (0, 180)]
    ]
    records += [
        r(str(t), (x, 230, x + 12, 240)) for t, x in [(-9, 70), (-6, 180), (-3, 290)]
    ]
    output = associate_axes(records)
    assert [
        r["text"] for r in output if r.get("method") == "positioned-axis-label-ticks"
    ] == [
        "Y axis: Intensity (a.u.); printed ticks: 8, 4, 0",
        "Y axis: ee (%); printed ticks: 70, 35, 0",
        "X axis: Concentration; printed ticks: -9, -6, -3",
    ]
