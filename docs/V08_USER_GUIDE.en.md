# 溯光 · Aletheia Nexus v0.8: AI-assisted literature processing and knowledge extraction

[中文](V08_USER_GUIDE.md) · Chinese is the primary document; this is its complete section-by-section English counterpart. Commands and example data are reproduced unchanged, including Chinese placeholders.

This guide covers the integrated v0.8.0 research engine, graphical workbench, natural-language CLI, and local MCP. Official release status is determined by [GitHub Releases](https://github.com/shenxuekairui/aletheia-nexus/releases) and [PyPI](https://pypi.org/project/aletheia-nexus/); the source version is not an upload status. Start with the [workbench](WORKBENCH_USER_GUIDE.en.md) or [natural-language/MCP entry points](V08_ENTRYPOINTS.en.md) without first writing task JSON. Existing acquire, import, parse, search, export, and EvidenceJudge interfaces remain available. This guide details the shared `aletheia-nexus research` contract and behavior.

See the [scientific acceptance record](V08_ACCEPTANCE.md) for accuracy, omissions, and whole-record results; the [ten-paper comparison](V08_TEN_PAPER_COMPARISON.en.md) for the latest comparison; and [integrated release checks](V08_RELEASE_ACCEPTANCE.en.md) for engineering gates and release status. Model reading, valid delivery, and scientific correctness are reported separately. Assistant source review is not a human gold standard. There is no promise of 90% performance across fields, and critical experimental conditions require checking the source.

## Quick start

After installing from the current release-candidate source, copy `examples/research-theme.json` and change its document paths to your own `.parsed.json` files. Paths are relative to the task JSON's directory; absolute paths also work. Register an unregistered PDF using the existing `import` command first; see the [research workflow](V072_RESEARCH_WORKFLOW.md) for main-text/SI registration. Do not bypass source verification for AI use.

```powershell
python -m pip install -e ".[dev]"
aletheia-nexus research run task.json --output-dir research-output
```

The example defaults to `mode=local`, `allow_remote=false`: it prepares task materials without calling AI. Existing local functions also require no API key. For extraction, set `mode=hybrid`, `allow_remote=true`, then explicitly add `--allow-remote`:

```powershell
aletheia-nexus research run task.json --output-dir research-output --allow-remote
```

## Default for new tasks: read sources before extraction

New natural-language and workbench tasks default to `source_first`, reading sources before assembling results. Manual `research-task/v1` tasks can also set `"extraction_strategy": "source_first"`. For historical compatibility, saved tasks omitting the field still use direct extraction; their task or cache is not changed. The strategy first creates a source-reading inventory with object, stage, source page, and field associations. It then gives the model the same original text/images plus that inventory to generate the existing fields, steps, and results. The inventory is a fallible AI reading draft, not a replacement for the source.

```json
"extraction_strategy": "source_first"
```

The natural-language entry point can select it without editing JSON:

```powershell
aletheia-nexus research ask "整理这些论文的方法、条件和主要结果" --papers ./papers --output-dir ./research-output --extraction-strategy source_first
```

Use `--extraction-strategy direct` for direct extraction. Loading a saved task without the option preserves its configuration; a new natural-language task without it defaults to `source_first`. When loading a task, the option saves a copy with the chosen strategy before preview/authorization fingerprinting, leaving the user's original file unchanged. An old strategy's fingerprint cannot authorize the changed task. You can still run `research run task.json --output-dir research-output --allow-remote`; MCP validation/execution accepts the same `task.extraction_strategy` and engine. The plan explains additional two-stage calls. Each document group and each round of new material requires at least two calls, all within the existing `budget.max_calls` and `budget.max_cost`; budgets are not raised automatically. Local mode only prepares materials, even with this strategy.

The run directory preserves inventory input, raw candidates, source-material fingerprints, and stage records. If reading succeeds but field assembly fails technically, rerunning the same task/material/model/prompt can reuse the inventory; changes to task, images, materials, model, or prompt require reading again. Reuse points to the original run/call number. Original failures, costs, and time remain in that manifest rather than being presented as new calls or zero cost.

If adding the reading inventory makes only the assembly request exceed its character limit, AN tries the existing reversible material encoding. It omits repeated default markers only, without deleting original text, reading entries, or images or raising the budget. If still too large, it fails clearly while retaining the valid reading cache. The encoding version, before/after character counts, and request fingerprint are recorded in the manifest and assembly input. The natural-language entry shows failed documents, error codes, and budget reasons; this input failure is not a model misreading. For larger input, preview and confirm again with `research ask --task task.json --papers ./papers --output-dir ./results --max-input-characters 200000`. The new plan is saved separately without overwriting the task, recalling the planning API, or increasing cost/call limits. The old fingerprint cannot approve the changed budget. Omission preserves a loaded task; new tasks default to 100000.

## Compatibility for the retired field-independent strategy

`field_independent` is retired. In confirmation on eight new papers, whole-field performance was lower than normal `source_first`, so new independent per-field execution is no longer provided. CLI/MCP offer `direct` and `source_first` only. Direct execution of an old task reports `field_independent_retired_use_source_first_or_direct_and_preview_again` before reading papers, creating a run, or calling a model.

Existing `research-task/v1` files, results, histories, and caches remain untouched and can still be viewed, checked, revised, and re-exported through `research export` or MCP without a key. To extract again, save a copy, explicitly change to `source_first` or `direct`, preview scope/calls/cost again, and authorize. AN does not replace an old strategy or repurchase historical answers automatically.

## Optional compact material presentation

Explicit `material_presentation=compact` is independent of the extraction strategy. It omits repeated default structural markers, without removing source text, numbers, charts, or images. Requests carry metadata to restore those defaults, and the complete material package is retained separately. Its purpose is reducing repeated encoding and input-resource pressure; it is not a proven scientific-accuracy strategy or a default.

```powershell
aletheia-nexus research ask "整理这些论文的方法与条件" --papers ./papers --output-dir ./research-output --material-presentation compact
```

The same option works when loading a task. Before preview/fingerprint creation, AN saves a new task copy containing the selection. The original is untouched, and its old fingerprint cannot authorize a different presentation. Omission preserves the saved configuration without injecting defaults into old tasks. You may instead set `"material_presentation": "compact"` in `research-task/v1` and use the original `research run` or MCP validation/execution. This does not increase call budgets or permitted directories; local mode still makes no remote calls. Material presentation cannot replace source-completeness or scientific-correctness checks.

## Models and keys

The first adapter uses the DeepSeek Responses API, with `deepseek-flash` as the configured model. It supports text, images, and JSON Schema; see the [DeepSeek Responses API documentation](https://api-docs.deepseek.com/api/create-response/). Ordinary automated tests use mocks and do not send papers. Set `DEEPSEEK_API_KEY` through the environment; do not put a key in task JSON, source, command arguments, result files, or chat.

On Windows, open “Edit environment variables for your account” and create the user variable `DEEPSEEK_API_KEY`, setting its value without quotes. A **new terminal** inherits it. An existing PowerShell can refresh it explicitly:

```powershell
$env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
```

Do not print the variable. On Linux/macOS, provide the same environment variable through a terminal or secure system configuration. AN does not save request headers or raw error responses. It records HTTP status, bounded error category, model, prompt/input fingerprints, time, and available token usage/cost estimates. Refusal, truncation, or unverifiable output is not silently accepted as success. Valid JSON does not guarantee scientific correctness. Network failures additionally record `transport_error_type` such as `ConnectError`, `RemoteProtocolError`, or `ReadTimeout` to distinguish connection, protocol, and response-waiting failures without recording exception text or keys.

Cost settings include `currency`, `input_cost_per_million`, `output_cost_per_million`, and optional `cached_input_cost_per_million`. Without a cached-input price, ordinary input pricing is used conservatively. `budget.max_cost` uses the same currency. The current example conservatively uses official peak uncached prices checked on 2026-10-25: CNY 2 per million input tokens and CNY 8 per million output tokens. This is not a future-price commitment; see [official pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/). A configured cache price applies only to cache-hit tokens actually reported by the provider. Missing detail is not used to guess cache volume. There is no automatic time-of-day pricing switch; a run spanning price periods should use peak prices for budgeting and be reconciled with the provider bill.

Before a call, AN reserves cost from UTF-8 input bytes, up to 1,024 input tokens per image, and the full maximum output. The image bound follows [official image-usage documentation](https://api-docs.deepseek.com/zh-cn/guides/vision/) checked on 2026-10-26; image quality/output allowance is not reduced. Complete usage settles an estimate using the configured rates while preserving the original reservation. A failed/timeout call with incomplete usage continues to occupy its reservation because it may have been billed. This is a conservative program budget, not the provider's billing hard cap. `max_cost` and `max_calls` limit one run; reruns have their own budgets. Cross-task totals must be accumulated separately. Missing usage is explicitly unknown, not zero cost. There is no automatic top-up or model routing.

Defaults are `reasoning_effort=high`, temperature 0, output allowance 65,536 tokens, and timeout 300 seconds. For long material, explicitly set `model.timeout_seconds` up to 600 seconds. This changes waiting time only; cost/call limits remain. Extraction, review, revision, and cross-paper comparison share the task's model configuration; examples also use high. Explicit old-task settings remain honored rather than silently altering historical experiments. `max_output_tokens` includes reasoning tokens and cannot be estimated solely from visible JSON. Development calls with high/24,000 also truncated, prompting the larger default; this alone does not establish better accuracy. `model_incomplete` retains the truncated candidate/reason rather than success. A larger allowance raises the pre-call reservation, still bounded by max_cost/max_calls.

For cumulative evaluation across tasks, use the repository script with one common output root for all relevant runs:

```powershell
python scripts/run_v08_evaluation.py task-a.json task-b.json --output-dir research-evaluation --max-total-cny 100 --allow-remote
```

The script runs serially with an OS file lock so multiple evaluations cannot spend the same balance concurrently. Reservations are recorded before HTTP; spent and unknown-billed calls count toward the cumulative limit. Independent `research run` outputs elsewhere do not automatically enter that ledger. Verify the provider's actual bill separately.

Once you have a bill, replace the cumulative estimate through the current checkpoint with its amount. First finish runs using the ledger and verify that the bill's time and API-key scope cover existing calls. Then run this separately; the amount is an example:

```powershell
python scripts/run_v08_evaluation.py --output-dir research-evaluation --max-total-cny 100 --record-provider-bill-cny 40.45 --bill-note "服务商账单覆盖当前已有调用；已核对时间和API Key范围"
```

This records local cost only and makes no model call. `provider-bills/` preserves each reconciliation checkpoint and fingerprints of covered calls, without rewriting run manifests. Later budgeting uses “latest bill + estimates of calls after its checkpoint”, avoiding double-counted old reservations; new unknown usage retains its reservation. A subsequent cumulative bill creates a new checkpoint and keeps the old one. Provider/local request counts may differ due to failures or reporting delay; AN does not claim transaction-level matching or apply an additional peak/off-peak discount to the billed amount.

## Four uses of one task contract

### Optional DeepSeek multi-round review (experimental)

Set `max_review_rounds: 1` in the task `budget` to enable extractor/reviewer roles; the maximum is two rounds and the default is 0. The reviewer checks at most four field/step targets per group against source material, hiding unrelated old fields, and separately checks coverage and claims. The extractor checks the source again and returns only targets needing revision, which AN merges into the retained result. Both roles use the same model configuration, without GPT, another provider, or an Agent framework. Agreement is not scientific correctness. With `include_steps: false`, no step-review targets are created for an unrequested empty procedure.

Review v5 separates ordinary missing fields from a missing whole record/experimental stage. Ordinary revisions open only identified or uncertain fields, steps, and claims; unrelated values, contexts, and citations stay unchanged. Step revisions may adjust associated step_ids without rewriting other fields; merged links are revalidated. Only a missing whole object/stage or an overall structural problem uses the explicitly recorded full-revision branch. When all targets need no change and old/new diagnostics are empty, the revision call is omitted. A candidate retaining issues/page requests can have diagnostics rechecked without rewriting fields. This engineering mechanism reduces losses from rewriting; it cannot guarantee the reviewer finds all omissions or gives correct advice.

One review round normally contains multiple HTTP calls. Two seven-field records, steps, coverage, and a few claims commonly require five review calls and one revision, in addition to initial extraction, network retries, and format repair. Start, for example, with `max_calls: 16`, `max_review_rounds: 1`, and a cost cap suitable for the document count. All calls share one budget. On exhaustion, invalid source/page, or incomplete review coverage, the preceding valid candidate remains and the run is PARTIAL. Failed review is not cached as successful and is retried on rerun; successful cache reuse retains its complete review history. Imprecise quotation/block matching keeps the result and original-page access without a verbatim-match retry.

Each round preserves input/feedback/output, local patch, grouped candidates, and rejection reasons; the manifest records versions and before/after fingerprints. Review cannot mark human confirmation or overwrite PDFs/parsed artifacts. New page requests raised after supplementation budget is exhausted remain pending rather than being called read. Cache restoration replays local patches and validates the merge; older review protocols are not treated as v5 successful caches. Current issues/requests describe unresolved items after revision. Corrected omissions and rejected review suggestions remain in feedback history instead of being reinserted by the program into current issues. This does not establish that the model solved the issue; check the science.

### Local images for small text and charts

Set `image_layout: "page_and_tiles"` for a document and select `image_pages` in hybrid/direct mode. Each page yields a 3200-pixel-long-edge overview and four overlapping crops, counted as five images. PDF identity, page, image hash, view type, and normalized top-left-origin region coordinates are retained. Crops remain evidence from that page; overlap is not independent evidence, and page-level visual citations still require checking.

The implementation reuses Poppler without a new image-library dependency. Exceeding max_images or the 48 MiB inline request-body limit fails before sending. DeepSeek rescales large images before inference, so crops may retain finer text; greater clarity alone does not prove more accurate extraction. See [official image documentation](https://api-docs.deepseek.com/guides/vision/) and the [accuracy-improvement record](V08_ACCURACY_WORK.md).

Task `type` is `organize`, `extract`, `procedure`, or `compare`, all using one engine. `objective` states the research question. Each `fields` entry has a unique `id`, semantic `description`, and type. Supported types are string, number, integer, boolean, and string_list, with optional label, unit, and scope. A unit is an expected description, not automatic conversion. Define object, conditions, and scope explicitly. Smaller fields can ease checking but do not guarantee completeness or accuracy. Paired development tests retained condition mismatches after splitting and introduced extra citation-validation failures; compare configurations on a few source-based tasks first.

Each document `id` is short and unique within the task. Document options are:

| Setting | Purpose |
| --- | --- |
| artifact | Existing canonical parsed file; read-only, with source reverification |
| pdf / sidecar | Explicit originals for relocated artifacts or original-page reading |
| pages | Selected PDF pages, 1-based, not printed article page numbers |
| image_pages | Original-page images to send, hybrid/direct only |
| image_layout | Default page; optional page_and_tiles adds four overlapping crops |
| notes | User context, not original-source facts |
| corrections | Task-level manual reading overlay, described below |

Main text and SI use separate document IDs, PDFs, and page numbers. Registered SUPPLEMENT sources are grouped with main text using the existing parent hash. SI must be listed explicitly; a model cannot read an unauthorized file.

Task `query` uses existing library search to select context; explicit `pages` take precedence. `context_pages` controls neighboring pages. Without query/pages, AN attempts the whole text. Exceeding the budget fails clearly: narrow scope or change the budget rather than accepting silent truncation. The package keeps full traceability; repeated geometry/diagnostic views are removed from the model-facing representation.

Use natural-language `rules` to preserve differences, distinguish stages, and select output language. `synthesize=true` adds cross-paper organization after per-paper extraction. Comparison still cites original sources, and its failure does not erase per-paper results.

For notes/tables only, set `"include_steps": false`, requiring each record's `steps` and every field's `step_ids` to be empty. This enters model constraints and local validation rather than relying only on prose. If steps are still generated, the existing single repair opportunity applies; another failure is explicit instead of deleting steps and calling it success. `true` permits source-supported steps but does not require invented procedures for papers lacking operations. Omission preserves the legacy permission for steps. Old results remain readable/revisable/exportable. Changing this setting changes the task fingerprint and prevents incompatible cache reuse.

If fields/steps suffice without additional per-paper scientific claims, set `"include_claims": false`. The model must still answer all configured fields and retain missing information, ambiguity, and material requests. Per-paper `claims` is constrained to empty rather than silently deleted after generation. This does not disable `synthesize=true`; comparison may still produce source-linked synthesis claims. Omission/`true` retains prior behavior. A changed option invalidates old cache compatibility without changing old files. Extraction instructions are not injected into the review checklist or targeted-revision replacements; those phases follow their own structures. This controls scope, not a proven universal accuracy gain: completed small new-paper comparisons did not improve whole records and showed local regression.

`export_formats`, for example `["markdown", "csv"]`, chooses derived exports. Allowed values are markdown, csv, and jsonl; omission selects all. Lists must be nonempty and unique. Raw result JSON, task, and manifest are always retained. Local mode has no extracted fields: it saves source-material reports/packages, not a fabricated result table.

## Processing paths and material supplementation

Extraction prompt v13 states that “not human-confirmed” images may still be read. When a clear original page conflicts with parsed text in a symbol or number, the model may use the page reading in a derived result, record both readings' difference in that field's `context`, and cite the original page. Unreadable content remains uncertain; AN does not guess characters from common knowledge, rewrite the PDF/canonical artifact, or call an image reading human-confirmed. Existing full-page images can serve this check; use crops if details are unclear. There is no evidence that every task should send every page as tiles.

- local: build local task packages only; zero remote calls.
- parsed: send selected v0.7 text/table observations only, for a text baseline.
- hybrid: text plus explicitly selected images; requested supplements add corresponding text/page images.
- direct: send selected original-page images without parsed text; an explicit pdf needs no parsed artifact.

Original-page modes require Poppler's `pdftoppm` on PATH. A single page is rendered using CropBox at 1600 pixels on the long edge, with up to 60 seconds waiting; readability still needs checking. `verify_original=true` requires image input for selected pages. The first implementation does not upload PDF files or automatically scan a whole paper visually.

Hybrid text/image pages can be independent: `pages=[1]`, `image_pages=[2]` sends parsed page 1 and original image page 2, without page 2's parsed text. Material builder=3 records their union in pages_requested; inspect blocks for actual text and images for actual images. Image pages can use block_id=null citations and remain visually unverified. References to an unavailable block on that page fall back to page-level checking; an image is not recorded as provided parsed text. Parsed pages also support block_id=null. Old packages/results remain readable, while the new material identity prevents reuse of caches with the old coverage logic.

If a model labels an SI page as main text, AN corrects `source_id` only when the page exceeds the original PDF's total pages, main/SI identity is bound, and the same page/block/quotation has a unique match in the supplied family. It does not change page, block, quotation, or science. `citation_source_resolution` retains the original citation/change; Markdown flags it and records/claims remain unconfirmed. Unknown sources, real but unprovided pages, missing blocks, and multiple matches are not resolved by guessing.

Models can request pages within task scope. `max_supplement_rounds` defaults to 1, maximum 3, also bounded by max_images, max_input_characters, max_output_tokens, max_calls, and max_cost. No new material means no repeat call. Missing files, rendering failure, or insufficient budget retain the current candidate and reason; unresolved gaps are left for the user. The model cannot rewrite PDFs or run arbitrary parsing commands.

For unavailable SI or material with unknown page numbers, a model may store a request using an existing document ID, `pages=[]`, and an explicit `reason`. Extracted results remain, with run `PARTIAL` and supplement `needs_input`; Markdown lists pending material. This does not automatically read files or repeatedly call a model on identical resumption. Register and add supplied SI to the task, then rerun; material changes invalidate old cache compatibility. Unknown document IDs, out-of-range pages, and empty reasons are not valid requests.

After supplementation, AN extracts the full task again from current material, passing earlier unresolved questions and current/new text/image coverage without feeding the entire old answer back. The old candidate remains in the run directory and can be retained with its original package if supplementation fails. This reduces carryover of earlier “not provided” judgments but does not guarantee good use of evidence or equate coverage with scientific support. Current extraction prompt v13 and review v6 are isolated from older caches; old results remain available offline.

Distinguish a need for neighboring pages/SI, a new parsing artifact, and a revised model task. Do not keep adding parser rules merely because a model cannot extract. `PARSED` is not correct scientific understanding.

If small headings are joined to body text, reparse using the updated parser into a new directory and point a new task to the artifact. The parser keeps block boundaries at major font changes without declaring every font change a section heading. Do not overwrite old artifacts: reparsing can change block IDs, and old extraction results must keep their original artifact. A new task uses the new material identity rather than the old extraction cache.

Parser 3.10.18 rejoins caption continuation lines when font, size, line spacing, and original-caption scope provide explicit layout evidence, retaining short tails, original positions, and uncertain readings. Body references to figure numbers are disambiguated first, so a longer joined body reference cannot replace the true caption. Similar caption/body styles, missing font data, or captions dominating a page may still leave separate blocks; this does not guarantee complete vector regions or extraction correctness. To apply it, save a new artifact:

```bash
aletheia-nexus parse paper.pdf --output revised/paper.parsed.json
```

Point the new task to that path, preserving the old artifact/run rather than adding `--overwrite` over historical sources.

Parser 3.10.19 uses actual inter-column whitespace where supported by layout to organize multi-column body text, preventing a three-column page's center column from being split between left/right groups. Mixed pages can identify an independent three-column body region through dominant text style. Captions, in-figure text, and tables retain their own boundaries. Spanning text that blocks whitespace, insufficient column evidence, or undetected text tables can still prevent full order recovery. This improves material organization only; field accuracy requires separate testing.

Parser 3.10.20 extends μ readings already established by embedded font glyphs to μmol and joined compound units. It does not infer units from values/domains or convert every ordinary mmol/mL to micro-units. Original readings, evidence, and uncertainty remain. Apply it by saving a new parsed artifact as above and updating task references. Old PDFs, artifacts, and AI results are not rewritten; a parser fix is not a new validation of extraction accuracy.

Parser 3.10.22 connects separately drawn borders of fully ruled native tables using their actual stroke widths and splits cross-column text at confirmed physical cell boundaries. Wrapped decimals/formulae remain original fragments; a cell can contain multiple fragments. AN does not fill decimals, blank values, or chemical formulae. Merged headers keep their row/column spans. Open borders, unrecognized captions, or image-only tables may still prevent relationship recovery, requiring original-page checking. This affects new parsing only: save a new artifact/update references while preserving old material/results.

Parser 3.10.23 also recognizes dotted `Tab.` and `Supplementary Tab.` captions using the same table logic; body references such as “Tab. 2 shows…” are still not captions. Original caption text and main/SI numbering spaces remain. Cross-page continuation, caption continuation, and shared conditions still need checking; detecting a table does not prove these relations are fully recovered.

For a critical number/formula, save a small-field extract task selecting the relevant original pages, compare parsed/hybrid output, and retain the original batch. Development checks using such narrow tasks corrected approximate-sign, formula-subscript, and element-assignment errors in visual reading. Increasing image resolution or reasoning effort did not show stable benefit. This is a checking method, not automatic scientific certification or a reason to discard other differences.

To review an existing claim, copy the [source-support review example](../examples/research-source-review.json), supply source paths/pages and the candidate claim, and record old result ID/field in notes. The default is local; change to parsed and explicitly enable remote use, still through `research run`. For original images use hybrid with image_pages. Prefer one explicit claim per task to avoid paired candidates suggesting answers. supported, contradicted, and insufficient are model assistance labels; read context/citations too. Development checks found a case where the explanation identified a wrong object but the label still said supported. Do not use the label to automatically delete, rewrite, or confirm old results. Reviews are independent derived records.

For a manual reading correction, add this object to that document's `corrections` list:

```json
{
  "block_id": "从该工件复制真实块ID",
  "original": "完整原始块文本",
  "replacement": "修订后的读法",
  "reason": "修订所依据的原页和理由",
  "author": "修订人",
  "at": "2026-10-25"
}
```

original must exactly match the source block. The old reading remains. Changing the task creates a new material fingerprint/result rather than hitting the old cache. Supplementing pages changes the derived package, not the canonical parsed artifact.

## Results, recovery, and revisions

Each run creates `runs/<运行ID>/` containing task.json, manifest.json, per-document package/candidate/result JSON, page images, and report.md/table.csv/records.jsonl. The report presents organized content, fields, steps, and lightweight citations; detailed diagnostics stay local. CSV guards against executing model text as spreadsheet formulas, with raw values/units retained in structured records. When csv is selected and results contain independent/cross-paper claims, AN also produces `claims.csv`: claim text, nature, review status, result ID, zero-based claim_index, and source citations. `result_id + claim_index` links a claim to its revision target. Assistant revisions do not become human confirmation. Existing `table.csv` contains structured field records only; exporting a claims-only comparison may leave it with headers only, so read `claims.csv`. No claims or no csv selection means no claims.csv.

```powershell
aletheia-nexus research export research-runs/runs/RUN_ID/comparison.result.json --output-dir comparison-export
```

The command reuses saved results without a model call. CSV retains internal field newlines; Windows does not translate already-serialized newlines again. Safe escaping and read-only source-result protection remain.

With jsonl selected and independent/cross-paper claims present, `claims.jsonl` also saves claims, nature, sources, result identity, and review status. `records.jsonl` continues to contain field records only for existing scripts.

Fields distinguish directly reported, normalized, not reported in supplied material, ambiguous, and unconfirmed information. Claims separately distinguish direct reporting, author interpretation, and AI synthesis. Different objects/stages occupy separate records, and conditions link to steps through step_ids. A summary with no single original value may have an empty raw_value while citations preserve original readings. Numeric, boolean, and normalized fields must retain raw_value. A not_reported field has value/raw_value/unit all null and its reason in context. Qualitative “ambient temperature” can be reported without a number. Only `status=not_reported` with all three null also permits `nature=null`; it is retained and shown as unspecified, not inferred to be source reporting or AI synthesis. Other statuses, steps, and claims still require nature. This compatibility does not validate a missing-information judgment or weaken citation checks. `value` follows the configured type; string fields may contain full qualitative descriptions/notes. reported/normalized values cannot be null/empty. context adds scope, qualifications, or normalization explanation and cannot replace the answer. AN never moves context into value automatically; raw candidates stay intact. An existing step ID does not prove a scientifically correct link.

AN validates paper identity and provided pages. Exact block/quotation matching is a location-quality signal, not a whole-result pass gate. Mismatched text, including word breaks, empty quotations, or missing block IDs retain the candidate and real-page entry as requiring review. Uncited fields/claims are also retained for review; every item need not have a verbatim quotation. In JSON, parsed-quotation-unverified means unmatched text and page-unverified means page-only location. Whitespace/typographical ligatures are equivalent; minus signs, subscripts, superscripts, and units are not rewritten, preserving the model's original reading. Visual citations always require review. A valid citation location is not proof that it supports a claim. Reports collapse review items while JSON keeps full details.

If an auxiliary `issues` source/page is invalid, the original issue/location is retained. `validation.unresolved_issue_locations` marks it unlocated and pending rather than discarding usable fields. Markdown explains the missing location; JSONL keeps the issue/diagnostic; CSV source columns still derive only from field citations. AN does not guess another SI or make a source link for the invalid position. Field/claim citations and supplement requests still undergo source/page validation. Human/assistant issue revision rechecks the location and retains history.

`max_repair_rounds` defaults to 1 and can be 0. For a structural error or nonexistent source/page, the model receives at most one specific error response to correct using the same material. This differs from max_supplement_rounds page supplementation.

If a fully completed response is missing only closing brackets, AN first tries bounded reversible local recovery, accepting it only when native structural validation admits a unique interpretation. No field values or model calls are added. Response metadata retains original text, insertion points, and recovery version, replayed during cache validation. Truncation, ambiguity, or missing required content still fails clearly. Syntax recovery is not confirmation of science or citation support. Error feedback lists actual location failures and may suggest matching positions within the same supplied paper. Text differences or imprecise blocks do not trigger repair. AN does not rewrite readings, move them to another paper, or enlarge the actual input scope automatically.

Duplicate/empty IDs on different records only cause assignment of unique record IDs, without changing fields, stages, steps, or calling the model again. The original candidate remains; manifest `record_id_adjustments` contains before/after IDs and the raw candidate fingerprint, preserved on cache reuse. Ambiguous step associations are not guessed. Repair/supplementation share the total budget. Authentication failure, refusal, and truncation are not blindly repeated; failed candidates remain as rejected files. Retained candidates can still contain scientific errors, so validation/export success does not replace source checking.

Rerunning the same command rechecks files/input fingerprints, reuses valid results, and retries failed papers without reusing incompatible tasks, prompts, provider settings, materials, or user notes. `--no-resume` forces a rerun. Completed results survive interruption. For status=PARTIAL, inspect manifest reasons first; missing parameters or source ambiguity can be useful partial output rather than a reason for repeated paid calls. Repeated requests for already-provided material preserve a reusable PARTIAL state, not full success. Valid PARTIAL results with exhausted supplementation are also reused for the same task. To continue, increase `max_supplement_rounds` or explicitly add material; this changes the fingerprint while preserving partial results/history. Use `--no-resume` only when an identical-condition extraction is actually intended.

Offline re-export:

```powershell
aletheia-nexus research export paper1.result.json paper2.result.json --output-dir edited-export
aletheia-nexus research export paper1.result.json --output-dir csv-export --formats csv
```

`--formats` changes this export only, not the original result or model calls. Omission uses the first result's task settings. Prefer this command when changing formats instead of modifying a task and rerunning extraction.

Results with the same question, field definitions/types, and rules can be merged across document scopes or processing modes, for example parsed for one paper and direct for another. Each record retains result/material identity, including result_id in CSV. Same-named fields with different meanings are not conflated. One source ID with different PDF hashes prevents a merge. Original-page access rechecks the local PDF hash and warns when the file has changed.

If results do not cover all task documents, the Markdown header lists included counts and missing source IDs. Offline merging calculates the union of input-task document scopes, counting SI separately. This is coverage information, not a success rate: absence can mean failure or deliberate partial selection and must not mean “not reported”. Detailed failures remain in the original manifest.json; CSV does not invent failed records.

Field `context` preserves scope, stage, and necessary qualifications. Markdown shows an explanation below the value; CSV adds `字段.context` after each field's value/raw_value/unit/status; JSONL retains the whole field. Scripts should read named columns rather than fixed positions. Old results can be re-exported without model calls. Explanations are escaped as text like other model output and cannot execute links, HTML, or spreadsheet formulas.

Field `step_ids` denotes the steps in that record to which a condition applies. Markdown displays linked step numbers. CSV appends each `字段.step_ids` and `steps`, storing JSON arrays and full step objects including original IDs, order, content, nature, and citations. Empty arrays remain empty rather than applying to all steps; same-named steps in different records are not merged. This exports existing relationships without proving them correct or supplying missing links.

For a human revision, copy the complete target record into revision.json replacement, with record_id, author, at, reason, and boolean confirm. Run:

```powershell
aletheia-nexus research revise paper1.result.json revision.json --output paper1.revised.json
aletheia-nexus research export paper1.revised.json --output-dir revised-export
```

The revised result retains parent result ID, prior content, and reason. confirm=true is the user's explicit confirmation of the whole record. Model responses have no human-confirmation field. Existing output targets are refused, and original PDFs, sidecars, and canonical artifacts retain write protection.

Independent per-paper/cross-paper claims use the same revise command: replace record_id with zero-based claim_index into response.claims, and provide complete text, nature, and citations in replacement. The author/at/reason/confirm requirements are unchanged. Citations remain checked. A later confirm=false edit revokes that claim's confirmation without affecting other claims or records. Use confirm=true only after actual human review.

AI diagnostics can also be wrong, for example calling a misread symbol “source ambiguity”. Target a zero-based `issue_index` into response.issues, give complete kind/detail/source_id/page in replacement, and use the same revise command. Issue confirm must be false. Only that issue is replaced, without deleting/reordering indices; history retains the old one. Related fields/claims are not changed automatically and must be revised separately to keep summaries and tables consistent.

Revisions may declare `authority` as human or assistant. Omission means human for compatibility with old manual files. Assistant/script-generated model review must explicitly say assistant and confirm=false. Such revisions cannot request human confirmation, and altered records/claims remain pending or evidence-insufficient. An assistant edit revokes prior human confirmation of that changed record only. authority records provenance, not account authentication or scientific truth.

Diagnostic-revision example, using example data to replace with actual source-based content:

```json
{
  "issue_index": 0,
  "replacement": {
    "kind": "strategy_problem",
    "detail": "原页中的近似号被模型误读为负号；相关字段另行修订，旧读法保留。",
    "source_id": "paper1",
    "page": 1
  },
  "authority": "assistant",
  "author": "执行原文复核的助手",
  "at": "2026-10-26",
  "reason": "复核所选原页后修正错误归因；不是人工确认。",
  "confirm": false
}
```

## Current acceptance boundaries

Automated tests check engineering behavior, not domain accuracy. Real API connectivity, development-paper results, assistant original-page review, actual human annotation, and independent held-out evaluation must be recorded separately. The original brief's 20–30 papers/100 fields/40 records, 90% precision, and 95% support were initial evaluation targets, not achieved scores or a universal quality promise. Delivery is described through frozen experiments, generalization gains, and known limitations, without claiming completion on a hard 90% threshold. See [design/audit](V08_DESIGN.md), [evaluation definitions](V08_EVALUATION.md), and [actual acceptance](V08_ACCEPTANCE.md). The [ten-paper comparison](V08_TEN_PAPER_COMPARISON.en.md) separately explains AN versus native browser PDF reading, including scope, models, and historical-answer limits; it is not a new independent held-out evaluation.

## Input fidelity and format recovery

Current input retains all selected original text/tables and consolidates repeated parse warnings for the model while keeping complete diagnostics in the local package. Lack of automatic image transcription does not mean the model cannot read a supplied original page. Visual readings still require checking. Paragraphs near a caption remain context instead of being merged into captions or rewritten automatically.

If a model adds an out-of-contract empty-array property, such as an empty ordering hint, AN normalizes the structure while retaining the entire raw response, removed position, and original value for replay; it does not regenerate scientific answers for that issue. The same applies to unknown null properties where the object contract forbids extra properties. Legal-field null, numeric 0, and false remain unchanged; empty extensions do not count as answered research fields. Known empty citations_note in steps/claims—null, empty string, or not_a_field—receive the same treatment. Nonempty notes remain explicit errors so possible scientific content is not discarded. Existing recognized-metadata handling remains. Nonempty unknown content, missing required scientific fields, wrong types, out-of-range citations, and invalid step relations still fail or enter bounded repair. Format recovery is not correctness. A missing step_ids can reversibly become [] only to mean no association was supplied; AN does not guess steps, conditions, scientific values, or sources. Raw responses/additions remain replayable. Existing nonempty associations, wrong types, and absent scientific fields are not replaced this way. Old results stay readable/exportable; prompt/material/adapter changes isolate caches.

DeepSeek adapter v8 accommodates output members requiring a fixed empty object, such as step phases. The server uses null, locally restored to the only allowed {}, with the raw response and conversion positions retained. It affects only exact empty-object members, without inventing scientific fields, treating an ordinary missing value as known, or discarding nonempty content. This fixes request compatibility and does not establish improved extraction accuracy.

PARTIAL may contain useful results while lacking SI, retaining source ambiguity, or awaiting checks. It does not mean no result for the paper. Read output and specific gaps first; clearing diagnostics cannot prove science correct.

## Discovering DOI candidates by title through MCP

`find_paper_candidates` accepts `title_query` and optional `limit` (1–5). Enable `--enable-acquisition` explicitly on the server. Discovery is off by default, and unauthorized calls do not access the network. It sends title/citation queries only to the fixed public Crossref endpoint, not papers or local files, and makes no model call. Review/authorize its returned local request file with:

```powershell
aletheia-nexus research authorize "工具返回的authorization_request路径"
```

Use the one-time token from the local terminal as `authorization` on the original request. Candidate DOI/title/authors/journal/year are unconfirmed identities. AN neither picks the first nor downloads automatically. After selecting one, the client passes DOI/optional title to existing `acquire_documents` and obtains separate acquisition authorization; discovery tokens do not authorize downloads or models. No model key is required. Timeout/service failure and no candidates have distinct statuses. Requests/results stay under local `discovery/`; existing DOI acquisition and source verification remain unchanged.

## Preparing a document batch in the MCP background

See [natural-language/MCP entry points](V08_ENTRYPOINTS.en.md) for installation/configuration. For many documents, ask the client to prepare PDFs in the background, report per-paper progress, and draft a task from successfully prepared papers. `prepare_documents_job(paths)` immediately returns a `job_id`, then `get_run_status(job_id)` tracks it rather than blocking a single tool call until all parsing finishes.

`completed/total` counts processed/selected documents including failures. `latest_document` and `items` retain per-paper result, parse_status, and reused status. A terminal result includes task-ready documents, failures, and local preparation_file. All-normal preparation is COMPLETED; usable documents with partial failure/incomplete parsing are PARTIAL; no successfully prepared document or an overall preparation failure is FAILED. Material availability is not scientific correctness.

Only explicitly selected files inside allowed directories are processed. Copies/derived artifacts are stored in the workspace without network/model calls or overwriting PDFs, source records, or existing parsed artifacts. Repeating the selection creates another job history and reuses valid source-matched parsing. After process exit, a query may show INTERRUPTED; resubmit the original selection to reuse completed papers. For reparsing/OCR, existing single-document parse_document creates a new artifact. Synchronous prepare_documents remains available.

## Querying saved planning and research runs through MCP

Without an API key, `list_research_runs(limit=20)` lists application jobs, successful/failed natural-language planning, and native research run history in the current workspace. Entries return status and available manifest_file/task_file/results/export paths. Read using `read_research_result(result)` and regenerate Markdown/CSV/JSONL through `export_research_results(results)` without a new model call. Application jobs retain their original job_id for progress.

Use `list_research_runs(directory="F:/papers/旧输出")` for an old output directory inside a configured --allow-dir or the workspace. It supplements discovery without expanding authorization. Only that directory's manifest.json and fixed structures planning/*/manifest.json, runs/*/manifest.json, and research/runs/*/manifest.json are checked. Application jobs are read only from the current workspace's jobs/*/status.json, without recursively traversing paper/experiment directories. Duplicate manifests merge by run identity; offline review views are not new calls, and costs remain attached to their owning runs rather than being summed. Damaged/unreadable manifests appear under unavailable. Discovery neither follows manifest directory instructions nor reads outside permitted boundaries.

## Preserving first-read notes (optional)

Set extraction_strategy: "source_first" and source_assembly: "preserve_readings" in research-task/v1 for one reading-model call per paper. AN then deterministically saves the model's own field assignments, readings, object scope, and scientific nature without another model assembly call for that paper. The natural-language option is `--source-assembly preserve_readings`; confirmation identifies this delivery mode.

This is for reading notes: `string`/`string_list` fields only, explicit `include_steps: false` and `include_claims: false`, and `budget.max_review_rounds` of 0. `procedure` is unsupported. One note record per paper is not a substitute for structured multi-stage experimental records. `synthesize: true` still calls the existing cross-paper model separately within the same budget.

A first reading can still misread/omit content. Fields with no assigned item remain unconfirmed rather than inferred not_reported. Unassigned entries, complete citations, and original readings stay in the linked inventory. Omission retains the normal workflow. This optional note-specific mode has not demonstrated a general scientific-accuracy gain.

## Reading original XLSX tables through MCP

In v0.8, `read_native_table(path="F:/papers/SI/data.xlsx", sheets=["Sheet1"])` reads complete selected sheets of an original workbook within permitted directories. Omit sheets for all; names must match exactly. It needs no key, network, model call, or new file and changes neither the workbook nor parsed artifacts.

It returns source SHA, sheet/cell counts, and a table_notes string. After checking attachment/main-text relation, the client can append the string to the corresponding document.notes array and use normal task validation/authorization. Reading does not bind SI or mark it VERIFIED. Material received by an MCP client is subject to that client's model/privacy configuration.

Plans retain short notes but show only counts/character lengths for long notes or table material, avoiding a full table JSON dump. This affects preview only: full content remains in saved documents[].notes and actual material and is sent after remote-task confirmation. The natural-language entry shows the task path, and MCP validation returns full task content for checking before approval. Authorization binds the full task; changed supplementary content requires reauthorization even if the preview looks unchanged.

Original numeric literals, units, coordinates, merges, formula/shared-formula declarations, existing caches, and number formats remain. AN neither recalculates formulas, infers scientific headers, nor proves cached values/interpretations correct. Original rich-text XML stays in the local workbook; returned text retains necessary content and semantic properties such as sub/superscript, without repeating formatting XML. Only XLSX cells are supported: not images, chart curves, full visual layout, or old XLS files.

Fixed limits are 10,000 populated/formula cells, 64 MiB of actually read XML parts, and 200,000 characters of complete table_notes. Unselected sheets do not consume the decompression/read budget. Exceeding a limit gives native_table_resource_limit instead of a truncated table presented as complete. When sheet metadata has been read, an error also returns available_sheets so the client can explicitly select appropriate sheets and retry. Limits are not raised automatically. Unselected material remains listed and cannot be described as read or not reported.

## Local citation-location recovery

For new results, if a quotation uniquely matches verbatim in text blocks of the same provided paper, AN can deterministically correct the page/block. Only whitespace and typographical ligatures are treated as equivalent; no fuzzy matching or changes to numbers, units, quotations, or scientific values. Repeated/elliptical quotations, image-only readings, and text absent from supplied blocks stay unchanged. An already-correct location is not redirected.

Result JSON citation_source_resolution v2 stores the old citation, new location, original block summary, and replayable evidence. Markdown/CSV/JSONL use corrected positions while keeping provenance. A valid position is not scientific support; results remain pending and are never automatically human-confirmed. Old v1 traces and valid caches stay readable/reusable without new model calls merely for a location-rule upgrade or overwriting old artifacts.
