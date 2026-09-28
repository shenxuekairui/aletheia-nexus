# v0.7 scientific content parsing contract

Status: implemented as an experimental native-text baseline in `0.7.0.dev0`.
The contract remains stricter than the parser's current layout coverage.

The acquisition layer answers **which file was obtained and why AN considers it
the requested main article**. The proposed parsing layer answers **which
source-linked objects can be extracted from those bytes**. It must not turn a
successful parse into a claim that the article, its conclusions, or the user's
subscription has been independently verified.

## Input gate

A parser request identifies a local PDF and its sibling `.acquisition.json`
sidecar. Before parsing, the caller must check all of the following:

1. Both files exist and are regular files; the PDF is not in `_unverified`.
2. The sidecar `schema` is a recognized acquisition-record variant (currently
   `aletheia-nexus/acquisition-record/v1` or
   `aletheia-nexus/access-acquisition-record/v1`). Unknown versions fail
   closed, rather than being guessed into a new shape.
3. `status == "VERIFIED"`, `pdf_validation.valid_pdf == true`,
   `identity_validation.status == "MATCH"`, and
   `identity_validation.document_role == "ARTICLE"`.
4. `target.doi` normalizes to the requested DOI; `retrieval.sha256` is a
   64-character hex digest and matches a fresh streaming SHA-256 of the PDF.
5. The PDF can still be opened and its page count agrees with the recorded
   `pdf_validation.page_count`. A corrupt, changed, or encrypted file is not
   silently recovered via a different route inside the parser.

An acquisition checkpoint alone is insufficient: its `VERIFIED` entry is a
resume record, not the full sidecar. Any failed gate yields a typed input error
and leaves the acquisition artifact untouched. A newer sidecar schema needs an
explicit compatibility adapter and regression fixtures.

## Output artifact

Write a *new* `.parsed.json` artifact (schema identifier
`aletheia-nexus/parsed-document/v2`) alongside, not instead of, the PDF and
acquisition sidecar. The v0.7 CLI and `aletheia_nexus.content` API produce and
validate this artifact. The unpublished v1 draft was superseded when the
backend/pipeline identity, quality summary, resource budgets, merged blocks,
structured table cells, and PDF image-resource associations became required.
The required fields are:

| Field | Contract |
| --- | --- |
| `schema`, `created_at`, `parser` | Versioned schema, UTC timestamp, pipeline/backend identity, ordered stages, configuration and execution fingerprints. |
| `source` | Normalized DOI, PDF SHA-256, acquisition-sidecar SHA-256, page count, and the acquisition schema identifier. Paths are local references, not evidence to publish. |
| `status`, `warnings`, `errors` | Explicit `PARSED`, `PARTIAL`, or `FAILED`; machine-readable codes and human-readable detail. `PARTIAL` is never silently treated as complete. |
| `quality` | Page/anchor coverage, text volume, object/unresolved counts, table-cell coverage, suppressed repeated page furniture, unassociated painted-image resources, and resource-limit termination. |
| `sections` | Stable IDs, parent IDs, heading text, order and referenced block IDs; do not infer missing hierarchy as fact. |
| `blocks` | Stable IDs, text or object reference, reading order, kind (paragraph, heading, caption, equation, etc.), extraction method and uncertainty flag. |
| `anchors` | For every text block: one-based PDF page, page-relative bounding box when available, and text/span evidence. If location is unavailable, mark the block unanchored rather than fabricating coordinates. |
| `references`, `figures`, `tables` | Identifiers and links to source blocks/anchors; unresolved or ambiguous links remain explicit. Tables may include cells only when their positions and associations can be supported. |

IDs should be deterministic for identical input bytes, parser version and
configuration. JSON ordering should be stable. Re-running a parser must not
modify the acquisition sidecar. A parser implementation may add fields through
a documented minor-compatible extension but must not reinterpret existing
fields without a new schema version.

