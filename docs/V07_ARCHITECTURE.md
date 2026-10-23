# v0.7 parsing architecture

v0.7 implements one bounded transition:

```text
VERIFIED or locally REGISTERED PDF (article or linked supplement)
  → source identity and integrity gate
  → native-first extraction with optional OCR
  → canonical scientific document (`parsed-document/v3`, v2 readable)
  → deterministic Markdown / JSONL / structure-aware chunks
```

The canonical document records observable source evidence. It does not claim to
understand scientific facts, figures, formulas, or tables semantically.

## Data flow and ownership

| Module | Responsibility |
| --- | --- |
| `content.gate` | Revalidate acquisition or local-registration evidence, article/SI role and parent, recorded DOI, PDF hash, readability, and page count. |
| `content.geometry` | Convert MediaBox/CropBox coordinates, non-zero origins, page rotation, and raster coordinates into one displayed-CropBox space. |
| `content.backends` | Produce validated `PageLayout` evidence. Native extraction is authoritative; OCR and specialist backends are optional supplements. |
| `content.pipeline` / `content.parser` | Assemble ordered blocks, sections, references, caption/region evidence, quality state, and deterministic IDs. |
| `content.captions` | Recognize captions and retain one caption identity for duplicate source readings. |
| `content.table_layout` / `content.ruled_tables` | Arrange observed columns/shared cells and painted grid geometry; report local ambiguity without inventing experimental semantics. |
| `content.schema` | Validate geometry, finite values, confidence/agreement, warning structure, cross-references, fingerprints, and artifact identity before persistence. |
| `content.artifact` | Navigate/search the canonical artifact and recheck source hashes using portable locators or caller-supplied paths. |
| `content.export` | Derive deterministic Markdown, JSONL, and structure-aware chunks without reparsing the PDF. |
| `content.corpus` / `content.evidence` | Search verified local artifacts, select relevant context, group review locations and export attributable evidence packs. |
| `parsing_cli` | Share parser/OCR option construction between single-file and batch commands. It owns CLI configuration, not scientific parsing rules. |

No parse or export stage performs discovery, network acquisition, entitlement
decisions, embeddings, remote AI calls, or scientific fact extraction. Optional
OCR models execute locally. The advisory `EvidenceJudge` interface consumes a
caller-selected evidence pack and cannot rewrite its canonical source readings.

## Project philosophy in the implementation

The PDF and acquisition record remain original evidence; parsed JSON is the
canonical downstream representation, not a certificate of scientific truth.
Stable operations are ordinary Python functions and local files. Both HTTP and
browser acquisition use the same identity/role outcome policy; both parser
commands use the same configuration builder. The existing backend/stage
interfaces stay bounded: no plugin registry, database, agent framework or model
provider is required for normal use.

The v0.7.2 release cleanup moves caption/table responsibilities out of the parser
without changing their rules. Replaying 42 captured real-document layouts
(403 pages) produced identical complete document dictionaries, excluding portable
file locators only. This checks refactoring equivalence, not fresh OCR accuracy.

## Identity, portability, and persistence

The source identity is `an:source:sha256:<pdf-sha256>`. The parsed identity is a
content-derived `an:parsed:v3:sha256:<digest>` that excludes creation time and
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
Execution identity includes backend configuration and relevant runtime dependency
versions so materially different extraction environments do not share one
execution fingerprint.

## Optional backends and degradation

`AdaptiveOcrBackend` preserves validated native evidence. OCR and specialist
failures are isolated per page/backend and recorded as
`OPTIONAL_BACKEND_FAILED` with page, stage, backend, and degradation state. They
do not erase native lines. Diagnostic text is scrubbed of local paths and URLs
before persistence.

Native/OCR overlap retains native text and preserves disagreeing OCR as a separate
`ocr-alternative`; signs and numbers are checked before treating similar text as agreement.
Agreement is recorded separately as
`engine_agreement`; it does not manufacture `1.0` extraction confidence. Optional
failures also record a stable reason category for machine consumers. Conflicts emit
a review warning. Figures and tables describe only observed caption, painted
region, or positioned-cell evidence through `evidence_status`; heuristic table
cell structure remains explicitly uncertain and every such object has
`interpretation_status: not-interpreted`.

## Consumption layer

`aletheia-nexus export` creates:

- Markdown for human review and prompt attachment;
- JSONL for pipelines;
- chunk JSON for RAG/Agent ingestion.

Chunking respects section changes, table-object boundaries, and isolates headings,
captions, equations, and references. Oversized individual blocks are split
deterministically. Every chunk is independently attributable: it carries source
and parsed artifact identities, block/anchor/page identifiers, and the detailed
page/bbox evidence chain.

## Status and limits

`PARSED` means the configured extraction completed without a blocking warning,
error, or resource truncation. `PARTIAL` and `FAILED` remain explicit. Page, block,
text, and OCR raster-pixel budgets prevent silent truncation or excessive raster
allocation. These statuses do not establish semantic accuracy or scientific truth.
