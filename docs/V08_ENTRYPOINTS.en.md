# 溯光 (Aletheia Nexus) v0.8.1: Chinese research entry point and local MCP

[中文主文档](V08_ENTRYPOINTS.md) · English translation

This guide covers v0.8.1. GitHub Releases and the PyPI project page establish release identity; use the actual checked-out commit or installed package version. Both entry points share
`ResearchApplication → research-task/v1 → run_task → export_results`.
Planning determines what to organize; scientific extraction reads the papers. A plan is not a verified scientific conclusion.
This page retains actual CLI, official-SDK protocol, and engineering records from development snapshot `8e3e82b`; they are not test results for the final integrated source.
For current engineering acceptance, see [integrated acceptance](V08_RELEASE_ACCEPTANCE.en.md). For scientific history and boundaries, see the [delivery report](V08_DELIVERY_REPORT.en.md) and
[latest ten-paper workflow comparison](V08_TEN_PAPER_COMPARISON.en.md). For the graphical interface, see the [workbench guide](WORKBENCH_USER_GUIDE.en.md).

## Installation and keys

Run in the source directory with Python >=3.11:

```powershell
pip install -e ".[mcp]"
```

For the built-in CLI alone, use `pip install -e .`. MCP is optional and uses the official Python SDK v2
`MCPServer`, minimum 2.3. Ordinary acquisition, parsing, search, and export do not depend on MCP.
Visual supplementation uses the existing Poppler `pdftoppm`, which must be on PATH. If unavailable, material gaps are recorded explicitly.

In Windows “Edit environment variables for your account,” create the user variable `DEEPSEEK_API_KEY`, then reopen the terminal.
The current terminal can also read a value already saved:

```powershell
$env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
```

Do not send the key to chat or place it in task/MCP JSON. The first implementation uses the existing DeepSeek
Responses API for planning and research; it does not attach Qwen Token Plan to an unattended research service.

## Starting with a PDF folder

```powershell
aletheia-nexus research ask "整理这些论文的研究对象、方法、主要结果和作者报告的局限，生成中文对比表，保留原文来源" --papers "F:\papers" --output-dir "F:\results\an08"
```

Alternatively run `aletheia-nexus research ask` and enter a directory and Chinese goal interactively.
By default only PDFs within the selected directory are read; the scope is not expanded recursively and new papers are not acquired online.

Registration and parsed copies are created in the results directory first, reusing existing artifacts that pass source checks. Original PDFs and canonical artifacts
are not overwritten. Derived PDFs use content-hash directories and the short name `paper.pdf` to reduce page-rendering failures caused by
long Windows filenames. Unknown titles, DOIs, or roles are explicit. Unregistered files are recorded as independent main papers with unconfirmed role,
without guessing SI parentage. For existing SI, first register it through the supplement/parent options in `aletheia-nexus import --help`,
then select the main paper and corresponding SI rather than treating attachments as independent papers.

Interactive use has two distinct permissions:

1. Send the Chinese goal and bibliographic metadata to the planning API, without full text.
2. After reviewing the Chinese plan, choose `e` to send paper materials and execute within the displayed scope, model, and budget.

The plan displays papers, field descriptions, steps/cross-paper comparison, original-page images, SI scope, model, request/cost caps, and
output formats. Choose `m` to edit and reload the saved task, `s` to save only, or `c` to cancel.
Models may expand requirements into finer fields; review them. A located citation does not establish scientific correctness.

The plan's image list is the initial input. Within selected documents and the supplementation-round, image, request, and cost caps,
`hybrid` can respond to model requests by reading additional original pages from the same PDF. It does not automatically download or bind new SI.
Additional pages create a new source package and material fingerprint while preserving original PDFs and old artifacts.

