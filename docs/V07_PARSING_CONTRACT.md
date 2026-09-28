# v0.7 parsing entry contract (design, not an implemented feature)

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

## Proposed output artifact

Write a *new* `.parsed.json` artifact (working schema identifier
`aletheia-nexus/parsed-document/v1`) alongside, not instead of, the PDF and
acquisition sidecar. This is a design target; no producer or consumer exists
in v0.6.1. The minimum fields for the first implementation are:

| Field | Contract |
| --- | --- |
| `schema`, `created_at`, `parser` | Versioned schema, UTC timestamp, method/name/version and configuration fingerprint. |
| `source` | Normalized DOI, PDF SHA-256, acquisition-sidecar SHA-256, page count, and the acquisition schema identifier. Paths are local references, not evidence to publish. |
| `status`, `warnings`, `errors` | Explicit `PARSED`, `PARTIAL`, or `FAILED`; machine-readable codes and human-readable detail. `PARTIAL` is never silently treated as complete. |
| `sections` | Stable IDs, parent IDs, heading text, order and referenced block IDs; do not infer missing hierarchy as fact. |
| `blocks` | Stable IDs, text or object reference, reading order, kind (paragraph, heading, caption, equation, etc.), extraction method and uncertainty flag. |
| `anchors` | For every text block: one-based PDF page, page-relative bounding box when available, and text/span evidence. If location is unavailable, mark the block unanchored rather than fabricating coordinates. |
| `references`, `figures`, `tables` | Identifiers and links to source blocks/anchors; unresolved or ambiguous links remain explicit. Tables may include cells only when their positions and associations can be supported. |

IDs should be deterministic for identical input bytes, parser version and
configuration. JSON ordering should be stable. Re-running a parser must not
modify the acquisition sidecar. A parser implementation may add fields through
a documented minor-compatible extension but must not reinterpret existing
fields without a new schema version.

## Fixture and evaluation gate

Do **not** commit downloaded publisher full texts or authenticated URLs merely
because AN could access them. Before implementation, assemble redistributable
or self-authored fixtures with a recorded source and redistribution permission,
plus separate synthetic adversarial examples. The initial matrix should cover
native text, two-column reading order, section hierarchy, references, a table,
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

## First v0.7 implementation sequence

1. Add pure input-gate tests for both current sidecar variants, corrupted PDF,
   hash mismatch, status/role mismatch and unknown schema.
2. Freeze the rights-cleared fixture manifest and gold annotations, then add a
   minimal schema validator with deterministic serialization.
3. Implement one baseline parser behind the gate and measure it before adding
   model-assisted extraction or more formats.
4. Expose outputs as explicitly experimental until the benchmark, privacy
   check, and local/hosted platform tests pass. Keep the current acquisition
   API and `VERIFIED` semantics unchanged.

Out of scope: interpreting scientific claims, factual truth assessment,
knowledge-graph correctness, and automatic entitlement decisions.
