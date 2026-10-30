# 溯光 (Aletheia Nexus) v0.8.0 integrated release acceptance

[中文主文档](V08_RELEASE_ACCEPTANCE.md) · English translation

This record covers v0.8.0; GitHub Releases and the PyPI project page establish release identity. Integration on 2026-10-30 began with research branch `59ce727` and workbench `b4d1002`; old branch results do not replace integrated verification.
Final local acceptance was frozen at `60a7756754e2be401542cd25c81a7d7f3f28ec3f` (H1); subsequent changes only update acceptance text and an old documentation link. The final section binds to this source; other records retain their historical snapshots without adding counts. GitHub Release and PyPI files establish public distributions and checksums.
For entry points and use, see the [research CLI/MCP guide](V08_ENTRYPOINTS.en.md), [workbench guide](WORKBENCH_USER_GUIDE.en.md), and [v0.8 release notes](RELEASE_NOTES_v0.8.0.en.md).
The latest scientific comparison is in the [ten-paper workflow report](V08_TEN_PAPER_COMPARISON.en.md); its historically reused denominators are not pooled with the older twenty- or eight-paper batches here.

## Final frozen acceptance (2026-10-30)

| Scope | Actual result and limits |
| --- | --- |
| Complete engineering suite | **3953 passed, zero failed, 148 skipped, 323.96 seconds**. Python 3.14.3 with UI/MCP installed; source, test, and script objects were unchanged before/after. |
| Optional dependencies and platforms | Local skips comprise 138 opt-in browser fixtures, two OCR cases, and eight system-link permission cases. They are not passes; the final PR commit runs a separate full cloud matrix. |
| Build and fresh installation | A fixed Git archive produced wheel/sdist and passed Twine. Two genuinely new venvs normally resolved and installed base and UI+MCP dependencies without old site-packages. Version, pip check, actual imports, and zero-model-call local mode passed. |
| Windows CLI | Newly installed packages display both names under redirected cp1252:strict and utf-8:strict; the base entry point does not load NiceGUI/Playwright. |
| Official MCP protocol | A real SDK 2.3 stdio client in the new installation discovered 23 tools and made eight successful local calls, including expected path-boundary and unauthorized-network rejections. Discovery does not establish online acceptance of every tool. |
| Installed UI | An isolated loopback service returned home 200; wrong Host/Origin/cross-site requests 403; unknown/traversing file routes 404. Self-started services exited; the user's 8098 instance was untouched. |
| Same-task real GUI | Ten checks and seven screenshots: Chinese metadata Mock planning → explicit content authorization → native reading/assembly → results and physical original page → clicked MD/CSV/JSONL and native ZIP export. Authorized UI task, run, result, and export share one fingerprint. The form explicitly changes hybrid to parsed after planning; the initial draft is not claimed to be the authorized final task. |
| Documentation and data | Sixteen Chinese-primary/independent-English pairs; a project-wide README plus conduct, contributing, security, and collaboration guidance. Sensitive-data checks cover 710 tracked files and actual H1 packages: no PDFs in the wheel, only four self-made fixtures in the sdist, and no real papers, private raw answers, user scripts, or credentials. |
| Ten-paper evidence integration | Completed answers are reused without paid reruns. Nine-paper primary analysis: AN 30/40 versus web 24/40; ten-paper supplementary analysis: 33/44 versus 24/44. Web remains stronger in some research-question comparisons. This is neither a new holdout nor a rerun on final release source. |

Final engineering, installation, protocol, and GUI acceptance made **zero paid model calls**. The GUI uses explicit MockTransport, not an online scientific-quality claim. Final cloud-commit checks, merge, tagging, and PyPI upload are separate publication steps, not predeclared from local results.

Source objects are `src=a90fe88a3c0884fa88c6d33e571f1b632e9c0f95`, `tests=81e9a455ef94b1ef1aeee91944af9edc19e3e299`, and `scripts=a7c46ede25633c76d4cf01be4f3ddde1d25875d1`. Subsequent acceptance-text/document-link-only changes reuse evidence through identical objects and wheel members; they do not claim a repeated full-suite execution.

