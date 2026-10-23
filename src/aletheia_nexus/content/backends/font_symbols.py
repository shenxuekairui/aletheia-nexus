"""Recover unambiguous symbol outlines from otherwise unmapped Type 1 fonts.

Some scientific PDFs give custom glyphs ASCII fallback codes but no ToUnicode.
Do not infer a sign from the surrounding chemistry or from a font/glyph name.
Inspect the actual painted outline; retain uncertainty for recovered readings.
"""

from __future__ import annotations

import io
import statistics
import struct
from typing import Any

from fontTools.agl import toUnicode
from fontTools.cffLib import CFFFontSet
from fontTools.misc import eexec, psCharStrings, psLib
from fontTools.pens.basePen import BasePen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont, TTLibError
from fontTools.ttLib.tables._g_l_y_f import Glyph
from pdfminer.cmapdb import CMapParser, FileUnicodeMap


def displaced_glyph_bounds(page: Any) -> dict[tuple[str, int], tuple[float, ...]]:
    """Recover vertical ink bounds when a font's em box misses its normal text.

    A font-wide descent may include exceptional glyphs far below the baseline.
    Using [descent, descent + 1 em] as every character's box then displaces the
    ordinary letters and numbers. Require a majority of mapped ASCII letters
    and digits to lie mostly outside that box. Han mappings are not baseline
    evidence: legacy symbol fonts sometimes map punctuation to Han characters.
    """
    result = {}
    resources = page.get("/Resources", {})
    resources = (
        resources.get_object() if hasattr(resources, "get_object") else resources
    )
    fonts = resources.get("/Font", {})
    fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
    for reference in fonts.values():
        font = reference.get_object()
        if font.get("/Subtype") == "/Type1":
            # A zero FontBBox is not a usable character box. Some legacy
            # subsets also give every Latin glyph a full-em advance and use
            # explicit text positions. Their embedded outlines retain the
            # actual ink bounds, including descenders and narrow digits.
            try:
                descriptor = font["/FontDescriptor"]
                box = descriptor["/FontBBox"]
                if box[2] > box[0] and box[3] > box[1]:
                    continue
                glyphs, matrix, encoding = _type1_font(
                    descriptor["/FontFile"].get_data()
                )
                pdf_encoding = font.get("/Encoding", {})
                pdf_encoding = (
                    pdf_encoding.get_object()
                    if hasattr(pdf_encoding, "get_object")
                    else pdf_encoding
                )
                names = dict(enumerate(encoding))
                cmap = FileUnicodeMap()
                if font.get("/ToUnicode"):
                    CMapParser(cmap, io.BytesIO(font["/ToUnicode"].get_data())).run()
                if isinstance(pdf_encoding, dict):
                    code = 0
                    for item in pdf_encoding.get("/Differences", []):
                        if isinstance(item, int):
                            code = item
                        else:
                            names[code] = str(item).lstrip("/")
                            code += 1
                boxes, normal = {}, []
                for cid, name in names.items():
                    if name not in glyphs:
                        continue
                    pen = RecordingPen()
                    glyphs[name].draw(pen)
                    points = [p for _, run in pen.value for p in run if p is not None]
                    if not points:
                        continue
                    boxes[cid] = (
                        min(p[0] for p in points) * matrix[0],
                        min(p[1] for p in points) * matrix[3],
                        max(p[0] for p in points) * matrix[0],
                        max(p[1] for p in points) * matrix[3],
                    )
                    text = cmap.cid2unichr.get(cid, toUnicode(name))
                    if len(text) == 1 and text.isalnum():
                        normal.append(boxes[cid])
                if normal:
                    low = statistics.median(b[1] for b in normal)
                    high = statistics.median(b[3] for b in normal)
                    for cid, b in boxes.items():
                        # Keep one text band per font. Ink-sized punctuation
                        # boxes would put decimal points on separate rows.
                        result[(str(font["/BaseFont"]).lstrip("/"), cid)] = (
                            b[0],
                            low,
                            b[2],
                            high,
                        )
            except (KeyError, ValueError, TypeError, IndexError):
                pass
            continue
        if font.get("/Subtype") != "/Type0" or font.get("/Encoding") != "/Identity-H":
            continue
        try:
            descendant = font["/DescendantFonts"][0].get_object()
            descriptor = descendant["/FontDescriptor"]
            descent = -abs(float(descriptor.get("/Descent", 0))) / 1000
            if descendant.get("/Subtype") != "/CIDFontType2" or descent >= -0.5:
                continue
            cmap = FileUnicodeMap()
            CMapParser(cmap, io.BytesIO(font["/ToUnicode"].get_data())).run()
            program = TTFont(io.BytesIO(descriptor["/FontFile2"].get_data()))
            units = program["head"].unitsPerEm
            locations, data = program["loca"].locations, program.reader["glyf"]
            mapping = descendant.get("/CIDToGIDMap", "/Identity")
            mapping = (
                mapping.get_object() if hasattr(mapping, "get_object") else mapping
            )
            gid_bytes = mapping.get_data() if hasattr(mapping, "get_data") else None
            if gid_bytes is None and mapping != "/Identity":
                continue
            bounds, normal = {}, []
            for cid, text in cmap.cid2unichr.items():
                if gid_bytes is not None and cid * 2 + 2 > len(gid_bytes):
                    continue
                gid = (
                    int.from_bytes(gid_bytes[cid * 2 : cid * 2 + 2], "big")
                    if gid_bytes is not None
                    else cid
                )
                if not 0 <= gid < len(locations) - 1:
                    continue
                start, end = locations[gid : gid + 2]
                if not 0 <= start < start + 10 <= end <= len(data):
                    continue
                contours, _, y0, _, y1 = struct.unpack(
                    ">hhhhh", data[start : start + 10]
                )
                if contours <= 0 or y1 <= y0:
                    continue
                box = (y0 / units, y1 / units)
                # CID identifies the painted glyph. Several CIDs may map to
                # the same digit while painting a normal, raised or lowered 2.
                bounds[cid] = box
                if len(text) == 1 and text.isascii() and text.isalnum():
                    normal.append(box)
            missed = sum(
                max(0, min(y1, descent + 1) - max(y0, descent)) < (y1 - y0) / 2
                for y0, y1 in normal
            )
            if normal and missed > len(normal) / 2:
                name = str(font["/BaseFont"]).lstrip("/")
                result.update({(name, cid): box for cid, box in bounds.items()})
        except (KeyError, ValueError, TypeError, IndexError, struct.error, TTLibError):
            # Unsupported/incomplete font data never justify moving a glyph.
            continue
    return result


