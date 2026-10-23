"""Conservative spatial grouping of printed scale labels in figure panels."""

from __future__ import annotations

import re
from decimal import Decimal

_LENGTH = re.compile(r"^(\d+(?:\.\d+)?)\s*[-–]?\s*([uμµnpmc]?m)$")


def length_key(text):
    match = _LENGTH.fullmatch(text.strip())
    return (
        (Decimal(match[1]), match[2].replace("µ", "μ").replace("um", "μm"))
        if match
        else None
    )


def join_length_fragments(records):
    """Rejoin an OCR number and unit on the same baseline with a small gap."""
    extra = []
    for number in records:
        if number.get("alternative") or not re.fullmatch(
            r"\d+(?:\.\d+)?", number["text"]
        ):
            continue
        x0, y0, x1, y1 = number["box"]
        nearby = []
        for unit in records:
            a, b, c, d = unit["box"]
            height = min(y1 - y0, d - b)
            if (
                not unit.get("alternative")
                and re.fullmatch(r"[uμµnpmc]?m", unit["text"])
                and -height * 0.15 <= a - x1 <= height * 0.8
                and abs((b + d - y0 - y1) / 2) <= height * 0.3
            ):
                nearby.append(unit)
        if len(nearby) != 1:
            continue
        unit = nearby[0]
        extra.append(
            dict(
                text=number["text"] + " " + unit["text"],
                score=min(number["score"], unit["score"]),
                box=(
                    x0,
                    min(y0, unit["box"][1]),
                    unit["box"][2],
                    max(y1, unit["box"][3]),
                ),
                method="positioned-length-fragments",
            )
        )
        number["alternative"] = unit["alternative"] = True
    return [*records, *extra]


def _runs(bits):
    start = None
    for i, bit in enumerate([*bits, False]):
        if bit and start is None:
            start = i
        elif not bit and start is not None:
            yield start, i
            start = None


def panel_boxes(image, box=None, depth=0):
    """Split only narrow white gutters that cross the complete image region."""
    box = box or (0, 0, image.width, image.height)
    crop = image.crop(box).convert("L")
    w, h = crop.size
    if depth >= 5:
        return [box]
    for axis, n, other in ((0, w, h), (1, h, w)):
        if n < 180:
            continue
        bits = []
        for i in range(n):
            band = crop.crop((i, 0, i + 1, h) if axis == 0 else (0, i, w, i + 1))
            bits.append(sum(band.histogram()[245:]) > other * 0.95)
        gaps = [
            (a, b)
            for a, b in _runs(bits)
            if a > n * 0.1 and b < n * 0.9 and 2 <= b - a <= n * 0.03
        ]
        if not gaps:
            continue
        a, b = min(gaps, key=lambda g: abs(sum(g) / 2 - n / 2))
        children = (
            [(box[0], box[1], box[0] + a, box[3]), (box[0] + b, box[1], box[2], box[3])]
            if axis == 0
            else [
                (box[0], box[1], box[2], box[1] + a),
                (box[0], box[1] + b, box[2], box[3]),
            ]
        )
        return [p for child in children for p in panel_boxes(image, child, depth + 1)]
    return [box]


def read_panel_markers(records, image, recognize):
    """Read missing corner labels inside already separated, scaled panels.

    The observed gutters and scale bar trigger a small source crop. Two
    resolutions must agree at high confidence. No alphabet/order completion
    is allowed, and an existing conflicting reading is never overwritten.
    """
    from PIL import ImageOps

    boxes = panel_boxes(image)
    if len(boxes) < 2:
        return records
    for x0, y0, x1, y1 in boxes:
        w, h = x1 - x0, y1 - y0
        if min(w, h) < 80:
            continue
        members = [
            r
            for r in records
            if not r.get("alternative")
            and x0 <= (r["box"][0] + r["box"][2]) / 2 < x1
            and y0 <= (r["box"][1] + r["box"][3]) / 2 < y1
        ]
        if not any(length_key(r["text"]) for r in members):
            continue
        corner = (x0, y0, x0 + w * 0.32, y0 + h * 0.28)
        nearby = [
            r for r in members if r["box"][0] < corner[2] and r["box"][1] < corner[3]
        ]
        if any(
            re.fullmatch(r"[A-Za-z][).]?", r["text"]) and r["score"] >= 0.9
            for r in nearby
        ):
            continue
        crop = image.crop(corner)
        readings = [
            recognize(
                ImageOps.expand(
                    crop.resize((crop.width * scale, crop.height * scale)),
                    border=8,
                    fill="white",
                )
            )
            for scale in (1, 2)
        ]
        if not all(r and r[1] >= 0.9 for r in readings):
            continue
        text = readings[0][0].strip()
        if text != readings[1][0].strip() or not re.fullmatch(r"[A-Za-z][).]?", text):
            continue
        conflicts = [r for r in nearby if r["text"].rstrip(").") != text.rstrip(").")]
        if conflicts:
            # A complete printed marker with its delimiter may resolve an
            # unreliable fragment. Keep that fragment as an alternative.
            if not text.endswith((")", ".")) or any(
                r["score"] >= 0.85 for r in conflicts
            ):
                continue
            for old in conflicts:
                old["alternative"] = True
        records.append(
            dict(
                text=text,
                score=min(r[1] for r in readings),
                box=corner,
                method="rapidocr-panel-corner-reading",
            )
        )
    return records


