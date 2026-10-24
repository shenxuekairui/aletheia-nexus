"""Associate printed axis titles and ticks; never infer values from curves."""

from __future__ import annotations

import re
from statistics import median


def _printed_horizontal_limits(image, ticks, *, allow_fill_above=False):
    """Find the painted horizontal border immediately above observed ticks."""
    if image is None:
        return None
    gray = image.convert("L")
    pixels = gray.load()
    left = min((t["box"][0] + t["box"][2]) / 2 for t in ticks)
    right = max((t["box"][0] + t["box"][2]) / 2 for t in ticks)
    height = median(t["box"][3] - t["box"][1] for t in ticks)
    bottom = min(t["box"][1] for t in ticks)
    for y in range(
        min(gray.height - 4, int(bottom) - 1), max(2, int(bottom - height * 2.5)), -1
    ):
        start = None
        runs = []
        for x in range(gray.width + 1):
            dark = x < gray.width and pixels[x, y] < 190
            if dark and start is None:
                start = x
            elif not dark and start is not None:
                if start <= left and x >= right:
                    runs.append((start, x))
                start = None
        for a, b in runs:
            # A filled image background is not a plot border. Require narrow
            # dark ink with predominantly light pixels on both sides.
            if all(
                sum(pixels[x, y + offset] > 220 for x in range(a, b)) / (b - a) >= 0.75
                for offset in ((3,) if allow_fill_above else (-3, 3))
            ):
                return a, b
    return None


