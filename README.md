# Aletheia Nexus

> **A local-first scientific knowledge acquisition infrastructure.**  
> 面向科研场景的本地优先科学知识获取基础设施。

Aletheia Nexus（AN）把科研知识获取拆成可靠、可测试、可组合的基础能力：对象识别、元数据解析、全文发现、访问路径解析、文件获取、论文身份验证、失败语义与来源追踪，并为后续 Content Parsing（内容解析）、Workflow（工作流）和 Agent（智能体）提供稳定底座。

当前稳定版本：

```text
Aletheia Nexus v0.5.2
Full-text Acquisition — FINAL / HARDENED / FROZEN
```

## Capability map

```text
Identifier / DOI Core             ✅
Metadata Resolution               ✅
Full-text Discovery               ✅ v0.4
Discovery Reliability             ✅ v0.4.1
Discovery Performance             ✅ v0.4.2
Direct PDF Acquisition            ✅ v0.5.0
PDF + Paper Identity Validation   ✅ v0.5.0
Route Resolution                  ✅ v0.5.1
Multi-route Acquisition           ✅ v0.5.2

Authenticated / Browser Access    → separate future capability
Content Parsing                   → next major line
Knowledge / Workflow / Agent      → later
Lab / Scientific World Model      → long term
```

v0.5 closes the **unauthenticated HTTP(S) full-text acquisition loop**. It intentionally does not absorb institutional login, browser JavaScript execution, CAPTCHA/anti-bot circumvention, paywall bypass or scientific-content parsing.

## Architecture

```text
Raw input
↓
Identifier / DOI Core
↓
Metadata Resolution
↓
Full-text Discovery
↓
FullTextCandidate[]
↓
Direct file or landing/repository/resolver route
↓
Route Resolution when needed
↓
Bounded retrieval
↓
PDF structural validation
↓
Paper identity validation
↓
Document-role validation
↓
VERIFIED main article
or explicit terminal outcome + attempt history
```

Long-term direction:

```text
Acquire → Parse → Knowledge → Workflow → Agent → Lab / Scientific World Model
```

## Core invariants

```text
Candidate ≠ File
File ≠ Valid PDF
Valid PDF ≠ Target Paper
Target Paper ≠ Main Article
Derived Candidate ≠ Verified File
Many attempted routes ≠ Success
```

Only a file that passes structural PDF validation, target-paper identity validation and main-document role validation can become `VERIFIED`.

> **宁可明确失败，也不要把错误文件交给下游科研系统。**

## Engineering principles

1. Correctness before automation（正确性优先于自动化）.
2. Explicit failure over silent wrong（明确失败优于静默错误）.
3. Stable primitives before orchestration（先稳定基础能力，再做编排）.
4. Bounded work（有界工作） for requests, retries, depth and file size.
5. Provenance over black boxes（来源追踪优于黑箱结果）.
6. Measure before optimize（先测量，再优化）.
7. No speculative abstraction（不为想象中的未来过度设计）.
8. Small, testable, reversible changes（小步、可验证、可回退）.
9. Local-first（本地优先）.
10. Human-in-the-loop（人在回路中） where automation is not trustworthy.

## Installation

Requirements:

```text
Python >= 3.11
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Check the installed version:

```powershell
python -c "import importlib.metadata as m; print(m.version('aletheia-nexus'))"
```

Expected:

```text
0.5.2
```

## Main APIs

### DOI normalization

```python
from aletheia_nexus.core.identifiers.doi import normalize_doi

doi = normalize_doi("https://doi.org/10.1038/nphys1170")
```

### Metadata Resolution（元数据解析）

```python
from aletheia_nexus.acquire.metadata import get_metadata

paper = get_metadata("10.1038/nphys1170")
```

### Full-text Discovery（全文发现）

```python
from aletheia_nexus.acquire.discovery import discover_full_text

result = discover_full_text(
    "10.1002/anie.201406668",
    unpaywall_email="you@example.com",
)
```

A `FullTextCandidate` is a route worth trying, not a verified article.

### Complete v0.5 workflow

```python
from aletheia_nexus.acquire.fulltext import acquire_full_text

result = acquire_full_text(
    "10.1038/s41893-022-00870-3",
    output_dir="downloads",
    unpaywall_email="you@example.com",
)

print(result.status)
print(result.verified_path)
```

If Discovery already exists:

```python
from aletheia_nexus.acquire.fulltext import acquire_from_discovery

