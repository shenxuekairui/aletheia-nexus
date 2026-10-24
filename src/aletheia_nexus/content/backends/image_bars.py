"""Associate printed bar labels using category positions and legend swatches.

Bar heights are never converted into measurements. Ambiguous/missing labels or
indistinguishable swatches leave the original readings unchanged.
"""

from __future__ import annotations

import re
from statistics import median

from aletheia_nexus.content.backends.image_axes import _printed_horizontal_limits


def _numeric_categories(records, image):
    """Require a unique axis title, ordered printed ticks and an actual border."""
    numbers = [r for r in records if re.fullmatch(r"[−-]?\d+(?:\.\d+)?", r["text"])]
    result = []
    for label in records:
        x0, y0, x1, y1 = label["box"]
        h = y1 - y0
        w = x1 - x0
        if w < 2 * h or not re.search(r"[A-Za-z]{2}", label["text"]):
            continue
        ticks = [
            r
            for r in numbers
            if y0 - 2.5 * h <= (r["box"][1] + r["box"][3]) / 2 < y0
            and x0 - w * 0.5 <= (r["box"][0] + r["box"][2]) / 2 <= x1 + w * 0.5
        ]
        if len(ticks) < 3:
            continue
        baseline = median((r["box"][1] + r["box"][3]) / 2 for r in ticks)
        ticks = [
            r
            for r in ticks
            if abs((r["box"][1] + r["box"][3]) / 2 - baseline) < h * 0.6
        ]
        if len(ticks) < 3:
            continue
        # A one-sided boundary is sufficient here only because the caller
        # subsequently requires two actual colour-matched bars per category.
        limits = _printed_horizontal_limits(image, ticks, allow_fill_above=True)
        if not limits:
            continue
        ticks = sorted(
            [
                r
                for r in numbers
                if limits[0] <= (r["box"][0] + r["box"][2]) / 2 <= limits[1]
                and abs((r["box"][1] + r["box"][3]) / 2 - baseline) < h * 0.6
            ],
            key=lambda r: r["box"][0],
        )
        values = [float(r["text"].replace("−", "-")) for r in ticks]
        if len(values) < 3 or not all(a < b for a, b in zip(values, values[1:])):
            continue
        result.append((ticks, {**label, "axis_limits": limits}))
    return [
        (ticks, label)
        for ticks, label in result
        if not any(
            other is not label and set(map(id, ticks)) & set(map(id, others))
            for others, other in result
        )
    ]