def associate_scales(records, image):
    """Attach observed scale readings to observed panels, without guessing labels.

    Missing panel letters use explicit row/column locations. Different printed
    scales within the same panel remain separate; no majority vote is used.
    """
    boxes = panel_boxes(image)
    markers = [
        r
        for r in records
        if re.fullmatch(r"[A-Za-z][).]?", r["text"])
        and r["score"] >= 0.9
        and not r.get("alternative")
    ]
    if len(boxes) == 1:
        # Some mosaics have touching panels. Aligned, evenly spaced markers
        # establish columns only when all share the same within-column offset.
        top = sorted(
            [r for r in markers if r["box"][3] < image.height * 0.2],
            key=lambda r: r["box"][0],
        )
        if 2 <= len(top) <= 6:
            step = image.width / len(top)
            offsets = [
                (r["box"][0] + r["box"][2]) / 2 - i * step for i, r in enumerate(top)
            ]
            if max(offsets) - min(offsets) < step * 0.08:
                boxes = [
                    (i * step, 0, (i + 1) * step, image.height) for i in range(len(top))
                ]
                # A complete rectangular arrangement of printed markers can
                # also establish touching rows. Never invent absent markers.
                columns = [
                    [
                        r
                        for r in markers
                        if i * step <= (r["box"][0] + r["box"][2]) / 2 < (i + 1) * step
                    ]
                    for i in range(len(top))
                ]
                count = len(columns[0])
                if 2 <= count <= 6 and all(len(c) == count for c in columns):
                    row_step = image.height / count
                    offsets_y = [
                        (r["box"][1] + r["box"][3]) / 2 - j * row_step
                        for column in columns
                        for j, r in enumerate(sorted(column, key=lambda r: r["box"][1]))
                    ]
                    if max(offsets_y) - min(offsets_y) < row_step * 0.08:
                        boxes = [
                            (i * step, j * row_step, (i + 1) * step, (j + 1) * row_step)
                            for j in range(count)
                            for i in range(len(top))
                        ]
    if len(boxes) < 2:
        return records

    def grid_index(value, axis):
        tolerance = min(b[axis + 2] - b[axis] for b in boxes) * 0.15
        positions = []
        for position in sorted(b[axis] for b in boxes):
            if not positions or position - positions[-1] > tolerance:
                positions.append(position)
        return 1 + min(range(len(positions)), key=lambda i: abs(positions[i] - value))

    extra = []
    for box in boxes:
        x0, y0, x1, y1 = box

        def inside(r):
            return (
                x0 <= (r["box"][0] + r["box"][2]) / 2 < x1
                and y0 <= (r["box"][1] + r["box"][3]) / 2 < y1
            )

        lengths = [
            r
            for r in records
            if inside(r) and length_key(r["text"]) and not r.get("alternative")
        ]
        if not lengths:
            continue
        if len({length_key(r["text"]) for r in lengths}) != 1:
            # Unequal stacked panels can share a column beside a plot, whose
            # axis interrupts a white gutter. Printed, aligned panel letters
            # above the scale establish this relationship without equal cells.
            local_markers = [r for r in markers if inside(r)]
            assigned = []
            for reading in lengths:
                above = [
                    r
                    for r in local_markers
                    if r["box"][0] <= reading["box"][0]
                    and r["box"][3] < reading["box"][1]
                ]
                if not above:
                    break
                left = max(r["box"][0] for r in above)
                column = [
                    r
                    for r in above
                    if left - r["box"][0] < max(r["box"][2] - r["box"][0], 1) * 2
                ]
                marker = max(column, key=lambda r: r["box"][3])
                assigned.append((reading, marker))
            if len(assigned) == len(lengths) and len(
                {id(m) for _, m in assigned}
            ) == len(lengths):
                for reading, marker in assigned:
                    extra.append(
                        {
                            **reading,
                            "text": f"Panel ({marker['text'].rstrip(').')}): scale {reading['text']}",
                            "method": "positioned-panel-scale",
                        }
                    )
                    reading["alternative"] = True
            continue
        labels = [
            r
            for r in markers
            if inside(r) and (r["box"][1] + r["box"][3]) / 2 < y0 + (y1 - y0) * 0.28
        ]
        if len(labels) == 1:
            label = labels[0]["text"].rstrip(").")
        else:
            row = grid_index(y0, 1)
            col = grid_index(x0, 0)
            label = f"row {row}, column {col}"
        best = max(lengths, key=lambda r: r["score"])
        extra.append(
            {
                **best,
                "text": f"Panel ({label}): scale {best['text']}",
                "method": "positioned-panel-scale",
            }
        )
        for reading in lengths:
            reading["alternative"] = True
    return [*records, *extra]
