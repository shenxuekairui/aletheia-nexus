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

Pending release gates: no-regression checks;
20-task review comparison; 32+4 legacy and 20 new retrieval queries; new paired
holdout; scientific-use review; final-commit CI and clean-install use; merged
main verification; GitHub/PyPI publication and published-package verification.
