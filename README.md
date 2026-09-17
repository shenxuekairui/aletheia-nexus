# Aletheia Nexus

> **A local-first scientific knowledge acquisition infrastructure.**  
> 面向科研场景的本地优先科学知识获取基础设施。

Aletheia Nexus（AN）不是一个单纯的“论文下载脚本”。它把科研知识获取中的对象识别、元数据解析、全文发现、访问路径解析、文件获取、论文身份验证、失败语义和可追溯性拆成可靠、可测试、可组合的基础能力，为未来的 Workflow（工作流）、Agent（智能体）和实验室级科研智能系统提供稳定底座。

当前版本：

```text
Aletheia Nexus v0.5.2
Multi-route Acquisition
多路径全文获取编排
```

当前能力状态：

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

---

## 1. Why AN exists

表面上，文献获取似乎只是：

```text
DOI
↓
PDF
```

可靠科研基础设施真正面对的是：

```text
输入真的是 DOI 吗？
↓
它对应哪个科研对象？
↓
元数据从哪里来？
↓
哪些来源可能有全文？
↓
Provider 给的是 PDF、落地页、仓储页还是 DOI resolver？
↓
网页能不能继续解析出真正的文件路径？
↓
同一条路线是不是已经尝试过？
↓
何时继续 fallback，何时应该停止？
↓
网络失败、权限失败、反爬阻断分别意味着什么？
↓
下载回来的东西真的是 PDF 吗？
↓
它真的是目标论文吗？
↓
它是正文还是 Supporting Information（补充材料）？
↓
整个过程能不能被复查、复现并供后续系统调用？
```

AN 的目标不是“尽一切办法下载到东西”，而是：

> **尽可能获取正确的科学对象；获取不到时，也要明确、可解释地失败。**

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
PaperMetadata
   ↓
Full-text Discovery
   ├─ OpenAlex
   └─ Unpaywall
   ↓
FullTextCandidate[]
   ↓
┌──────────────────────────────────────────────┐
│ v0.5.2 Multi-route Acquisition              │
│                                              │
│ Direct PDF candidate ───────────────┐        │
│                                     ↓        │
│ Landing / repository / resolver     │        │
│              ↓                      │        │
│ v0.5.1 Route Resolution             │        │
│              ↓                      │        │
│ Derived PDF Candidate ──────────────┘        │
│              ↓                               │
│ v0.5.0 Direct Acquisition + Validation       │
│              ↓                               │
│          VERIFIED?                           │
│          ├─ yes → stop                       │
│          └─ no  → bounded fallback/expansion │
└──────────────────┬───────────────────────────┘
                   ↓
Verified local article
or explicit terminal outcome + attempt history
```

长期结构：

```text
Aletheia Nexus
│
├─ Acquire
│  ├─ Identifier
│  ├─ Metadata
│  ├─ Discovery
│  └─ Fulltext
│
├─ Parse
├─ Knowledge
├─ Workflow
├─ Agent
├─ Lab
└─ World
```

v0.5.2 标志着当前 **Acquire / Fulltext（全文获取）主线在未认证 HTTP 范围内完成闭环**。

---

## 3. Core invariants

AN 当前最重要的边界是：

```text
Candidate
≠ File

File
≠ Valid PDF

Valid PDF
≠ Target Paper

Target Paper
≠ Main Article

Derived Candidate
≠ Verified File

