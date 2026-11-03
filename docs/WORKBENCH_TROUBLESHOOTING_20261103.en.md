# Aletheia Nexus workbench incident report and remedies

[中文](WORKBENCH_TROUBLESHOOTING_20261103.md)

Date: 2026-11-03. Baseline: v0.8.1, Windows x64, Python 3.12.15, UI and MCP extras. This report follows local import, parsing, AI extraction, review and export. Inputs are anonymized as PDF-A and PDF-B. Papers, model responses, user libraries, credentials and local task records are excluded from the contribution.

“Patched” means included in this proposed change, not merged or released upstream. The associated PR and release records determine publication status.

## Findings

| Symptom | Finding | Remedy/status |
| --- | --- | --- |
| Repeated missing-file notification after import | The original PDFs existed. A generated acquisition snapshot path was 261 characters long and could not be created in this Windows environment. | A shorter workspace resolved the local installation; the patch adds compact Windows snapshot locators and a specific excessive-workspace error. |
| PDF-A cannot be parsed | Inverted CropBox coordinates produced negative page heights. No text was extracted from its 119 pages. | Original preserved; not claimed fixed. Obtain a valid source or create and visually validate a separate repaired derivative. |
| Input character budget exceeded | PDF-B contains about 28,000 text characters, but its 14-page structured model material contains 163,121 characters. The submitted task allowed 100,000. | Preserve the guard; narrow scope or explicitly revise the task after reviewing cost/call limits. A new local default and execution task used 200,000. |
| Editing the displayed limit did not fix the old task | The actual failed receipt still contained 100,000. | Inspect the effective task, not just the form. The precise form/history/expert-contract interaction was not established; no unproven UI event defect is claimed fixed. |
| A completed local task had no AI summary | Its mode was `local`, meaning preparation without model calls; the API key was initially absent. | Select `parsed` for model extraction, configure credentials, review scope and budget, then execute. |
| Export links did not download | Files existed, but links opened new tabs and the server sent `Content-Disposition: inline`. No download event occurred. | Explicit attachment links, while retaining inline previews. |
| No consolidated visual report | Tables and Markdown were inconvenient for reading, source-image inspection and printing. | Add an offline HTML derivative and workbench preview/download entries. |
| MCP confused with a chat interface | A native MCP service exists but requires a separate client connection. | Explain the existing interface; no conversational UI or client integration is claimed added. |

## Windows snapshot paths

The failing path had this shape:

```text
<workspace>/research-workspace/materials/<64-char PDF hash>/json/<64-char acquisition hash>.acquisition.json
```

Import had succeeded. Failure occurred when `WorkbenchResearch._snapshot()` created the research copy. A generic `FileNotFoundError` notification incorrectly suggested that the selected original PDF had disappeared.

The immediate operational remedy is a shorter `--workspace`. Stop active tasks and back up settings/history first. Successful historical artifacts contain explicit locators; do not blindly replace absolute paths throughout existing records. The original workspace was retained during this incident.

The workbench and the shared CLI/MCP research service use the same path-selection helper. The patch uses `m/<first 24 PDF hash characters>/...` when a generated Windows sidecar path would reach 240 characters. This is only a storage locator: full PDF and acquisition hashes, source validation and immutable-copy collision checks remain intact. A conflicting existing copy is rejected rather than overwritten. Historical locators are not rewritten. If the compact target is still at least 260 characters, fail before copying with `workspace_path_too_long` and recommend a shorter workspace.

Atomic export, canonical parsed artifacts and local PDF registration also repeated destination/source filenames inside temporary names. This could exceed the Windows limit despite a valid final destination. The patch uses a same-directory UUID temporary name, preserving exclusive creation, atomic replacement and canonical-source overwrite protection, with a regression test.

Code: `research_app.py`, `workbench/research.py`, `workbench/messages.py`, `content/export.py`, `content/schema.py`, `content/local.py`.

## Malformed PDF geometry

An example PDF-A page had MediaBox `[0, 0, 549.9213, 802.2047]` and CropBox `[0, 802.2048, 549.9213, 0]`. The parser reported `CropBox must have positive dimensions`; the document yielded no extracted text.

This is independent of the path issue. Browser readability does not prove valid extraction geometry. Prefer a valid original. If repair is necessary, retain the original, save a separately identified derivative and visually verify page rendering and text positions before registering it. This contribution neither repairs that input nor weakens geometry checks.

## Input budgets, preparation and credentials

The limit applies to serialized structured material/requests, including evidence blocks and references, rather than plain text alone. Local measurements for one parsed version of PDF-B were:

| Selected physical pages | Model-material JSON characters |
| --- | ---: |
| All 14 | 163121 |
| 1 | 6998 |
| 1–3 | 15155 |
| 1–5 | 46780 |

