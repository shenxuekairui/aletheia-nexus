# v0.7 native-first OCR

OCR is an optional evidence-recovery path, not a replacement for reliable native
PDF text.

## CLI

Install the Python image dependency and make Poppler `pdftoppm` and Tesseract 5
available on `PATH`:

```console
python -m pip install "aletheia-nexus[ocr]"
aletheia-nexus parse paper.pdf --doi 10.1234/example --ocr
```

`--ocr-languages` selects Tesseract languages and
`--ocr-max-raster-pixels` bounds each page allocation. The pre-render estimate
accounts for PDF `/UserUnit`, and the actual rendered bitmap dimensions are checked
again before OCR preprocessing. The default render is 300 DPI with orientation
detection, small-angle deskew, Otsu binarization, and TSV word coordinates.

## Trigger and fusion contract

OCR is requested only for sparse native text, suspicious characters,
image-dominant pages, or meaningful painted-image regions without native anchors.

- Native text always wins on overlap.
- OCR fills only spatial gaps.
- Coordinate overlap and normalized text similarity suppress duplicates.
- `extraction_confidence` remains the chosen engine's reported confidence.
- `engine_agreement` separately records native/OCR or multi-engine agreement.
- Disagreement emits `OCR_ENGINE_DISAGREEMENT` and requires review.
- Timeout, missing executable, invalid geometry, specialist failure, and resource
  exhaustion are explicit; validated native evidence remains available and the
  degradation includes a stable machine-readable reason category.

All raster boxes are inverted through applied deskew/orientation transforms and
mapped into `pdf-cropbox-display-bottom-left-normalized/v1`. MediaBox, CropBox,
non-zero origins, and PDF page rotation use the same geometry implementation as
native text.

## Executable evidence and limits

CI installs real Poppler and Tesseract and runs the self-authored raster-only PDF
through rendering, OCR, fusion, parsing, and schema validation. The smoke fixture
asserts exact expected text and a positioned title anchor. Unit fixtures cover
rotation/origin transforms, optional-backend timeout/failure, malformed geometry,
confidence/agreement separation, and raster budget rejection.

The deterministic fixture's exact OCR text is useful regression evidence, but it
does not prove a sub-1% loss rate on arbitrary scans. A general loss claim requires
human-transcribed page truth across representative scan quality, scripts, tables,
equations, and figures.

## Specialist boundary

Generic OCR does not understand a table, formula, plot, or scientific image.
`RegionExtractionBackend` may add positioned evidence through the same validation
and fusion rules. v0.7 records what was observed and leaves scientific image
understanding, plot digitization, formula semantics, and universal table recovery
to later releases.
