# v0.7.3 acceptance record

Status: **NOT ACCEPTED / NOT RELEASED**. The 0.7 series has not yet met its
closure conditions. Protocol: [V073_FINAL_PLAN.md](V073_FINAL_PLAN.md).

Baseline: v0.7.2, commit `643094b943c7ab9c7aa7de4ef5897d688617ae6f`.
Historical first scores remain historical. No v0.7.3 scientific accuracy,
review-burden reduction, independent review or publication success is claimed.

The task-local evidence ledger records baseline hashes, complete historical
adjudication, frozen tasks/queries/holdout, candidate execution identity, paired
first scores, any exposed regressions, local error coverage, source checks,
coverage and elapsed times. Restricted PDFs and authentication data are not
public deliverables.

## Baseline source audit, before product changes

The implementing assistant inspected 36 rendered source pages covering all 75
historically scorable questions plus the separately excluded source-glyph item.
This is a current source audit, not a new blind test or third-party review.
All 37 delivered PDF and parsed-artifact hashes match the delivery manifest.

| Measure | v0.7.2 evidence |
| --- | --- |
| Historical first result, unchanged | 52/75 |
| Current strict default complete reading | 69/75 |
| Current historical content rubric | 72/75 |
| Previously confirmed target content retained | 52/52 |
| Current strict failures without adequate local relation warning | 4 |
| Original excluded source-glyph item | 1, outside the unchanged denominator |

The six strict failures are missing microscopy panel identities (12-A3),
unrepresented shared table labels (18-A2, 24-A2, 24-A4), an unresolved temperature
glyph (28-A2), and a catalyst name split around its numeric table row (37-A3).
The three shared-label cases pass the historical content rubric but require
reconstruction under the stricter default-reading contract. This is a newly
identified baseline limitation, not a v0.7.3 regression. The temperature question
remains a failure despite a source-glyph caveat; it has not been removed.
Source conflicts in 03-A5 and 15-A1 remain intact.

Additional defects outside those targets include footnotes/caption continuations
inside table grids, missing minus signs in figure wavenumber labels, and a false
negative tick in a figure summary. They are development findings, not grounds
to change the fixed question denominator. No human-time saving is inferred.

Local evidence hashes (SHA-256):

- `baseline/current75-adjudication.json`:
  `3c072c69f268183e13910e2ac94a78f6efa0db0cf4ea85fb964000d909a9a28f`
- Frozen 20 tasks / 20 new literal queries, `protocol/tasks-queries-v1.json`:
  `87629cfcf58fe2ca3e0694a7f82694ae57f7c03740df6df0baabfdf17e5c4fa3`
- Exposure inventory (2,583 prior parsed files, 122 distinct identities),
  `protocol/exposed-identities.json`:
  `bec53a946d043f19b6d493b63d26701ff50e24f5a4b298c5e725c4b8db1a26a0`

The legacy delivery used English Tesseract plus image OCR. Its current artifact
audit is not the future paired holdout run in the locked bilingual configuration.

The literal retrieval baseline was rerun against the delivered corpus: original
article queries reproduce Top1 **12/32**, Top5 **19/32**; SI **3/4**. The new
frozen 20 queries give Top1 **13/20**, Top5 **16/20**. These are retrieval hits,
not complete-answer scores. Candidate results remain pending.

## Source-first holdout seal

On 2026-10-23 at 15:19:42 UTC, before any v0.7.3 product-code change or AN
parsing of these sources, 60 questions and source oracles were hash-locked:
16 prose, 20 table, 12 figure and 12 SI questions. The sample contains 12 main
articles (9 English, 3 Chinese) and 4 associated SI PDFs, **671 pages** retained
in full. Original pages supporting every answer were rendered and visually
inspected by the implementing assistant. This is not external independent
review or double-blind testing. No holdout score is available yet.

The expanded prior-exposure inventory conservatively excludes 312 identities,
including downloaded but previously unparsed PDFs. No sample hash, DOI or
parent/SI DOI matched. Two inaccessible initial main-article candidates were
replaced before parsing; one considered source was rejected for prior exposure.
An unavailable SI candidate was replaced by publicly available SI associated
with another selected main article. The original frame and reasons remain in
the local ledger. Selection used source content and access, never AN results.

Original-source disagreements include catalyst loading/material terminology,
a table-versus-prose statistic, and a main/SI result/method discrepancy. Their
oracles require the separate statements and sources to survive; no scientific
guessing is permitted. Native-only and the locked bilingual optional-OCR run
will be scored separately after the candidate is stable.

- `protocol/holdout-v1.json` (sources, questions, answers, rules):
  `2ac6e32b00144aceae120ffe2401987f9aacaaee45b23f52ae25bf71e10fc40e`