Default research limits are ten HTTP requests and an estimated CNY 2. Planning separately allows up to two requests and an estimated CNY 0.5.
Set `--max-calls`, `--max-cost`, or `--planning-max-cost`, or use `--model-config` to point to
an existing MODEL-contract configuration. Price/usage estimates are not bills; unknown usage retains a reservation.
A missing key produces an explicit error. Existing handwritten tasks still work with `research run`; the application does not pretend to have understood natural language.

Available execution strategies are `direct` and `source_first`. `field_independent` was retired after unseen-paper revalidation;
execution of tasks selecting it is explicitly rejected. Historical results remain readable, verifiable, revisable, and exportable. Save a separate task and explicitly choose
an available strategy, then review and authorize it again. The program does not silently replace old strategies.

New natural-language AI tasks default to `source_first`; choose `--extraction-strategy direct` explicitly if wanted.
Loading a task does not change its strategy because of a new default. Legacy tasks omitting the strategy remain direct, and tasks supplied directly by an
MCP client follow the original contract. Reading followed by assembly usually requires at least two requests per paper; request/cost caps do not increase automatically.

## Noninteractive use: review first, then approve the fingerprint

```powershell
aletheia-nexus research ask "提取方法和实验条件" --papers "F:\papers" --output-dir "F:\results\an08" --non-interactive --allow-planning --save-only
```

Inspect the printed plan and task file, then execute after review:

```powershell
aletheia-nexus research ask --papers "F:\papers" --output-dir "F:\results\an08" --task "打印出的task.json路径" --non-interactive --execute --allow-remote --confirm-plan "打印出的计划指纹"
```

The second command does not call planning again. The fingerprint binds the task, PDF/source records, parsed artifacts, model, budget, and allowed directories.
Changes to materials or task require a new preview. Noninteractive mode has no implicit upload permission.

### Explicitly adjusting an exceeded input limit

The default request character limit is 100000; a loaded task retains its saved value. A successful first reading can be followed by an oversized
assembly request after the reading draft is added. The program first attempts reversible encoding that omits only repeated default markers, removing no body text, readings, or images.
If still too large, it identifies the paper and `input_budget_exceeded`, preserving the completed first reading and original failure.

For a larger input, neither handwritten JSON nor another planning API call is needed:

```powershell
aletheia-nexus research ask --papers "F:\papers" --output-dir "F:\results\an08" --task "已保存的task.json路径" --max-input-characters 200000 --non-interactive --save-only
```

The argument must be a positive integer. A separate task copy and new plan fingerprint are produced. Use the newly printed task path and fingerprint
with the execution command above. The old fingerprint cannot authorize a changed budget. Paper scope, cost cap, and request cap
retain their existing values. Omitting the argument does not automatically raise the input limit; new natural-language tasks also accept this explicit argument.

## MCP: local stdio

```powershell
aletheia-nexus mcp serve --allow-dir "F:\papers" --workspace "F:\results\an08"
```

No network port is opened. Repeat `--allow-dir` for additional allowed directories; do not grant an entire disk or home directory by default.
The workspace stores new materials, tasks, and exports and is also readable, except for its internal `.authorizations` directory.
Path traversal and out-of-bound locations embedded in artifacts are rejected.

Copy the [Windows stdio configuration](../examples/mcp-stdio-windows.json) and substitute your own absolute paths.
Common clients use an `mcpServers` wrapper. If `cwd` is unsupported, omit it; an absolute Python executable and
installed module still work. Remote model calls are disabled by default; local queries need no key.

Remote operation requires `--enable-remote` and environment variables passed to the child process. Some clients filter environment variables;
Windows can use the supplied script to read user variables without writing a key into JSON:

```json
{
  "mcpServers": {
    "aletheia-nexus": {
      "command": "powershell.exe",
      "args": [
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "F:/AI4S/github/aletheia-nexus/scripts/start_an_mcp.ps1",
        "-Python", "F:/AI4S/github/aletheia-nexus/.venv/Scripts/python.exe",
        "-Papers", "F:/AI4S/papers",
        "-Workspace", "F:/AI4S/results/an08", "-EnableRemote"
      ]
    }
  }
}
```

