# Native SI corpus fixes and retest (2026-11-03)

[中文](SI_NATIVE_CORPUS_FIX_20261103.md)

This round addresses native acquisition defects exposed by the [120-paper benchmark](SI_SCALE_BENCHMARK_20261103.en.md), with product source `a65cc4b`. **Native routes can cover more public resources, but cannot guarantee every paper and SI file from every publisher.** Subscription/login resources require an entitled official API or session. Unpublished, removed, unverifiable or delivery-refused files may remain unavailable.

Implementation alone cannot guarantee access: Crossref full-text links can still require subscription, login or a license ([official access documentation](https://www.crossref.org/documentation/retrieve-metadata/text-and-data-mining/#access-and-rate-limits)); PMC also limits which content is available for automated retrieval and reuse ([official open-subset documentation](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/)).

## Changes

| Defect | Fix and boundary |
| --- | --- |
| False PMC title mismatch | Compare visible text from markup such as `<i>`, `<sup>` and `<sub>` with the existing Unicode/punctuation normalization. Preserve raw sources. No fuzzy matching; DOI, PMCID, version, OA and retraction gates remain strict, with individually reported failed checks. |
| Filename/content mismatch | Strong byte signatures and bounded ZIP-member checks take precedence: actual PNG named `.jpg` becomes `.png`; actual OOXML named `.doc` becomes `.docx`. Record declared/detected formats and correction, without rewriting bytes or downgrading invalid OOXML to generic ZIP. |
| Unsupported formats | Add storage for MPG/MPEG, RAR and Python text attachments, with basic signature/text checks. No script execution, archive extraction or claim of content parsing. |
| Empty JATS placeholders | A completely empty `local-data` node becomes diagnostic only when explicit valid SI/source-data files resolve in the same inherited context. Descriptive missing-file nodes, other contexts and placeholder-only groups remain incomplete. |
| Legacy PMC URLs | Recognize official NCBI `articles/instance/<digits>/...` URLs for PMCID discovery. Obtain and verify the main PDF through the official manifest and DOI gate; never promote the SI URL itself to main text. |
| Site links in native HTTP fallback | Ignore generic review/help links without file evidence; retain explicit files, supported MIME, download attributes and download endpoints. Covers the prior IOP RSS and Cambridge help-link shapes; this is not a complete publisher-HTML reacceptance. |

CLI, workbench and MCP continue using shared acquisition/attachment services. Main-to-SI integration, SI-only recovery, source/hash reuse and separate roles remain in the existing workflow; no alternate engine or database was added.

## Live retest

Reuse the same 120 DOIs and 26 publisher/brand strata without replacement. The original manifest SHA-256 remains `a4fbd89422feeef92ed3c58b06d11a1f2c4e2eacd2ff74a0b8c90742c0011790`. Only the native workflow is scheduled for the whole cohort, including its normal HTTP fallback. The per-file cap is the product default **100 MiB**, so these counts cannot be used to calculate improvement against the original **16 MiB** round.

All 27 original non-COMPLETED cases in the 104 metadata-positive cohort were also tested at 100 MiB on an independent old checkout, `1c14dce`, whose product source matches `ada8b63`. The manifest and actual checkout versions are separately recorded. Old/new runs used 2/4 processes, public HTTP, 20-second request timeout, 20 attachments and 240 seconds per case, without browser, account login or model calls. This is exposed regression, not a holdout or an experiment with identical network conditions.

The first new run suffered a global TLS failure: from `073`, 40 consecutive new-main cases had only ConnectError, as did SI for eight historical main texts; `071`/`072` SI was also affected. NCBI, Europe PMC, Figshare and example.com probes all returned `SSL: UNEXPECTED_EOF_WHILE_READING`; the recorded local proxy path also failed. That run's **66 COMPLETED, 1 PARTIAL, 12 FAILED, 1 NOT_FOUND, 40 NOT_ATTEMPTED** remains at `current/run` and `audit-final.json`. Neither TLS verification nor network settings were changed.

Connectivity recovered; all four probes returned 200 at 2026-11-03 12:37:36 UTC. We then reran **all 120 cases with identical manifests/code in new output directories**, along with all 27 old-source controls. The following are intact results of that independent complete run, not a composite of multiple attempts:

| Cohort | Papers | Verified main | At least one SUPPLEMENT | Attachment workflow COMPLETED |
| --- | ---: | ---: | ---: | ---: |
| HAS_SUPPL:Y | 104 | 104 | 96 | 99 |
| HAS_SUPPL:N controls | 8 | 8 | 0 | 0 |
| Historical difficult | 5 | 5 reused | 0 | 0 |
| Historical successful regression | 3 | 3 reused | 3 | 3 |

All main texts: **112 VERIFIED, 8 EXISTING_VERIFIED**. SI: **102 COMPLETED, 4 NOT_FOUND, 12 FAILED, 2 INTERACTION_REQUIRED**. The metadata-positive workflow completion rate is 99/104 (95.2%), not manually confirmed SI completeness: COMPLETED concerns discovered files and can include only source-data/review roles. No attachments were registered for the eight controls, but most fallback pages were blocked, so this does not estimate a site-wide false-positive rate. Sampling remains OA/PMC and biomedical biased; 26 brand strata are not 26 independent companies.

Saved **218 attachments with 218 unique SHA-256 values**, across **17 extensions**: 193 SUPPLEMENT, 21 SOURCE_DATA, 3 PEER_REVIEW, 1 REPORTING_SUMMARY. Recomputed byte hashes and parent DOI/main-PDF/source-record checks all passed. No main-article reference-count shortfall was found among COMPLETED cases with readable current XML; nine independent XML queries were unavailable and eight historical cases had no such reference. Counts are not same-version or human scientific-content gold.

**At the same 100 MiB cap, the 27 problem cases yielded 8 old-source versus 24 new-source COMPLETED.** Representative real deliveries follow; all 27 records remain in the audit:

| Case | Same-cap old → new | Delivered result |
| --- | --- | --- |
| 017 IEEE | INTERACTION_REQUIRED → COMPLETED | Markup title; 1 PDF |
| 025 Biologists | Main EXHAUSTED → main VERIFIED, SI COMPLETED | Legacy PMC link; 1 PDF |
| 030 Wiley | PARTIAL → COMPLETED | 7 DOCX/MP4 files; empty placeholder diagnostic |
| 036 PNAS | FAILED → COMPLETED | Markup title; 1 PDF |
| 040 Taylor & Francis | PARTIAL → COMPLETED | 1 DOCX and 1 PNG, declared JPG; bytes unchanged |
| 041 SAGE | FAILED → COMPLETED | Markup title; 1 DOC |
| 050 PeerJ | FAILED → COMPLETED | 1 RAR, not extracted |
| 068 BMJ | FAILED → COMPLETED | Markup title; 2 PDFs |
| 076 PeerJ | FAILED → COMPLETED | 1 Python file, not executed |
| 082 Wiley | PARTIAL → COMPLETED | Empty-placeholder diagnostic; 1 DOCX |
| 085 Science | FAILED → COMPLETED | Markup title; PDF + ZIP |
| 093 SAGE | PARTIAL → COMPLETED | 2 DOCX files, one declared DOC |
| 102 PeerJ | FAILED → COMPLETED | Markup title; 1 XLSX |
| 103 Biologists | Main EXHAUSTED → main VERIFIED, SI COMPLETED | 1 PDF + 11 XLSX files |
| 104 Copernicus | FAILED → COMPLETED | Markup title; 1 PDF |

`028 ACS` originally saved PDF + three MPG files with another object returning 403. After recovery, the complete run obtained PDF + **four MPG files** through the official PMC manifest and COMPLETED; the earlier PARTIAL record was not changed. Copies registered through a different source manifest are new source records, not mislabeled reuse.

The five remaining incomplete metadata-positive cases are:

- `066 Taylor & Francis` and `069 IEEE`: network failure during file transfer after HTTP 200. Independent copied-library followups both COMPLETED, saving ZIP and MP4 respectively; the complete run retains FAILED, without folding followups into 99/104.
- `045 AIP` and `097 AIP`: current XML has no supplementary-material node; publisher fallback returns 403. The former's data statement requires contacting the author; the latter links to an XFEL dataset DOI. Neither directly supplies an SI file. HAS_SUPPL:Y is not main-SI gold, and the blocked publisher pages cannot establish absence of SI.
- `008 PLOS`: NOT_FOUND; extra DOC/DOCX belong to review subarticles and are not relabeled main SI.

Five historical difficult cases still lack SI: Wiley/RSC access refusal, no supported Springer entry, and unconfirmed MDPI/Elsevier page identity. Acquiring a new PMC main text is distinct from supplementing an existing main text from another source.

Five selected format/correction cases were tested on whole-library copies: **11/11 REUSED**, covering PNG, RAR, MPG, Python and DOCX. Every original library file and copied main/source record remained unchanged. Four known publisher-page regressions were also checked: Cambridge COMPLETED with one PDF, PLOS NOT_FOUND, one IOP data-page redirect rejected outside allowed file hosts, and another IOP verification challenge. No RSS was registered. These are specific regression checks, not general publisher-HTML availability evidence.

See the [machine audit](validation/si-native-corpus-20261103.json), [all-case CSV](validation/si-native-corpus-cases-20261103.csv), [new manifest](../benchmarks/si_publishers_20261103/native-current-manifest.json) and [old manifest](../benchmarks/si_publishers_20261103/native-baseline-manifest.json). Raw PDFs, attachments, receipts, HTTP, XML and stdout remain at `F:/AI4S/outputs/AN_SI_NATIVE_FIX_20261103/`: final complete runs in `recovered/run` and `recovered-baseline/run`, first interrupted-network run still in `current/run`. Full texts/media are not committed or historical results overwritten.

To reproduce, use matching product source and fresh output directories; source mismatches are rejected:

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/benchmark_si_publishers.py run --manifest benchmarks/si_publishers_20261103/native-current-manifest.json --output F:/AI4S/outputs/native-retest/run
python scripts/summarize_si_publishers.py --root F:/AI4S/outputs/native-retest
```

Restore the eight historical main-text paths locally first; report missing files rather than substituting placeholders or overwriting old outputs.

## Automated and installed-package checks

- 42 new cases cover markup titles, precise identity failures, placeholder boundaries, actual-format correction, invalid-format rejection, storage without execution, reuse/raw-source preservation, RSS/help exclusion and official legacy PMC URLs with wrong-DOI rejection.
- Full suite: **4178 passed, 148 skipped, 293.97 seconds**. [Output](validation/si-native-corpus-pytest.txt). Existing conditional skips are not claimed as executed tests.
- All 228 Python files in the wheel match `a65cc4b`; wheel SHA-256: `6b020cce18f7aec04ae0e6f984fd503dbfeb52a8012a2383ff2cdc1a9e227389`.
- Independently installed wheel, relevant native SI/PMC/integration tests from **C:/Windows/System32**: **107 passed, 2.76 seconds**. [Output](validation/si-native-corpus-installed-pytest.txt). This verifies installed-package paths and logic, not a manually launched GUI in this round.
- Ruff and Git whitespace checks passed. No merge or release.

## Acceptance

**The scoped native defect fixes meet merge conditions**: full regression, isolated installation, same-cap old-source comparison, 120-paper live run and format reuse checks are complete, without observed weakening of identity gates or file-integrity failures. Changes are pushed for review, without merge or release. The broader goal of complete SI acquisition across all publishers remains unfulfilled: five historical difficult cases and restricted-page fallback need further coverage. Universal native HTTP acquisition is not promised.