- `protocol/exposed-identities-expanded.json`:
  `4f178b8930112bc08d107c6b8e1a937b46c54b211b2aedc8a291a1ae027d3c73`

The 20-task baseline is now recorded before product tuning. Full-document
exports for each task retain all readings. The implementing assistant actually
checked **42 independent answer-affecting source issues**, median **2** per
task; default complete answers were **16/20**, and source-assisted completion
was **20/20**. Eight missing microscopy panel identities count eight checks.
Unrelated alternatives and display groups do not count. The candidate must
require at most **31** such checks, with median at most 2 and no loss of
completion, coverage or conflicts. The observed review wall time was 245 s
across four batches, including assistant/tool time; this is not human timing
and no human speedup is claimed. Per-task times were not measured.

- `baseline/tasks/adjudication.json`:
  `b8a5c76ee835868cd7545d71aa30527e5aa888fdd4f0ca01a872c7b787898676`

Pending release gates: no-regression checks;
20-task review comparison; 32+4 legacy and 20 new retrieval queries; new paired
holdout; scientific-use review; final-commit CI and clean-install use; merged
main verification; GitHub/PyPI publication and published-package verification.

## Development evidence (not acceptance)

The first 37-document fresh development extraction completed without parse-run
errors. Subsequent code changes require another extraction; these artifacts are
not a frozen release candidate. The six-page diagnostic probes also retained the
original primary text while changing OCR alternatives, but counts alone do not
establish accuracy or coverage.

On the unchanged v0.7.2 delivery artifacts, the revised retrieval code obtained
article Top1 **15/32**, Top5 **24/32**, SI **4/4**, and new-query Top5 **19/20**.
Queries and denominators were not changed. A temporary lost caption hit was
restored by retaining direct captions alongside region contexts. These are
development ranking results, not new parse accuracy or final acceptance scores.

Implemented mechanisms under review:

- Geometric association of a two-line description straddling a numeric table
  row; repeated explicit primed entry references for blank descriptive cells.
  Unsupported blank row labels receive local gaps instead of copied conditions.
- Region-limited OCR on native text pages. A whole-line mask was found to create
  an unrelated numeric error; native glyph provenance now narrows it to affected
  words and neighbouring context. Sparse/scanned pages retain whole-page OCR.
- Exact scientific-text agreement, including case-sensitive unit-only labels;
  high-confidence repeated corner readings for missing scaled-panel labels;
  an explicit local warning for nonmonotonic observed axis ticks. No tick value
  is repaired from an expected progression.
- Primary row/header/footnote search, separately searchable alternatives, direct
  figure captions, and bounded nearby-text retrieval. Repeated windows are
  deferred, not deleted or treated as interpreted experimental relationships.
- Visible primary table/figure evidence, observed cell alignment, local gaps and
  reading differences, with all alternative readings retained. Display changes
  are not credited as fewer independent source judgments.

Source checks confirmed the primed-label and split-description repairs. Four
additional microscope panel identities were read from actual corner glyphs;
four other missing letters still require review. A local Tesseract corner probe
did not provide reliable additional labels and was not added to the product.

The deterministic suite at this development checkpoint passed **1,938** tests
with **115** opt-in/platform skips. The frozen parser fixture evaluation retained
all 886 gold characters, 18/18 structural assertions and 32/32 anchored blocks.
These checks do not replace the pending real OCR/browser/platform release gate
or scientific evaluation. The holdout remains unopened.

The full hosted matrix on development commit `c135ef1` subsequently passed all
eight jobs (Python 3.11–3.14, Windows/Chromium, browser extra, OCR extra and clean
wheel packaging), run `39992117162`. It is not the final release-commit gate.
Fresh development extraction with its preceding implementation gave article
Top1 14/32, Top5 23/32, SI 4/4 and new-query Top5 19/20; the original query
30-A2 lost its designated hit and remains reported as a failure.

Whole-corpus primary-text comparison then rejected the `c135ef1` OCR masking
strategy for release: some valid figure labels disappeared when surrounding
page ink was masked, and isolated damaged words could be joined across columns.
These failures were outside the frozen question targets and were found before
opening the holdout. A smaller number of candidates was therefore not credited
as an acceptance benefit. Figure OCR now retains page segmentation context and
selects only readings at painted images; masked native-glyph regions use sparse
text segmentation (an explicitly requested segmentation mode remains respected).
Original image labels, conflicting readings and page coordinates are checked
separately from readable prose. Targeted source probes recovered the lost labels
and removed the observed cross-column fragment. Another fresh corpus run and
coverage adjudication are required before candidate freeze. The local failed
extraction, comparison and probe records remain available; no first score was
overwritten.
