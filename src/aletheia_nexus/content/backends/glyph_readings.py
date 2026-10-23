"""Decode painted symbol glyphs independently of defective PDF character maps.

Only simple geometric symbols and verified unit shapes are recovered here.
Readings carry the original character code; no paper vocabulary is consulted.
"""

from __future__ import annotations

import io

from fontTools.agl import toUnicode
from fontTools.cffLib import CFFFontSet
from fontTools.pens.qu2cuPen import Qu2CuPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from pdfminer.cmapdb import CMapParser, FileUnicodeMap
from pdfminer.encodingdb import EncodingDB

from aletheia_nexus.content.backends.font_symbols import (
    _ink_intervals,
    _mapped_m_outline,
    _outline_symbol,
    _OutlineContours,
    _type1_font,
)


def geometric_reading(operations, units):
    """Read a ring or angular comparison/cross by its ink topology."""
    if not operations or operations[-1][0] != "closePath":
        return None
    if value := _outline_symbol(operations, units):
        return value
    if value := _mapped_m_outline(operations, units):
        return value
    pen = _OutlineContours()
    for op, points in operations:
        if op not in {"moveTo", "lineTo", "curveTo", "qCurveTo", "closePath"}:
            return None
        getattr(pen, op)(*points)
    cs = [[(x / units, y / units) for x, y in c] for c in pen.contours]
    if not cs or any(len(c) < 3 for c in cs):
        return None

    def bounds(contours):
        ps = [p for c in contours for p in c]
        return (
            min(x for x, y in ps),
            min(y for x, y in ps),
            max(x for x, y in ps),
            max(y for x, y in ps),
        )

    x0, y0, x1, y1 = bounds(cs)
    w, h = x1 - x0, y1 - y0
    if len(cs) == 2 and 0.4 < w < 1.2 and 0.4 < h < 1.2 and 0.7 < w / h < 1.5:
        slices = [_ink_intervals(cs, y0 + h * t) for t in (0.2, 0.5, 0.8)]
        if all(len(s) == 2 for s in slices):
            widths = [s[-1][1] - s[0][0] for s in slices]
            centers = [(s[-1][1] + s[0][0]) / 2 for s in slices]
            if all(abs(c - (x0 + x1) / 2) < w * 0.03 for c in centers) and all(
                abs(a - b) < w * 0.04
                for a, b in zip(widths, [w * 0.8, w * 0.5, w * 0.2])
            ):
                return "△"
            outer = max(cs, key=lambda c: bounds([c])[2] - bounds([c])[0])
            if (
                abs(w - h) < max(w, h) * 0.04
                and all(abs(v - w) < w * 0.02 for v in widths)
                and all(
                    min(abs(x - x0), abs(x - x1), abs(y - y0), abs(y - y1)) < 0.01
                    for x, y in outer
                )
            ):
                return "□"
    if len(cs) == 1 and 0.3 < w < 1 and 0.35 < h < 1 and 0.7 < w / h < 1.5:
        low, middle, high = [_ink_intervals(cs, y0 + h * t) for t in (0.2, 0.5, 0.8)]
        if all(len(s) == 1 for s in (low, middle, high)):
            if middle[0][1] - middle[0][0] > w * 0.9 and all(
                s[0][1] - s[0][0] < w * 0.2
                and abs(sum(s[0]) / 2 - (x0 + x1) / 2) < w * 0.1
                for s in (low, high)
            ):
                return "+"
    if len(cs) == 2 and 0.3 < w < 1 and 0.12 < h < 0.5:
        bars = sorted((bounds([c]) for c in cs), key=lambda b: b[1])
        if (
            all(
                all(
                    len(s := _ink_intervals([c], b[1] + (b[3] - b[1]) * t)) == 1
                    and s[0][1] - s[0][0] > w * 0.9
                    for t in (0.25, 0.5, 0.75)
                )
                for c in cs
                for b in [bounds([c])]
            )
            and all(b[2] - b[0] > w * 0.95 and 0 < b[3] - b[1] < h * 0.3 for b in bars)
            and bars[1][1] - bars[0][3] > h * 0.25
        ):
            return "="
    if len(cs) == 2 and 0.35 < w < 0.8 and 0.35 < h < 0.7 and y0 > -0.05:
        # An open upper-right diagonal crossing a left counter and curling
        # back at the lower right. This excludes closed a/d counters with an
        # upright right stem. Used only for unmapped symbols by the caller.
        lower = _ink_intervals(cs, y0 + h * 0.25)
        middle = _ink_intervals(cs, y0 + h * 0.5)
        upper = _ink_intervals(cs, y0 + h * 0.85)
        if (
            len(lower) >= 3
            and len(middle) == len(upper) == 2
            and upper[0][1] - upper[0][0] > w * 0.25
            and upper[1][0] > x0 + w * 0.7
            and upper[1][0] - middle[1][0] > w * 0.12
            and middle[0][1] < x0 + w * 0.2
            and x0 + w * 0.4 < middle[1][0] < x0 + w * 0.7
            and lower[-1][0] > x0 + w * 0.8
        ):
            return "α"
    # A polygonized mu has the same two open stems and left descender as a
    # curved mu. Test its ink, so font outline storage does not change units.
    if len(cs) == 1 and 0.3 < w < 0.8 and -0.3 < y0 < -0.08 and 0.3 < y1 < 0.65:
        upper = [_ink_intervals(cs, y1 * t) for t in (0.4, 0.65, 0.85)]
        below = _ink_intervals(cs, y0 * 0.5)
        low = [
            interval
            for t in (0.02, 0.05, 0.1)
            for interval in _ink_intervals(cs, y1 * t)
        ]
        if (
            all(len(s) == 2 for s in upper)
            and len(below) == 1
            and below[0][1] < x0 + w * 0.35
            and all(b - a < w * 0.3 for s in upper for a, b in s)
            and all(
                abs(a - b) < w * 0.12
                for s in upper[1:]
                for pair, base in zip(s, upper[0])
                for a, b in zip(pair, base)
            )
            and any(a < x0 + w * 0.3 and b > x0 + w * 0.55 for a, b in low)
        ):
            return "μ"
    if len(cs) == 2 and 0.15 < w < 0.45 and abs(w - h) < 0.02:
        a, b = sorted(
            (bounds([c]) for c in cs), key=lambda b: b[2] - b[0], reverse=True
        )
        if (
            a[0] < b[0] < b[2] < a[2]
            and a[1] < b[1] < b[3] < a[3]
            and abs(a[0] + a[2] - b[0] - b[2]) < 0.02
            and abs(a[1] + a[3] - b[1] - b[3]) < 0.02
            and all(len(_ink_intervals(cs, y0 + h * t)) == 2 for t in (0.35, 0.5, 0.65))
            and _ink_intervals(cs, y0 + h * 0.2)[-1][1]
            - _ink_intervals(cs, y0 + h * 0.2)[0][0]
            < w * 0.9
        ):
            return "°" if y0 > 0.35 else "∘"
    # Cross-sections describe the painted operator, including rounded stroke
    # ends. A PDF writer may encode those end caps with cubic curves.
    if not (0.3 < w < 1 and 0.25 < h < 0.95):
        return None
    bar = []
    body = []
    for c in cs:
        a, b, d, e = bounds([c])
        (
            bar if d - a > w * 0.75 and e - b < h * 0.18 and e < y0 + h * 0.3 else body
        ).append(c)
    if not body:
        return None
    bx, by, ex, ey = bounds(body)
    bw, bh = ex - bx, ey - by
    sections = [_ink_intervals(body, by + bh * t) for t in (0.15, 0.3, 0.5, 0.7, 0.85)]
    if all(len(s) == 1 for s in sections):
        centers = [(s[0][0] + s[0][1]) / 2 for s in sections]
        thickness = max(b - a for s in sections for a, b in s)
        if (
            thickness < bw * 0.38
            and abs(centers[0] - centers[-1]) < bw * 0.12
            and abs(centers[1] - centers[-2]) < bw * 0.12
        ):
            if (
                centers[2] - centers[0] > bw * 0.5
                and centers[2] - centers[1] > bw * 0.2
            ):
                return "≥" if len(bar) == 1 else (">" if not bar else None)
            if (
                centers[0] - centers[2] > bw * 0.5
                and centers[1] - centers[2] > bw * 0.2
            ):
                return "≤" if len(bar) == 1 else ("<" if not bar else None)
    if not bar and len(cs) == 1 and 0.7 < w / h < 1.5:
        low, mid, high = sections[0], sections[2], sections[-1]
        if (
            len(low) == len(high) == 2
            and len(mid) == 1
            and mid[0][1] - mid[0][0] < w * 0.4
        ):
            if (
                all(
                    abs(a - b) < w * 0.1
                    for u, v in zip(low, high)
                    for a, b in zip(u, v)
                )
                and all(b - a < w * 0.25 for a, b in [*low, *high])
                and abs(sum(mid[0]) / 2 - (x0 + x1) / 2) < w * 0.1
            ):
                return "×"
    return None