These are incident-specific values, not a universal conversion ratio. A 200,000-character limit accommodates this material but does not guarantee every later request or comparison will fit.

Check documents, physical pages and parse versions first. Reduce unnecessary scope or explicitly revise the input cap after reviewing pricing, call count and cost caps. Loaded historical plans, submitted tasks and new defaults are separate. Use effective-plan preview and inspect `budget.max_input_characters`; when the expert contract is enabled, inspect that contract. Reopen the research page and create a new plan after changing defaults. Keep old failures as history.

`local` does not generate an AI answer. Model extraction requires an appropriate mode such as `parsed`, valid API configuration and the reviewed authorization. The subsequent real workbench execution used 200,000 characters, at most 10 calls and a 2 CNY cap. It made two requests and estimated 0.702408 CNY using the supplied prices; this is not a provider invoice.

The result remained PARTIAL because it requested further figure/table inspection. Completion of requests, valid citation locations and scientifically verified claims are distinct states.

Session-only API keys disappear after a process restart. Users can explicitly opt into the existing Windows credential feature. A patch must not silently persist a key. Never include secrets in chat messages, examples, task files, logs or public contributions.

## Download behavior

Reproduction: open Results, export the selected version, then click `report.md`. The old link opened a tab and served an inline response; the report and ZIP already existed.

The fix labels output links as downloads, uses the same tab/download attribute, and requests `/an-file/{token}?download=true`. The optional boolean parameter selects `attachment`; the default remains `inline` for previews. File capabilities, allowed roots, hashes and same-origin checks remain in force. Users export first, then click the relevant download link; the export button does not automatically save to an arbitrary local directory.

Code: `workbench/ui.py`.

## Visual report

`workbench/visual_report.py` renders existing native results as a standalone HTML derivative. Workbench export now includes an HTML option and provides a preview and `report.html` download.

The report contains claim cards, complete field values/context, procedural records, individual citations, issues, material requests and source/task metadata. Local source-page images prioritize explicitly requested figure/table review pages, at most six pages per source at a 1600-pixel scale. This is not every image from the entire PDF.

No model calls or new scientific claims are introduced. Source images are only read when HTML is explicitly selected; existing callers without a format selection retain text-only exports. Source bytes are verified before and after rendering; images from a failed verification are discarded. Historical text remains readable when original PDFs or the renderer are unavailable, with a warning for omitted images. Content is HTML-escaped and images are embedded without remote fonts, scripts or CDNs. Different results namespace source IDs to keep historical versions separate.

Printing expands images and references and waits for image decoding before opening the browser print dialog. Users can save a PDF. The feature does not automatically send supplementary pages to a model or upgrade review flags. Native results/history remain unchanged; native ZIPs retain the underlying structures. This change integrates HTML into workbench export only, without changing CLI/MCP export contracts.

Code: `workbench/visual_report.py`, `research.py`, `ui_research.py`.

## Existing MCP support

`src/aletheia_nexus/mcp_server.py` implements `aletheia-nexus mcp serve`. It exposes document listing, preparation, parsing, search, original-page reading and research-result tools for an external AI client. Installing its dependency is not proof of an active client connection. No multi-turn chat UI or MCP host connection was added during this incident. See [the MCP guide](V08_ENTRYPOINTS.en.md).

## Validation and remaining limitations

The patch is based on upstream commit 403514fd6ce49822db80039de8bde6011aa93b63. The final complete `python -m pytest -q` run on Windows / Python 3.12.15 reported 3881 passed and 231 conditional skips in approximately 296 seconds. Repository-wide Ruff format/lint, compileall, pip dependency checks and frozen benchmark integrity passed. The wheel built successfully and includes the visual-report module without runtime libraries or PDFs. Added tests cover Windows path selection/errors, atomic export to long destinations, content preservation, escaping, historical-source isolation, explicit HTML selection and discarding images when sources change during rendering. Skipped optional tests are not counted as passed; other Python/OS combinations remain subject to actual CI results.

Local browser checks exercised actual Markdown and ZIP downloads and validated contents, retained inline previews, unknown-token 404 and cross-origin 403 behavior, desktop width 1440 and narrow width 390 without horizontal overflow, six decoded embedded source pages, and print-time expansion of images/references.

Not completed or outside scope: repair of PDF-A, scientific verification of all original equations/figures, a continuous chat UI, an actual conversational MCP client connection, and reconciliation with the provider invoice. Browser observations apply to the tested local Edge environment, not every embedded browser, OS or printer driver.

## Public contribution boundary

Include only reusable source changes, synthetic tests, this document and its Chinese counterpart. Exclude papers, user reports containing paper images, native model outputs, libraries, authorization grants, credentials, user-specific absolute paths and installed environments. Reviewers should focus on snapshot compatibility, attachment versus preview behavior, source/history isolation, rendering costs and truthful partial/review states.
