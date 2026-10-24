# v0.7.3 acceptance record

Status: **NOT ACCEPTED / NOT RELEASED**. The 0.7 series has not yet met its
closure conditions. Protocol: [V073_FINAL_PLAN.md](V073_FINAL_PLAN.md).

Baseline: v0.7.2, commit `643094b943c7ab9c7aa7de4ef5897d688617ae6f`.
Historical first scores remain historical. The exposed development results
below are complete; the first native-only holdout result is recorded below.
The locked primary OCR candidate run and publication remain pending; its
completed baseline OCR result is recorded below.
No independent third-party review or human-time improvement is claimed.

The task-local evidence ledger records baseline hashes, complete historical
adjudication, frozen tasks/queries/holdout, candidate execution identity, paired
first scores, any exposed regressions, local error coverage, source checks,
coverage and elapsed times. Restricted PDFs and authentication data are not
public deliverables.

## Baseline source audit, before product changes

The latest exposed development changes also address numeric-first product
labels with staggered result rows, multiple literal footnote markers and an
intervening-product guard. An isolated native ligature can rejoin only a unique
pair of adjacent letters on the same painted baseline; its reading and bounds
are preserved, including unresolved private-use glyphs. Numeric bar categories
require an actual axis, two explicitly printed values per category and distinct
legend colours that continue through the painted bars. Bar heights never supply
values. The associated axis-label fragments remain labelled as layout evidence.
Vertical crop replacement now refuses to discard observed label, sign or unit
characters. The content suite passes 614 tests (three opt-in skips); full fresh
scientific regression and final release verification remain required.

Hosted run `40050560113` on `f4b1ff0` passed all eight jobs. Its unpublished
wheel passed 24 actual-use checks in a fresh environment; wheel/sdist source
bytes matched that commit and contained only the four authored PDF fixtures.
This is a development checkpoint, not publication verification.

The complete exposed rerun then found another release blocker: an experiment
grid could stop before a footnoted index, or put its first marked experiment
in the header. A numeric product-column header could also be ignored. The
correction retains literal index suffixes and numeric headers, requires the
same sequential rows and complete aligned columns, and stops at a spanning
footnote line. A tentative guard against malformed indexes initially rejected
two valid tables because wrapped footnotes started with numbers; that behavior
was rejected and the observed spanning boundary retained instead. Concentration
text, broken sequences and missing experiment cells remain counterexamples.

The implementing assistant checked the distinct SI and two-column source
layouts. Replay of 764 exposed captured pages changes seven pages, including
the original article, its SI and a separate historical article; the other
candidate grids are unchanged. An earlier fresh native probe recovered all
ten article experiments, but it predates the complete boundary correction.
These are diagnostics, not a completed scientific regression or new blind
score. The parser execution identity is 3.10.6; full candidate verification
and the unopened second holdout remain pending.

Hosted run `40044049727` on `0b09ebe` did **not** pass the full gate: seven jobs
passed, but Windows browser attempt 1 failed an initial bounded page read.
Attempt 2 passed that case but failed navigation/startup/CDP timeouts in three
other browser cases. Eight local cold-browser probes returned the expected
access state. These observations do not establish the hosted failures' cause
or waive them. The original logs remain in the evidence ledger; the final
commit still requires every hosted job to succeed.

The next hosted run, `40047629818` on `5815223`, passed all eight jobs. Its
local deterministic suite passed 2,085 tests (115 opt-in/platform skips), real
browser tests 119 and ordinary-browser tests two. The full local RC report
remains failed because that invocation omitted the installed OCR executables
from `PATH`; the unchanged real OCR test passed after setting their paths.
These are recorded separately, not a rewritten successful RC report.

A complete fresh two-document exposed regression on `5815223` passed **5/8**
frozen questions. The product/footnote group and indexed experiment rows were
recovered, but the L7 result group, unreadable membrane-name glyph and bar-chart
primary fusion still failed. In particular, correct source-image bar relations
were being demoted by overlapping standalone OCR labels. A successful isolated
image probe was therefore not credited as a default complete answer.

The subsequent development correction distinguishes a relationship's evidence
extent from the extent of its source labels. Local OCR disagreements still
compare with those source readings and remain exported; relationships stay
uncertain layout evidence. The exposed page now keeps all three printed bar
groups as primary and the erroneous `435` as a local alternative to `43.5`.
Percentage-result grouping distinguishes close rows within each repeated
column and recognizes AN's ink-colour display prefix without deleting it.
Observed plot-frame strokes prevent false internal panel cuts; actual wide
gutters and printed parenthesized panel letters are supported. The demonstrated
false `803 cm`/`800 cm` scale associations disappear without discarding the
readings or inferring their missing reciprocal-unit signs.

