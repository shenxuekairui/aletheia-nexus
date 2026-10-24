# v0.7.3 scientific acceptance and publication

Status: **SCIENTIFIC SCOPE REVIEW COMPLETE / FINAL ENGINEERING PENDING / NOT RELEASED**. The 0.7 series has not
completed its closure checks. No routine 0.7.4 feature release is planned. The owner authorized
a design-goal-based closure amendment on 2026-10-24 after results were known;
the original protocol and amendment are both in
[V073_FINAL_PLAN.md](V073_FINAL_PLAN.md). Original failed numerical gates remain
failed historical results; they are not retroactively relabelled as passes.

This record distinguishes historical first results, exposed regressions and
unopened validation. The implementing assistant checks source pages and code;
this is **not independent third-party review or measured human performance**.
The previous incremental record is preserved verbatim in
[V073_DEVELOPMENT_RECORD.md](V073_DEVELOPMENT_RECORD.md). Its intermediate
versions, incomplete runs and failures are historical checkpoints, not current
release certification. Original v0.7.2 records are unchanged.

## Current gates

The final bounded semantic adjustment changes panel length associations from
an asserted scale role to a compact `Panel (...): label ...` description.
Existing uncertainty flags and `positioned-panel-length` identify its unverified
layout role. Geometry, literal
values, raw alternatives and confidence stay intact; legacy method identities
remain readable. Final parser/fusion/image-adapter identities are
3.10.15 / 1.10.5 / 1.5.13. Content tests pass 729 with three skips. Fresh local
OCR on the exposed chromatogram page removes two false scale-role assertions.
Paired old/new association functions on identical fresh OCR records differ only
in role wording and method identity. Two real micrograph images retain all nine
length associations, and a no-association control remains unchanged.

These are targeted source checks, not another complete scientific score or
an independent evaluation. The chromatogram question still fails because its
experiment/peak/metric relationships remain incomplete. The table-stage exposed
regression below remains explicitly associated with that earlier stage;
neither old complete scores nor zero-miss claims are automatically transferred
to the final backend. Original first reports are immutable.

Local evidence: `panel-role-compact-source/source-role-review.json`, SHA-256
`68baf5aa3313fb5f4b0d54017b579413b16fd5cefdc5da65773d78d0043da2e1`;
`panel-role-compact-micrograph/source-role-review.json`, SHA-256
`482356a038898ccce1c64d8bee898a992175a7c912895acab5603ba0be9f1d91`.
Final-commit engineering, clean installed use and publication remain pending.

The longer intermediate wording on `68dab90` changed font-weighted paragraph
classification on five pages. It is rejected despite passing engineering
checks. Compact neutral wording avoids this collateral effect without adding
parser rules. On 86 exposed document executions / 1,847 cached pages, all 229
generated associations change only the intended wording and method identity;
the remaining complete page payload is unchanged. This downstream replay does
not rerun full OCR or constitute a new scientific score. The initial mismatch
diagnostics and span-aware comparison remain preserved. The final replay is
`panel-role-compact-replay/summary.json`, SHA-256
`e4399c384a65bccf13e7d5b9520445fad08c0a288f141a20d4de142a79c71361`.

The same 32+4 old and 20 new literal queries were rerun against the final replay:
old Top1 13/32, Top5 24/32; SI 4/4; new Top1 15/20, Top5 19/20. Twenty complete
task packs were re-exported. Removing the unverified scale claim has a real
review cost: T07 needs twelve length-role confirmations in addition to its four
unresolved panel identities. All twelve bars were checked on the source page;
these are separate judgments, not one folded figure. The supplemental ledger
therefore gives **33 checks versus baseline 42 (21.4% reduction)**, median 0.5;
18/20 default-complete and 20/20 after review remain the task conclusions.
Other task judgments are retained from the previous exposed review with the
same underlying evidence. This is a targeted supplemental review, not a fresh
twenty-task timing study. The original 25% burden target is no longer met;
the earlier 21-check result remains a historical stage, not the final claim.
Evidence: `panel-role-compact-task-supplement.json`, SHA-256
`969491e6bf27f8530a0a4e3bf1274270de78dcfaf21330ab86758b1a7513da47`.

Under the owner's amended scope, scientific review supports closure as a
**local evidence preparation and source-review tool**: bounded table and fusion
improvements, useful retrieval, preserved alternatives/source conflicts, and
working advisory interfaces justify retaining the release. Critical citation
and complex figure interpretation require source review; some errors still
lack local notice. This is not acceptance of the original accuracy, zero-miss
or final 25% task-burden targets. Further broad parser rules are not justified
by the observed regressions and complexity. Final engineering/use checks and
publication authorization remain separate requirements before release and
closure of the 0.7 series.

The [systematic engineering review](V073_ENGINEERING_REVIEW.md) covers the
complete release delta and end-to-end contracts. It found and tightened
script-flattening comparisons, false same-location OCR corroboration, axis-unit
comparison and an unsanitized optional-backend diagnostic; removed repeated
evidence reconstruction within each export; and corrected exporter identity.
The pre-opening frozen implementation is `84666bb`, using parser 3.10.14, fusion 1.10.3 and
image adapter 1.5.11. All eight hosted CI jobs, ten immutable local RC checks
and 24 clean installed-use checks pass. Its exposed targeted OCR regression is
**55/60**, with zero locally undisclosed critical errors in the frozen questions;
all scientific page payloads across 671 pages exactly match the preceding
targeted run. Five failed answers remain failures. This run is not full-file
default OCR or new sealed-sample acceptance.

The complete historical batch Q on `84666bb` now preserves all 64 historical
regressions, including the two shared-condition failures retained in P's 62/64.
All 54 documents / 503 pages completed; task exports, literal retrieval and
original75 preservation have been checked. The candidate was frozen before
opening the second sample for sequential paired execution. All four first
adjudications are now sealed. The second-set native first scores are
sealed at 24/60 for v0.7.2 and 28/60 for the candidate; critical errors without
adequate local notice are 27 and 16 respectively. The baseline OCR first score
is 25/60 with 26 such errors; candidate OCR is **35/60 with 14**. Ten answers
improve and none regress relative to baseline OCR. Errors decrease by 28.6%,
passing the paired-improvement rule, but the 54/60 minimum and zero-unflagged
gates fail. An unresolved Å/A unit after removal of a false minus remains
incorrect. No first score changes. The table below reports the original numerical
protocol, before the owner's later scope amendment; it is not the amended
fitness-for-use decision.

