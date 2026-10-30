"""Character-positioned native extraction for scientific page layouts."""

from __future__ import annotations

import io
import re
import statistics
import unicodedata
from collections import Counter
from importlib.metadata import version
from typing import Any

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTChar, LTContainer, LTCurve, LTFigure
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pypdf import PdfWriter
from pypdf.generic import IndirectObject

from aletheia_nexus.content.backends.font_symbols import (
    displaced_glyph_bounds,
    mapped_degree_readings,
    mapped_outline_units,
    mapped_unit_m_readings,
    unmapped_font_symbols,
)
from aletheia_nexus.content.backends.glyph_readings import encoded_glyph_readings
from aletheia_nexus.content.backends.native import _page_objects
from aletheia_nexus.content.backends.vector_text import (
    VectorTextLimitError,
    vector_text_regions,
)
from aletheia_nexus.content.backends.vertical_text import vertical_lines
from aletheia_nexus.content.geometry import PageGeometry
from aletheia_nexus.content.models import LayoutLine, PageLayout


def suspicious_text(text: str) -> bool:
    return (
        bool(re.search(r"\(cid:\d+\)|@\s*\d", text))
        or any(
            c == "\ufffd" or unicodedata.category(c) in {"Cc", "Cs", "Co"}
            for c in text
            if c not in "\t\r\n"
        )
        or any(
            unicodedata.category(c).startswith("M")
            and (not index or not text[index - 1].isalpha())
            for index, c in enumerate(text)
        )
        or any(
            unicodedata.category(c).startswith("P")
            and unicodedata.bidirectional(c) in {"R", "AL"}
            and re.search(r"[\d/／]\s*$", text[:index])
            and not any(
                x.isalpha() and unicodedata.bidirectional(x) in {"R", "AL"}
                for x in text
            )
            for index, c in enumerate(text)
        )
    )


def _dominant_font(chars: list[LTChar]) -> str | None:
    # Inline symbols, superscripts and occasional emphasized words should not
    # change the paragraph's font face. Require a majority of full-size letters;
    # an ambiguous mixture supplies no boundary evidence.
    largest = max(c.size for c in chars)
    names = [
        c.fontname for c in chars if c.get_text().isalpha() and c.size >= largest * 0.85
    ]
    if not names:
        return None
    name, count = Counter(names).most_common(1)[0]
    return name if count > len(names) / 2 else None


def _ordered_glyphs(chars: list[LTChar]) -> list[LTChar]:
    """Keep overlapping subscript/superscript runs intact in plain text."""
    size = max(c.size for c in chars)
    baseline = statistics.median(
        (c.y0 + c.y1) / 2 for c in chars if c.size >= size * 0.85
    )
    ordered = []
    scripts: list[LTChar] = []

    def flush() -> None:
        # A lowered label such as 'cat' and an elevated '-1' share x coordinates.
        # Serialize the complete lower run first, without interleaving letters.
        for elevated in (False, True):
            group = [c for c in scripts if ((c.y0 + c.y1) / 2 > baseline) == elevated]
            if group and min(c.size for c in group) < max(c.size for c in group) * 0.85:
                # A subscript can itself carry a smaller subscript and charge.
                # Its own baseline, not the outer formula baseline, orders them.
                ordered.extend(_ordered_glyphs(group))
            else:
                ordered.extend(sorted(group, key=lambda c: c.x0))
        scripts.clear()

    for char in sorted(chars, key=lambda c: c.x0):
        if char.size >= size * 0.85:
            flush()
            ordered.append(char)
        else:
            if scripts:
                gap = char.x0 - max(c.x1 for c in scripts)
                local_size = max(c.size for c in scripts)
                if gap > 0.3 and not (
                    char.size < local_size * 0.85 and gap <= local_size * 0.6
                ):
                    flush()
            scripts.append(char)
    flush()
    return ordered


def _attach_symbols(rows: list[list[LTChar]], symbols: list[LTChar]) -> set[int]:
    """Attach signs by local neighbours and text baseline, not another column."""
    ambiguous = set()
    for symbol in symbols:
        matches = []
        for index, row in enumerate(rows):
            neighbours = [
                c
                for c in row
                if max(0, c.x0 - symbol.x1, symbol.x0 - c.x1)
                <= max(3, max(c.size, symbol.size) * 0.6)
                and (
                    abs((c.y0 + c.y1 - symbol.y0 - symbol.y1) / 2)
                    <= max(2, max(c.size, symbol.size) * 0.72)
                    or abs(c.matrix[5] - symbol.matrix[5]) < 0.5
                )
            ]
            if neighbours:
                matches.append(
                    (
                        min(abs(c.matrix[5] - symbol.matrix[5]) for c in neighbours),
                        index,
                    )
                )
        matches.sort()
        if matches and (len(matches) == 1 or matches[1][0] - matches[0][0] > 1):
            rows[matches[0][1]].append(symbol)
        else:
            # Preserve a detached glyph and flag the competing rows as well.
            ambiguous.update(index for _, index in matches)
            ambiguous.add(len(rows))
            rows.append([symbol])
    return ambiguous


