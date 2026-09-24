# Contributing to Aletheia Nexus

Thank you for helping make research inputs more trustworthy. AN is early-stage software; small, reproducible reports are more useful than broad claims about publisher support.

## Before opening an issue

Search existing issues and the [user manual](docs/USER_MANUAL.md). State your operating system, Python and AN versions, whether the attempt used public HTTP, an official API, or a browser session, and the final AN status. For a PDF identity or role error, describe what AN classified and what the document actually is. Share a DOI only if it is appropriate to disclose.

**Do not post** cookies, authorization headers, API keys, signed URLs, institution account details, login screenshots, private browsing traces, or copyrighted PDF files. Redact local usernames and profile paths from logs. If the issue might expose a security flaw, use [SECURITY.md](SECURITY.md) instead of a public bug report.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[dev,browser]"
python -m pytest -q
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
```

Browser integration tests use a local fixture server and real Chromium, not publisher accounts:

```bash
python -m playwright install chromium
AN_RUN_BROWSER_SMOKE=1 python -m pytest -q tests/acquire/access/test_browser_integration.py
```

On PowerShell, set `$env:AN_RUN_BROWSER_SMOKE = "1"` before the last command. Live publisher attempts are not part of CI and must never require sharing credentials with maintainers.

## What makes a good change

1. Open an issue or discussion for changes to public result semantics, trust criteria, or access-policy behavior before implementing them.
2. Keep publisher-specific URL and page rules in `src/aletheia_nexus/acquire/access/publisher_adapters/`. Put publisher-neutral navigation, download capture, and verification in the shared engine and validation layers.
3. Add a deterministic regression test for every bug. A fixture must not contain real authentication state or third-party PDF bytes without permission.
4. Preserve bounded requests, URL safety checks, identity/role verification, and explicit non-success statuses. A new route is a candidate, never evidence of entitlement or a verified article.
5. Run the relevant local suite before a PR. Ready PRs must pass the project's full Linux, Windows, Python compatibility, and browser gates; draft PRs may use the documented opt-in CI label when necessary.

Write a PR description with the user-visible behavior, why the change is needed, tests run, and any remaining limitations. Keep documentation and the English/Chinese README capability labels aligned. Do not rewrite frozen release tags or mix historical benchmark numbers with current development results.

## First-time user feedback

We particularly welcome reports from researchers who have never used AN before. Try the [quick start](README.en.md#get-started) with one DOI you are allowed to access, then tell us where installation, status language, or handoff was confusing. The goal is to learn whether a stranger can reach a meaningful result without a maintainer guiding them—not to inflate a success-rate statistic.

By contributing code, you agree it will be distributed under the repository's [Apache-2.0 license](LICENSE).
