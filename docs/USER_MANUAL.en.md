# 溯光 · Aletheia Nexus User Manual

[中文](USER_MANUAL.md) · Chinese is the primary document; this is its complete section-by-section English counterpart. Commands and example data are reproduced unchanged, including Chinese placeholders.

This manual covers the **integrated v0.8.1 version**, including the graphical workbench, natural-language CLI, and local stdio MCP. Official release status is determined by [GitHub Releases](https://github.com/shenxuekairui/aletheia-nexus/releases) and [PyPI](https://pypi.org/project/aletheia-nexus/); a version number in source does not establish that a package has been uploaded.

For everyday use, start with the [workbench manual](WORKBENCH_USER_GUIDE.en.md), [natural-language and MCP guide](V08_ENTRYPOINTS.en.md), and [v0.8 research-task guide](V08_USER_GUIDE.en.md). `research run/export/revise`, DeepSeek configuration, custom fields, original-page checking, result reuse, and revisions use the same research engine. New natural-language and workbench tasks default to reading sources before assembling results; saved tasks that omit the strategy retain the original direct-extraction behavior. Quality and release status are documented separately in the [scientific acceptance record](V08_ACCEPTANCE.md), [ten-paper comparison](V08_TEN_PAPER_COMPARISON.en.md), [integrated release checks](V08_RELEASE_ACCEPTANCE.en.md), and [v0.8 release notes](RELEASE_NOTES_v0.8.1.en.md). Passing engineering tests does not confirm scientific content.

The following acquisition, verification, parsing, and local-library CLI instructions are retained from **v0.7.2** for researchers obtaining, verifying, organizing, and parsing papers. AN connects DOI/bibliographic input to local PDFs and source records, then to searchable, exportable structured content. It supports papers without DOIs, local registration, PDF supplements, cross-paper search, and result-based export. See the [0.7.2 research workflow](V072_RESEARCH_WORKFLOW.md) for routine operations and the [README](../README.en.md) for first use. The [v0.7.2 release notes](RELEASE_NOTES_v0.7.2.md) and section 10 preserve their historical context; they are not the current v0.8 release gates.

AN obtains files through public routes, authorized official APIs, and the user's own browser session wherever possible. A file is marked `VERIFIED` only after PDF structure, paper identity, and main-text role checks pass. AN does not provide subscriptions or enter passwords, MFA responses, or CAPTCHAs for the user.

See the [practical research acceptance report](V072_PRACTICAL_ACCEPTANCE.md) for parsing capabilities and quantitative limits. The emphasis is on numbers, units, metrics, their associated conditions, search, and checking original pages; complete graphical reconstruction is not a hard requirement. Small chemical formulae inside figures still require checking, and genuine conflicts in the source are retained separately. `PARSED` is a parsing status, not confirmation that all experimental data are correct.

## 1. Environment and installation

Python 3.11 or later is required. Windows PowerShell example:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install aletheia-nexus
aletheia-nexus doctor
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir downloads/first-paper
```

Public HTTP routes do not require browser dependencies. A single DOI with `--public-only` is suitable for an initial trial; when external sources cannot supply a trustworthy main text, AN reports a non-success status. For interactive browser access, additionally run `python -m pip install "aletheia-nexus[browser]"` and `python -m playwright install chromium`. Developers can run `python -m pip install -e ".[dev,browser]"` from the repository root. A GitHub Release alone does not prove that PyPI upload succeeded; check the target version on PyPI. Keep output outside the repository to separate code and downloaded files. DOI services, metadata services, and publishers require network access; institutional access remains subject to publisher policy and the current account. The browser uses a separate persistent profile that may contain login state. Protect it as account information and do not commit or share it.

## 2. Preparing a paper list

Batch commands accept three input forms:

- `.txt`: one DOI per line; blank lines and lines beginning with `#` are ignored.
- `.json`: a list of DOI strings or bibliographic objects; each object must provide at least `doi` or `title`.
- `.csv`: `doi` / `title` columns, optionally with `authors`, `journal`, `year`, `volume`, `issue`, `pages`, and `cnki_id`. JSON authors are a list; CSV authors are separated with ASCII semicolons.

Supply an accurate title for difficult papers. It helps AN distinguish main text, supplementary material, and links to the wrong paper, especially when the PDF does not print a DOI, extracted title text is damaged, or an existing file is being imported.

Classified inputs additionally support `folder` (relative to the output root), `filename` (an optional custom name), and `tags` (a JSON list or semicolon-separated CSV values). Default filenames follow “year-journal-title”, followed by short identity and content hashes. Missing fields are omitted rather than invented; existing files are not renamed in bulk. Use `aletheia-nexus library DIR --folder 分类 --tag 标签` to list them and `aletheia-nexus library tag PAPER.pdf --add 已阅读` to change independent tags. Tags do not rewrite acquisition or parsing evidence; damaged tags produce a warning without hiding the paper. See the [classified-input example](../examples/classified-papers.json).

```json
[
  {"doi": "10.1021/example", "title": "The Exact Article Title"},
  "10.1038/example"
]
```

For real DOI-only input, see [`benchmarks/user_20260923_20_with_titles.json`](../benchmarks/user_20260923_20_with_titles.json), with explicit titles for only two papers. For repeatable acquisition-layer testing, use [`benchmarks/user_20260923_20_frozen.json`](../benchmarks/user_20260923_20_frozen.json). `publisher` is benchmark metadata; `year` remains a bibliographic constraint. Neither is an access credential. DOIs are normalized. Bibliographic requests are deduplicated and resumed using all constraints, so the same DOI with different titles is not merged. Use `--keep-duplicates` to retain exact duplicates. See [`benchmarks/README.md`](../benchmarks/README.md).

## 3. The common batch workflow

The commands below process papers sequentially in a visible browser. If login, MFA, or a CAPTCHA is detected, AN pauses on the page and resumes after the user completes it. Without `--interaction-timeout`, there is no preset waiting limit.

A debugging port is normally unnecessary: run `aletheia-nexus acquire dois.json --output-dir downloads/my-batch`. The normal launch mode uses a dedicated AN profile, follows system proxy settings, and preserves the window and authentication after the client exits. Explicitly choose `--direct-connection` to bypass the browser proxy. You can close that AN window after the task and reuse the same profile next time. Use `--browser-launch-mode managed` when AN should own the window lifecycle. The following CDP example is for users who specifically need to attach to a local debugging port.

```powershell
aletheia-nexus acquire dois.json `
  --output-dir downloads/my-batch `
  --cdp-endpoint http://127.0.0.1:9222 `
  --cdp-navigate
```

When the selected local endpoint is not running, the CLI starts a dedicated Edge/Chrome with a persistent profile and opens the papers in sequence. Valid cookies and institutional authentication can be reused in the same session; AN does not read, print, or write cookie values. `--cdp-navigate` navigates for each batch item; without it, AN first attempts to attach to an already-open matching paper tab. Newly launched dedicated browsers follow the system proxy by default and connect directly when no proxy is configured. `--direct-connection` explicitly bypasses the browser proxy; `--browser-use-system-proxy` explicitly selects system settings. These options are mutually exclusive and affect only newly launched AN browsers. An attached external CDP browser retains its own network settings.

On Windows, if AN's Playwright browser repeatedly encounters verification while ordinary Edge opens the same paper, first try the following dedicated Edge route with a **single DOI**. Keep the final proxy-selection option only if you trust the current system proxy:

```powershell
aletheia-nexus acquire 10.1039/D6TA02244H `
  --output-dir downloads/edge-check `
  --profile my-institution `
  --cdp-endpoint http://127.0.0.1:9222 `
  --cdp-navigate `
  --browser-use-system-proxy `
  --interaction-timeout 180
```

AN starts a separate Edge if that local port is free, without changing your everyday Edge. If a browser already owns the port, AN attaches to that session; first confirm it is the intended AN browser. Bind debugging ports only to localhost and close the dedicated browser afterward. This does not bypass CAPTCHAs or guarantee publisher access.

Persistent downloading requires Chromium/Edge/Chrome >=155. Versions 152–154 have an upstream crash involving historical download objects; AN refuses to begin downloads rather than clearing profile data or history. On Windows/Linux x64, `aletheia-nexus browser-install` installs official Chrome for Testing into AN's separate directory without requiring the source checkout; old scripts remain compatible. Windows prefers a supported stable Edge/Chrome >=155, otherwise the separate runtime; headless operation is supported. `--executable-path PATH` selects a fixed runtime and cannot be combined with `--channel` or CDP. The default batch profile is `human-handoff` under `.aletheia-nexus/browser-profiles/` in the user's home. Use different `--profile NAME` values for institutions, accounts, or browser engines; `--profile-root DIR` changes the location. **Changing `--profile` alone does not switch an already-running CDP browser's actual profile.** Do not upload dedicated profiles. New sessions follow the system proxy by default; explicit `--direct-connection` does not change an attached external browser. AN does not switch modes within a task. A normal launch that finds an existing AN window in another mode fails clearly: close that dedicated window first or explicitly keep its mode. System mode does not freeze later OS proxy/VPN changes.

For unattended operation without waiting for login or CAPTCHAs:

```powershell
aletheia-nexus acquire dois.txt `
  --output-dir downloads/unattended `
  --non-interactive
```

`--non-interactive` **does not disable browsers or official APIs**. Existing authorized sessions may be reused, and a browser may open automatically; only waiting for human input is disabled. Unattended operation does not bypass login. AN records the relevant status when a site requires an account, subscription, or verification. An unrecognized access notice may instead result in `EXHAUSTED`; inspect diagnostics. Add `--fail-on-unverified` if an enclosing script requires every input item to be verified.

When an OpenAlex candidate contains a PMC record, AN first checks the official PMC Article Datasets AWS public bucket and prioritizes validating its PDF. This route accommodates PMC's distribution migration completed in August 2026; it does not scrape article pages or depend on the retired OA Web Service. Objects are rejected as candidates when outside an automatically retrievable dataset, missing a PDF, withdrawn, or inconsistent with the DOI metadata.

The normal acquisition workflow also supports an on-demand Crossref fallback. Only after public routes, official APIs, publisher browsing, and applicable CNKI routes have not obtained the paper does it check registered full-text/resource links. Existing metadata for this paper is reused first. If metadata has not been requested and automatic metadata is allowed, at most one additional Crossref request is made; a failed metadata lookup is not repeated here. The fallback does not run after success, while login/CAPTCHA is pending, after a download has started, or while an unverified file is retained. It tries at most four previously unvisited links within the remaining browser-route budget; it does not replace candidates or reorder the existing routes. XML/plain-text interfaces and similarity-check-only links are not PDF candidates. A link is not evidence of open access; the same access and main-text checks apply. `--public-only` retains its existing public workflow and does not start this browser fallback.

### Common options

| Option | Purpose |
| --- | --- |
| `--output-dir DIR` | Store PDFs, per-paper records, checkpoints, and batch reports. |
| `--cdp-endpoint URL` | Connect to a local AN browser debugging endpoint. |
| `--cdp-navigate` | Navigate per batch item rather than forcing reuse of the current tab. |
| `--profile NAME` / `--profile-root DIR` | Isolate and retain browser state for an institution or account. |
| `--no-start-browser-if-needed` | Do not start Edge/Chrome automatically if the local CDP endpoint is unavailable. |
| `--browser-use-system-proxy` | Explicitly follow OS proxy settings, also the default for a new browser; do not change system settings. |
| `--direct-connection` | Explicitly bypass the browser proxy; alias `--browser-direct-connection`. Mutually exclusive with system proxy selection and fixed within the task. |
| `--interaction-timeout N` | Wait at most N seconds for login/verification; omission means continued waiting. |
| `--stop-on-interaction` | Stop the batch if the current DOI still needs interaction; otherwise continue with later items. |
| `--non-interactive` | Do not wait for human login or CAPTCHA handling. |
| `--no-resume` | Ignore checkpoints and retry all inputs. |
| `--local-pdf DOI=PATH` | Import an existing PDF and repeat full verification; repeatable. |
| `--manual-ieee-fallback` | After automatic IEEE acquisition fails in an interactive terminal, request the path to a PDF saved by the user. |
| `--keep-unverified` | Keep PDFs that fail main-text identity verification for diagnosis. |
| `--fail-on-unverified` | Exit nonzero if any input is not `VERIFIED`, including no-DOI and invalid inputs. |
| `--unpaywall-email EMAIL` | Provide a contact email for applicable open-access discovery. |
| `--cnki` / `--no-cnki` | Enable/disable the CNKI browser provider; enabled by default. |
| `--cnki-all-titles` | Try CNKI for all unobtained papers, including those with only an English metadata title. |
| `--cnki-max-results N` | Maximum CNKI title/author matching candidates; default 20. |
| `--no-cnki-refresh-retry` | Disable CNKI's default single recovery refresh; other sources gain no automatic refresh. Active downloads, denied permissions, identity conflicts, and human authentication are not blindly retried. |
| `--browser-launch-mode auto/normal/managed` | `auto` defaults to normal launch for visible browsing and managed for headless; `normal` explicitly chooses normal launch. |
| `--source auto/cnki/exclude_cnki` | Automatic routing, CNKI-only, or excluding CNKI; default auto. |

Resumption checks hashes of both the PDF and acquisition sidecar. A legacy checkpoint without a sidecar hash causes reacquisition rather than being accepted as verified. If the same verified PDF is obtained again, AN preserves its first acquisition record to protect existing parsing evidence. Damaged records or identity conflicts are not silently overwritten.

Run `aletheia-nexus acquire --help` for all options; `scripts/batch_v06_download.py` remains a compatibility entry point. For slow sites, consider increasing `--base-timeout`, `--request-timeout`, `--max-source-routes`, or `--max-pdf-candidates`. Larger budgets extend runtime but cannot create subscription rights.

## 4. Login and institution selection

1. AN opens a visible paper/PDF browser page.
2. The user completes institution selection, login, MFA, or CAPTCHA in that browser.
3. AN observes the page without actively refreshing in the waiting loop. After a challenge disappears, availability must remain stable for several checks. AN first reads the PDF/download already received by the browser; only if necessary does it make one bounded retry of the same target, then continue.

Publishers such as Elsevier may suggest an institution from the network IP and repeat institution selection even with the same browser profile. If the suggested institution lacks that journal, switch using the publisher's own interface. AN does not change the system proxy or impersonate an institution. Cookies after a successful switch may be reused but are not guaranteed to remain valid.

If you confirm that no subscription is available, close the current challenge page or set a finite `--interaction-timeout N`. The DOI may finish as `INTERACTION_REQUIRED`, with later items continuing by default. Record the human conclusion “no entitlement” separately; incomplete login must not automatically become `ENTITLEMENT_REQUIRED`. `Ctrl+C` interrupts the entire command: checkpointed papers can be reused next time, but this run's full `batch-report.json` may not be updated. AN may automatically classify `ENTITLEMENT_REQUIRED` only when the publisher explicitly displays a purchase/no-entitlement page.

IEEE DOIs use the same browser workflow. When a remembered “Access Through …” institution button appears, AN attempts to click it, waits about five seconds, and retries the PDF. Passwords, MFA, and other human verification remain the user's responsibility. Every file undergoes the same main-text verification.

### CNKI

After public sources and applicable official APIs fail, the browser provider tries CNKI for papers whose metadata title contains Chinese. It reuses Crossref/DataCite titles and authors, searches by title, uses authors to help rank matches, captures new detail tabs, and selects only explicit PDF controls. CAJ links are not saved as PDFs. Downloads must pass the common PDF-structure and DOI/title identity checks. Successful sidecars record `cnki_authenticated_browser`, the source page, and SHA-256, without cookies or credentials.

Defaults do not send every foreign-language paper to CNKI. To expand the scope explicitly or disable it, use the Python API configuration:

```python
BrowserAccessConfig(
    cnki_enabled=True,
    cnki_search_all_titles=True,  # 默认 False，仅自动处理中文标题
    cnki_max_results=5,
)
```

For a CNKI slider or CAPTCHA, AN does not answer it or simulate dragging. A visible browser waits for the user and reports `CAPTCHA` through `interaction_callback`. Timeout or disabled interaction yields `INTERACTION_REQUIRED`. PDF availability remains subject to campus networking, institutional VPN, the session, and subscriptions; CAJ-only or no PDF permission is not reported as success.

You can also run `python scripts/download_cnki.py --doi "10.16560/j.cnki.gzhx.20230412"`, or use `--title "论文标题" --author "作者"`. Title mode obtains the real DOI from the detail page or PDF first page and does not invent an identifier if no unique DOI exists. Visible browsing waits for human authentication by default and then resumes. See [CNKI automated acquisition](CNKI_AUTOMATION.md) for API/batch parameters, errors, and offline checks.

CNKI normally clicks the actual PDF control natively in a supported browser and captures the attachment/PDF response, preserving page scripts, the network stack, and institutional state. `--cnki-context-request` explicitly selects an HTTP request with the same cookies; this is not the native browser network stack and is not an authentication bypass. An institutional-IP transition page is not treated as a personal-login requirement merely from its title. The dedicated CNKI CLI accepts repeated `--doi` values in one session. After the batch returns, interactive mode leaves the window open until it is closed or Ctrl+C is pressed, without downloading again. `--no-keep-browser-open` restores automatic cleanup. Noninteractive mode and temporary Python API calls clean up resources they own.

The default CNKI paper interval is **five seconds**. Within one browser session, timing starts when the preceding CNKI acquisition ends, and the next paper waits only for the remaining interval. The first paper, local import, and checkpoint reuse add no delay; other sources are unaffected. Both the unified CLI and CNKI script accept `--cnki-paper-interval 10` for ten seconds, or `0` to disable it. The Python API is `BrowserAccessConfig(cnki_paper_interval=10)`; batches must reuse `BrowserSession`. The interval must be finite and nonnegative.

Failed acquisition also counts toward the interval. Browser-context reconnection before download must wait as well. Once a download transaction has started, reconnection or a batch retry does not repeat it.

An explicit CNKI “too frequent” notice or HTTP 429 stops later dedicated CNKI acquisition in that session as `CNKI_RATE_LIMITED`; AN does not retry automatically at the paper interval. Start a new run after the limit is lifted. Five seconds is AN's default pacing, not a universal limit published by CNKI.

## 5. Resumption and file verification

Each batch writes this layout:

```text
downloads/my-batch/
  <年份-期刊-标题>--<身份短码>-<文件哈希短码>.pdf
  json/
    batch-checkpoint.json
    batch-report.json
    <年份-期刊-标题>--<身份短码>-<文件哈希短码>.acquisition.json
```

Missing bibliographic filename components are omitted; a missing title falls back to the identifier. With `folder`, PDFs go to that category and acquisition/tag JSON files to its `json/`; reports and checkpoints default to the root `json/`. Explicit `--report`/`--checkpoint` paths remain respected. Existing files are not moved or renamed in bulk: parsing, the library, and resumption support old locations and keep old checkpoints in place.

Running the same command reuses a `VERIFIED` file only when both PDF and source record exist and both SHA-256 values match the checkpoint. Legacy checkpoints without source hashes trigger reacquisition; other non-success states are retried. Renaming an unverified PDF cannot make the checkpoint trust it. A successful `.acquisition.json` records source, structure, DOI/title match, and main-text/supplement judgment, while redacting short-lived signed URLs. Checkpoints do not store cookies, tokens, URLs, or exception messages.

`batch-report.json` lists each paper's `status`, `verified_path`, `resumed`, and safe diagnostics. `status_counts` describes this single run. To combine independent retests as a corpus, deduplicate by DOI while preserving every run report; individual retests must not be presented as a single complete batch.

Exit code `0` means normal batch processing ended, **not that every paper is `VERIFIED`**. Code `2` means at least one `RUNNER_ERROR`; `3` means the batch paused at an interaction under that configuration; `4` means `--fail-on-unverified` found any input item below `VERIFIED`, including an invalid DOI; `RUNNER_ERROR` and paused states still take precedence as `2` and `3`. Inspect the item report: neither the exit code nor filename establishes verified literature identity, let alone scientific correctness.

### Interpreting statuses

| Status | Meaning and next step |
| --- | --- |
| `VERIFIED` | A readable PDF passed target-identity and main-text-role checks. |
| `INTERACTION_REQUIRED` / `AUTH_REQUIRED` | Login, institutional authentication, MFA, or CAPTCHA is needed/incomplete; complete it and resume. |
| `ENTITLEMENT_REQUIRED` | The publisher explicitly reports no main-text entitlement for this session; retry with an authorized account. |
| `ACCESS_DENIED` | Explicit site rejection/blocking; inspect site status and normal access conditions. |
| `EXHAUSTED` | Tried routes did not yield verification; not equivalent to no entitlement. Inspect `diagnostics`. |
| `BROWSER_UNAVAILABLE` | Browser startup, connection, or debugging connection failed/timed out. |
| `UNSAFE_URL` / `INVALID_DOI` | URL violates safety constraints or DOI input is invalid. |
| `RUNNER_ERROR` / `ERROR` | Program/per-paper workflow error; retain the report and reproduce it. |
| `DEFERRED` | Later DOI not processed after stopping at an interaction. |

`RETRIEVED_UNVERIFIED`, `SUPPLEMENT`, `INVALID_PDF`, and similar per-paper diagnostics are not successful files. A free supplement for the same DOI cannot replace main text. AN's first-page title rules tolerate titles joined together by PDF extraction. A DOI found only on later pages without a matching first-page title does not earn `VERIFIED`.

## 6. Existing PDFs and official APIs

Import a lawfully obtained PDF with `--local-pdf "DOI=C:\path\paper.pdf"`. AN copies and reverifies it without modifying the original. If the PDF does not print its DOI, also provide an accurate `title` in JSON/CSV; otherwise insufficient identity evidence may leave it unverified.

The Elsevier Article Retrieval API is optional. Supply credentials only through environment variables, not commands, source, or reports:

```text
ELSEVIER_API_KEY
ELSEVIER_INST_TOKEN      # 可选
ELSEVIER_BEARER_TOKEN    # 可选
```

Public routes and authorized browser sessions remain usable without these keys. `--no-elsevier-api` disables API autodiscovery. AN does not bypass subscriptions, CAPTCHAs, or access controls.

## 7. Source-linked parsing from v0.7

The parser accepts `VERIFIED` main text with an existing `.acquisition.json`, or local PDFs explicitly registered using `import`. Papers without DOI use the registered title and local identity; SI must be associated with a separate main text. Before running, AN rechecks the record, role, PDF SHA-256, readability, and page count. `--doi` is an optional consistency check and does not create a DOI:

```powershell
aletheia-nexus parse downloads\paper.pdf --doi 10.1234/example
```

The default `.parsed.json` output is alongside the PDF with the same stem; the PDF and acquisition sidecar remain unchanged. Use `--sidecar`/`--output` for explicit paths. An existing output conflicts by default; only explicit `--overwrite` replaces it. Batch/CI callers rejecting degraded output can add `--fail-on-partial`. An input-gate failure exits `5`; `PARTIAL`/`FAILED` with that option exits `6`.

New output uses `aletheia-nexus/parsed-document/v3`; v2 remains readable. v3 adds nullable DOI, title, identity basis, document role, and SI parent identity. The unpublished v1 draft is not a compatibility commitment. Canonical artifacts retain path-independent source/parsed `artifact_id`, source DOI/hash, pipeline/backend versions, configuration/execution fingerprints, MediaBox/CropBox/rotation, quality coverage, sections, merged paragraphs, structured references, figure/table evidence, and cells. Blocks use the common `pdf-cropbox-display-bottom-left-normalized/v1` page/bbox convention and text spans. Machine-specific absolute paths are excluded; safe relative locators are only for reverification and do not determine identity. The default backend orders lines using actual glyph positions; merged block boxes remain conservatively `bbox_precision: estimated`. Status is explicitly `PARSED`, `PARTIAL`, or `FAILED`.

The default backend reads native PDF text and image resources without implicit OCR. Scans or sparse-text pages clearly produce `PARTIAL` with `PAGE_WITHOUT_TEXT`/`SPARSE_TEXT`, without fabricated coordinates. For scans, install `aletheia-nexus[ocr]`, Poppler/Tesseract, and use `--ocr`. `--ocr-languages` and `--ocr-max-raster-pixels` control language and per-page memory. The budget accounts for PDF `/UserUnit` before rendering and rechecks actual pixels afterward. OCR triggers only for low native character count, garbling, image-dominated content, or image regions without text anchors. Agreement corroborates readings; differences in symbols, digits, or garbled text preserve both native text and an uncertain `ocr-alternative`. High text similarity is not numeric agreement. Engine confidence and multi-engine consistency are separate; failure, timeout, or unavailable resources preserve native evidence with stable machine-readable degradation reasons. See [v0.7 OCR](V07_OCR.md).

The pipeline merges consecutive same-column lines, restores section semantics, and preserves explicitly unresolved references. Figure/table fields state only `caption-observed`, `caption-and-region-observed`, or `caption-and-cell-evidence-observed`, always with `interpretation_status: not-interpreted`. Generic OCR is not table, equation, or chart understanding; specialized parsers must use the region interface. Successful parsing does not establish that the paper's conclusions are true.

Control limits with `--max-pages`, `--max-blocks`, and `--max-text-characters`; `--no-merge-paragraph-lines` keeps line blocks. A reached limit produces `PARTIAL` rather than silent truncation. Parsed artifacts support source-linked search:

```powershell
aletheia-nexus search downloads\paper.parsed.json "experimental condition" `
  --section-type methods --verify-sources
```

Each hit includes section, PDF page, normalized bbox, and source text. `--verify-sources` rechecks both PDF and acquisition-sidecar SHA-256. Python callers can use `ParsedArtifact.search()`, `section_text()`, `locate()`, and `verify_local_sources()`. See [v0.7 architecture](V07_ARCHITECTURE.md) for module and backend boundaries.

Downstream use does not require parsing the PDF again. Export three deterministic derived views from a canonical artifact:

```powershell
aletheia-nexus export downloads\paper.parsed.json --format markdown `
  --output downloads\paper.ai.md
aletheia-nexus export downloads\paper.parsed.json --format jsonl `
  --output downloads\paper.ai.jsonl
aletheia-nexus export downloads\paper.parsed.json --format chunks `
  --output downloads\paper.chunks.json --max-chars 6000
```

Every chunk remains independently traceable through source/parsed artifact IDs, block/anchor/page identifiers, and the `block → anchor → page/bbox` chain. Chunking prioritizes section/table-object boundaries and separates headings, captions, equations, and references. Outputs refuse overwriting by default. Even explicit `--overwrite` can replace only a derived output, never a canonical parsed artifact, original PDF, or acquisition sidecar.

Public regression uses small project-authored Apache-2.0 redistributable PDFs in `benchmarks/v07_fixtures/`. Run `python scripts/evaluate_v07_parser.py` to check the input gate, per-page gold text, anchors, sections, two-column order, and figure/table evidence. `benchmarks/v07_public_oa/` separately defines three hash-frozen OA qualification papers downloaded on demand. Neither corpus establishes generalization to all publisher layouts or scientific semantics.

## 8. Troubleshooting

- **Browser connection timeout:** Check `http://127.0.0.1:9222/json/version`. A responding endpoint does not rule out a stuck internal debugging connection. Close only the dedicated AN browser and retry; login state generally remains in the persistent profile. Do not close everyday browsers or delete an entire user profile.
- **`TargetClosedError` and a locked profile:** Another Edge/Chrome likely owns the same AN profile. Pass its `--cdp-endpoint` to attach, or close only the dedicated AN browser/use another `--profile`. Do not let two processes write the same profile.
- **Linux normal launch cannot connect:** Besides profile contention, check the graphical session, browser dependencies, and system sandbox support. Ubuntu AppArmor may constrain a separately downloaded browser. Prefer a supported system Chrome (`--channel chrome`), or ask an administrator to follow [Chromium's official sandbox instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/security/apparmor-userns-restrictions.md). Do not disable sandboxing to visit publisher/institutional accounts.
- **Login completed but no continuation:** Return to the same AN browser session. AN checks old/new publisher tabs and authentication tabs left blank after new-tab authentication. If stuck, safely interrupt and resume from the checkpoint, retaining the scene/report for reproduction.
- **Repeated ScienceDirect/RSC verification:** AN does not actively refresh while waiting; the site may redirect or rebuild its challenge. Check whether the CAPTCHA remains, the paper has reopened, and the institution has entitlement. A brief blank page is not verification success. Repeated challenges/timeouts require human handling, not repeated requests to the same PDF. Increasing retries is not a remedy for site risk controls.
- **Ordinary Edge works but AN Edge loops:** Compare proxy mode and egress network. AN defaults to system settings; check for explicit `--direct-connection` or attachment to an older direct-mode window. Close that dedicated window before changing mode; do not toggle proxies within one task. VPN/TUN routing and browser proxying are different layers; AN does not alter the OS network.
- **An opened PDF is labeled `SUPPLEMENT`:** Inspect `identity.evidence`, the actual first page, and source URL. An ACS main text may contain “Supporting Information” navigation; the phrase alone is insufficient. Current rules combine first-page title and Abstract evidence.
- **`EXHAUSTED`:** Distinguish 403/challenges, no PDF candidates, title mismatch, and an actual purchase page. More retries usually do not resolve missing subscriptions.
- **Wrong institution automatically chosen:** Switch through the publisher's institution-selection UI. AN neither rewrites institutional cookies nor guarantees that IP-based redirection remembers the choice permanently.

## 9. Developer checks and scope

```powershell
python -m pip install -e ".[dev,browser,ocr]"
python -m pip check
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
python -m compileall -q src scripts
python scripts/verify_frozen_benchmark.py
python scripts/evaluate_v07_parser.py
python -m pytest -q
python scripts/verify_v07_rc.py --browser-smoke --visible-browser-smoke --ocr-smoke --public-oa `
  --report qualification-report.json
```

These scripts/unit tests neither replace entitlement checks in a real institutional environment nor establish compatibility with every paper layout. AN 0.7 connects acquisition/verification to source-anchored native-text-first parsing with optional selective OCR. v0.8 adds AI-assisted research organization; model output, experimental-condition links, and scientific claims must still be checked against sources. Engineering checks cannot replace scientific acceptance.

v0.7 qualification scripts import the current repository's `src` first to avoid testing another checkout in a reused environment. `--browser-smoke` requires the browser extra and Chromium; `--ocr-smoke` requires the OCR extra, Poppler, and Tesseract. Install missing components and rerun rather than calling skips or `PARTIAL` a pass. Private-corpus qualification requires a nonempty input and every paper to reach `PARSED`; missing files, hash changes, or partial parsing fail it.

The current CNKI bibliographic check is `cnki_bibliographic/v5`. A complete matching PDF title, authors, and publication record can pass without separately confirming a supplied DOI; explicit DOI/bibliographic conflicts still fail. It supports journal-name structure, publication information in the first three page margins, and constrained cross-checks of DOI/article number/continuous pages between CNKI records and the PDF, without paper/journal whitelists. See [generic verification rules](CNKI_AUTOMATION.md#通用书目核验规则v5). Original design and historical evidence are in [CNKI integration design](CNKI_INTEGRATION_DESIGN.md) and the [v3 acceptance report](CNKI_V3_INTEGRATION_REPORT.md). Existing DOI routes remain compatible; no-DOI inputs use CNKI ID/bibliographic identity, and ambiguous candidates are not resolved by picking the first. Unverified PDFs are retained in isolation by default, do not count as success, and are not erased by a later search timeout. `--no-cnki-keep-unverified` disables retention.

## 10. Historical: v0.7.3 checks before merging main

This section preserves v0.7.3's original release requirements and figures. It does not instruct maintainers to change v0.8 back to 0.7.3. For current checks/release status, see [v0.8 integrated release checks](V08_RELEASE_ACCEPTANCE.en.md); preparation records, official publication, and public-install verification must be recorded separately.

The final v0.7.3 PR must target `main`. Do not push a feature branch directly to `main` or commit copyrighted papers, institutional profiles, cookies, tokens, or reports containing signed URL parameters. Maintainers must retain the final commit SHA, test output, and private report locations. Do not merge or tag a stable release when code gates fail or evidence is missing.

1. On final code, run section 9's Ruff, compilation, frozen benchmark, parser evaluation, and full tests. Python 3.11–3.14 must pass, along with dedicated real Chromium, Poppler/Tesseract, and clean-wheel installation jobs.
2. Complete the frozen [v0.7.3 scientific gates](V073_FINAL_PLAN.md): the original 75 current checks, retention of the original 52 and H/I/J/K plus the latest 16, task review workload, fixed search, evidence export, and paired new sealed-set evaluation. Record itemized conclusions in [acceptance](V073_ACCEPTANCE.md). The v0.7.2 24-paper regression, 14-paper acquisition validation, and initial scores remain historical evidence, not substitutes. Recheck hashes, per-paper states, and source relations; interpret hidden text outside the CropBox against the visible page. Private PDFs/outputs remain ignored. Parsing completion, complete anchors, or consistent regression must not be called “100% visual or semantic correctness.”
3. Run at least one public-DOI PMC cloud smoke check: official-bucket candidate, consistent metadata DOI, `VERIFIED` main-text PDF, and matching sidecar hash. External-service smoke does not replace deterministic tests or establish a general acquisition success rate.
4. Confirm `pyproject.toml` version `0.7.3`, update release notes/history, build sdist/wheel from a clean commit, check dependencies, and verify `aletheia-nexus --version`, `doctor`, and core imports from the wheel in a genuinely new temporary environment. GitHub Release alone does not prove PyPI upload; inspect PyPI and a fresh install.
5. Push the feature branch and update its PR. Wait for actual `success` on the **final commit** for Python 3.11–3.14, Linux/Windows Chromium, OCR, and package jobs; `skipped`, cancellation, and old green commits do not substitute. After review, maintainers merge the PR, then create a new immutable `v0.7.3` tag on merged `main` and publish. Do not move old tags or upload an old package version again. Update preparation wording only after publication succeeds.

Only after scientific acceptance, actual workflows, and release checks pass should that version be declared complete and the 0.7 series closed. Archive nonblocking limitations honestly; no routine 0.7.4 feature version is planned.

Interpret older institutional/release evidence through [release history](RELEASE_HISTORY.en.md) and [pre-v0.7 readiness](PRE_V07_READINESS.md). Do not retroactively turn accumulated individual retests, one institution, or this public PMC smoke into cross-institution qualification.