result = acquire_from_discovery(
    discovery,
    output_dir="downloads",
    expected_title="Known article title",
)
```

## v0.5 behavior

### Direct Acquisition + Validation — v0.5.0

```text
concrete file candidate
→ safe bounded retrieval
→ PDF structure inspection
→ paper identity
→ document role
→ VERIFIED or explicit non-success
```

### Route Resolution — v0.5.1

Generic static-page evidence includes scholarly PDF metadata, semantic PDF anchors, embedded PDF routes, JSON-LD media routes, relative URLs, explicit PDF-looking URLs and explicit quoted `.pdf` paths in static inline script state.

No JavaScript execution or publisher-specific URL guessing is required for these signals.

### Multi-route Orchestration — v0.5.2

```text
Metadata + Discovery may bootstrap concurrently
↓
try direct files first
↓
resolve page routes when needed
↓
validate derived files immediately
↓
follow only bounded, high-confidence next-hop routes
↓
use DOI resolver fallback when appropriate
↓
first VERIFIED main article stops
```

Stable defaults:

```text
max route attempts              16
max file attempts               24
max route depth                  2
max route expansions per page    4
HTTPS probe timeout              5 s
```

## Final workflow statuses

```text
VERIFIED
NO_CANDIDATES
DISCOVERY_FAILED
AUTH_REQUIRED
ACCESS_BLOCKED
EXHAUSTED
LIMIT_REACHED
```

Access semantics are conservative. HTTP 401 maps to `AUTH_REQUIRED`; HTTP 403, explicit challenge/WAF pages and comparable access barriers map to `ACCESS_BLOCKED`. AN does not infer institutional login from a generic block.

Every failure keeps route/file attempt evidence rather than collapsing to a boolean.

## Safety, identity and provenance

Current safeguards include:

- HTTP(S)-only acquisition and URL/redirect safety checks;
- bounded timeout, retries, redirects, page size, file size and route depth;
- transient retries only for appropriate failures;
- SHA-256 while streaming;
- temporary-file cleanup and atomic promotion;
- provider provenance separated from AN-derived provenance;
- deterministic verified filenames and `.acquisition.json` sidecars.

Page/PDF identity is intentionally conservative:

```text
MATCH
MISMATCH
UNKNOWN
```

Exact DOI evidence outranks title similarity. Explicit DOI metadata for another work cannot be overridden by a matching-looking title.

Document roles are:

```text
ARTICLE
SUPPLEMENT
UNKNOWN
```

Strong non-main signals include conventional Supporting Information and auxiliary files such as Reporting Summary, peer-review files, Source Data and decision letters. Route-level hints may change priority or skip obvious non-main candidates, but **only file-level validation can create `VERIFIED`**.

## Testing

Deterministic CI runs on Python 3.11 and 3.14:

```text
editable install  ✅
pip check         ✅
Ruff format       ✅
Ruff static       ✅
compileall        ✅
pytest            ✅
```

Final v0.5 deterministic suite:

```text
510 passed on Python 3.11
Python 3.14 also passes the complete CI workflow
```

Real publisher networks are tested separately because third-party access policy is inherently variable.

Fixed live stress corpora:

```text
benchmarks/cdi_acquisition_10.json
benchmarks/seawater_desalination_10.json
```

Runner:

```text
scripts/manual_multiroute_acceptance.py
```

A same-environment 20-paper stress run on 2026-09-17 produced `6 / 20 VERIFIED`. This deliberately difficult corpus is diagnostic evidence, not a universal download-success estimate. No false `VERIFIED` was observed; the dominant remaining limitation was publisher/index access-layer blocking.

## Documentation

Canonical final v0.5 contract:

```text
docs/v0.5.2-multi-route-acquisition.md
```

Historical layer records:

```text
docs/v0.5.0-direct-acquisition.md
docs/v0.5.1-route-resolution.md
```

Discovery history remains under `docs/v0.4*`.

## Scope boundary and next line

v0.5 deliberately excludes:

```text
CARSI / SSO / institutional login
browser JavaScript execution
persistent browser sessions
CAPTCHA / anti-bot circumvention
paywall bypass
publisher-specific guessed URL catalogues
unbounded crawling
scientific-content parsing
knowledge-base / autonomous Agent logic
```

The next major line is:

```text
Verified local article
↓
Content Parsing（内容解析）
↓
structured scientific document
↓
Knowledge / Workflow / Agent
```

Authenticated/browser access can be developed later as a separate capability when a concrete workflow justifies its additional state, security and maintenance cost.

Aletheia Nexus is intended to become a reliable scientific-knowledge infrastructure layer. The long-term asset is not one model or one script, but the accumulation of reliable tools, structured data, provenance, workflows, evaluation rules and laboratory knowledge that can survive changes in models and platforms.
