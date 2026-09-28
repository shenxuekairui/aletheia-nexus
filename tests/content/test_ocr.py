from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader
from pypdf.generic import FloatObject, NameObject

from aletheia_nexus.content import (
    AdaptiveOcrBackend,
    AdaptiveOcrConfig,
    NativePdfBackend,
    TesseractOcrBackend,
    TesseractOcrConfig,
    parse_document,
    validate_parsed_document,
)
from aletheia_nexus.content.backends.tesseract import _parse_tsv
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageObject

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "v07_fixtures"


class _StaticBackend:
    version = "1"

    def __init__(self, name: str, lines: tuple[LayoutLine, ...]) -> None:
        self.name = name
        self.lines = lines

    def extract_page(self, page, page_number):
        del page
        return PageLayout(
            page=page_number,
            width=600,
            height=800,
            lines=self.lines,
        )


def _ocr_line(text: str, confidence: float, engine: str) -> LayoutLine:
    return LayoutLine(
        text,
        60,
        400,
        300,
        420,
        12,
        extraction_method="test-ocr",
        extraction_confidence=confidence,
        source_engines=(engine,),
    )


def test_adaptive_ocr_preserves_native_and_adds_only_consensus_gap():
    native_line = LayoutLine(
        "Native text is authoritative.",
        60,
        700,
        300,
        720,
        12,
        source_engines=("native@1",),
    )
    native = _StaticBackend(
        "native",
        (native_line,),
    )
    first = _StaticBackend(
        "ocr-a",
        (
            replace(
                native_line,
                text="Native text is authoritative!",
                extraction_method="test-ocr",
                extraction_confidence=0.91,
                source_engines=("ocr-a@1",),
            ),
            _ocr_line("Missing raster annotation", 0.90, "ocr-a@1"),
        ),
    )
    second = _StaticBackend(
        "ocr-b",
        (_ocr_line("Missing raster annotation", 0.88, "ocr-b@1"),),
    )
    backend = AdaptiveOcrBackend(
        native_backend=native,
        ocr_backends=(first, second),
        config=AdaptiveOcrConfig(min_native_characters=100),
    )

    result = backend.extract_page(object(), 1)

    assert [line.text for line in result.lines] == [
        "Native text is authoritative.",
        "Missing raster annotation",
    ]
    assert result.lines[0].source_engines == ("native@1", "ocr-a@1")
    assert result.lines[1].extraction_method == "ocr-consensus"
    assert result.lines[1].source_engines == ("ocr-a@1", "ocr-b@1")
    assert result.lines[1].extraction_confidence == pytest.approx(0.90)
    assert result.lines[1].engine_agreement == pytest.approx(1.0)
    assert {item["code"] for item in result.warnings} == {
        "OCR_TRIGGERED",
        "OCR_TEXT_SUPPLEMENTED",
    }


def test_adaptive_ocr_disagreement_is_uncertain_and_reviewable():
    native = _StaticBackend("native", ())
    first = _StaticBackend("ocr-a", (_ocr_line("alpha result", 0.80, "a@1"),))
    second = _StaticBackend("ocr-b", (_ocr_line("omega result", 0.95, "b@1"),))
    backend = AdaptiveOcrBackend(
        native_backend=native,
        ocr_backends=(first, second),
    )

    result = backend.extract_page(object(), 1)

    assert len(result.lines) == 1
    assert result.lines[0].text == "omega result"
    assert result.lines[0].uncertain is True
    assert "OCR_ENGINE_DISAGREEMENT" in {item["code"] for item in result.warnings}


def test_optional_backend_failure_preserves_native_evidence():
    native_line = LayoutLine("Reliable native evidence", 20, 700, 240, 720, 12)
    native = _StaticBackend("native", (native_line,))

    class Broken:
        name = "broken-ocr"
        version = "1"

        def extract_page(self, page, page_number):
            raise TimeoutError(
                "budget exhausted at C:\\Users\\private\\token.txt "
                "https://example.invalid/file?signature=secret"
            )

    result = AdaptiveOcrBackend(
        native_backend=native,
        ocr_backends=(Broken(),),
        config=AdaptiveOcrConfig(min_native_characters=100),
    ).extract_page(object(), 1)

    assert [line.text for line in result.lines] == ["Reliable native evidence"]
    failure = next(
        warning
        for warning in result.warnings
        if warning["code"] == "OPTIONAL_BACKEND_FAILED"
    )
    assert failure["backend"] == "broken-ocr@1"
    assert failure["degraded"] is True
    assert failure["reason"] == "TIMEOUT"
    assert "C:\\Users" not in failure["detail"]
    assert "signature=secret" not in failure["detail"]
    assert "<redacted-local-path>" in failure["detail"]
    assert "<redacted-url>" in failure["detail"]