Local OCR may also fill an explicit missing native letter glyph when a unique
positioned word preserves its surrounding letters, line context and all
numbers. It does not copy the OCR's other spelling changes. Original native
text, full OCR and a local substitution record survive. Numeric gaps, case
conflicts, repeated matches, missing glyph positions and low confidence abstain.
The exposed source replay recovers the membrane name while preserving the
native catalyst and unit that OCR misread. This replay is not fresh extraction
or a new first result. The content suite passes **636** tests (three opt-in
skips); the complete deterministic suite passes 2,107 (115 opt-in/platform
skips). Fresh complete regression remains required.

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
not complete-answer scores. The completed candidate comparison is below.

## Source-first holdout seal

On 2026-10-23 at 15:19:42 UTC, before any v0.7.3 product-code change or AN
parsing of these sources, 60 questions and source oracles were hash-locked:
16 prose, 20 table, 12 figure and 12 SI questions. The sample contains 12 main
articles (9 English, 3 Chinese) and 4 associated SI PDFs, **671 pages** retained
in full. Original pages supporting every answer were rendered and visually
inspected by the implementing assistant. This is not external independent
review or double-blind testing. The first native-only score is now recorded
below; the primary OCR pair continues with the frozen candidate and settings.

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

Pending release gates: new paired holdout; final scientific-use review;
final-commit CI and clean-install use; merged main verification; GitHub/PyPI
publication and published-package verification.

## First holdout result: native-only configuration

Both frozen native-only runs completed all 16 PDFs / 671 pages with zero
runtime errors. Manual source-page adjudication covers all 60 frozen questions;
the denominator and required facts are unchanged. These are first results,
not repaired regressions. The implementing assistant performed the review.

| Native-only measure | v0.7.2 | Frozen v0.7.3 candidate |
| --- | ---: | ---: |
| Complete default primary reading | 33/60 (55%) | 33/60 (55%) |
| Prose | 15/16 | 15/16 |
| Table | 11/20 | 11/20 |
| Figure | 2/12 | 2/12 |
| SI | 5/12 | 5/12 |
| Questions containing an unflagged critical error | 16 | 15 |

The one disclosure improvement is a localized membrane-name glyph warning;
the primary name remains wrong and the question still fails. These results
do not establish a correctness improvement. Native-only parsing leaves
important image text, table relationships and shared conditions unresolved.
Some embedded-font recovery also inserts false equals signs into quantities
and units; a correct original reading retained in a diagnostic does not rescue
the default primary reading. Original main/SI and table/prose conflicts remain
separate rather than being reconciled by the parser.

| Source identity | v0.7.2 complete | v0.7.3 complete |
| --- | ---: | ---: |
| H01 / H01-SI | 6/8; 1/3 | 6/8; 1/3 |
| H02 | 3/3 | 3/3 |
| H03R | 1/3 | 1/3 |
| H04R | 1/5 | 1/5 |
| H05 / H05-SI | 2/3; 2/3 | 2/3; 2/3 |
| H06 / H06-SI | 3/4; 2/3 | 3/4; 2/3 |
| H07 | 1/4 | 1/4 |
| H08 / H08-SI | 1/4; 0/3 | 1/4; 0/3 |
| H09 | 3/3 | 3/3 |
| H10 | 1/3 | 1/3 |
| H11 | 3/4 | 3/4 |
| H12 | 3/4 | 3/4 |

The local adjudication contains every question, failure category, inspected
primary block, source hash, artifact hash, page and bounding box. The H08
table caption continuation is explicitly cited on its actual page 8; the
frozen target table stays on page 6. The source-discrepancy question includes
both the SI page 11 and related main-article page 3. No source page is silently
relocated to make an answer appear complete.

- `holdout-native-first-adjudication.json`:
  `2c20d97444772554416880a7c111f6a284676ce0a37a6043ad944d32645aeb36`
- Frozen candidate source commit:
  `9a6d27d5f874bb3a00bbb4aab26f826d4c97ab96`
- `protocol/candidate-freeze.json`:
  `bee5b85c1fb4c078c4088966ddb4e35204e6a1d8c4322b195cd296e3c916a875`

The prospectively chosen primary acceptance configuration includes the locked
optional OCR. That paired run is still in progress, unchanged. Its result must
be reported separately. This native-only score cannot be substituted for it,
nor can engineering success establish scientific acceptance.

