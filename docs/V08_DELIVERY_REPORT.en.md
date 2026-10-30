# Aletheia Nexus (溯光) v0.8 Development Delivery Report: Historical Snapshot

[中文](V08_DELIVERY_REPORT.md) · [Current quality and status](V08_STATUS.en.md) · [Current release notes](RELEASE_NOTES_v0.8.0.en.md) · [Latest ten-paper comparison](V08_TEN_PAPER_COMPARISON.en.md)

> This page preserves the complete development-delivery record for code snapshot `8e3e82b` on 2026-10-30. References below to `0.8.0.dev0`, a draft PR and the then-unmerged/unpublished scope are historical, not current publication authorization or release status. Use the links above for current status; these older engineering and scientific scores do not replace later acceptance evidence.

Updated: 2026-10-30. Delivery at this snapshot was `0.8.0.dev0`, tested at code commit `8e3e82b`; the final documentation commit changed explanations only. Development branch: `feat/v0.8-extraction`, using the existing [draft PR #11](https://github.com/shenxuekairui/aletheia-nexus/pull/11). At that stage there was no main merge, release tag or formal publication.

The Chinese natural-language entrypoint and local MCP shared tasks, scientific execution, provenance and results, producing local research materials from raw PDF folders. Real scientific testing was complete, but **cross-domain 90% performance had not been established**. All scientific scores came from item-by-item assistant review of original sources, **not human expert gold**; GPT did not rewrite runtime answers. The user amended that stage's completion criterion to evidence-backed general-candidate validation, useful integration and delivery, rather than an indefinite hard 90% optimization gate.

## Delivered functions and module responsibilities

| Module | Delivered capability |
| --- | --- |
| `research_app.py` | Enumerate/register/prepare documents within allowed roots, reuse parsed materials, validate tasks, show Chinese plans, handle budgets, independent local authorization and background status |
| `research_ask.py` and planner | Generate `research-task/v1` drafts from Chinese goals; separate metadata-only planning from paper-content execution in consent and accounting; save, edit, confirm or cancel |
| `mcp_server.py` | Official Python SDK v2 `MCPServer`, local stdio and 23 tools; reuse application interfaces rather than a second extraction engine |
| `processing/contracts.py`, `engine.py`, `provider.py` | Custom fields/procedures, real DeepSeek text/image input, structured output, bounded retries, cache, partial success, costs and failure records |
| `materials.py`, native-table and material-presentation modules | Task packages, context, tables, SI, original pages and regions; traceable supplements/manual corrections without overwriting PDFs or canonical artifacts |
| `source_first.py`, `readings.py` | Optional read-then-assemble processing and first-reading notes; existing reversible compact encoding for assembly over its input limit, reusing successful first reads |
| `results.py` and existing exports | Citation-location/revision history, Markdown/CSV/JSONL, local history reading and re-export |

Four general task types shared fields and provenance; there was no synthesis-specific business engine. MCP covered DOI acquisition, title candidates, import/SI binding, library filters/tags, parsing, search/context/pages, research tasks, status, results, revisions and export. Title search returned at most five candidates; selecting a DOI and acquiring it required separate authorization. Institutional login and access problems retained the existing human-assisted entrypoint.

Remote operations were disabled by default. MCP could read only allowed directories and its workspace. Independent local authorization bound the task fingerprint, scope and budget; a model-supplied `confirmed=true` was not approval. Protocol messages used stdout and logs stderr. Keys were read only from environment variables, never written to tasks, reports or ordinary logs. No database or persistent chat agent was added.

## Scientific results at this snapshot

The formal 20-paper A/B/C batch delivered 19/20 papers and 17/18 tasks with DeepSeek, versus 18/20 papers and 16/18 tasks with Qwen. Fair comparison used **17 jointly delivered papers, 15 tasks and 22 records**. Technical failures/recoveries were reported separately with all cost/time retained. Each stage fixed its first valid answer rather than selecting the best response.

| Common valid 17-paper scope | Strict field precision / recall | Correct required-information groups | Complete-record correctness |
| --- | --- | --- | --- |
| DeepSeek | 71/84, 84.52% | 133/139, 95.68% | 14/22, 63.64% |
| Qwen | 69/84, 82.14% | 131/139, 94.24% | 12/22, 54.55% |

Denominators differed for each model's entire valid set: DeepSeek had 77/92 fields, 147/153 groups and 14/24 records; Qwen had 72/88, 136/145 and 12/23. Different subsets cannot be compared directly. A literature organization, B question-driven evidence and C conditions/procedures all ran in practice. Required-fact coverage was relatively high, but complete fields and records were lower, indicating attribution, additional errors and information organization remained major bottlenecks.

A further frozen three-arm confirmation used **8 papers not used for this round's tuning, four topics and B-type comparison tasks**, with 24 fields, 56 required groups and 8 paper records per arm. All 12/12 route tasks delivered. There were 73 real HTTP attempts, including 5 exact-condition technical recoveries, and unknown usage 0. All 24 paper outputs and 12 cross-paper outputs underwent original-source review.

| New 8-paper B confirmation | Strict field precision / recall | Correct required groups | Complete paper records |
| --- | --- | --- | --- |
| Normal read-then-assemble `source_first` | 21/24, 87.50% | 54/56 | 5/8 |
| Independent field reading | 14/24, 58.33% | 55/56 | 0/8 |
| `compact` materials | 20/24, 83.33% | 55/56 | 4/8 |

This was **B-route confirmation, not overall A/B/C accuracy**. A strict field required complete mandatory information, correct attribution and no confirmed error among its other assertions. Required groups measured necessary units only and could not replace strict fields. Source ambiguity/conflicts, omissions, relation errors and minor transcription were retained separately; broad-reading sensitivities did not overwrite frozen strict scores.

Cross-paper synthesis was reviewed separately: all three arms covered 12/12 required comparison groups, while whole syntheses with all extra content correct were 1/4, 1/4 and 2/4. On two exposed difficult problems using identical text and no images, Flash and `deepseek-v4-pro` each covered 6/6 required groups and produced 1/2 fully correct syntheses. This provided no stable net benefit for a default Pro upgrade; model-specific best answers were not combined.

## Route decisions and fixes

- **Retire independent field execution.** On the new 8 papers it lost 7 correct fields and 5 complete records relative to normal processing: 0 papers improved, 6 regressed and 2 tied. Old tasks/results remained readable, verifiable, revisable and exportable. New execution explicitly rejected the retired strategy without silently switching routes or repurchasing output. Its short-field wire candidate retained offline evidence only; an unhelpful runtime module was not kept.
- **Retain compact materials for resource use.** On the same 8 first reads, actual input tokens fell 721,325→626,876, a 13.09% reduction, retaining source text, fields, constraints and images. Science lost a net 1 field and 1 record, so this was not an accuracy upgrade. Reversible compact fallback actually recovered an assembly exceeding its character limit; if it still exceeded the limit it failed explicitly without truncating science or increasing approval limits.
- **Retain same-source exact-quote location recovery.** Correct a page/block only where an exact quotation has one unique match in an already supplied source, retaining before/after values and evidence. 4 real locations recovered with zero API calls; scientific values, quotations and review-required status were unchanged. Old caches and original formal scores were not rewritten.
- **Keep original-page and region reading for actual reading needs.** Expanded comparisons did not establish universal replacement of hybrid processing. Whole pages plus fixed regions did not consistently improve readings. Tiles were not forced globally, while MCP could still read a bounded region for a task.
- **Experiment-unit merging, added review, first-reading retention, simpler schemas, typography materials and model-stage comparisons were screened.** Routes without demonstrated general net benefit were not made defaults. `preserve_readings` retained its explicit one-AI-reading draft purpose. Expanded step-link-only checking found no eligible gaps across 10 C tasks and 15 records, so no model calls were repurchased for zero applicable items. See [route revalidation](V08_ROUTE_REVALIDATION.md) and the [optimization ledger](V08_OPTIMIZATION_LEDGER.md) for positive/negative evidence.
- **Fix reliable delivery.** Unique JSON closing and recognizable auxiliary-metadata handling prevented loss of whole answers. Short file locks fixed Windows status read/write races. Changed sources/budgets changed fingerprints, while successful earlier stages could be reused. Engineering recovery was not counted as scientific accuracy improvement.

Remaining errors included confusing total amounts with components, carrier/object/stage attribution, overgeneralizing trends across different factors, and falsely diagnosing different metrics as conflicts or unreported information. Most required evidence had already appeared; simply adding thinking, output or review did not show stable benefit. New domains or stronger models should use independent frozen comparisons rather than promises that existing strict scores were sufficient.

## Actual natural-language and MCP acceptance

Starting from a folder containing a real PDF with a Chinese filename, the goal was to organize research objects, methods and authors' main results into Chinese notes and CSV. Planning sent only the goal and metadata, using 1 actual model call. The saved task did not require handwritten field changes. A local operator reviewed scope/fingerprint under the user's existing authorization before execution; the report did not pretend a human clicked approval at that moment.

The first source read succeeded and was cached, but assembly reached 103,776 characters against the original 100,000 limit; a second HTTP request was never sent. The fix reduced the request to 89,441 through reversible compact encoding, **reusing the successful first read without paying again**. The model then requested pages 6–10 of the same PDF. AN supplied 5 original-page images within the unchanged image allowance, created a new package and continued. The supplemental reading therefore had genuinely different material from the cached original input.

Delivery contained **1 record, 3 fields, Chinese Markdown/CSV, with status `PARTIAL`**. Including the original failed run, research used 4 HTTP calls at estimated **1.08986816 CNY**, without raising the original 4-call / 3 CNY budget. Metadata planning separately cost an estimated **0.015262 CNY**. PDFs, parsed materials, old tasks, successful cache, original failure and costs remained. Independent source review retained approximate figure readings and an original carrier-reference conflict; functional delivery was not scientific-gold acceptance.

An **actual stdio subprocess using official SDK 2.3** then completed the 23-tool handshake and workflow: submit the generated legal task → validate → generate a separate one-use local CLI grant → execute asynchronously and query → read results → re-export Markdown/CSV/JSONL. Reusing the real output cache required **0 new model HTTP calls**. A newly connected session with no API key or remote enablement actually read documents, source pages, diagnostics, history and results and re-exported, with 0 model calls. No natural-language conversation in a particular desktop AI host was claimed.

The first private acceptance wrapper incorrectly assumed there could be only one source read and asserted after legitimate page supplementation. Its logs were retained. Root reconciled the unchanged native manifest with zero API calls and confirmed actual delivery. The model was not rerun and the failure was not overwritten to repair that wrapper.

## Simplest usage at that stage

With Python >=3.11, install from the source directory; add the optional extra when using MCP:

```powershell
pip install -e ".[mcp]"
$env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
aletheia-nexus research ask "整理这些论文的方法、实验条件、主要结果与局限，生成中文对比表并保留来源" --papers "F:\papers" --output-dir "F:\results\an08" --extraction-strategy source_first
```

First authorize sending the instruction/metadata, then review the Chinese plan, scope and budget before execution. Save, edit or cancel as needed. A missing key produces an explicit error rather than pretending to understand the request. `--max-calls`, `--max-cost` and `--max-input-characters` set explicit limits. Changing a task creates a new fingerprint, so old approval cannot approve a changed budget. Image preview describes initial pages; hybrid mode may supplement original pages within the same documents and existing budget.

Start local MCP:

```powershell
aletheia-nexus mcp serve --allow-dir "F:\papers" --workspace "F:\results\an08"
```

Replace Python, document and workspace paths in the copyable [Windows stdio configuration](../examples/mcp-stdio-windows.json). Remote models are not permitted by default; use the [entrypoint guide](V08_ENTRYPOINTS.en.md) for environment configuration and independent local authorization. Never write keys into client JSON. Remove the client entry or stop its stdio subprocess to disable it; no public service is involved. See the [research guide](V08_USER_GUIDE.en.md) for more usage.

## Engineering, costs and compatibility boundaries

The ordinary full suite at code snapshot `8e3e82b` reported **2763 passed, 0 failed, 119 skipped in 100.68 seconds**. Another 111 real headless browser tests had already passed on identical relevant source/test Git trees. Evidence was reused without claiming a rerun. 8 cases remained unexecuted: visible browser 2, external OCR 2 and Windows symlink privileges 4. This was not one “2874 passed / 8 skipped” run.

The snapshot's wheel/sdist build, Twine, installation, version, CLI help, doctor, pip check and installed-package real SDK protocol passed. 8 actual legacy field-strategy results remained readable/verifiable at their original bytes. Wheel SHA-256: `2d5137fdea9eb9cbcf84b74a4eaec3abb0a0156a447b966bf6c4ce6fc044293f`. Installation used an independent project environment while explicitly reusing locally installed third-party dependencies; it was **not fresh online resolution/installation of every dependency**.

The 73 HTTP calls for the new 8-paper confirmation had per-call time-aware estimated cost **13.01384352 CNY**. 4 difficult text-model comparison calls had conservative time-aware estimated cost **2.99451620 CNY**. These were not provider charges or all historical cumulative costs. Previous network-interruption unknown-usage reservations and original failures remained; reservations were not treated as invoices, and no budget expansion or top-up occurred. Qwen was not repurchased during that finalization; its historical cost proxy remained distinct from actual plan charges.

The v0.7 acquisition, parsing, search and provenance system was retained, with compatible `parsed-document/v3` and `research-task/v1`, no overwrite of original/canonical artifacts, and no changes to published history/tags. The explicit execution compatibility boundary was the retired field strategy; historical results remained readable, verifiable and exportable. Expert annotation, unexecuted real-environment cases and desktop AI-host conversations remained possible later pre-release checks. Development delivery was not formal scientific acceptance.

## Locally verifiable evidence

Original scientific materials and raw responses remained local research data, not public repository content. Paths below are relative to the original local root `F:/AI4S/outputs/AN08_20261025`, for local review rather than mandatory public-test downloads of real papers:

| Evidence | Local path / binding |
| --- | --- |
| Common valid 20-paper comparison | `expanded-unseen-pool-20261028/formal-runtime-preparation/qwen-comparison-aggregation-20261030/quality-summary.json` |
| Frozen new 8-paper aggregate | `new8-final-aggregation-preparation-20261030/root-final-v3.json`, SHA `9acfaeac8b971dd3e70b3fcf90c29e7203d3c53cc7929628eb841743b4d08fa0` |
| Independent Sol check | `new8-final-aggregation-preparation-20261030/independent-sol-peer/peer-9acfaeac8b97.json`, 565 checks passed, 0 anomalies |
| Difficult text-model comparison | `hard-b-cross-model-development-20261030/source-review/root-ready-paired-summary.json`, SHA `b45c6263b60a757398d02fb1e3a03628a6f1a9cb3ecc8e34a60904f9fdb502a7` |
| Final engineering acceptance | `final-engineering-acceptance-20261030/converged-8e3e82b/engineering-summary.json` |
| Real CLI and cost reconciliation | `final-entrypoint-acceptance-20261030/root-native-CLI-acceptance.json` |
| SDK cached and keyless sessions | `final-entrypoint-acceptance-20261030/reuse-stdio-v2/receipt.json`, `history-stdio-v2/receipt.json` |
| Actual example exports | `final-entrypoint-acceptance-20261030/results/exports/keyless-final-73ed2d9c/` |

Further work should target complex relations, internal source conflicts and precise figure values, using new evidence for general mechanisms. Evidence-backed candidates at this stage had converged; the stage did not continue repurchasing routes without demonstrated benefit just to reach a fixed score.
