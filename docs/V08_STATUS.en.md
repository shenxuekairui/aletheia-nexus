# 溯光 · Aletheia Nexus v0.8: current scope and quality

[中文](V08_STATUS.md) · Chinese primary document · Updated: 2026-10-30

This page covers the **integrated 0.8.0 version** and is the primary current scope/quality entry point.
Official release identity is determined by [GitHub Releases](https://github.com/shenxuekairui/aletheia-nexus/releases)
and [PyPI](https://pypi.org/project/aletheia-nexus/); a source version is not proof of upload.
Old dev0, commit, PR, and then-current pending/no-publication statements remain in the [status archive](V08_STATUS_HISTORY.md).
They are historical snapshots, not current instructions; the archive retains their scores and limitations.

## One set of actual capabilities

The graphical workbench, Chinese natural-language CLI, and local stdio MCP share `research-task/v1`,
the research engine, source checks, budgets, caches, run states, revisions, and Markdown/CSV/JSONL exports.
They support literature organization, custom fields, experimental conditions/procedures, and cross-paper comparison.
Domain fields are task-defined, not a dedicated synthesis template. Acquisition, local import,
`parsed-document/v3`, search, and evidence location remain available.

- New natural-language and workbench tasks default to `source_first`: read source evidence, then assemble fields.
  First processing of new material usually needs at least two stages per paper; cross-paper synthesis is additional and caches can reduce new requests. Budgets are not raised automatically.
- Saved tasks omitting the strategy still use `direct`, without silent rewriting or incompatible cache reuse.
  `mode=local` prepares local material only, with zero remote model calls. Local history/result reading and re-export need no key.
- `compact` remains reversible encoding for input-resource use, without deleting scientific content or claiming an accuracy upgrade.
  `preserve_readings` is limited first-read note delivery; an AI draft is not a confirmed fact.
- MCP exposes 23 composable tools including native XLSX reading. Reading a table does not confirm its SI relationship or source identity.
  **SI automatically included in workbench research tasks is currently PDF only**; other acquired attachment formats are not automatically sent into research extraction.
  Native XLSX reading through MCP does not imply a corresponding automatic research-extraction control in the UI.
- Original PDFs, acquisition sidecars, canonical parsed artifacts, raw model responses, failures, costs, and revision history are retained.
  New output is a traceable derivative; AI cannot mark itself human-confirmed.

See the [workbench manual](WORKBENCH_USER_GUIDE.en.md), [natural-language/MCP entry points](V08_ENTRYPOINTS.en.md),
and [research-task guide](V08_USER_GUIDE.en.md). Neither model output nor `PARSED` guarantees scientific correctness.

## Interpreting scores

**Strict fields** require complete necessary content and correct object/stage/condition relations, also checking extra scientific errors.
Precision concerns output fields; recall concerns required fields. Omissions and incorrect not-reported assertions are not technical failures.
**Required information groups** check particular facts/relations; high group coverage does not establish whole-field completeness or correct extra inference.
**Whole records** require the necessary fields/relations to be correct together, not merely several correct values.
Cross-paper synthesis has its own denominator, separate from per-paper fields/records. Batches, task types, and common-valid scopes are not pooled.

**Execution failures** include network, service, budget, and undeliverable-format failures, distinct from delivered scientific errors.
Same-condition technical recovery preserves failures, cost, and time and uses one first-valid answer per task, not an extra sample.
If undelivered tasks are excluded from scientific scoring, valid delivery must still be reported rather than hidden.

All scores below come from itemized assistant source review, **not expert human gold standards or double-blind assessment**.
GPT/assistants did not rewrite running-model answers to improve automatic scores. Revisions remain separate from original automatic results.

## Evidence 1: the 20-paper A/B/C batch

This existing real-paper batch compares the **17 papers valid for both models**, rather than all 20 papers.

| Common-valid scope | Strict field precision / recall | Required information relations | Whole records |
| --- | --- | --- | --- |
| DeepSeek | 71/84 (84.5%) | 133/139 | 14/22 |
| Qwen | 69/84 (82.1%) | 131/139 | 12/22 |

Model-specific valid scopes and technical failures remain in [scientific acceptance](V08_ACCEPTANCE.md) and the [historical archive](V08_STATUS_HISTORY.md).
Do not add model-exclusive successes to a common-scope comparison or subtract a later batch's score as proof of a causal strategy gain.

## Evidence 2: eight new papers confirming B-task routes

Each arm has 24 fields, 56 required groups, and 8 records. This B-task confirmation does not represent all three task classes.

| Route | Strict field precision / recall | Confirmed required groups | Whole records |
| --- | --- | --- | --- |
| Normal `source_first` | 21/24 | 54/56 | 5/8 |
| Independent per-field reading | 14/24 | 55/56 | 0/8 |
| `compact` presentation | 20/24 | 55/56 | 4/8 |

All arms delivered 8 papers and their own 4 syntheses; every attempt and technical recovery remains recorded.
Independent per-field execution showed no net generalization benefit and is retired; old results remain readable/revisable/verifiable/exportable.
`compact` has a confirmed resource-presentation use, not an accuracy gain inferred from slightly higher group coverage.
See [route revalidation](V08_ROUTE_REVALIDATION.md) and the [optimization ledger](V08_OPTIMIZATION_LEDGER.md) for full routes, synthesis denominators, and decisions.

## Evidence 3: the 10-paper AN / native web-PDF comparison

See the [ten-paper comparison](V08_TEN_PAPER_COMPARISON.en.md). AN reuses historical API answers from 2026-10-29.
The web workflow generated 8 actual answers on 2026-10-30, covering 10 papers/8 tasks, with an unknown underlying model snapshot.
These are exposed materials and different dates/workflows, **not a new held-out test or scientific output regenerated by the final source code**.

| View | AN strict precision / recall | Web strict precision / recall | AN whole records | Web whole records |
| --- | --- | --- | --- | --- |
| Primary: 9 historically common-valid papers | 30/40 (75.0%) | 24/40 (60.0%) | 5/11 | 3/11 |
| Supplement: 10 papers | 33/44 (75.0%) | 24/44 (54.5%) | 5/12 | 3/12 |

The supplement adds zero-API mechanical format recovery of a historically rejected raw response, preserving scientific values and the original answer.
It does not erase the historical failure. All fields have substantive output, so precision and recall are equal in this batch.
A tasks are tied overall, B favors the web workflow, and C experimental-condition/procedure organization provides AN's main advantage; this is not universal superiority.
Across two B-task syntheses, both pass 6/6 required comparison groups, but whole synthesis is **AN 0/2, web 2/2**.
Extra inference/condition-association errors still fail a whole synthesis; group coverage cannot substitute for it.

## Main limitations and release checks

The main difficulties remain compound-field omissions, object/stage/condition mismatches, figure/table semantics, and extra cross-paper inference.
A resolvable citation does not establish support. SI visibility, table relationships, and small symbols require original-source checking.
These three evidence sets have different denominators, models, materials, and tasks and must not become one global accuracy score.
The user removed the hard 90% stopping threshold; frozen references were not changed and initial targets were not relabeled as achieved results.

See [v0.8 integrated release checks](V08_RELEASE_ACCEPTANCE.md) for integrated engineering tests, actual UI/CLI/MCP,
packages, current CI, and skip scope; an old commit's full-suite count does not replace the final gate.
Source, main merge, tags, GitHub Release, PyPI upload, and public-install verification are separate states recorded from actual evidence.
See [evaluation definitions](V08_EVALUATION.md), [scientific acceptance](V08_ACCEPTANCE.md), and [release notes](RELEASE_NOTES_v0.8.0.en.md)
for detail. The full old status text belongs only to the [historical archive](V08_STATUS_HISTORY.md).