After recording the complete first native score, this set exposed a reproducible
font-identity collision. It is now used for repair, so **all 60 questions have
become regression data for subsequent candidates**. The first native score and
the unchanged original OCR executions remain intact; they cannot certify the
repaired implementation. New independent first results require a new source-first
seal under the same protocol. The promotion record has SHA-256
`bf1c032e42bcfc08f2325f6c9aa3456b693909ec5a9a265e48251de319936fd8`.

The concrete defect is that a simple font and a CID font can share a font name
while using character code 32 for different glyphs. Recovery keyed by that name
mistakenly substituted the CID font's equals sign for ordinary spaces in the
other resource, corrupting quantities such as value/unit pairs. Native recovery
now keys glyph, unit and geometry repairs by the actual PDF font resource in
the temporary extraction copy. Same-named fonts, reversed resource order and
nested Form resources are covered by self-authored counterexamples; original
page bytes remain unchanged. Native backend identity is 1.18.0 and parser
identity is 3.9.2, preventing reuse of stale readings.

The focused suite passes 108 tests. Five exposed real-page probes spanning two
SI layouts and one main-article table remove the false space-to-equals repairs
while retaining the source's actual equals signs. These are local regressions,
not a new scientific accuracy score or a completed full-corpus verification.
Hosted run `40031072131` subsequently passed all eight jobs on font-repair
commit `148e1bc26978666932dc6668c261838a0b2c6d76`, including Windows/Chromium,
optional OCR, browser extras and clean-wheel installation. Scientific
revalidation of that later implementation remains due.

The opened first set also reveals text converted to painted vector outlines:
there is neither a native character map nor an embedded raster image, so the
existing image-only OCR trigger can skip whole experimental regions. This is
reproduced in two main-article layouts and an SI condition diagram. Native
extraction now records local runs of aligned filled glyph-sized paths without
overlapping native text. These regions trigger the existing optional OCR and
retain bounded `VECTOR_TEXT_UNVERIFIED` notices; no text is inferred from the
paths and no new recognition engine is added. Straight rules and ordinary
stroked bonds are excluded. Widely separated OCR word groups retain their own
positions instead of becoming a single experimental reading.

The focused suite passes 51 tests, including nested/clipped Forms, horizontal
and vertical runs, readable-native counterexamples and separated versus
continuous numeric phrases. Five source-page probes locate the previously
skipped vector runs; a text-only Methods page creates no such region. Two OCR
probes of the same exposed page recover omitted table values and separate wide
columns, but still misread some catalyst labels and fail to recover a current
unit. **These are incomplete local repairs, not passing scientific answers.**
Those failures remain regression targets. At that repair, identities were native1.19.0,
adaptive1.10.0, Tesseract adapter1.8.0 and parser3.9.3. Full-corpus regressions,
burden/retrieval/export checks and a new sealed first evaluation remain due.

The second source frame retains the original 12-main/4-SI and 60-question
distribution and all gates. It has 673 pages. No PDF hash matches the prior
exposure inventory or the first opened set. One access-blocked Science article
was replaced by the prospectively recorded Chemical Science reserve before AN
parsing. The second seal was completed at **2026-10-23 22:58:03 UTC**, before
any AN execution on these files. Its 60 source-reviewed questions retain the
16 prose / 20 table / 12 figure / 12 SI distribution and unchanged scoring gates.
Three table-category questions concern borderless aligned experiment lists
inside a figure; that subtype will also be reported separately. Main first-page
DOIs, titles/authors and publisher-linked SI identities were checked. No default AN
output for these new materials has been opened. This remains an implementing
assistant's source-first evaluation, not external or double-blind review.

- `protocol/holdout-v2.json`: SHA-256
  `c765c5034a96625e6324f32646e69e2b2f18a477af20b0392f56fc1457d4ff8b`.
- Candidate/runtime freeze and execution of this second set remain pending.

Hosted run `40033857056` passed all eight jobs on vector-repair commit
`6ce904718018488a6439b3152831cdd09694ce2d`. This is development CI, not acceptance.

Further exposed-source checks found a captionless table inside a figure. Its
three painted rules and repeated numeric columns are now used to retain wrapped
conditions in their observed rows, preventing paragraph merging across distinct
experiments. No caption is invented. Repeated, explicitly keyed measurements
under uniquely aligned figure labels can also retain the label, value and signed
error together; all displaced fragments remain available as alternatives.
Competing labels, column crossings, ambiguous row proximity and incomplete
repeated keys abstain from grouping. These are observed layout associations.

