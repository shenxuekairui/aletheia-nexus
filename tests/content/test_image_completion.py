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