def associate_bars(records, image):
    import numpy as np

    active = [r for r in records if not r.get("alternative") and r["score"] >= 0.9]
    number = re.compile(r"[−-]?\d+(?:\.\d+)?%?")
    labels = [
        r
        for r in active
        if not number.fullmatch(r["text"])
        and re.search(r"[A-Za-z]", r["text"])
        and len(r["text"]) <= 30
        and r["box"][2] - r["box"][0] >= (r["box"][3] - r["box"][1]) * 0.7
    ]
    rows = []
    for r in sorted(labels, key=lambda r: sum(r["box"][1::2])):
        if rows and abs(sum(r["box"][1::2]) - sum(rows[-1][0]["box"][1::2])) < (
            r["box"][3] - r["box"][1]
        ):
            rows[-1].append(r)
        else:
            rows.append([r])
    numeric = _numeric_categories(active, image)
    contexts = {id(row): label for row, label in numeric}
    rows.extend(row for row, _ in numeric)
    rgb = np.asarray(image.convert("RGB"))

    def feature(box):
        x0, y0, x1, y1 = [round(x) for x in box]
        pixels = rgb[
            max(0, y0) : min(image.height, y1), max(0, x0) : min(image.width, x1)
        ]
        if pixels.size < 30:
            return None
        # Include white hatching in the texture distribution. The colours and
        # series order come from the image, never a metric vocabulary.
        bins = (pixels.astype(int) // 32).reshape(-1, 3)
        indexes = bins[:, 0] * 64 + bins[:, 1] * 8 + bins[:, 2]
        hist = np.bincount(indexes, minlength=512) / len(indexes)
        if np.mean(pixels.max(axis=2) - pixels.min(axis=2) > 30) < 0.08:
            return None
        return hist

    extra = []
    previous_bottom = 0
    for categories in rows:
        if len(categories) < 3:
            continue
        context = contexts.get(id(categories))
        categories = sorted(categories, key=lambda r: sum(r["box"][::2]))
        centers = [(r["box"][0] + r["box"][2]) / 2 for r in categories]
        steps = [b - a for a, b in zip(centers, centers[1:])]
        step = median(steps)
        if min(steps) < step * 0.7 or max(steps) > step * 1.3:
            continue
        bottom = min(r["box"][1] for r in categories)
        top = (
            max(
                (
                    other["box"][3]
                    for _, other in numeric
                    if context
                    and other is not context
                    and other["box"][3] < bottom
                    and other["axis_limits"][0] < context["axis_limits"][1]
                    and context["axis_limits"][0] < other["axis_limits"][1]
                ),
                default=0,
            )
            if context
            else previous_bottom
        )
        previous_bottom = max(r["box"][3] for r in categories)
        interior = [
            r
            for r in labels
            if top <= r["box"][1]
            and r["box"][3] < bottom
            and centers[0] - step * 0.5 < r["box"][0] < centers[-1] + step * 0.7
        ]
        legends = []
        for label in interior:
            x0, y0, x1, y1 = label["box"]
            h = y1 - y0
            peers = [
                r
                for r in interior
                if r is not label
                and abs(r["box"][0] - x0) < h * 0.4
                and h * 0.6 < abs(sum(r["box"][1::2]) - y0 - y1) / 2 < h * 2
            ]
            if len(peers) != 1:
                continue
            f = feature((x0 - h * 1.9, y0 + h * 0.15, x0 - h * 0.35, y1 - h * 0.15))
            if f is not None:
                legends.append((label, f))
        if len(legends) != 2 or np.abs(legends[0][1] - legends[1][1]).sum() < 0.6:
            continue
        candidates = [
            r
            for r in active
            if number.fullmatch(r["text"])
            and top <= r["box"][1]
            and r["box"][3] < bottom
            and centers[0] - step * 0.45
            < sum(r["box"][::2]) / 2
            < centers[-1] + step * 0.45
        ]
        assignments = []
        for category, cx in zip(categories, centers):
            values = [
                r for r in candidates if abs(sum(r["box"][::2]) / 2 - cx) < step * 0.45
            ]
            if len(values) != 2:
                assignments = []
                break
            pairs = []
            for value in values:
                x0, y0, x1, y1 = value["box"]
                h = y1 - y0
                vx = (x0 + x1) / 2
                start = y1 + 1
                if context:
                    # Exclude white space between a printed label and the bar.
                    # The painted column must continue to its actual baseline.
                    ix0, ix1 = round(vx - h * 0.25), round(vx + h * 0.25)
                    band = rgb[
                        round(y1 + 1) : round(bottom - 3),
                        max(0, ix0) : min(image.width, ix1),
                    ]
                    colour = (
                        (band.max(axis=2) - band.min(axis=2) > 30).mean(axis=1)
                        if band.size
                        else []
                    )
                    first = next(
                        (
                            i
                            for i, v in enumerate(colour[: max(1, round(h))])
                            if v >= 0.8
                        ),
                        None,
                    )
                    if (
                        first is None
                        or len(colour) - first < 3 * h
                        or sum(v >= 0.8 for v in colour[first:]) / (len(colour) - first)
                        < 0.85
                    ):
                        break
                    start = round(y1 + 1) + first
                end = start + h * 0.6 if context else y1 + h * 0.7
                f = feature((vx - h * 0.25, start, vx + h * 0.25, end))
                if f is None:
                    break
                distances = sorted(
                    (float(np.abs(f - lf).sum()), i)
                    for i, (_, lf) in enumerate(legends)
                )
                if distances[0][0] > 0.8 or distances[1][0] - distances[0][0] < 0.35:
                    break
                pairs.append((value, legends[distances[0][1]][0]))
            if len(pairs) != 2 or pairs[0][1] is pairs[1][1]:
                assignments = []
                break
            assignments.append((category, pairs))
        metric_labels = []
        if context:
            left = context["axis_limits"][0]
            metric_labels = [
                r
                for r in active
                if re.search(r"[A-Za-z]", r["text"])
                and r["box"][3] - r["box"][1] > 1.3 * (r["box"][2] - r["box"][0])
                and top <= r["box"][1] < r["box"][3] < bottom
                and 0 <= left - r["box"][2] <= 2 * (r["box"][2] - r["box"][0])
            ]
            metric_labels.sort(key=lambda r: r["box"][1], reverse=True)
        for category, pairs in assignments:
            text = (
                (context["text"] + " = " if context else "")
                + category["text"]
                + ": "
                + "; ".join(
                    f"{label['text']} {value['text']}" for value, label in pairs
                )
            )
            members = [category, *[v for v, _ in pairs], *[label for _, label in pairs]]
            if context:
                members.extend([context, *metric_labels])
            if metric_labels:
                text += "; adjacent axis labels: " + " | ".join(
                    r["text"] for r in metric_labels
                )
            extra.append(
                {
                    **category,
                    "text": text,
                    "box": (
                        min(r["box"][0] for r in members),
                        min(r["box"][1] for r in members),
                        max(r["box"][2] for r in members),
                        max(r["box"][3] for r in members),
                    ),
                    "method": "printed-bar-label-association",
                    "score": min(r["score"] for r in members),
                }
            )
            for value, _ in pairs:
                value["alternative"] = True
                value["association_source"] = True
            category["alternative"] = True
            category["association_source"] = True
    return [*records, *extra]