A remaining missing glyph in the same source was traced to PDF WinAnsi's unused
code aliases, which differ from an ordinary Windows text codec. The embedded
program contains the actual bullet glyph. Recovery now follows the base encoding
while honoring explicit Differences and ToUnicode; blank/missing glyph programs
do not authorize the repair. This follows [ISO 32000-1, Annex D, Latin character
set note 3](https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/pdfstandards/pdf/PDF32000_2008.pdf),
without chemical vocabulary or sample-value replacements.

The focused suite passes 106 tests; the content suite passes 536 with three
existing opt-in skips. Exposed-page probes restore one five-experiment table,
three separate mass/error label groups, and the missing bullet; three other
source layouts create no new embedded grid or keyed group. These are regressions,
not new first scores. Initial fixture failures (a missing required title and a
counterexample that did not actually cross the neighboring column) are retained
in the local test logs. This stage used parser identity **3.10.0**, native backend
**1.19.1**; complete scientific regressions and release verification remain due.

Another exposed table places a reaction diagram between its caption and an
explicit Entry header. The parser now recognizes a complete, consecutively
numbered experiment grid under aligned headers, preserves wrapped header text,
and keeps the diagram as context rather than treating its fragments as data
cells. Missing columns, discontinuous indices and intervening captions abstain.
Literal `nd` remains `nd`; no numerical value is inferred. Repeated percentage
result lines under uniquely aligned source labels retain their separate lines
and footnote markers. An ambiguous upper result cannot be bypassed by assigning
a lower result to the label. Original fragments remain available.

The content suite passes **542 tests**, with three existing opt-in skips.
A fresh native probe restores the exposed table's seven experiment rows; a
structural replay of completed, already exposed OCR layouts also restores nine
label/result groups, including the separate starred results. Replay is not fresh
extraction or a new score. The first replay harness failed backend validation
because JSON arrays were not reconstructed as tuples; that output is preserved.
The corrected harness has no parse errors. The initial competing-result test
failure is also retained. Unresolved native chemical-label case differences
remain failures; grid recovery alone does not establish complete correctness.
Current parser identity is **3.10.1**.

Hosted run `40038639189` on `e86d8a9` passed seven of eight jobs. Its Windows
real-browser HTTP 429/session-pause test failed. The unchanged test passed a
local real-browser rerun; adding response/request diagnostics to its existing
assertion did not relax it or change the product. Run `40040088176` on
`72f8d635f25c5fb0ecb4c965505623d93e8dceeb` subsequently passed all eight jobs.
The earlier failure is retained and its cause is not established. Neither run
certifies later source changes or constitutes final release CI.

The exposed figure-axis audit identified raised rotated numerals separated from
their base label. Native extraction now uses the actual text origin (including
PDF text rise), relative glyph size, displacement and unique adjacency to retain
a short raised number as a superscript. Competing bases, overlapping candidates,
equal-sized annotations and lower annotations do not acquire an exponent role.
Both rotation directions and three scales are covered. Three source axis labels
recover their signed exponents; other inspected native labels stay intact.

Another source font maps encoded capitals to lowercase Unicode despite painting
named uppercase glyphs. A case-only repair now requires an explicit uppercase
encoding and two present, different, painted uppercase/lowercase outlines in
the same embedded Type1 font. Custom encoding overrides, blank or identical
outlines, and non-case mappings are counterexamples. Original mappings and local
correction records remain. Source checks restore the table's chemical-label case
without chemistry lookup. Neither repair changes the original PDF.

The focused combined suite passes 41 tests, and the content suite passes **570**
with three existing opt-in skips. Initial tests exposed the missing text-rise
origin and an incorrect test expectation about line-versus-character diagnostic
fields; their logs are preserved. Native backend identity is now **1.19.2**.
These source-page probes still require complete fresh scientific regression.

The exposed multi-level table header also split nested subscripts and charges
into extra rows/columns. Short numeric/sign fragments now rejoin only a unique,
nearby, smaller-font script base; ordering recurses within nested script groups.
Competing bases, independent full-size values, connected measurements and distant
digits remain separate. The source table changes from a fragmented 9-by-7 grid
to its observed 6-by-5 grid in a fresh complete native document parse, with no
runtime error. A second source layout recovers formula subscripts in two reagent
labels; its previously detached comma is still retained separately. Three other
inspected source pages have identical line texts. This does not establish full
reaction-condition correspondence or count as a new holdout result.

