# Aletheia Nexus

> **A local-first scientific knowledge acquisition infrastructure.**  
> 面向科研场景的本地优先科学知识获取基础设施。

Aletheia Nexus（AN）不是一个单纯的“论文下载脚本”。它把科研知识获取过程中容易被忽略的身份识别、来源发现、路径解析、文件验证、失败语义和可追溯性拆成清晰、可靠、可测试的基础能力，为未来的 Workflow（工作流）、Agent（智能体）和实验室级科研智能系统提供稳定底座。

当前版本：

```text
Aletheia Nexus v0.5.1
Route Resolution
访问路径解析
```

当前能力状态：

```text
Identifier / DOI Core             ✅
Metadata Resolution               ✅
Full-text Discovery               ✅ v0.4
Discovery Reliability             ✅
Discovery Performance             ✅
Direct PDF Acquisition            ✅ v0.5.0
PDF + Paper Identity Validation   ✅ v0.5.0
Route Resolution                  ✅ v0.5.1

Multi-route Acquisition           → v0.5.2
Authenticated / Browser Access    → later
Content Parsing                   → later
Knowledge / Agent / Lab           → later
```

---

## 1. What problem is AN solving?

表面上，文献获取似乎只是：

```text
DOI
↓
PDF
```

真正可靠的科研系统需要处理的是：

```text
输入真的是 DOI 吗？
↓
它对应哪个科研对象？
↓
元数据从哪里来？
↓
哪些地方可能有全文？
↓
Provider 给的是 PDF、落地页、仓储还是解析器？
↓
网页能不能进一步解析出真正的文件路径？
↓
网络失败、权限失败、反爬阻断分别意味着什么？
↓
下载回来的东西真的是 PDF 吗？
↓
它真的是目标论文吗？
↓
它是正文还是 Supporting Information（补充材料）？
↓
整个过程能不能被复查、复现和继续自动化？
```

因此 AN 采用分层路线，而不是把所有复杂性塞进一个“万能下载器”。

---

## 2. Core architecture

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
┌─────────────────────────────────────┐
│ v0.5 Acquisition line               │
│                                     │
│ PDF candidate ───────────────┐      │
│                              ↓      │
│ Landing / repository /       │      │
│ resolver candidate           │      │
│          ↓                   │      │
│ v0.5.1 Route Resolution      │      │
│          ↓                   │      │
│ Derived PDF Candidate ───────┘      │
│          ↓                          │
│ v0.5.0 Direct Acquisition           │
│          ↓                          │
│ PDF Validation                      │
│          ↓                          │
│ Paper Identity + Document Role      │
└──────────┬──────────────────────────┘
           ↓
Verified local file + provenance
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
├─ Agent
├─ Lab
└─ World
```

当前重点仍然是把 `Acquire` 做成可靠底座。

---

## 3. Key invariants

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
```

只有经过文件结构、论文身份和文档角色验证的内容，才允许被系统当作可信正文。

这意味着：

> **宁可明确 UNKNOWN / ACCESS_BLOCKED / INVALID_PDF，也不要拿错文件后告诉下游“成功了”。**

---

## 4. Design principles

Aletheia Nexus 当前遵循：

1. **Correctness before automation（正确性优先于自动化）**：自动化不能以错误结果为代价。
2. **Explicit failure over silent wrong（明确失败优于静默错误）**：失败原因是系统输出的一部分。
3. **Stable primitives before orchestration（先稳定基础能力，再做编排）**：稳定能力 → Skill，确定流程 → Workflow，开放决策 → Agent。
4. **Discovery and Acquisition are different problems（发现与获取分离）**：知道“哪里可能有全文”不等于拿到全文。
5. **Route Resolution and File Validation are different problems（路径解析与文件验证分离）**：网页里找到一个 PDF-looking URL 不等于文件可信。
6. **Provenance over black boxes（来源追踪优于黑箱结果）**：Provider、派生方式、redirect、SHA-256、验证证据都尽量保留。
7. **Measure before optimize（先测量，再优化）**：只优化真实瓶颈。
8. **No speculative abstraction（不为想象中的未来提前抽象）**：出现真实重复后再提取公共层。
9. **Small, testable, reversible changes（小步、可测试、可回退）**：每层稳定后及时冻结。
10. **Local-first（本地优先）**：核心数据、文件、状态和知识尽可能由研究者自己掌控。
11. **Human-in-the-loop（人在回路中）**：低置信度、授权访问和高风险环节允许人工介入。

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
0.5.1
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

