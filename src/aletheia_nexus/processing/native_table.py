"""Read-only XLSX coordinate evidence, without formula or scientific inference.

This is a selected-sheet cell view, not a spreadsheet renderer. The original
workbook remains authoritative; drawings, charts and formula results are never
generated here. Callers can attach the complete JSON view to document.notes.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NATIVE_TABLE_VERSION = "1"
NATIVE_TABLE_SCHEMA = "aletheia-nexus/native-source-grid/v1"
CELL_COLUMNS = [
    "column",
    "literal",
    "type",
    "formula",
    "cache_state",
    "number_format",
    "formula_attributes",
    "value_literal",
    "style_id",
]


class NativeTableLimitError(ValueError):
    """A complete source view exceeds an explicit resource budget."""


# IDs with locale-dependent displays retain the original ID rather than guessing
# a display string. Custom format codes are read verbatim from styles.xml.
_BUILTIN_FORMATS = {
    0: "General",
    1: "0",
    2: "0.00",
    3: "#,##0",
    4: "#,##0.00",
    9: "0%",
    10: "0.00%",
    11: "0.00E+00",
    12: "# ?/?",
    13: "# ??/??",
    14: "mm-dd-yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    37: "#,##0 ;(#,##0)",
    38: "#,##0 ;[Red](#,##0)",
    39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;[Red](#,##0.00)",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "mmss.0",
    48: "##0.0E+0",
    49: "@",
}


def _children(node, name):
    return [n for n in node if n.tag.rsplit("}", 1)[-1] == name]


def _child(node, name):
    return next(iter(_children(node, name)), None)


def _part(base, target):
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    if target.startswith("/"):
        path = posixpath.normpath(target.lstrip("/"))
    if path.startswith("../") or path == "..":
        raise ValueError("XLSX relationship escapes the package")
    return path


def _relationships(archive, part, read_part):
    relpath = posixpath.join(
        posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
    )
    if relpath not in archive.namelist():
        return {}
    return {r.attrib["Id"]: r.attrib for r in ET.fromstring(read_part(relpath))}


def _string(node):
    """Display text excludes phonetic annotations; rich run properties survive."""
    runs = _children(node, "r")
    if not runs:
        text = _child(node, "t")
        return (text.text or "") if text is not None else "", []
    items = []
    for run in runs:
        text, props = _child(run, "t"), _child(run, "rPr")
        items.append(
            {
                "text": (text.text or "") if text is not None else "",
                "properties_xml": ET.tostring(props, encoding="unicode")
                if props is not None
                else None,
            }
        )
    return "".join(r["text"] for r in items), items


def _styles(read_part, part):
    if not part:
        return [{"numFmtId": 0, "formatCode": "General", "origin": "default"}]
    root = ET.fromstring(read_part(part))
    formats = _child(root, "numFmts")
    custom = (
        {int(n.attrib["numFmtId"]): n.attrib["formatCode"] for n in formats}
        if formats is not None
        else {}
    )
    xfs = _child(root, "cellXfs")
    if xfs is None:
        return [{"numFmtId": 0, "formatCode": "General", "origin": "default"}]
    out = []
    for xf in xfs:
        ident = int(xf.get("numFmtId", "0"))
        code = custom.get(ident, _BUILTIN_FORMATS.get(ident))
        out.append(
            {
                "numFmtId": ident,
                "formatCode": code,
                "origin": "custom" if ident in custom else "builtin",
                "xf_attributes": dict(xf.attrib),
            }
        )
    return out


def read_native_xlsx(
    path: str | Path,
    *,
    sheets: list[str] | tuple[str, ...] | None = None,
    max_cells: int = 10_000,
    max_uncompressed_bytes: int = 64 * 1024 * 1024,
) -> dict:
    """Read every populated/formula cell of explicitly selected sheets, in order.

    Numbers, units and cached formula values remain source strings. Shared formula
    followers retain their declarations; formulas are not expanded or evaluated.
    Cell or archive budgets fail explicitly, never return a truncated table.
    Other worksheets are listed as unselected, not implicitly read in full.
    """
    if (
        type(max_cells) is not int
        or max_cells < 1
        or type(max_uncompressed_bytes) is not int
        or max_uncompressed_bytes < 1
    ):
        raise ValueError("XLSX resource limits must be positive integers")
    if sheets is not None and (
        isinstance(sheets, str) or not sheets or len(set(sheets)) != len(sheets)
    ):
        raise ValueError(
            "sheets must be a nonempty sequence of unique exact sheet names"
        )
    path = Path(path)
    with path.open("rb") as source:
        source_hash = hashlib.file_digest(source, "sha256").hexdigest()
    warnings = {
        "charts_drawings_and_display_layout_not_rendered",
        "formula_caches_are_unverified_not_recalculated",
    }
    result = {
        "schema": NATIVE_TABLE_SCHEMA,
        "version": NATIVE_TABLE_VERSION,
        "source_workbook_sha256": source_hash,
        "source_filename": path.name,
        "cell_columns": CELL_COLUMNS.copy(),
        "representation": "Original column plus enclosing row identifies each cell. All selected populated/formula cells are retained with source literals, types, formula/cache and format metadata. No scientific headers, units or values are inferred. Styled empty cells are counted; row positions and merged ranges are retained. This is not a rendered workbook or proof of scientific correctness.",
        "sheets": [],
        "unselected_sheets": [],
    }
    with ZipFile(path) as archive:
        read_parts = set()
        uncompressed_bytes = 0

        def read_part(part):
            nonlocal uncompressed_bytes
            if part not in read_parts:
                uncompressed_bytes += archive.getinfo(part).file_size
                if uncompressed_bytes > max_uncompressed_bytes:
                    raise NativeTableLimitError(
                        "Selected XLSX parts exceed max_uncompressed_bytes; select fewer sheets or explicitly raise the limit; no view returned"
                    )
                read_parts.add(part)
            return archive.read(part)

        workbook_part = "xl/workbook.xml"
        if "_rels/.rels" in archive.namelist():
            for relation in ET.fromstring(read_part("_rels/.rels")):
                if relation.get("Type", "").endswith("/officeDocument"):
                    workbook_part = _part("", relation.attrib["Target"])
        workbook = ET.fromstring(read_part(workbook_part))
        relationships = _relationships(archive, workbook_part, read_part)
        shared_part = next(
            (
                _part(workbook_part, r["Target"])
                for r in relationships.values()
                if r.get("Type", "").endswith("/sharedStrings")
            ),
            None,
        )
        styles_part = next(
            (
                _part(workbook_part, r["Target"])
                for r in relationships.values()
                if r.get("Type", "").endswith("/styles")
            ),
            None,
        )
        shared = (
            [_string(n) for n in ET.fromstring(read_part(shared_part))]
            if shared_part
            else []
        )
        result["styles"] = styles = _styles(read_part, styles_part)
        sheet_list = _child(workbook, "sheets")
        if sheet_list is None:
            raise ValueError("XLSX workbook has no sheets")
        known = {s.attrib["name"] for s in sheet_list}
        if sheets is not None and not set(sheets) <= known:
            raise ValueError(
                "Unknown XLSX sheets: " + ", ".join(sorted(set(sheets) - known))
            )
        total = 0
        for source in sheet_list:
            name = source.attrib["name"]
            if sheets is not None and name not in sheets:
                result["unselected_sheets"].append(
                    {
                        "sheet": name,
                        "state": source.get("state", "visible"),
                        "reason": "not_selected_by_user_not_read",
                    }
                )
                continue
            rid = next(
                v for k, v in source.attrib.items() if k.rsplit("}", 1)[-1] == "id"
            )
            rel = relationships[rid]
            if rel.get("TargetMode") == "External" or not rel.get("Type", "").endswith(
                "/worksheet"
            ):
                raise ValueError(
                    f"Selected sheet {name!r} is external or not a worksheet; select supported worksheets explicitly"
                )
            part = _part(workbook_part, rel["Target"])
            sheet_raw = read_part(part)
            root = ET.fromstring(sheet_raw)
            dimension = _child(root, "dimension")
            merges = _child(root, "mergeCells")
            sheet = {
                "sheet": name,
                "state": source.get("state", "visible"),
                "source_part": part,
                "source_part_sha256": hashlib.sha256(sheet_raw).hexdigest(),
                "dimension": dimension.get("ref") if dimension is not None else None,
                "merged_ranges": [n.attrib["ref"] for n in merges]
                if merges is not None
                else [],
                "rows": [],
                "populated_cells": 0,
                "styled_empty_cells": 0,
                "rich_text": {},
            }
            data = _child(root, "sheetData")
            if data is not None:
                for row in data:
                    target = {
                        "row": int(row.attrib["r"]),
                        "span": row.get("spans"),
                        "cells": [],
                    }
                    for cell in _children(row, "c"):
                        coord = cell.attrib["r"]
                        match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", coord)
                        if not match or int(match[2]) != target["row"]:
                            raise ValueError(
                                f"Invalid XLSX cell coordinate or row: {coord!r}"
                            )
                        value, formula, inline = (
                            _child(cell, "v"),
                            _child(cell, "f"),
                            _child(cell, "is"),
                        )
                        if value is None and formula is None and inline is None:
                            sheet["styled_empty_cells"] += 1
                            continue
                        total += 1
                        if total > max_cells:
                            raise NativeTableLimitError(
                                f"Selected XLSX sheets exceed max_cells={max_cells}; select fewer sheets or explicitly raise the limit; no partial view returned"
                            )
                        kind, literal, rich = (
                            cell.get("t", "n"),
                            value.text if value is not None else None,
                            [],
                        )
                        if kind == "s":
                            index = int(literal)
                            if not 0 <= index < len(shared):
                                raise ValueError(
                                    f"Unknown XLSX shared string {literal!r} at {coord}"
                                )
                            literal, rich = shared[index]
                        elif inline is not None:
                            literal, rich = _string(inline)
                        style = int(cell.get("s", "0"))
                        if not 0 <= style < len(styles):
                            raise ValueError(
                                f"Unknown XLSX cell style {style} at {coord}"
                            )
                        cache = (
                            "not_a_formula"
                            if formula is None
                            else "missing"
                            if value is None
                            else "empty"
                            if value.text is None
                            else "cached"
                        )
                        target["cells"].append(
                            [
                                match[1],
                                literal,
                                kind,
                                formula.text if formula is not None else None,
                                cache,
                                styles[style]["formatCode"],
                                dict(formula.attrib) if formula is not None else None,
                                value.text if value is not None else None,
                                style,
                            ]
                        )
                        sheet["populated_cells"] += 1
                        if rich:
                            sheet["rich_text"][coord] = rich
                        if isinstance(literal, str) and re.search(
                            r"_x[0-9A-Fa-f]{4}_", literal
                        ):
                            warnings.add(
                                "OOXML_string_escape_sequences_retained_not_decoded"
                            )
                    sheet["rows"].append(target)
            for tag in [
                "drawing",
                "legacyDrawing",
                "tableParts",
                "conditionalFormatting",
                "dataValidations",
                "extLst",
            ]:
                if _child(root, tag) is not None:
                    warnings.add(tag + "_metadata_not_interpreted")
            result["sheets"].append(sheet)
        if _child(workbook, "externalReferences") is not None:
            warnings.add("external_workbook_references_not_resolved")
        if _child(workbook, "definedNames") is not None:
            warnings.add("defined_names_not_interpreted")
        if any(s["formatCode"] is None for s in styles):
            warnings.add("unresolved_builtin_number_format_ID_preserved_not_guessed")
    result.update(
        populated_cells=total,
        complete_selected_sheet_cell_view=True,
        warnings=sorted(warnings),
        resource_usage={
            "uncompressed_bytes_read": uncompressed_bytes,
            "parts_read": sorted(read_parts),
        },
    )
    return result


def native_table_notes(view: dict, *, max_chars: int = 200_000) -> str:
    """All scientific cells for document.notes; raw style XML stays in local view."""
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")

    def semantic_runs(runs):
        out = []
        for run in runs:
            item = {"text": run["text"]}
            if run["properties_xml"]:
                props = ET.fromstring(run["properties_xml"])
                for tag, key in [
                    ("vertAlign", "vertical_align"),
                    ("b", "bold"),
                    ("i", "italic"),
                ]:
                    node = _child(props, tag)
                    if node is not None:
                        item[key] = node.get("val", "true")
            out.append(item)
        return out

    sheets = []
    for sheet in view["sheets"]:
        declarations, unresolved = {}, {}
        for row in sheet["rows"]:
            for cell in row["cells"]:
                coord = cell[0] + str(row["row"])
                if cell[6]:
                    declarations[coord] = cell[6]
                if cell[5] is None:
                    unresolved[coord] = view["styles"][cell[8]]["numFmtId"]
        sheets.append(
            {
                **sheet,
                "rows": [
                    {**row, "cells": [cell[:6] for cell in row["cells"]]}
                    for row in sheet["rows"]
                ],
                "formula_declarations": declarations,
                "unresolved_number_format_ids": unresolved,
                "rich_text": {
                    coord: semantic_runs(runs)
                    for coord, runs in sheet["rich_text"].items()
                },
            }
        )
    projection = {
        **{key: value for key, value in view.items() if key != "styles"},
        "notes_presentation_version": "2",
        "cell_columns": CELL_COLUMNS[:6],
        "sheets": sheets,
    }
    text = (
        "Native XLSX coordinate evidence (derived; original workbook SHA identifies source):\n"
        + json.dumps(
            projection, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    )
    if len(text) > max_chars:
        raise NativeTableLimitError(
            f"Complete XLSX notes exceed max_chars={max_chars}; select fewer sheets or explicitly raise the limit; no truncated notes returned"
        )
    return text