def _outline_symbol(operations: list, units: float) -> str | None:
    contours: list[list[tuple[str, tuple]]] = []
    for operator, points in operations:
        if operator == "moveTo":
            contours.append([])
        if not contours or operator not in {
            "moveTo",
            "lineTo",
            "curveTo",
            "qCurveTo",
            "closePath",
        }:
            return None
        contours[-1].append((operator, points))
    if not contours or any(c[-1][0] != "closePath" for c in contours):
        return None

    def bounds(contour):
        points = [p for _, run in contour for p in run if p is not None]
        return (
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        )

    boxes = [bounds(c) for c in contours]
    if len(contours) <= 2:
        points = [p for c in contours for _, run in c for p in run if p is not None]
        x0, y0 = min(p[0] for p in points), min(p[1] for p in points)
        x1, y1 = max(p[0] for p in points), max(p[1] for p in points)
        width, height = x1 - x0, y1 - y0
        horizontals, stems = [], []
        for contour in contours:
            last = None
            for op, run in contour:
                if op == "lineTo" and last is not None:
                    point = run[0]
                    if (
                        abs(point[1] - last[1]) < units * 0.001
                        and abs(point[0] - last[0]) > width * 0.3
                    ):
                        horizontals.append((point[1] - y0) / max(height, 1))
                    if (
                        abs(point[0] - last[0]) < units * 0.001
                        and abs(point[1] - last[1]) > height * 0.25
                    ):
                        stems.append((point, last))
                if run:
                    last = run[-1]
        # A centered plus with a lower horizontal bar; some fonts join the
        # lower bar to its stem. Rounded ends are allowed, slashes and ∓ are not.
        if (
            units * 0.4 <= width <= units * 0.9
            and units * 0.45 <= height <= units * 0.9
            and any(y < 0.1 for y in horizontals)
            and any(0.4 < y < 0.6 for y in horizontals)
            and any(max(a[1], b[1]) > y0 + height * 0.9 for a, b in stems)
            and all(
                y <= y0 + height * 0.12
                or y0 + height * 0.4 <= y <= y0 + height * 0.6
                or abs(x - (x0 + x1) / 2) <= width * 0.08
                for x, y in points
            )
        ):
            return "±"
    if len(contours) == 1:
        x0, y0, x1, y1 = boxes[0]
        previous = None
        diagonal_edge = False
        for operator, points in contours[0]:
            if operator == "lineTo" and previous is not None:
                diagonal_edge |= (
                    abs(points[0][0] - previous[0]) > units * 0.001
                    and abs(points[0][1] - previous[1]) > units * 0.001
                )
            if points:
                previous = points[-1]
        if (
            not diagonal_edge
            and x1 - x0 >= units * 0.3
            and 0 < y1 - y0 <= units * 0.08
            and x1 - x0 >= 8 * (y1 - y0)
            and units * 0.1 < (y0 + y1) / 2 < units * 0.6
        ):
            return "−"
        if (
            not diagonal_edge
            and units * 0.2 <= x1 - x0 <= units * 0.5
            and 0 < y1 - y0 <= units * 0.08
            and 4 <= (x1 - x0) / (y1 - y0) < 8
            and units * 0.15 < (y0 + y1) / 2 < units * 0.4
        ):
            return "-"
    if len(contours) == 2:
        first, second = contours
        x0, y0, x1, y1 = boxes[0]
        dy = boxes[1][1] - y0
        # A small raised circular ring. Baseline letters, zero, centered circle
        # operators and larger circled symbols do not meet these bounds.
        outer, inner = sorted(boxes, key=lambda b: b[2] - b[0], reverse=True)
        width, height = outer[2] - outer[0], outer[3] - outer[1]
        if (
            all(
                sum(op == "curveTo" for op, _ in c) == 4
                or sum(op == "qCurveTo" for op, _ in c) == 8
                for c in contours
            )
            and all(op != "lineTo" for c in contours for op, _ in c)
            and units * 0.15 <= width <= units * 0.35
            and abs(width - height) <= units * 0.015
            and units * 0.35 < outer[1]
            and units * 0.45 < (outer[1] + outer[3]) / 2 < units * 0.7
            and outer[0] < inner[0] < inner[2] < outer[2]
            and outer[1] < inner[1] < inner[3] < outer[3]
            and abs(inner[0] + inner[2] - outer[0] - outer[2]) < units * 0.015
            and abs(inner[1] + inner[3] - outer[1] - outer[3]) < units * 0.015
            and abs((inner[2] - inner[0]) - (inner[3] - inner[1])) < units * 0.015
        ):
            return "°"
        # Two vertically translated filled waves, not two straight '=' bars.
        if (
            len(first) == len(second)
            and sum(op == "curveTo" for op, _ in first) >= 4
            and x1 - x0 >= units * 0.3
            and units * 0.1 <= y1 - y0 <= units * 0.4
            and abs(dy) > y1 - y0
            and all(
                op1 == op2
                and len(p1) == len(p2)
                and all(
                    abs(a[0] - b[0]) <= units * 0.015
                    and abs(a[1] + dy - b[1]) <= units * 0.015
                    for a, b in zip(p1, p2)
                )
                for (op1, p1), (op2, p2) in zip(first, second)
            )
        ):
            return "≈"
    return None


