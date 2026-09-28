# Aletheia Nexus v0.7.0 — source-linked parsing

v0.7.0 connects the verified acquisition artifact to a versioned,
source-linked document representation. It also closes acquisition defects
found while building the parser corpus. This release does not claim scientific
truth assessment, knowledge-graph correctness, or universal publisher access.

## Acquisition closure

- PMC records discovered through existing providers can be resolved through
  the official PMC Article Datasets public AWS bucket. Metadata DOI, article
  type, retraction state, and PDF availability are checked before a candidate
  is attempted.
- PMC augmentation is idempotent, retry-bounded, and isolated per article
  version so one malformed version does not discard another valid version.
- Expected titles normalize literal and escaped HTML markup without persisting
  provider markup in identity comparison.
- Browser startup failures recognize common Chromium profile lock markers and
  provide a safe recovery hint without exposing the original command line.

The PMC route was exercised against the public record for
`10.1016/j.heliyon.2024.e27078`: the official cloud PDF produced a 14-page
`VERIFIED` article with DOI/title identity match and a sidecar-matching SHA-256.
This is a route smoke test, not a general acquisition success-rate claim.

## Parsing and OCR

- A fail-closed input gate accepts only an unchanged `VERIFIED` main article
  with matching DOI, hash, role, readability, and page count.
- `parsed-document/v2` records stable source anchors, pipeline/backend identity,
  sections, references, figures, tables, cells, budgets, warnings, and explicit
  `PARSED`/`PARTIAL`/`FAILED` status.
- Pipeline 2.3.0 improves multi-column line splitting, decorated headings,
  numbered and author-year references, end-of-bibliography detection, caption
  discrimination, and continued/supplement object handling.
- Optional `AdaptiveOcrBackend` keeps native text authoritative and triggers OCR
  only for sparse, suspicious, image-dominant, or unanchored regions.
- The Tesseract adapter supports 300-DPI rendering, orientation correction,
  deskew, Otsu binarization, TSV coordinates, and confidence. Coordinate/text
  fusion removes overlap; multi-engine agreement raises confidence and
  disagreement requests manual review.
- Table, formula, and figure specialists can use the public
  `RegionExtractionBackend` contract.

## Validation evidence

Two private, hash-frozen real-layout corpora were reprocessed without entering
the repository:

- 24 papers / 436 pages: 24/24 `PARSED`, zero omitted and zero added normalized
  native-layer tokens;
- 14 papers / 219 pages: 14/14 `PARSED`, zero omitted and zero added normalized
  native-layer tokens;
- combined: 38 papers / 655 pages and 2,609,595 retained text characters.

The checked-in deterministic suite covers acquisition, input gating, source
anchors, layout/structure, OCR trigger and fusion, double-engine disagreement,
specialist routing, schema validation, and consumer lookup. The final commit
completed locally on Windows/Python 3.14 with **858 passed, 7 skipped**; Ruff,
bytecode compilation, the frozen acquisition benchmark, and the parser
evaluation gate also passed. It must additionally pass the repository's Python
3.11, Python 3.14, Linux Chromium, and Windows Chromium PR jobs before merge.

## Boundaries

Zero loss above means equality with the PDFs' native text layers. The real
corpora contain no textless pages, so actual OCR executable quality is not
measured by that number. A claim below 1% total visual information loss requires
human-reviewed page transcription covering raster text, tables, formulas, and
charts. Unresolved semantic objects retain source anchors for review rather
than being silently discarded or guessed.

The package version is `0.7.0`. A version change and GitHub Release do not prove
PyPI availability; confirm the published project and a clean installation
separately.
