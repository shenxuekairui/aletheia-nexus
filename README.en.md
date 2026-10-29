# Aletheia Nexus

The development branch includes an optional **local NiceGUI research workbench**.
It has not been released to PyPI. From this source checkout:

```console
python -m pip install -e ".[ui]"
aletheia-nexus ui --library /path/to/library
```

The browser opens at `http://127.0.0.1:8080`. Existing libraries remain usable.
The workbench connects acquisition, category-level shared `SI/` attachments,
library organization, title translation, previewed physical batch renaming,
saved table views, parsing, keyword evidence search, research and result review.
Remote model operations require explicit consent. Settings provide a session API key,
optional workspace-scoped Windows Credential Manager storage, and environment-variable compatibility;
keys are not written to task files or presets. New UI workspaces try public sources before an
authorized visible browser. Automatic checking after manual verification is optional and applies
to main-article waiting; an explicit pause still needs resuming, and SI challenges require a reviewed retry.
Per-paper translation, naming and parsing share the batch's translation call/cost limits;
cached titles remain usable, and uncertain billing does not silently trigger another request.
Retries can select one or several papers or fetch only incomplete SI after revalidating the main.
Identical verified PDFs with the same DOI may share a display row while their raw sources and SI remain independent.
Scientific markup is flattened only for new filename presentation, without changing source titles or human translations.
Publisher SI coverage remains partial: an unconfirmed identity, challenge, viewer response or missing link is not a successful download.
See the [workbench guide and support matrix](docs/WORKBENCH_USER_GUIDE.md),
[implementation audit](docs/WORKBENCH_IMPLEMENTATION.md), and
[acceptance record](docs/WORKBENCH_ACCEPTANCE.md). UI delivery does not establish
scientific extraction accuracy or change the existing v0.8 evaluation conclusions.

The development branch adds opt-in literature processing and field extraction with
DeepSeek Flash, with local, source-linked results. See the [v0.8 development guide](docs/V08_USER_GUIDE.md)
and [audit/design](docs/V08_DESIGN.md). This is unreleased work; the v0.7.3 release
capabilities and historical benchmark claims below remain separate.

