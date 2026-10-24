# v0.7.3 scientific acceptance and publication

Status: **NOT ACCEPTED / NOT RELEASED**. The 0.7 series has not met its
closure conditions. No routine 0.7.4 feature release is planned. The fixed
criteria remain in [V073_FINAL_PLAN.md](V073_FINAL_PLAN.md).

This record distinguishes historical first results, exposed regressions and
unopened validation. The implementing assistant checks source pages and code;
this is **not independent third-party review or measured human performance**.
The previous incremental record is preserved verbatim in
[V073_DEVELOPMENT_RECORD.md](V073_DEVELOPMENT_RECORD.md). Its intermediate
versions, incomplete runs and failures are historical checkpoints, not current
release certification. Original v0.7.2 records are unchanged.

## Current gates

| Gate | Required | Current status |
| --- | --- | --- |
| New sealed primary OCR sample | At least 54/60; target 57/60; paired error reduction rule | Second set sealed, not yet parsed; pending |
| Unflagged critical errors | Zero local omissions/errors without adequate notice | Pending second set; exposed native regression has zero |
| Original 75 and preservation | Full current scoring; original 52 target contents and 64 historical regressions retained | Latest full 54-document extraction running |
| Twenty research tasks | At most 31 independent checks, median at most 2; completion/coverage/conflicts retained | Current extraction and task review pending |
| Retrieval | Old Top1 >=12/32, Top5 >=20/32; SI >=3/4; new Top5 >=18/20 | Current corpus execution pending; queries unchanged |
| Source/export/compatibility | Correct original pages, alternate readings and true conflicts retained | Final complete corpus check pending |
| Engineering and actual use | Complete CI and clean installation on final commit | Current development CI passes; final commit/use checks pending |
| Publication | Verified main, tag, GitHub Release, PyPI and installed distribution | Not published |

A warning can disclose a failure; it cannot make the answer correct. A correct
alternative, manual reconstruction of an experiment, abstention or missing
context fails complete default-primary correctness. Global PARTIAL is not a
local warning. Layout groups remain observed layout evidence, not certified
scientific data.

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

## Current exposed regression

Commit `ba7f735692838c98fc25e9aaa3ee9271141a4fd2` completed a fresh native
extraction of all **16 documents / 671 pages**, with zero runtime errors.
All 43 question-bearing pages have exactly the same primary/alternate block
text and geometry, table relationships and normalized local warnings as the
previously source-adjudicated native structural replay. Every cited text and
position was also checked before transporting those source judgments. This is
fresh extraction with native backend 1.19.5 and parser 3.10.9, not captured-layout
replay and not independent blind validation.

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

The OCR regression on this commit was stopped after its first complete document
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
Fresh complete regression is running on `0f61979`. Its first reviewed complete
OCR documents are H01 **7/8** and H08 **4/4**, both with zero unflagged errors.
H01 recovers the microampere unit but still misreads I/l in a catalyst label;
that answer fails despite correct numeric rows and a local warning. H08 now
retains the paired standard/scaled results, footnotes and 10⁻⁴ A axis. These
12 questions are not a complete 60-question score. Candidate counts, omissions,
task checks and additional runtime still require full measurement.

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

## Unopened validation and final release work

The second seal retains the same 12-main/four-SI, 60-question distribution and
all fixed gates, with 673 pages. It excludes prior development and the complete
first set. One access-blocked article was replaced by its recorded reserve
before parsing; the original sampling frame and reason remain. As of this
record, no AN parsing of this set has occurred. The candidate must first finish
historical preservation, task/retrieval/export checks and exposed regression.

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
remain failed historical records, not rewritten or waived. The last complete
ten-check local RC passed on `ec615bd`; the last completed 24-check clean
installed-use run passed on `f4b1ff0`. Neither certifies the final commit.

Final work still includes complete scientific adjudication, exact-final-commit
CI and clean use, PR merge, verified main, v0.7.3 tag, GitHub Release, existing
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
| Fresh ba7f735 native adjudication | `e5992bff581004989278edbdcb2ab04b3a42b1f5fa9441394d0a99fa5b2f6a02` |
| Second unopened seal | `c765c5034a96625e6324f32646e69e2b2f18a477af20b0392f56fc1457d4ff8b` |