统一 `FullTextCandidate` 主要字段：

```text
doi
url
provenance
url_type
access_type
version
host_type
license
source_name
is_best
```

重要语义：

```text
CandidateUrlType.PDF
=
Provider-reported PDF candidate
≠
AN verified PDF
```

Discovery ranking（排序）表示**下一步获取优先级**，不是学术权威性排名。

---

## 9. Direct PDF Acquisition — v0.5.0

v0.5.0 是稳定的文件获取与验证原语。

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
one PDF Candidate
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

稳定结果状态包括：

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

关键访问语义：

```text
401 → AUTH_REQUIRED
403 → ACCESS_BLOCKED
```

因为 HTTP 403 可能来自权限、WAF（Web 应用防火墙）、anti-bot、IP policy 等多种原因，不能直接声称“需要机构登录”。

详细契约见：`docs/v0.5.0-direct-acquisition.md`。

---

## 10. Route Resolution — v0.5.1

v0.5.1 解决：

> Provider 只告诉我论文页面在哪时，AN 能不能继续把它解析成更具体的文件候选？

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

当前通用能力包括：

```text
安全 HTML/page 获取
manual redirects
页面身份 MATCH / MISMATCH / UNKNOWN
ARTICLE / LOGIN / ACCESS_DENIED / CHALLENGE 页面分类
citation_pdf_url
bepress_citation_pdf_url
EPrints / generic PDF metadata
<link type="application/pdf">
Download / View PDF anchors
iframe / embed / object PDF routes
JSON-LD PDF media
relative URL
<base href>
PDF magic-byte sniffing
ARTICLE / SUPPLEMENT / UNKNOWN role hints
Derived Candidate provenance
candidate dedupe + deterministic ranking
explicit HTTP → HTTPS route derivation
```

### Why `DerivedFullTextCandidate`?

例如：

```text
OpenAlex
↓
HAL landing page
↓
AN reads citation_pdf_url
↓
HAL document route
```

不能把最后的 PDF URL 假装成“OpenAlex 直接告诉 AN 的”。因此 v0.5.1 同时记录：

```text
provider provenance
+
parent route
+
source page
+
derivation method
+
evidence
```

### Role hint is not verification

Landing Page 里可能同时有：

```text
Article PDF
Supporting Information
Reporting Summary
Peer Review file
Source Data
```

v0.5.1 只给角色提示；最终是否为目标正文仍然由 v0.5.0 验证。

详细契约见：`docs/v0.5.1-route-resolution.md`。

---

## 11. Real-network acceptance

AN 不把 live publisher network（真实出版社网络）放进日常 CI，因为第三方网站随时会变化。但重要版本会使用固定语料做手动/临时工作流验收。

固定 CDI 10-paper corpus：

```text
benchmarks/cdi_acquisition_10.json
```

验收脚本：

```text
scripts/manual_cdi_10_route_acceptance.py
```

v0.5.1 在 2026-09-16 的 hardened real-network run（强化后真实网络验收）中，使用 OpenAlex-only Discovery 得到：

```text
VERIFIED                                      5 / 10
NO_FILE_CANDIDATE                             3 / 10
ACCESS_BLOCKED                                1 / 10
INVALID_PDF | RETRIEVED_UNVERIFIED | SUPPLEMENT  1 / 10
```

真实打通的路径包括：

```text
Nature landing → citation_pdf_url → Nature PDF
Springer old route failed → DOI landing → current Springer PDF
HAL landing → repository document
PolyU landing → usable HTTPS repository PDF
existing direct Nature PDF → verified unchanged
```

这轮验收更重要的结论不是“5/10”本身，而是：

