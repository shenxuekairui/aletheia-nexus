"""Printed bar values need physical category and colour evidence."""

from copy import deepcopy

import pytest

from aletheia_nexus.content.backends.image_bars import associate_bars


def chart(*, axis=True, bars=True):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    image = Image.new("RGB", (450, 410), "white")
    draw = ImageDraw.Draw(image)

    def r(text, box):
        return dict(text=text, box=box, score=0.99)

    records = [r("Alpha", (350, 20, 397, 36)), r("Beta", (350, 42, 390, 58))]
    colours = [(0, 140, 90), (180, 40, 150)]
    draw.rectangle((317, 20, 346, 36), fill=colours[0])
    draw.rectangle((317, 42, 346, 58), fill=colours[1])
    records.extend(
        [
            r("Current (mA)", (130, 360, 310, 378)),
            r("Volume", (25, 100, 40, 190)),
            r("(mL)", (25, 60, 40, 98)),
        ]
    )
    for i, cx in enumerate((100, 200, 300)):
        records.append(r(str(5 + 10 * i), (cx - 10, 328, cx + 10, 348)))
        for j, dx in enumerate((-15, 15)):
            # Deliberately unrelated bar heights and printed values.
            text = str((4, 51, 7, 83, 9, 24)[2 * i + j])
            y = 90 + 60 * j + 15 * i
            x = cx + dx
            records.append(r(text, (x - 8, y - 16, x + 8, y)))
            if bars:
                draw.rectangle((x - 12, y + 7, x + 12, 319), fill=colours[j])
    if axis:
        draw.line((60, 320, 400, 320), fill="black", width=2)
    return image, records


def groups(records, image):
    return [
        r
        for r in associate_bars(records, image)
        if r.get("method") == "printed-bar-label-association"
    ]


def test_numeric_categories_keep_values_units_and_series_with_raw_evidence():
    image, records = chart()
    original = deepcopy(records)
    result = groups(records, image)
    assert [r["text"] for r in result] == [
        f"Current (mA) = {category}: Alpha {a}; Beta {b}; adjacent axis labels: Volume | (mL)"
        for category, a, b in [(5, 4, 51), (15, 7, 83), (25, 9, 24)]
    ]
    assert all(r["box"][0] <= 25 and r["box"][3] >= 378 for r in result)
    assert [r["text"] for r in records] == [r["text"] for r in original]
    assert sum(bool(r.get("alternative")) for r in records) == 9


@pytest.mark.parametrize("axis,bars", [(False, True), (True, False)])
def test_numbers_and_coloured_points_without_both_bar_and_axis_proof_abstain(
    axis, bars
):
    image, records = chart(axis=axis, bars=bars)
    assert not groups(records, image)
    assert not any(r.get("alternative") for r in records)


def test_missing_value_competing_axis_and_identical_series_remain_unresolved():
    image, records = chart()
    assert not groups([r for r in deepcopy(records) if r["text"] != "51"], image)
    competing = deepcopy(records)
    competing.append(dict(text="Time (s)", box=(130, 361, 310, 379), score=0.99))
    assert not groups(competing, image)
    assert not groups(deepcopy(records), image.convert("L").convert("RGB"))


def test_adjacent_panels_do_not_borrow_categories_or_metric_labels():
    image, records = chart()
    Image = pytest.importorskip("PIL.Image")
    combined = Image.new("RGB", (900, 410), "white")
    combined.paste(image, (0, 0))
    combined.paste(image, (450, 0))
    shifted = [
        {
            **r,
            "text": r["text"].replace("Volume", "Mass").replace("mL", "mg"),
            "box": (r["box"][0] + 450, r["box"][1], r["box"][2] + 450, r["box"][3]),
        }
        for r in records
    ]
    result = groups([*records, *shifted], combined)
    assert len(result) == 6
    assert all("Volume" in r["text"] and "Mass" not in r["text"] for r in result[:3])
    assert all("Mass" in r["text"] and "Volume" not in r["text"] for r in result[3:])
