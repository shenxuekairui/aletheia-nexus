# Native SI acquisition for non-OA papers (2026-11-03)

[中文](SI_NON_OA_BENCHMARK_20261103.md)

Independent SI is now available through CLI/UI/MCP and this frozen corpus has been retested. See [independent SI acceptance, 2026-11-04](SI_INDEPENDENT_20261104.en.md) for the new official-hosting routes and actual failure-to-success cases. The baseline below remains unchanged; diagnostic delivery is not retrospectively counted as product success.

Earlier cross-publisher tests selected OA/PMC candidates to obtain main texts and XML references, introducing substantial selection bias. They cannot establish non-OA or universal SI coverage. This independent round tested **54 metadata-closed papers across 19 publisher/brand strata**, plus four known OA regression controls, with real network requests and no login, browser, paid API or model calls. Product source remains `6c7d587` (identical product code to `a65cc4b`); acquisition logic was not changed for these tests.

**Main-text and SI access must be measured separately.** Four papers lacked an acquired main text but anonymous native HTTP delivered their SI. The current integrated product workflow requires main verification first, so those papers succeeded only in the independent probe, not the normal workflow. No fake main PDF or product-success claim was introduced.

## Frozen protocol and scope

- [Manifest](../benchmarks/si_closed_20261103/manifest.json) SHA-256: `6b479b1f1c724ae9da929a6c3876256b57ce9fe94fe60e256a42e6d53bd53ef1`, frozen before article/SI delivery. No DOI was replaced based on outcome.
- Twenty prefix strata were planned. Take the first 40 Crossref journal-article records per prefix, published 2021-01-01 through 2026-06-30, sorted by publication date descending; exclude correction/retraction/obituary titles. Require an unambiguous OpenAlex DOI match, article/review type, `is_oa=false` and `oa_status=closed`. SHA-256 seeded ordering, distinct journals preferred, up to three papers per stratum. [Sampling evidence](../benchmarks/si_closed_20261103/sampling-evidence.json) preserves counts, ambiguity and source hashes.
- Science supplied two eligible papers, PNAS one, and none of the 40 Royal Society candidates met the rule: 54 papers and 19 nonempty strata. No OA substitutions were made; these gaps do not establish absence of non-OA papers in those publishing systems.
- Four exposed successful OA cases from the previous round check ordinary workflow/network behavior; they are not a holdout. Limited candidate pools, date ranges and metadata coverage prevent population-wide publisher estimates.
- Metadata-closed is not a manually audited entitlement status, and not every paper is known to have SI. Some article classifications may still cover commentary/news or papers without SI. **There is no independent human SI-positive gold set; dividing delivered papers by all 54 would not measure complete-SI success.**
- See [Crossref filter documentation](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/) and [OpenAlex OA definitions](https://help.openalex.org/data/works/open-access/). OpenAlex counts any payment/login-free full text as OA; closed covers other cases. Metadata can lag source conditions.
- Initial metadata requests partly failed, and OpenAlex returned duplicate DOI records. Those originals remain. Before delivery, bounded metadata retries and ambiguous-DOI exclusion produced the final freeze, reusing successful raw pools by hash without consulting SI outcomes. Earlier unmeasured manifests are not mixed into final scores.

## Separate measurements

1. **Normal product workflow:** shared AcquisitionService, public sources, browser disabled, SI after main verification, with unchanged identity/provenance/parent gates.
2. **Independent no-main SI probe:** reuse existing ACS Figshare, official DOI-page discovery, explicit attachments, allowed-host redirects, streaming transport and format validation. Require the manifest's parent DOI/title or sole DOI on the official page before requesting explicit files. No guessed filenames, JavaScript execution, account cookies, script execution or extraction. Files are saved unregistered without a parent PDF hash and are not claimed as parser-ready library attachments.

Separate processes/results; 100 MiB per file, 20 attachments, 20-second request timeout, 200 seconds per phase, four concurrent cases and 5 GiB disk budget. All 58 cases executed without time/budget skips. The independent probe is diagnostic, not a new product engine. Institutional login was not used, so entitled access was not evaluated.

## Complete outcomes

| Cohort | Papers | Main VERIFIED | Integrated SI COMPLETED | Independent delivery of SUPPLEMENT |
| --- | ---: | ---: | ---: | ---: |
| Metadata closed | 54 | 0 | 0; all 54 NOT_ATTEMPTED | 4 |
| Known OA controls | 4 | 4 | 4 | 1 |

Closed main outcomes: 51 EXHAUSTED, three AUTH_REQUIRED. None of the four successful independent deliveries used PMC:

| DOI | Publisher | Saved | Actual route |
| --- | --- | --- | --- |
| `10.1021/acsami.6c06732` | ACS | PDF, 2,329,969 bytes | Official ACS Figshare manifest → Figshare downloader → ACS S3 |
| `10.1021/acs.jpclett.6c01699` | ACS | PDF, 3,567,613 bytes | Same; exact parent DOI/title and official MD5 checked |
| `10.1007/s11056-026-10197-y` | Springer | DOCX, 15,210,079 bytes | DOI-confirmed article page → explicit static-content.springer.com attachment |
| `10.1007/s43450-026-00780-x` | Springer | PDF, 396,492 bytes | Same official explicit-link route |

Raw independent closed-probe outcomes:

| Outcome | Papers | Interpretation |
| --- | ---: | --- |
| Files delivered | 4 | Explicitly associated files delivered, not guaranteed complete SI or product registration |
| HTTP 403 | 34 | All AcquisitionAccessBlockedError. Source refused public HTTP in this environment; 403 alone cannot distinguish anti-bot/access causes or establish that SI requires payment |
| Identity unconfirmed | 6 | Three Elsevier, three IOP; page did not meet the sole-DOI gate, so no association/download |
| Login/challenge | 6 | Three Nature LOGIN, three IEEE CHALLENGE; no browser/account escalation |
| No supported entry found | 4 | Three Cambridge, one Springer; absence of SI is not established |

Per-stratum counts below refer only to delivered SUPPLEMENT, excluding main text, peer review and source data:

| Publisher/brand | Closed papers | Delivered SI |
| --- | ---: | ---: |
| Elsevier | 3 | 0 |
| ACS | 3 | 2 |
| RSC | 3 | 0 |
| Wiley | 3 | 0 |
| Springer | 3 | 2 |
| Nature | 3 | 0 |
| Science | 2 | 0 |
| OUP | 3 | 0 |
| Cambridge | 3 | 0 |
| Taylor & Francis | 3 | 0 |
| SAGE | 3 | 0 |
| BMJ | 3 | 0 |
| IEEE | 3 | 0 |
| IOP | 3 | 0 |
| AIP | 3 | 0 |
| APS | 3 | 0 |
| Royal Society | 0 | Not measured; no eligible pool candidate |
| Karger | 3 | 0 |
| Biologists | 3 | 0 |
| PNAS | 1 | 0 |

Among OA probes, ACS delivered one SI file. eLife saved nine SOURCE_DATA files with unresolved items and remained PARTIAL_DELIVERY; Wiley/Taylor & Francis pages returned 403. The ordinary product workflow completed main/SI for all four through its available archive routes. Page and archive availability differ; the two measurements cannot be added together.

## Checks, limits and remaining work

Independent probes saved 14 files: four closed, ten OA-control. Recomputed SHA-256/MD5 matches recorded downloads and applicable official manifests; Springer parents were rechecked against the saved HTML's sole DOI. Saved integrated attachments were rehashed and existing parent checks verified. **No byte/parent-evidence failures were found.** These are engineering checks, not human scientific-content confirmation or evidence against undiscovered attachments.

Remaining work:

- Support independent SI discovery/delivery in the product when main text is unavailable, with a truthful association state. This probe does not ship that capability.
- Improve official repository/API coverage, HTML intermediary handling, page identity and explicit attachment discovery. The 34 refusals do not mean all non-OA SI requires institutional access.
- Three earlier Royal Society review-only cases have explicit Figshare supplement references that native discovery does not follow. Same-version PMC XML and public Figshare `resource_doi` were checked; see the [inventory evidence](validation/si-royal-external-inventory-20261103.json). This is a discovery omission. Prior COMPLETED statuses/counts remain, without implying SI completeness. One ZIP is about 184 MiB, above the 100 MiB default. Metadata inventories are not counted as deliveries here.

Only test tools, frozen inputs and reports were added. Ruff, compilation, CLI, frozen classification/hashes, no-network recovery and all 58 real cases were checked. Product code is unchanged and its full suite was not rerun this round. Previous **4178 passed / 148 skipped** and installed **107 passed** remain prior-round evidence, not new executions.

**Decision: the public native non-OA test is complete; universal SI acquisition is unproven and does not meet broad feature acceptance.** This preserves earlier specific title/format regression fixes and does not relabel access problems as format defects. No merge or release.

## Evidence and reproduction

[Machine audit](validation/si-closed-20261103.json) and [all-case CSV](validation/si-closed-cases-20261103.csv) preserve all 58 cases. Raw APIs, HTML, PDFs, attachments, request statuses and phase stdout remain at local `F:/AI4S/outputs/AN_SI_CLOSED_20261103_final/`; earlier sampling/preflight artifacts are separate. Full texts/media are not committed.

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/benchmark_si_closed.py run --manifest benchmarks/si_closed_20261103/manifest.json --output F:/AI4S/outputs/si-closed-new/run
python scripts/summarize_si_closed.py --root F:/AI4S/outputs/si-closed-new/run
```

The runner checks product source. Use fresh directories to retain history. `scripts/sample_si_closed.py --output <new-directory>` resamples metadata, producing a new cohort that must not be mistaken for this freeze.
