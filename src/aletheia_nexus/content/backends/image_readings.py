"""Reconcile source-image OCR variants without inventing digits or units."""

from __future__ import annotations

import colorsys
import re
import unicodedata
from collections import Counter

from aletheia_nexus.content.backends.readings import literal_reading_key


def reading_key(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("−", "-")


def merge_complete_reading(records, candidate):
    """Prefer a source reading that completes overlapping truncated fragments.

    Existing full, conflicting numbers or exponents are never overwritten.
    All displaced readings remain as alternatives in the same image region.
    """
    a = candidate["box"]
    key = literal_reading_key(candidate["text"])
    near = []
    for old in records:
        b = old["box"]
        overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
            0, min(a[3], b[3]) - max(a[1], b[1])
        )
        if not old.get("alternative") and overlap > 0.45 * min(
            (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
        ):
            near.append(old)
    if not near:
        return False
    if len(near) == 1 and literal_reading_key(near[0]["text"]) == key:
        return False
    # Removing ONLY new unit exponents allows an incomplete "12 h" reading
    # to match "12 h-1". A pre-existing exponent must match exactly.
    bare = re.sub(r"(?<=[A-Za-z])[+-]\d{1,2}", "", key)

    def raised_unit_fragment(old):
        # OCR may detect a raised signed exponent separately, losing its
        # typography in the fragment string. Require both the complete source
        # reading and the fragment's position beside an unchanged unit label.
        suffix = re.fullmatch(r"(.*[A-Za-z])([⁺⁻][⁰¹²³⁴⁵⁶⁷⁸⁹0-9]{1,2})", key)
        oldkey = literal_reading_key(old["text"])
        if (
            suffix is None
            or not re.fullmatch(r"[+-]\d{1,2}", oldkey)
            or oldkey != unicodedata.normalize("NFKC", suffix[2]).replace("−", "-")
        ):
            return False
        x0, y0, x1, y1 = old["box"]
        bases = [r for r in near if literal_reading_key(r["text"]) == suffix[1]]
        if len(bases) != 1:
            return False
        bx0, by0, bx1, by1 = bases[0]["box"]
        return (
            (x0 + x1) / 2 >= bx1
            and by0 <= (y0 + y1) / 2 < (by0 + by1) / 2
            and y0 < by0
            and y1 < by1
        )

    if not all(
        (oldkey := literal_reading_key(old["text"])) in key
        or (not re.search(r"(?<=[A-Za-z])[+-]\d", oldkey) and oldkey in bare)
        or raised_unit_fragment(old)
        for old in near
    ):
        return False
    for old in near:
        old["alternative"] = True
    colours = {old["ink_colour"] for old in near if old.get("ink_colour")}
    if len(colours) == 1:
        candidate["ink_colour"] = colours.pop()
    records.append(candidate)
    return True


def ink_colour(image, box):
    """Name only a dominant saturated ink colour on a light background."""
    x0, y0, x1, y1 = box
    # Detector rectangles can include parts of the neighbouring line. Use
    # the central band for hue, without extending into another text line.
    h = y1 - y0
    y0, y1 = y0 + h * 0.15, y1 - h * 0.15
    crop = image.crop(
        (
            max(0, int(x0)),
            max(0, int(y0)),
            min(image.width, int(x1) + 1),
            min(image.height, int(y1) + 1),
        )
    ).convert("RGB")
    if not crop.width or not crop.height:
        return None
    counts = Counter()
    ink = 0
    for r, g, b in crop.get_flattened_data():
        if min(r, g, b) > 215:
            continue
        ink += 1
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.6 or v < 0.35:
            continue
        h *= 360
        colour = (
            "red"
            if h < 15 or h >= 345
            else "orange"
            if h < 45
            else "yellow"
            if h < 75
            else "green"
            if h < 165
            else "cyan"
            if h < 195
            else "blue"
            if h < 265
            else "magenta"
        )
        counts[colour] += 1
    if not counts:
        return None
    name, count = counts.most_common(1)[0]
    # Anti-aliased glyph edges are often grey. The hue must dominate the
    # saturated ink, while most of the crop must still be light background;
    # otherwise this would name a heatmap background as its text colour.
    light = sum(crop.convert("L").histogram()[216:]) / (crop.width * crop.height)
    return (
        name
        if light > 0.6
        and count >= 8
        and count > sum(counts.values()) * 0.85
        and count > ink * 0.3
        else None
    )


def complete_edge_scripts(records, image, recognize):
    """Recover a clipped terminal unit exponent or formula subscript.

    Two different source crops must give the same complete reading. Existing
    characters, digits and units cannot change. No dictionary is consulted.
    """
    for old in list(records):
        key = reading_key(old["text"])
        unit = bool(re.fullmatch(r"\d+(?:\.\d+)?[A-Za-z]{1,3}", key))
        formula = bool(re.fullmatch(r"(?:[A-Z][a-z]?[0-9]*[/()]?){3,}", key))
        if old.get("alternative") or old["score"] < 0.85 or not (unit or formula):
            continue
        x0, y0, x1, y1 = old["box"]
        h = y1 - y0
        if x1 - x0 < h * 2 or h <= 0:
            continue
        readings = []
        for pad in (0.15, 0.3):
            box = (
                max(0, int(x0 - h * pad)),
                max(0, int(y0 - h * 0.05)),
                min(image.width, int(x1 + h * 0.4)),
                min(image.height, int(y1 + h * 0.2)),
            )
            result = recognize(image.crop(box))
            if result is None:
                break
            text, score = result
            new = reading_key(text)
            suffix = new[len(key) :] if new.startswith(key) else ""
            if score < 0.9 or not re.fullmatch(
                r"[+-]\d{1,2}" if unit else r"\d{1,2}", suffix
            ):
                break
            readings.append(
                dict(
                    text=text, score=score, box=box, method="rapidocr-edge-script-crop"
                )
            )
        if len(readings) == 2 and reading_key(readings[0]["text"]) == reading_key(
            readings[1]["text"]
        ):
            merge_complete_reading(records, readings[0])
    return records


def normalize_formula_scripts(text):
    """Normalize OCR markup only when it surrounds printed formula digits."""
    key = reading_key(text)
    if not any(c in key for c in "_{}"):
        return None
    for i, c in enumerate(key):
        if c in "_{}" and not (
            (i > 0 and key[i - 1].isdigit())
            or (i + 1 < len(key) and key[i + 1].isdigit())
        ):
            return None
    clean = re.sub(r"[_{}]", "", key)
    if re.fullmatch(r"(?:[A-Z][a-z]?\d*[/()]?){2,}", clean) and re.search(r"\d", clean):
        return clean
    return None


def reread_formula_markup(records, image, recognize):
    """Resolve low-scoring OCR script markup only with matching source crops."""
    from PIL import ImageOps

    for old in list(records):
        key = normalize_formula_scripts(old["text"])
        if old.get("alternative") or key is None or old["score"] < 0.65:
            continue
        x0, y0, x1, y1 = old["box"]
        h = y1 - y0
        box = (
            max(0, int(x0 - h * 0.15)),
            max(0, int(y0)),
            min(image.width, int(x1 + h * 0.2)),
            min(image.height, int(y1)),
        )
        crop = image.crop(box).convert("RGB")
        grey = crop.convert("L")
        runs = []
        for y in range(grey.height):
            if (
                sum(
                    v < 170
                    for v in grey.crop((0, y, grey.width, y + 1)).get_flattened_data()
                )
                >= 2
            ):
                if not runs or runs[-1][-1] < y - 1:
                    runs.append([])
                runs[-1].append(y)
        if not runs:
            continue
        band = max(runs, key=len)
        scores = []
        for factor in (1, 2):
            tight = ImageOps.expand(
                crop.crop(
                    (0, max(0, band[0] - 1), crop.width, min(crop.height, band[-1] + 2))
                ),
                10,
                "white",
            )
            result = recognize(
                tight.resize((tight.width * factor, tight.height * factor))
            )
            if (
                result is None
                or result[1] < 0.65
                or (normalize_formula_scripts(result[0]) or reading_key(result[0]))
                != key
            ):
                break
            scores.append(result[1])
        if len(scores) == 2:
            old["alternative"] = True
            records.append(
                dict(
                    text=key,
                    box=old["box"],
                    score=min(old["score"], *scores),
                    method="rapidocr-corroborated-formula-script",
                )
            )
    return records


def reread_uncertain_lines(records, image, recognize):
    """Reread a padded source crop at two scales, keeping the raw reading.

    High-confidence numbers may not change. The only such edits allowed are
    OCR script punctuation and I/l/1 confusions, independently reread from ink.
    """
    from PIL import ImageOps

    from aletheia_nexus.content.backends.image_panels import length_key

    def comparable(text):
        key = re.sub(r"(?<=\d)[_{}]|[_{}](?=\d)", "", reading_key(text))
        return re.sub(r"(?<=[A-Za-z])[Il1](?=[A-Za-z%])", "|", key)

    for old in list(records):
        text = old["text"]
        if (
            old.get("alternative")
            or not 0.5 <= old["score"] < 0.94
            or not re.search(r"\d", text)
            or sum(c.isalpha() for c in text) < 2
        ):
            continue
        x0, y0, x1, y1 = old["box"]
        h = y1 - y0
        if h <= 0 or x1 - x0 < h * 2:
            continue
        candidates = []
        scale_conflicts = []
        original_length = length_key(text)
        for vertical_pad in (0, 0.05):
            box = (
                max(0, int(x0 - h * 0.2)),
                max(0, int(y0 - h * vertical_pad)),
                min(image.width, int(x1 + h * 0.2)),
                min(image.height, int(y1 + h * vertical_pad)),
            )
            crop = ImageOps.expand(image.crop(box).convert("RGB"), 12, "white")
            readings = []
            for scale in (1, 2):
                result = recognize(
                    crop
                    if scale == 1
                    else crop.resize((crop.width * scale, crop.height * scale))
                )
                if result is None or result[1] < (0.9 if original_length else 0.95):
                    break
                readings.append(result)
            if len(readings) == 2 and reading_key(readings[0][0]) == reading_key(
                readings[1][0]
            ):
                new, score = readings[0][0], min(r[1] for r in readings)
                new_length = length_key(new)
                if (
                    original_length
                    and new_length
                    and original_length[0] == new_length[0]
                    and original_length[1] != new_length[1]
                ):
                    # Two crop resolutions support a substantive unit alternative,
                    # even when they cannot justify replacing the main reading.
                    scale_conflicts.append((new, score))
                if (
                    score >= 0.95
                    and reading_key(new) != reading_key(text)
                    and score >= old["score"] + 0.03
                ):
                    candidates.append((new, score))
        candidate = (
            max(candidates, key=lambda r: r[1])
            if len({reading_key(r[0]) for r in candidates}) == 1
            else None
        )
        if candidate is None or (
            old["score"] >= 0.85 and comparable(candidate[0]) != comparable(text)
        ):
            for new, score in scale_conflicts:
                if any(
                    reading_key(r["text"]) == reading_key(new)
                    and r["box"] == old["box"]
                    for r in records
                ):
                    continue
                records.append(
                    dict(
                        text=new,
                        score=score,
                        box=old["box"],
                        alternative=True,
                        method="rapidocr-scale-unit-alternative",
                        warning="IMAGE_SCALE_UNIT_CONFLICT",
                    )
                )
            continue
        new, score = candidate
        old["alternative"] = True
        records.append(
            dict(
                text=new,
                score=score,
                box=old["box"],
                method="rapidocr-corroborated-line-crop",
            )
        )
    return records