def _cff_zero_glyph(data: bytes, top: Any) -> str | None:
    """Read an unambiguous code-zero entry omitted by fontTools' format 0.

    Zero can also be padding for an unencoded glyph. Multiple zero entries
    therefore have no unique reading. The caller still verifies the outline
    and only replaces pdfminer's missing-character fallback, never ToUnicode.
    """
    offset = top.rawDict.get("Encoding", 0)
    if not isinstance(offset, int) or offset <= 1 or offset + 2 > len(data):
        return None
    if data[offset] != 0:  # Format 0 only, no supplement overriding a code.
        return None
    count = data[offset + 1]
    codes = data[offset + 2 : offset + 2 + count]
    if len(codes) != count or codes.count(0) != 1:
        return None
    glyph_index = codes.index(0) + 1
    return top.charset[glyph_index] if glyph_index < len(top.charset) else None


def _type1_font(data: bytes) -> tuple[dict, list, list]:
    """Decode embedded Type 1 glyphs, including fonts with no subroutines."""
    font = psLib.suckfont(data, "ascii")
    private = font["Private"]
    subrs = private.get("Subrs", [])
    len_iv = private.get("lenIV", 4)
    if len_iv < 0:
        raise ValueError("Unsupported unencrypted Type 1 charstrings")

    def decode(program):
        decrypted, _ = eexec.decrypt(program, 4330)
        return psCharStrings.T1CharString(decrypted[len_iv:], subrs=subrs)

    glyphs = {name: decode(program) for name, program in font["CharStrings"].items()}
    subrs[:] = [decode(program) for program in subrs]
    return glyphs, font["FontMatrix"], font["Encoding"]


