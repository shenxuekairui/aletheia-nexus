# Aletheia Nexus v0.7.0 — canonical scientific documents

v0.7.0 turns an unchanged, verified paper into a portable, source-linked
Canonical Scientific Document and deterministic AI-ready derived views. It does
not add embeddings, model calls, scientific claim interpretation, or Agents.

## Acquisition closure

- The parser gate accepts only a matching `VERIFIED` main article and rechecks
  DOI, role, schema, PDF/sidecar hashes, readability, and page count before and
  after parsing.
- PMC records can use the official Article Datasets route with bounded retries,
  version isolation, and DOI/article/retraction/PDF checks.
- Title normalization and browser profile-lock diagnostics were corrected without
  weakening acquisition identity or access-control boundaries.
- Browser recovery preserves observed PDF routes ahead of inferred fallbacks,
  including at the batch/service boundary. Publisher preferences control attempt
  order, and PDF endpoint challenges use the shared visible wait and delivery path.
- Reader access controls exclude institution administration links. Hidden/stale
  controls, remembered institution activation, and explicit target entitlement
  boundaries have focused regressions. PDF identity and article-role checks remain
  shared across every delivery method.

## Canonical parsing contract

- `structured-pdf-pipeline/2.4.0` writes validated
  `aletheia-nexus/parsed-document/v2` artifacts with stable source and parsed IDs.
- Source identity is separate from local location. Only safe relative locators may
  be persisted; moving unchanged artifacts preserves identity.
- MediaBox, CropBox, non-zero origins, page rotation, rendered pixels, OCR
  orientation, and deskew share one canonical displayed-page coordinate system.
- Backend output is validated at runtime for page identity, dimensions, finite
  geometry, confidence/agreement, provenance, objects, and warnings.
- Optional OCR/specialist failure is isolated and explicit; reliable native
  evidence is retained.
- Existing parsed outputs are not silently replaced. `--overwrite` is required.
- Figures and tables describe caption/region/cell evidence and explicitly state
  `not-interpreted`; captions are not presented as scientific understanding.

## OCR and AI-ready exports

- `aletheia-nexus parse --ocr` provides the real Poppler + Tesseract executable
  path with a per-page raster-pixel budget.
- Native text remains authoritative. Engine confidence and engine agreement are
  separate fields, and disagreement remains reviewable.
- `aletheia-nexus export` creates deterministic Markdown, JSONL, or
  structure-aware chunk JSON. Every chunk links through block/anchor/page/bbox to
  the source artifact and records exporter/configuration identity.
- Export refuses to overwrite its parsed input or locally referenced source PDF
  and acquisition record, including when `--overwrite` is specified.

## Qualification

- Self-authored frozen evaluator: 4/4 gate decisions, 32/32 anchored blocks, 6/6
  selected anchors, 10/10 sections, 18/18 structural assertions, and 886/886 gold
  characters with zero deletions, insertions, or substitutions.
- Real executable OCR smoke: the raster-only fixture renders through Poppler,
  extracts through Tesseract, returns exact expected text, and retains positioned
  anchors.
- Public OA qualification: three hash-frozen PMC papers passed status, pages,
  anchors, selected text, and conservative reference/figure/table thresholds.
- Private stress sets: 24/24 papers (436 pages) and 14/14 papers (219 pages)
  completed as `PARSED`. These figures demonstrate completion and diagnostics,
  not human-labelled semantic accuracy.
- The earlier parser milestone on Windows/Python 3.14 had **874 passed, 8
  skipped**. Current integration and final-check results are recorded separately
  in [release history](RELEASE_HISTORY.md); historical publisher downloads are not
  a fresh success rate for the final code.

The release workflow now tests Python 3.11, 3.12, 3.13, and 3.14; real Chromium;
real Poppler + Tesseract; distribution build/twine validation; and installation of
the wheel in a clean environment. The final PR commit must be green before merge.
The clean-wheel gate also runs the CLI acquisition/resume/parse/search/export
contract. The local v0.7 runner selects this checkout's source and offers explicit
`--browser-smoke`, `--ocr-smoke`, and `--public-oa` checks; private corpus qualification
fails for empty, missing, changed, failed, or partially parsed inputs.

## Security, privacy, copyright, and boundaries

Minimum dependency versions include fixes available in pypdf 6.19, Pillow 12.3,
and FontTools 4.60.2. Persistent diagnostics redact local paths and URLs. Git
ignores parsed documents, AI exports, and qualification reports because they may
contain copyrighted full text or local run data. OA PDFs are hash-frozen but
fetched on demand rather than redistributed.

The exact synthetic OCR result and native-text stress results do not justify a
general “below 1% visual information loss” claim. That requires representative,
human-transcribed visual truth for scans, equations, tables, and figures.

Deferred to v0.8+: embeddings, vector databases, semantic search, LLM summaries,
scientific entity/condition/measurement/claim/relation extraction, knowledge
graphs, MCP/Agent/laboratory-memory features, plot digitization, spectroscopy,
scientific image interpretation, and universal table/chart/formula understanding.