The execution-policy setting applies only to that launch process. Use a script from a local repository you have reviewed; system policy is not changed.
Keys pass through the environment only. stdout carries protocol messages and stderr carries logs.

## Using AN from an MCP client

For example: “List the papers in F:/papers, prepare local materials, organize methods and main findings, and show me the plan first.”

| Tool | Purpose | Remote operation |
| --- | --- | --- |
| `list_documents` | List PDFs; `catalog=true` reads existing library tags, parent relationships, and integrity, with folder/tag/query filters | No |
| `update_document_tags` | Add/remove library tags on workspace PDF copies while retaining provenance and parse evidence | No |
| `find_paper_candidates` | Query up to five Crossref candidates by title/bibliography; select a DOI before separate acquisition | Independent discover permission; no AI |
| `get_acquisition_status` | Read acquisition/registration status; explicitly supplied PDFs can undergo current integrity/identity checks | No |
| `acquire_documents` | Batch public DOI acquisition, identity verification, and checkpoint recovery; returns asynchronous job_id | Independent public-acquisition permission; no AI |
| `prepare_documents` | Prepare explicitly selected PDFs, isolate failures, and create workspace copies | No |
| `prepare_documents_job` | Prepare explicitly selected PDFs in the background, return job_id, and reuse valid parsing | No |
| `import_local_document` | Register a main paper or explicitly parented SI copy using supplied metadata; DECLARED only | No |
| `parse_document` | Explicitly create a separate new parsed artifact for a registered paper, preserving older versions | No |
| `draft_research_task` | Validate a client-supplied task directly or plan from natural language | Only the natural-language branch needs planning permission |
| `validate_research_task` | Validate sources/fields/budgets; return a plan and authorization request | No |
| `execute_research_task` | Run the existing engine asynchronously; return job_id | Research mode needs independent permission |
| `get_run_status` | Read status, errors, native manifests, and cost | No |
| `export_research_results` | Re-export compatible results as Markdown/CSV/JSONL | No |
| `search_documents` | Existing table/caption-aware search on selected papers, retaining coverage | No |
| `read_native_table` | Read native cells/ranges from explicitly selected local XLSX, retaining source and reading limits | No |
| `read_document_context` | Read complete original-page context, tables, captions, and locations | No |
| `read_original_page` | Return an original-page image, optionally enlarging a normalized displayed-page region with source/bounds retained | No |
| `read_original_page_text` | Read a selected PDF page's text layer with column-aligned whitespace, provenance, and truncation status; no prior parse required | No |
| `get_parse_diagnostics` | Inspect parse quality, failure diagnostics, and current source verification | No |
| `read_research_result` | Read existing fields, citations, validation, and revision history | No |
| `revise_research_result` | Explicit assistant revision of one existing record/claim/issue, independently saved/exported and never human-confirmed | No |
| `list_research_runs` | Read local run history and recorded costs; kind distinguishes research from acquisition | No |

Read tools return allowed-directory content to the host client. Whether its own model sends that content remotely
is governed by the client's privacy and approval mechanisms. AN's `--enable-remote` controls AN's own model calls.
Search directly reuses v0.7 table/caption content units and evidence packages; a literal nonmatch is not missing scientific information.
If `read_document_context` exceeds the character budget, it explicitly skips complete context rather than truncating headers or silently dropping rows.
Prepare manual cross-drive PDF/artifact combinations with `prepare_documents` in the workspace before library search.

### Reading an original page's layout text

For example: “Read this paper's native text layer on page 12, preserving table-column alignment; show the original-page image for uncertain parts.”
The client calls `read_original_page_text(document, page=12)`, using the document object returned by registration or preparation.
No parsing, Poppler, OCR, or API key is needed; only the specified PDF within allowed directories is accessed.
This also supports clients needing text input. The existing `read_original_page` image tool remains available.