| Gate | Required | Current status |
| --- | --- | --- |
| New sealed primary OCR sample | At least 54/60; target 57/60; paired error reduction rule | **Failed**: baseline OCR 25/60; candidate OCR 35/60. Paired improvement passes; absolute minimum fails. Separate native: 24/60 versus 28/60 |
| Unflagged critical errors | Zero local omissions/errors without adequate notice | **Failed**: OCR 26 versus 14 questions; native 27 versus 16. Counts are questions containing at least one critical issue, not individual erroneous tokens |
| Original 75 and preservation | Full current scoring; original 52 target contents and 64 historical regressions retained | Q on 84666bb: 72/75 strict, 52/52 original contents retained, 64/64 historical regressions |
| Twenty research tasks | At most 31 independent checks, median at most 2; completion/coverage/conflicts retained | Q evidence retains P's 21 checks, median 0.5, 18/20 default completion and 20/20 after source checks |
| Retrieval | Old Top1 >=12/32, Top5 >=20/32; SI >=3/4; new Top5 >=18/20 | Q: old 13/32 and 24/32; SI 4/4; new Top1 15/20 and Top5 19/20 |
| Source/export/compatibility | Correct original pages, alternate readings and true conflicts retained | All four second-set modes source-reviewed and mechanically export-checked. Candidate source-conflict answer V06-Q02 remains incomplete; export integrity does not establish scientific completeness |
| Engineering and actual use | Complete CI and clean installation on final commit | 84666bb: 8 CI jobs, 10 immutable local RC checks and 24 clean installed-use checks pass; final release commit pending |
| Publication | Verified main, tag, GitHub Release, PyPI and installed distribution | Not published |

A warning can disclose a failure; it cannot make the answer correct. A correct
alternative, manual reconstruction of an experiment, abstention or missing
context fails complete default-primary correctness. Global PARTIAL is not a
local warning. Layout groups remain observed layout evidence, not certified
scientific data.

## Bounded table repair after second-set exposure

Parser 3.10.15 retains the limited indexed-table repair: a separately styled
label/title reaches the existing grid stages, printed header rules exclude
adjacent-column prose, and wide left-aligned headers retain short values in
their columns. Ambiguous overlaps, incomplete rows and broken index sequences
still abstain. An attempted broader Supplementary-caption/centred-grid expansion
was rejected: it introduced false directory/diagram table associations and
disturbed previously correct layouts. Its patch and outputs remain local evidence.

On the exposed second set, the current parser-only replay scores **29/60 native
and 36/60 OCR**, with **15 and 13** questions containing locally undisclosed
critical errors. Only V08-Q03 becomes complete: atmosphere/electricity controls
retain each experiment's yield, metric, temperature and source. The hydrate and
prime errors in V08-Q02/Q05 remain failed despite restored rows. No first score
is replaced. This is implementing-assistant regression review, not a new blind
test or third-party assessment.

All 54 historical documents / 503 pages and the old targeted regression's 671
pages retain their complete scientific page payloads. Both second-set modes
replayed all 16 documents / 673 pages; only V08 pages 2 and 5 changed. Its complete
ten-page file was then freshly extracted in native and fixed OCR modes: no
runtime errors and exact agreement with the replay. Native took 7.887 seconds
and OCR 202.277 seconds; this is not a controlled speed comparison. Page 2/5
exports preserve both tables, original pages, all primary text, alternatives
and warnings (73 native blocks; 146 OCR blocks including 31 alternatives).
No task-level burden reduction is claimed from these two table repairs.

Relevant content tests: 727 passed, three skipped; lint passed. Full final-commit
engineering verification remains pending. The regression, source review,
rejected trial and fresh extraction evidence are sealed locally under
`v2-table-probe/table-narrow/adjudication.json`, SHA-256
`30011204a9e0beda17df75dc5f9a03bb342cdc31e06851488f49a03f398dcc33`.

## Rechecked v0.7.2 baseline

The baseline tag resolves to `643094b943c7ab9c7aa7de4ef5897d688617ae6f`.
The original two-paper first result was **14/16**, followed by **16/16** on the
same questions after repair. The two first failures concerned experiment rows,
shared conditions and footnotes; the regression is not a new blind test.

| Measure | Verified baseline |
| --- | --- |
| Original user questions, historical first | 52/75 |
| Complete current pre-tuning audit, strict primary rubric | 69/75 |
| Same current audit, historical content rubric | 72/75 |
| Originally confirmed key content retained | 52/52 |
| Current strict failures without adequate local disclosure | 4 |
| H / I / J / K historical first | 5/16; 4/8; 9/12; 8/12 |
| H / I / J / K historical regression | 16/16; 8/8; 12/12; 12/12 |
| Delivered original library | 37 files, 287 pages, no parse runtime error |
| Anchored content blocks | 17,023; anchoring does not establish scientific correctness |
| Article review locations across historical repair | 1,961 to 1,985 |
| Uncertain blocks across historical repair | 5,447 to 12,475 |
| Literal original article Top1 / Top5 | 12/32; 19/32, previously 13/32; 20/32 |
| Literal SI Top5 | 3/4 |

The old final confirmation covered the original 52 key targets, not a fresh
complete score of all 75. Neither “23 failures remain” nor “75 pass” follows
from it. One originally excluded unreadable source-glyph item remains outside
the unchanged 75-question denominator. Ambiguous chemistry and actual source
contradictions remain distinguishable from parser errors.

The new 20-query baseline is Top1 13/20, Top5 16/20. The 20 frozen tasks require
42 independent source judgments, median 2: default completion 16/20, completion
after source checks 20/20. Observed assistant/tool review wall time is 245 s;
per-task human time was not measured.

## First sealed set: immutable results

The first source-first seal contains 12 main articles, four SI files, 671 pages
and 60 questions: 16 prose, 20 table, 12 figure and 12 SI. Source/DOI/parent
identities were checked against 312 conservatively excluded prior identities.
Original answer pages were rendered and checked before parsing. Both versions
use the same locked runtime, sources and prospectively selected configuration:
300 DPI, local `chi_sim+eng` best models and optional RapidOCR, one worker per
run. Native-only scores remain separate. Default parsing calls no remote AI.

The first v0.7.3 implementation is frozen at
`9a6d27d5f874bb3a00bbb4aab26f826d4c97ab96`; later fixes cannot change its score.

| First measure | v0.7.2 | Frozen v0.7.3 |
| --- | ---: | ---: |
| Native complete primary | 33/60 | 33/60 |
| Native prose / table / figure / SI | 15/16; 11/20; 2/12; 5/12 | Same |
| Native questions with an unflagged critical error | 16 | 15 |
| Optional OCR complete primary | 34/60 | 34/60 |
| Optional OCR questions with an unflagged critical error | 15 | 14 |

