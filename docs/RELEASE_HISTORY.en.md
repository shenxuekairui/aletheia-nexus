# Aletheia Nexus (溯光) — Release and Acceptance History

[中文](RELEASE_HISTORY.md) · [Current quality and status](V08_STATUS.en.md) · [Latest ten-paper comparison](V08_TEN_PAPER_COMPARISON.en.md)

## v0.8.0: AI literature processing and the local workbench

On 2026-10-30 the research/MCP and local-workbench branches were integrated into `release/v0.8.0`, with package version 0.8.0.
Regression, browser, SDK and installation evidence for the final commit is recorded in the [integrated acceptance report](V08_RELEASE_ACCEPTANCE.en.md).
See the [release notes](RELEASE_NOTES_v0.8.0.en.md) for capabilities and scientific limits. Establish the published release identity by checking the actual main commit,
version tag, GitHub Release and PyPI files together. The 0.7 history is not rewritten, and passing engineering checks does not establish scientific accuracy.

This file preserves historical versions, test snapshots and the interpretation of real-network acceptance results. The [README](../README.en.md) introduces the project, current capabilities and entrypoints. Every number below belongs to **the commit, input set and environment at that time**, rather than a generally comparable download success rate. Real publisher results depend on institutional authorization, site behavior and run budgets. Original reports may contain protected access context and remain local rather than being committed.

To protect personal commit information and old run records from the original development repository, this public repository starts from the audited v0.6 source snapshot. **It does not include early Git commits or the `v0.5.2` tag.** The v0.5.2 numbers below describe the frozen private-development state; they do not imply a tag or commit that can be checked out in this public repository.

## v0.7.3: Closing the 0.7 series

Capabilities and limits at that stage are documented in the [v0.7.3 release notes](RELEASE_NOTES_v0.7.3.md) and [acceptance record](V073_ACCEPTANCE.md). After results were known, the owner authorized closure against practical design goals. The original numerical targets were not reached and first scores were not rewritten. The second set contained 12 articles and 4 supplements, totaling 673 pages. First complete-answer correctness with the primary OCR configuration improved from 25/60 to 35/60; subsequent exposed regression retained 36/60. The original 75 questions reached strict complete correctness of 70/75; the previously confirmed 52 content items and 64 key historical regressions were preserved. The final twenty-task supplementary ledger reduced independent checks from 42 to 33; the earlier result of 21 checks is not used to claim a final 50% workload reduction.