The returned `text` is layout text derived by pypdf from the PDF text layer, retaining alignment whitespace and line breaks. It also returns
original-PDF identity, physical page, extraction engine/version, text hash, and a stable derived identifier. It does not change the PDF or existing canonical
artifacts, automatically enter AN's research model input, or change the default extraction strategy.

The default maximum is 40000 characters; `max_characters` accepts 1–200000. `text_truncated=true`
means only the opening portion is delivered; `total_characters` gives that extraction's total length. Increase the limit
or read the original-page image for complete context. This differs from the whole-context budget policy of `read_document_context`.
`has_native_text=false` means this extraction yielded no text-layer content, not that the paper did not report the required information.

Layout text may still have character-encoding, rotation, and reading-order problems. Extracting text does not automatically understand relationships
among images, curves, and legends, or restore cross-page headers. Readable column alignment is another source view, not proof that table
or scientific relationships are correctly understood. The host client's use of returned content remains subject to the privacy boundary above.

### Enlarging a page region

For example: “Enlarge this dual-axis panel, including both axes, series markers, and the necessary legend.”
The client reads the whole page first, then uses the same tool's optional argument:
`read_original_page(document, page=7, region=[0.4, 0.45, 0.65, 0.7])`.
These are example coordinates, not a claim about the position of a figure in an arbitrary paper.

`region=[left,top,right,bottom]` uses 0–1 coordinates relative to the **complete PDF CropBox in its displayed rotation**,
with the top-left as origin, not relative to an earlier crop. The region is generated from an original-page raster with a 3200-pixel long edge. The response includes actual
pixel-rounded bounds, requested bounds, original raster dimensions, pixel region, and image hash. The PDF stays read-only.
Without `region`, the original whole-page view is returned, without changing ordinary research-task image input.

A selection may omit legends, shared headers, axes, or footnotes. Valid coordinates do not establish sufficient context or scientific meaning.
Read the whole page or enlarge the selection when needed. This interface supplies traceable region reading only. AN's current research request contract still
automatically supplements pages, without default autonomous model region selection, image correction, or a new multiround extraction strategy.

### Authorized public full-text acquisition

Acquisition is disabled by default. Start with this capability enabled when needed:

```powershell
aletheia-nexus mcp serve --allow-dir "F:\papers" --workspace "F:\results\an08" --enable-acquisition
```

Alternatively copy the [public-acquisition stdio configuration](../examples/mcp-stdio-windows-acquisition.json) and change absolute paths.
With `start_an_mcp.ps1`, add `-EnableAcquisition`. It is separate from `-EnableRemote`;
public downloading needs no DeepSeek key and grants no model-call permission.

In the client: “Acquire DOI 10.1371/journal.pone.0310216, verify its source, and prepare parsing; show the acquisition plan first.”
The client calls `acquire_documents(papers=[{"doi":"10.1371/journal.pone.0310216"}])`.
Each paper may include a `title` identity constraint; a batch allows up to ten papers. For title-only input, query
`find_paper_candidates` and select the DOI first. This tool does not automatically obtain SI or log into institutions.
Those existing CLI capabilities are not all exposed through MCP. Public-acquisition failure does not automatically open browsers, use official credentials, or expand permissions.

The tool first returns a Chinese scope description and `authorization_request` file without networking. Review it in a separate terminal using
the `research authorize` command below, then pass its one-use authorization to this tool's `authorization` argument.
Approval binds DOI/title, allowed directories, fixed public-route restrictions, and the recovery checkpoint; `confirmed=true` is not a substitute.
Planning/research authorization cannot authorize acquisition, and acquisition authorization cannot authorize AI. Each approval is single-use.