Many attempted routes
≠ Success
```

只有经过文件结构、论文身份和文档角色验证的内容，才允许成为 `VERIFIED`。

> **宁可明确 UNKNOWN / ACCESS_BLOCKED / INVALID_PDF / EXHAUSTED，也不要拿错文件后告诉下游“成功了”。**

---

## 4. Engineering principles

1. **Correctness before automation（正确性优先于自动化）**。
2. **Explicit failure over silent wrong（明确失败优于静默错误）**。
3. **Stable primitives before orchestration（先稳定基础能力，再做编排）**。
4. **Discovery ≠ Acquisition（发现不等于获取）**。
5. **Route Resolution ≠ File Validation（路径解析不等于文件验证）**。
6. **Provenance over black boxes（来源追踪优于黑箱结果）**。
7. **Bounded work（有界工作）**：网络请求、递归深度、文件大小和重试都必须有边界。
8. **Measure before optimize（先测量，再优化）**。
9. **No speculative abstraction（不为想象中的未来提前抽象）**。
10. **Small, testable, reversible changes（小步、可测试、可回退）**。
11. **Local-first（本地优先）**。
12. **Human-in-the-loop（人在回路中）**：认证、低置信度和高风险环节允许人工介入。

---

## 5. Installation

要求：

```text
Python >= 3.11
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

检查版本：

```powershell
python -c "import importlib.metadata as m; print(m.version('aletheia-nexus'))"
```

当前应输出：

```text
0.5.2
```

---

## 6. DOI Core

```python
from aletheia_nexus.core.identifiers.doi import (
    extract_dois,
    looks_like_doi,
    normalize_doi,
    normalize_dois,
)
```

支持 DOI URL/prefix、大小写、空格、正文标点、百分号编码、常见包裹符号和复杂历史后缀，并支持批量标准化、稳定去重和杂乱文本提取。

---

## 7. Metadata Resolution

当前支持：

```text
Crossref
DataCite
```

```python
from aletheia_nexus.acquire.metadata import get_metadata

paper = get_metadata("10.1038/nphys1170")
print(paper.doi, paper.title, paper.authors)
```

Metadata 层明确区分 Not Found、Provider/Agency、Network、Rate Limit、Request、Service、Parse 等失败，而不是统一压成一个模糊的 `failed`。

---

## 8. Full-text Discovery — v0.4

```python
from aletheia_nexus.acquire.discovery import discover_full_text

result = discover_full_text(
    "10.1002/anie.201406668",
    unpaywall_email="you@example.com",
)

for candidate in result.candidates:
    print(candidate.url)
    print(candidate.url_type)
    print(candidate.access_type)
    print(candidate.version)
    print(candidate.host_type)
    print(candidate.provenance)
```

当前 Discovery Provider：

```text
OpenAlex
Unpaywall
```

`FullTextCandidate` 表示“值得尝试的全文位置”，而不是已经验证的论文文件。

Discovery ranking（排序）表示**下一步获取优先级**，不是学术权威性排名。

详细设计：

- `docs/v0.4-discovery.md`
- `docs/v0.4.1-discovery-reliability.md`
- `docs/v0.4.2-discovery-performance.md`
- `docs/v0.4.2-provider-assessment.md`

---

## 9. Direct PDF Acquisition + Validation — v0.5.0

```python
from aletheia_nexus.acquire.fulltext import acquire_direct_pdf

result = acquire_direct_pdf(
    candidate,
    output_dir="downloads",
    expected_title="Optional known title",
)
```

职责：

```text
one concrete PDF candidate
↓
safe HTTP retrieval
↓
manual redirect validation
↓
streaming + size limit + SHA-256
↓
PDF structure inspection
↓
paper identity
↓
ARTICLE / SUPPLEMENT
↓
VERIFIED or explicit non-success
```

典型状态包括：

```text
VERIFIED
RETRIEVED_UNVERIFIED
SUPPLEMENT
MISMATCH
INVALID_PDF
AUTH_REQUIRED
ACCESS_BLOCKED
NOT_FOUND
TOO_LARGE
UNSAFE_URL
REDIRECT_ERROR
REQUEST_ERROR
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
ERROR
```

详细契约：`docs/v0.5.0-direct-acquisition.md`。

---

## 10. Route Resolution — v0.5.1

```python
from aletheia_nexus.acquire.fulltext import resolve_full_text_route

result = resolve_full_text_route(
    candidate,
    expected_title="Optional known title",
)

for derived in result.candidates:
    print(derived.candidate.url)
    print(derived.method)
    print(derived.role_hint)
    print(derived.evidence)
```

