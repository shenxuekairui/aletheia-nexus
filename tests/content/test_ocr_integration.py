"""Real executable smoke for the optional Poppler + Tesseract path."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from aletheia_nexus.content import (
    AdaptiveOcrBackend,
    TesseractOcrBackend,
    TesseractOcrConfig,
    parse_document,
)

FIXTURES = Path(__file__).resolve().parents[2] / "benchmarks" / "v07_fixtures"


@pytest.mark.skipif(
    os.environ.get("AN_RUN_OCR_SMOKE") != "1",
    reason="set AN_RUN_OCR_SMOKE=1 to run external OCR executables",
)
def test_real_poppler_tesseract_raster_only_pdf(tmp_path):
    renderer = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not renderer or not tesseract:
        pytest.fail("AN_RUN_OCR_SMOKE requires pdftoppm and tesseract on PATH")

    backend = AdaptiveOcrBackend(
        ocr_backends=(
            TesseractOcrBackend(
                TesseractOcrConfig(
                    renderer_command=renderer,
                    tesseract_command=tesseract,
                    detect_orientation=False,
                )
            ),
        )
    )
    result = parse_document(
        FIXTURES / "sparse_scan.pdf",
        "10.5555/an.v07.sparse",
        output_path=tmp_path / "real-ocr.parsed.json",
        backend=backend,
        created_at="2026-09-28T00:00:00+00:00",
    )

    text = " ".join(str(block["text"]) for block in result.document["blocks"])
    expected = (
        "RASTER ONLY SCIENTIFIC ARTICLE Methods The verified sample contains "
        "forty two observations. Results OCR preserves this source linked evidence."
    )
    assert result.status == "PARSED"
    assert text == expected
    assert result.document["quality"]["ocr_supplemented_blocks"] >= 3
    assert all(anchor["bbox"] is not None for anchor in result.document["anchors"])
    assert all(
        0 <= coordinate <= 1
        for anchor in result.document["anchors"]
        for coordinate in anchor["bbox"]
    )
    title = next(
        block
        for block in result.document["blocks"]
        if "RASTER ONLY SCIENTIFIC ARTICLE" in block["text"]
    )
    title_anchor = next(
        anchor
        for anchor in result.document["anchors"]
        if anchor["id"] == title["anchor_id"]
    )
    assert title_anchor["bbox"][0] < 0.2
    assert title_anchor["bbox"][1] > 0.75