def _mapped_m_outline(operations: list, units: float) -> str | None:
    """Recognize only an angular capital M or a descended, open-top Greek mu.

    Some legacy fonts label both as Latin m even in ToUnicode. This evidence
    is used only in a positioned numeric unit token, never to recase prose.
    """
    if (
        sum(op == "moveTo" for op, _ in operations) != 1
        or not operations
        or operations[-1][0] != "closePath"
    ):
        return None
    points = [p for _, run in operations for p in run]
    x0, y0 = min(x for x, _ in points), min(y for _, y in points)
    x1, y1 = max(x for x, _ in points), max(y for _, y in points)
    width, height = x1 - x0, y1 - y0
    if not (0.3 * units < width < units and 0.35 * units < height < units):
        return None
    segments = []
    last = None
    for op, run in operations:
        if op == "lineTo" and last is not None:
            segments.append((last, run[0]))
        if run:
            last = run[-1]
    # Two long diagonals on each side of the central valley. Lowercase m's
    # curved arches, N, W and a plain u do not satisfy this outline.
    falling = sum(
        b[0] - a[0] > 0.18 * width
        and b[1] - a[1] < -0.55 * height
        or a[0] - b[0] > 0.18 * width
        and a[1] - b[1] < -0.55 * height
        for a, b in segments
    )
    rising = sum(
        b[0] - a[0] > 0.18 * width
        and b[1] - a[1] > 0.55 * height
        or a[0] - b[0] > 0.18 * width
        and a[1] - b[1] > 0.55 * height
        for a, b in segments
    )
    if y0 >= -0.03 * units and falling == 2 and rising == 2:
        valleys = [
            p
            for p in points
            if x0 + 0.3 * width < p[0] < x0 + 0.7 * width and p[1] < y0 + 0.3 * height
        ]
        if len(valleys) >= 2:
            return "M"
    # Mu: left descender, two straight upright stems, open top, curved bowl.
    below = [p for p in points if p[1] < -0.1 * units]
    vertical = [
        (a, b)
        for a, b in segments
        if abs(a[0] - b[0]) < 0.015 * units and abs(a[1] - b[1]) > 0.3 * units
    ]
    if (
        y0 < -0.15 * units
        and 0.35 * units < y1 < 0.65 * units
        and below
        and max(x for x, _ in below) < x0 + 0.35 * width
        and any(a[0] < x0 + 0.3 * width for a, b in vertical)
        and any(a[0] > x0 + 0.5 * width for a, b in vertical)
        and sum(op == "curveTo" for op, _ in operations) >= 4
        and not any(
            abs(a[0] - b[0]) > 0.5 * width and min(a[1], b[1]) > y1 - 0.08 * units
            for a, b in segments
        )
    ):
        return "μ"
    return None