The baseline derives boxes from PDF text matrices and estimated glyph widths,
so it records `bbox_precision: estimated`; it does not present them as
glyph-exact geometry. Consumers that need pixel- or glyph-level highlighting
must treat that field as a capability boundary.

## Fixture and evaluation gate

Do **not** commit downloaded publisher full texts or authenticated URLs merely
because AN could access them. The checked-in `benchmarks/v07_fixtures` set is
self-authored, generated deterministically, and redistributable under
Apache-2.0. Its frozen manifest and gold annotations cover native text,
two-column reading order, section hierarchy, references, a table,
figure/caption association, equations, scanned or sparse-text pages, and an
article-plus-supplement pair. Keep institution-only PDFs in ignored local paths
for private exploratory tests; they are not public CI fixtures.

For each fixture, record the expected document identity, pages, selected
anchor spans, sections and table/figure links in a versioned gold annotation.
Report exact denominators and both false associations and omissions. The
minimum release report should include DOI/hash gate pass/fail, anchored-block
coverage, anchor correctness, section recall, table/figure link precision,
runtime and peak memory on Windows and Linux. A parser/model change must be
compared against the same frozen fixture hashes and annotations; live metadata
or publisher response is not part of this benchmark.

## v0.7 implementation status

1. **Complete:** pure input-gate tests cover both current sidecar variants,
   corrupt and changed PDFs, DOI/hash/page mismatch, status/role mismatch,
   `_unverified` paths, and unknown schema.
2. **Complete:** the self-authored fixture manifest, SHA-256 values, gold
   annotations, schema validator, stable IDs, and deterministic serialization
   are checked in.
3. **Complete:** `structured-pdf-pipeline/2.1.0` separates a public extraction
   backend contract from block assembly, structure/object linking, and quality
   stages. The bundled native backend merges paragraph lines, suppresses
   repeated page furniture, uses font weight plus conservative text-shape rules
   for headings, distinguishes equations and author-style references, and
   resolves citations explicitly. It records only image XObjects actually
   painted by the page content stream, links nearby positioned images to
   captions, recovers positioned table cells (including mathematical cells),
   and enforces page/block/text budgets. A validated consumer API provides
   section text, fresh source-hash checks, and searches that return PDF
   page/bbox anchors.
4. **Still a release gate:** outputs remain experimental until the final
   release commit passes hosted Linux and Windows jobs and real-layout evidence
   is broad enough for any stronger quality claim. The acquisition API and
   `VERIFIED` meaning remain unchanged.

Run the offline benchmark with `python scripts/evaluate_v07_parser.py`. It
reports exact correct/total denominators, per-fixture status, runtime, peak
memory, platform, and the frozen manifest hash. The initial Windows result is
4/4 gate decisions, 32/32 anchored blocks, 6/6 selected anchors, 10/10 section
recall, 2/2 table/figure caption links, 1/1 image-resource association, 1/1
table structure, 2/2 reference resolution cases, and 2/2 reading-order checks.
These small synthetic denominators prevent regressions; they are not a claim
of general publisher-layout accuracy. See [the architecture](V07_ARCHITECTURE.md)
for module and extension boundaries.

A private, user-supplied real-layout check on 2026-09-28 fixed 24 unique DOI,
PDF and sidecar hashes before comparing parser 2.0.0 with 2.1.0. All 24
documents (436 pages) completed as `PARSED` in both runs. The structural section
candidate count fell from 2168 to 570, references increased from 967 to 1176
while unresolved references fell from 68 to 62, unresolved semantic figures
fell from 1151 to 0 after unused page resources stopped becoming figures, and
tables with recovered cells increased from 3 to 11. Runtime increased from
34.69 s to 50.61 s because painted-image placement is inspected conservatively.
These aggregate diagnostics are not gold annotations or a publisher-wide
accuracy claim; the protected PDFs and per-paper artifacts remain outside the
repository.

Out of scope: interpreting scientific claims, factual truth assessment,
knowledge-graph correctness, and automatic entitlement decisions.