v0.5.1 把 landing page / repository / resolver route 转换为**有证据、可追溯的文件候选**。

当前通用信号包括：

```text
citation_pdf_url / scholarly metadata
<link type="application/pdf">
Download / View PDF anchors
iframe / embed / object
JSON-LD media routes
relative URL / <base href>
PDF magic-byte sniffing
ARTICLE / SUPPLEMENT / UNKNOWN hints
explicit HTTP → HTTPS derivation
```

它不会因为“链接看起来像 PDF”就宣布成功；最终文件仍交给 v0.5.0 验证。

详细契约：`docs/v0.5.1-route-resolution.md`。

---

## 11. Multi-route Acquisition — v0.5.2

v0.5.2 将前面的稳定能力组合成 DOI 级全文获取 Workflow（工作流）。

### Main API

```python
from aletheia_nexus.acquire.fulltext import acquire_full_text

result = acquire_full_text(
    "10.1038/s41893-022-00870-3",
    output_dir="downloads",
    unpaywall_email="you@example.com",
)

print(result.status)
print(result.verified_result)
```

如果已经完成 Discovery：

```python
from aletheia_nexus.acquire.fulltext import acquire_from_discovery

result = acquire_from_discovery(
    discovery,
    output_dir="downloads",
    expected_title="Known article title",
)
```

### Orchestration policy

默认策略：

```text
Metadata + Discovery 可并行启动
↓
先尝试 concrete PDF candidates
↓
必要时解析 landing/repository/resolver routes
↓
新派生的 PDF 立即验证
↓
必要时进行有限深度 route expansion
↓
provider routes 失败后可使用 DOI resolver fallback
↓
第一个 VERIFIED main article 立即停止
```

同时具备：

```text
canonical URL dedupe
redirect-target dedupe
strong SUPPLEMENT hint skipping
HTTP → HTTPS traceable alternatives
page-like invalid PDF → route fallback
route/file attempt budgets
route-depth budget
complete route/file attempt history
explicit terminal semantics
```

默认边界：

```text
max route attempts              16
max file attempts               24
max route depth                  2
max route expansions per page    4
HTTPS probe timeout              5 s
```

### Final workflow statuses

```text
VERIFIED
NO_CANDIDATES
DISCOVERY_FAILED
AUTH_REQUIRED
ACCESS_BLOCKED
EXHAUSTED
LIMIT_REACHED
```

一个失败结果仍然保留：Discovery 结果、每次 route/file attempt、来源、父路径、派生方式、证据、去重计数、深度、耗时和最终原因。

详细冻结契约：`docs/v0.5.2-multi-route-acquisition.md`。

---

## 12. Real-network acceptance

真实出版社网络会随时间、IP、访问策略变化，因此 **live-network acceptance（真实网络验收）不是日常 deterministic CI（确定性持续集成）的一部分**。

固定语料：

```text
benchmarks/cdi_acquisition_10.json
benchmarks/seawater_desalination_10.json
```

v0.5.2 验收脚本：

```text
scripts/manual_multiroute_acceptance.py
```

示例：

```powershell
python scripts/manual_multiroute_acceptance.py `
  --corpus benchmarks/seawater_desalination_10.json `
  --output-dir real_network_acceptance/v0.5.2-seawater
```

验收记录的不只是成功数，还包括：

```text
provider status
route attempts
file attempts
route depth / expansion
redirect/final URL
deduplication counters
role hints
elapsed time
final status
verified URL
```

发布判断采用两类证据：

```text
确定性 CI
+
固定语料真实网络验收
```

真实网络的 `VERIFIED` 数量可以波动；不可接受的是通过降低验证标准、猜 URL 或错误提升文件来制造“成功”。

---

## 13. Safety and reliability

### Retry

只对合理的临时错误自动 Retry（重试），例如：

```text
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
```

明确的权限、阻断、Not Found、Unsafe URL、Too Large、Request Error 等不会被盲目重试。

### Access semantics

```text
401 → AUTH_REQUIRED
403 → ACCESS_BLOCKED
```