def mapped_unit_m_readings(page: Any) -> dict[str, str]:
    """Read the actual Type 1 glyph for WinAnsi m, without trusting its label."""
    result = {}
    resources = page.get("/Resources", {})
    resources = (
        resources.get_object() if hasattr(resources, "get_object") else resources
    )
    fonts = resources.get("/Font", {})
    fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
    for reference in fonts.values():
        font = reference.get_object()
        if (
            font.get("/Subtype") != "/Type1"
            or font.get("/Encoding") != "/WinAnsiEncoding"
            or not font.get("/FirstChar", 256) <= 109 <= font.get("/LastChar", -1)
        ):
            continue
        try:
            descriptor = font["/FontDescriptor"]
            if "/FontFile" in descriptor:
                glyphs, matrix, _ = _type1_font(descriptor["/FontFile"].get_data())
            elif descriptor.get("/FontFile3", {}).get("/Subtype") == "/Type1C":
                cff = CFFFontSet()
                cff.decompile(io.BytesIO(descriptor["/FontFile3"].get_data()), None)
                top = cff[cff.fontNames[0]]
                glyphs, matrix = top.CharStrings, top.FontMatrix
            else:
                continue
            pen = RecordingPen()
            glyphs["m"].draw(pen)
            reading = _mapped_m_outline(pen.value, 1 / abs(float(matrix[0])))
            if reading:
                result[str(font.get("/BaseFont", "")).lstrip("/")] = reading
        except Exception:
            continue
    return result


class _OutlineContours(BasePen):
    """Flatten curves for scale-independent ink cross sections, not OCR."""

    def __init__(self):
        super().__init__(None)
        self.contours = []

    def _moveTo(self, point):
        self.contours.append([point])

    def _lineTo(self, point):
        self.contours[-1].append(point)

    def _closePath(self):
        pass

    def _curveToOne(self, first, second, end):
        start = self._getCurrentPoint()
        for step in range(1, 25):
            t = step / 24
            self.contours[-1].append(
                tuple(
                    (1 - t) ** 3 * start[i]
                    + 3 * t * (1 - t) ** 2 * first[i]
                    + 3 * t * t * (1 - t) * second[i]
                    + t**3 * end[i]
                    for i in (0, 1)
                )
            )


def _ink_intervals(contours, y):
    edges = []
    for contour in contours:
        for a, b in zip(contour, contour[1:] + contour[:1]):
            if min(a[1], b[1]) <= y < max(a[1], b[1]):
                edges.append(
                    (
                        a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]),
                        1 if b[1] > a[1] else -1,
                    )
                )
    intervals, winding, start = [], 0, 0
    for x, direction in sorted(edges):
        if not winding:
            start = x
        winding += direction
        if not winding and x > start:
            if intervals and start - intervals[-1][1] < 0.01:
                intervals[-1] = (intervals[-1][0], x)
            else:
                intervals.append((start, x))
    return intervals