Native backend identity is **1.19.3**. The content suite passed **573 tests** with
three opt-in skips before adding a further painted-PDF regression; all four
nested-script tests then passed. The first ordering failure and intermediate
source probe remain in the local evidence. No original glyph or PDF is replaced.

An additional exposed figure audit found that one PDF stores a complete figure
as 1,469 touching one-pixel strips, and another as six touching strips. The
previous per-resource minimum size and positive-gap grouping either omitted the
figure region or associated only its bottom strip. Contiguous, equal-width,
non-overlapping strips now form an observed region while every original
resource remains in `source_objects`. Optional image OCR pastes equally sampled
strips at native pixel resolution; it does not resize them, fill gaps or infer
panel contents. Gaps, overlaps, displaced columns, inconsistent sampling and
the pixel budget all constrain this operation.

The content suite passes **582 tests**, with three opt-in skips. Structural
replay covers both columns on two exposed source pages, with all original
resources retained. A fresh OCR page probe recovers separate panel/scale
relationships previously fragmented across resources, but the difficult
microscopy question still lacks complete lattice and panel relationships and
is not reported as passing. Full figure coverage by a local warning is a
diagnostic correction, not a content correction or a reduction in independent
review decisions. Parser / Tesseract / image-OCR identities are now **3.10.2 /
1.8.1 / 1.5.4**. A control-page audit also found an existing prose-as-caption
association problem; it remains to be corrected and checked before freezing.

That control-page problem is now corrected: recognition removes only spacing
between adjacent Chinese characters in its decision view, so a prose verb such
as `给 出 了` cannot create a new figure. A multi-sentence `为…其中，` prose
reference is also retained as prose. Short descriptive captions remain valid.
A fresh complete native parse retains the two original prose passages and
associates only the actual figure caption with its image, without a runtime
error. The original first result is unchanged.

Short axis titles previously selected only central numeric ticks. Optional image
OCR can now extend their association to an observed, thin horizontal plot border
immediately above the same tick row. It uses existing printed readings, never
interpolation, curve values or a guessed numeric sequence. Blank/filled regions,
competing titles and duplicate numeric sequences do not authorize extension.
Group anchors include the actual tick locations as well as the title. Two
exposed source images recover their outer time ticks; the first still retains
all four negative-current ticks. These are development source-image probes,
not completed scientific-question regrades or first holdout results.

The combined focused checks pass 50 axis/image tests and 106 caption/parser
tests. The complete content suite passes **596 tests**, with three opt-in skips.
The initial synthetic axis fixture accidentally supplied only two seed ticks;
its failure is retained and the fixture now supplies the required three.
Parser and image-OCR identities are **3.10.3** and **1.5.5**. Hosted run
`40042446564` on `e6441d9` passed six jobs before a subsequent branch update
cancelled the two browser jobs; it is not a complete or final CI pass.

## First holdout result: completed baseline OCR configuration

The locked v0.7.2 OCR run completed all 16 PDFs / 671 pages without runtime
errors. Its full 60-question manual adjudication is **34/60 (56.7%)**: prose
15/16, tables 12/20, figures 2/12 and SI 5/12. Fifteen questions contain a
critical error without an adequate local notice. This is the original frozen
baseline result, not a repaired rerun; the frozen v0.7.3 OCR run continues.

| Source identity | v0.7.2 OCR complete |
| --- | ---: |
| H01 / H01-SI | 6/8; 1/3 |
| H02 | 3/3 |
| H03R | 1/3 |
| H04R | 2/5 |
| H05 / H05-SI | 2/3; 2/3 |
| H06 / H06-SI | 3/4; 2/3 |
| H07 | 1/4 |
| H08 / H08-SI | 1/4; 0/3 |
| H09 | 3/3 |
| H10 | 1/3 |
| H11 | 3/4 |
| H12 | 3/4 |

OCR recovers additional digits, scales and diagram labels, but several complete
answers still fail because experiment, panel, unit or axis-endpoint relationships
are missing. False native glyph mappings also remain primary errors. Correct
fragments, diagnostic originals or retained alternatives do not rescue a failed
default answer. Original source conflicts remain separately represented.

Immutable local record `holdout-v072-ocr-first-adjudication.json`, SHA-256:
`f560cd4c0a3bdf45cff6e9e818606c0b68f981d1f3d84651684321445816b7dc`.
It includes all judgments, source/parsed hashes, actual primary blocks and
anchors, error categories and source-specific counts. Exact whole-page reuse of
an already reviewed native judgment is identified; changed evidence received
manual review. Neither this baseline nor engineering CI establishes acceptance
of the current implementation.