def associate_axes(records, image=None):
    ticks = [
        r
        for r in records
        if r["score"] >= 0.85
        and not r.get("alternative")
        and re.fullmatch(r"[+−-]?\d+(?:\.\d+)?[-–]?", r["text"])
    ]
    labels = [
        r
        for r in records
        if r["score"] >= 0.9
        and not r.get("alternative")
        and re.search(r"[^\W\d_]{2}", r["text"])
    ]

    def center(r, axis):
        return (r["box"][axis] + r["box"][axis + 2]) / 2

    horizontal = []
    for label in labels:
        x0, y0, x1, y1 = label["box"]
        h, w = y1 - y0, x1 - x0
        if w < 2 * h:
            continue
        near = [
            t
            for t in ticks
            if y0 - 2.5 * h <= center(t, 1) < y0
            and x0 - w * 0.5 <= center(t, 0) <= x1 + w * 0.5
        ]
        rows = []
        for tick in sorted(near, key=lambda t: center(t, 1)):
            row = next(
                (g for g in rows if abs(center(g[0], 1) - center(tick, 1)) < h * 0.6),
                None,
            )
            if row is None:
                rows.append([tick])
            else:
                row.append(tick)
        rows = [g for g in rows if len(g) >= 3]
        if len(rows) == 1:
            ordered = sorted(rows[0], key=lambda t: center(t, 0))
            limits = _printed_horizontal_limits(image, ordered)
            if limits:
                baseline = median(center(t, 1) for t in ordered)
                tolerance = median(t["box"][2] - t["box"][0] for t in ordered) * 0.4
                ordered = sorted(
                    [
                        t
                        for t in ticks
                        if abs(center(t, 1) - baseline) < h * 0.6
                        and limits[0] - tolerance
                        <= center(t, 0)
                        <= limits[1] + tolerance
                    ],
                    key=lambda t: center(t, 0),
                )
            values = [float(t["text"].rstrip("-–").replace("−", "-")) for t in ordered]
            # A Y-axis zero on the same baseline must not silently become an
            # extra X tick. Competing or repeated numeric sequences abstain.
            differences = [b - a for a, b in zip(values, values[1:])]
            if all(d > 0 for d in differences) or all(d < 0 for d in differences):
                horizontal.append((label, ordered))
    output = []
    for xlabel, xticks in horizontal:
        if any(
            other is not xlabel and {id(t) for t in xticks} & {id(t) for t in ts}
            for other, ts in horizontal
        ):
            continue
        baseline = min(center(t, 1) for t in xticks)
        tick_height = median(t["box"][3] - t["box"][1] for t in xticks)
        # An earlier X axis bounds a stacked plot. Do not merge two panels.
        previous = max(
            (other["box"][3] for other, _ in horizontal if other["box"][3] < baseline),
            default=0,
        )
        axes = []
        for label in labels:
            x0, y0, x1, y1 = label["box"]
            w = x1 - x0
            h = y1 - y0
            if label is xlabel or not previous <= center(label, 1) < baseline:
                continue
            vertical = h >= w * 1.3
            above = w >= h * 1.3 and y1 < baseline - tick_height * 4
            if not (vertical or above):
                continue
            near = [
                t
                for t in ticks
                if previous < center(t, 1) < baseline - tick_height * 0.6
                and (
                    (
                        vertical
                        and (
                            x1 - w * 0.5 <= t["box"][0] <= x1 + w * 2
                            or x0 - w * 2 <= t["box"][2] <= x0 + w * 0.5
                        )
                    )
                    or (
                        above
                        and center(t, 1) > y1
                        and x0 - h * 0.5 <= center(t, 0) <= x1 + h * 0.5
                    )
                )
            ]
            groups = []
            for tick in sorted(near, key=lambda t: center(t, 0)):
                group = next(
                    (
                        g
                        for g in groups
                        if abs(center(g[0], 0) - center(tick, 0))
                        < (w if vertical else tick_height) * 0.6
                    ),
                    None,
                )
                if group is None:
                    groups.append([tick])
                else:
                    group.append(tick)
            groups = [
                g
                for g in groups
                if len(g) >= 3
                and (
                    above
                    or min(center(t, 1) for t in g)
                    <= center(label, 1)
                    <= max(center(t, 1) for t in g)
                )
            ]
            if len(groups) != 1:
                continue
            yticks = sorted(groups[0], key=lambda t: center(t, 1))
            gaps = [center(b, 1) - center(a, 1) for a, b in zip(yticks, yticks[1:])]
            if min(gaps) <= 0 or max(gaps) > median(gaps) * 1.6:
                continue
            axes.append((label, yticks))
        if not axes:
            continue
        # A plot may repeat the same title above and beside a tick column.
        # Keep the more qualified spelling (e.g. its printed percent unit).
        reduced = []
        for label, ts in axes:
            same = next(
                (
                    i
                    for i, (other, ot) in enumerate(reduced)
                    if {id(t) for t in ts} == {id(t) for t in ot}
                    and re.sub(r"\s+|\(%\)|%", "", label["text"])
                    == re.sub(r"\s+|\(%\)|%", "", other["text"])
                ),
                None,
            )
            if same is None:
                reduced.append((label, ts))
            elif len(label["text"]) > len(reduced[same][0]["text"]):
                reduced[same] = (label, ts)
        axes = reduced
        # Two titles for the same vertical tick column remain ambiguous.
        if any(
            {id(t) for t in a[1]} & {id(t) for t in b[1]}
            for i, a in enumerate(axes)
            for b in axes[i + 1 :]
        ):
            continue
        for axis, label, values in [("Y", label, ts) for label, ts in axes] + [
            ("X", xlabel, xticks)
        ]:
            numbers = [float(t["text"].rstrip("-–").replace("−", "-")) for t in values]
            steps = [b - a for a, b in zip(numbers, numbers[1:])]
            ambiguous = not (all(d > 0 for d in steps) or all(d < 0 for d in steps))
            output.append(
                {
                    **label,
                    "box": (
                        min(r["box"][0] for r in [label, *values]),
                        min(r["box"][1] for r in [label, *values]),
                        max(r["box"][2] for r in [label, *values]),
                        max(r["box"][3] for r in [label, *values]),
                    ),
                    "text": f"{axis} axis: {label['text']}; "
                    + (
                        "unresolved tick order; observed readings: "
                        if ambiguous
                        else "printed ticks: "
                    )
                    + ", ".join(t["text"].rstrip("-–") for t in values),
                    "score": min(r["score"] for r in [label, *values]),
                    "method": "positioned-axis-label-ticks",
                    **(
                        {"warning": "IMAGE_AXIS_TICK_ORDER_CONFLICT"}
                        if ambiguous
                        else {}
                    ),
                }
            )
            if not ambiguous:
                for original in [label, *values]:
                    original["alternative"] = True
                    original["association_source"] = True
    return [*records, *output]