Local receipts are under `F:/AI4S/outputs/AN08_RELEASE_20261030/final-release-20261030/`: `full-h1/receipt.json`, `package-h1/summary.json`, `ui-h1/receipt.json`, and `final-content-audit.json`. H1 installation-acceptance SHA-256 values below are local evidence, not subsequent cloud-distribution checksums:

- wheel: `68354c7eb7b4f8413453b282d9aa952e7999425ee5a97601608a50442dfc47d6`.
- sdist: `91ea0053fbaaf5cc85e874b83fcc4c4616f19025c26f4b897330c7797d039988`.

After bilingual branding, actual Windows CI reproduced a root-CLI UnicodeEncodeError under redirected cp1252:strict. Fix `ae0d465` configures UTF-8 text output, preserves lazy optional imports, and explicitly tests both encodings. Related regressions had 1127 passes and 18 skips, followed by eleven successful cloud checks on that commit. The final documentation commit still checks its own cloud results.

The everyday 8098 workbench was subsequently restarted from integrated 0.8.0 with both names displayed; 81 source/canonical files, 26 historical tasks, and settings bytes stayed unchanged. The historical statement below that the old process was not restarted describes only earlier isolated acceptance.

## Integration scope

- Both branch histories are preserved in merge `6829be8`. Two textual conflicts concerned provider stage/custom-operation prompts and CLI task-fingerprint tests; both correct behaviors were retained.
- Ordinary UI tasks gain a `direct/source_first` choice using existing task validation/saving. Loaded plans/presets retain strategy without automatic budget increases. The retired field-independent strategy does not return.
- Package version is 0.8.0; MCP reads installed-package metadata. Optional-dependency MCP CI actually runs official-SDK protocol and independent-authorization tests, preventing the entire matrix from silently skipping them.

## Actual verification of integration-stage snapshots

The first local checks bind to `feda03f4c34bd04edc6f0ad39108dfb5cc4028d1`. Cross-version
lock-test isolation was then completed, and new tasks defaulted to reading followed by assembly at the user's request. Separate default regressions are listed below;
the default-change snapshot is `f14834f`. The first full suite cannot count as validation after that change. Final remote checks bind the PR's actual HEAD;
this sentence does not substitute for current GitHub check results.

| Scope | Record for the stated snapshot |
| --- | --- |
| Merge-focused tests | 164 passed in 14.40 seconds: model stages, custom operations, first-reading cache, CLI/planning, title translation, and normalization. Zero paid model calls. |
| New UI strategy tests | Seven passed in 4.39 seconds: real-provider Mock two-stage flow, cache reuse, original budget, fingerprints, old plans/presets, and retired-strategy rejection. |
| New-default entry-point regression | 71 combined CLI/planning/MCP/UI checks passed in 23.81 seconds; another 35 UI-related checks include new defaults, old tasks/presets, and zero-call local mode. The sets overlap and are not added. The post-default full suite and real-browser evidence bind their own current source. |
| Formatting and static checks | Formatting and Ruff passed for 556 files under `src/tests/scripts`. |
| First integrated full suite | 3947 passed, zero failed, 148 skipped, 231.96 seconds, bound to feda03f and retained historically. |
| Default-change snapshot full suite | **3952 passed, zero failed, 148 skipped, 274.33 seconds**, bound to f14834f. Both UI and MCP were installed; tracked files were clean before/after and the two user scripts untouched. |
| Frozen parser regression | Twenty fixed DOIs passed sequence checks; four self-made PDFs passed parsing-eligibility checks; original manifest hashes stayed unchanged. Not new real scientific accuracy. |
| Default-change snapshot real UI browser | Temporary Chromium156, independent library/port, eight passing checks on f14834f: new tasks initially use reading then assembly without manual selection; Mock planning retains strategy and ten-request/CNY 2 budget. Both unauthorized gates, result pages, and step original pages passed. Source files and six PDF/provenance files were unchanged; service closed. |
| Package/dependency acceptance | First frozen archive built wheel/sdist and passed Twine; genuinely new base and UI+MCP venvs installed with online dependency resolution, noneditable and without old site-packages. Version 0.8.0, pip check, and CLI passed. The final post-default package is built separately from its actual commit; the first package hashes below do not stand in for it. |
| Packaged MCP/UI baseline | Official SDK2.3 real stdio reported version 0.8.0, 23 tools, and eight local calls. Package UI home returned 200; wrong Host/Origin/cross-site returned 403; unknown/traversing file routes returned 404. Self-started processes exited. The final package requires separate current-commit receipts and CI verification. |
| Final GitHub CI | Supplied by current-HEAD checks on the release-candidate PR. Python3.11–3.14, wheel, MCP, OCR, Linux/Windows browsers, and both-platform workbench gates must all pass before merging; old branch green checks are not substitutes. |