All four first configurations completed the 16 PDFs / 671 pages without runtime
errors. Neither native nor OCR complete accuracy improved in this comparison. Missing
figure text/relationships and false space-to-equals font repairs are failures,
not successes rescued by diagnostics. Both OCR category scores are prose
15/16, table 12/20, figure 2/12 and SI 5/12.

After the native results informed repairs, **the entire first set became exposed
regression data**. Both completed original OCR executions remain immutable.
Subsequent scores on these materials are regressions; a fresh run is not a fresh
blind sample. Per-document first scores and all original failures remain in the
archived record and local adjudication files.

| Source | First OCR v0.7.2 / frozen v0.7.3 |
| --- | ---: |
| H01 | 6/8; 6/8 |
| H01-SI | 1/3; 1/3 |
| H02 | 3/3; 3/3 |
| H03R | 1/3; 1/3 |
| H04R | 2/5; 2/5 |
| H05 | 2/3; 2/3 |
| H05-SI | 2/3; 2/3 |
| H06 | 3/4; 3/4 |
| H06-SI | 2/3; 2/3 |
| H07 | 1/4; 1/4 |
| H08 | 1/4; 1/4 |
| H08-SI | 0/3; 0/3 |
| H09 | 3/3; 3/3 |
| H10 | 1/3; 1/3 |
| H11 | 3/4; 3/4 |
| H12 | 3/4; 3/4 |

## Completed native and intermediate OCR exposed regression

Commit `0f6197909a9cd3e69129896a6f7e9a74106a0e7a` completed a fresh native
extraction of all **16 documents / 671 pages**, with zero runtime errors.
All 43 question-bearing pages have exactly the same primary/alternate block
text and geometry, table relationships and normalized local warnings as the
previously source-adjudicated native structural replay. Every cited text and
position was also checked before transporting those source judgments. This is
fresh extraction with native backend 1.19.5 and parser 3.10.10, not captured-layout
replay and not independent blind validation.

Earlier frozen `61d723b` completed another fresh extraction of all
16 PDFs / 671 pages with zero runtime errors. All scientific fields on **all
671 pages** match the `0f61979` artifacts exactly: blocks, anchors, pages, tables,
figures, warnings and errors. Each cited text, page and position was revalidated
before carrying forward the source judgments below. This strengthens the
retention check but does not turn a regression into a new blind result.

| Exposed native measure | Current result |
| --- | ---: |
| Complete default-primary answers | 46/60 |
| Prose / table / figure / SI | 15/16; 15/20; 5/12; 11/12 |
| Questions with an unflagged critical error | 0 |

| Source | Native complete |
| --- | ---: |
| H01 / H01-SI | 6/8; 3/3 |
| H02 | 3/3 |
| H03R | 1/3 |
| H04R | 3/5 |
| H05 / H05-SI | 2/3; 3/3 |
| H06 / H06-SI | 3/4; 2/3 |
| H07 | 4/4 |
| H08 / H08-SI | 2/4; 3/3 |
| H09 | 3/3 |
| H10 | 2/3 |
| H11 | 3/4 |
| H12 | 3/4 |

The 14 failed native answers remain failures. They include omitted outlined or
raster figure values, incomplete experimental/footnote associations, unreadable
material glyphs, units/reference labels and microscopy scales/lattice spacings.
Local notices cover the actual affected regions, including diagrams inside
observed tables. This does not satisfy the primary OCR acceptance gate.

The earlier `ba7f735` OCR regression was stopped after its first complete document
exposed an invalid-output failure; the historical development-M run was stopped
after four complete documents for the same cause. Both failed checkpoints are
preserved. An older `f4b1ff0` run is preserved after all 12 main-article
OCR outputs and all 16 native outputs completed; its remaining SI OCR was
explicitly stopped as superseded. It is not a complete 60-question OCR score.
The older historical extraction exposed empty-row exceptions in document 14
and two pages of legacy P01. The same generic guard repairs all three native
page probes; the original failures remain recorded. Complete current-corpus
recovery must still pass.

The new outline route uses the already selected local RapidOCR model on the
existing page raster. Only actual unmapped outline regions and one glyph-height
of adjacent context retain readings; clear native text is excluded. Three
exposed prototypes recover footnoted result groups and a microampere label.
Those prototypes are not credited as completed current answers. The fresh run
revealed that real model polygons contain NumPy float32 scalars, whereas the
prototype's JSON replay used built-in floats. The canonical layout contract
rejected the whole optional output, also losing otherwise valid Tesseract
readings. Six H01 pages and 11 pages across three historical documents recorded
optional-backend failures; zero top-level parse errors did not make them usable.

The adapter now converts model coordinates at its input boundary and validates
the vector result before adding it to the Tesseract output. Invalid supplemental
geometry retains the Tesseract reading plus an explicit failure notice. Fresh
real-model probes on three pages from two layouts observe float32 input, pass
canonical validation and recover the intended primary groups/unit; a Methods
page triggers no additional vector recognition. The 660-test content suite
passes with three opt-in skips. Parser/Tesseract identities are 3.10.10/1.8.3.
The `0f61979` OCR extraction was explicitly stopped as superseded after all
12 main articles and H06-SI completed: **13 PDFs / 251 pages**, covering
**46/51 complete answers and zero unflagged errors in that reviewed subset**.
The other nine SI questions remain unscored for this run. This is not a 60-item
score or an estimate of the final candidate. Completed artifacts, partial SI
layouts, source judgments and the stop reason remain saved. A fresh complete
16-PDF native run completed on frozen `61d723b`. Its OCR run was later stopped
as superseded after H01 and H08 completed (11/12 reviewed answers); partial
H06-SI layouts remain saved. No full 60-question OCR score is assigned to that
incomplete run, and no best-output selection across versions is allowed.

| Source | Intermediate OCR complete |
| --- | ---: |
| H01 | 7/8 |
| H02 / H03R / H04R | 3/3; 3/3; 5/5 |
| H05 / H06 / H06-SI | 2/3; 3/4; 3/3 |
| H07 / H08 | 4/4; 4/4 |
| H09 / H10 | 3/3; 3/3 |
| H11 / H12 | 3/4; 3/4 |

The five failed answers retain catalyst I/l ambiguity, a missing inverse-length
unit, a damaged reference-electrode label, incomplete microscopy labels/lattice
values and a missing scale/panel association. Local disclosures do not repair
them. H06-SI retains the true main/SI differences in yield measurement and ee;
H12 preserves the conflicting prose claim and tabulated R² values.