def _outlined_unit(operations: list, units: float) -> str | None:
    """Recognize m's three stems/two arches or a raised ring plus open C.

    Legacy fonts can polygonize curves and divide one letter into several
    contours. Use painted ink, irrespective of contour count or glyph names.
    The caller restricts these readings to unit positions and keeps originals.
    """
    if not operations or operations[-1][0] != "closePath":
        return None
    pen = _OutlineContours()
    for op, points in operations:
        if op not in {"moveTo", "lineTo", "curveTo", "qCurveTo", "closePath"}:
            return None
        getattr(pen, op)(*points)
    contours = [[(x / units, y / units) for x, y in c] for c in pen.contours]
    if not contours or any(len(c) < 3 for c in contours):
        return None

    def bounds(cs):
        points = [p for c in cs for p in c]
        return (
            min(x for x, _ in points),
            min(y for _, y in points),
            max(x for x, _ in points),
            max(y for _, y in points),
        )

    x0, y0, x1, y1 = bounds(contours)
    width, height = x1 - x0, y1 - y0
    if 0.55 < width < 1 and 0.35 < height < 0.6 and -0.04 <= y0 < 0.2:
        sections = [_ink_intervals(contours, y0 + height * t) for t in (0.25, 0.4, 0.6)]
        if all(len(section) == 3 for section in sections):
            stems = sections[0]
            if (
                all(0.03 < b - a < width * 0.25 for a, b in stems)
                and all(
                    abs(a - b) < 0.025
                    for section in sections[1:]
                    for pair, base in zip(section, stems)
                    for a, b in zip(pair, base)
                )
                and all(
                    any(
                        a < (left[1] + right[0]) / 2 < b
                        for t in (0.8, 0.85, 0.9, 0.95)
                        for a, b in _ink_intervals(contours, y0 + height * t)
                    )
                    for left, right in zip(stems, stems[1:])
                )
            ):
                return "m"
    small, body = [], []
    for contour in contours:
        a, b, c, d = bounds([contour])
        (small if d - b < 0.35 and b > 0.6 and c < 0.4 else body).append(contour)
    if not small or not body:
        return None
    a, b, c, d = bounds(small)
    ring_width, ring_height = c - a, d - b
    bx, by, ex, ey = bounds(body)
    if not (
        0.15 < ring_width < 0.32
        and 0.8 < ring_width / ring_height < 1.2
        and 0.45 < ex - bx < 0.8
        and 0.55 < ey - by < 0.85
        and c < bx + (ex - bx) * 0.3
        and b > by + (ey - by) * 0.7
    ):
        return None
    for shape, low, high in [
        (small, b, d),
        ([[(y, x) for x, y in cs] for cs in small], a, c),
    ]:
        section = _ink_intervals(shape, (low + high) / 2)
        if len(section) != 2 or section[1][0] - section[0][1] < ring_width * 0.3:
            return None
    middle = [_ink_intervals(body, by + (ey - by) * t) for t in (0.4, 0.5, 0.6)]
    if not all(len(s) == 1 and s[0][1] < bx + (ex - bx) * 0.4 for s in middle):
        return None
    # Both ends must curve back to the right: excludes a ring beside I or L.
    if all(
        any(
            q > bx + (ex - bx) * 0.6
            for _, q in _ink_intervals(body, by + (ey - by) * t)
        )
        for t in (0.1, 0.9)
    ):
        return "℃"
    return None


def mapped_outline_units(page: Any) -> dict[tuple[str, str], str]:
    """Verify custom Type 1 encodings against unit outlines, per unique mapping."""
    result = {}
    resources = page.get("/Resources", {})
    if hasattr(resources, "get_object"):
        resources = resources.get_object()
    fonts = resources.get("/Font", {})
    if hasattr(fonts, "get_object"):
        fonts = fonts.get_object()
    for reference in fonts.values():
        font = reference.get_object()
        if font.get("/Subtype") != "/Type1" or "/ToUnicode" not in font:
            continue
        try:
            glyphs, matrix, encoding = _type1_font(
                font["/FontDescriptor"]["/FontFile"].get_data()
            )
            cmap = FileUnicodeMap()
            CMapParser(cmap, io.BytesIO(font["/ToUnicode"].get_data())).run()
            names, code = dict(enumerate(encoding)), 0
            pdf_encoding = font.get("/Encoding", {})
            if hasattr(pdf_encoding, "get_object"):
                pdf_encoding = pdf_encoding.get_object()
            if isinstance(pdf_encoding, dict):
                for item in pdf_encoding.get("/Differences", []):
                    if isinstance(item, int):
                        code = item
                    else:
                        names[code] = str(item).lstrip("/")
                        code += 1
            values = list(cmap.cid2unichr.values())
            for cid, text in cmap.cid2unichr.items():
                if (
                    len(text) != 1
                    or values.count(text) != 1
                    or names.get(cid) not in glyphs
                ):
                    continue
                pen = RecordingPen()
                glyphs[names[cid]].draw(pen)
                reading = _outlined_unit(pen.value, 1 / abs(float(matrix[0])))
                if reading and reading != text:
                    result[(str(font["/BaseFont"]).lstrip("/"), text)] = reading
        except (KeyError, ValueError, TypeError, IndexError, psLib.PSError):
            continue
    return result


