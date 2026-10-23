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

`--ocr-languages` selects Tesseract languages, `--ocr-tessdata-dir` selects a
local model directory, `--ocr-dpi` sets rendering resolution (at least 300), and
`--ocr-max-raster-pixels` bounds each page allocation. The pre-render estimate
accounts for PDF `/UserUnit`, and the actual rendered bitmap dimensions are checked
again before OCR preprocessing. The default render is 300 DPI with orientation
detection, small-angle deskew, Otsu binarization, and TSV word coordinates.

`--ocr-alternative-tessdata-dir` optionally adds a second local model directory
with the same languages/rendering settings. Both `parse` and `parse-batch`
support it. The default remains a single model. Different readings are retained
for review; this is not a voting system or a guarantee that the primary reading
is correct. The real-corpus review found a best-only regression in a percentage
that the other model still read correctly.

## Trigger and fusion contract

OCR is requested only for sparse native text, suspicious characters,
image-dominant pages, or meaningful painted-image regions without native anchors.

- On text-rich, non-image-dominant pages, OCR supplements gaps and uncertain
  native text. If clean native lines cover at least 80% of an OCR line's area,
  the redundant OCR reading is not added. Page-wide OCR should not turn healthy
  native prose into hundreds of false conflicts. This does not verify that
  every apparently readable native glyph is correct.
- A clearly corrupt hidden native layer may yield to a sufficiently confident,
  spatially comparable OCR line. The original remains as `native-alternative`,
  separate from the main reading, with uncertainty on both readings.
- When a different OCR reading matches every surviving native character and
  the exact number of missing glyphs, it can replace an OCR primary that does
  not. At least eight surviving alphanumeric characters must constrain the
  comparison. This can recover a dropped repeated digit; it cannot distinguish
  two wrong values of equal length. All differing readings stay uncertain.
- OCR fills spatial gaps and preserves disagreeing readings as separate `ocr-alternative` evidence.
- Coordinate overlap and normalized text similarity suppress duplicates,
  including OCR spaces between Chinese characters and combined native fragments.
  Private-use or missing glyphs require exact agreement; fuzzy matching cannot
  erase a recovered chemical symbol from a table header.
- Identical alternatives at the same location retain one reading with all
  contributing engine identifiers. Their uncertainty is preserved. Separate
  numeric tokens such as `1 2` cannot collapse into `12` during comparison.
- `extraction_confidence` remains the chosen engine's reported confidence.
- `engine_agreement` separately records native/OCR or multi-engine agreement.
- Disagreement emits `OCR_ENGINE_DISAGREEMENT` and requires review.
- Numeric evidence must also agree on units, signs, percentages and letter case;
  high sentence similarity alone does not justify merging it. Conflicting OCR
  engines retain both readings, even when one engine reports higher confidence.
- A low-confidence numeric or alphabetic token marks its whole line for review;
  averaging many confident words must not hide a damaged number or unit.
- At most three short, low-confidence measurement lines per page/model are
  retried as enlarged local crops using single-line segmentation. An accepted
  retry must contain a digit, preserve an existing percent sign, and improve
  reported confidence by at least 0.10 to at least 0.85. The original remains
  available when text changes; the new primary reading stays uncertain.
  This retry currently applies only when no image orientation/deskew transform
  was needed. It cannot repair all unit exponents or high-confidence mistakes.
- OCR within a meaningful non-page-sized image is marked as figure content and
  uncertain, including high-confidence chart axes. Full-page scans are excluded
  from this figure heuristic. It does not classify every possible plot/table.
- Timeout, missing executable, invalid geometry, specialist failure, and resource
  exhaustion are explicit; validated native evidence remains available and the
  degradation includes a stable machine-readable reason category.

All raster boxes are inverted through applied deskew/orientation transforms and
mapped into `pdf-cropbox-display-bottom-left-normalized/v1`. MediaBox, CropBox,
non-zero origins, and PDF page rotation use the same geometry implementation as
native text.

The execution identity records the OCR adapter version and SHA-256 of the active
language models (including orientation data when enabled). Replacing model files
invalidates batch reuse even if the Tesseract executable version is unchanged.
Model paths are not persisted in the portable identity.
Line-level engine identifiers include a model-hash suffix, so two models using
the same Tesseract executable remain distinguishable in the evidence.

The official [Tesseract model comparison](https://github.com/tesseract-ocr/tessdoc/blob/main/Data-Files.md)
describes `tessdata_best` as the slower, accuracy-oriented model family. AN accepts
these models through `--ocr-tessdata-dir`; it does not download them during parsing.
The accuracy review uses pinned official model files and records their hashes.

## Executable evidence and limits

For optional source-image OCR, install `aletheia-nexus[image-ocr]` and use
`parse --ocr --image-ocr rapidocr` (or the same options with `parse-batch`).
The pinned RapidOCR package supplies the local models; parsing does not download
models or upload paper content. Both commands accept the same language/model,
DPI, raster-budget and paragraph-merging controls. CI verifies the installed
models on a self-authored image with network connections disabled.

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

### Detached unit superscripts (adapter 1.4.0)

For a low-confidence per-length unit token, the adapter can re-read a detached
raised component that is actually present in the same raster word box. It uses
unconstrained single-character OCR, accepts only one digit with a score of at
least 90, and attempts at most three glyphs per page/model. It does not infer an
exponent from unit conventions. The original numeric token, canonical line box,
previous reading and uncertainty remain available; the corrected reading records
`tesseract-superscript-retry`. This does not handle every exponent or numeric error.

Painted stencil image masks are recorded as images, including full-page JBIG2
scans. Unpainted resources/soft masks are not independently counted. This avoids
treating a scanned page's hidden text layer as born-digital authoritative text.

### Semantic boundary

Generic OCR does not understand a table, formula, plot, or scientific image.
`RegionExtractionBackend` may add positioned evidence through the same validation
and fusion rules. v0.7 records what was observed and leaves scientific image
understanding, plot digitization, formula semantics, and universal table recovery
to later releases.