The completed development-N extraction exposed regressions in two historical
documents, affecting three questions.
In document 04, the complete correct reference-axis label was alternate-only:
the preservation check rejected the complete crop solely because the operator
VS/vs changed case. The repair normalizes only that standalone operator during
preservation comparison; unit/material case, signs and numbers remain exact.
A fresh real-model page probe restores the existing complete primary reading,
with the ambiguous OCR spelling and original fragments retained as alternatives.
In document 37, a short diagram symbol terminated the numeric grid after entry6.
The bounded interstitial-ink rule now permits nonempty nonnumeric OCR symbols
in the same empty interval between two consistently aligned experiment rows.
It keeps the ink as source content, without assigning it a numeric cell. The
same captured-page structural replay restores all11 experiments, including the
split catalyst label and39/86(R) row. Six previously failing scale/ink variants
now pass; native conditions, numeric cells, separate captions and changed-column
counterexamples remain protected. All670 content tests pass, with3 opt-in skips.
Parser/image-adapter identities become3.10.11/1.5.8. Neither probe is a completed
fresh corpus acceptance; original development-N failures remain unchanged.

Development N's complete strict rescore is **69/75**, with the originally
excluded source-glyph item kept outside that denominator. The six failures are
12-A3, 18-A2, 28-A2, 04-A7, 37-A3 and 37-A4. The last two lack a local relation
notice and count as **two unflagged critical errors**. Originally confirmed
targets have 50/52 strict-complete readings; key-content retention under the
older rubric was not separately rescored at this checkpoint. Neither strict
failure nor an alternate-only answer is hidden by the historical rubric.

N's extraction is locked to `0f61979`, but automatic downstream analysis imported
the working checkout and lacks a verified import-time code lock. Its query/task
outputs are diagnostic only. The manual 75-item record is based on hash-verified
parsed artifacts and remains valid intermediate evidence. Development O
locked both extraction and analysis to `61d723b` and started rerunning all 54 PDFs /
503 pages. The repaired 04/37 full-document probes preserve the reference-axis
reading and all 11 experimental rows, but do not replace O's final scoring.

O was subsequently stopped as superseded with 33 documents / 228 pages complete;
no full75, historical64, task or query result is assigned to it. Its two repaired
documents were visually rechecked and all completed/partial artifacts remain.
Development P then ran all 54 documents with both extraction and analysis
pinned to `364052f`. Its completed results and the later Q validation are
recorded below; no complete result is assigned to the interrupted O run.

## Scoped exposed development regression after the engineering review

Before executing `364052f` on the exposed set, a separate development-method
record fixes all **60 questions and 43 question/related-source pages**. Those
43 pages use the identical frozen OCR configuration; the other 628 pages supply
fresh native context. The verification-only backend records this routing in
its execution identity. This is **targeted development regression**, not a
complete default-OCR extraction or a new blind score. No question is removed,
no page is selected from its parser result, and no answer combines the best
outputs from different versions.

Repeated full OCR of hundreds of unqueried spectra pages was consuming most of
each small engineering iteration. Restricting this already exposed development
check reduces that repetition while retaining all question-bearing sources.
The historical corpus retains complete default-config extraction of all
54 PDFs / 503 pages. The second 16-PDF / 673-page paired sample also remains a
**complete-file** execution in both versions and configurations.
All numerical release gates, source oracles and first results stay unchanged;
the targeted regression cannot satisfy the new-holdout gate by itself.

This run is now complete: 16 files / 671 pages processed, with fresh uniform OCR
on the 43 fixed pages and native context on the other 628, without runtime errors.
Observed processing wall time was 2,065.05 seconds; this is not a controlled
speed comparison or human review time. The 60 questions score **55/60**:
prose 16/16, table 19/20, figure 8/12 and SI 12/12. Five incomplete answers remain
failures despite their local disclosures; the count of locally undisclosed
critical errors in these questions is zero.

| Source | Current targeted OCR regression |
| --- | ---: |
| H01 / H01-SI | 7/8; 3/3 |
| H02 | 3/3 |
| H03R | 3/3 |
| H04R | 5/5 |
| H05 / H05-SI | 2/3; 3/3 |
| H06 / H06-SI | 3/4; 3/3 |
| H07 | 4/4 |
| H08 / H08-SI | 4/4; 3/3 |
| H09 / H10 | 3/3; 3/3 |
| H11 / H12 | 3/4; 3/4 |

The failures are H01-Q01 (catalyst I/l ambiguity), H05-Q03 (missing inverse-length
unit), H06-Q04 (reference-electrode notation), H11-Q04 (missing microscopy
identity/lattice information) and H12-Q04 (missing scale/panel association).
Where earlier source judgments were retained, all question-page blocks,
anchors, table/figure relations and warnings were compared exactly after
resolving opaque IDs, without Unicode normalization. H07 and H12 each added
one uncertain non-answer stroke/logo fragment; both differences were inspected
against the original page, and no accuracy improvement was credited. The nine
remaining SI questions received fresh source-page adjudication.

The review also records limits outside the requested answers: H08-SI's page-48
current-axis exponent/unit is incomplete and locally flagged, while its asked
peak/onset potentials and conditions are complete native prose. H01-SI page 20
prints different Ni loadings in its diagram and paragraph; both remain separate.
Neither a question pass nor this aggregate certifies every scientific statement
on those pages. These results do not replace the immutable first 34/60 OCR score
or establish the paired improvement gate on the new unopened sample.

## Current historical scoring and remaining preservation blocker

Development-P's original library has completed fresh full-document extraction
under its fixed historical configuration on `364052f`. The complete current
rescore is **72/75 strict primary answers**, or **73/75** under the separately
retained historical-content rubric. The original excluded unreadable item is
still excluded. All original 52 target contents remain, although only 51 satisfy
the stricter complete-answer rubric: the missing imprint-to-row association in
18-A2 is still a failure. The other strict failures are 12-A3's four missing
microscopy panel identities and 28-A2's ambiguous native source glyph. Their
local limitations remain disclosed; none is promoted to a correct answer by
its warning. Exact page-payload retention and separately source-reviewed repairs
support this rescore; this is an exposed implementing-assistant review.

The same 20 frozen tasks were then reviewed from complete document exports,
including all 40 oracle references and main/SI sources. They require **21
independent source judgments**, versus 42 at baseline, with median **0.5 versus
2**. Default completion is 18/20 versus 16/20; completion after checking sources
remains 20/20. Twenty-five baseline issues are eliminated, four new competing
readings require checking, and no credit comes from display grouping. Three
conflicts in one table still count three; four missing panel mappings still
count four. True source conflicts and the incomplete SI solvent wording remain.
Observed assistant/tool wall time is 117.157 seconds, including concurrent probe
polling and prior source knowledge; it is not measured human time or a speedup
claim. These results belong to `364052f`, before the next repair.

