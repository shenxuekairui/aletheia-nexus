# v0.7.3 final research and release plan

Original frozen protocol date: 2026-10-23 (Asia/Singapore). The original numerical
gates and results below remain historical evidence. The owner authorized a
prospective scope amendment on 2026-10-24, after seeing the results; see the final
section. **Not yet accepted or released.** There is no planned routine 0.7.4
feature release.

## Evidence and scope

The release baseline is tag `v0.7.2`, dereferenced commit
`643094b943c7ab9c7aa7de4ef5897d688617ae6f`. Read the original adjudications,
source pages, captured artifacts and implementation; summaries are pointers, not
an alternative to those records. Preserve existing debug files, PDF bytes,
acquisition records, historical scores and tags. Keep restricted sources and
machine/account details outside the public repository. Local audit material is
stored in the task's `AN073_final_20261023` output directory with file hashes.

The default scientific reading, its metric and experimental context are the
unit of correctness. Stable capabilities remain local tools; original evidence
is immutable. No new engine, vector store, knowledge graph, GUI, general agent
framework, model router or automated scientific conclusion system is in scope.
No publisher expansion, full PDF reconstruction, structure recognition, general
reaction-arrow understanding or arbitrary plot digitisation is required.

Work in order:

1. Hash and inspect the original evidence. Complete a current, question-by-question
   adjudication of all 75 historical scorable questions before tuning. Keep the
   original excluded unreadable item separate; do not alter the denominator.
2. Freeze 20 source-review tasks and 20 realistic queries before implementation.
   Prepare and seal a new source-first holdout after checking exposure identities.
3. Repair demonstrated numeric/metric/context failures, then OCR fusion and
   retrieval. Each substantive rule needs the original failure, another layout
   and a counterexample against false merging. No DOI, title, target value or
   sample-specific substitution in product code.
4. Check task completion, necessary source checks, coverage, conflicts, exports,
   execution identity, compatibility and the existing judgment interface.
5. Freeze a candidate commit/configuration/environment, then open the holdout once
   for paired v0.7.2/v0.7.3 execution. Retain both native-only and OCR results.
6. Conduct a source-first scientific-use review of the final outputs, including
   misses and unflagged errors, separately from code/test review.
7. Complete local RC, clean installed-package use and the full hosted matrix on
   the final PR commit; merge, check main, then tag that verified main commit.
8. Publish GitHub Release, complete the existing PyPI workflow and independently
   install the published distribution; record artifacts and checksums.

## Fixed release gates

These gates are fixed before implementation or holdout parser execution. A
failed score must not change a question, threshold, denominator or accepted
configuration. A source-oracle correction requires the original record, source
evidence and an explicit amendment; report the original scoring alongside it.

| Measure | Required outcome |
| --- | --- |
| New holdout primary complete correctness | At least 90%; 95% is the stated target, not a substitute denominator. Values, signs, units, metrics, conditions and source attribution all must be correct together. |
| Paired improvement | Baseline errors >=4: reduce errors by at least 25% (integer ceiling); 1–3: reduce by at least 1; 0: retain 0. |
| Unflagged critical errors | Zero in the acceptance sample. A page/document PARTIAL flag is insufficient. Count local warning coverage separately from correctness. |
| Actual task review locations | Across 20 frozen tasks, at least 25% fewer independently necessary source judgments, median not higher; completion correctness, coverage and retained conflicts cannot decrease. |
| Original literal queries | Unchanged 32 article queries: Top5 >=20/32 and Top1 >=12/32; unchanged 4 SI queries: Top5 >=3/4. Keep the original designated-page scoring even if other answers are reasonable. |
| New realistic queries | Frozen 20: Top5 >=18/20; retrieval success and complete answer correctness are separate. |
| Preservation | Original confirmed 52 targets and H/I/J/K (16/8/12/12), latest 16-question regression: no new losses. Fully adjudicate all original 75. |
| Attribution and coverage | Every selected evidence item returns to its correct original page; confirmed source contradictions and all substantive alternative readings remain accessible and exported. No coverage reduction to improve warning counts. |
| Engineering and use | Final-commit full CI succeeds (skips are not passes), clean install, acquire/import, parse, search, selected export, source access, interruption/resume and legacy artifacts work. |