[中文 README](https://github.com/shenxuekairui/aletheia-nexus/blob/main/README.md) · [User Manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md) · [v0.7.3 Release Notes](docs/RELEASE_NOTES_v0.7.3.md) · [Contributing](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md) · [Security](https://github.com/shenxuekairui/aletheia-nexus/blob/main/SECURITY.md)

> **From one verified paper to scientific knowledge infrastructure that can grow with research.**

Aletheia Nexus (AN) is a **local-first scientific knowledge infrastructure** project. It starts with literature: acquire and verify papers, organize them locally, and turn verified PDFs into structured data that retains its connection to the original evidence.

Give AN a DOI or a bibliography, and the result is more than a downloaded file. It records whether the file is the intended main article, where it came from, and whether its bytes have changed. Parsed content can then be traced back to a page and location in the source PDF.

The published release provides a Python package and command-line tools; the development branch adds
the optional graphical workbench described above. AN does not independently conduct scientific research.

## Why AN exists

Stronger models alone do not create reliable scientific systems. Research also depends on things that must outlast a model or platform: original data, evidence, processing history, experimental rules, tools, workflows, and the methods and judgment researchers develop over time.

Much of that context is scattered across browser tabs, download folders, scripts, notes, and conversations. AN aims to help researchers and laboratories retain reusable digital assets instead of starting again whenever a project, person, or tool changes.

The starting point is deliberately concrete: **make one paper a trustworthy, traceable, reusable local research artifact.** Build reliable tools and data first, then scientific knowledge, workflows, and agents.

> **Stable capabilities belong in tools; repeatable processes belong in workflows; genuinely open-ended decisions belong in agents.**

Human scientific judgment remains at the center of that system.

## What you can do today

AN connects acquisition, local organization, and source-linked parsing:

```text
DOI / bibliography (CNKI also accepts titles)
        ↓
Discover sources → acquire through public or already authorized access
        ↓
Verify the main article → save PDF and provenance → organize folders and tags
        ↓
Parse verified or locally registered articles and supplements → retain structure and source locations
        ↓
Cross-paper search → select evidence and condition pages → Markdown / JSONL / source manifests
        ↓
Use in your own research, LLM, RAG, workflow, or agent tools
```

| Your task | AN's capability |
| --- | --- |
| Find a paper | DOI normalization, Crossref / DataCite metadata, OpenAlex / Unpaywall / PMC and related full-text leads |
| Acquire the main article | Public HTTP, authorized official APIs, browser institutional sessions, sequential batches and resume |
| Acquire CNKI journal articles | DOI or title requests, bibliographic routing and verification; failed foreign-publisher requests are not all sent to CNKI |
| Check the file | PDF structure, article identity, main-document role, source records and SHA-256 checksums |
| Organize locally | Input folders, optional names and tags; year-journal-title naming; filter the local library |
| Read and locate content | Native-text-first parsing, optional OCR, sections, blocks, references and observed figure/table evidence with page locations |
| Use other tools | Search parsed artifacts; export Markdown, JSONL or structure-aware chunks without a model or vector-database dependency |

This is not universal coverage or a promise to download every paper. Online acquisition depends on sources, entitlement, and site behavior; parsing reports incomplete results explicitly. Scientific semantic interpretation, knowledge graphs, and autonomous research remain future work.

## Quick start

Requires Python 3.11+. Commands below are single-line examples for common shells. This README describes v0.7.3; check [PyPI](https://pypi.org/project/aletheia-nexus/) for the currently published version.

### 1. Install and check the environment

```bash
python -m pip install -U aletheia-nexus
aletheia-nexus --version
aletheia-nexus doctor
```

The base installation needs neither a browser nor a model API key. Online acquisition still needs network access: local-first does not mean every step is offline.

### 2. Try a public paper

```bash
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir downloads/first-paper
```

Look for `VERIFIED`: the PDF passed identity and main-document checks. A saved file, an open PDF tab, or a completed command alone is not proof of success. If public sources cannot provide a verifiable article, AN reports that outcome explicitly.

### 3. Use browser-assisted institutional access

```bash
python -m pip install -U "aletheia-nexus[browser]"
python -m playwright install chromium
aletheia-nexus acquire 10.7503/cjcu20250333 --output-dir downloads/papers
```

Visible acquisition defaults to an ordinary dedicated browser launch, preferring available Chrome/Edge, with an AN-owned profile and the system proxy settings. Use `--direct-connection` to explicitly bypass browser proxies. The selected network mode stays fixed throughout a task, including reconnects. AN does not read or modify your everyday browser profile. The browser stays open after the task; subsequent tasks can reuse the same session. Close the dedicated window when you finish using it.

AN can reuse existing institutional IP, campus-network or VPN access. If login or a CAPTCHA is still required, complete it in that window while AN waits. **AN does not supply subscriptions, bypass paywalls, or solve CAPTCHAs.** No browser configuration guarantees that a site will waive verification.

Use `--browser-launch-mode managed` for a program-managed browser lifecycle. On Windows / Linux x64, `aletheia-nexus browser-install` can provision a separate browser runtime. See the [User Manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md) for browser and network settings.

### 4. Acquire and organize a bibliography

Save this as `papers.json`, replacing the DOI, folder and tags as needed:

```json
[
  {
    "doi": "10.7503/cjcu20250333",
    "folder": "chemistry/to-read",
    "tags": ["to-read", "priority"]
  }
]
```

```bash
aletheia-nexus acquire papers.json --output-dir downloads/library --fail-on-unverified
aletheia-nexus library downloads/library --folder "chemistry" --tag "to-read"
aletheia-nexus library downloads/library --query "catalysis"
```

TXT files can contain one DOI per line; JSON/CSV also accept titles, authors, journals and years. CNKI requests without a DOI can use a title; supply authors and a year when possible to distinguish similar papers. See the [input guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md#2-准备文献清单) and [complete example](https://github.com/shenxuekairui/aletheia-nexus/blob/main/examples/classified-papers.json).

New files use **year-journal-title**, followed by short identity/content hashes to avoid collisions. Missing metadata is omitted, not invented. An optional `filename` sets the readable name. Existing files are not renamed, and AN does not guess subject categories with a model.

Generated acquisition records, batch reports and checkpoints default to a `json/` subdirectory. Classified folders keep their acquisition records and labels in their own `json/` directory. Legacy layouts remain readable and resumable; explicit report and checkpoint paths are respected.

Repeating a batch checks the files and provenance before resuming. You can edit tags separately without changing the PDF or acquisition evidence; replace `PAPER.pdf` with the actual path:

```bash
aletheia-nexus library tag PAPER.pdf --add "read" --remove "to-read"
```

### 5. Parse, search and export

Replace `PAPER.pdf` with the acquired file path and use that paper's real DOI. Keep its `.acquisition.json` provenance file in `json/`; legacy records beside the PDF are also supported:

```bash
aletheia-nexus parse PAPER.pdf --doi 10.1371/journal.pone.0310216
aletheia-nexus search PAPER.parsed.json "Methods" --verify-sources
aletheia-nexus export PAPER.parsed.json --format markdown --output PAPER.ai.md
aletheia-nexus export PAPER.parsed.json --format jsonl --output PAPER.ai.jsonl
aletheia-nexus export PAPER.parsed.json --format chunks --output PAPER.chunks.json
```

Parsing creates a separate `.parsed.json` artifact without modifying the PDF or acquisition record. Markdown suits reading and model context, JSONL suits data pipelines, and structure-aware chunks suit downstream retrieval and RAG. All are derived views of the same parsed artifact.

For scanned pages, install Poppler and Tesseract, then enable the optional OCR dependency:

```bash
python -m pip install -U "aletheia-nexus[ocr]"
aletheia-nexus parse PAPER.pdf --doi 10.1371/journal.pone.0310216 --ocr
```

To supplement printed figure labels, install `aletheia-nexus[image-ocr]` and add `--ocr --image-ocr rapidocr`. Image models run locally; their identity and source image locations are recorded. A length label retains its text and position, but its scientific role requires source review: a length unit alone does not establish a scale bar. Single-paper and batch parsing share model-directory, DPI, pixel-budget and paragraph-merge controls. See the [OCR guide](docs/V07_OCR.md) for setup and limitations.

Verified DOI-less papers can now be parsed. Use `import` to register local PDFs and `--parent` to link PDF supplements. Native/OCR disagreements retain both readings with explicit uncertainty. Corpus search, numbered evidence selection, condition-page expansion and export coverage are described in the [0.7.2 research workflow](docs/V072_RESEARCH_WORKFLOW.md).

## Trust means more than a successful download

The expensive mistakes in research are often not formatting errors. They are a supplement mistaken for a main article, the wrong paper fed to a model, or extracted content that can no longer be located in its source. AN treats these as data-infrastructure problems, not just prompting problems.

### Files and identity

Acquisition routes share the main-document verification boundary. Readable bytes are not enough: identity and role must match the request. Similar titles, insufficient evidence or identity conflicts are not resolved by blindly accepting the first result. Checksums allow later checks to detect changed files.

### Content and provenance

Before parsing, AN rechecks provenance, document role, file hashes and page count, plus DOI when present. Acquired PDFs require `VERIFIED / MATCH`; local imports retain `REGISTERED / DECLARED` identity without claiming automatic verification. Main articles and linked PDF supplements are supported, each with its own PDF page numbers. Parsed blocks, references and observed figure/table evidence retain source locations. Exported chunks preserve the chain:

```text
chunk → block → source anchor → PDF page and position → original paper
```

**`PARSED` means the relevant document parsing completed, not that the paper is scientifically true or all figures and scientific meaning are understood.** Incomplete work is marked with states such as `PARTIAL`.

Version 0.7.3 addresses links between values, metrics, experiment rows and conditions, OCR fusion, and local source review. Both holdout evaluations have completed; material subsequently used for repairs is exposed regression data. The second set contains 12 main articles and four supplements, totaling 673 pages. First complete-answer accuracy with the primary OCR configuration improved from 25/60 to 35/60, but the original accuracy and zero-unflagged-error targets were not met. The owner subsequently authorized closure based on practical design goals; this amendment was made after results were known. The [acceptance record](docs/V073_ACCEPTANCE.md) retains first scores, remaining errors and final verification status. AN supports local evidence preparation and traceable review; critical data citations still require checking the original page, especially small chemical formulae, incomplete experiment relationships and complex figures. Default parsing does not call AI; advisory AI interfaces remain separate from original parsing. Tests and anchors do not establish scientific accuracy. The [v0.7.2 historical record](docs/V072_PRACTICAL_ACCEPTANCE.md) retains its first 14/16 and subsequent 16/16 exposed regression unchanged.

### Access and human boundaries

`INTERACTION_REQUIRED` means a human step is needed; `ENTITLEMENT_REQUIRED` means the current session lacks full-text access; `EXHAUSTED` means the attempted routes did not yield a verified main article. These are useful outcomes, not failures to hide.

CNKI currently focuses on journal PDFs, not CAJ conversion or whole-database coverage. Recovery is bounded: AN does not pursue automation by repeatedly refreshing login pages, defeating challenges, or weakening identity checks.

### Local ownership

PDFs, provenance, parsed artifacts and labels are local files. No database, background index or model service is required. Keep companion files together when moving or backing up papers. Browser profiles may contain login state and should be protected like account information.

## Engineering principles and direction

Correctness comes before automation; explicit failure comes before silent corruption. Derived views must not overwrite source evidence. Stable data should not depend on one model or platform. Abstract real repetition rather than adding complexity for hypothetical future needs.

The current focus is a reliable literature foundation. The longer-term direction is:

```text
Trustworthy research data → verifiable tools → reproducible workflows → accumulated knowledge → contextual agents
```

Entities, methods, experimental conditions, measurements, claims and their evidence belong to a future scientific semantic layer, not a completed capability of this release.

## Verification and documentation

The project uses deterministic regression tests, real-browser fixtures, parser benchmarks and package checks. Live publisher evidence is recorded separately. Results from a particular environment are neither a universal download rate nor a scientific-semantic accuracy score.

- [User Manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md): installation, input, batches, organization, parsing, OCR and troubleshooting.
- [v0.7.3 Release Notes](docs/RELEASE_NOTES_v0.7.3.md): changes, acceptance results and boundaries.
- [Practical research acceptance](docs/V072_PRACTICAL_ACCEPTANCE.md): current research tasks, first-run and regression results, source traceability, review workload and remaining limits.
- [Release History](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_HISTORY.md): version-specific evidence and release status.
- [CNKI Guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/CNKI_AUTOMATION.md): inputs, institutional access and limitations.
- [Parsing Contract](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V07_PARSING_CONTRACT.md), [Architecture](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V07_ARCHITECTURE.md), [OCR](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V07_OCR.md): integration and technical boundaries.
- [CI Architecture](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/CI_ARCHITECTURE.md) and [Benchmarks](https://github.com/shenxuekairui/aletheia-nexus/blob/main/benchmarks/README.md): reproducible engineering checks.

## Participate

Reproducible bug reports, legally shareable fixtures, institutional-access feedback and first-use experiences are welcome. Share onboarding feedback in [Issue #3](https://github.com/shenxuekairui/aletheia-nexus/issues/3); see [Contributing](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md) for development guidance.

Do not post copyrighted PDFs, cookies, tokens, institutional login screenshots, signed URLs or unredacted local paths in public issues. Follow the [Security Policy](https://github.com/shenxuekairui/aletheia-nexus/blob/main/SECURITY.md) for security reports.

Code is licensed under [Apache License 2.0](https://github.com/shenxuekairui/aletheia-nexus/blob/main/LICENSE). Papers and other third-party content retain their own copyright, licenses and access conditions; AN's license does not grant redistribution rights to them.

*Aletheia* means truth; *Nexus* means connection. AN is not trying to become a smarter download script, but scientific data and knowledge infrastructure that can be trusted over time: **so that every conclusion has a path back to its evidence.**
