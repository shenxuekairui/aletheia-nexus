# Aletheia Nexus

> A local-first path from a verifiable research paper to durable scientific knowledge.

[中文 README](https://github.com/shenxuekairui/aletheia-nexus/blob/main/README.md) · [User manual (Chinese)](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md) · [Contributing](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md) · [Security](https://github.com/shenxuekairui/aletheia-nexus/blob/main/SECURITY.md)

**Why this name?** *Aletheia* is Greek for truth; *Nexus* means connection. We want evidence scattered across papers, data, tools, and research practice to form trustworthy connections—so conclusions can be traced to their sources and each investigation can add to a researcher's long-term knowledge.

## Why this project exists

Research has increasingly capable models, but still lacks a dependable entry point for facts. A DOI can lead to the main article, supporting information, a login screen, a paywall, a citation, or a dead link. Finding a plausible PDF is not the same as acquiring the **correct main article with an explainable provenance**. Errors at this boundary propagate into parsers, search indexes, knowledge systems, and agents.

Aletheia Nexus (AN) begins with a deliberately testable question: *Is this locally saved file the intended paper's main text, and how did it get here?* It treats a failed acquisition as an informative result rather than quietly importing the wrong document. The larger ambition is a researcher-controlled, auditable scientific knowledge foundation that can eventually connect evidence, methods, workflows, and decisions. The current repository implements the acquisition layer, not that entire future system.

## What works today

| Maturity | Capability | Boundary |
| --- | --- | --- |
| **Implemented** | DOI normalization and Crossref/DataCite metadata resolution | External services can be unavailable or incomplete. |
| **Implemented** | Full-text candidate discovery from metadata, OpenAlex, Unpaywall, and other configured sources | A candidate URL is only a lead, not proof of access or identity. |
| **Implemented** | Bounded public HTTP acquisition and static article/landing-page expansion | No subscription or access-control bypass. |
| **Implemented** | PDF structure, DOI/title identity, and main-article-versus-supplement checks | `VERIFIED` means the file identity/role is supported, not that its scientific claims are true. |
| **Implemented** | Provenance, SHA-256, explicit outcomes, and resumable verified-file checkpoints | Sensitive browser credentials are not stored in these records. |
| **Experimental** | Official Elsevier API where configured; persistent browser sessions and human handoff for legitimate institutional access | Requires the user's actual entitlement and may need login, MFA, or CAPTCHA. One post-release source commit passed single-institution controls across ACS and Wiley; multi-institution generalization is not established. |
| **Experimental** | Sequential batch runs with browser-session reuse | Site changes and access state can still require intervention. |
| **Planned** | Structured parsing, scientific memory, knowledge graphs, and agent workflows | Not delivered by the current release. |

The first public code release was **v0.6.0**. **v0.6.1** adds publisher adapters, an installed CLI, Windows CI, and PyPI packaging without changing the frozen v0.6.0 tag. A later source commit completed a single-institution qualification; that evidence must not be retroactively attributed to the frozen PyPI release. See the [release history](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_HISTORY.md) and [pre-v0.7 readiness record](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/PRE_V07_READINESS.md) for exact scope. First-time testing by independent users remains open; the three-minute onboarding target has not yet been independently established.

## How it works

```text
DOI → metadata and candidate sources → bounded acquisition
    → PDF structure and identity checks → main-text role check
    → VERIFIED file + provenance + hash, or an explicit non-success status
```

Every access route converges on the same document validation. The browser engine handles navigation, response/download capture, challenge observation, and handoff. Narrow publisher adapters handle known article URL patterns and visible page differences; they cannot declare an article verified. A browser that displays a PDF has not by itself completed acquisition.

## Get started

Python 3.11 or newer is required. With the v0.6.1 PyPI release:

```bash
python -m pip install aletheia-nexus
aletheia-nexus doctor
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir downloads
```

The `--public-only` example does not require a browser and may legitimately report `EXHAUSTED` if no verified main article is publicly reachable. A quick local CLI smoke test is `aletheia-nexus --help`; a live DOI attempt depends on network services and access rights.

For the experimental authenticated browser path:

```bash
python -m pip install "aletheia-nexus[browser]"
python -m playwright install chromium
aletheia-nexus acquire papers.json --output-dir downloads/papers --fail-on-unverified
```

`papers.json` may contain DOI strings or objects with `doi` and optional `title`. TXT and CSV input are also supported. The installed `aletheia-nexus acquire` command replaces the old `scripts/batch_v06_download.py` invocation; that script remains as a compatibility wrapper. For all options, run `aletheia-nexus acquire --help` and consult the [detailed manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md).

Check the [PyPI project](https://pypi.org/project/aletheia-nexus/) for published versions; a GitHub source checkout or release alone does not prove that a PyPI upload succeeded. To try an unmerged development branch instead, clone the repository and run `python -m pip install -e .` from its root.

## Result semantics

- `VERIFIED`: a validated main-article PDF exists locally with traceable acquisition evidence.
- `INTERACTION_REQUIRED`: the site needs human action; the program can wait and resume when the page becomes usable.
- `ENTITLEMENT_REQUIRED`: the current legitimate session has no full-text access, or the site asks for purchase.
- `EXHAUSTED`: configured routes and budgets were used without a verified main article. This does not mean the paper is nonexistent.

The output includes per-paper status, a batch report and checkpoint, and a `.acquisition.json` sidecar for verified PDFs. Only a file that still exists and matches its SHA-256 can be reused as verified on a later run. The tool does not provide publisher subscriptions, answer CAPTCHAs, or bypass paywalls.

## Roadmap and participation

The next near-term priorities are to stabilize the acquisition architecture, make installation and first use straightforward across Windows/Linux, and obtain feedback from researchers who did not build the project. Later work will parse verified papers into source-linked objects, connect those objects to experimental context and research decisions, and expose auditable workflows to agents. These are directions, not current features.

If you are trying AN for the first time, please join the [v0.6.1 first-time setup trial](https://github.com/shenxuekairui/aletheia-nexus/issues/3). A small report is especially valuable: which DOI, which legal access route, what status AN returned, and what you observed instead. **Remove cookies, tokens, account details, institutional login screenshots, signed URLs, and copyrighted PDF bytes** before opening an issue. See [CONTRIBUTING.md](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md) and the [issue templates](https://github.com/shenxuekairui/aletheia-nexus/tree/main/.github/ISSUE_TEMPLATE).

The code is licensed under [Apache-2.0](https://github.com/shenxuekairui/aletheia-nexus/blob/main/LICENSE). Third-party papers retain their own copyright and access terms; the project license does not authorize their redistribution.
