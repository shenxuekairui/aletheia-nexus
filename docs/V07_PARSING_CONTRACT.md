# v0.7 scientific content parsing contract

Status: `0.7.3` candidate, `structured-pdf-pipeline/3.9.0`; v2 remains readable.

Search-result v1 adds `reading_role`, `matching_rows`, `interpretation_status`
and `review_locations` without changing hit identities or legacy selection.
Review locations reuse the evidence export's primary/alternative block IDs,
unresolved text differences and local warnings on the hit pages. They are added
after ranking. Nearby text, observed rows and figure captions remain layout
context, not interpreted or verified experimental tuples. Selected evidence
export retains all corresponding readings and original-page anchors.
Scientific acceptance and publication remain pending in [V073_ACCEPTANCE.md](V073_ACCEPTANCE.md).

The release target is:

> Verified or explicitly registered local PDF → source-linked document → searchable, reviewable AI evidence

## Trusted input

Parsing requires a local PDF and acquisition sidecar. The gate fails closed unless:

1. both are regular files and the PDF is not in `_unverified`;
2. the acquisition schema is explicitly supported;
3. an acquisition record is `VERIFIED / MATCH / ARTICLE`, or a local-document/v1
   record is `REGISTERED / DECLARED` with an explicit title and ARTICLE/SUPPLEMENT role;
   a supplement carries its distinct parent PDF hash and article identity;
   the recorded DOI, when supplied, agrees with the optional requested DOI;
4. a fresh PDF SHA-256 and page count equal the acquisition evidence; and
5. neither PDF nor sidecar changes while parsing.

The parser never reacquires a failed input or converts an acquisition failure into
a trusted source.

## Canonical artifact

`aletheia-nexus/parsed-document/v3` is the current Canonical Scientific
Document. Its important fields are:

| Field | Contract |
| --- | --- |
| `artifact_id` | Deterministic parsed identity, independent of timestamp and local path. |
| `source` | Nullable DOI, title, article identity, ARTICLE/SUPPLEMENT role, identity basis, optional parent, PDF/sidecar hashes, page count and safe relative locators. |
| `parser` | Parser/backend versions, ordered stages, configuration and execution fingerprints, including relevant backend/runtime dependency identity. |
| `pages` | Displayed dimensions, MediaBox, CropBox, rotation, and canonical coordinate-system identifier. |
| `blocks` / `anchors` | Ordered text evidence with extraction method, confidence, separate engine agreement, page, bbox, and text span. |
| `sections` / `references` | Conservative structure and explicit resolved/unresolved citation evidence. |
| `figures` / `tables` | Caption, painted-region, and positioned-cell evidence only; `interpretation_status` is always `not-interpreted`. |
| `quality` | Coverage, counts, OCR use, uncertainty/review state, and resource termination. |
| `warnings` / `errors` | Structured code/detail plus page, stage, backend, and degradation fields where applicable. |

Positioned table cells may carry `row_span` or `column_span` (positive integers,
default 1), with `span_evidence` describing the geometric observation. Centered,
repeated group labels can cover multiple rows; multilevel headers can cover
their observed child columns. Empty cells are not filled with invented values.
These spans remain uncertain evidence, not verified scientific relationships.
Evidence packs retain the cell fields; text chunks provide table context but
are not a structured measurement export. A numeric fragment that straddles rows
is retained and flagged rather than silently discarded or assigned a guessed row.

Wide painted gaps may separate a multiword header or mixed label/value line only
when every resulting piece aligns with a distinct table column. This does not
guarantee complete recovery of sparse or nested table groups.

Whole header phrases can also be separated at narrow whitespace when their
painted positions uniquely align to distinct columns. Repeated sparse group
columns participate in the grid; nested centered conditions can span their own
observation rows without creating an invented numeric observation. Adjacent
column captions must remain separate. `TABLE_COLUMN_COLLISION` and
`TABLE_CONTINUATION_UNRESOLVED` identify supported local geometric conflicts;
they do not detect every unrecognized or truncated table.

Positioned figure `source_objects` may carry `text_completeness: not-verified`.
`RASTER_REGION_TEXT_UNVERIFIED` links the figure, page and image regions that may
contain untranscribed values, units or scale bars. Closely aligned image rows can
belong to one figure; an intervening caption ends that association. Region
coverage is not image-text recognition or a verified scale-to-panel relationship.

With adaptive OCR enabled, upright embedded images may receive a local OCR pass
on an isolated high-contrast footer band. Literal length labels, their engine
identity and source coordinates are retained; no inferred unit replacement is
allowed. Figure source objects may include `annotation_block_ids` pointing to
these blocks. `IMAGE_LABEL_UNRESOLVED` marks an observed length reading that
fails the confidence threshold. Ordinary or ambiguous footer text does not
create a speculative length warning. This is not general diagram recognition: arbitrary interior
text, rotated images, form nesting and unrecognized supplementary captions can
remain unread without that local warning. Full-image text completeness remains
`not-verified` after a successful label. The annotation execution identity is
versioned separately from unchanged full-page OCR extraction.

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

