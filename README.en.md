# Aletheia Nexus (溯光)

[中文](https://github.com/shenxuekairui/aletheia-nexus/blob/main/README.md) · [User manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.en.md) · [Local workbench](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/WORKBENCH_USER_GUIDE.en.md) · [Research and MCP](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.en.md) · [Contributing](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.en.md)

> **From one verified paper to scientific knowledge infrastructure that can grow with research.**

Aletheia Nexus (溯光, AN) is a **local-first scientific knowledge infrastructure project**. It connects paper acquisition, local organization, structured reading, AI-assisted information processing and source review so that notes, experimental conditions, comparison tables and research history can be saved, revised and reused over time.

Starting a topic, comparing methods, preparing an experiment or writing a review should not require repeatedly searching download folders, copying passages and rebuilding the same tables. AN aims to make that work cumulative: retain where materials came from and how they were processed, then use them again for a new question.

## Why AN exists

The longer-term question goes beyond acquiring papers:

> **As AI, software engineering, workflows and agents enter research, what infrastructure lets researchers and laboratories accumulate data, evidence, knowledge, tools and methods?**

Stronger models alone do not create reliable scientific systems. Original data, evidence, processing history, experimental rules and the judgment researchers develop need their own durable organization.

Today, much of this context is scattered across browser tabs, download folders, scripts, notes and conversations. Projects end, people leave and tools change. We begin with a concrete task: **make one paper a readable, traceable, reusable local research artifact.** Reliable data and tools can then support knowledge organization, composable workflows and agent collaboration where it is useful.

> **Stable capabilities belong in tools; repeatable processes belong in workflows; open-ended decisions belong in agents. Human scientific judgment remains central.**

## What you can do today

| Your task | Materials and capabilities you receive |
| --- | --- |
| Prepare a research topic | Start with DOIs, titles, bibliographies or local PDFs; organize papers, link supplements and prepare reading materials and notes |
| Compare experiments and methods | Define objects, methods, parameters, steps and results to extract; retain original values, units, experimental scope and sources; export comparison tables |
| Investigate a research question | Search local original text, organize relevant evidence, competing explanations and open questions, then return to articles, figures and supplements |
| Maintain your own library | Import and batch acquisition, folders and tags, title translation, previewed renaming or relocation, parsed versions and local task history |
| Revise and reuse results | Move between results and source locations, preserve revisions, and export Markdown, CSV, JSONL and relevant provenance |
| Let other AI tools use the library | Call acquisition, parsing, search, research and result tools through local MCP, using the same underlying services |

Materials can accumulate through one continuous workflow:

```text
Papers and supplementary materials
    ↓
Local library: sources, folders, tags and files
    ↓
Reading materials, tables, original pages and evidence with locations
    ↓
Research question → notes / information tables / procedures / cross-paper comparison
    ↓
Check, revise and export → the next experiment, review or research workflow
```

Different research tasks share general fields and execution mechanisms; they do not require a fixed template for one scientific discipline.

## Three ways to use AN

- **Local research workbench:** a Chinese-language interface for acquisition, library management, research search, AI tasks and source review. Start with your folders and research needs.
- **Command line:** batch processing, scripts and repeatable tasks. `research ask` accepts natural language without requiring a handwritten task JSON file.
- **MCP server:** let an MCP-capable AI client compose AN's local tools. A client that already supplies a valid structured task does not need an additional planning-model call.

All three entrypoints share core capabilities, provenance and results. Your materials do not remain confined to one conversation.

## Quick start

Requires Python 3.11 or newer; a virtual environment is recommended. Install the release package and open the local workbench:

```bash
python -m pip install "aletheia-nexus[ui,mcp]>=0.8.1"
aletheia-nexus --version
aletheia-nexus doctor
aletheia-nexus ui --library "./library"
```

The browser opens at `http://127.0.0.1:8080`. Import your own PDF folder or acquire a public paper first. For CLI and local parsing only, use `python -m pip install aletheia-nexus`. To start from source, run `python -m pip install -e ".[ui,mcp]"` inside the cloned project directory.

UI and MCP are optional dependencies. Configure browser binaries, Poppler or OCR engines according to environment diagnostics and the manual; installing the Playwright Python package does not provision every browser runtime. Check [PyPI](https://pypi.org/project/aletheia-nexus/) and [GitHub Releases](https://github.com/shenxuekairui/aletheia-nexus/releases) for published versions and files. Source progress does not establish publication status.

### Start with a research request

Select papers in the workbench and describe the materials you need, or use the CLI:

```bash
aletheia-nexus research ask "Organize these papers by research object, methods, main results and limitations; export a comparison table with original sources" --papers "./papers" --output-dir "./results"
```

Review the draft task, literature scope, fields, model and budget before executing. Tasks, raw responses, provenance, results and failures are saved in the output directory for later review, revision and export.

New AI plans default to reading the materials before assembling fields; single-pass extraction remains selectable in the plan. Existing tasks retain their strategy, and the program does not increase call or cost limits for the user.

The built-in AI workflow currently uses DeepSeek. Configure a key in the workbench or the local `DEEPSEEK_API_KEY` environment variable. Planning sends your objective and necessary metadata; sending paper content requires separate authorization. A configured key does not enable remote processing automatically. Local management, parsing, search and exports of existing results need no model API.

### Acquire papers or connect other AI tools

```bash
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir "./library"
aletheia-nexus mcp serve --allow-dir "./papers" --workspace "./results"
```

Acquisition uses public sources or existing authorized institutional access. Complete logins and CAPTCHAs yourself in the dedicated browser when required. MCP uses local stdio by default, restricts document access to allowed directories and requires independent authorization for remote operations. See the [natural-language and MCP guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.en.md).

## Your materials remain local

Users control original papers, parsed artifacts, tasks, history and exports; an external model is a replaceable capability. Core local functions do not require a particular model, vector database or cloud account system. Provenance and history remain with the materials for later tools and workflows.

AI may still omit information, misread figures or confuse experimental objects and conditions. Successful parsing, a valid structured response or a resolvable citation does not establish scientific correctness. Check important conclusions against the original source, particularly complex figures, units, experimental stages and article–SI relationships. Saved review items and failures allow researchers to retain uncertainty and revise results.

See the [scientific quality notes](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_STATUS.en.md) and [latest ten-paper comparison](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_TEN_PAPER_COMPARISON.en.md) for current boundaries, evaluation methods and observed performance. Scientific evaluation is separate from engineering acceptance. Examples, assistant reviews and development-set improvements are not expert certification or universal performance guarantees.

## Documentation and participation

Primary documents are Chinese with independent English counterparts:

| Topic | 中文 | English |
| --- | --- | --- |
| Installation and common workflows | [使用手册](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md) | [User manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.en.md) |
| Graphical workbench | [工作台指南](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/WORKBENCH_USER_GUIDE.md) | [Workbench guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/WORKBENCH_USER_GUIDE.en.md) |
| Literature processing and extraction | [科研指南](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_USER_GUIDE.md) | [Research guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_USER_GUIDE.en.md) |
| Natural language and MCP | [入口与配置](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.md) | [Entrypoints and configuration](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.en.md) |
| Scientific quality and latest comparison | [质量说明](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_STATUS.md) · [十篇对照](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_TEN_PAPER_COMPARISON.md) | [Quality](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_STATUS.en.md) · [Ten-paper comparison](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_TEN_PAPER_COMPARISON.en.md) |
| Versions and acceptance | [发布说明](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_NOTES_v0.8.1.md) · [版本记录](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_HISTORY.md) · [验收](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_RELEASE_ACCEPTANCE.md) | [Release notes](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_NOTES_v0.8.1.en.md) · [Release history](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_HISTORY.en.md) · [Acceptance](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_RELEASE_ACCEPTANCE.en.md) |

Report real research needs and usability problems in [Issues](https://github.com/shenxuekairui/aletheia-nexus/issues), or follow the [contribution guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.en.md) to improve code and documentation. The community follows a [code of conduct](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CODE_OF_CONDUCT.en.md); report sensitive matters according to the [security guidance](https://github.com/shenxuekairui/aletheia-nexus/blob/main/SECURITY.en.md).

Code is licensed under [Apache-2.0](https://github.com/shenxuekairui/aletheia-nexus/blob/main/LICENSE). Papers and other third-party materials retain their own copyright and access conditions; the code license does not grant redistribution rights to those materials.
