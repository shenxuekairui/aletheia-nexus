# Aletheia Nexus (溯光) v0.8.1 — Package-validation correction

[中文](RELEASE_NOTES_v0.8.1.md) · [Full capabilities](RELEASE_NOTES_v0.8.0.en.md) · [Current acceptance](V08_RELEASE_ACCEPTANCE.en.md)

Updated on 2026-10-30 for the `release/v0.8.1` correction. Final checks, the tag, GitHub Release and PyPI upload must be recorded separately from actual results. A version number does not replace evidence of publication or a successful public installation.

## Why a patch version is needed

v0.8.0 was merged into main and received an immutable version tag and GitHub Release. In the independent PyPI publishing workflow triggered by that Release, an installed-package test selected a cache using a broad file pattern and mistook a source-reading inventory cache for the final research-result cache. The selection depended on directory enumeration order, causing this acceptance check to fail in the installed-package environment.

The correction makes the test select the intended research result explicitly while retaining the original cache-compatibility and replay requirements. Version identifiers and documentation advance to 0.8.1. Product behavior for scientific extraction, parsing, acquisition, UI, CLI and MCP carries forward from 0.8.0. This patch creates no new scientific-accuracy result.

The change is in `tests/processing/test_json_closure.py`: identify the result cache uniquely using its result contract and the first run manifest's `result_id`, covering both inventory-first and result-first directory enumeration. Existing closure-recovery, digest/trace-tampering and cache-rebuild assertions remain, with the first-reading cache also checked for byte preservation.

## Publication status and preserved history

| Version | GitHub status | PyPI status |
| --- | --- | --- |
| 0.8.0 | Original tag and [GitHub Release](https://github.com/shenxuekairui/aletheia-nexus/releases/tag/v0.8.0) retained | Upload job skipped after installed-package acceptance failed; 0.8.0 was not uploaded |
| 0.8.1 | Publication requires the corrected commit and final checks; actual tag and Release establish status | Actual 0.8.1 files and public-install verification establish status |

The original failure and workflow records remain. An existing GitHub Release does not establish PyPI publication, and an earlier commit's green checks do not replace validation of the corrected commit. Neither v0.8.0 nor older tags are moved or rewritten.

## Capabilities, installation and limits

See the [v0.8.0 feature description](RELEASE_NOTES_v0.8.0.en.md): the local workbench, natural-language tasks and 23 local MCP tools share one research engine. New AI plans read sources before assembly; historical tasks, provenance, results and caches retain their meanings.

After the [PyPI project page](https://pypi.org/project/aletheia-nexus/) displays 0.8.1 and its actual files, install with Python >=3.11:

```powershell
python -m pip install "aletheia-nexus[ui,mcp]==0.8.1"
aletheia-nexus --version
aletheia-nexus ui --library "D:\文献库"
```

Before public availability, install from the reviewed correction checkout using `python -m pip install -e ".[ui,mcp]"`. Configure browser, Poppler and OCR runtimes for the selected capabilities. Model credentials and authorization to send content remain separate.

Interpret scientific quality through the original cohorts in [current quality and scope](V08_STATUS.en.md) and the [ten-paper workflow comparison](V08_TEN_PAPER_COMPARISON.en.md). Assistant source review is not expert human gold, historical-answer reuse is not a new holdout, and an engineering correction is not a scientific-accuracy improvement.

Actual patch tests, packages, cloud checks and publication outcomes belong in [integrated acceptance](V08_RELEASE_ACCEPTANCE.en.md). Passing counts or distribution checksums are not filled in before the checks finish.