HTTP 403 可能来自权限、WAF（Web 应用防火墙）、anti-bot、IP policy 等多种原因，因此 AN 不会自动把它解释成“需要机构登录”。

### SSRF boundary

外部 Provider 和网页都可能提供 URL，因此 Acquisition 层限制：

```text
HTTP(S) only
hostname required
embedded credentials rejected
private / loopback / link-local literal IP rejected
best-effort DNS preflight checks
redirect targets revalidated
bounded redirects
bounded timeout
bounded body/file size
```

### Validation authority

任何 Discovery、HTML metadata、link text、role hint 或 provider label 都不能单独产生 `VERIFIED`。

---

## 14. Testing

v0.5.2 最终确定性测试矩阵：

```text
Python 3.11  ✅
Python 3.14  ✅

editable install  ✅
pip check         ✅
Ruff format       ✅
Ruff static       ✅
compileall        ✅
pytest            ✅
```

当前测试集：

```text
488 passing tests on Python 3.11
Python 3.14 matrix also passing
```

运行：

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

---

## 15. Repository layout

```text
src/aletheia_nexus/
├─ core/
│  └─ identifiers/
└─ acquire/
   ├─ metadata/
   ├─ discovery/
   └─ fulltext/
      ├─ validation/
      ├─ resolution/
      └─ orchestration/

benchmarks/
├─ cdi_acquisition_10.json
└─ seawater_desalination_10.json

scripts/
├─ manual_cdi_10_route_acceptance.py
└─ manual_multiroute_acceptance.py

docs/
├─ v0.4-discovery.md
├─ v0.4.1-discovery-reliability.md
├─ v0.4.2-discovery-performance.md
├─ v0.4.2-provider-assessment.md
├─ v0.5.0-direct-acquisition.md
├─ v0.5.1-route-resolution.md
└─ v0.5.2-multi-route-acquisition.md

tests/
└─ deterministic regression suite
```

---

## 16. What v0.5 intentionally does not do

v0.5.2 冻结后，以下能力明确不属于当前稳定主线：

```text
CARSI / SSO / institutional login
browser JavaScript execution
cookie/session persistence
CAPTCHA / anti-bot circumvention
paywall bypass
publisher-specific URL guessing
unbounded crawling
OCR
scientific-content parsing
knowledge-base construction
autonomous research Agent
```

这些不是“漏做了”，而是为了保持模块边界清晰而明确留给其他层。

---

## 17. Why v0.5 freezes here

v0.5 已经形成完整责任链：

```text
Discover
→ Resolve route
→ Acquire file
→ Validate PDF
→ Verify paper identity
→ Classify document role
→ Coordinate multiple routes
→ Stop on VERIFIED or explicit failure
```

继续为了少数网站加入 publisher-specific heuristics（出版社特定启发式规则）、猜测 URL 或更激进的网络策略，会开始损害可维护性、来源追踪和失败语义。

因此当前最有价值的下一步不是继续把 0.5 做“大”，而是把它作为稳定工具层冻结，让下一层直接复用。

---

## 18. Next

下一条主线将从：

```text
“可靠地拿到正确论文”
```

转向：

```text
Verified local article
↓
Content Parsing（内容解析）
↓
sections / text / tables / figures / references
↓
structured scientific objects
↓
Knowledge / Workflow / Agent
```

Authenticated / Browser Acquisition（认证/浏览器获取）可以作为未来独立能力存在，但只有在真实科研工作流证明其复杂性值得时再引入。

---

## Version status

```text
v0.4    Full-text Discovery              FROZEN
v0.4.1  Discovery Reliability            FROZEN
v0.4.2  Discovery Performance            FROZEN
v0.5.0  Direct Acquisition + Validation  FROZEN
v0.5.1  Route Resolution                 FROZEN
v0.5.2  Multi-route Acquisition          FROZEN
```

**Aletheia Nexus v0.5.2 completes and freezes the current v0.5 full-text acquisition line.**