## Completed exposed development acceptance and candidate freeze

The fresh `development-h` run completed 54 exposed documents / 503 pages, with
zero parse errors, missing block anchors or optional-backend failures. It used
two workers and the previously recorded historical configurations; its 3,395.54 s
extraction wall time is not an isolated paired performance benchmark. Parsing
used `d0d80acedd5adebac24f7348e242d159ead54170`. Export and local notice
presentation used `9a6d27d5f874bb3a00bbb4aab26f826d4c97ab96`; all parsing,
backend, table and retrieval implementation bytes are identical between those
snapshots. That distinction is preserved in the local execution records.

| Same exposed materials and rubric | v0.7.2 audit | v0.7.3 candidate |
| --- | ---: | ---: |
| Original 75, strict complete primary reading | 69/75 | 72/75 |
| Original 75, historical content rubric | 72/75 | 73/75 |
| Original confirmed target content retained | 52/52 | 52/52 |
| Strict failures without adequate local disclosure | 4 | 0 |
| H / I / J / K regression | 16/16; 8/8; 12/12; 12/12 | Same |
| Latest exposed 16-question regression | 16/16 | 16/16 |
| Original literal article Top1 / Top5 | 12/32; 19/32 | 14/32; 24/32 |
| Original SI Top5 | 3/4 | 4/4 |
| New frozen 20 queries Top1 / Top5 | 13/20; 16/20 | 14/20; 19/20 |
| Twenty tasks, complete default answers | 16/20 | 18/20 |
| Twenty tasks, completion after source checks | 20/20 | 20/20 |
| Independent source judgments / median per task | 42 / 2 | 21 / 0.5 |
| Observed assistant review wall time | 245 s | 322 s |

These are exposed regressions, not new blind results. Historical first results
remain 52/75; H 5/16, I 4/8, J 9/12, K 8/12; and latest 14/16. The original
52-target preservation is a content test: under the stricter relation rubric,
51/52 are currently complete, with the pre-existing 18-A2 shared-label gap
remaining. It is not legitimate to call that strict 52/52.

The three remaining original-question failures are 12-A3 (four panel identities
still require source interpretation), 18-A2 (two shared R/S labels lack supported
spans), and 28-A2 (unusable source temperature glyph). They remain failures;
local disclosure does not repair them. The original separate excluded glyph
item is still outside the denominator. Source contradictions remain intact.

The task reduction is **50%**, with 25 old independent issues eliminated and
four new OCR differences counted. Those new differences concern one lost
decimal point, one electrode-name bracket, and two S/5 configuration readings.
One source page containing three disagreements still counts three judgments.
Display folding receives zero reduction credit. The timed session included
tool latency and context handling; no per-task times were measured. Its longer
wall time does not establish a speedup. All 20 reviewed exports are byte-identical
to the completed-run exports, and all requested facts, source conflicts and
source gaps remain available.

The literal old Top5 misses are 7-A4, 21-A1, 21-A3, 21-A4, 24-A3, 24-A4, 30-A3
and 38-A3. New Q06 remains a miss: its unchanged literal `Ru2` does not match
the printed `Ru-2` form. These failures were not removed or rewritten. A hit
does not certify that the full scientific answer is correct.

All 37 original files / 287 pages remain. Candidate block count is 17,763 versus
17,023. Native paragraphs sometimes split around new OCR; some assembled graph
axes become incomplete while their raw readings remain; a few unresolved
ligatures and uncertain header-rule fragments remain. The source audit records
these limitations explicitly. In particular, an exposed `500 nm` scale is still
wrong as primary `500 mm`, with the local unit conflict and alternative retained.
This is improved disclosure, not an accuracy repair. No whole-library reduction
in manual burden or universal figure completeness is claimed.

The original whole-library exported burden has now been independently
reproduced from the preserved files using each checkpoint's own exporter
(implementation self-audit, not a third party). The 37-document / 287-page
v0.7.2 delivery yields **1,985** uncertain article review locations and **12,475**
exported uncertain article blocks, exactly matching its original record. The
completed development-H extraction with its frozen `9a6d27d` exporter yields
**1,990** locations and **13,125** blocks; the document median rises from
**38.5 to 42**. These are exported display/review counts, distinct from raw
parser uncertainty and from the 20 tasks' independently counted decisions.

