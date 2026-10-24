"""Printed borders, not extrapolated values, bound axis endpoint association."""

from copy import deepcopy

import pytest

from aletheia_nexus.content.backends.image_axes import associate_axes


def axes():
    def record(text, box):
        return dict(text=text, box=box, score=0.99)

    records = [
        record("Time / s", (140, 225, 200, 235)),
        record("Current / A", (45, 70, 55, 150)),
    ]
    records += [
        record(str(v), (x - 5, 205, x + 5, 215))
        for x, v in zip(range(80, 321, 40), range(1, 8))
    ]
    records += [
        record(str(v), (60, y, 70, y + 10)) for y, v in [(40, 9), (90, 4), (150, -2)]
    ]
    # Another panel's tick and a baseline Y tick lie outside the painted border.
    records += [record("8", (355, 205, 365, 215)), record("0", (55, 205, 65, 215))]
    return records


def image(border=True, filled=False):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    result = Image.new("RGB", (500, 260), "black" if filled else "white")
    if border:
        ImageDraw.Draw(result).line((80, 195, 320, 195), fill="black")
    return result


def test_observed_border_recovers_outer_ticks_and_preserves_their_source_bounds():
    result = associate_axes(axes(), image())
    x = next(
        r
        for r in result
        if r.get("method") == "positioned-axis-label-ticks"
        and r["text"].startswith("X axis:")
    )
    assert x["text"] == "X axis: Time / s; printed ticks: 1, 2, 3, 4, 5, 6, 7"
    assert x["box"] == (75, 205, 325, 235)
    assert not next(r for r in result if r["text"] == "8").get("alternative")
    assert not next(r for r in result if r["text"] == "0").get("alternative")


@pytest.mark.parametrize("source", [None, "blank", "filled"])
def test_no_painted_border_does_not_authorize_endpoint_extension(source):
    result = associate_axes(
        axes(), None if source is None else image(False, source == "filled")
    )
    x = next(
        r
        for r in result
        if r.get("method") == "positioned-axis-label-ticks"
        and r["text"].startswith("X axis:")
    )
    assert x["text"] == "X axis: Time / s; printed ticks: 2, 3, 4"


def test_competing_axis_titles_abstain_and_duplicate_baseline_ticks_stay_separate():
    records = axes()
    records.append(dict(text="Charge / C", score=0.99, box=(139, 224, 199, 234)))
    assert not any(
        r.get("method") == "positioned-axis-label-ticks"
        for r in associate_axes(deepcopy(records), image())
    )
    records = axes()
    records.append(dict(text="1", score=0.99, box=(80, 205, 90, 215)))
    assert not any(
        r.get("method") == "positioned-axis-label-ticks"
        for r in associate_axes(records, image())
    )
