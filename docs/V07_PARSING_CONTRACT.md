# v0.7 scientific content parsing contract

Status: implemented for `0.7.0` by `structured-pdf-pipeline/2.4.0`.

The release target is:

> VERIFIED PDF → source-linked canonical scientific document → model-agnostic AI-ready data

## Trusted input

Parsing requires a local PDF and acquisition sidecar. The gate fails closed unless:

1. both are regular files and the PDF is not in `_unverified`;
2. the acquisition schema is explicitly supported;
3. the status is `VERIFIED`, validation says it is a readable main `ARTICLE`, and
   the normalized DOI equals the requested DOI;
4. a fresh PDF SHA-256 and page count equal the acquisition evidence; and
5. neither PDF nor sidecar changes while parsing.

The parser never reacquires a failed input or converts an acquisition failure into
a trusted source.

## Canonical artifact

`aletheia-nexus/parsed-document/v2` is the long-lived Canonical Scientific
Document. Its important fields are:

| Field | Contract |
| --- | --- |
| `artifact_id` | Deterministic parsed identity, independent of timestamp and local path. |
| `source` | DOI, stable source identity, PDF/sidecar hashes, page count, acquisition schema, and optional safe relative locators. |
| `parser` | Parser/backend versions, ordered stages, configuration and execution fingerprints, including relevant backend/runtime dependency identity. |
| `pages` | Displayed dimensions, MediaBox, CropBox, rotation, and canonical coordinate-system identifier. |
| `blocks` / `anchors` | Ordered text evidence with extraction method, confidence, separate engine agreement, page, bbox, and text span. |
| `sections` / `references` | Conservative structure and explicit resolved/unresolved citation evidence. |
| `figures` / `tables` | Caption, painted-region, and positioned-cell evidence only; `interpretation_status` is always `not-interpreted`. |
| `quality` | Coverage, counts, OCR use, uncertainty/review state, and resource termination. |
| `warnings` / `errors` | Structured code/detail plus page, stage, backend, and degradation fields where applicable. |

The canonical coordinate system is
`pdf-cropbox-display-bottom-left-normalized/v1`. All native, image, and OCR
evidence must map into it. Runtime validation rejects non-finite or out-of-range
geometry, invalid dimensions/rotation, malformed confidence/agreement, bad warning
records, dangling references, fingerprint mismatch, and invalid artifact identity.

An existing parsed target is a conflict by default. `--overwrite` is the explicit
opt-in. Source locators cannot be absolute paths, drive/UNC paths, traversal paths, or
URLs under either POSIX or Windows path semantics, and are excluded from artifact
identity. This keeps artifacts portable and prevents default disclosure of
machine-specific paths.

## Extraction and uncertainty

Native text is authoritative. Optional OCR or specialist failures preserve native
evidence and create an explicit degradation warning. OCR confidence is the engine's
confidence; agreement is a different field. A figure caption does not mean the
figure was interpreted, and table-like positioned text does not mean a universal
table parser succeeded.

`PARSED` means the configured evidence extraction completed. `PARTIAL` signals
sparse text, failed pages, or resource limits. `FAILED` means no usable page result
survived. None of these states validates scientific claims.

## Derived AI views

Markdown, JSONL, and structure-aware chunk exports are deterministic derived
artifacts, not new Sources of Truth. Every chunk independently includes source and
parsed IDs, block/anchor/page identifiers, exporter version/configuration identity
through its enclosing export, and detailed evidence chains:

```text
chunk → block → anchor → page/bbox → source artifact
```

Chunking respects sections and isolates headings, captions, equations, and
references. v0.7 includes no embeddings, vector store, model-provider integration,
summarization, entity extraction, claim extraction, knowledge graph, MCP server, or
Agent implementation.

## Qualification evidence

Three evidence layers are kept distinct:

1. `benchmarks/v07_fixtures`: self-authored, deterministic PDFs and frozen gold.
   The evaluator currently checks 4/4 input gates, 32/32 anchored blocks, 6/6
   selected anchors, 10/10 sections, 18/18 structural assertions, no object-link
   omission/false association, and 886/886 gold characters with zero deletion,
   insertion, or substitution. A raster-only fixture is exercised through real
   Poppler + Tesseract in its dedicated smoke.
2. `benchmarks/v07_public_oa`: three hash-frozen OA papers fetched from the official
   PMC dataset, with manually selected title/section/object-count assertions. This
   qualifies representative real layouts, not complete semantics.
3. Private corpora: 24 papers/436 pages and 14 papers/219 pages completed parsing on
   the final pipeline. They are broader stress evidence only. Aggregate block/text
   diagnostics and native-layer comparison are not human semantic accuracy.

The change from parser 2.3 to canonical CropBox clipping removes hidden/off-page
duplicate text layers in several PDFs. Rendered-page spot checks confirmed that the
removed MDPI/JHEP samples were not visible page content. This is a geometry
correction, not a claim that all visual information loss is below 1%.

The hosted release gate also runs the frozen evaluator explicitly and uploads its
machine-readable report as a CI artifact bound to the tested commit.

Run the bounded local gate with:

```console
python scripts/verify_v07_rc.py --ocr-smoke --public-oa --report qualification-report.json
```

Public paper text, private PDFs, parsed artifacts, and AI exports are not committed
by default. Project licensing does not change the copyright of source papers.