The largest H location counts are original documents 35 (238), 27 (187), and
39 (159). Document 36 drops from 129 to 80 locations, while document 35 rises
from 220 to 238. Such grouping changes are not automatically resolved scientific
issues and receive no task-reduction credit. The latest full extraction must
repeat these measurements; H does not demonstrate a whole-library burden gain.

The candidate freeze `protocol/candidate-freeze.json` has SHA-256
`bee5b85c1fb4c078c4088966ddb4e35204e6a1d8c4322b195cd296e3c916a875`.
It locks candidate `9a6d27d`, the exact v0.7.2 source, and runtime/models before
the four sequential, one-worker native/OCR runs of all 671 holdout pages.
No held-out scientific result is available at this checkpoint.

Local SHA-256 evidence:

- Complete extraction audit: `7247a6c3c04f1afef5db455eb5162166c7e9d444dfaccd6fff11e0213669395c`
- Current 75 adjudication: `c56d36ac74f95dbfc85c8d22d8943d40be3db907759384d0726c964907271f05`
- Historical 64-question regression: `af2e3a724c27c1210e0955b6aa44d65a5916b0b998620fc6f9ee19a50cc16181`
- Source coverage adjudication: `fad59bae1fd16eade1c466a747a6430c186f5975c23109fcee3500386d66ceaa`
- Actual 20-task review: `96a242da27ab4da950f82178b4ea82c5ae8b720401252213ae421ea9dabae9bd`

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

A further original-page check found outlined scheme labels outside raster image
objects. Restricting page-context OCR to image boxes alone would also lose valid
content. The selection now retains readings in native-text gaps, using native
geometry, as well as painted images. The actual source labels and negative case
(clear native prose) were checked before restarting the full extraction. The
intermediate `development-c` run was stopped and preserved as incomplete, not
counted as a successful regression. An additional existing figure-unit error
(a printed nm scale read as mm) remains in the boundary ledger with its uncertain
source-linked figure reading; it is not claimed as corrected or silently assigned
the unit used by neighbouring panels.

Local development checks after this coverage repair passed 1,940 deterministic
tests (115 opt-in/platform skips), 119 real browser tests, two normal-browser
tests and one real OCR test. The later search presentation change separately
passed 97 focused tests (one opt-in skip); it adds the existing export review
locations after ranking and prints primary/alternative status, matched observed
rows, local gaps and differences. These are development checks, not final-head
release verification or measured review-burden savings.

The complete-text audit also found that a high-confidence short OCR crop could
replace a longer native line containing an unresolved private glyph. Recovery
now requires coverage of the native line, preservation of visible text (including
negation and unit case), and compatible surviving numbers or an explicit
missing-glyph fit. Still-unreadable lines retain full-line OCR context; already
recovered glyphs keep the smaller local scope. Nine exposed page probes restored
the previously readable prose and retained the native originals. The content
suite passes 475 tests with three opt-in skips. Fresh final extraction is pending;
the older development-d extraction cannot establish this repair's acceptance.

The optional `qualify_v07_public_oa.py` check was also run unchanged. Its
`PARSED`-only status check failed for all three fixed public papers, while the
source hashes, required text, page counts, anchors, tables and figures passed.
An exact-code v0.7.2 paired native run reproduces all three `PARTIAL` statuses.
The before/after blocks (text, kind, region and uncertainty), anchors and tables
are identical, with no runtime errors. Existing reasons are unresolved glyphs,
unverified raster text and table-column collisions. This optional result remains
failed in the ledger; it is not relabelled green or weakened. The mandatory full
RC command in `CI_ARCHITECTURE.md` remains unchanged. Native partial coverage is
reported as a usage boundary, separately from the locked optional-OCR scientific
acceptance configuration.

The next structural audit compared table-row relationships, not only retained
characters. It found an additional blocker in the exposed review table: newly
retained vector-diagram OCR interrupted grid detection, leaving the numeric
columns outside the table object. The table detector now continues past short
OCR fragments only when they lie inside the same empty column interval between
two aligned numeric experiments. Those fragments remain source blocks; neither
their text nor experimental conditions are copied into another row. Native
labels, standalone numbers, changed columns, intervening captions and prose
are counterexamples. The parser execution version is now 3.9.1. The content
suite passes 487 tests with three opt-in skips. Complete extraction and a
separate structural replay are being checked before candidate freeze; replay
is explicitly distinguished from fresh OCR and from unseen evaluation.