Original PDF pixels remain the scientific source. Native text and OCR are derived
readings. Optional OCR or specialist failures preserve native evidence and create
an explicit degradation warning. OCR disagreements retain native and alternative
readings, mark both uncertain and never silently substitute signs or numbers.
OCR confidence is the engine's
confidence; agreement is a different field. A figure caption does not mean the
figure was interpreted, and table-like positioned text does not mean a universal
table parser succeeded.

Embedded glyph evidence can contradict a unique explicit font mapping. A narrow
unit repair then retains the original and corrected line in
`NATIVE_UNIT_MAPPING_CORRECTED`; the corrected reading remains uncertain. No
paper-specific values or scientific plausibility rules override the source.
Mutually overlapping alternative OCR readings may share one review location
without a native primary. Grouping preserves every block and conflicting reading,
and does not choose a preferred answer.

`PARSED` means the configured evidence extraction completed. `PARTIAL` signals
sparse text, ambiguous glyphs, image-dominant pages, conflicts, failed pages, or resource limits. `FAILED` means no usable page result
survived. None of these states validates scientific claims.
Image-text completeness notices are informational for this completion status but
require review; a document can be `PARSED` while its image text remains unverified.

## Derived AI views

Markdown, JSONL, and structure-aware chunk exports are deterministic derived
artifacts, not new Sources of Truth. Every chunk independently includes source and
parsed IDs, block/anchor/page identifiers, exporter version/configuration identity
through its enclosing export, and detailed evidence chains:

```text
chunk → block → anchor → page/bbox → source artifact
```

Chunking respects sections and keeps table captions, observed cells and nearby
footnotes together; large split contexts are explicitly numbered. Corpus evidence
exports retain complete chosen page contexts, status and omission manifests.
v0.7 includes no embeddings, vector store, model-provider integration,
summarization, entity extraction, claim extraction, knowledge graph, MCP server, or
Agent implementation.

## Optional reading assessment

`aletheia_nexus.content` exports `EvidenceJudge`, `ReadingDecision` and
`assess_reading`. This is a small Python extension point for a caller-supplied
judge; the default parser does not invoke it. No provider or network client is
included, and no model call is needed for the deterministic repairs.

Build an evidence pack with the existing search selection and condition pages,
then choose a `parsed_artifact_id` and a `review_locations` ID:

```python
from aletheia_nexus.content import assess_reading

assessment = assess_reading(
    pack, my_judge,
    parsed_artifact_id=document_id,
    location_id=review_location_id,
    question="Which reading matches the original PDF at this location?",
)
```

`my_judge` supplies `name`, `version` and `judge(request) -> ReadingDecision`.
The request contains a copy of the selected document's complete included context:
source hash and PDF locator, primary and alternative readings, page/bbox anchors,
review target, and observed table cells with row/column positions. It does not
contain rendered PDF pixels; a visual judge must obtain them explicitly using the
source locator and verify its hash. Missing evidence calls for abstention.

Return `ReadingDecision("prefer" | "unresolved" | "abstain", block_ids, reason)`.
Non-abstaining decisions must cite the target location and may cite other blocks
in the supplied context. Unknown or duplicate references and missing reasons are
rejected; provider errors propagate. The result is advisory and bound to the
evidence-pack ID, with citations reconstructed from the original evidence.
It never overwrites parsed text or clears uncertainty, and does not decide that a
scientific claim is true. Original contradictions remain distinct. The caller
controls whether any external provider is used and what context it receives.

The runnable [offline integration example](../examples/assess_evidence.py)
accepts an exported JSON evidence pack and explicit document/location IDs. It
demonstrates abstention and saves an exclusively created, separate advisory file.
Replace its judge only when explicitly choosing a provider. Default parsing and
export never call it. Report AI-assisted results separately from default-reading
accuracy; an advisory preference does not erase a conflicting source statement.

Evidence-pack v1 remains additive and backwards compatible. Review locations may
also expose `primary_block_ids`, `alternative_block_ids`, `reading_differences`
and `local_warnings`. Text differences are comparisons of observed readings, not
scientific error classifications. Unpaired alternatives remain present. Markdown
shows primary table/figure readings, observed cell alignment and local differences
before expandable alternatives. A row span states the parser's observed layout
evidence; it is not confirmation of an experiment's scientific interpretation.
Display grouping and folding never count as resolved independent review issues.

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