- challenge page 不再被误判成 wrong paper；
- generic resolver page 不再因标题冲突被武断判为 MISMATCH；
- Reporting Summary / Peer Review 不再被误标为 ARTICLE；
- Supporting Information 仍会被拒绝；
- **没有错误文件被提升为 VERIFIED。**

剩余失败主要来自服务器阻断、权限/反爬边界或页面本身没有暴露文件，因此没有为了提升 benchmark 分数去加入出版社硬编码、猜 URL 或绕过访问控制。

---

## 12. Reliability and safety

### Retry

只对合理的临时错误自动 Retry（重试）：

```text
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
```

明确的权限、阻断、Not Found、Unsafe URL、Too Large、Request Error 等不会被盲目重试。

### SSRF safety boundary

外部 Provider 和网页都可能提供 URL，因此 Acquisition 会拒绝明显危险的非公网目标，并在 redirect 前重新验证。

当前 DNS 检查属于 best-effort preflight（尽力式预检查），不宣称能够抵御所有对抗性 DNS rebinding（DNS 重绑定）攻击。更强保证需要受限网络沙箱或连接地址固定。

### Local storage

只有符合持久化策略的文件才进入正式输出路径。Verified 文件旁会写入 `.acquisition.json` sidecar（旁车记录），保存 URL、redirect、hash、身份和验证证据。

---

## 13. Testing

日常 CI 当前覆盖：

```text
Python 3.11
Python 3.14

editable install
pip check
Ruff format
Ruff static checks
compileall
pytest
```

v0.5.1 最终强化测试集：

```text
455 tests passing on Python 3.11
Python 3.14 matrix green
```

真实网络测试不进入永久 CI；固定 benchmark 和手动 runner 保留在仓库中用于版本验收和回归比较。

---

## 14. Repository layout

```text
src/aletheia_nexus/
├─ core/
│  └─ identifiers/
└─ acquire/
   ├─ metadata/
   ├─ discovery/
   └─ fulltext/
      ├─ models.py
      ├─ exceptions.py
      ├─ safety.py
      ├─ retry.py
      ├─ transport.py
      ├─ validation.py
      ├─ identity.py
      ├─ storage.py
      ├─ service.py
      └─ resolution/
         ├─ models.py
         ├─ transport.py
         ├─ parser.py
         ├─ identity.py
         ├─ derivation.py
         └─ service.py

tests/
benchmarks/
scripts/
docs/
```

Canonical release documents：

```text
docs/v0.4-discovery.md
docs/v0.5.0-direct-acquisition.md
docs/v0.5.1-route-resolution.md
```

---

## 15. What v0.5.1 intentionally does not do

```text
❌ automatic multi-route orchestration
❌ browser JavaScript rendering
❌ CARSI / SSO login
❌ cookie/session persistence
❌ CAPTCHA bypass
❌ anti-bot circumvention
❌ paywall bypass
❌ publisher-specific adapter catalogue
❌ guessed PDF URL templates
❌ OCR / scientific-content parsing
```

这些不是“漏做”，而是为了保持模块边界清晰。

---

## 16. Next: v0.5.2 Multi-route Acquisition

下一层将第一次把现在已经稳定的基础能力编排起来：

```text
DiscoveryResult
↓
Candidate #1
├─ PDF → v0.5.0
└─ Landing → v0.5.1 → derived PDFs → v0.5.0
↓
if not VERIFIED
↓
Candidate #2
↓
...
↓
first VERIFIED ARTICLE stops
```

v0.5.2 负责的是 route-attempt policy（路径尝试策略）、fallback（回退）和完整 attempt history（尝试历史），而不是重新实现 Discovery、HTML parser 或 PDF validator。

---

## 17. Long-term direction

Aletheia Nexus 最终希望形成：

```text
科研对象识别
→ 科学信息获取
→ 内容解析
→ 知识组织
→ Skill / Workflow
→ Agent 可调用能力
→ 个人与实验室科研工作流
```

长期价值不只是某个脚本，而是持续积累：

```text
数据
知识
工具
工作流
来源与证据
失败经验
评价标准
历史决策
实验室隐性知识
```

使系统从“通用 AI 工具”逐渐变成可验证、可迁移、可追溯、可复用的科研智能基础设施。