def test_invalid_optional_backend_geometry_is_quarantined():
    native = _StaticBackend(
        "native", (LayoutLine("Native evidence", 20, 700, 200, 720, 12),)
    )
    invalid = _StaticBackend("invalid", (LayoutLine("Bad", float("nan"), 1, 2, 3, 10),))
    result = AdaptiveOcrBackend(
        native_backend=native,
        ocr_backends=(invalid,),
        config=AdaptiveOcrConfig(min_native_characters=100),
    ).extract_page(object(), 1)

    assert [line.text for line in result.lines] == ["Native evidence"]
    assert "OPTIONAL_BACKEND_FAILED" in {warning["code"] for warning in result.warnings}


def test_specialist_backend_receives_unanchored_table_region():
    native_layout = PageLayout(
        page=1,
        width=600,
        height=800,
        lines=(LayoutLine("Table 2 Results", 50, 650, 180, 670, 10),),
        objects=(PageObject("image", "Im1", bbox=(0.1, 0.2, 0.9, 0.7)),),
    )

    class Native:
        name = "native"
        version = "1"

        def extract_page(self, page, page_number):
            del page, page_number
            return native_layout

    class TableBackend:
        name = "table-grid"
        version = "1"
        supported_regions = frozenset({"table"})

        def __init__(self):
            self.seen = []

        def extract_region(self, page, page_number, region):
            del page
            self.seen.append(region)
            return PageLayout(
                page=page_number,
                width=600,
                height=800,
                lines=(_ocr_line("A 42", 0.99, "table-grid@1"),),
            )

    specialist = TableBackend()
    backend = AdaptiveOcrBackend(
        native_backend=Native(),
        specialist_backends=(specialist,),
    )

    result = backend.extract_page(object(), 1)

    assert specialist.seen[0].region_type == "table"
    assert result.lines[-1].content_region == "table"


def test_formula_specialist_is_routed_and_corroborates_native_text():
    equation = LayoutLine("E = mc2", 60, 400, 180, 420, 12)

    class Native:
        name = "native"
        version = "1"

        def extract_page(self, page, page_number):
            del page
            return PageLayout(page_number, 600, 800, lines=(equation,))

    class FormulaBackend:
        name = "formula-model"
        version = "1"
        supported_regions = frozenset({"formula"})

        def extract_region(self, page, page_number, region):
            del page
            assert region.region_type == "formula"
            return PageLayout(
                page_number,
                600,
                800,
                lines=(
                    replace(
                        equation,
                        extraction_method="formula-model",
                        extraction_confidence=0.96,
                        source_engines=("formula-model@1",),
                    ),
                ),
            )

    result = AdaptiveOcrBackend(
        native_backend=Native(), specialist_backends=(FormulaBackend(),)
    ).extract_page(object(), 1)

    assert len(result.lines) == 1
    assert result.lines[0].text == "E = mc2"
    assert result.lines[0].content_region == "formula"
    assert result.lines[0].source_engines == ("formula-model@1",)