The same source audit also reproduced a pre-existing image-fusion error outside
the frozen 75 questions: a corroborated numeric margin crop promoted `0.3` over
the fuller source reading `>0.3`. The image adapter now retains a fuller
non-numeric reading as primary when a crop merely repeats its digits; the crop
remains an anchored alternative. This also protects units, percent signs and
footnote markers without guessing their meaning. Real source probes retain the
inequality and preserve previously recovered signed chart ticks. The adapter
identity changes to 1.5.2. The superseded development-e extraction is preserved
as incomplete after 22 documents; it is not reported as a completed regression.
The next full extraction uses the updated identities throughout.

A further source check investigated the existing `500 nm` / `500 mm` scale
error. The full image and padded crops disagree; changing crop padding changes
the reading. The parser therefore does not infer the unit from neighbouring
panels or promote a less certain unit replacement. Two agreeing resolutions of
a local crop can now retain a same-value, different-unit scale alternative and
an `IMAGE_SCALE_UNIT_CONFLICT` warning at the actual label. The stricter primary
replacement criteria are unchanged. This is improved local error disclosure,
**not a repaired primary answer**. Different numbers, inconsistent/weak crops
and agreeing units do not establish such a conflict. Four real page probes keep
all primary readings unchanged and add the demonstrated conflict only; the other
three pages add no scale-unit alternatives. The image adapter is 1.5.3. The
content suite passes 499 tests (three opt-in skips); the deterministic suite
passes 1,970 tests (115 opt-in/platform skips). A complete extraction with this
identity is still required before opening the sealed holdout.

The unpublished 0.7.3 development wheel also completed 24 installed-package
use checks in a fresh Windows/Python 3.14 environment: public DOI acquisition
and parsing, declared local article/SI import, a real cooperative interruption
and durable resume, configuration invalidation, unchanged-artifact reuse,
role-filtered retrieval, three export formats, verified source resolution,
optional local OCR, old-artifact reading and the separate offline advisory
example. The imported module is inside the clean environment. Source conflict
evidence remains unchanged; the example abstains and refuses overwrite. This
is an engineering/use result, not scientific accuracy or final-commit release
verification. Its fresh dependencies include pypdf 6.21.2 and fonttools 4.67.0;
the separately locked paired scientific runtime has not changed.

An initial development harness expected a native-only SI hit for a word absent
from that artifact. The role filter correctly excluded the article containing
the word. That failed harness run is preserved; the positive use check now uses
the source-attested HPLC term. None of the frozen 32+4 or 20 scientific queries
was changed. Package inspection also found that the new Python advisory example
was omitted by the existing JSON-only example manifest; the source distribution
now includes it. Restricted papers and the user's unrelated debug files remain
outside the packages. Final release artifacts and installation checks are still
pending.

Task-oriented inspection then found a specific source of unnecessary table OCR:
the area of a wide OCR line included whitespace between native columns, so it
was treated as an uncovered source region even when its words were already
readable in native cells. Tesseract word positions now scope those readings.
Painted figure words and actual native-text gaps survive; separated gaps are
not joined across a native experiment. Recognition still uses the full page
context. Temporary word positions are cleared before native table splitting,
and partial readings remain uncertain because their confidence came from the
original OCR line. The adapter identity is 1.7.2.

Twelve exposed source-page probes retain all prior primary text; three table
layouts drop spurious competing readings. One page additionally exposes two
uncertain header/logo fragments, which are not claimed as scientific data.
A separate fresh full extraction of the affected review article retains its
63 observed cells, five numeric/label columns and complete split catalyst name
in the correct experiment row. The deterministic suite passes 1,977 tests with
115 opt-in/platform skips. The older development-f and development-g runs are
preserved as incomplete after 30 and 29 documents respectively. A new complete
run is required; these probes and test counts do not satisfy scientific gates.

The subsequent installed wheel of `d0d80ac` passed all 24 actual use checks,
and hosted run `40019005530` passed all eight jobs on that commit. Both are
development verification, not the final release gate. The full fresh extraction
continues with that frozen parsing implementation.

Export inspection reproduced a further localization defect: native glyph
warnings carry PDF display-point boxes, while review blocks use normalized
anchors. A warning about the unreadable temperature glyph existed in the
canonical artifact but was absent beside its paragraph. Evidence export now
retains selected page geometry and converts only known native warning boxes
for local presentation, preserving the original warning and box. Other
columns/pages and page-wide notices cannot acquire that local warning. The
source line is displayed with the notice. This changes neither parsed content
nor OCR execution; the two page-shape/counterexample tests and 1,979-test
deterministic run pass (115 opt-in/platform skips). Parsing extraction remains
valid; retrieval and exports must use and record this later code identity.
