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
