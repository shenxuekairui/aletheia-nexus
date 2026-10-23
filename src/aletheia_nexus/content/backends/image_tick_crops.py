"""Recover printed chart-margin digits lost in whole-image downsampling."""

from __future__ import annotations

import re

from aletheia_nexus.content.backends.image_readings import reading_key


def read_tick_margins(records, image, read, recognize):
    from PIL import ImageOps

    numeric = re.compile(r"[+−-]?\d+(?:\.\d+)?")
    if (
        max(image.size) < 1800
        or sum(bool(numeric.fullmatch(r["text"])) for r in records) < 6
    ):
        return records
    w, h = image.size
    bottom_ticks = [
        r for r in records if numeric.fullmatch(r["text"]) and r["box"][1] > h * 0.75
    ]
    bottom = min((r["box"][1] for r in bottom_ticks), default=h * 0.86)
    # Use the lowest text row, excluding the zero at the plot origin.
    bottom_rows = []
    for r in sorted(bottom_ticks, key=lambda r: r["box"][1]):
        row = next(
            (
                row
                for row in bottom_rows
                if abs(row[0]["box"][1] - r["box"][1])
                < (r["box"][3] - r["box"][1]) * 0.6
            ),
            None,
        )
        if row is None:
            bottom_rows.append([r])
        else:
            row.append(r)
    rows = [row for row in bottom_rows if len(row) >= 3]
    if rows:
        row = max(rows, key=lambda row: row[0]["box"][1])
        bottom = (
            min(r["box"][1] for r in row)
            - min(r["box"][3] - r["box"][1] for r in row) * 0.15
        )
    bands = [(0, int(bottom), w, h), (0, 0, int(w * 0.18), h), (int(w * 0.82), 0, w, h)]
    # An observed tick column supplies a tighter strip, separating a neighbouring
    # panel letter or axis stroke without assuming the values of missing ticks.
    for left, right in [(0, w * 0.2), (w * 0.8, w)]:
        column = [
            r
            for r in records
            if r["score"] >= 0.95
            and numeric.fullmatch(r["text"])
            and left <= (r["box"][0] + r["box"][2]) / 2 <= right
            and r["box"][3] < bottom
        ]
        if len(column) >= 3:
            pad = min(r["box"][3] - r["box"][1] for r in column) * 0.1
            bands.append(
                (
                    max(0, int(min(r["box"][0] for r in column) - pad)),
                    0,
                    min(w, int(max(r["box"][2] for r in column) + pad)),
                    h,
                )
            )
    for box in bands:
        crop = image.crop(box)
        passes = []
        for scale in (0.5, 0.6):
            resized = crop.resize((int(crop.width * scale), int(crop.height * scale)))
            rows = []
            for r in read(resized):
                if r["score"] < 0.95 or not numeric.fullmatch(r["text"]):
                    continue
                a, b, c, d = r["box"]
                if c - a < 0.25 * (d - b) * sum(ch.isdigit() for ch in r["text"]):
                    continue
                rows.append(
                    {
                        **r,
                        "box": (
                            box[0] + a / scale,
                            box[1] + b / scale,
                            box[0] + c / scale,
                            box[1] + d / scale,
                        ),
                    }
                )
            passes.append(rows)

        def overlaps(a, b):
            return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(
                a[3], b[3]
            )

        for candidate in passes[0]:
            corroborated = any(
                reading_key(r["text"]) == reading_key(candidate["text"])
                and overlaps(r["box"], candidate["box"])
                for r in passes[1]
            )
            if not corroborated:
                a, b, c, d = candidate["box"]
                pad = (d - b) * 0.15
                tight = ImageOps.expand(
                    image.crop(
                        (
                            max(0, int(a - pad)),
                            max(0, int(b - pad)),
                            min(w, int(c + pad)),
                            min(h, int(d + pad)),
                        )
                    ).convert("RGB"),
                    12,
                    "white",
                )
                check = recognize(tight)
                if (
                    check is None
                    or check[1] < 0.95
                    or reading_key(check[0]) != reading_key(candidate["text"])
                ):
                    continue
            near = [
                r
                for r in records
                if not r.get("alternative")
                and r["score"] >= 0.85
                and overlaps(r["box"], candidate["box"])
            ]
            if any(
                reading_key(r["text"]) == reading_key(candidate["text"]) for r in near
            ):
                continue
            # Crop boundaries separate digits from axis strokes and panel labels.
            # A different existing number is a conflict, never a correction.
            digits = re.findall(r"\d+(?:\.\d+)?", candidate["text"])
            if any(re.findall(r"\d+(?:\.\d+)?", r["text"]) != digits for r in near):
                continue
            if any(not numeric.fullmatch(r["text"]) for r in near):
                # A margin crop may omit a printed inequality, unit, footnote
                # or surrounding label. Agreement on its digits cannot replace
                # the fuller source reading (tables also have numeric margins).
                # Keep the crop as a partial alternative, including its box.
                if not any(
                    reading_key(r["text"]) == reading_key(candidate["text"])
                    and overlaps(r["box"], candidate["box"])
                    for r in records
                ):
                    records.append(
                        {
                            **candidate,
                            "alternative": True,
                            "method": "rapidocr-corroborated-tick-crop",
                        }
                    )
                continue
            if any(
                numeric.fullmatch(r["text"])
                and reading_key(r["text"]).startswith(("+", "-"))
                and reading_key(r["text"]) != reading_key(candidate["text"])
                for r in near
            ):
                continue
            for r in near:
                r["alternative"] = True
            records.append({**candidate, "method": "rapidocr-corroborated-tick-crop"})
    return records