def mapped_degree_readings(page: Any) -> dict[tuple[str, str], tuple[float, ...]]:
    """Verify a wrong explicit CID mapping against a raised-ring glyph.

    Read individual simple glyphs: legacy subset fonts can have sparse, invalid
    unused loca entries. Never interpret a Chinese character by its meaning.
    Ambiguous mappings (one Unicode value for different painted glyphs) stay put.
    """
    result = {}
    resources = page.get("/Resources", {})
    resources = (
        resources.get_object() if hasattr(resources, "get_object") else resources
    )
    fonts = resources.get("/Font", {})
    fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
    for reference in fonts.values():
        font = reference.get_object()
        if (
            font.get("/Subtype") == "/Type1"
            and font.get("/Encoding") == "/WinAnsiEncoding"
            and not font.get("/ToUnicode")
        ):
            # Some old subsets assign a raised ring to an ASCII digit. Read
            # the painted outline; the caller also requires numeric °C/°F
            # context. A real digit must never be replaced by this recovery.
            try:
                stream = font["/FontDescriptor"]["/FontFile3"]
                if stream.get("/Subtype") != "/Type1C":
                    continue
                cff = CFFFontSet()
                cff.decompile(io.BytesIO(stream.get_data()), None)
                top = cff[cff.fontNames[0]]
                units = 1 / abs(float(top.FontMatrix[0]))
                for code, name in enumerate(
                    "zero one two three four five six seven eight nine".split(), 48
                ):
                    if (
                        not font.get("/FirstChar", 256)
                        <= code
                        <= font.get("/LastChar", -1)
                    ):
                        continue
                    if name not in top.CharStrings:
                        continue
                    pen = RecordingPen()
                    top.CharStrings[name].draw(pen)
                    if _outline_symbol(pen.value, units) == "°":
                        points = [
                            p for _, run in pen.value for p in run if p is not None
                        ]
                        result[(str(font["/BaseFont"]).lstrip("/"), chr(code))] = (
                            min(p[0] for p in points) / units,
                            min(p[1] for p in points) / units,
                            max(p[0] for p in points) / units,
                            max(p[1] for p in points) / units,
                        )
            except Exception:
                pass
            continue
        if font.get("/Subtype") != "/Type0" or font.get("/Encoding") != "/Identity-H":
            continue
        try:
            descendant = font["/DescendantFonts"][0].get_object()
            if descendant.get("/Subtype") != "/CIDFontType2":
                continue
            cmap = FileUnicodeMap()
            CMapParser(cmap, io.BytesIO(font["/ToUnicode"].get_data())).run()
            program = TTFont(
                io.BytesIO(descendant["/FontDescriptor"]["/FontFile2"].get_data())
            )
            units = program["head"].unitsPerEm
            locations, data = program["loca"].locations, program.reader["glyf"]
            mapping = descendant.get("/CIDToGIDMap", "/Identity")
            mapping = (
                mapping.get_object() if hasattr(mapping, "get_object") else mapping
            )
            gid_bytes = mapping.get_data() if hasattr(mapping, "get_data") else None
            if gid_bytes is None and mapping != "/Identity":
                continue
            counts = {}
            for value in cmap.cid2unichr.values():
                counts[value] = counts.get(value, 0) + 1
            for cid, text in cmap.cid2unichr.items():
                if text == "°" or counts[text] != 1:
                    continue
                if gid_bytes is not None and cid * 2 + 2 > len(gid_bytes):
                    continue
                gid = (
                    int.from_bytes(gid_bytes[cid * 2 : cid * 2 + 2], "big")
                    if gid_bytes is not None
                    else cid
                )
                if not 0 <= gid < len(locations) - 1:
                    continue
                start, end = locations[gid : gid + 2]
                if not 0 <= start < end <= len(data):
                    continue
                glyph = Glyph(data[start:end])
                if glyph.isComposite():
                    continue
                pen = RecordingPen()
                glyph.draw(pen, None)
                if _outline_symbol(pen.value, units) == "°":
                    points = [p for _, run in pen.value for p in run if p is not None]
                    result[(str(font["/BaseFont"]).lstrip("/"), text)] = (
                        min(p[0] for p in points) / units,
                        min(p[1] for p in points) / units,
                        max(p[0] for p in points) / units,
                        max(p[1] for p in points) / units,
                    )
        except Exception:
            continue
    return result


