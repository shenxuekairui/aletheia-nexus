"""Source-preserving spreadsheet reading; all fixtures are synthetic OOXML."""

import hashlib
import json
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from aletheia_nexus.processing.native_table import (
    CELL_COLUMNS,
    NATIVE_TABLE_SCHEMA,
    NATIVE_TABLE_VERSION,
    NativeTableLimitError,
    native_table_notes,
    read_native_xlsx,
)

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "原始数据.xlsx"
    sheet = f'''<worksheet xmlns="{S}"><dimension ref="A1:G9"/>
    <sheetData>
      <row r="1" spans="1:7"><c r="A1" t="s"><v>0</v></c><c r="E1" t="inlineStr"><is><t>Other region</t></is></c></row>
      <row r="2" spans="1:7"><c r="A2" t="s"><v>1</v></c><c r="B2" s="1"><v>0.000</v></c><c r="E2" t="inlineStr"><is><t xml:space="preserve"> α µM 10⁻³ </t></is></c><c r="F2" t="b"><v>0</v></c><c r="G2" s="1"/></row>
      <row r="3" spans="1:7"><c r="C3" s="1"><f t="shared" si="0" ref="C3:C5">A3+B3</f><v>0</v></c></row>
      <row r="4" spans="1:7"><c r="C4"><f t="shared" si="0"/><v/></c></row>
      <row r="5" spans="1:7"><c r="C5"><f t="shared" si="0"/></c></row>
      <row r="6" spans="1:7"><c r="D6" t="e"><v>#N/A</v></c></row>
      <row r="7" spans="1:7"><c r="A7" t="s"><v>2</v></c></row>
      <row r="8" spans="1:7"><c r="C8" t="str"><f t="array" ref="C8:D8">CONCAT(A1,A2)</f><v>not recalculated</v></c></row>
      <row r="9" spans="1:7"/>
    </sheetData><mergeCells count="3"><mergeCell ref="A1:C1"/><mergeCell ref="E1:F1"/><mergeCell ref="E5:F6"/></mergeCells>
    <drawing xmlns:r="{R}" r:id="picture1"/><conditionalFormatting sqref="B2"><cfRule type="cellIs" priority="1" operator="greaterThan"><formula>0</formula></cfRule></conditionalFormatting>
    </worksheet>'''
    large = (
        f'<worksheet xmlns="{S}"><dimension ref="A1:A200"/><sheetData>'
        + "".join(
            f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, 201)
        )
        + "</sheetData></worksheet>"
    )
    format_code = escape('"µ" 0.000', {'"': "&quot;"})
    parts = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
        "_rels/.rels": f'<Relationships xmlns="{P}"><Relationship Id="book" Type="{R}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Small" sheetId="1" r:id="s1"/><sheet name="Large" sheetId="2" state="hidden" r:id="s2"/></sheets><definedNames><definedName name="Example">Small!$A$1</definedName></definedNames><externalReferences><externalReference r:id="external1"/></externalReferences></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{P}"><Relationship Id="s1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="s2" Type="{R}/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="ss" Type="{R}/sharedStrings" Target="sharedStrings.xml"/><Relationship Id="style" Type="{R}/styles" Target="styles.xml"/><Relationship Id="external1" Type="{R}/externalLink" Target="externalLinks/externalLink1.xml"/></Relationships>',
        "xl/styles.xml": f'<styleSheet xmlns="{S}"><numFmts count="1"><numFmt numFmtId="164" formatCode="{format_code}"/></numFmts><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        "xl/sharedStrings.xml": f'<sst xmlns="{S}" count="3" uniqueCount="3"><si><t>Header µM</t></si><si><r><t>H</t></r><r><rPr><vertAlign val="subscript"/></rPr><t>2</t></r><r><t>O</t></r></si><si><t>_x000A_ retained</t></si></sst>',
        "xl/worksheets/sheet1.xml": sheet,
        "xl/worksheets/sheet2.xml": large,
        "xl/worksheets/_rels/sheet1.xml.rels": f'<Relationships xmlns="{P}"><Relationship Id="picture1" Type="{R}/drawing" Target="../drawings/drawing1.xml"/></Relationships>',
        "xl/drawings/drawing1.xml": '<wsDr xmlns="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"/>',
        "xl/externalLinks/externalLink1.xml": f'<externalLink xmlns="{S}" xmlns:r="{R}"><externalBook r:id="file1"><sheetNames><sheetName val="Data"/></sheetNames></externalBook></externalLink>',
        "xl/externalLinks/_rels/externalLink1.xml.rels": f'<Relationships xmlns="{P}"><Relationship Id="file1" Type="{R}/externalLinkPath" Target="file:///unavailable-original.xlsx" TargetMode="External"/></Relationships>',
    }
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        "</Types>",
        '<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        '<Override PartName="/xl/externalLinks/externalLink1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml"/></Types>',
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return path


def cells(view):
    return {
        cell[0] + str(row["row"]): dict(zip(CELL_COLUMNS, cell))
        for row in view["sheets"][0]["rows"]
        for cell in row["cells"]
    }


