# Native SI acquisition improvements and acceptance (2026-11-03)

[中文](SI_NATIVE_ACQUISITION.md)

Subsequent generic rules, multiple formats/files and main-acquisition integration have separate [cross-publisher observations](SI_PUBLISHER_COVERAGE.en.md). This document preserves the original ACS improvement cohort.

Developed from `1ac4e07` on `feat/si-native-reliability`. “Native” means built-in HTTP, structured manifests and page parsing, without model-invented links or manual assistant downloads. The source retains development version 0.8.2; this does not establish publication.

## Changes

The previous SI workflow used verified PMC manifests or explicit official article-page links. Missing anchors, blocked article HTTP responses or inconsistent PMC versions could prevent delivery; repeatedly opening a browser did not establish that a file had been saved.

This change reuses existing attachment storage, registration and PDF SI parsing:

- **Official ACS Figshare manifests:** when the existing PMC route finds no file, search public records by parent DOI. Check `resource_doi`, the complete parent title after removing HTML formatting, the publisher supplement DOI (parent DOI plus `.sNNN`), ACS record origin and numeric ID. Download only public, nonconfidential, nonembargoed files with explicit IDs, sizes and MD5 values.
- **HTTP delivery:** permit only the manifest's Figshare file ID and its matching ACS storage redirect/file name. This does not broadly authorize Figshare or Amazon hosts for other attachments. Check declared size, MD5, content SHA-256 and the existing format gate before parent registration.
- **Reuse:** matching the historical receipt's SHA-256 is insufficient; the current manifest's size and MD5 must also match. Changed manifests cannot silently reuse files because their URLs are unchanged. Old files are retained.
- **Official HTML:** recognize explicit `citation_supplementary_material`, `citation_supplementary_material_url` and `rel=supplement/supplementary`, with official-scope base URLs. The sole matching article DOI remains required; main PDFs and arbitrary external links are not treated as SI.
- **Direct-request compatibility:** supply the verified page Referer without query parameters, without copying browser cookies. Recorded Elsevier linkinghub PIIs can supply the corresponding ScienceDirect article candidate; this does not bypass access restrictions.
- **Chinese diagnostics:** identity conflicts, incomplete manifests, limits and failed size/checksum checks retain clear errors and explanations.

Implementation follows the [official Figshare article API documentation](https://docs.figshare.com/old_docs/api/articles/) and [API usage guide](https://info.figshare.com/user-guide/how-to-use-the-figshare-api/): exact `resource_doi` filtering through `POST /v2/articles/search`, followed by `GET /v2/articles/{id}`. Only public metadata is queried, without accounts or keys. The request sends a parent DOI, not paper content.

## Boundaries

The adapter applies only to `10.1021/` parents with meaningful titles. Explicit `page_urls` preserve directed-page behavior. Failures retain diagnostics and existing page fallbacks. No result is not evidence that SI does not exist. Original PMC version/identity checks remain intact.

Each invocation examines at most 10 records, with at most 64 files and a 2 MiB JSON response limit. Existing attachment-count and per-file byte limits remain active. Metadata requests do not follow redirects or carry credentials, and rate limiting does not trigger a loop of repeated calls. Unhandled portions remain visible instead of being counted as complete.

PDF SI remains **DECLARED SUPPLEMENT**, with official-manifest association evidence. Delivery, structural validity and parent association do not confirm scientific content. Archives are not extracted or executed. Other login, CAPTCHA and browser-delivery requirements retain their existing authorization boundaries.

## Actual comparison

Independent copies of existing verified main PDFs were used, without downloading mains again, modifying originals, starting browsers or calling paid models. The baseline SI source files were checked against public main `403514f`. Both versions used a 20-second network timeout, at most three attachments and 15 MiB per file.

| Parent DOI | Before | After | Observed delivery |
| --- | --- | --- | --- |
| `10.1021/acs.jpcc.4c00353` | FAILED | FAILED | No matching Figshare record; article HTTP blocked. No claim that the paper has no SI |
| `10.1021/acsomega.6c02245` | FAILED | COMPLETED | New native Figshare route: 2,111,935 bytes, 10 PDF pages; repeat REUSED |
| `10.1021/acsomega.6c08217` | COMPLETED | COMPLETED | Existing PMC route: 1,678,331 bytes, 11 PDF pages; repeat REUSED |
| `10.1021/ja0659323` | FAILED | COMPLETED | New native Figshare route: 354,191 bytes, 5 PDF pages; repeat REUSED |

Two additional papers delivered SI, and the existing successful route stayed successful. This four-paper sample is **not a publisher-wide success rate**. The older seven-publisher run recorded NOT_FOUND for the first ACS Omega paper; this run's pure-HTTP baseline was FAILED. Those represent different times/session conditions and are retained separately.

Successful-file SHA-256 values:

- ACS Omega `6c02245`: `160e997c0ab3a224afc9b4a2766b3b9ad84be8a921a38eb3d3c2ddea0ebcf9d7`
- ACS Omega `6c08217`: `788aab0dadfa13d3145d77134f249dc1ef6f20a6ec3a0783e07e899bd6cfe55d`
- JACS: `645b20a584f0e6330d22e4755a786abd6471355f13565e3f5daf815efb21d9ab`

The [machine-readable observations](validation/si-native-live-20261103.json) provide authoritative file checks. Full local files and separate initial, control and retest outputs are under `F:/AI4S/outputs/AN_SI_NATIVE_20261103/`.

## Automated checks and delivery

The 53 new tests cover parent/publisher/record identity, embargo/confidentiality, file IDs, paths, sizes and MD5, response and candidate limits, scoped redirects, original retention, reuse and manifest changes, existing HTML fallback, distinct attachment roles, explicit metadata, base URLs and query-free Referer. Together with existing Chinese-diagnostic checks: **97 passed**.

Final full-suite result: **4041 passed, 148 skipped, zero failures, 337.71 seconds**. The [complete output](validation/si-native-pytest.txt) preserves the original result. Existing conditional skips concern browser smoke tests, external OCR and system symlink privileges; skips are not passes.

The initial full run had 4040 passed, one failed and 148 skipped: seven new backend literal errors lacked Chinese explanations. The mappings were completed and the entire suite rerun successfully. The [initial failed run](validation/si-native-pytest-initial.txt) is retained; assertions were not changed to hide the issue.

The wheel was built and installed in an isolated directory. Running both new test files from System32 produced **53 passed**, with [installed-package output](validation/si-native-installed-pytest.txt) recorded separately. All 224 Python files in the wheel match the final checkout byte for byte. Wheel SHA-256: `36f5df2f4cf94a91ce0ab23f6ba8fb226fe4944801a55f18b2df7c1e8e99f925`. Ruff, compileall, Git whitespace checks, local documentation links and reported hashes passed.

Interface failures, synthetic fixtures and real delivery are recorded separately. No unperformed human or scientific-accuracy checks are counted as passes. The change meets code-merge conditions; one public route remains blocked, so complete SI coverage is not claimed.

Main changes: `workbench/supplement_figshare.py`, `workbench/supplements.py`, `workbench/messages.py` and two new test files. No database changes, replacement acquisition engine or new browser permissions.
