# Cross-publisher, multi-format SI acquisition and integration

[中文](SI_PUBLISHER_COVERAGE.md)

The subsequent [120-paper benchmark](SI_SCALE_BENCHMARK_20261103.en.md) found generic-context misassociation and page/file confusion; merge is currently not recommended. This document retains the earlier small-cohort observations and assessment without extending them to broader acceptance.

2026-11-03, developed from `8c1c9ba` on `feat/si-publisher-coverage`; source version remains development 0.8.2. Generic discovery, difficult delivery adapters and main-acquisition integration extend the existing PMC, ACS Figshare and authorized-browser capabilities. **Generic support is not a guarantee that every publisher or article will deliver all SI automatically.**

## Implementation

- **Generic page semantics:** attachment containers, heading hierarchy, `aria-label`, explicit `data-href` buttons, existing attachment metadata/rel links and JSON-LD Article `associatedMedia`, `hasPart` and `supplementaryMaterial`. No script execution. Context parsing excludes pseudo-anchors in scripts/templates, navigation and footers; existing explicit script PDF URL extraction remains. Reference headings terminate inherited attachment context. Up to 4096 ordinary links and 256 discovered attachments, with explicit truncation. Late SI no longer disappears after the first 256 ordinary links.
- **Parent identity:** a sole matching page-level scholarly DOI remains mandatory. Top-level/@graph Article identifiers participate in the same conflict check; citations do not establish parent identity. Known publisher/CDN families remain constrained. Unknown publishers can establish an origin through an actual DOI-resolver redirect plus the matching sole DOI, then use same-host attachments only. Arbitrary repositories and cloud hosts are not globally authorized.
- **Supplement landing pages:** follow explicitly linked pages such as MDPI `/s1`, at most two pages and one level. Recheck DOI, origin and response completeness; retain article-to-landing evidence. Depth/count limits, login, identity conflicts and retrieval failures remain incomplete outcomes.
- **Difficult routes:** PLOS `article/file` checks `type=supplementary`, parent DOI and `.sNNN`; main/figure files and ambiguous parameters are rejected. Official PLOS corpus R2 delivery is bound to the exact parent, supplement identifier and filename on every redirect, rather than authorizing Cloudflare storage generally. Recorded RSC articlepdf routes gain same-DOI articlehtml/articlelanding candidates; Springer PDF sources gain article candidates. PNAS, Taylor & Francis and SAGE DOI supplement paths get parent checks; additional publisher/CDN relationships are recognized. `Client Challenge` is not interpreted as absent SI.
- **Extensionless and multiple formats:** link MIME, validated final URLs, a type-only hint from Content-Disposition, delivered signatures and ZIP/Office members determine file type. Remote filenames never become local paths or raw diagnostic fields. Added DOC/PPT, RTF, OpenDocument and GIF/GZIP support joins PDF, DOCX/XLSX/PPTX, XLS, CSV/TSV, text, chemical structures, images and applicable audio/video. Unknown formats, HTML responses, invalid containers and limits fail explicitly. Explicit unhandled formats do not silently count as complete coverage.
- **Main integration and multiple files:** the existing `AcquisitionService` invokes the shared SI service after main verification. Each file has independent storage, hash, parent association, receipt and status. One failure retains other successes. Checkpoint recovery reuses the main; successful SI becomes REUSED after source/hash checks, while failed items can retry. The default is 20 files, up to 100, with a separate byte cap; count truncation yields PARTIAL.

PDF SI remains DECLARED SUPPLEMENT, not VERIFIED main text or scientifically confirmed content. Only SUPPLEMENT PDFs enter existing parsing. Source data, peer-review files, reporting summaries and non-PDF files retain distinct roles. Applicable signatures/container checks do not validate scientific content. Archives are not extracted and files are not executed. No replacement acquisition engine, database change or new login permissions.

## Engineering fixtures and live delivery are separate

**95 new automated cases** include 27 page templates (including an independent unknown publisher), 14 extensionless-format responses, JSON-LD conflicts, long pages, reference/navigation exclusions, PLOS parameter/cloud-object binding, landing-page bounds, response filenames, multiple mixed files, partial failures, reuse and original preservation. These are synthetic fixtures, not 27 successful live publisher downloads.

Five cases use the real main acquisition engine and SI pipeline with fixture HTTP responses, without replacing either service:

| Scenario | Verified behavior |
| --- | --- |
| Complete main and SI | VERIFIED main plus PDF, XLSX and CSV; still one library article |
| One attachment returns login HTML | Other two retained; SI/task PARTIAL; main VERIFIED |
| Two-file limit | Two saved, truncation/PARTIAL retained |
| Main identity mismatch | Main not counted successful; no SI file request |
| SI disabled | Main only; no SI file request |

The first three also check that recovery does not request the main again, successful SI is REUSED and main/source bytes remain unchanged. Mixed-format storage checks independent receipts and library associations.

## Actual Windows network observations

Ordinary local Python 3.14 and public HTTP, without browser, paid models or account login. Existing articles use independent library copies; originals remain untouched. The PLOS integrated scenario acquires and verifies a new main through the existing engine; difficult samples retrieve SI only. Caps: 20 files, 25 MiB each, 15–20-second network timeout. See [machine-readable observations](validation/si-coverage-live-20261103.json) for source, size and hash details.

| Source/scenario | Previous version | This run |
| --- | --- | --- |
| PLOS `10.1371/journal.pone.0039704`, publisher page | NOT_FOUND, zero files | COMPLETED, 12 native HTTP files (7 XLS + 5 DOC); all REUSED on repeat |
| Same PLOS, version-bound PMC manifest | Retest PARTIAL, 7 files; DOC unsupported | Main-acquisition entry: main VERIFIED, SI COMPLETED, 12 files; checkpoint repeat resumed main and REUSED all 12 |
| ACS `10.1021/acsomega.6c02245` | Existing enhanced route succeeded | COMPLETED, one PDF; route preserved |
| Science `10.1126/sciadv.aeb1911` | Existing route succeeded | COMPLETED, one PDF |
| RSC `10.1039/d4cc01176g` | Historically restricted | FAILED, article HTTP blocked, zero files |
| Wiley `10.1002/cctc.202201687` | Historically restricted | FAILED, article HTTP blocked, zero files |
| Elsevier `10.1016/j.elecom.2022.107204` | Historically restricted | FAILED, article HTTP blocked, zero files |
| MDPI `10.3390/nano13050931` | Historically not delivered | FAILED, article blocked/timed out, zero files |
| Springer `10.1007/s11814-019-0365-0` | Historically not found | NOT_FOUND, no explicit attachment found; a separate HTTP probe returned Client Challenge, so absent SI is not established |

All 12 PLOS SHA-256 values match between this run's publisher and PMC routes, totaling **5,552,640 bytes**. The previous installed SI source matches `8c1c9ba`. Its first PMC attempt timed out on XML; a separate 20-second retest delivered seven files. The initial failure is retained. The new publisher route initially discovered 12 links but rejected unsupported PLOS cloud redirects; a separate retest after file-scoped delivery adaptation saved all files. Initial failures were not rewritten. Local originals/results: `F:/AI4S/outputs/AN_SI_COVERAGE_20261103/`.

PLOS file/hosting guidance is documented in its [official Supporting Information instructions](https://journals.plos.org/plosone/s/supporting-information). Cloud delivery matching follows actual official responses in this run, not a promise of permanent interface stability. This cohort does not establish a publisher-wide success rate or human scientific-content acceptance.

## Validation and delivery

Full suite: **4136 passed, 148 skipped, zero failures, 302.40 seconds**; see [full output](validation/si-coverage-pytest.txt). Skips retain existing browser-live, external OCR, system symlink-permission and other runtime conditions; they are not passes. The isolated wheel ran all new cases from `C:\Windows\System32`: **95 passed**, with the imported package location verified; see [installed tests](validation/si-coverage-installed-pytest.txt). All 228 packaged Python files match the worktree byte for byte. Wheel SHA-256: `217181e8ee9aba90fbd8ba5e3aff1eaf1430f14153f7ad61e3f1738ab42576de`. The validation wheel has not been published.

README, Chinese/English workbench guides and this report are updated; the earlier ACS cohort keeps its original measurements. Main files: `supplements.py`, new `supplement_markup.py`, `supplement_formats.py`, `supplement_pages.py`, `supplement_plos.py`, localized status/diagnostics and two test files.

Repository-wide Ruff, compileall, Git whitespace checks, changed-document local links and report assertions passed.

The change meets this round's code-merge conditions; it has not been merged or released. Remaining restricted sources require lawful session access or manual association; generic rules cannot guarantee delivery, and successful SI retrieval from every publisher is not claimed.