The ordinary full suite's 148 skips comprise 138 opt-in real-browser fixtures, two external OCR cases, and eight local
symlink/junction-permission cases. They are not local passes; remote optional-dependency/browser jobs run separately.
Actual UI interactions are listed separately; eight GUI checks do not establish execution of all 138 browser fixtures.

### Defaults for effective mechanisms

New AI tasks—ordinary UI, Chinese CLI, and MCP natural-language planning—default to `source_first`, based on the previously observed four-paper ABC
contemporaneous confirmation improvement from 55/77 to 63/77. Deep thinking, the 65536 output cap, and verified parsing/citation/delivery fixes
remain default. Saved tasks and explicit strategies remain intact. Original v1 tasks omitting strategy still mean direct; local mode
does not call models, and new defaults do not raise budgets. Global material reduction, fixed image tiles, additional Agent review, Pro
routing, and similar routes lack stable scientific net-benefit evidence and are not enabled from isolated success. Compact encoding is used only for resource needs or
input-limit fallback. SI/additional-page reading remains bound to selected documents and this authorization.

First `feda03f` acceptance-package SHA-256 values, retained but not checksums for subsequent default-change builds:

- wheel: `38cf0866f29daa8832b29d5afe6c8443564d0b09ca912e96df6596bed42f06ef`.
- sdist: `97dea4e5620ad542efe01887b344f2f70cfc236a120cbd2c5dd9c6e052a97122`.

The wheel includes no paper PDFs. The sdist includes only four repository-made parsing fixtures, not real scientific test papers uploaded to a public package.
This integrated acceptance made no paid-model or publisher requests. UI natural-language planning used explicit MockTransport,
not a real-model claim. Earlier real CLI research execution remains documented in the research-stage report.

Full local logs, JUnit, source objects, installation logs, and screenshots are under `F:/AI4S/outputs/AN08_RELEASE_20261030/`:
`full-suite-feda03f/receipt.json`, `ui-acceptance/final-handoff.json`,
`package-acceptance/summary.json`, and `parser-evaluation.json`. These paths are not runtime dependencies.
Default-change full-suite and actual UI evidence are `full-suite-default-f14834f/receipt.json` and
`ui-default-source-first-f14834f/final-handoff.json`; final packages/checksums are saved separately for their actual commit.

## First remote failure and fix, retained

The first Python3.11 base environment had 3675 passes, 313 skips, and one failure:
`test_history_status_resolution_and_mtime_share_short_io_lock`. Its global `Path.stat`
hook also intercepted earlier Python `glob` discovery of literal filenames before the status-I/O lock under test was entered.
The fix preselects discovered candidates in this test while retaining strict parse/mtime/concurrent-write lock-boundary checks;
it does not weaken production locks, add retries, or skip platforms. Six related local lock tests passed in 5.23 seconds. The PR reruns
the complete cloud gates. Original failure log `ci-first-123926529755.log` remains; jobs skipped because an upstream job failed
are not passes. The candidate also includes public main's ancestry: main's 0.7.3 squash tree matches the already included
historical version exactly, without changing old parser code in the integrated tree.

