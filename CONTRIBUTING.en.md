# Contributing to Aletheia Nexus (溯光)

[中文](CONTRIBUTING.md) · [Project overview](README.en.md) · [Code of conduct](CODE_OF_CONDUCT.en.md) · [Security](SECURITY.en.md)

Researchers and developers are welcome to improve literature acquisition, document reading, information organization and reuse of research materials. Specific, reproducible problems and clearly described research needs are more useful than broad success-rate or feature-count claims.

## Where to start

- Describe where your work stopped: your goal, the step reached and the result received.
- Improve the Chinese documentation and its corresponding independent English file.
- Share a legally distributable minimal example, source location or field requirement to distinguish parsing, model understanding and result-organization problems.
- Fix a general problem and add a meaningful regression check; never encode the answer to a particular paper in product logic.

Before opening an issue, check existing reports and the [user manual](docs/USER_MANUAL.en.md). Include your operating system, Python and application versions, entrypoint, input type, expected behavior and actual status. Redacted commands or a minimal reproduction are enough; uploading an entire library is unnecessary.

Do not post API keys, cookies, authorization headers, signed download URLs, institutional accounts, login screenshots, private browsing traces or papers without redistribution permission in public issues, PRs or logs. Follow the [security reporting instructions](SECURITY.en.md) for vulnerabilities or sensitive material.

## Local development

Use Python 3.11 or newer and install the optional dependencies you need in a virtual environment:

```bash
python -m pip install -e ".[dev,ui,mcp]"
python -m pytest -q
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
```

UI and MCP are optional entrypoints, not mandatory dependencies for base CLI or local parsing. Configure browser binaries and OCR executables using `aletheia-nexus doctor` and the user manual.

Real browser regressions use test-owned profiles and local fixtures, without institutional accounts. For example:

```bash
python -m playwright install chromium
AN_RUN_BROWSER_SMOKE=1 python -m pytest -q tests/acquire/access/test_browser_integration.py
```

On PowerShell, first run `$env:AN_RUN_BROWSER_SMOKE = "1"`, then the test command without its environment-variable prefix. Unexecuted optional tests must be reported as skipped. Ordinary automation should use mocks or local materials, without paid model APIs, publisher logins or CAPTCHAs.

## Implementation and validation

1. Reuse acquisition, parsing, research tasks, provenance, caching and export services. CLI, UI and MCP must not each maintain a separate research engine.
2. Solve observed problems with the smallest general mechanism. Keep publisher-specific rules in their adapters rather than continually adding core rules or frameworks for individual examples.
3. Preserve original PDFs, canonical parsed artifacts, raw model responses, failures and revision history. Save additions as traceable derivatives; do not silently overwrite history.
4. Run checks relevant to changed behavior. For low-impact documentation changes, verify content and links. Full release validation covers engineering, distributions, optional entrypoints and compatibility; test count does not establish quality.
5. Separate execution failure, incorrect answers, omissions, relation errors and uncertainty in scientific evaluation. Do not alter frozen references or denominators after observing results. Development-example improvements need further evidence from materials not used for tuning. Assistant review is not human expert gold.

For public-contract or important behavior changes, explain the problem, compatibility and tradeoffs within the user's current authorization. Do not repeatedly request permission for development, pushing or publication that was already explicitly authorized. Recheck expanded scope or a newly irreversible impact. Handle secrets and paid budgets according to actual authorization.

## Documentation and submissions

Primary documentation is Chinese, paired with an independent `.en.md` English file. Scattered translations on one page do not replace a complete counterpart. Retain both “溯光” and “Aletheia Nexus” while preserving compatible commands, package names, schemas and existing URLs.

The README introduces the overall project: its research purpose, what users receive and the shortest useful starting path. Dedicated documents carry version details, scores, failures and acceptance evidence so a changelog does not replace the project overview.

A PR should describe the user-visible behavior, motivation, checks actually run and remaining limitations. Never label an unexecuted check as passed or a package/publication as released before it exists. Do not rewrite release history, old tags or user work unless the task explicitly requires it.

First-time users can help by recording whether they could organize a paper, check its sources and find the outputs without a maintainer guiding them. Retain real difficulties; a successful demonstration is not a user study.

Code contributions are distributed under the repository's [Apache-2.0 license](LICENSE). Papers and other third-party materials retain their own copyright and access conditions.