def test_complete_coordinates_merges_literals_formats_and_read_only(workbook):
    original = workbook.read_bytes()
    view = read_native_xlsx(workbook, sheets=["Small"])
    assert view["schema"] == NATIVE_TABLE_SCHEMA
    assert view["version"] == NATIVE_TABLE_VERSION
    assert view["source_workbook_sha256"] == hashlib.sha256(original).hexdigest()
    assert workbook.read_bytes() == original
    assert view["complete_selected_sheet_cell_view"] is True
    sheet = view["sheets"][0]
    assert sheet["merged_ranges"] == ["A1:C1", "E1:F1", "E5:F6"]
    assert sheet["rows"][0]["span"] == "1:7"
    assert sheet["styled_empty_cells"] == 1
    assert sheet["populated_cells"] == 12
    assert sheet["rows"][-1] == {"row": 9, "span": "1:7", "cells": []}
    got = cells(view)
    assert got["A1"]["literal"] == "Header µM"
    assert got["A1"]["type"] == "s" and got["A1"]["value_literal"] == "0"
    assert got["B2"]["literal"] == "0.000"
    assert got["B2"]["number_format"] == '"µ" 0.000'
    assert got["E2"]["literal"] == " α µM 10⁻³ "
    assert got["F2"]["literal"] == "0" and got["F2"]["type"] == "b"
    assert got["D6"]["literal"] == "#N/A" and got["D6"]["type"] == "e"
    assert view["unselected_sheets"] == [
        {"sheet": "Large", "state": "hidden", "reason": "not_selected_by_user_not_read"}
    ]


def test_shared_formula_declaration_and_missing_empty_zero_caches(workbook):
    got = cells(read_native_xlsx(workbook, sheets=["Small"]))
    assert got["C3"]["formula"] == "A3+B3"
    assert got["C3"]["formula_attributes"] == {"t": "shared", "si": "0", "ref": "C3:C5"}
    assert got["C3"]["cache_state"] == "cached" and got["C3"]["literal"] == "0"
    assert got["C4"]["formula"] is None and got["C4"]["formula_attributes"] == {
        "t": "shared",
        "si": "0",
    }
    assert got["C4"]["cache_state"] == "empty"
    assert got["C5"]["cache_state"] == "missing"
    assert got["C8"]["literal"] == "not recalculated"
    assert got["C8"]["formula_attributes"] == {"t": "array", "ref": "C8:D8"}


def test_rich_subscripts_and_unsupported_features_are_explicit(workbook):
    view = read_native_xlsx(workbook, sheets=["Small"])
    assert cells(view)["A2"]["literal"] == "H2O"
    runs = view["sheets"][0]["rich_text"]["A2"]
    assert "subscript" in runs[1]["properties_xml"]
    assert {
        "drawing_metadata_not_interpreted",
        "conditionalFormatting_metadata_not_interpreted",
        "external_workbook_references_not_resolved",
        "defined_names_not_interpreted",
        "OOXML_string_escape_sequences_retained_not_decoded",
    } <= set(view["warnings"])


def test_selected_sheet_budget_never_chooses_small_sheets_silently(workbook):
    with pytest.raises(NativeTableLimitError, match="select fewer sheets") as failure:
        read_native_xlsx(workbook, max_cells=50)
    assert failure.value.available_sheets == ["Small", "Large"]
    selected = read_native_xlsx(workbook, sheets=["Small"], max_cells=50)
    assert selected["populated_cells"] == 12
    assert read_native_xlsx(workbook)["populated_cells"] == 212
    with pytest.raises(NativeTableLimitError, match="max_uncompressed_bytes"):
        read_native_xlsx(workbook, sheets=["Small"], max_uncompressed_bytes=100)
    # Unselected large sheets are not decompressed or charged to this budget.
    used = selected["resource_usage"]["uncompressed_bytes_read"]
    assert (
        read_native_xlsx(workbook, sheets=["Small"], max_uncompressed_bytes=used)[
            "populated_cells"
        ]
        == 12
    )
    with pytest.raises(NativeTableLimitError, match="max_uncompressed_bytes"):
        read_native_xlsx(workbook, max_uncompressed_bytes=used)


@pytest.mark.parametrize("selection", [[], ["Missing"], ["Small", "Small"], "Small"])
def test_explicit_invalid_sheet_selection(workbook, selection):
    with pytest.raises(ValueError):
        read_native_xlsx(workbook, sheets=selection)


def test_notes_contain_full_provenance_or_fail_without_truncation(workbook):
    view = read_native_xlsx(workbook, sheets=["Small"])
    notes = native_table_notes(view)
    decoded = json.loads(notes.split("\n", 1)[1])
    assert decoded["source_workbook_sha256"] == view["source_workbook_sha256"]
    assert decoded["sheets"][0]["rows"] == [
        {**row, "cells": [cell[:6] for cell in row["cells"]]}
        for row in view["sheets"][0]["rows"]
    ]
    assert decoded["sheets"][0]["formula_declarations"]["C4"] == {
        "t": "shared",
        "si": "0",
    }
    assert decoded["sheets"][0]["rich_text"]["A2"][1] == {
        "text": "2",
        "vertical_align": "subscript",
    }
    assert "properties_xml" not in notes
    assert "µM" in notes and "10⁻³" in notes
    with pytest.raises(NativeTableLimitError, match="no truncated notes"):
        native_table_notes(view, max_chars=100)