See the [v0.7.3 Release](https://github.com/shenxuekairui/aletheia-nexus/releases/tag/v0.7.3) for the published identity, final CI, PyPI installation and checksums. Completion of that release chain closed the 0.7 series, with no routine 0.7.4 feature version planned. Important scientific citations still require review of the original page. Local AI suggestions use the existing separate interface, and default parsing does not call a remote model.

The v0.7.2 [release notes](RELEASE_NOTES_v0.7.2.md), [practical scientific acceptance](V072_PRACTICAL_ACCEPTANCE.md) and [published release](https://github.com/shenxuekairui/aletheia-nexus/releases/tag/v0.7.2) retain their historical meaning. That release unified parsing configuration and acquisition-identity decisions and separated figure/table responsibilities. Layout replay of 42 documents and 403 pages retained identical complete parsed documents.

The original status and first scores of each development check are preserved below. Phrases such as “not committed,” “not published” or “acceptance not passed” describe their historical snapshots, not the current version's status.

## Development snapshots: original records retained

- 2026-10-23: [Parsing delivery for practical research](V072_PRACTICAL_ACCEPTANCE.md). First answers to 16 research questions on two new papers scored 14/16; the same set reached 16/16 after generic layout fixes. Historical set K regressed at 12/12, with its first 8/12 preserved. Code tests: 1895 passed, 114 skipped. Source conflicts and blurred chemical formulas in figures still require local evidence review. Not committed, merged or released at that snapshot.

- 2026-10-22: [v0.7.2 final fixes and delivery](V072_FINAL_DELIVERY.md). The remaining 4 items were fixed; H/I/J regressions were 16/16, 8/8 and 12/12. New set K, comprising 2 papers and 1 supplement, first scored 8/12, identical to the previous version. Its 4 failures concentrated at two source locations without local hints; formal scientific acceptance was not passed. Local Python 3.14: 1864 passed, 114 skipped; the package passed 10 CLI checks. Not committed, merged or released.
- 2026-10-22: [v0.7.2 units and column-splitting retest](V072_UNITS_COLUMNS_VALIDATION.md). Of the 8 remaining items, 7 were fixed. H/I regressions scored 16/16 and 7/8; new set J first scored 9/12, the same as the previous version. Across 77 PDFs, dual-OCR review locations changed 4223→4078. Figure scales and new table failures still blocked formal acceptance. Full suite: 1835 passed, 114 skipped. Changes were not yet committed or released.
- Source version at that time: `0.7.2`. Added local/no-DOI/SI parsing, cross-paper search, batch recovery and selected-evidence export. See the [v0.7.2 release notes](RELEASE_NOTES_v0.7.2.md). Published identity and its commit are determined by [GitHub Releases](https://github.com/shenxuekairui/aletheia-nexus/releases).
- Upstream `v0.7.0` had been merged into `main` and tagged. Its [release notes](RELEASE_NOTES_v0.7.0.md), tag and test evidence remain unchanged. Check the [PyPI project](https://pypi.org/project/aletheia-nexus/) and fresh-environment installation evidence to establish whether a newer version has been uploaded.
- v0.6.0 source version: `0.6.0`. The first public version was closed on code correctness and installability; formal institutional-access qualification was outside that closure scope.
- Code-level closure requires actual `success` for Python 3.11–3.14, real Chromium, real OCR and clean-wheel cloud jobs at the final release commit. Frozen parsing evaluation must also produce and retain a machine-readable CI report. A draft PR's `skipped` status or a failure with no executed steps is not a pass. Specific run records accompany the GitHub Release.
- On 2026-09-24, the project initiator deferred formal positive-control institutional-access acceptance until after the public version. It was not passed and cannot be replaced by historical cumulative 37/40 or 19/20 results. Release notes must disclose that access depends on the user's lawful subscription, institution and current site behavior.
- Merge and tagging order follows the [manual's historical release checks](USER_MANUAL.en.md#10-historical-v073-checks-before-merging-main) and [v0.6 technical specification](v0.6-acquisition-maximization.md#16-exit-criteria).

## Acquisition updates included in v0.7.2: original development records

- [x] **Browser defaults follow the system proxy (2026-10-12):** ordinary launch, managed launch, CDP automatic launch and compatibility scripts now default to system proxy settings, with direct access when no system proxy exists. Mutually exclusive `--direct-connection` (alias `--browser-direct-connection`) and `--browser-use-system-proxy` remain available. Python follows the system by default; `direct_connection=True` or the older explicit `use_system_proxy=False` selects direct access.
  - BrowserSession fixes the selected system/direct mode for the run. Failed reconnections do not switch modes, and changing modes during a run is rejected. An already open AN window with a different requested mode is not silently reused or restarted; an external CDP browser retains its own settings. AN does not modify the system proxy or freeze proxy-address/VPN-route changes made by the user.
  - This was a general default-behavior change. Historical direct-download results retain their original interpretation and are not online acceptance evidence for the new default. At that snapshot, changes were local and not committed or released.
  - Local Python 3.14 ordinary regression: **1465 passed, 85 skipped**. Separately enabled real-browser fixtures for both modes: **2 passed**, covering native PDF downloads, dedicated profiles, retained sessions and client reconnects. Fixtures used self-authored pages and intercepted responses, without contacting real publishers or changing system proxies. Ruff, CLI/compatibility-script help and diff checks passed.

- [x] **Generic CNKI bibliography verification and status preservation (2026-10-11):** `cnki_bibliographic/v4` uses general parenthetical structures for institutional-journal full/base names while retaining conflicts between institutions and versions. It adds publication evidence at the physical edges of the first 3 pages. If an image-based journal name cannot be extracted, the caller must supply full bibliographic constraints; a uniquely declared PDF DOI, article identifier, or issue/year plus continuous pages then independently links the CNKI record. There are no paper, DOI or journal-name allowlists, and identifiers carried by a candidate do not themselves establish verification.
  - Search/navigation failures after receipt of an unverified PDF no longer overwrite file status. CLI output uses safe bibliography-conflict field names. Context reconnects also honor the paper interval. Original batch reports, later metadata supplements and post-fix regressions remain separate.
  - Local Python 3.14 ordinary regression: **1429 passed, 84 skipped**; Ruff passed. Offline verification of 20 existing PDFs against the original no-DOI requests achieved **20/20 MATCH**. Online downloading is recorded separately; offline verification is not a new successful download. Changes were local and not yet committed or released.
  - Post-fix online regression used the original inputs for the 10 affected papers, without manually adding DOIs/record IDs or replacing journal names. AN CLI `--source cnki` downloaded them into an independent directory with explicit `--cnki-paper-interval 5`: **10/10 VERIFIED**, command exit code 0. The existing institutional session was reused, but old PDFs/checkpoints were not. This is regression evidence for that input set, not a success rate for arbitrary papers.

- [x] **CNKI paper interval (requested and recorded on 2026-10-11):** include the local implementation in the next formal version. By default, CNKI starts the next paper at least 5 seconds after the previous acquisition ends, crediting elapsed time. The first paper, local imports and checkpoint reuse add no wait; other sources are unaffected. The unified CLI and CNKI-specific script add `--cnki-paper-interval SECONDS`; the Python option is `cnki_paper_interval`, default `5.0`, with `0` disabling the interval. Explicit rate limiting or download HTTP 429 stops subsequent CNKI acquisition in the current session with `CNKI_RATE_LIMITED`, without scheduled automatic retry.
  - Changes cover the shared browser session, configuration validation, CNKI message/response identification, acquisition orchestration, both command entrypoints, tests and documentation. At that snapshot they were local, not committed or released. Merge them with the JSON organization update below and check off after final release validation.
  - Local Windows / Python 3.11: ordinary regression **1380 passed, 84 skipped**; separately enabled CNKI real-browser fixtures **19 passed**, including stopping after native download returns a blank HTTP 429. Ruff formatting and lint passed. Browser tests used intercepted local responses, not the live CNKI site, and do not establish its online download limits.

- [x] **Keep download JSON separate (requested for the next version on 2026-10-10):** merge the local directory-organization implementation into the next formal version. New acquisition records, batch reports, checkpoints and library-tag JSON default to a `json/` subdirectory; categorized directories each use their own `json/`. Retain compatibility for old directories, resume and parsed-source validation, and honor explicit report/checkpoint paths. This concerns acquisition/local-management JSON and does not change the default `.parsed.json` output location.
  - Pending changes include `src/aletheia_nexus/core/artifact_paths.py`, acquisition storage, batch resume, auditing, CLI, library, parsing entrypoints, private-corpus validation scripts, tests and documentation. At that snapshot implementation was local in `integration/cnki-acquisition-final`, not committed or released.
  - Local targeted regression: **251 passed, 2 skipped**; Ruff passed. Include the change in the final release commit, run the existing release checks, document it in the new notes, and then check off this item.

## v0.7.1 — Acquire, organize and reuse trustworthy literature

Building on v0.7 source-linked parsing and AI export, this version completed everyday workflows for bringing papers into a local library:

- **Paper inputs:** CNKI journal DOI/title requests use unified acquisition and identity checks, retaining the division of work with public sources and publisher routes.
- **Institutional access:** default ordinary launch uses a dedicated browser, direct access and session reuse; the user still completes logins and CAPTCHAs.
- **Local organization:** specify folders, names and tags at input time. New files default to year-journal-title; use `library` to view and update tags.
- **Trustworthy reuse:** resume and repeated acquisition protect files and source records. Parsing, search, OCR and the three export forms retain the evidence chain without weakening validation.

Upgrades do not batch-rename old files. Old checkpoints without source hashes trigger reacquisition. CNKI papers without a DOI can be acquired and verified, but the parsing channel at that time still required a real DOI. See the [v0.7.1 release notes](RELEASE_NOTES_v0.7.1.md) for features, examples and other limits.

Local engineering regression was completed, with its exact scope below. Formal publication requires cloud CI and distribution validation at the same final commit. Check actual results in [GitHub Actions](https://github.com/shenxuekairui/aletheia-nexus/actions) and release records; local checks and older online scores are not substitutes.

### 2026-10-10 project-wide pre-release checks: integrated workspace

The baseline was the integrated workspace after `c553855`, covering DOI/metadata, discovery/acquisition, CNKI routing/retries, browser lifecycle, identity/role/hash checks, local management, parsing/export, packaging and publication. This was a risk-directed code review and full test run, not a formal security proof or a claim that line-by-line review found every problem.

The work retained local-first operation, verifiable provenance, layered reuse and bounded automation. It added no database, background index, browser-forensics service, automatic login or CAPTCHA handling; it did not rewrite the parser, weaken `VERIFIED`, or add automatic refreshing for other publishers. Existing URL redaction moved into the shared core with compatible imports, avoiding a reverse dependency from public acquisition to the browser layer.

Confirmed and fixed in that round:

- Reacquiring the same PDF rewrote its sidecar and invalidated historical parsed-evidence hashes. The first successful record is now retained; damaged/conflicting records cannot be silently overwritten.
- Uncategorized DOI resume checked the PDF without provenance. All inputs now verify PDF/sidecar hashes; old checkpoints without hashes trigger reacquisition.
- Signed URLs in public HTTP were not redacted. Sources, candidates, redirects and network-error URLs now use one redaction function without changing runtime request URLs.
- Fixed `.part` names could overwrite another task's temporary content. Acquisition records, parsing and exports now use separate temporary files.
- Local management overtrusted the `VERIFIED` string; damaged tags hid papers; Windows case differences bypassed reserved-directory checks. It now checks recorded evidence, retains papers with tag warnings, and blocks internal directory names case-insensitively.
- Release gates omitted CNKI/ordinary-launch checks; source distributions omitted fixtures while including only some tests. Validators, CI and explicit packaging lists were completed; local downloads, authentication profiles and temporary diagnostic scripts are not packaged.

Local Windows / Python 3.12.14 validation:

| Check | Result |
| --- | --- |
| Full deterministic suite | 1339 passed, 83 skipped |
| Separate real-browser fixtures: shared layer, CNKI, ordinary launch/reconnect | 81 passed |
| Full suite after unpacking the source distribution | 1339 passed, 83 skipped |
| Clean wheel environment: CLI, local management, parsing, export | 164 passed, 2 skipped |
| Ruff formatting/lint, compilation, dependency consistency | Passed |
| Frozen 20-paper input integrity and self-authored parsing fixtures | Passed; not an online download success rate |
| wheel/sdist build, Twine, installed CLI/doctor | Passed |

Of the 83 ordinarily skipped cases, 81 browser cases were actually executed separately. The other two concerned real OCR without local Tesseract and Windows symlink privileges. The clean wheel did not install the browser extra but retained public acquisition, parsing, exports and local management. No new live-publisher acceptance was added; older field results do not replace this round's tests.

**Local passes still did not establish formal publication.** Test builds during those engineering checks used version `0.7.0`; they were local validation artifacts, not a new release. Subsequent preparation changed the source version to `0.7.1`. Build `0.7.1` again from a clean commit, pass Linux/Windows, Python 3.11–3.14, real OCR, browser and clean-wheel cloud gates, and then publish a new tag. Do not reuse `v0.7.0` or overwrite a same-version PyPI package. The machine-readable local report remains in ignored `downloads/release-readiness-20261010/`, outside the distribution.

## 2026-10-09 integration with updated upstream and preparation to push the fix branch

Refreshing remotes showed 42 new commits on the original v0.7 feature branch, merged into `main` through `d415a06` and tagged. `fix/publisher-recovery-integration` was created from updated `main` and merged five local acquisition-fix commits, retaining upstream parser 2.5.0, exports, artifact-identity checks and Chinese documentation. The shared upstream export writer already protected sources, so redundant local CLI checks were removed while integration regressions were retained. No existing branches or release tags were overwritten or reused.

Post-merge validation: Python 3.11 and 3.14 each **930 passed, 59 skipped**; Chromium **58 passed**; real OCR in each Python environment **1 passed**; three public OA qualification papers passed. The private sets again achieved **24/24, 14/14 PARSED**, with identical main text, anchors and structure. Uncertainty-label changes in 31 tables matched existing upstream 2.5.0 fixes exactly. Dependency, Ruff, compilation, frozen-input and parser-gold checks passed. See the [upstream integration review](ACQUISITION_PRE_UPDATE_AUDIT.md#上传分支前与最新上游集成); originals are outside the repository in `branch-integration-20261009`. This does not replace final-commit cloud CI or cross-institution/device qualification.

## 2026-10-09 final integration and local release preparation

The acquisition, recovery, parsing, search, export and installed-CLI chains were checked on the converged `2223187` state. Upper-level browser recovery ordering was completed: observed PDFs, including unknown CDNs, remain ahead of inferred entries under route-count limits, and duplicate URLs retain original provenance. Previously ordering had only been adjusted inside one browser route, not at the batch entrypoint. A real Chromium fixture reproduced that gap before confirming main-article acquisition when the batch permits one route. Exports also reject overwriting their own input and PDFs/acquisition records referenced by local locators, even with `--overwrite`.

Release validation imports the current checkout explicitly to avoid testing different source code through a reused environment, and adds an explicit Chromium check. Private-corpus qualification no longer silently skips missing sidecars; empty inputs, changed input hashes and incomplete parsing fail. Clean-wheel CI/release checks add CLI contracts for acquisition/import, checkpoint resume, parsing, search and three export formats. Existing architecture is retained, with no new runtime dependency, public download option or publisher-specific pipeline.

Local Windows / Python 3.11 and 3.14 each **915 passed, 59 skipped**; separately enabled Python 3.11 Chromium **58 passed**; real OCR in each Python environment **1 passed**. Three frozen OA parsing qualifications passed. Fixed private corpora achieved **24/24, 14/14 PARSED**, comprising 436 and 219 pages, with main text, anchors and structure matching older results. Legacy figure/table `resolved` fields were migrated, so identical historical artifact IDs were not claimed. Public PMC DOI `10.1021/acsomega.2c08031` entered actual acquisition through an existing PMC-page candidate; the official Article Datasets route returned an 18-page `VERIFIED` main article with independent identity/hash auditing. This was not a success-rate test of the full automatic DOI-discovery chain.

Ruff, compilation, frozen input, parser gold, dependencies, sdist/wheel and Twine passed. The independently installed base-wheel environment passed **16 CLI tests**, and its 94 Python source files matched the checkout. See the [final integration record](ACQUISITION_PRE_UPDATE_AUDIT.md#最终接入复核2026-10-09). Original files/reports remain outside the repository in `final-integration-20261009`. Final-commit Python 3.11–3.14, Linux/Windows Chromium, OCR and package cloud jobs still had to pass. Cross-institution/device qualification remained incomplete; this round did not rerun the eight-paper official-site batch or publish remotely.

## 2026-10-09 acquisition convergence before further updates

Necessity and overfitting review retained entry identification, reader login, PDF challenge waiting, authenticated delivery and shared main-article verification. Duplicate endpoint recovery and candidate-request budgets were merged; popups only observe. Wiley control preferences affect ordering only, and PDF URLs observed in metadata/pages/network precede inferred routes. Terminal summaries were unified and hidden/disappeared controls gained adapter checks. Production code decreased by a net 363 lines, without a new public option or dependency. See the [pre-update review](ACQUISITION_PRE_UPDATE_AUDIT.md) for rationale, counterexamples and final checks. Historical official-site results are not relabeled as a source rerun.

Local ordinary suite: 903 passed; real Chromium fixtures: 57 passed. The pre-release script, sdist/wheel builds, Twine and clean-wheel dependency/CLI smoke checks passed. Final-commit cloud qualification and cross-institution/device acceptance still required independent completion. No main merge, tag or PyPI upload had occurred at that snapshot.

## 2026-10-09 entry and waiting fixes after the complete CLI retest

The formal `acquire` batch retest exposed selection of a Science subscription-administrator entry, PDF-endpoint CAPTCHAs missing visible waiting, long dynamic/hidden-control scans, and stale interaction instructions after a CAPTCHA redirected to SSO. Fixes covered institution-entry filtering, browser resume at PDF endpoints, recognition of already verified delivery while waiting, operation/scan budgets per control phase, and notifications when challenge type changes. The official-site runner also defaulted to unlimited waiting for human verification.

The complete CLI checkpoint finally reported 8/8 VERIFIED: 7 official-site main articles and 1 OSTI version, with four reused checkpoints. Elsevier was observed pausing at a CAPTCHA and then automatically receiving the main article and continuing in the same process after user completion. RSC also needed manual help reaching the institutional entry. A separate AN official-site call then tested Science `adh4355`, obtaining the 8-page official main article after human verification; the original 79-page OSTI record was retained. Official-site main articles for all eight DOIs were eventually acquired, without claiming a single unattended eight-paper success or cross-institution/device acceptance. See [acquisition recovery fixes](ACQUISITION_RECOVERY_FIXES.md). Final ordinary tests: 898 passed; real Chromium fixtures: 53 passed; Ruff, formatting and diff checks passed.

## 2026-10-09 browser-verification recovery and delivery fixes: source patch

Official-site records and shared-code review drove fixes for resuming items after verification, activating access through Wiley's remembered institution, recognizing TF access where the institution is known but the target remains restricted, Elsevier LinkingHub's official entry, fallback recovery from an existing PDF page, retained challenge popups and PDF-event delivery. Embedded viewers gained streaming-size and waiting limits; independent auditing no longer lets optional text-extraction exceptions override a received main article. Further testing found PDF-endpoint CAPTCHAs swallowed as ordinary failure; terminal-state propagation was added and repeated requests stopped. Native-only takeover does not replay context HTTP requests.

Local Windows / Python 3.11 full suite: **891 passed, 40 skipped**; separately enabled self-authored real Chromium fixtures: **39 passed**. Ruff, formatting and diff checks passed. First attempts on eight official-site papers produced **2 VERIFIED**, five CAPTCHA cases and one external timeout. A separate rerun of that timeout case, with missing-status handling fixed, produced INTERACTION_REQUIRED. The latest aggregate therefore contained two successes and six interaction-required cases, not one rerun batch. Confirmed unavailable TF/Thieme access was not reauthenticated.

The earlier collection of 30 papers with 25 official-site main articles is historical cumulative evidence, not this patch's single-run automatic success rate. The exact historical Science hang was still unreproduced; cross-institution, device and operating-system qualification remained pending. See [acquisition recovery fixes](ACQUISITION_RECOVERY_FIXES.md) for design, evidence and validation boundaries. Original records and papers remain outside the repository.

## 2026-10-08 browser acquisition-control scanning fix: source patch

One live Science attempt showed the main-download control at index 609 after takeover of an existing article tab, beyond the generic fallback scan's first 120 controls. That mode does not replay direct PDF requests, so the previous result was `NO_FILE_CANDIDATES`. After the fix, the same lawful browser session acquired a 9-page main article whose identity, role and hash passed verification. All five Science official main articles had eventually been acquired, but the last was a separate post-fix test, not a full batch rerun.

Related review covered shared PDF/institution-login controls, IEEE institutional popups, popup-close controls and embedded PDF frames. Controls are filtered by text, links and accessibility attributes before applying existing attempt limits. Same-origin PDF frames precede unrelated frames while bounded recovery remains. Supplement paths, recommendation popups and attachments cannot replace the main article; all downloads retain shared identity, role and byte checks.

Local Chromium fixtures cover link forms for Science, ACS, Wiley `epdf/pdfdirect`, RSC `articlepdf`, ScienceDirect `pdfft`, IEEE, Nature, MDPI and Thieme, plus JavaScript, accessible PDF/login buttons, long IEEE popups and delayed close controls. These are deterministic shared-logic tests, not online entitlement or download success-rate acceptance for other publishers. A separate unit regression covers unrelated frames displacing the PDF. Real papers, original pages, browser profiles and acquisition reports remain local, outside the repository.

## 2026-09-24 post-release source qualification: not the v0.6.1 tag snapshot

Source commit `7c91c89` fixed browser-challenge recovery and erratum-PDF false positives and completed launch provenance for AN's dedicated Edge and a strict offline verifier. Local Windows / Python 3.14 deterministic tests: **761 passed, 7 skipped**; real Chromium integration: **7 passed**. Ruff, frozen-input integrity, dependency and wheel-build checks passed. These counts belong to that commit, not v0.6.1 release testing, and that commit had not yet been published as a new PyPI version.

In an institutional session confirmed lawful by the project initiator, clean `7c91c89` and AN's dedicated direct-access Edge ran the full fixed CDI/desalination stress set: **18/20 `VERIFIED`**. Three ACS/Wiley positive controls with previously confirmed access achieved **3/3 `VERIFIED`**, covering two access systems, with runner errors **0**. One control overlapped the stress set, yielding 22 unique DOIs rather than a missing run. Strict offline checks passed; the three control articles' first pages, titles, page counts, identities and hashes were manually reviewed. The two unsuccessful stress papers retained `ENTITLEMENT_REQUIRED` and `INTERACTION_REQUIRED`. The original failed report using an unauthorized Elsevier candidate was retained and not spliced into the passing report. Reports, authorization controls, profiles and PDFs remain in Git-ignored local directories; the repository contains summaries and boundaries only. See [pre-v0.7 readiness and single-institution acceptance](PRE_V07_READINESS.md).

This evidence supports **one institution and two access systems**. It does not establish cross-institution reproducibility or entitlement to all publishers, nor mean that the frozen v0.6.1 PyPI package included the subsequent fixes.

## 2026-09-28 v0.7 private real-layout regression

The user supplied 24 papers kept outside the repository. `dois.txt` was deduplicated and PDF/acquisition-sidecar SHA-256 hashes fixed before execution. Old parser 2.0.0 and optimized 2.1.0 processed the same 24 papers and 436 pages, both **24/24 `PARSED`**. Structural section candidates decreased 2168→570; reference objects increased 967→1176, with unresolved references 68→62. The old parser treated undrawn PDF `/Image` resources as semantic images, producing 1151 unresolved figure objects. Version 2.1.0 stopped synthesizing those objects, with unresolved figure objects 0. Tables with located cells increased 3→11. Conservative checks of painted images and positions increased total runtime 34.69→50.61 seconds.

Further paper-by-paper comparison of source PDFs and artifacts on the same frozen input used 2.2.0 to re-extract and compare retained text across 436 pages. All 24/24 achieved identical normalized text, with omitted and extra words both 0. Body phrases such as “Figure/Table … shows/lists” no longer generated figure/table objects. Bracketed table rows, volume/page fields, institution IDs and review-comment numbers no longer polluted the primary bibliography; documents with same-label duplicate references decreased 7→0. Multiple references merged into a double-column text block share an anchor and are parsed separately, reducing unresolved references 62→41. Reference objects changed 1176→980, mostly by removing false table-row, volume/page, institution and review-number objects, not by losing body text. Highly similar captions from duplicate text layers retain one semantic object but every source block. Genuine `continued` and `figure supplement` evidence is not incorrectly merged.

These are aggregate diagnostics on identical hashed inputs, not manually item-labeled accuracy. 0 unresolved figure objects does not mean all real images were detected. PDFs, sidecars, queues and per-paper results remain in local ignored directories. Public CI still uses only self-authored distributable fixtures.

Version 2.4.0 achieved 24/24 and 14/14 `PARSED` on the same 24-paper/436-page and 14-paper/219-page sets. After unifying visible CropBox coordinates, retained characters totaled 1,716,967 and 871,617. Decreases from the old version concentrated in a few MDPI/JHEP PDFs with hidden, out-of-bounds or duplicate text layers; coordinate diagnostics and visible-page spot checks confirmed representative text was not visible body content. The old native-layer character-conservation rule cannot serve as the release gate, and the change is not semantic accuracy. Public evidence added three hash-frozen OA qualification papers and a real Poppler + Tesseract raster-only smoke check. The self-authored gold set's 886 characters had 0 deletions, 0 insertions and 0 substitutions. Full visual-information loss still requires broader page-level human truth.

The acquisition layer also adapted to PMC's 2026 Article Datasets distribution change. It queries the official public S3 bucket only where discovery already has a PMC record, filters DOI, open/manuscript status, retraction status and PDF fields, isolates per-version failures and reuses bounded retries. Real public sample `10.1016/j.heliyon.2024.e27078` returned a 14-page main article through this route, passing identity, role and SHA-256 checks. The route does not scrape PMC web pages or change publisher-authorization boundaries.

## v0.6.1 — CLI, adapters and Windows CI

This round moved publisher-page differences into `publisher_adapters/` and generic download capture into `browser_engine/`, added the installed `aletheia-nexus` CLI, Windows CI, PyPI Trusted Publishing, and English/community documentation. Historical v0.6.0 **734 passed, 7 skipped** belongs to the older commit and cannot automatically serve as final v0.6.1 evidence. The final v0.6.1 commit requires fresh local/cloud tests and, after actual PyPI upload, a clean-environment `pip install aletheia-nexus`. See the [v0.6.1 development/release plan](v0.6.1-development.md).

2026-09-24 development snapshot (**not** release acceptance): local Windows / Python 3.14 deterministic tests **742 passed, 7 skipped**, real Chromium integration **7 passed**; Ruff, fixed 20-paper input integrity, sdist/wheel and `twine check` passed. An independently installed development wheel passed version and `doctor` checks. Public DOI `10.1371/journal.pone.0310216` acquired with the new CLI `--public-only` was `VERIFIED`; this is one public-route smoke check, not cross-publisher success-rate or institutional positive-control acceptance. Development commit `a5e1023` passed all four cloud jobs; the formal release commit still required its own checks.

On 2026-09-24 the initiator decided to publish v0.6.1 first and disclose in the [release notes](RELEASE_NOTES_v0.6.1.md) that first installation/three-minute use by unfamiliar users lacked independent feedback and formal cross-institution positive controls remained incomplete. Both were open post-release validation work, not passed checks.

## v0.6 — Acquisition Maximization: first public code version

When public HTTP cannot obtain a `VERIFIED` main article, v0.6 adds authorized official APIs, persistent browser sessions, institution/account authentication and bounded human-in-the-loop recovery. PDFs still require shared structure, target-identity and main-role checks. Reproducible Nature/ACS false negatives and false positives from reference DOIs on later pages drove targeted `fulltext/identity.py` and `validation.py` regressions. The private repository's `v0.5.2` tag was unchanged.

Local RC deterministic snapshot on 2026-09-23: Python 3.11 and 3.14 each **734 passed, 7 skipped**; all 7 real Chromium integration cases passed in both environments. Subsequent documentation/benchmark checks on `2026-09-24` again produced 734 passed, 7 skipped on Python 3.14, Chromium 7/7, with Ruff, dependency, build and workflow-syntax checks passed. Local results do not replace complete cloud CI at the final release commit.

### Historical 40-paper stress set

The 2026-09-23 same-batch results below include the fixed fuel-cell, CDI and seawater-desalination groups:

| Input set | Same-batch `VERIFIED` |
| --- | ---: |
| Fuel-cell classics | 14/20 |
| CDI | 9/10 |
| Seawater desalination | 8/10 |
| Total | **31/40** |

Independent single-paper retests later used the same 40-DOI scope. Three ScienceDirect papers verified after lawful institutional authentication by the user; two Nature articles verified after fixing first-page title boundaries; AN automatically received and verified one IEEE paper after user institutional authentication. The **DOI-deduplicated cumulative result is therefore 37/40**, not the success rate of one full rerun; it does not replace the original 31/40 batch statistic.

The remaining papers were `10.1038/nchem.367` and `10.1038/s44221-024-00340-4`, whose pages required purchase and therefore showed explicit subscription boundaries, and `10.1061/(ASCE)0733-9372(2007)133:11(1004)`, whose institutional login was incomplete. The original latter status was `INTERACTION_REQUIRED`, not proof of its final entitlement. Regressions cover the reproduced ACS “Supporting Information” navigation error and Nature first-page title-order error; they do not establish zero false negatives for every new publisher layout.

### User-specified 20-paper input

The [original real input](../benchmarks/user_20260923_20_with_titles.json) from 2026-09-23 explicitly supplied titles for only 2 papers. AN's persistent Edge session, user-completed logins/CAPTCHAs, checkpoint resume and independent retests produced a DOI-deduplicated cumulative **19/20 `VERIFIED`**. The remaining paper, `10.1055/a-2508-9744`, required purchase at the official main-article entry, and the user confirmed no current subscription. Its automated `EXHAUSTED` status is not a PDF-verification failure.

To separate metadata-resolution changes from acquisition changes, the repository also retains a [frozen input](../benchmarks/user_20260923_20_frozen.json) for the same 20 DOIs with fixed titles, publishers and years. **19/20 is the original input's historical cumulative result, not one new frozen-input test.** See the [benchmark notes](../benchmarks/README.md) for source, field rules and offline-integrity checks.

## v0.5.2 — Multi-route Acquisition: stable freeze

- Tag: `v0.5.2`; tagged commit: `4f831eb75a38f19735cf6c98bcd64458fac344c0`; release date: 2026-09-17.
- Frozen deterministic tests: Python 3.11 **510 passed**; the complete frozen Python 3.14 CI workflow also passed. `707 passed、6 skipped` describes later development, **not** the v0.5.2 release snapshot.
- Fixed stress set in the same environment: CDI 4/10 and seawater desalination 2/10, totaling **6/20**. This measures public unauthenticated HTTP acquisition on a difficult corpus, not success across all disciplines.
- Scope: aggregate candidate sources, prefer direct files, resolve static landing routes, and orchestrate multiple routes with finite depth/budget until the first main paper passes structure, identity and role checks. See the [v0.5.2 specification](v0.5.2-multi-route-acquisition.md).

## Earlier capability layers

| Version | Delivered boundary | Detailed record |
| --- | --- | --- |
| v0.5.1 | Static landing/repository route resolution | [Route Resolution](v0.5.1-route-resolution.md) |
| v0.5.0 | Direct PDF acquisition, structure and article-identity checks | [Direct Acquisition](v0.5.0-direct-acquisition.md) |
| v0.4.2 | Discovery performance and provider assessment | [Discovery Performance](v0.4.2-discovery-performance.md), [Provider Assessment](v0.4.2-provider-assessment.md) |
| v0.4.1 | Discovery-layer reliability | [Discovery Reliability](v0.4.1-discovery-reliability.md) |
| v0.4 | Full-text discovery foundations | [Discovery](v0.4-discovery.md) |

This version history is separate from future ambitions. Native-text-first parsing and optional selective OCR were implemented in v0.7, while knowledge organization, scientific-truth decisions and agent workflows remained plans at that stage. Parsing capability alone did not establish their completion.
