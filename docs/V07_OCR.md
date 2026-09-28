# v0.7 native-first OCR

The v0.7 parser treats the PDF content stream as the authoritative source and
uses OCR only as positioned supplementary evidence. This prevents a normal
born-digital article from being flattened into a lower-quality raster copy.

## Enable selective OCR

Install the optional Python dependency and provide Poppler's `pdftoppm` and
Tesseract 5 on `PATH`:

```console
python -m pip install "aletheia-nexus[ocr]"
```

```python
from aletheia_nexus.content import (
    AdaptiveOcrBackend,
    TesseractOcrBackend,
    parse_document,
)

backend = AdaptiveOcrBackend(ocr_backends=(TesseractOcrBackend(),))
result = parse_document(
    "paper.pdf",
    "10.1234/example",
    sidecar_path="paper.acquisition.json",
    backend=backend,
)
```

The Tesseract backend renders at 300 DPI, detects page orientation, estimates
and corrects small skew, applies Otsu binarization, and reads TSV word
coordinates and confidence. OCR is triggered only when a page has too little
native text, suspicious replacement/control characters, dominant image
coverage, or a meaningful painted image region without overlapping native text.

Fusion is coordinate-aware:

- overlapping native text is always retained;
- similar OCR at the same coordinates becomes corroborating provenance;
- OCR is added only where native coordinates are empty;
- overlapping OCR engines are deduplicated;
- agreement between engines raises confidence;
- disagreement is retained as uncertainty and emits
  `OCR_ENGINE_DISAGREEMENT`, making manual review explicit.

Every parsed block records `extraction_method`, `extraction_confidence`,
`source_engines`, page, normalized anchor coordinates, and `content_region`.
The quality summary reports OCR-supplemented blocks, consensus blocks, mean
confidence, and whether manual review is required.

## Tables, formulas, and figures

General OCR is not a table, formula, or chart parser. Implement
`RegionExtractionBackend` for a specialist and pass it through
`specialist_backends`. The adaptive backend detects unanchored painted regions,
routes `table` and `figure` regions only to compatible specialists, and fuses
their positioned output through the same native-first rules. Formula specialists
can use the same contract when a formula-region detector supplies a
`PageRegion(region_type="formula", ...)`.

## Validation

Frozen fixture manifests may provide `gold.text_pages`. The offline evaluator
then reports character deletions, insertions, substitutions, information-loss
rate, total character-error rate, exact duplicate-text rate, and aggregate
structural recall. A reported loss rate is meaningful only for pages with
human-reviewed gold text; native-text conservation alone cannot measure text
that exists only inside pixels.
