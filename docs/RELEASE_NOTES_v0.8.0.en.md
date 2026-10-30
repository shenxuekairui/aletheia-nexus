# Aletheia Nexus (溯光) v0.8.0 — AI literature processing and a local workbench

[中文](RELEASE_NOTES_v0.8.0.md)

This document covers 0.8.0 and was prepared on 2026-10-30. The release identity is determined by its tag/commit in [GitHub Releases](https://github.com/shenxuekairui/aletheia-nexus/releases) and its actual [PyPI files](https://pypi.org/project/aletheia-nexus/). The pre-release integration branch is `release/v0.8.0`.

## What researchers can do

- **Local workbench:** select raw PDFs or an existing library. Acquisition, import, categories/tags, main-paper/SI management, previewed renaming/moves, parsing, search, research tasks and results share local services. Progress, partial completion and recoverable history remain visible.
- **Natural-language research:** describe reading goals, fields and outputs in Chinese, obtain an editable plan, then authorize its scope and budget. Planning sends necessary metadata; extraction reads paper content. They have separate authorization and accounting.
- **Reusable research materials:** save single/multiple-paper notes, custom tables, experimental conditions/steps and question-focused comparisons as Markdown, CSV and JSONL, with sources, original responses and revisions. Results can be reopened, checked and re-exported.
- **Local MCP:** the official Python SDK v2 and local stdio expose 23 tools for acquisition/preparation, parsing, search/context/original pages, research, history and results, using the same research engine.
- **Evidence and reading:** task context, associated SI, original pages/regions, native tables and XLSX reading; unique verbatim quotations within the same supplied source can deterministically recover locations. Original PDFs and existing canonical parse artifacts remain unchanged.
- **Bilingual product identity:** the workbench, browser title, CLI/MCP and introductions retain “溯光 · Aletheia Nexus”. Redirected Windows CLI output uses UTF-8; commands, package names, source schemas and existing credential identifiers remain compatible.

## Installation and entry points

Python >=3.11. Check that the desired version is available on PyPI before installing the release, or install from the selected source checkout:

```powershell
python -m pip install "aletheia-nexus[ui,mcp]==0.8.0"
# Source install: run inside the cloned project directory
python -m pip install -e ".[ui,mcp]"
aletheia-nexus ui --library "D:\文献库"
```

The GUI opens at `http://127.0.0.1:8080`. Core CLI/parsing do not require UI or MCP; the source extras `.[ui]` and `.[mcp]` are independently selectable. Browser runtimes, Poppler and OCR dependencies depend on the chosen optional path. An installed Python dependency does not prove a browser or OCR runtime is available.

```powershell
aletheia-nexus research ask "整理方法、实验条件和主要结果，生成中文比较表并保留来源" --papers "D:\论文" --output-dir "D:\科研结果" --extraction-strategy source_first
aletheia-nexus mcp serve --allow-dir "D:\论文" --workspace "D:\科研结果"
```

Keys come from environment variables, GUI session configuration or explicitly saved Windows credentials, not tasks, presets or ordinary logs. Configuring a key does not authorize transmission. MCP model arguments cannot replace independent local authorization. See the [workbench manual](WORKBENCH_USER_GUIDE.en.md) and [CLI/MCP guide](V08_ENTRYPOINTS.en.md).

## Integration fixes and compatibility

Research branch `59ce727` and workbench `b4d1002` were merged with both histories retained. The Provider keeps phase-specific scientific prompts alongside independent operations such as title translation. UI integration does not silently replace plan budgets, fingerprints or old caches. MCP reports the installed package version rather than a divergent hardcoded value.

`research-task/v1`, `parsed-document/v3` and historical results remain compatible. `direct` and `source_first` remain available. New execution of `field_independent`, which lacked a net generalization benefit, is retired; historical tasks/results can still be read, verified, revised and exported. Execution is not silently rerouted. Compact material is retained for resource management: oversized assembly may try reversible compact encoding without truncating scientific content or increasing the budget.

New AI plans default to the validated `source_first` read/assemble strategy in the ordinary workbench, `research ask` and MCP natural-language planning. A paper normally needs at least two model requests. The preview shows the actual strategy; call/cost limits are not raised automatically. Saved tasks, directly supplied client tasks and explicit choices retain their meanings. An omitted strategy in old `research-task/v1` still means direct extraction, preserving old cache and authorization semantics. Local mode makes no remote model call.

UI registration, organization and display metadata remain separate from immutable originals and source identities. Existing directories remain loadable; there is no automatic whole-library migration or overwrite. Callers of a retired strategy should save a revised task and review/authorize it again.

## Scientific quality and limits

In the common 17 valid papers of the 20-paper ABC batch, DeepSeek strict field precision/recall was 71/84 (84.52%), with 14/22 complete records; Qwen was 69/84 (82.14%), with 12/22. A separate 8-paper B confirmation gave normal source-first 21/24 (87.5%) fields and 5/8 records. This is not an overall ABC accuracy figure. All scoring is assistant original-source review, **not human expert gold**; GPT did not rewrite runtime answers.

Remaining errors include condition/object/stage attribution, required omissions, precise figure readings and falsely diagnosed source conflicts. Strict fields/whole records are different from fact-group coverage and resolvable citations. UI, schema validation and engineering tests do not establish scientific meaning. Check important claims against originals. See the [development delivery record](V08_DELIVERY_REPORT.en.md) for experiments, recovery, cost and scope.

A separate [10-paper workflow comparison with native PDF reading](V08_TEN_PAPER_COMPARISON.en.md) is complete: in the primary 9-paper view, AN scored 30/40 against the web interface's 24/40; the supplementary 10-paper view, after one zero-API recovery, scored 33/44 against 24/44. Gains concentrate on complete experimental materials; A ties and the web path does better on B. It reuses historical AN answers, the web backend snapshot is unknown, and it is neither a new holdout nor a new scientific run of the final integrated source. Its denominators are not combined with the earlier cohorts.

Major candidates underwent tiered screening; **not every variant received adequate fresh-paper generalization testing**. Automatic two-model answer selection and dynamic local-image reading still lack sufficient evidence of universal whole-record benefit. The expanded step-append cohort had no applicable missing links, which does not establish the mechanism is ineffective. Closing a queue does not prove every route useless; unverified capabilities are not performance promises.

Publisher/SI coverage depends on source, entitlement, login, challenges and file conditions. Not finding an attachment does not mean no SI exists. Whole-library backup and cross-machine absolute-path repair are not one-click operations. Complex step/citation editing retains expert entry points. The 0.7 acquisition, parsing and verification history remains intact; old scores are not described as new integrated-version measurements.

## Release acceptance

The integrated engineering, UI, MCP, package and current cloud results are documented in [integrated acceptance](V08_RELEASE_ACCEPTANCE.en.md). Old branch totals 2763/3379 and historical ten-check CI are not substitutes for the final candidate. Before merging, retain all current failures, skips and unfinished work; a changed version number alone does not mean publication is complete.