The 25% review target applies to **independent decisions needed for the same
research task**, not grouped UI items or raw uncertain-block counts. Three
substantive conflicts in one figure count as three. Record separately (a) errors
actually repaired, (b) exact duplicates actually removed, (c) display-only grouping,
and (d) unresolved independent issues. Record actual elapsed review sessions and
processing times, with reviewer identity and order; do not manufacture human-time
or speedup estimates from warning counts. An assistant's source review must be
labelled as such, never as measured human performance or third-party review.

Critical local coverage means the warning identifies the affected block, cell
relation or bounded source region and the kind of uncertainty that could change
the requested answer. Blanket warnings on all content cannot satisfy this gate.
A correctly reported gap or an abstention is safe behaviour but still fails
primary complete correctness for an answerable frozen question. Correct text
only in an alternative, or coordinates requiring reconstruction of relationships,
does not rescue a failed primary answer.

## Configuration and holdout

Primary acceptance configuration: the shipped CLI defaults with optional local
OCR enabled, `--ocr --image-ocr rapidocr --ocr-languages chi_sim+eng`, one Tesseract `tessdata_best` model set
with `chi_sim+eng`, 300 DPI, standard resource limits and paragraph merging. No
per-paper backend, model, parameter or output selection. Freeze exact runtime,
binary/model hashes and CLI-equivalent options before running. Run native-only
as a separate, fully reported configuration; never blend its answers into the
primary score. Default parsing makes no remote AI calls. AI-assisted scores, if
any, must remain separate and cannot satisfy the default-reading gate.

Holdout target: 12 previously untuned main articles and 4 associated SI files,
60 answerable questions, covering prose experimental conditions, table values
and relationships, directly readable figure labels/units/scales, and SI. Target
distribution: 16 prose, 20 table, 12 figure, 12 SI questions. Include at least
three Chinese main articles, multiple sources, native/scanned or mixed layouts,
and the user's established research directions. Selection must not use AN output
or favour easy layouts. Use file hashes, DOI and parent/SI identities to exclude
all prior development, stress, replay, tuning and holdout materials; uncertainty
about prior exposure disqualifies a source from the new holdout, not from
development. Record the sampling frame and all eligibility decisions.

Inspect rendered source pages first, recording precise question, expected
answer, metric, relevant conditions, source location and scoring components.
Hash-lock sources, questions, answers, queries and rules before opening parser
output. Candidate stability means relevant regressions and development checks
pass and its code/environment identities are recorded before the paired run.
The same assistant may prepare and adjudicate this source-first holdout; that
is not external independent review or double-blind testing. Non-random sample
scores cannot be generalised to all research literature.

If a holdout result informs a repair, the entire opened set becomes regression
material. Keep its first score permanently; a subsequent independent first score
requires a genuinely new sealed set with the same protocol. No retrospective
replacement of hard questions. Original scientific contradictions pass only
when both readings, their separate locations and uncertainty are preserved;
the parser must not choose a scientifically plausible value.

## Initial audit findings and decisions

The original v0.7.2 report distinguishes first 14/16 from regression 16/16,
52/75 historical scoring from 52-target preservation, and anchor coverage from
scientific accuracy. Retain those distinctions. Recompute stored totals from
individual records; verify changed targets at their source pages.

The implementation has position-based OCR fusion, optional image OCR,
whole-table search units, page-context evidence export and an advisory
`EvidenceJudge` interface already. Extend these bounded mechanisms only after
demonstrating a defect; do not introduce a second review system. Audit fuzzy
non-numeric OCR agreement, geometry-based containment, table context and
alternative-hit ranking for real loss or extra judgments. The current workflow
document's old “3 locations / 5 misses” statement requires current-evidence
qualification; historical reports themselves remain unchanged.