After approval, the tool returns `job_id`. Use `get_run_status` for per-paper results and local `pdf`/`sidecar` paths.
The server reuses existing batch acquisition, PDF/identity verification, and checkpoint mechanisms, allowing up to four routes and four file candidates per paper;
route/file request timeout is thirty seconds, with at most one attempt per route/file. `COMPLETED/PARTIAL/FAILED`
distinguish full success, partial success, and nondelivery. Original public-route states and exception types remain separate. Background execution does not block stdio requests.
Successful files can go directly to `prepare_documents`, retaining download provenance rather than becoming human-declared or overwriting old PDFs.

For failed/interrupted recovery, request another plan with the same `papers` and `resume_job_id`, then approve again.
Recovery writes a new task directory, copying and checking verified files and retrying failures only. Original checkpoints, PDFs, provenance, and history remain unchanged.
Recovery is unavailable while the original task runs; checkpoint changes invalidate old approval, and corrupt checkpoints fail explicitly.
If the process stopped before its first checkpoint, the plan explicitly states that the selected scope will restart acquisition rather than trusting leftover files automatically.

Public acquisition covers public main texts. Query title candidates using `find_paper_candidates`, review them, then authorize acquisition separately.
Candidate order is not identity confirmation. Institutional sessions still use the existing CLI human-handoff process, without a public server.
The following is a historical `8e3e82b` development-snapshot record, not final integrated acceptance: an official SDK 2.3.0 real stdio client completed mocked-network authorization/recovery/parsing tests; separately, the public DOI above was actually downloaded,
verified, and prepared as a successful twelve-page parse, with zero model calls. Recovery through a fresh server process and unusable HTTP proxy
reused valid files with zero acquisition attempts, preserving original PDF/source-record/checkpoint hashes. A manual conversation in an actual desktop AI client remains separate acceptance work.

### Acquisition records and current source checks

`get_acquisition_status(sidecar="F:/papers/json/paper.acquisition.json")` reads existing
acquisition records, including nondelivery states such as `AUTH_REQUIRED`, without requiring parsed artifacts or a successfully downloaded PDF.
Record-only reads return `current_check.status=NOT_CHECKED`; historical `VERIFIED` is not proof that the current file remains intact.

Explicitly adding `pdf="F:/papers/paper.pdf"` reuses the source gate to check hashes, page counts, record status, and identity.
Optionally provide `expected_doi` for an expected-DOI check; it cannot be requested without the PDF.
The response preserves `recorded_status` and `current_check` separately: an old record may remain `VERIFIED` while its current
check is `FAILED/PDF_HASH_MISMATCH`. Local registration stays
`REGISTERED/DECLARED` with `identity_verified=false` even after integrity passes. Passing checks does not prove scientific correctness.

This tool does not follow paths/URLs in the record, retry acquisition, or write/upgrade source records. Both PDF and sidecar
must be inside locally allowed directories. There is no `confirmed` or remote-authorization argument. Public DOI downloading uses
independent `acquire_documents` permission; institutional sessions still need the existing acquisition CLI and access settings.

### Explicit assistant revisions

First read the result with `read_research_result`, retaining the target's complete structure. In
`revise_research_result(result="结果JSON路径", revision={...})`, `revision` must contain:

- Exactly one existing target: `record_id`, or zero-based `claim_index` / `issue_index`.
- `replacement`: the complete replacement record, claim, or issue; record IDs cannot change.
- `reason`: a nonempty revision rationale.

The tool reuses existing revision and citation validation. It calls no AI, downloads or reads no new pages, and does not change tasks, source packages, or original files.
Bound PDFs, source records, and canonical parsed artifacts must still be within allowed directories and match their saved identities.
Missing or changed sources fail explicitly; changing paths/reparsing does not silently migrate old citations.

The server fixes `authority=assistant` and `confirm=false`, records UTC time, and uses the client name/version from the MCP handshake.
Caller-provided `author`, `at`, `authority`, and `confirm` are not accepted. Self-reported client names provide historical attribution,
not identity authentication or human approval. Revised targets remain pending review; untouched targets retain their existing human-review state under existing rules.
Adding/deleting records, claims, or issues and editing supplementary requests are unsupported. Each call revises one existing target only.

