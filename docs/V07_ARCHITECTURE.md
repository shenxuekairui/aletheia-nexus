# v0.7 parsing architecture

v0.7 implements one bounded transition:

```text
VERIFIED PDF
  → source identity and integrity gate
  → native-first extraction with optional OCR
  → canonical scientific document (`parsed-document/v2`)
  → deterministic Markdown / JSONL / structure-aware chunks
```

The canonical document records observable source evidence. It does not claim to
understand scientific facts, figures, formulas, or tables semantically.

## Data flow and ownership

| Module | Responsibility |
| --- | --- |
| `content.gate` | Revalidate the acquisition schema, `VERIFIED` article role, DOI, PDF hash, readability, and page count. |
| `content.geometry` | Convert MediaBox/CropBox coordinates, non-zero origins, page rotation, and raster coordinates into one displayed-CropBox space. |
| `content.backends` | Produce validated `PageLayout` evidence. Native extraction is authoritative; OCR and specialist backends are optional supplements. |
| `content.pipeline` / `content.parser` | Assemble ordered blocks, sections, references, caption/region evidence, quality state, and deterministic IDs. |
| `content.schema` | Validate geometry, finite values, confidence/agreement, warning structure, cross-references, fingerprints, and artifact identity before persistence. |
| `content.artifact` | Navigate/search the canonical artifact and recheck source hashes using portable locators or caller-supplied paths. |
| `content.export` | Derive deterministic Markdown, JSONL, and structure-aware chunks without reparsing the PDF. |

No parse or export stage performs discovery, network acquisition, entitlement
decisions, embeddings, model inference, or scientific fact extraction.

## Identity, portability, and persistence

The source identity is `an:source:sha256:<pdf-sha256>`. The parsed identity is a
content-derived `an:parsed:v2:sha256:<digest>` that excludes creation time and
local locators. Moving an unchanged PDF, sidecar, and parsed artifact therefore
does not change identity. `source.locators` may contain only safe relative paths;
absolute paths and URLs are rejected. Consumers may instead pass explicit local
paths when rechecking hashes.

Parsed and exported files refuse to replace an existing target unless the caller
uses the explicit overwrite option. They are written through a temporary file and
atomic replacement. Parsed artifacts are the Source of Truth for downstream use;
AI exports are labelled derived artifacts and carry source/parsed IDs plus exporter
configuration fingerprints.

## Canonical geometry

`pdf-cropbox-display-bottom-left-normalized/v1` is the only accepted anchor
coordinate system. Page metadata retains MediaBox, CropBox, rotation, displayed
width, and displayed height. Native text and painted PDF image boxes are translated
from PDF user space after CropBox origin and page rotation. OCR boxes are mapped
from top-left raster space back through deskew and orientation transforms into the
same displayed page space.

Backend output is validated before it can enter the long-lived artifact. Invalid
page numbers, dimensions, rotations, boxes, non-finite numbers, confidence,
agreement, object metadata, or warning structures fail that backend result. The
parser also verifies backend dimensions/rotation against the actual PDF page.

## Optional backends and degradation

`AdaptiveOcrBackend` preserves validated native evidence. OCR and specialist
failures are isolated per page/backend and recorded as
`OPTIONAL_BACKEND_FAILED` with page, stage, backend, and degradation state. They
do not erase native lines. Diagnostic text is scrubbed of local paths and URLs
before persistence.

Native/OCR overlap retains native text. Agreement is recorded separately as
`engine_agreement`; it does not manufacture `1.0` extraction confidence. Conflicts
emit a review warning. Figures and tables describe only observed caption, painted
region, or positioned-cell evidence through `evidence_status`; every such object
has `interpretation_status: not-interpreted`.

## Consumption layer

`aletheia-nexus export` creates:

- Markdown for human review and prompt attachment;
- JSONL for pipelines;
- chunk JSON for RAG/Agent ingestion.

Chunking respects section changes and isolates headings, captions, equations, and
references. Oversized individual blocks are split deterministically. Every chunk
contains an evidence chain from block and anchor to page/bbox and the source and
parsed artifact identities.

## Status and limits

`PARSED` means the configured extraction completed without a blocking warning,
error, or resource truncation. `PARTIAL` and `FAILED` remain explicit. Page, block,
text, and OCR raster-pixel budgets prevent silent truncation or excessive raster
allocation. These statuses do not establish semantic accuracy or scientific truth.