def _attach_inline_glyphs(rows: list[list[LTChar]]) -> set[int]:
    """Rejoin an isolated letter only between two adjacent baseline neighbours."""
    moved, ambiguous = [], set()
    for source in rows:
        for char in source:
            text = char.get_text()
            if (
                len(text) != 1
                or not (text.isalpha() or unicodedata.category(text) == "Co")
                or char.matrix[1]
                or char.matrix[2]
            ):
                continue
            baseline = getattr(char, "an_text_origin", char.matrix[4:6])[1]

            def same_baseline(other):
                return (
                    other is not char
                    and other.get_text().isalpha()
                    and abs(other.size - char.size) <= char.size * 0.1
                    and not other.matrix[1]
                    and not other.matrix[2]
                    and abs(
                        getattr(other, "an_text_origin", other.matrix[4:6])[1]
                        - baseline
                    )
                    < 0.1
                )

            if any(
                same_baseline(c)
                and max(0, c.x0 - char.x1, char.x0 - c.x1) <= char.size * 0.4
                for c in source
            ):
                continue
            targets = []
            for target in rows:
                if target is source:
                    continue
                neighbours = [c for c in target if same_baseline(c)]
                if any(
                    -0.05 * char.size <= char.x0 - c.x1 <= 0.3 * char.size
                    for c in neighbours
                ) and any(
                    -0.05 * char.size <= c.x0 - char.x1 <= 0.3 * char.size
                    for c in neighbours
                ):
                    targets.append(target)
            if len(targets) == 1:
                moved.append((char, source, targets[0]))
            elif targets:
                ambiguous.add(id(char))
    for char, source, target in moved:
        source.remove(char)
        target.append(char)
    return ambiguous


def _attach_nested_scripts(rows: list[list[LTChar]]) -> set[int]:
    """Revisit short numeric fragments after all local script bases exist.

    A lowered multi-letter label may be assembled after its final digit due to
    differing ink bounds. Only a unique, adjacent alphabetic base in a larger
    text row can absorb the detached fragment; ordinary numeric rows stay put.
    """
    ambiguous = set()
    moves = []
    for source, row in enumerate(rows):
        fragments = [[]]
        for char in sorted(row, key=lambda c: c.x0):
            group = fragments[-1]
            if group and char.x0 - max(c.x1 for c in group) > max(
                2, max(c.size for c in group) * 0.9
            ):
                fragments.append([])
            fragments[-1].append(char)
        for fragment in fragments:
            text = "".join(c.get_text() for c in fragment).strip()
            if not re.fullmatch(r"[+−\-0-9]{1,4}", text):
                continue
            candidates = []
            for target, base in enumerate(rows):
                if (
                    target == source
                    or not base
                    or max(c.size for c in fragment) >= max(c.size for c in base) * 0.85
                ):
                    continue
                if all(
                    any(
                        c.get_text().isalpha()
                        and max(0, char.x0 - c.x1, c.x0 - char.x1) <= c.size * 0.8
                        and (
                            abs(char.size - c.size) <= char.size * 0.15
                            and abs(char.an_text_origin[1] - c.an_text_origin[1]) < 0.5
                            or char.size < c.size * 0.85
                            and abs((char.y0 + char.y1 - c.y0 - c.y1) / 2)
                            <= c.size * 0.72
                        )
                        for c in base
                    )
                    for char in fragment
                ):
                    candidates.append(target)
            if len(candidates) == 1:
                moves.append((source, candidates[0], fragment))
            elif candidates:
                ambiguous.update(id(c) for c in fragment)
    for source, target, fragment in moves:
        identities = {id(c) for c in fragment}
        rows[source][:] = [c for c in rows[source] if id(c) not in identities]
        rows[target].extend(fragment)
    return ambiguous


