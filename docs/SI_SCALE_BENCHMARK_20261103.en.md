# Live SI benchmark: 120 papers across publisher strata (2026-11-03)

[中文](SI_SCALE_BENCHMARK_20261103.md)

Completed **120 papers across 26 publisher/brand strata** against production commit `ada8b63`, using actual public network responses without changing acquisition code. **Merge is currently not recommended for the cross-publisher SI objective: confirmed RSS misassociation and page/file confusion should be fixed first.** The earlier small-cohort merge assessment does not extend to this broader acceptance protocol.

## Frozen protocol

The [manifest](../benchmarks/si_publishers_20261103/manifest.json) was frozen before acquisition, SHA-256 `a4fbd89422feeef92ed3c58b06d11a1f2c4e2eacd2ff74a0b8c90742c0011790`: 104 Europe PMC HAS_SUPPL:Y records (four per stratum), eight HAS_SUPPL:N controls and eight historical cases. Nature and Springer/BMC share a parent group; 26 strata are not 26 independent companies.

Selection used the first 40 core records for each DOI-prefix stratum, OA/PDF availability and 2021–2024 first-publication dates, fixed-seed SHA-256 ordering, preferring distinct journals. No acquisition outcomes were used to replace cases. This is a biomedical/OA/Europe-PMC-biased cohort, not a representative random sample of all publisher output. [Sampling fingerprints](../benchmarks/si_publishers_20261103/sampling-evidence.json) retain queries and local raw-pool locations. HAS_SUPPL includes reviewer histories, author responses and source data; it is not human gold for main-article SI.

The normal workflow acquired 112 new mains with integrated native SI; eight historical mains used independent copies for SI-only recovery. Each case then tested publisher DOI-page HTML discovery/delivery with PMC/Figshare manifest fallback explicitly disabled. The two cases lacking verified mains attempted page discovery only, without fabricated parent documents.

