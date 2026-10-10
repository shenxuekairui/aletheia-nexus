# Aletheia Nexus

[中文 README](https://github.com/shenxuekairui/aletheia-nexus/blob/main/README.md) · [User Manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md) · [v0.7.1 Release Notes](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_NOTES_v0.7.1.md) · [Contributing](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md) · [Security](https://github.com/shenxuekairui/aletheia-nexus/blob/main/SECURITY.md)

> **From one verified paper to scientific knowledge infrastructure that can grow with research.**

Aletheia Nexus (AN) is a **local-first scientific knowledge infrastructure** project. It starts with literature: acquire and verify papers, organize them locally, and turn verified PDFs into structured data that retains its connection to the original evidence.

Give AN a DOI or a bibliography, and the result is more than a downloaded file. It records whether the file is the intended main article, where it came from, and whether its bytes have changed. Parsed content can then be traced back to a page and location in the source PDF.

AN currently provides a Python package and command-line tools. It is not a graphical reference manager or an agent that independently conducts research.

## Why AN exists

Stronger models alone do not create reliable scientific systems. Research also depends on things that must outlast a model or platform: original data, evidence, processing history, experimental rules, tools, workflows, and the methods and judgment researchers develop over time.

Much of that context is scattered across browser tabs, download folders, scripts, notes, and conversations. AN aims to help researchers and laboratories retain reusable digital assets instead of starting again whenever a project, person, or tool changes.

The starting point is deliberately concrete: **make one paper a trustworthy, traceable, reusable local research artifact.** Build reliable tools and data first, then scientific knowledge, workflows, and agents.

> **Stable capabilities belong in tools; repeatable processes belong in workflows; genuinely open-ended decisions belong in agents.**

Human scientific judgment remains at the center of that system.

## What you can do today

v0.7.1 connects acquisition, local organization, and source-linked parsing:

```text
DOI / bibliography (CNKI also accepts titles)
        ↓
Discover sources → acquire through public or already authorized access
        ↓
Verify the main article → save PDF and provenance → organize folders and tags
        ↓
Parse verified papers with a DOI → retain structure and source locations
        ↓
Search / Markdown / JSONL / source-linked chunks
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

Requires Python 3.11+. Commands below are single-line examples for common shells. This README describes the v0.7.1 source; check [PyPI](https://pypi.org/project/aletheia-nexus/) for the currently published version.

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

Visible acquisition defaults to an ordinary dedicated browser launch, preferring available Chrome/Edge, with an AN-owned profile and direct networking. It does not read or modify your everyday browser profile. The browser stays open after the task; subsequent tasks can reuse the same session. Close the dedicated window when you finish using it.

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

Repeating a batch checks the files and provenance before resuming. You can edit tags separately without changing the PDF or acquisition evidence; replace `PAPER.pdf` with the actual path:

```bash
aletheia-nexus library tag PAPER.pdf --add "read" --remove "to-read"
```

### 5. Parse, search and export

Replace `PAPER.pdf` with the acquired file path and use that paper's real DOI. Keep its `.acquisition.json` provenance file alongside it:

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

OCR supplements missing native evidence. Missing dependencies, timeouts and incomplete extraction produce explicit diagnostics instead of false completeness. **DOI-less CNKI acquisition and verification are supported, but the current parsing path still requires a real DOI.**

## Trust means more than a successful download

The expensive mistakes in research are often not formatting errors. They are a supplement mistaken for a main article, the wrong paper fed to a model, or extracted content that can no longer be located in its source. AN treats these as data-infrastructure problems, not just prompting problems.

### Files and identity

Acquisition routes share the main-document verification boundary. Readable bytes are not enough: identity and role must match the request. Similar titles, insufficient evidence or identity conflicts are not resolved by blindly accepting the first result. Checksums allow later checks to detect changed files.

### Content and provenance

Before parsing, AN rechecks `VERIFIED` status, DOI, document role, PDF and acquisition-record hashes, and page count. Parsed blocks, references and observed figure/table evidence retain source locations. Exported chunks preserve the chain:

```text
chunk → block → source anchor → PDF page and position → original paper
```

**`PARSED` means the relevant document parsing completed, not that the paper is scientifically true or all figures and scientific meaning are understood.** Incomplete work is marked with states such as `PARTIAL`.

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
- [v0.7.1 Release Notes](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_NOTES_v0.7.1.md): release overview, upgrade behavior and boundaries.
- [Release History](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_HISTORY.md): version-specific evidence and release status.
- [CNKI Guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/CNKI_AUTOMATION.md): inputs, institutional access and limitations.
- [Parsing Contract](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V07_PARSING_CONTRACT.md), [Architecture](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V07_ARCHITECTURE.md), [OCR](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V07_OCR.md): integration and technical boundaries.
- [CI Architecture](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/CI_ARCHITECTURE.md) and [Benchmarks](https://github.com/shenxuekairui/aletheia-nexus/blob/main/benchmarks/README.md): reproducible engineering checks.

## Participate

Reproducible bug reports, legally shareable fixtures, institutional-access feedback and first-use experiences are welcome. Share onboarding feedback in [Issue #3](https://github.com/shenxuekairui/aletheia-nexus/issues/3); see [Contributing](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md) for development guidance.

Do not post copyrighted PDFs, cookies, tokens, institutional login screenshots, signed URLs or unredacted local paths in public issues. Follow the [Security Policy](https://github.com/shenxuekairui/aletheia-nexus/blob/main/SECURITY.md) for security reports.

Code is licensed under [Apache License 2.0](https://github.com/shenxuekairui/aletheia-nexus/blob/main/LICENSE). Papers and other third-party content retain their own copyright, licenses and access conditions; AN's license does not grant redistribution rights to them.

*Aletheia* means truth; *Nexus* means connection. AN is not trying to become a smarter download script, but scientific data and knowledge infrastructure that can be trusted over time: **so that every conclusion has a path back to its evidence.**