def _identify_font_resources(writer, page):
    """Give direct fonts identities in the temporary copy used by both readers.

    PDF font names are not unique: a simple font's byte 32 can be a space while
    a same-named CID font paints an equals at CID 32. Never share their repairs.
    The original page and font resources are left untouched.
    """
    seen = set()

    def visit(resources):
        fonts = resources.get("/Font", {})
        for key, reference in list(fonts.items()):
            if not isinstance(reference, IndirectObject):
                fonts[key] = writer._add_object(reference)
        for reference in resources.get("/XObject", {}).values():
            obj = reference.get_object()
            if obj.get("/Subtype") == "/Form" and id(obj) not in seen:
                seen.add(id(obj))
                visit(obj.get("/Resources", {}))

    visit(page.get("/Resources", {}))


class _FontResourceManager(PDFResourceManager):
    def get_font(self, objid, spec):
        font = super().get_font(objid, spec)
        font.an_resource_id = objid
        return font


class _ClippedPageAggregator(PDFPageAggregator):
    def __init__(
        self,
        *args,
        ink_bounds=None,
        glyph_readings=None,
        program_readings=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.ink_bounds = ink_bounds or {}
        self.corrected_glyphs = 0
        self.glyph_readings = glyph_readings or {}
        self.program_readings = program_readings or {}

    def render_char(
        self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate
    ):
        advance = super().render_char(
            matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate
        )
        char = self.cur_item._objs[-1]
        char.an_resource_id = font.an_resource_id
        # Text rise (Ts) moves the painted baseline without changing LTChar's
        # text matrix. Rotated scripts need the actual origin, not only Tm.
        char.an_text_origin = (
            matrix[4] + rise * matrix[2],
            matrix[5] + rise * matrix[3],
        )
        program_reading = self.program_readings.get((char.an_resource_id, cid))
        if (
            program_reading
            and program_reading != char.get_text()
            and not suspicious_text(program_reading)
            and suspicious_text(char.get_text())
        ):
            char.original_reading = char.get_text()
            char._text = program_reading
        reading = self.glyph_readings.get((char.an_resource_id, cid))
        if reading in {"α", "△", "□"} and not suspicious_text(char.get_text()):
            reading = None
        if reading in {"−", "-"} and char.get_text() != "±":
            reading = None
        if (
            reading
            and reading != char.get_text()
            and char.get_text() not in {"x", "X", "o", "O", "0"}
        ):
            char.outline_reading = reading
        ink = self.ink_bounds.get((char.an_resource_id, cid))
        if ink and not matrix[1] and matrix[3] > 0 and fontsize > 0:
            if len(ink) == 4:
                char.reading_bbox = char.bbox
                points = [
                    (
                        matrix[4]
                        + x * fontsize * scaling * matrix[0]
                        + (rise + y * fontsize) * matrix[2],
                        matrix[5] + (rise + y * fontsize) * matrix[3],
                    )
                    for x in (ink[0], ink[2])
                    for y in (ink[1], ink[3])
                ]
                char.set_bbox(
                    (
                        min(p[0] for p in points),
                        min(p[1] for p in points),
                        max(p[0] for p in points),
                        max(p[1] for p in points),
                    )
                )
            elif not matrix[2]:
                char.set_bbox(
                    (
                        char.x0,
                        matrix[5] + (rise + ink[0] * fontsize) * matrix[3],
                        char.x1,
                        matrix[5] + (rise + ink[1] * fontsize) * matrix[3],
                    )
                )
            # LTChar.size remains the text em size, including for scripts.
            self.corrected_glyphs += 1
        return advance

    def begin_figure(self, name, bbox, matrix):
        # PDF Form BBox is x0,y0,x1,y1; LTFigure expects x,y,width,height.
        x0, y0, x1, y1 = bbox
        super().begin_figure(name, (x0, y0, x1 - x0, y1 - y0), matrix)


class LayoutPdfBackend:
    """Use actual glyph bounds instead of estimating widths from string length."""

    name = "pdfminer-native-layout"
    version = "1.19.9"

    @property
    def execution_identity(self) -> dict[str, object]:
        return {
            "runtime_dependencies": {
                "pdfminer.six": version("pdfminer.six"),
                "pypdf": version("pypdf"),
                "fonttools": version("fonttools"),
            }
        }

    def extract_page(self, page: Any, page_number: int) -> PageLayout:
        # Enforce pypdf's existing decompression/concatenation guards before
        # pdfminer expands the same stream. The pipeline records a failed page
        # and continues; never relax the guard to force a parse.
        contents = page.get_contents()
        if contents is not None:
            contents.get_data()
        unit_repairs = []
        recovered_count = 0
        writer = PdfWriter()
        copied = writer.add_page(page)
        geometry = PageGeometry.from_page(copied)
        _identify_font_resources(writer, copied)
        symbol_readings, unmapped = unmapped_font_symbols(copied)
        unit_readings = mapped_unit_m_readings(copied)
        degree_readings = mapped_degree_readings(copied)
        outline_units = mapped_outline_units(copied)
        # pdfminer uses the MediaBox; align its origin with the displayed crop.
        copied.mediabox = copied.cropbox
        stream = io.BytesIO()
        writer.write(stream)
        stream.seek(0)
        manager = _FontResourceManager()
        glyph_readings, program_readings = encoded_glyph_readings(copied)
        device = _ClippedPageAggregator(
            manager,
            laparams=LAParams(all_texts=True, detect_vertical=True),
            ink_bounds=displaced_glyph_bounds(copied),
            glyph_readings=glyph_readings,
            program_readings=program_readings,
        )
        interpreter = PDFPageInterpreter(manager, device)
        interpreter.process_page(next(PDFPage.get_pages(stream)))
        layout = device.get_result()
        glyphs = []
        vector_shapes = []
        clipped_glyphs = 0
        degree_originals = {}

        def visit(item: Any, clip: tuple | None = None) -> None:
            nonlocal clipped_glyphs
            if isinstance(item, LTFigure):
                box = item.bbox
                clip = (
                    (
                        max(clip[0], box[0]),
                        max(clip[1], box[1]),
                        min(clip[2], box[2]),
                        min(clip[3], box[3]),
                    )
                    if clip
                    else box
                )
            if isinstance(item, LTChar):
                if clip and (
                    item.x1 <= clip[0]
                    or item.x0 >= clip[2]
                    or item.y1 <= clip[1]
                    or item.y0 >= clip[3]
                ):
                    clipped_glyphs += 1
                    return
                glyphs.append(item)
            elif isinstance(item, LTCurve) and item.fill:
                box = item.bbox
                if clip:
                    box = (
                        max(box[0], clip[0]),
                        max(box[1], clip[1]),
                        min(box[2], clip[2]),
                        min(box[3], clip[3]),
                    )
                box = (
                    max(0, box[0]),
                    max(0, box[1]),
                    min(geometry.width, box[2]),
                    min(geometry.height, box[3]),
                )
                if box[2] > box[0] and box[3] > box[1]:
                    vector_shapes.append((box, len(item.pts) >= 6))
            elif isinstance(item, LTContainer):
                for child in item:
                    visit(child, clip)

        visit(layout)
        for char in glyphs:
            reading = getattr(char, "outline_reading", None)
            if (char.an_resource_id, char.get_text()) in degree_readings:
                continue  # Existing raised-ring recovery also repairs bounds.
            if reading == "∘":
                # A raised ring followed by C/F is a temperature sign. A
                # baseline circle elsewhere remains a circle operator.
                following = [
                    c
                    for c in glyphs
                    if c.get_text() in {"C", "F"}
                    and -1 <= c.x0 - char.x1 <= c.size * 0.6
                    and abs(c.y1 - char.y1) <= c.size * 0.7
                ]
                if following and any(
                    c.get_text().isdigit()
                    and -1 <= char.x0 - c.x1 <= c.size * 1.5
                    and abs(c.y1 - char.y1) <= c.size * 0.7
                    for c in glyphs
                ):
                    reading = "°"
            if reading and reading not in {"μ", "M"}:
                char.original_reading = char.get_text()
                char._text = reading
        for char in glyphs:
            if (char.an_resource_id, char.get_text()) not in degree_readings:
                continue
            if char.matrix[1] or char.matrix[2] or char.matrix[3] <= 0:
                continue
            neighbours = [
                c
                for c in glyphs
                if c is not char and abs(c.matrix[5] - char.matrix[5]) < 0.5
            ]
            if any(
                c.get_text() in {"C", "F"} and -1 <= c.x0 - char.x1 <= char.size * 0.6
                for c in neighbours
            ) and any(
                c.get_text().isdigit() and -1 <= char.x0 - c.x1 <= char.size * 1.5
                for c in neighbours
            ):
                degree_originals[id(char)] = char.get_text()
                ink = degree_readings[(char.an_resource_id, char.get_text())]
                char._text = "°"
                # The defective CID font's descent can place a raised ring on
                # the next text row. Use its verified ink bounds for this sign.
                char.set_bbox(
                    (
                        char.x0,
                        char.matrix[5] + ink[1] * char.size,
                        char.x1,
                        char.matrix[5] + ink[3] * char.size,
                    )
                )
        # Reassemble from real glyph bounds. Library text-line grouping can split
        # Chinese punctuation and superscripts into separate paragraphs.
        vertical, consumed = vertical_lines(
            glyphs,
            geometry.width,
            geometry.height,
            f"{self.name}@{self.version}",
            suspicious_text,
        )
        for char in glyphs:
            if id(char) in consumed and hasattr(char, "original_reading"):
                unit_repairs.append(
                    {
                        "code": "NATIVE_GLYPH_MAPPING_CORRECTED",
                        "page": page_number,
                        "bbox": [char.x0, char.y0, char.x1, char.y1],
                        "before": char.original_reading,
                        "after": char.get_text(),
                        "detail": "vertical glyph recovered from embedded shape; original mapping retained",
                    }
                )
        glyphs = [char for char in glyphs if id(char) not in consumed]
        rows: list[list[LTChar]] = []
        row_centers: list[float] = []
        row_sizes: list[float] = []
        margin_glyphs = 0
        ambiguous_glyphs = set()
        symbols = []
        for char in sorted(
            glyphs, key=lambda c: (-round(c.size), -(c.y0 + c.y1) / 2, c.x0)
        ):
            if not char.upright and (
                char.x1 < geometry.width * 0.08 or char.x0 > geometry.width * 0.92
            ):
                margin_glyphs += 1
                continue
            center = (char.y0 + char.y1) / 2
            matches = []
            for index, y in enumerate(row_centers):
                if char.size >= row_sizes[index] * 0.85:
                    if abs(center - y) <= max(2.0, row_sizes[index] * 0.35):
                        matches.append((abs(center - y), index))
                    continue
                # Smaller scripts belong to nearby base glyphs, not the global
                # row center (which may have been seeded in the other column).
                # An oversized decorative mark cannot serve as a text base.
                if any(
                    abs(c.size - char.size) <= char.size * 0.15
                    and abs(c.matrix[5] - char.matrix[5]) < 0.5
                    and max(0.0, char.x0 - c.x1, c.x0 - char.x1) <= char.size * 0.8
                    for c in rows[index]
                ):
                    matches.append((-1.0, index))
                    continue
                neighbours = [
                    c
                    for c in rows[index]
                    if c.size >= row_sizes[index] * 0.85
                    and (
                        c.get_text().isalnum()
                        or c.get_text() in "),.;:]}%\"'"
                        or suspicious_text(c.get_text())
                    )
                    and max(0.0, char.x0 - c.x1, c.x0 - char.x1) <= c.size * 0.8
                    and abs(center - (c.y0 + c.y1) / 2) <= max(2.0, c.size * 0.72)
                ]
                if neighbours:
                    matches.append(
                        (
                            min(abs(center - (c.y0 + c.y1) / 2) for c in neighbours),
                            index,
                        )
                    )
            if not matches:
                rows.append([char])
                row_centers.append(center)
                row_sizes.append(char.size)
            else:
                matches.sort()
                if (
                    len(matches) > 1
                    and char.size < row_sizes[matches[0][1]] * 0.85
                    and matches[1][0] - matches[0][0] < 0.5
                ):
                    ambiguous_glyphs.add(id(char))
                rows[min(matches)[1]].append(char)
        ambiguous_glyphs.update(_attach_inline_glyphs(rows))
        ambiguous_glyphs.update(_attach_nested_scripts(rows))
        # Repair only isolated signs. Leave already connected prose/formulas
        # in their original rows to avoid changing unrelated reading order.
        for row in rows:
            detached = [
                c
                for c in row
                if id(c) in degree_originals
                or (
                    c.get_text() in {"−", "°"}
                    and not any(
                        other is not c
                        and max(0, other.x0 - c.x1, c.x0 - other.x1)
                        <= max(3, max(c.size, other.size) * 0.6)
                        for other in row
                    )
                )
            ]
            symbols.extend(detached)
            row[:] = [c for c in row if c not in detached]
        rows = [row for row in rows if row]
        ambiguous_rows = _attach_symbols(rows, symbols)
        lines = list(vertical)
        for row_index, row in enumerate(rows):
            segments: list[list[LTChar]] = [[]]
            for char in sorted(row, key=lambda c: c.x0):
                segment = segments[-1]
                ink = [c for c in segment if not c.get_text().isspace()]
                gap = (
                    char.x0 - max(c.x1 for c in ink)
                    if ink and not char.get_text().isspace()
                    else 0
                )
                across_column = (
                    segment
                    and segment[0].x0 < geometry.width * 0.4
                    and abs(
                        (max(c.x1 for c in segment) + char.x0) / 2
                        - geometry.width * 0.5
                    )
                    < geometry.width * 0.05
                )
                if segment and (
                    gap > max(10, statistics.median(c.size for c in segment) * 1.6)
                    or across_column
                    and gap > max(6, char.size * 0.8)
                ):
                    segments.append([])
                segments[-1].append(char)
            for chars in segments:
                parts = []
                original_parts = []
                glyph_spans = []
                review_offsets = set()
                right = None
                uncertain_font = False
                unit_positions = {}
                outline_positions = {}
                glyph_corrections = []
                for char in _ordered_glyphs(chars):
                    reading_box = getattr(char, "reading_bbox", char.bbox)
                    if right is not None and reading_box[0] - right > char.size * 0.13:
                        parts.append(" ")
                        original_parts.append(" ")
                    original_parts.append(
                        getattr(char, "original_reading", char.get_text())
                    )
                    key = (char.an_resource_id, char.get_text())
                    if hasattr(char, "original_reading"):
                        glyph_corrections.append(
                            {"before": char.original_reading, "after": char.get_text()}
                        )
                    if key in outline_units:
                        outline_positions[sum(map(len, parts))] = outline_units[key]
                    replacement = symbol_readings.get(key)
                    if char.get_text() == "m" and char.an_resource_id in unit_readings:
                        unit_positions[sum(map(len, parts))] = unit_readings[
                            char.an_resource_id
                        ]
                    if (
                        char.get_text() == "m"
                        and getattr(char, "outline_reading", None) == "M"
                    ):
                        unit_positions[sum(map(len, parts))] = "M"
                    value = replacement if replacement else char.get_text()
                    if getattr(char, "outline_reading", None) == "μ":
                        # Use the painted unit prefix only in a unit token.
                        # Doing this at glyph level keeps offsets correct when
                        # a multi-character CID placeholder is replaced.
                        tail = sorted(
                            (
                                c
                                for c in chars
                                if c.x0 > char.x0 + 0.1 and c is not char
                            ),
                            key=lambda c: c.x0,
                        )
                        following = "".join(
                            (" " if i and c.x0 - tail[i - 1].x1 > c.size * 0.13 else "")
                            + c.get_text()
                            for i, c in enumerate(tail)
                        )
                        if re.match(r"\s*(?:mol|[mglLAsF])(?:[^A-Za-z]|$)", following):
                            glyph_corrections.append({"before": value, "after": "μ"})
                            value = "μ"
                    offset = sum(map(len, parts))
                    glyph_spans.append((offset, offset + len(value), char.x0, char.x1))
                    if (
                        key in unmapped
                        or replacement is not None
                        or value != char.get_text()
                        or hasattr(char, "original_reading")
                        or suspicious_text(value)
                        or id(char) in degree_originals
                    ):
                        review_offsets.update(range(offset, offset + len(value)))
                    parts.append(value)
                    recovered_count += int(replacement is not None)
                    uncertain_font |= key in unmapped
                    right = max(right or reading_box[2], reading_box[2])
                raw_text = "".join(parts)
                characters = list(raw_text)
                for offset, reading in outline_positions.items():
                    prefix, suffix = raw_text[:offset], raw_text[offset + 1 :]
                    if (reading == "℃" and re.search(r"[\d/／]\s*$", prefix)) or (
                        reading == "m"
                        and re.search(r"[/／·⋅]\s*$", prefix)
                        and re.match(r"(?:[23²³⁻−\-·⋅/\s)]|$)", suffix)
                    ):
                        characters[offset] = reading
                for match in re.finditer(
                    r"(?:^|(?<=[\d(\s]))\s*∘\s*(?=[CF](?![A-Za-z]))", raw_text
                ):
                    # A verified circular glyph adjacent to a numerical
                    # temperature/unit has the degree role, even if PDF bounds
                    # made the earlier per-character adjacency test ambiguous.
                    characters[raw_text.index("∘", match.start(), match.end())] = "°"
                for match in re.finditer(
                    r"(?<![\w.])(?:\d+(?:\.\d+)?|\.\d+)\s*(mm|m)(?!\w)", raw_text
                ):
                    offset = match.start(1)
                    reading = unit_positions.get(offset)
                    if (match[1], reading) in {("mm", "μ"), ("m", "M")}:
                        characters[offset] = reading
                    # A millimolar unit can combine a normal prefix m with a
                    # small-cap M from a different embedded font/encoding.
                    last = match.end(1) - 1
                    if unit_positions.get(last) == "M":
                        characters[last] = "M"
                # A proven mu outline can prefix a unit even when a numerator
                # intervenes (ng mL-1). A real millilitre m has no such proof.
                for offset, reading in unit_positions.items():
                    if reading == "μ" and re.match(
                        r"m(?:mol|[mglLAsF])(?=$|[^A-Za-z]|[A-Za-z]+(?:[−⁻+-]?\d|[²³]))",
                        raw_text[offset:],
                    ):
                        characters[offset] = reading
                text = "".join(characters).strip()
                review_offsets.update(
                    i for i, (a, b) in enumerate(zip(raw_text, characters)) if a != b
                )
                unit_corrected = text != raw_text.strip()
                degree_corrected = any(id(c) in degree_originals for c in chars)
                if not text:
                    continue
                # PDF writers may append invisible spaces across an entire
                # column. They must not expand a numeric cell or its anchor.
                ink_chars = [c for c in chars if c.get_text().strip()]
                x0, y0 = min(c.x0 for c in ink_chars), min(c.y0 for c in ink_chars)
                x1, y1 = max(c.x1 for c in ink_chars), max(c.y1 for c in ink_chars)
                x0, x1 = max(0.0, x0), min(geometry.width, x1)
                y0, y1 = max(0.0, y0), min(geometry.height, y1)
                if x1 <= x0 or y1 <= y0:
                    continue
                uncertain = (
                    suspicious_text(text)
                    or uncertain_font
                    or unit_corrected
                    or degree_corrected
                    or row_index in ambiguous_rows
                    or any(id(c) in ambiguous_glyphs for c in chars)
                    or bool(glyph_corrections)
                )
                if (
                    review_offsets
                    and row_index not in ambiguous_rows
                    and not any(id(c) in ambiguous_glyphs for c in chars)
                ):
                    left_trim = len(raw_text) - len(raw_text.lstrip())
                    unit_repairs.append(
                        {
                            "code": "NATIVE_GLYPH_CONTEXT",
                            "page": page_number,
                            "bbox": [x0, y0, x1, y1],
                            "after": text,
                            "text_offsets": sorted(
                                i - left_trim
                                for i in review_offsets
                                if left_trim <= i < left_trim + len(text)
                            ),
                            "detail": "These native glyph offsets require local reading; neighbouring decoded text is retained.",
                        }
                    )
                if glyph_corrections:
                    unit_repairs.append(
                        {
                            "code": (
                                "NATIVE_UNIT_MAPPING_CORRECTED"
                                if any(c["after"] == "μ" for c in glyph_corrections)
                                else "NATIVE_GLYPH_MAPPING_CORRECTED"
                            ),
                            "page": page_number,
                            "bbox": [x0, y0, x1, y1],
                            "corrections": glyph_corrections,
                            "before": "".join(original_parts).strip(),
                            "after": text,
                            "detail": "readings recovered from embedded font programs; original mappings retained",
                        }
                    )
                if unit_corrected:
                    unit_repairs.append(
                        {
                            "code": "NATIVE_UNIT_MAPPING_CORRECTED",
                            "page": page_number,
                            "bbox": [x0, y0, x1, y1],
                            "before": raw_text.strip(),
                            "after": text,
                            "detail": "unit mapping contradicts embedded glyph outline; original reading retained here, corrected reading remains uncertain",
                        }
                    )
                if degree_corrected:
                    unit_repairs.append(
                        {
                            "code": "NATIVE_DEGREE_MAPPING_CORRECTED",
                            "page": page_number,
                            "bbox": [x0, y0, x1, y1],
                            "original_mappings": sorted(
                                {
                                    degree_originals[id(c)]
                                    for c in chars
                                    if id(c) in degree_originals
                                }
                            ),
                            "after": text,
                            "detail": "explicit Unicode mapping contradicts an embedded raised circular ring; corrected reading remains uncertain",
                        }
                    )
                lines.append(
                    LayoutLine(
                        text=text,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        font_size=max(1.0, statistics.median(c.size for c in chars)),
                        dominant_font=_dominant_font(chars),
                        bold=sum(
                            any(
                                name in c.fontname.casefold()
                                for name in ("bold", "black", "heavy", "demi")
                            )
                            for c in chars
                        )
                        > len(chars) / 2,
                        extraction_method="pdfminer-glyph-layout",
                        extraction_confidence=0.5 if uncertain else 1.0,
                        source_engines=(f"{self.name}@{self.version}",),
                        uncertain=uncertain,
                        glyph_spans=tuple(
                            (
                                a - len(raw_text) + len(raw_text.lstrip()),
                                b - len(raw_text) + len(raw_text.lstrip()),
                                x0,
                                x1,
                            )
                            for a, b, x0, x1 in glyph_spans
                            if raw_text[a:b].strip()
                        ),
                    )
                )
        warnings = list(unit_repairs)
        if device.corrected_glyphs:
            warnings.append(
                {
                    "code": "NATIVE_GLYPH_BOUNDS_CORRECTED",
                    "page": page_number,
                    "detail": f"{device.corrected_glyphs} glyph boxes use embedded outlines because font metrics are displaced or degenerate; text mappings unchanged",
                }
            )
        if ambiguous_glyphs:
            warnings.append(
                {
                    "code": "NATIVE_AMBIGUOUS_GLYPH_ROW",
                    "page": page_number,
                    "detail": f"{len(ambiguous_glyphs)} small glyphs have competing local text baselines; affected lines remain uncertain",
                }
            )
        if clipped_glyphs:
            warnings.append(
                {
                    "code": "NATIVE_CLIPPED_TEXT_OMITTED",
                    "page": page_number,
                    "detail": f"omitted {clipped_glyphs} glyphs wholly outside their enclosing PDF Form display bounds",
                }
            )
        if ambiguous_rows:
            warnings.append(
                {
                    "code": "NATIVE_DETACHED_SYMBOL",
                    "page": page_number,
                    "detail": "minus/degree glyph has no unique neighbouring text row; glyph and affected rows remain uncertain",
                }
            )
        if recovered_count:
            warnings.append(
                {
                    "code": "NATIVE_FONT_SYMBOL_RECOVERED",
                    "detail": f"page {page_number}: recovered {recovered_count} unmapped symbols from embedded glyph outlines; readings remain uncertain",
                    "page": page_number,
                }
            )
        if margin_glyphs:
            warnings.append(
                {
                    "code": "MARGIN_TEXT_OMITTED",
                    "detail": f"page {page_number}: omitted {margin_glyphs} rotated outer-margin glyphs",
                    "page": page_number,
                }
            )
        if any(line.uncertain for line in lines):
            warnings.append(
                {
                    "code": "NATIVE_GLYPH_UNCERTAIN",
                    "detail": f"page {page_number}: native text contains missing/ambiguous glyphs; consult the PDF or enable OCR",
                    "page": page_number,
                }
            )
        objects = _page_objects(copied, geometry)
        try:
            outlined_text = vector_text_regions(
                vector_shapes, lines, geometry.width, geometry.height
            )
        except VectorTextLimitError as exc:
            outlined_text = (exc.region,)
            warnings.append(
                {
                    "code": "VECTOR_TEXT_SCAN_LIMIT",
                    "page": page_number,
                    "bbox": list(exc.region.bbox),
                    "source_object": exc.region.name,
                    "detail": f"{exc}; native text is retained, but this drawing region needs visual review or OCR.",
                }
            )
        objects = (*objects, *outlined_text)
        for obj in outlined_text:
            warnings.append(
                {
                    "code": "VECTOR_TEXT_UNVERIFIED",
                    "page": page_number,
                    "bbox": list(obj.bbox),
                    "source_object": obj.name,
                    "detail": "Painted outlines have no verified native text reading. Their values, symbols and units need local OCR or source review; geometry alone does not establish a reading.",
                }
            )
        if any(
            o.object_type == "image"
            and o.bbox
            and (o.bbox[2] - o.bbox[0]) * (o.bbox[3] - o.bbox[1]) > 0.8
            for o in objects
        ):
            warnings.append(
                {
                    "code": "IMAGE_DOMINANT_PAGE",
                    "detail": f"page {page_number}: a page-sized image may contain text not reliably represented by the native text layer",
                    "page": page_number,
                }
            )
        return PageLayout(
            page=page_number,
            width=geometry.width,
            height=geometry.height,
            media_box=geometry.media_box,
            crop_box=geometry.crop_box,
            rotation=geometry.rotation,
            lines=tuple(lines),
            objects=objects,
            warnings=tuple(warnings),
        )