def test_adaptive_pipeline_records_ocr_provenance_and_quality(tmp_path):
    class Ocr:
        version = "1"

        def __init__(self, name):
            self.name = name

        def extract_page(self, page, page_number):
            del page
            return PageLayout(
                page=page_number,
                width=612,
                height=792,
                lines=(
                    LayoutLine(
                        f"Recovered scan text for page {page_number}.",
                        54,
                        680,
                        300,
                        695,
                        11,
                        extraction_method="test-ocr",
                        extraction_confidence=0.92,
                        source_engines=(f"{self.name}@1",),
                    ),
                ),
            )

    backend = AdaptiveOcrBackend(
        native_backend=NativePdfBackend(),
        ocr_backends=(Ocr("ocr-a"), Ocr("ocr-b")),
    )
    result = parse_document(
        FIXTURES / "sparse_scan.pdf",
        "10.5555/an.v07.sparse",
        output_path=tmp_path / "ocr.parsed.json",
        backend=backend,
    )

    validate_parsed_document(result.document)
    assert result.status == "PARSED"
    assert result.document["quality"]["ocr_supplemented_blocks"] == 1
    assert result.document["quality"]["ocr_consensus_blocks"] == 1
    assert all(
        block["source_engines"] == ["ocr-a@1", "ocr-b@1"]
        for block in result.document["blocks"]
    )
    assert [
        item["name"]
        for item in result.document["parser"]["backend"]["components"]["ocr"]
    ] == ["ocr-a", "ocr-b"]


def test_tesseract_configuration_and_tsv_coordinates():
    with pytest.raises(ValueError, match="at least 300"):
        TesseractOcrConfig(dpi=299)
    with pytest.raises(ValueError, match="max_raster_pixels"):
        TesseractOcrConfig(max_raster_pixels=0)

    payload = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t100\t200\t80\t20\t96.0\tAlpha\n"
        "5\t1\t1\t1\t1\t2\t190\t200\t70\t20\t94.0\tBeta\n"
    )
    lines = _parse_tsv(
        payload,
        page_number=1,
        page_width=600,
        page_height=800,
        image_width=1200,
        image_height=1600,
        engine_id="tesseract@5",
    )

    assert len(lines) == 1
    assert lines[0].text == "Alpha Beta"
    assert lines[0].x0 == 50
    assert lines[0].y0 == 690
    assert lines[0].extraction_confidence == pytest.approx(0.95)
    assert lines[0].source_engines == ("tesseract@5",)


def test_tesseract_refuses_raster_allocation_over_budget():
    page = PdfReader(FIXTURES / "sparse_scan.pdf").pages[0]
    backend = TesseractOcrBackend(TesseractOcrConfig(max_raster_pixels=1))

    with pytest.raises(RuntimeError, match="raster budget exceeded"):
        backend.extract_page(page, 1)


def test_tesseract_execution_identity_records_configuration_and_runtime():
    backend = TesseractOcrBackend(
        TesseractOcrConfig(
            languages="eng+chi_sim",
            max_raster_pixels=12_345_678,
            page_segmentation_mode=6,
        )
    )

    identity = backend.execution_identity

    assert identity["configuration"]["languages"] == "eng+chi_sim"
    assert identity["configuration"]["max_raster_pixels"] == 12_345_678
    assert identity["configuration"]["page_segmentation_mode"] == 6
    assert "tesseract" in identity["runtime_dependencies"]
    assert "poppler" in identity["runtime_dependencies"]
    assert "pillow" in identity["runtime_dependencies"]
    assert "/" not in identity["configuration"]["renderer_command"]
    assert "\\" not in identity["configuration"]["renderer_command"]


def test_tesseract_raster_budget_accounts_for_pdf_user_unit():
    page = PdfReader(FIXTURES / "sparse_scan.pdf").pages[0]
    page[NameObject("/UserUnit")] = FloatObject(10)
    backend = TesseractOcrBackend(
        TesseractOcrConfig(max_raster_pixels=50_000_000)
    )

    with pytest.raises(RuntimeError, match="raster budget exceeded"):
        backend.extract_page(page, 1)


def test_adaptive_execution_identity_includes_nested_backend_configuration():
    ocr = TesseractOcrBackend(
        TesseractOcrConfig(languages="eng", page_segmentation_mode=6)
    )
    backend = AdaptiveOcrBackend(ocr_backends=(ocr,))

    identity = backend.execution_identity

    assert identity["native"]["name"] == "pypdf-native-layout"
    assert "runtime_dependencies" in identity["native"]["components"]
    assert identity["ocr"][0]["name"] == "tesseract-ocr"
    assert (
        identity["ocr"][0]["components"]["configuration"]["page_segmentation_mode"]
        == 6
    )
