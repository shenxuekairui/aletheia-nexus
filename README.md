# Aletheia Nexus

> **A local-first scientific knowledge acquisition infrastructure.**  
> 面向科研场景的本地优先科学知识获取基础设施。

Aletheia Nexus（AN）不是单纯的论文下载脚本。它把科研知识获取拆成可靠、可测试、可组合的基础能力：对象识别、元数据解析、全文发现、访问路径解析、文件获取、论文身份验证、失败语义与来源追踪，并为后续 Content Parsing（内容解析）、Workflow（工作流）和 Agent（智能体）提供稳定底座。

当前稳定版本：

```text
Aletheia Nexus v0.5.2
Full-text Acquisition line — FINAL / FROZEN
```

---

## 1. Current capability map

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

Authenticated / Browser Access    → later, separate capability
Content Parsing                   → next major line
Knowledge / Workflow / Agent      → later
Lab / Scientific World Model      → long term
```

v0.5 closes the **unauthenticated HTTP(S) full-text acquisition loop**. It intentionally does not absorb institutional login, browser automation, CAPTCHA bypass, paywall bypass or scientific-content parsing.

---

## 2. Architecture

```text
Raw input
↓
Identifier / DOI Core
↓
Normalized DOI
↓
Metadata Resolution
↓
Full-text Discovery
↓
FullTextCandidate[]
↓
┌─────────────────────────────────────────────┐
│ v0.5 Full-text Acquisition                 │
│                                             │
│ Direct PDF ─────────────────┐               │
│                             ↓               │
│ Landing / repo / resolver   │               │
│        ↓                    │               │
│ Route Resolution            │               │
│        ↓                    │               │
│ Derived file candidate ─────┘               │
│        ↓                                    │
│ Retrieval + PDF Validation                  │
│        ↓                                    │
│ Paper Identity + Document Role              │
│        ↓                                    │
│ VERIFIED? yes → stop                        │
│           no  → bounded fallback/expansion  │
└──────────────────┬──────────────────────────┘
                   ↓
Verified local article
or explicit terminal outcome + attempt history
```

Long-term structure:

```text
Acquire
↓
Parse
↓
Knowledge
↓
Workflow
↓
Agent
↓
Lab / Scientific World Model
```

---

## 3. Core invariants

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

---

## 4. Engineering principles

AN follows a small set of rules:

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

---

## 5. Installation

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

---

## 6. Main APIs

### DOI normalization

```python
from aletheia_nexus.core.identifiers.doi import normalize_doi

doi = normalize_doi("https://doi.org/10.1038/nphys1170")
```

The DOI core also provides batch normalization, stable deduplication, extraction from noisy text and syntax checks.

### Metadata Resolution（元数据解析）

```python
from aletheia_nexus.acquire.metadata import get_metadata

paper = get_metadata("10.1038/nphys1170")
```

Current metadata providers include Crossref and DataCite.

### Full-text Discovery（全文发现）

```python
from aletheia_nexus.acquire.discovery import discover_full_text

result = discover_full_text(
    "10.1002/anie.201406668",
    unpaywall_email="you@example.com",
)
```

Current Discovery providers:

```text
OpenAlex
Unpaywall
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

---

## 7. What v0.5 does

### Direct Acquisition + Validation — v0.5.0

```text
concrete file candidate
↓
safe bounded retrieval
↓
PDF structure inspection
↓
paper identity
↓
document role
↓
VERIFIED or explicit non-success
```

### Route Resolution — v0.5.1

Generic static-page evidence includes:

```text
citation_pdf_url / scholarly PDF metadata
<link type="application/pdf">
Download / View PDF anchors
iframe / embed / object
JSON-LD media routes
explicit PDF-looking URLs
relative URL + <base href>
explicit quoted .pdf paths in static inline script state
```

No JavaScript execution or publisher-specific URL guessing is required for these signals.

### Multi-route Orchestration — v0.5.2

Default policy:

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

---

## 8. Final workflow statuses

```text
VERIFIED
NO_CANDIDATES
DISCOVERY_FAILED
AUTH_REQUIRED
ACCESS_BLOCKED
EXHAUSTED
LIMIT_REACHED
```

Access semantics are deliberately conservative:

```text
401 → AUTH_REQUIRED
403 → ACCESS_BLOCKED
```

A 403 can represent authorization, WAF（Web 应用防火墙）, anti-bot or IP policy; AN does not automatically interpret it as institutional login.

Every failure keeps route/file attempt evidence rather than collapsing to a boolean.

---

## 9. Safety and provenance

Current safeguards include:

- HTTP(S)-only acquisition;
- URL and redirect safety checks;
- bounded timeout / retries / redirects / page size / file size;
- transient retries only for appropriate network/rate-limit/service failures;
- SHA-256 while streaming;
- temporary-file cleanup and atomic promotion;
- provider provenance separated from AN-derived provenance;
- deterministic verified filenames and `.acquisition.json` sidecars.

Verified sidecars preserve enough information to explain where a file came from, how it was retrieved and why it was accepted.

---

## 10. Validation policy

Page/PDF identity is intentionally conservative:

```text
MATCH
MISMATCH
UNKNOWN
```

Exact DOI evidence is stronger than title similarity. Explicit DOI metadata for another work cannot be overridden by a matching-looking title.

Document roles are:

```text
ARTICLE
SUPPLEMENT
UNKNOWN
```

Strong non-main signals include conventional Supporting Information and auxiliary scientific files such as Reporting Summary, peer-review files, Source Data files and decision letters.

Route-level hints only affect priority/skipping. **Only file-level validation can create `VERIFIED`.**

---

## 11. Testing

Normal CI is deterministic and runs on Python 3.11 and 3.14:

```text
editable install  ✅
pip check         ✅
Ruff format       ✅
Ruff static       ✅
compileall        ✅
pytest            ✅
```

Final v0.5 freeze audit:

```text
504 passed on Python 3.11
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

Recorded same-environment stress run on 2026-09-17:

```text
6 / 20 VERIFIED = 30%
ACCESS_BLOCKED   8
NO_CANDIDATES    4
EXHAUSTED        2
```

This small difficult corpus is diagnostic evidence, not a universal download-success estimate. Its dominant remaining limitation was access-layer blocking rather than false file verification.

---

## 12. Documentation

Canonical final v0.5 contract:

```text
docs/v0.5.2-multi-route-acquisition.md
```

Historical layer records:

```text
docs/v0.5.0-direct-acquisition.md
docs/v0.5.1-route-resolution.md
```

Discovery history:

```text
docs/v0.4-discovery.md
docs/v0.4.1-discovery-reliability.md
docs/v0.4.2-discovery-performance.md
docs/v0.4.2-provider-assessment.md
```

---

## 13. Scope boundary and next line

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

---

## 14. Project direction

Aletheia Nexus is intended to become a reliable scientific-knowledge infrastructure layer:

```text
scientific object identification
→ information acquisition
→ trustworthy local artifact
→ content parsing
→ knowledge organization
→ Workflow / Agent callable capability
→ laboratory research infrastructure
```

The long-term asset is not one model or one script. It is the accumulation of reliable tools, structured data, provenance, workflows, evaluation rules and laboratory knowledge that can survive changes in models and platforms.
