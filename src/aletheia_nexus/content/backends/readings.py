"""Small, evidence-based cleanup of positioned OCR readings."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from aletheia_nexus.content.models import LayoutLine, PageLayout


def literal_reading_key(value: str) -> str:
    """Fold typography and spacing without flattening scientific scripts."""
    value = "".join(
        char
        if unicodedata.decomposition(char).startswith(("<super>", "<sub>"))
        else unicodedata.normalize("NFKC", char)
        for char in unicodedata.normalize("NFC", value)
    )
    return "".join(value.split()).replace("−", "-")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def recover_word_glyphs(native: LayoutLine, candidate: LayoutLine):
    """Fill an explicit missing letter glyph from a unique observed OCR word.

    Keep every surviving native letter, digit and unit. This does not use a
    vocabulary, repair numbers or accept the OCR's other spelling changes.
    The caller must establish matching line geometry and sufficient confidence.
    """
    changes = []
    pattern = re.compile(
        r"(?<![A-Za-z0-9])([A-Za-z]{2,})([\ue000-\uf8ff\ufffd\x00])([A-Za-z]{2,})(?![A-Za-z0-9])"
    )
    for match in pattern.finditer(native.text):
        printed = [
            span
            for span in native.glyph_spans
            if span[0] <= match.start(2) < span[1] and span[2] < span[3]
        ]
        if len(printed) != 1:
            continue
        observations = list(
            re.finditer(
                r"(?<![A-Za-z0-9])"
                + re.escape(match[1])
                + r"([A-Za-z]{1,3})"
                + re.escape(match[3])
                + r"(?![A-Za-z0-9])",
                candidate.text,
            )
        )
        if len(observations) != 1:
            continue
        changes.append((match.start(2), match.end(2), observations[0][1]))
    text = native.text
    for start, end, letters in reversed(changes):
        text = text[:start] + letters + text[end:]
    return text, changes


def _models(line: LayoutLine) -> set[str]:
    return {
        re.sub(r"\+(?:line|superscript)-retry$", "", engine)
        for engine in line.source_engines
    }


def _same_row(first: LayoutLine, second: LayoutLine) -> bool:
    intersection = max(0, min(first.y1, second.y1) - max(first.y0, second.y0))
    height = max(first.y1 - first.y0, second.y1 - second.y0)
    width = max(0, min(first.x1, second.x1) - max(first.x0, second.x0))
    return height > 0 and intersection / height >= 0.65 and width > 0


def corroborate_chinese(
    native: PageLayout, layouts: list[PageLayout]
) -> tuple[list[PageLayout], list[dict[str, object]]]:
    """Repair one Han glyph only when native and a separate OCR model agree.

    Require two unchanged Han neighbours on each side, unique in each reading,
    and matching line geometry. Never edit digits, signs, units or insert text.
    Compare immutable inputs so repairs cannot corroborate subsequent repairs.
    """
    warnings = []
    result = []
    for index, layout in enumerate(layouts):
        lines = []
        for line in layout.lines:
            positions = [i for i, c in enumerate(line.text) if not c.isspace()]
            text = _compact(line.text)
            if not re.search(r"[\u4e00-\u9fff]{5}", text):
                lines.append(line)
                continue
            native_rows = [r for r in native.lines if _same_row(line, r)]
            other_rows = [
                r
                for j, other in enumerate(layouts)
                if j != index
                for r in other.lines
                if _same_row(line, r)
                and r.extraction_confidence >= 0.8
                and r.source_engines
                and line.source_engines
                and not _models(r).intersection(_models(line))
                and r.content_region not in {"ocr-alternative", "native-alternative"}
            ]
            changes = []
            for offset in range(2, len(text) - 2):
                window = text[offset - 2 : offset + 3]
                if not re.fullmatch(r"[\u4e00-\u9fff]{5}", window):
                    continue
                if text.count(window) != 1:
                    continue
                pattern = re.compile(
                    re.escape(window[:2]) + r"([\u4e00-\u9fff])" + re.escape(window[3:])
                )

                def votes(rows):
                    values = set()
                    for row in rows:
                        matches = list(pattern.finditer(_compact(row.text)))
                        if len(matches) == 1:
                            values.add(matches[0].group(1))
                    return values

                native_votes, ocr_votes = votes(native_rows), votes(other_rows)
                if len(native_votes) != 1 or native_votes != ocr_votes:
                    continue
                corrected = next(iter(native_votes))
                if corrected != text[offset]:
                    changes.append((positions[offset], text[offset], corrected))
            if changes:
                characters = list(line.text)
                for offset, before, after in changes:
                    characters[offset] = after
                corrected_text = "".join(characters)
                # The original remains in the structured warning, without adding
                # a second review candidate for a corroborated spelling repair.
                warnings.append(
                    {
                        "code": "OCR_CJK_CORROBORATED",
                        "detail": f"page {native.page}: isolated Chinese glyph corrected using native text and a separate OCR reading",
                        "page": native.page,
                        "bbox": [line.x0, line.y0, line.x1, line.y1],
                        "before": line.text,
                        "after": corrected_text,
                        "source_engines": list(line.source_engines),
                        "corroborating_engines": sorted(
                            {
                                engine
                                for row in native_rows + other_rows
                                for engine in row.source_engines
                            }
                        ),
                        "native_readings": [r.text for r in native_rows],
                        "other_readings": [r.text for r in other_rows],
                    }
                )
                line = replace(line, text=corrected_text, uncertain=True)
            lines.append(line)
        result.append(replace(layout, lines=tuple(lines)))
    return result, warnings