New versions live at workspace `revisions/<uniqueID>/result.json`; parent results, PDFs, and old artifacts are not overwritten.
Complete JSON retains each rationale, previous content, and parent-result ID for reading, copying, or export. The same directory also receives
existing Markdown/CSV/JSONL research exports. A table export is not the full history; retain JSON for traceability.
This entry point validates structure, sources, and citation locations, not scientific correctness of revisions.

### Explicit registration and new parse versions

For a local main paper without a source record, call
`import_local_document(pdf="F:/papers/paper.pdf", title="论文标题", doi="10.xxxx/...")`.
DOI is optional. Caller metadata is recorded as `REGISTERED/DECLARED`, not download verification.
Import preserves a PDF copy, original path, and filename in the workspace and returns `document`; it does not overwrite original PDFs or provenance.
For existing registration/acquisition records, use `prepare_documents` to retain them. Register new SI explicitly with
`import_local_document(pdf="F:/papers/SI.pdf", title="补充材料", role="SUPPLEMENT", parent={"pdf": "主文PDF路径", "sidecar": "主文来源记录路径"})`.
The parent must be a registered or verified independent main paper. SI does not receive a separate DOI and keeps parent references. Parentage remains the caller's
`DECLARED` assertion, not verified official linkage. The tool does not infer links from filenames or accept `confirmed`.

For an existing library, use `list_documents(directory="工作区路径", recursive=true, catalog=true, tag="待读", query="关键词")`;
`folder` filters relative directory paths. Use ordinary listing for unregistered PDFs in that directory.
On workspace copies, `update_document_tags(pdf="副本PDF路径", add=["待读"], remove=["已读"])` adds/removes tags.
Only tag files change; PDFs, provenance, and parse evidence remain intact. `--allow-dir` grants reading only, not tag changes in the original external library.
Public title discovery requires separate `discover` permission rather than reused `acquire` approval. Institutional login/CAPTCHA sessions continue through
the existing acquisition CLI/access settings; public DOI permission does not expand to them.

Pass returned `document` to `parse_document(document=..., max_pages=2000)` to explicitly use the current parser
for a new version. Each call writes a unique `*.parsed.json` recognized by existing `load_corpus` scans; it does not rename or overwrite
old canonical artifacts. `prepare_documents` still reads old `parsed-UUID.json` and does not reparse merely because the parser upgraded.
Use the returned `document` to explicitly choose the new version. Old citations/results remain bound to their original artifact.

Native text is the default. Only `ocr=true, ocr_languages="eng"` enables the existing local native-first selective OCR,
requiring Poppler/Tesseract and installed language data without downloading models. Executable-path configuration is not exposed.
A new native version does not replace an existing OCR version. The tool returns actual `status`, `parser`, `quality`, `warnings`, `errors`,
and options. Page limits, missing OCR dependencies, or insufficient materials may yield `PARTIAL/FAILED`, not complete parsing.
This is a synchronous local operation. Large PDFs/OCR can take time; set client timeouts or use the existing parsing CLI.

Parser 3.10.21 additionally recognizes `Supplementary Figure/Table` headings, retaining same-number main and supplementary headings
separately. Old artifacts do not upgrade automatically; use `parse_document` for a separate new version. A located heading
does not establish correct table relationships: real SI still contains split decimals and misplaced columns. Read dense tables using `read_original_page`
or explicitly include their pages in research-task `image_pages`, retaining raw readings and uncertainty.

If the client already has a model, it can generate and validate a task directly without AN's planning API. With only a natural-language goal,
AN first returns a planning authorization request. Model-supplied `confirmed=true` never automatically sends metadata or paper contents.

Remote approval produces a local request file. In a separate terminal, run:

```powershell
aletheia-nexus research authorize "返回的authorization_request路径"
```

