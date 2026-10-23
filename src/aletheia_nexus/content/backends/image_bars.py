"""Associate printed bar labels using category positions and legend swatches.

Bar heights are never converted into measurements. Ambiguous/missing labels or
indistinguishable swatches leave the original readings unchanged.
"""

from __future__ import annotations

import re
from statistics import median


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
        categories = sorted(categories, key=lambda r: sum(r["box"][::2]))
        centers = [(r["box"][0] + r["box"][2]) / 2 for r in categories]
        steps = [b - a for a, b in zip(centers, centers[1:])]
        step = median(steps)
        if min(steps) < step * 0.7 or max(steps) > step * 1.3:
            continue
        bottom = min(r["box"][1] for r in categories)
        top = previous_bottom
        previous_bottom = max(r["box"][3] for r in categories)
        interior = [
            r
            for r in labels
            if top <= r["box"][1]
            and r["box"][3] < bottom
            and centers[0] - step * 0.5 < r["box"][0]
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
                f = feature((vx - h * 0.25, y1 + 1, vx + h * 0.25, y1 + h * 0.7))
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
        for category, pairs in assignments:
            text = (
                category["text"]
                + ": "
                + "; ".join(
                    f"{label['text']} {value['text']}" for value, label in pairs
                )
            )
            extra.append(
                {
                    **category,
                    "text": text,
                    "method": "printed-bar-label-association",
                    "score": min(
                        [
                            category["score"],
                            *[value["score"] for value, label in pairs],
                            *[label["score"] for value, label in pairs],
                        ]
                    ),
                }
            )
            for value, _ in pairs:
                value["alternative"] = True
            category["alternative"] = True
    return [*records, *extra]