The broader historical64 preservation check found two further regressions:
H01-4 and J01-3 retain their numbers but lose centered shared-condition spans.
OCR punctuation over part of a native glyph becomes an independent cell and
breaks the grouping. The complete P review is **62/64**: H 15/16, I 8/8,
J 11/12, K 12/12 and latest 16/16. Required table values, experimental context
and source conflicts remain in the other 62 questions; unrelated image text
and unasked content are not certified. Thus preservation is **not passed**, irrespective
of the 75-item score, engineering tests or task improvement.

The complete P batch finishes 54 documents / 503 pages without parse runtime
errors. Its final twenty task exports are exactly equal to those manually
reviewed from the already completed documents. The unchanged 32 article queries
score Top1 **13/32**, Top5 **24/32**; SI **4/4**; new queries Top1 **15/20**,
Top5 **19/20**. The new Q06 failure and eight old Top5 failures remain recorded;
retrieval hits are not complete-answer scores. Across the original 37-document,
287-page library, article review locations instead rise to **2,404** from 1,985,
uncertain blocks to **13,671** from 12,475, and median locations to **48.5** from
38.5. This is an adverse whole-library result, not a burden reduction. The
frozen-task reduction does not justify hiding these additional candidates.
Source inspection of the two largest increases (papers 17: +130 and 16: +91)
finds mixed useful labels and incorrect structural fragments in vector reaction
diagrams. This does not establish that all extra warnings are necessary. The
inspected pages remain a local source/multimodal-review boundary; no chemical
guessing or blanket suppression is introduced to improve the count.

A minimal fusion repair now locates such punctuation using actual overlap and
containment within a known native glyph. It uses the existing disagreement and
alternative-reading path; the table algorithm is unchanged. Five preselected
pages were freshly extracted under their respective unchanged historical
configurations. The two affected pages retain every line's text and geometry;
the punctuation becomes an alternative with a local notice. Structure replay
restores the three four-row current-density groups and two eight-row material
groups, matching the original pages. The other three PageLayouts are exactly
unchanged. This is scoped regression evidence, not complete-document acceptance.
An earlier probe used the holdout configuration by mistake and is retained but
excluded from paired attribution. The full historical64 review, final candidate
retention and unopened sample remain required.