def unmapped_font_symbols(page: Any) -> tuple[dict, set]:
    """Return outline readings and uncertain fallbacks, keyed by font and text.

    Unmapped custom Encoding/Differences and embedded code-zero are considered. A partial
    ToUnicode does not cover every glyph; its explicit mappings still win. The
    original PDF is never modified. Unsupported/damaged fonts remain uncertain.
    """
    recovered: dict[tuple[str, str], str] = {}
    uncertain: set[tuple[str, str]] = set()
    resources = page.get("/Resources", {})
    resources = (
        resources.get_object() if hasattr(resources, "get_object") else resources
    )
    fonts = resources.get("/Font", {})
    fonts = fonts.get_object() if hasattr(fonts, "get_object") else fonts
    for reference in fonts.values():
        font = reference.get_object()
        if font.get("/Subtype") != "/Type1":
            continue
        encoding = font.get("/Encoding")
        encoding = (
            encoding.get_object() if hasattr(encoding, "get_object") else encoding
        )
        if not isinstance(encoding, dict) and encoding is not None:
            continue
        candidates = {}
        code = 0
        name = str(font.get("/BaseFont", "")).lstrip("/")
        for entry in (encoding or {}).get("/Differences", []):
            if isinstance(entry, int):
                code = int(entry)
                continue
            glyph_name = str(entry).lstrip("/")
            if 0 <= code < 256 and not toUnicode(glyph_name):
                # pdfminer emits this fallback only when the character has no
                # Unicode reading. Never replace an explicitly mapped glyph.
                keys = [(name, f"(cid:{code})")]
                if not font.get("/ToUnicode") and 32 <= code < 127:
                    keys.append((name, chr(code)))
                candidates[glyph_name] = keys
                uncertain.update(keys)
            code += 1
        if not candidates and encoding is not None:
            continue
        try:
            descriptor = font["/FontDescriptor"]
            if "/FontFile" in descriptor:
                data = descriptor["/FontFile"].get_data()
                # Embedded PDF Type 1 streams omit the PFA/PFB file trailer.
                glyphs, matrix, built_in_encoding = _type1_font(data)
                if encoding is None and built_in_encoding[0] != ".notdef":
                    key = (name, "(cid:0)")
                    candidates[built_in_encoding[0]] = [key]
                    uncertain.add(key)
            else:
                stream = descriptor["/FontFile3"]
                if stream.get("/Subtype") != "/Type1C":
                    continue
                data = stream.get_data()
                cff = CFFFontSet()
                cff.decompile(io.BytesIO(data), None)
                top = cff[cff.fontNames[0]]
                glyphs, matrix = top.CharStrings, top.FontMatrix
                if encoding is None and (zero_glyph := _cff_zero_glyph(data, top)):
                    key = (name, "(cid:0)")
                    candidates[zero_glyph] = [key]
                    uncertain.add(key)
            units = 1 / abs(float(matrix[0]))
            for glyph_name, keys in candidates.items():
                pen = RecordingPen()
                glyphs[glyph_name].draw(pen)
                if symbol := _outline_symbol(pen.value, units):
                    recovered.update((key, symbol) for key in keys)
        except Exception:
            # Font parsing is an optional recovery. Preserve native fallback and
            # mark its line uncertain if the embedded font cannot be decoded.
            continue
    return recovered, uncertain