Before the default change, all eleven remote checks on `0f297e5` passed, including real Windows/Linux browsers, OCR,
MCP, and both-platform workbench. Evidence: `pre-default-0f297e5-cloud-success.json`. That does not replace
verification after the default change; inspect the PR's current checks directly.

## Scientific quality and data protection

This is engineering/entry-point integration, adding no scientific-performance denominator and changing no old references or original model answers. The following preintegration batches are retained: among seventeen common papers from the original twenty, DS scored 71/84 and Qwen 69/84; a separate eight-paper B batch's normal route scored 21/24 and 5/8 records. All use assistant source review rather than expert gold. Complex relations, figure readings, and internal source conflicts remain limited. See the [scientific delivery report](V08_DELIVERY_REPORT.en.md); the subsequent ten-paper historical workflow comparison has its own [report](V08_TEN_PAPER_COMPARISON.en.md), without backfilling or pooling these original denominators.

Acceptance used independent output, synthetic fixtures, and explicitly labeled Mock. The original user library/8098 service, two debug scripts, PDFs, provenance, and old canonical artifacts were preserved. Real browser fixtures, protocol acceptance, and online model/publisher results are recorded separately and cannot replace one another. See the [v0.8 release notes](RELEASE_NOTES_v0.8.0.en.md) for functionality and use.

## Rechecking integration by feature and filling coverage gaps

On 2026-10-30, research branch `59ce727`, UI branch `b4d1002`, and integrated `880c9d7` were checked again.
No implemented feature was found lost during merging. All 49 original UI source files, 760 symbols, and 106 UI test files remain;
only two research-UI files gained strategy wiring. Research's original 169 source paths and 1589 test functions remain;
old UI code did not replace the core engine, contracts, reading-then-assembly flow, result validation, or historical export.
Another 76 boundary tests and 81 UI feature tests passed. These overlap existing full-suite coverage and are not added to its count.

The previously incomplete same-plan GUI flow was completed: original PDF in a new workspace → metadata Mock planning →
explicit content authorization → native inventory/assembly stages → the same task's results and physical original page →
click exports for Markdown/CSV/JSONL and native task data. Ten actual browser checks passed with matching plan, native-run,
result, and export task fingerprints. No research result was preseeded and no real-model/publisher requests occurred; the self-started service closed.
This establishes entry-point/shared-engine wiring, not new scientific accuracy. Installed-package SDK checks had actually discovered 23 tools,
with eight calls covering seven distinct tools including rejection paths, not online acceptance of all 23 tools.

`test_browser_connection_live.py` was also found missing from both-platform browser CI. An isolated run showed the original test
incorrectly required page enumeration order to survive CDP reconnection. An independent Playwright control without AN also reversed order while
all original targetIds, URLs, windows, page markers, timeOrigin, and navigation histories remained unchanged. The original failure is preserved.
The test now compares those states exactly by target, still checking page count, browser liveness, native SI bytes, and only two
fixture requests. Together with connection unit tests, 23 checks passed. It was added to Windows/Linux browser CI; current-commit remote
results must still be read from PR checks rather than reusing the earlier eleven green checks. Product source did not change for this supplementary acceptance.

Feature preservation does not mean every advanced capability has an ordinary UI button: native XLSX sheets are readable through MCP,
whereas automatic UI research materials currently include PDF SI only. `preserve_readings` and explicit `compact` configuration still use expert
task entry, as does complex step/citation editing. The old 8098 UI process was not restarted during that isolated test;
using the integrated version required restarting from the 0.8.0 installation. An isolated test does not establish deployment into that old process.
Detailed original evidence is in `final-feature-recheck/` under the local directory above.