The repair is committed as `84666bb`, with fusion identity 1.10.3. Its fresh
complete historical batch is running from an immutable archive. The exposed
targeted regression completes all 16 documents / 671 pages without runtime
errors in 1,958.888 seconds of observed wall time, not controlled human or
performance timing. All 671 scientific page payloads exactly match `364052f`,
including the 43 frozen OCR pages and their warnings/alternative readings.
The same 55/60 result and five failures are retained, not replaced by a new blind
score. All eight jobs in the
[84666bb hosted matrix](https://github.com/shenxuekairui/aletheia-nexus/actions/runs/40074584721)
pass. All ten immutable local RC checks also pass: 2,190 deterministic tests
(117 skips), 121 real-browser tests, two normal-browser tests and one real-OCR
test. These engineering results do not close the scientific preservation gate.
Its clean installation also passes all 24 actual-use checks, including public
acquisition, optional OCR, old artifacts and interruption/resume. All 149 Python
sources match the archive; only the four authored PDF fixtures are packaged.
The unpublished wheel SHA-256 is
`3745cdc5e8aa03c062fd1534a8dd00587c2a1ba911d006da32e626bfac8438d6`;
sdist SHA-256 is
`cdbdb7d11f3c66cbbef4db6858bcc71925594406c1e556f06f1ef07314cc7aab`.

The five remaining exposed targeted failures are explicit and locally disclosed:

| Frozen question | Remaining default-reading failure |
| --- | --- |
| H01-Q01 | Catalyst table labels confuse iodine I with l; correct spelling in prose does not repair those row labels. |
| H05-Q03 | Four FTIR annotations retain their numbers but lose the cm⁻¹ exponent. |
| H06-Q04 | The figure's Fc⁺/⁰ reference is split/misread, despite retaining the other panel's results. |
| H11-Q04 | A microscopy panel identity and lattice labels/value association remain incomplete. |
| H12-Q04 | Some scale values lack panel identities and one required scale is absent; a caption alone cannot supply the associations. |

These remain failed answers even with bounded source notices. Correct fragments
elsewhere, alternate readings and source inspection do not upgrade the default
score. Full per-question source locations, primary evidence and warning records
are retained in the hashed local adjudication; no chemical dictionary or
invented figure relationship is used to complete them.

## Complete Q preservation before the second opening

The immutable `84666bb` archive completed all **54 documents / 503 pages**
under the fixed historical settings. Source bytes, actual page counts, complete
page processing and block anchors were checked; no runtime parse errors,
invalid block anchors or backend-failure warnings occurred. Original PDF/font
diagnostics remain in the raw logs. Observed extraction wall time was 4,333.288
seconds with concurrent verification; this is not a controlled speed comparison.

| Same materials and rubric | v0.7.2 audit | Q on 84666bb |
| --- | ---: | ---: |
| Original75 strict / historical-content | 69/75; 72/75 | 72/75; 73/75 |
| Original52 content / strict complete | 52/52; 49/52 | 52/52; 51/52 |
| Historical H/I/J/K plus latest16 | 64/64 | 64/64 |
| Old article Top1 / Top5; SI Top5 | 12/32; 19/32; 3/4 | 13/32; 24/32; 4/4 |
| New query Top1 / Top5 | 13/20; 16/20 | 15/20; 19/20 |
| Task default / after source checks | 16/20; 20/20 | 18/20; 20/20 |
| Independent task judgments / median | 42 / 2 | 21 / 0.5 |
| Article review locations / uncertain blocks | 1,985 / 12,475 | 2,404 / 13,671 |

All 503 scientific page payloads were compared with P, resolving opaque IDs
without normalizing scientific text. Exactly three pages changed. Fresh complete
H01/J01 p4 outputs reproduce the source-reviewed shared spans and restore the
two historical answers; P's 62/64 stays unchanged. On exposed T0 P02-MAIN p4,
the false dot overlapping “Electric” moves from a table cell to a located OCR
alternative. All 113 located text readings and all 36 body cells remain. Its
pre-existing incomplete multilevel header relationships are not awarded a
correctness improvement. All three changes were checked against original pages.

All original75 question pages remain exactly equal to P, retaining its three
strict failures, local notices and original52 contents. All twenty complete task
exports are equal after validating and resolving only their changed parsed
artifact identities. They therefore retain the prior source judgments: 25 old
issues eliminated, four new issues, zero display-only credit. This equality
check is not another manual timing session. Whole-library review counts remain
worse than the baseline; the task-specific reduction cannot erase that result.
Literal query failures remain recorded with the unchanged designated-page rubric.

## Earlier completed development checkpoint

The earlier development-H extraction completed 54 exposed documents / 503 pages
without runtime errors. Its results are retained here for comparison, **not
substituted for validation of the later parsing implementation**.

| Same material and rubric | v0.7.2 audit | Development H |
| --- | ---: | ---: |
| Original 75, strict / historical-content rubric | 69/75; 72/75 | 72/75; 73/75 |
| Originally confirmed target contents | 52/52 | 52/52 |
| Historical H/I/J/K plus latest regression | 64/64 | 64/64 |
| Old article Top1 / Top5; SI Top5 | 12/32; 19/32; 3/4 | 14/32; 24/32; 4/4 |
| New queries Top1 / Top5 | 13/20; 16/20 | 14/20; 19/20 |
| Tasks, default / source-assisted completion | 16/20; 20/20 | 18/20; 20/20 |
| Independent source judgments / median | 42 / 2 | 21 / 0.5 |
| Observed assistant/tool wall time | 245 s | 322 s |

The 21-check reduction comprises 25 repaired/eliminated issues and four newly
visible substantive differences; display-only grouping contributes zero. No
human speedup is claimed. The original 52 have only 51 strict-complete readings
because an existing shared-label gap remains; key-content preservation is not
strict 52/52. Strict failures 12-A3, 18-A2 and 28-A2 remain locally disclosed.

Whole-library exported article review locations instead rise from 1,985 to
1,990, uncertain blocks from 12,475 to 13,125, and median locations per article
from 38.5 to 42. The task-specific reduction does **not** establish a reduction
in whole-library manual burden. Literal query failures, alternative reasonable
answers and the original designated-page scoring remain in the ledger.

## Second opening and final release work

The second seal retains the same 12-main/four-SI, 60-question distribution and
all fixed gates, with 673 pages. It excludes prior development and the complete
first set. One access-blocked article was replaced by its recorded reserve
before parsing; the original sampling frame and reason remain. The candidate
freeze records all completed development gates, exact code, runtime, source and
runner hashes. First execution has completed: v0.7.2 native, v0.7.2 OCR, v0.7.3
native and v0.7.3 OCR run sequentially with one global document worker and no
concurrent development extraction. All 16 files / 673 pages run in every mode.
The recorded workflow specified review after an entire mode completed. Actual
review order departed from that statement: saved manual drafts for 15 baseline
OCR documents and five candidate native documents predate their whole-mode
completion. Review used completed per-document execution records; final review
packs and first-adjudication seals were created only after whole-mode completion.
The code, runtime, questions, answers, denominator and gates stayed fixed; there
was no tuning, per-document rerun or configuration selection. File modification
times establish saved checkpoints, not exact first-view times or human review
duration. The deviation is preserved in a separate audit, not erased by changing
the earlier statement. The user subsequently explicitly authorized concurrent
checking of completed documents. Candidate OCR review then used terminal
per-document records and verified source/output hashes; its final score was
sealed after all 16 files completed. This prospective authorization does not
erase the earlier deviation. This is source-aware implementer adjudication,
not blind or external independent review.

All four complete first adjudications are now sealed. Each mode processed all
16 documents / 673 pages with zero parse runtime errors. The following table is
complete-primary correctness; it does not combine answers between configurations.

| Document | v0.7.2 native | v0.7.2 OCR | Candidate native | Candidate OCR |
| --- | ---: | ---: | ---: | ---: |
| V01 | 3/6 | 3/6 | 5/6 | 5/6 |
| V01-SI | 2/3 | 2/3 | 2/3 | 3/3 |
| V02 | 3/6 | 3/6 | 4/6 | 4/6 |
| V03 | 2/5 | 2/5 | 3/5 | 4/5 |
| V03-SI | 1/3 | 1/3 | 1/3 | 2/3 |
| V04 | 3/5 | 3/5 | 3/5 | 3/5 |
| V05 | 2/3 | 2/3 | 2/3 | 2/3 |
| V05-SI | 0/3 | 1/3 | 0/3 | 1/3 |
| V06 | 1/3 | 1/3 | 1/3 | 1/3 |
| V07 | 1/5 | 1/5 | 1/5 | 4/5 |
| V07-SI | 2/3 | 2/3 | 2/3 | 2/3 |
| V08 | 2/7 | 2/7 | 2/7 | 2/7 |
| V09R | 0/2 | 0/2 | 0/2 | 0/2 |
| V10 | 1/2 | 1/2 | 1/2 | 1/2 |
| V11 | 1/1 | 1/1 | 1/1 | 1/1 |
| V12 | 0/3 | 0/3 | 0/3 | 0/3 |
| **Total** | **24/60** | **25/60** | **28/60** | **35/60** |
| Questions with critical issues lacking adequate local notice | 27 | 26 | 16 | 14 |

Candidate native gains four complete table answers and loses none; reducing
36 errors to 32 does not satisfy the paired 25% reduction rule, 54/60 minimum or
zero-unflagged requirement. Native is the separate diagnostic configuration,
not the primary OCR gate. By category, candidate native is prose 13/16, table
10/20, figure 0/12 and SI 5/12. Newly bounded gaps still fail correctness. Remaining
problems include missing figure text and panel relations, detached exponents,
incorrect chemical glyphs, truncated tables and fragmented experimental roles.
Candidate OCR is prose 13/16, table 14/20, figure 0/12 and SI 8/12. Its ten
paired gains are eight table questions and two SI questions, with no losses.
The 25 remaining failures include missing experimental relationships, native
fragmentation, incorrect glyphs, missing or detached units/exponents, and
incomplete source-conflict preservation. All twelve figure questions fail
complete correctness despite useful recovered text; nine of those have local
disclosure and three contain at least one critical issue without adequate
local disclosure. Warnings and recovered tokens are not complete answers.

V03-Q01 quotes the general Table1 footnote alongside its first result. A separate
source qualification preserves the explicitly marked specialized conditions;
retaining the two statements does not certify that their conditions form a single
procedure. That qualification changes neither the frozen question nor its failed
native score. V08-Q06 uses the explicit Scheme4e reference from page5 to the
page6 caption; page6 was already source-sealed for another question. This direct
reference is retained in the baseline and candidate audits, not inferred from
similar experiments.

All four modes passed mechanical selected-evidence export audits:
16 documents / 44 question pages each, retaining respectively 1,851 / 3,540 /
1,821 / 4,995 blocks and 0 / 476 / 0 / 903 alternative blocks. Counts differ with extraction
and grouping; they are not coverage or burden scores. Audit success means the
selected parsed evidence and its source identity survive export, including wrong
readings and gaps; it does not make those readings scientifically correct.
Observed native batch wall times are 401.112 s and 455.358 s; OCR is
6,243.377 s versus 6,501.390 s (candidate 4.13% longer, about 108 minutes). Read-only review/export activity overlapped some runs, so these are
recorded execution times, not an isolated speed benchmark or human-time measure.

On `0f61979`, 2,131 deterministic tests pass, 115 opt-in or platform skips;
660 content tests pass with three opt-in skips. The complete
[hosted matrix on 0f61979](https://github.com/shenxuekairui/aletheia-nexus/actions/runs/40059220825)
has eight successful jobs, including Windows, browser, OCR and clean wheel.
Skipped draft runs are not passes. The complete local RC subsequently failed
one real-browser case: disabling CNKI refresh retry still produced two detail
visits. The popup-timeout fallback opened the selected URL again after a
submitted result click. Four deterministic cases reproduced the duplicate
request. The repair reuses only a newly opened child of that click or its
observed same-tab navigation; an unresolved timeout now fails explicitly.
It never retries the detail URL implicitly or adopts unrelated/existing tabs.
All 122 provider tests and four real-browser refresh/timeout combinations pass;
a fresh complete local RC is still required. This acquisition-only repair does
not change the parser, its execution identity or ongoing scientific artifacts.

Earlier failed Windows attempts and the optional PARSED-only public-OA check
remain failed historical records, not rewritten or waived. The hosted matrix on acquisition-only `a199b57` also passes
[eight jobs](https://github.com/shenxuekairui/aletheia-nexus/actions/runs/40061043717).
Its local RC used the working checkout and overlapped subsequent source/test
edits; retain that report only as a diagnostic, not immutable-commit validation.
The final local RC must run a dedicated archived checkout. Subsequent immutable
ten-check local RCs pass on `7954f54` and `61d723b`. All24 clean installed-use checks pass
on the unpublished `0f61979` wheel, including actual public acquisition and
source-byte verification;149 Python source files match its archive and only
the four authored PDF fixtures are packaged. This is not published-package
or final-commit certification.

On `61d723b`, the [full hosted matrix](https://github.com/shenxuekairui/aletheia-nexus/actions/runs/40065089590)
has eight successful jobs. Its immutable local RC has ten successful checks,
including 2,167 deterministic tests (117 skips) and 121 real-browser tests.
Its separately built unpublished wheel passes all 24 installed-use checks;
149 source files match its archive and the package includes only the four
authored PDF fixtures. Wheel SHA-256 is
`ead3733f4c8dd332565f39027c85d39c68ad1cd80e1cf3070774856742bbe3eb`;
sdist SHA-256 is
`65a55c876513b8a08be821c42b90f739cda6a5f83de54585858d74180102a0df`.
These engineering checks do not establish scientific acceptance or publication.

The newer `364052f` also passes eight hosted jobs, all ten immutable local RC
checks and all 24 clean installed-use checks. Its RC includes 2,176 deterministic
passes / 117 skips, 121 real-browser passes, two normal-browser passes and one
real-OCR pass. Its wheel/sdist again match all 149 archived Python sources and
include only the four authored PDF fixtures. The unpublished wheel SHA-256 is
`015e5eb55d74e24a3629bbc844f37e4f5e2f4f8424ca31857624e6d14078fdf9`;
sdist SHA-256 is
`bd01b9ff700f8e830f50042b319492ce79ba2d163e70236ec04e68e90cc07690`.
The public acquisition/install check is actual use, not a scientific accuracy
score. The final release commit and published-package checks remain required.

The second set now becomes exposed regression material because its sealed
failures inform repair decisions. First scores and gates remain immutable.
The user's convergence direction permits hard semantic reconstruction to remain
an optional local-AI review boundary, but does not waive failed questions.
The engineering review records all 25 failures in four repair/boundary groups.
Nine whole-answer cases are provisionally outside bounded parser repair; even
hypothetically fixing the other sixteen would yield only 51/60 on this exposed
set. That arithmetic is a ceiling under the stated deferral, not a measured
regression or a revised acceptance target. Do not replace hard questions or
repeat new holdouts merely to chase the score. Default and future AI-assisted
results remain separate; no remote model was used by the parser.

Under the later owner amendment, remaining release work is exact-final-commit
CI and clean use, PR merge, verified main, explicit publication authorization,
v0.7.3 tag, GitHub Release, existing
PyPI publication and fresh published-package installation/checksums. Until these
actually pass, no release or closure claim is made.

## Evidence identities

Detailed evidence is in the task-local `AN073_final_20261023` directory. Public
material excludes restricted PDFs, credentials and authentication state.

| Evidence | SHA-256 |
| --- | --- |
| Pre-tuning full75 adjudication | `3c072c69f268183e13910e2ac94a78f6efa0db0cf4ea85fb964000d909a9a28f` |
| Frozen20 tasks/queries | `87629cfcf58fe2ca3e0694a7f82694ae57f7c03740df6df0baabfdf17e5c4fa3` |
| First source/question/oracle seal | `2ac6e32b00144aceae120ffe2401987f9aacaaee45b23f52ae25bf71e10fc40e` |
| First native adjudication | `2c20d97444772554416880a7c111f6a284676ce0a37a6043ad944d32645aeb36` |
| First frozen-candidate OCR adjudication | `64730cddc17191f93088dd13993f2ae18e60f57aeff97ca915e9e726c197f00d` |
| First baseline OCR adjudication | `f560cd4c0a3bdf45cff6e9e818606c0b68f981d1f3d84651684321445816b7dc` |
| First-set promotion to regression | `bf1c032e42bcfc08f2325f6c9aa3456b693909ec5a9a265e48251de319936fd8` |
| Fresh 0f61979 native adjudication | `a567cef12d2f0b55e98f20a07effc6dd631c430d1282adf95f1b4d4bb685a61f` |
| Fresh 61d723b native adjudication, all-page comparison | `0eefb9bdecf3b7ff86ba744460f7e0d47f8733c5e5925c8851f984870ff11e77` |
| Intermediate N complete75 adjudication | `5f6fe5fdf8689656dd827e18c18c652f43d1c0a6faa88cb1a5360e5fc9980622` |
| P complete75 adjudication on 364052f | `3514eab750ca63ffb2f11f2dbcacc33a4cf652c3ec4047760ebbe56c8a83e4a7` |
| P twenty-task manual review, metadata correction only | `3ec9d902fd3adb4e30c7d0f434b91a5c04352fc223702d28d224e4a36f7831b4` |
| P complete historical64 review, 62/64 | `44b266bd7b4d1c106a637845a2043634123e430e07d16a88c3108c86c7a1c320` |
| P twenty reviewed task exports equal final batch exports | `2702394498dd0fba512ce73105e1e21c3616075c4c46ee9f2f15cb2ed61108bb` |
| P source spot-check of the largest review-count increases | `72e963a52580d63b4922ff7d9898bbd5e495a6b1660a1207465f7d0c13f2c8f5` |
| Matched five-page punctuation-fragment comparison | `0fe3f644a9beea37a505025a444c1bbb9be9e96f9c92e2f771d5e9875505f9d1` |
| Two shared-condition source-page reviews | `26030ef4f4bf0510b17c1cc3b430ab2185e9f25a254e063691484ca969904a9c` |
| Superseded 0f61979 OCR stop and reviewed subset | `89e71017dfe3801452353e82fc188df632bf727409d7f9a41b360a3997462d42` |
| Engineering source/test/CI review on 61d723b | `6a2bd2f769c10167a91e3b60c5a2678b378c4f2e459212e05421ac32ca30e2ac` |
| Eight-page consensus-guard source comparison on 364052f | `23836ecad274a984f63d57d82b4642f410e8c74dffc276a183b2e955170d5aae` |
| Engineering/CI/RC/installed-use seal on 364052f | `cf3b1dafeb7022ad4876fc6e7a48c5d5b361976874f85e4d612db64bae270727` |
| Engineering/CI/RC/installed-use seal on 84666bb | `abb054e260c29860d0e3afa81a0117bc8ef2fc4a228abe7a377dfabe3d2a2dc3` |
| Prospective exposed-development routing method | `7d54fb04370cc06905027929191b0f359b78f511f4dcb6e40b8876dc075f69b1` |
| Complete targeted exposed OCR regression on 364052f | `1a4368c70e4dc7ff2fb54bb70954f4816c0166e0adbfe7a5cfd994ef03a28b9e` |
| Complete targeted exposed OCR regression on 84666bb | `2397bd8005719d55085e71953def1285a12a807f60b7388953ee1dce5a5fa5c2` |
| All671 page payloads retained between the targeted runs | `b29fb8f5d726c73d23b18dd73bb22efa20772e11e0cae2d92ce544e1d6fe1783` |
| Fresh ba7f735 native adjudication | `e5992bff581004989278edbdcb2ab04b3a42b1f5fa9441394d0a99fa5b2f6a02` |
| Q complete75 retention | `7d56b2eaf7754f283b9a93bf2aff5a8c618d211b7a00cf24c6274e896fa97b6e` |
| Q historical64 adjudication, 64/64 | `5e5fad946ebd7bc8ee1565234be59426628471a2b267bbb400d865a94322561f` |
| Q complete task-export retention | `4f4cb190abfd64436c1dd97d81f31fb6f54452d94a7ae41377ee96fc1a9d742b` |
| Complete503 P/Q page comparison | `ed03a0d222f6d8b187ad3a8ad9cc857b683430b60a2030cb4b4f73a9c2345156` |
| Q additional P02 header source review | `35b3637b70f5d001e7aca43ee9f7ae9bf56cf528a2c37b55a528395c4b1474ad` |
| Second source/question/oracle seal | `c765c5034a96625e6324f32646e69e2b2f18a477af20b0392f56fc1457d4ff8b` |
| Candidate freeze before second opening | `21c0321acf4e423bd52f4fa41e4349d5465171d7c4ef5f3da87e61a73679afe0` |
| Second-set baseline native first adjudication | `e791b79fd464e8cc1f8153ff42ab546afa9fe1c9b00da7a92f5b2306d890c9e6` |
| Second-set baseline OCR first adjudication | `3f06803dafed2af4d80153fc7cf62871b1898a886da3725d51f0abdbc2a6a7c9` |
| Second-set candidate native first adjudication | `2d8759ffa0de1a3ea0cd2016cbda93048e13fdd6ef1c87af483f6de03b918ca0` |
| Second-set review-order deviation | `92d8cdc1975df60e00efae4dce1adab7733c6183ad80acbab81ac68f8a195d7e` |
| Second-set V03 source-context qualification | `dc496e7c385f02096222c607f8e721e619b7a93bef8d59d75208459c4a116484` |
| Second-set baseline native supplemental references | `ba79c1a62fb50d9747bd6d985208769ad2596776ae71dc50e943f001a39f14c6` |
| Second-set candidate native supplemental reference | `047d0b6448f67992cc623da60bc1f178a154c3ea8c4f65189fb197d3c124fe97` |
| Second-set baseline native export audit | `6d64ebba14547b5aeb52aa181a3d396f308b013b166d1cae113707712fa6b93e` |
| Second-set baseline OCR export audit | `217679860760784723f5066139ab583ce91eea3fa260b787d46a2ec36b4a1f07` |
| Second-set candidate native export audit | `3756e9b7d235b3de8cee3bd300951da0a8bdcf0b2f6e0be768c5850895bbc696` |
| Second-set candidate OCR first adjudication | `d2cb4cd4c368a431cf06199019a7743e0ada91e88d7b2d6dd85bd28ae9668002` |
| Second-set complete paired first summary | `7d3bb5d625218e50778218072c0653f35c08b8ade4fcdb94135ddab9cbe8ed01` |
| Second-set authorized concurrent candidate OCR review | `274e34a9bbcf54addbb1f8c0e58aa442b7402b8c750b9ad1d180ce3b51b93905` |
| Second-set baseline OCR supplemental reference | `d7568ed3e9351b39ff9a8774a3a73ce4886068e40534cf835f2f88e6341d6de4` |
| Second-set candidate OCR supplemental reference | `6135412e36f221bdc00fabfcce77233e7055bacbdca784a28a535129a9060ed3` |
| Second-set candidate OCR export audit | `57d3e08d852655d14704d015c01f11a1b53c31b684f2243003b4eef6bc2e312c` |
| Second-set bounded repair and AI-boundary decision | `81d0450b122274e64b8ece69973f122f3863cebb48a1a1f59abc2aba99dd5bad` |
| Second-set promotion to regression after all first seals | `ed0fa04bebf9df3e4d1d825110ecd3db1808251ed0ec2ee8b5d92938f77c9750` |