Review scope and budget, confirm, and pass the single-use authorization to the current AN tool. Planning, research, and public-acquisition permissions are separate.
Changes to tasks, source files, budgets, or directories require approval again; already permitted supplementation for the same documents within budget uses the original permission.
Authorization is valid for one hour and expires after one use. MCP has no
grant-issuing tool. The trusted CLI's `--approve-fingerprint` is only for previously reviewed requests; models should not call it themselves.
This is an MCP-parameter boundary, not an OS sandbox against arbitrary local programs running as the same user.

Keep the client/server open and query until terminal status. Disconnecting a stdio client may stop the server process tree.
After restart, unfinished tasks become `INTERRUPTED`, without automatically resending paid requests. Inspect native workspace manifests
and delivered results before recovering with new approval. Existing cache rules remain: unstable supplementation failures cannot become valid cache,
and recovery may require an API call. Stop using Ctrl+C or disable/remove the client configuration, without deleting originals.

New tasks use OS file locks to identify running owners, allowing another MCP entry point to query CLI execution. After owner exit,
they return `INTERRUPTED`. Old tasks lacking ownership records retain an unknown state rather than guessing their process has stopped.

## Saved content and acceptance boundaries

`materials/` and `preparations/` retain registration/parsing and selection records. `planning/` separately stores planning requests,
raw responses, task.json, and manifests with `phase=task_planning`. `jobs/` provides unified progress;
`research/runs/` contains native research results/source packages; `exports/` contains re-exports; `revisions/` contains independent revised versions and exports.
`PARTIAL`, diagnostics, and AI judgments never become human confirmation.

Engineering success is not scientific accuracy improvement. See acceptance records for real models, clients, failures, usage, and limitations.
Real SDK protocol tests and manual conversations in a desktop AI client are documented separately and cannot substitute for one another.

### Scientific-development snapshot execution (2026-10-30, `8e3e82b`)

This section preserves that commit's original execution, cost, failure, and engineering figures; they have not been updated into final integrated-version scores.

An actual twelve-page original PDF with a Chinese filename was used, requesting three Chinese fields: research object, methods, and main results reported by the authors.
One planning API call was made. Under the user's existing authorization, the root assistant locally reviewed the saved plan,
scope, and budget before execution. This is not a record of an on-the-spot human plan click and does not mark scientific results human-confirmed.

After first reading, the assembly request had 103776 characters, exceeding the 100000 limit, so the first run failed explicitly. After the fix, the same task
reused its first reading and reversible encoding reduced input to 89441 characters. The model then requested five original-page images, pages 6–10 of the same PDF,
using the existing one supplementation round and six-image maximum. Research totaled four HTTP requests and an estimated CNY 1.08986816, including
the first run's reading, without raising the original four-request/CNY 3 budget. Planning separately cost an estimated CNY 0.015262; both estimates use configured prices.
The final result contains one record, three Chinese fields, and Markdown/CSV, retaining `PARTIAL` status rather than asserting complete scientific correctness.

A separate official Python SDK 2.3.0 stdio server exposed 23 tools. After independent local approval, the same task
actually reused cache with zero model HTTP. A subsequent keyless server queried documents, diagnostics, and history, read results, and re-exported
Markdown/CSV/JSONL with zero model HTTP. PDF/canonical-artifact hashes remained unchanged. These are actual protocol calls,
not a claim of a manual desktop AI-host conversation or Python function calls mislabeled as MCP acceptance.

The `8e3e82b` development snapshot's full engineering suite had 2763 passes, zero failures, and 119 skips. Of these, 111 headless cases had actual prior passing records,
with matching source/test Git subtrees reused by hash rather than run again. The other eight—two visible-browser, two real-OCR,
and four Windows symlink-permission cases—were not run. That snapshot's wheel build, installation, and local SDK smoke checks passed; its new private environment explicitly
reused existing dependencies rather than resolving dependencies through a clean online installation. See the [final delivery report](V08_DELIVERY_REPORT.en.md) for the full delivery and scientific results.