Windows Python 3.14.3, public HTTP, no browser, login or model calls. Limits: 20 seconds per request, 20 files, 16 MiB per file initially, 240 seconds per case, four processes. The primary run took 924.19 seconds and recorded 1512 HTTP requests including independent reference XML lookups. All 120 cases executed; no time/disk-budget skip. Two main failures subsequently encountered blocked page access recorded as EXCEPTION; they are not passes. API semantics follow [official Europe PMC REST documentation](https://dev.europepmc.org/RestfulWebService) and the [query reference](https://europepmc.org/docs/EBI_Europe_PMC_Web_Service_Reference.pdf). No local paper content was uploaded.

## Primary results

| Cohort | Papers | Verified mains | At least one SUPPLEMENT | Native attachment COMPLETED | HTML SUPPLEMENT papers | HTML COMPLETED |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HAS_SUPPL:Y | 104 | 102 | 84 | 77 | 9 | 3 |
| HAS_SUPPL:N controls | 8 | 8 | 0 | 0 | 0 | 0 |
| Historical difficult | 5 | 5 reused | 0 | 0 | 0 | 0 |
| Historical successful regression | 3 | 3 reused | 3 | 3 | 1 | 0 |

Native results include the product's trusted PMC/ACS Figshare routes. HTML results isolate DOI article-page rules and cannot be added to native results. COMPLETED means every discovered attachment was processed, potentially only reviewer files; it does not establish complete main SI or scientific-content correctness. Controls produced no registered SI, but most page fallbacks were blocked, so this is not a general false-positive-rate estimate.

The 104 metadata-marked records by stratum:

| Publisher/brand stratum | Papers | Mains | Native SUPPLEMENT | Native COMPLETED | HTML SUPPLEMENT | HTML COMPLETED |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Elsevier | 4 | 4 | 4 | 4 | 0 | 0 |
| ACS | 4 | 4 | 3 | 1 | 0 | 0 |
| RSC | 4 | 4 | 4 | 4 | 0 | 0 |
| Wiley | 4 | 4 | 4 | 2 | 0 | 0 |
| Springer BMC | 4 | 4 | 4 | 4 | 2 | 2 |
| Nature | 4 | 4 | 4 | 4 | 1 | 1 |
| Science | 4 | 4 | 3 | 3 | 0 | 0 |
| PLOS | 4 | 4 | 3 | 2 | 2 | 0 |
| MDPI | 4 | 4 | 4 | 4 | 0 | 0 |
| PNAS | 4 | 4 | 3 | 1 | 0 | 0 |
| Frontiers | 4 | 4 | 3 | 3 | 0 | 0 |
| OUP | 4 | 4 | 4 | 4 | 0 | 0 |
| Cambridge | 4 | 4 | 4 | 4 | 4 | 0 |
| Taylor Francis | 4 | 4 | 4 | 3 | 0 | 0 |
| SAGE | 4 | 4 | 3 | 2 | 0 | 0 |
| BMJ | 4 | 4 | 3 | 3 | 0 | 0 |
| IEEE | 4 | 4 | 3 | 3 | 0 | 0 |
| IOP | 4 | 4 | 3 | 3 | 0 | 0 |
| AIP | 4 | 4 | 2 | 2 | 0 | 0 |
| APS | 4 | 4 | 4 | 4 | 0 | 0 |
| eLife | 4 | 4 | 4 | 3 | 0 | 0 |
| Karger | 4 | 4 | 4 | 4 | 0 | 0 |
| Royal Society | 4 | 4 | 1 | 4 | 0 | 0 |
| PeerJ | 4 | 4 | 1 | 1 | 0 | 0 |
| Biologists | 4 | 2 | 2 | 2 | 0 | 0 |
| Copernicus | 4 | 4 | 3 | 3 | 0 | 0 |

Of the metadata-marked cohort, 87 papers delivered some attachment and 84 included SUPPLEMENT. Across all cases, native delivery saved 176 records (152 SUPPLEMENT, 20 SOURCE_DATA, three PEER_REVIEW, one REPORTING_SUMMARY); HTML saved 44 records including two misclassified feeds. The 220 saved records represent 181 distinct SHA-256 values, not 220 distinct files. Recomputed SHA-256 and parent DOI/PDF/source hashes found **no integrity or parent-record failures**. Semantic misassociation can pass those checks and is audited separately.

Actual native extensions included PDF, DOC, DOCX, XLS, XLSX, PPTX, ZIP, MP4, JPEG, GIF and CIF, with multiple files per paper. Of the verified mains, 113 came from PMC and five from other real sources; two mains failed. This distribution does not establish broad publisher-page availability.

## Separate byte-limit and reuse diagnostics

Seven cases affected by the initial 16 MiB cap were retested at the product default of 100 MiB, retaining the 20-file/20-second limits and verified mains in independent libraries. This post-hoc group is not a new holdout, and its results do not replace primary scores.

| Case | First pass | 100 MiB retest | Files | Files over 16 MiB |
| --- | --- | --- | ---: | ---: |
| 030-Wiley | PARTIAL | PARTIAL | 7 | 2 |
| 054-ACS | PARTIAL | COMPLETED | 2 | 1 |
| 062-PNAS | PARTIAL | COMPLETED | 4 | 3 |
| 073-eLife | PARTIAL | COMPLETED | 16 | 1 |
| 080-ACS | FAILED | COMPLETED | 3 | 3 |
| 086-PLOS | PARTIAL | COMPLETED | 5 | 1 |
| 088-PNAS | PARTIAL | COMPLETED | 3 | 1 |

Six became COMPLETED. Wiley remained PARTIAL: all seven explicit files saved, with a remaining missing-link-node diagnostic. Forty records saved, twelve larger than 16 MiB, adding MOV/TIF coverage. Cap-triggered failures should not be attributed to publisher capability alone.

Seven successful cases selected post hoc for extension coverage passed **44/44 REUSED**, spanning all eleven initial native extensions. Byte/parent checks and main/source preservation passed. All 100 MiB/reuse mains and source records remained unchanged; old attachments were not overwritten. See [follow-up observations](validation/si-scale-followup-20261103.json).

## Findings and reference-audit correction

1. **Confirmed generic-context misassociation:** IOP cases 018 and 044 saved journal RSS 1.0/RDF feeds as PEER_REVIEW. Feed namespaces, URLs and hashes are in the [machine audit](validation/si-scale-observations-20261103.json). They are not correct research attachments. Broad review context also requests site help/sign-in pages; context boundaries and file evidence need tightening.
2. **Page/file confusion:** PLOS 008 treats the HTML peerReview page as a file and emits attachment_type_not_confirmed. IOP `/data` also exposes a landing-page gap. Identify/follow bounded directories or report unsupported navigation; HTTP 200 does not establish file delivery.
3. **Unsupported formats:** ACS 028 has four MPG videos; PeerJ 050 has RAR and 076 has Python code. They are not saved, while successful supported files remain. Extend bounded storage based on actual formats without executing scripts or extracting archives; retain incomplete coverage.
4. **A source extension/content mismatch:** Taylor & Francis 040's `.jpg` starts with PNG bytes, confirmed in a separate bounded request. Rejecting its declared JPEG format is conservative behavior. [Header evidence](validation/si-scale-image-header-20261103.json) is not counted as successful acquisition.
5. **Identity/version and access constraints:** some IEEE, PNAS, SAGE, BMJ and Science records fail PMC identity/version/OA checks, with blocked page fallback. Do not relax those checks for a higher score. Two Biologists mains failed; all five historical difficult cases still lack SI. Newly acquiring a PMC main does not demonstrate SI recovery for an older main from another origin.
6. **The preliminary PLOS missing-SI interpretation was corrected:** 008's DOC/DOCX files belong to aggregated-review-documents and author-comment sub-articles. Extra 034/060 entries also belong to author responses. Original unscoped XML counts remain; final analysis adds main/sub-article scope. After excluding these, no COMPLETED native case had fewer saved records than main-article supplementary-material hrefs. This is still neither same-version nor human scientific gold. Excluding reviewer sub-articles in the native path was correct.

## Reproduction and delivery

The [per-case CSV](validation/si-scale-cases-20261103.csv) and [complete machine summary](validation/si-scale-observations-20261103.json) retain all 120 results, including failures/exceptions. Actual files, receipts, per-request HTTP records, XML, script fingerprints and stdout remain under `F:/AI4S/outputs/AN_SI_SCALE_20261103/`; full text/media are not committed.

Run with unchanged production source and a fresh output directory:

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/benchmark_si_publishers.py run --manifest benchmarks/si_publishers_20261103/manifest.json --output F:/AI4S/outputs/si-scale-rerun/run
python scripts/summarize_si_publishers.py --root F:/AI4S/outputs/si-scale-rerun
python scripts/benchmark_si_followup.py --root F:/AI4S/outputs/si-scale-rerun
```

The manifest includes local paths for eight historical mains. Restore their genuine source files for another machine; missing inputs must be reported rather than replaced by placeholder mains. Public API/network state changes require separate runs. The executed runner hash is in sampling evidence. Committed tools subsequently gained source-equivalence, resume and concurrent accounting protections; production source and primary outputs were not rewritten.

This round adds live tools, frozen data and Chinese/English documentation only. Ruff, script compilation, CLI argument checks and no-network recovery of completed output passed. The full product suite was not rerun for test-tool/documentation changes. The previous 4136 passed/148 skipped remains an earlier result, not new evidence from this round.

**Acceptance: large-scale testing is complete; cross-publisher generic SI acceptance has not passed. Fix confirmed misassociation and page/file distinction, then run a separate comparison on the same frozen cohort. Format and trusted-entry expansion remain additional work.** No merge or release.