No proposed numerical release gate has been weakened. Exact sample identities,
task definitions and query text are separate hash-locked local manifests; their
public hashes and aggregate results belong in `V073_ACCEPTANCE.md`. Incomplete
evidence is a pending gate, not a passing result. Failures remain blockers in
0.7.3; nonblocking limitations are documented without expanding scope.

Before implementation, the 75-question audit additionally distinguishes the
historical content-preservation rubric (which accepted legible adjacent table
text) from the strict default-relation rubric above. Blank shared experiment
labels that require reconstruction fail the latter even when their component
text is preserved. Both results must be reported; neither rewrites historical
scores. This clarification does not weaken any release gate.

## Owner-authorized convergence amendment — 2026-10-24

After the complete second first-score report and bounded repair review, the
owner instructed: “门槛不是死的，达到设计目标就可以，不需要为了追求达不到的
指标一直修改，尽可能达到我们的设计目标和设计哲学，符合实际使用需求即可，
自行判断可以预留AI处理接口”. This explicitly changes the prospective closure
decision. It is **an amendment made after results were known**, not a claim that
the original numerical protocol passed or was changed before testing. The
original plan, all first scores, failures and denominators remain preserved.

The release is assessed as a local evidence preparation tool for research,
with scientific interpretation and critical data citation subject to source
review. It is not certified automatic extraction of complete experiments from
arbitrary figures, chemistry glyphs or source conflicts. Use these closure checks:

1. Keep demonstrated general improvements with bounded complexity. Reject
   changes whose wider effects outweigh their measured benefit. Do not add
   engines or rules merely to reach a sample percentage; no further holdout
   replacement solely to pursue a passing score.
2. Preserve confirmed core behaviors, original bytes, page identity, substantive
   alternate readings and source contradictions. Report remaining default errors
   and missed local notices explicitly; declaring a boundary does not repair a
   question, lower its denominator or turn its score into a pass.
3. Check the actual import/acquire, parse, resume, search, source access and export
   chain, including the original research tasks and retrieval evidence. Retain
   task-specific gains without claiming lower whole-library review burden.
4. Keep layout associations distinct from verified scientific facts. Remove
   demonstrated unsupported semantic assertions using minimal changes; do not
   build general interpretation machinery to replace expert review.
5. Reuse `EvidenceJudge` / `assess_reading` for bounded advisory review: cite
   existing evidence, allow abstention, save suggestions separately and preserve
   default local parsing without remote AI. Do not claim AI performance without
   separately measured results.
6. Complete full CI and clean installed-use checks on the final candidate,
   document remaining limitations in both user guidance and release notes,
   and make an explicit fitness-for-use judgment before publication.

The original 90% and zero-unflagged sample requirements are no longer automatic
vetoes under this owner-approved scope. Their actual failures remain visible.
No replacement numerical accuracy promise is invented. Engineering, evidence
integrity and transparent capability boundaries remain required. Formal
publication requires final review and uses the owner's explicit initial
authorization for commits, PRs, merging and formal release. The later instruction
forbids unauthorized publication; it does not revoke that authorization. The
earlier assistant wording suggesting another approval was needed is corrected;
there is no planned routine 0.7.4 feature version.

The local authorization and prior-plan snapshot are sealed in
`protocol/owner-convergence-amendment-20261024.json`, SHA-256
`ec65ef92d03c02a555af9ae150f6471ff2d0a8b1ba960e9138247149ea6e581d`.

The authorization clarification is preserved in
`protocol/publication-authorization-clarification.json`, SHA-256
`57ff48defec794c837bfce7fa71e05efbfbd47d5901d862bb52c4a5ecf944053`.
It does not waive final code/main CI, installed-use checks or publication receipts.