def encoded_glyph_readings(page):
    """Map (font, character code) to a shape-proven reading.

    Codes, rather than decoded strings, distinguish two glyphs incorrectly
    mapped to the same character. Explicit source mappings are retained in the
    correction record by the layout aggregator.
    """
    result = {}
    program_readings = {}
    seen = set()

    def fonts(resources):
        for ref in resources.get("/Font", {}).values():
            f = ref.get_object()
            if id(f) not in seen:
                seen.add(id(f))
                yield f
        for ref in resources.get("/XObject", {}).values():
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Form" and id(obj) not in seen:
                seen.add(id(obj))
                yield from fonts(obj.get("/Resources", {}))

    for font in fonts(page.get("/Resources", {})):
        try:
            name = str(font["/BaseFont"]).lstrip("/")
            if font.get("/Subtype") == "/Type0":
                descendant = font["/DescendantFonts"][0].get_object()
                program = TTFont(
                    io.BytesIO(descendant["/FontDescriptor"]["/FontFile2"].get_data())
                )
                cmap = FileUnicodeMap()
                CMapParser(cmap, io.BytesIO(font["/ToUnicode"].get_data())).run()
                mapping = descendant.get("/CIDToGIDMap", "/Identity")
                data = mapping.get_data() if hasattr(mapping, "get_data") else None
                glyph_order = program.getGlyphOrder()
                glyphs = program.getGlyphSet()
                units = program["head"].unitsPerEm
                names = {
                    cid: glyph_order[
                        int.from_bytes(data[cid * 2 : cid * 2 + 2], "big")
                        if data is not None
                        else cid
                    ]
                    for cid in cmap.cid2unichr
                    if (data is None or cid * 2 + 2 <= len(data))
                    and (
                        int.from_bytes(data[cid * 2 : cid * 2 + 2], "big")
                        if data is not None
                        else cid
                    )
                    < len(glyph_order)
                }
                quadratic = True
            elif font.get("/Subtype") == "/Type1":
                descriptor = font["/FontDescriptor"]
                quadratic = False
                if "/FontFile" in descriptor:
                    glyphs, matrix, encoding = _type1_font(
                        descriptor["/FontFile"].get_data()
                    )
                else:
                    stream = descriptor["/FontFile3"]
                    if stream.get("/Subtype") != "/Type1C":
                        continue
                    cff = CFFFontSet()
                    cff.decompile(io.BytesIO(stream.get_data()), None)
                    top = cff[cff.fontNames[0]]
                    glyphs, matrix, encoding = (
                        top.CharStrings,
                        top.FontMatrix,
                        top.Encoding,
                    )
                units = 1 / abs(float(matrix[0]))
                pdf_encoding = font.get("/Encoding", {})
                if isinstance(pdf_encoding, str):
                    base = pdf_encoding.lstrip("/")
                    diff = []
                else:
                    base = str(pdf_encoding.get("/BaseEncoding", "")).lstrip("/")
                    diff = pdf_encoding.get("/Differences", [])
                names = (
                    dict(enumerate(encoding))
                    if not base and isinstance(encoding, list)
                    else {}
                )
                if not base and isinstance(encoding, str):
                    base = encoding
                if base:
                    chars = EncodingDB.get_encoding(base)
                    names.update(
                        {
                            code: g
                            for g in glyphs.keys()
                            for code, text in chars.items()
                            if toUnicode(g) == text
                        }
                    )
                code = 0
                for item in diff:
                    if isinstance(item, int):
                        code = item
                    else:
                        names[code] = str(item).lstrip("/")
                        code += 1
            else:
                continue
            for cid, glyph_name in names.items():
                if glyph_name not in glyphs or glyph_name == ".notdef":
                    continue
                if font.get("/Subtype") == "/Type1":
                    decoded = toUnicode(glyph_name)
                    if decoded and all(ord(c) >= 32 for c in decoded):
                        program_readings[(name, cid)] = decoded
                pen = RecordingPen()
                glyphs[glyph_name].draw(
                    Qu2CuPen(pen, 1, all_cubic=True) if quadratic else pen
                )
                if (value := geometric_reading(pen.value, units)) and value not in {
                    "≈",
                }:
                    result[(name, cid)] = value
        except Exception:
            # Damaged optional font programs must not discard native text.
            continue
    return result, program_readings
