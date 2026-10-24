"""Reread fragmented vertical image labels as one horizontal crop."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from aletheia_nexus.content.backends.readings import literal_reading_key


def _literal_label(text):
    # Reference-operator case is typography; unit and material case is not.
    return literal_reading_key(re.sub(r"\bvs\b", "vs", text, flags=re.IGNORECASE))


def _preserves_fragments(reading, fragments):
    """A crop must not drop observed unit, sign or label characters."""

    def key(text):
        # The reference operator VS/vs is case-insensitive. Unit and material
        # spellings remain exact: mV/MV and Cl/CI must still disagree.
        return "".join(
            c
            for c in _literal_label(text)
            if c.isalnum()
            or c in "+-/±%°.·×"
            or unicodedata.decomposition(c).startswith(("<super>", "<sub>"))
        )

    candidate = key(reading)
    for order in (fragments, fragments[::-1]):
        remaining = iter(candidate)
        if all(c in remaining for c in key(" ".join(order))):
            return True
    return False


def read_vertical_labels(records, image, read):
    from PIL import ImageOps

    def text_key(text):
        return re.sub(r"\W", "", text).casefold()

    candidates = [
        r
        for r in records
        if not r.get("alternative") and re.search(r"[A-Za-z]", r["text"])
    ]
    used = set()
    extra = []
    for seed in candidates:
        x0, y0, x1, y1 = seed["box"]
        w = x1 - x0
        if (
            id(seed) in used
            or y1 - y0 < w * 1.25
            or not (x1 < image.width * 0.15 or x0 > image.width * 0.85)
        ):
            continue
        group = [seed]
        for _ in range(len(candidates)):
            near = [
                r
                for r in candidates
                if r not in group
                and abs(sum(r["box"][::2]) - x0 - x1) / 2 < w * 0.6
                and max(0, r["box"][1] - y1, y0 - r["box"][3]) < w * 0.7
            ]
            if not near:
                break
            group.extend(near)
            x0 = min(r["box"][0] for r in group)
            x1 = max(r["box"][2] for r in group)
            y0 = min(r["box"][1] for r in group)
            y1 = max(r["box"][3] for r in group)
        crop = image.crop(
            (
                max(0, int(x0 - w * 0.12)),
                max(0, int(y0 - w * 0.12)),
                min(image.width, int(x1 + w * 0.12) + 1),
                min(image.height, int(y1 + w * 0.12) + 1),
            )
        )
        readings = []
        for angle in (90, 270):
            rotated = ImageOps.expand(
                crop.rotate(angle, expand=True), max(8, round(w * 0.15)), "white"
            )
            readings.extend(
                r
                for r in read(rotated)
                if r["score"] >= 0.9 and len(text_key(r["text"])) >= 2
            )
        if not readings:
            continue
        best = max(readings, key=lambda r: len(text_key(r["text"])) * r["score"])
        ordered = sorted(group, key=lambda r: r["box"][1])
        if not _preserves_fragments(best["text"], [r["text"] for r in ordered]):
            continue
        keys = [
            text_key(" ".join(r["text"] for r in order))
            for order in (ordered, ordered[::-1])
        ]
        if (
            max(
                SequenceMatcher(None, text_key(best["text"]), key).ratio()
                for key in keys
            )
            < 0.65
        ):
            continue
        # Competing complete readings with different text stay unresolved.
        if any(
            len(text_key(r["text"])) >= len(text_key(best["text"])) * 0.9
            and _literal_label(r["text"]) != _literal_label(best["text"])
            for r in readings
        ):
            continue
        extra.append(
            dict(
                text=best["text"],
                score=best["score"],
                box=(x0, y0, x1, y1),
                method="rapidocr-vertical-label-crop",
            )
        )
        for r in group:
            r["alternative"] = True
            used.add(id(r))
    return [*records, *extra]
