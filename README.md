# Aletheia Nexus

> **A local-first scientific knowledge acquisition infrastructure.**  
> 面向科研场景的本地优先科学知识获取基础设施。

Aletheia Nexus（AN）不是单纯的论文下载脚本。它希望把科研中的知识获取逐步拆成**可靠、可测试、可追溯、可组合**的基础能力，并继续向 Content Parsing（内容解析）、Knowledge（知识组织）、Workflow（工作流）和 Agent（智能体）扩展。

长期目标不是构建一个“万能 Agent”，而是形成可以持续积累的数据、工具、规则、工作流和科研知识基础。

## Current status

当前正式稳定版本：

```text
Aletheia Nexus v0.5.2
Unauthenticated Full-text Acquisition
FINAL / HARDENED / FROZEN
```

当前开发主线：

```text
Aletheia Nexus v0.6
Acquisition Maximization
official API / authenticated / institutional / browser-session access
```

v0.6 不修改已经冻结的 v0.5 HTTP 核心，而是在 v0.5 无法得到
`VERIFIED` 时升级到持久浏览器会话、合法机构/账号认证和受控
Human-in-the-loop（人在回路中）恢复。

Release snapshot：

```text
Tag:       v0.5.2
Commit:    4f831eb75a38f19735cf6c98bcd64458fac344c0
Tests:     510 passed on Python 3.11
CI:        Python 3.11 / 3.14 ✅
Released:  2026-09-17
```

`v0.5.2` tag 是 v0.5 全文获取层的冻结快照。后续 `main` 可以继续进入 v0.6，而 v0.5 只有在出现**可复现的正确性缺陷**时才应重新打开。

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
Official Authenticated API Access 🚧 v0.6
Authenticated Browser Access      🚧 v0.6
Acquisition Maximization          🚧 v0.6

Content Parsing                   → v0.7 next
Knowledge / Workflow / Agent      → later
Lab / Scientific World Model      → long term
```

当前 v0.5 已闭合 **unauthenticated HTTP(S) full-text acquisition（未认证 HTTP(S) 全文获取）**链路。v0.6 将官方认证 API、浏览器登录、JavaScript challenge、机构认证和 Human-in-the-loop 放在独立 Access Layer（访问层）中，而不是污染 v0.5 HTTP core。AN 不做付费墙绕过、凭据猜测或 CAPTCHA-solving service（验证码代答服务）。

## Architecture

当前主链：

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
Direct file or landing / repository / resolver route
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

长期方向：

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

对应的工程分层原则是：

```text
稳定能力 → Skill（技能）
确定流程 → Workflow（工作流）
开放决策 → Agent（智能体）
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

只有通过 PDF 结构、目标论文身份和主文档角色验证的文件才能成为：

```text
VERIFIED
```

> **宁可明确失败，也不要把错误文件交给下游科研系统。**

## Quick start

Requirements：

```text
Python >= 3.11
```

Windows PowerShell（基础能力）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

如果需要 v0.6 Browser Access（浏览器访问）：

```powershell
python -m pip install -e ".[dev,browser]"
python -m playwright install chromium
```

浏览器能力是 optional dependency（可选依赖），不会污染 v0.5 的普通 HTTP
安装和 CI。

检查安装版本：

```powershell
python -c "import importlib.metadata as m; print(m.version('aletheia-nexus'))"
```

稳定标签 `v0.5.2` 应输出 `0.5.2`。v0.6 开发分支在冻结前使用
`0.6.0.dev0`。

## Main APIs

### DOI normalization（DOI 标准化）

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

`FullTextCandidate` 只表示“值得尝试的全文路径”，不表示已经获得正确论文。

### Complete v0.5 workflow（完整全文获取）

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

如果已经有 Discovery 结果：

```python
from aletheia_nexus.acquire.fulltext import acquire_from_discovery

result = acquire_from_discovery(
    discovery,
    output_dir="downloads",
    expected_title="Known article title",
)
```

### v0.6 Acquisition Maximization（获取率最大化）

```python
from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserSession,
    acquire_full_text_maximized,
)


def on_interaction(challenge, url):
    print(f"请在打开的浏览器中完成 {challenge.kind}: {url}")


result = acquire_full_text_maximized(
    "10.1038/s44221-024-00340-4",
    output_dir="downloads",
    browser_config=BrowserAccessConfig(
        profile_name="institution",
        channel="chrome",
        headless=False,
        interaction_callback=on_interaction,
    ),
    unpaywall_email="you@example.com",
)

print(result.status)
print(result.verified_path)
```

执行逻辑：

```text
v0.5 public/direct routes
↓
未 VERIFIED
↓
official authenticated API when configured/applicable
↓
仍未 VERIFIED
↓
persistent browser profile
↓
session reuse / JavaScript / SSO / login / MFA / CAPTCHA handoff
↓
captured PDF response / authenticated request / browser download
↓
原有 PDF + paper identity + document-role validation
↓
VERIFIED
```

核心原则仍然是：**浏览器和认证只能提高“拿到文件”的能力，不能降低
`VERIFIED` 标准。**

Elsevier ScienceDirect 官方 API 可选配置使用环境变量，避免把密钥写进代码或命令行：

```text
ELSEVIER_API_KEY
ELSEVIER_INST_TOKEN      # optional
ELSEVIER_BEARER_TOKEN    # optional
```

程序中可通过 `ElsevierAccessConfig.from_env()` 读取。API key、institution
token 和 bearer token 只进入请求 header，不进入 `.acquisition.json`。

真实验收时，除了固定 20 篇困难集，还应使用 `--entitled-doi` 加入
**你已经人工确认在同一机构/账号下能下载的论文**。这些阳性对照如果任何
一篇不能 `VERIFIED`，0.6 就不能视为完成：

```powershell
python scripts/manual_v06_access_acceptance.py \
  --entitled-doi 10.xxxx/example1 \
  --entitled-doi 10.xxxx/example2
```

批量任务建议复用一个 live BrowserSession（实时浏览器会话），而不是每篇
论文重新启动浏览器：

```python
config = BrowserAccessConfig(
    profile_name="institution",
    channel="chrome",
    headless=False,
    interaction_callback=on_interaction,
)

with BrowserSession(config) as session:
    for doi in dois:
        result = acquire_full_text_maximized(
            doi,
            output_dir="downloads",
            browser_session=session,
            unpaywall_email="you@example.com",
        )
```

这样不仅复用磁盘 cookie，也保留同一批任务中的短期 SSO / challenge state
（挑战状态）。

## v0.5 full-text acquisition

### v0.5.0 — Direct Acquisition + Validation

```text
concrete file candidate
→ safe bounded retrieval
→ PDF structure inspection
→ paper identity
→ document role
→ VERIFIED or explicit non-success
```

### v0.5.1 — Route Resolution

支持从通用静态页面证据中解析文件路径，包括：

```text
citation_pdf_url / scholarly PDF metadata
semantic Download / View PDF anchors
iframe / embed / object PDF routes
JSON-LD media routes
relative URLs
explicit PDF-looking URLs
explicit quoted .pdf paths in static inline script state
```

不执行 JavaScript，也不根据出版社域名猜测 PDF URL。

### v0.5.2 — Multi-route Acquisition

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

稳定默认限制：

```text
max route attempts              16
max file attempts               24
max route depth                  2
max route expansions per page    4
HTTPS probe timeout              5 s
```

## Explicit outcomes

最终工作流状态：

```text
VERIFIED
NO_CANDIDATES
DISCOVERY_FAILED
AUTH_REQUIRED
ACCESS_BLOCKED
EXHAUSTED
LIMIT_REACHED
```

访问语义保持保守：

```text
HTTP 401 → AUTH_REQUIRED
HTTP 403 → ACCESS_BLOCKED
explicit challenge / WAF page → ACCESS_BLOCKED
```

AN 不会因为一个普通的 block 自动断言“需要机构登录”，也不会把 challenge page 误当成“没有候选路径”。

每次失败都会尽可能保留 route/file attempt（路径/文件尝试）、来源、派生关系、深度和失败原因，而不是只返回 `True / False`。

## Safety, identity and provenance

v0.5 的关键防线包括：

- HTTP(S)-only acquisition；
- URL / redirect safety checks（URL / 重定向安全检查）；
- timeout、retry、redirect、page/file size、route depth 等有界限制；
- 只对合适的瞬时网络/限流/服务错误重试；
- streaming SHA-256；
- 临时文件失败清理与原子提升；
- provider provenance（数据源来源）与 AN-derived provenance（AN 派生来源）分离；
- 确定性的文件命名和 `.acquisition.json` sidecar（伴随元数据文件）。

论文身份状态：

```text
MATCH
MISMATCH
UNKNOWN
```

明确 DOI 证据优先于标题相似度；已知属于其他论文的 DOI 不能被“看起来很像”的标题覆盖。

文档角色：

```text
ARTICLE
SUPPLEMENT
UNKNOWN
```

Supporting Information、Reporting Summary、Peer Review、Source Data、Decision Letter 等明确非主文档不会因为 DOI/标题匹配而被错误提升为主论文。

## Engineering principles

Aletheia Nexus 当前遵循：

1. Correctness before automation（正确性优先于自动化）.
2. Explicit failure over silent wrong（明确失败优于静默错误）.
3. Stable primitives before orchestration（先稳定基础能力，再做编排）.
4. Clear module boundaries（保持清晰模块边界）.
5. Bounded work（网络与计算工作有界）.
6. Provenance over black boxes（来源追踪优于黑箱结果）.
7. Measure before optimize（先测量，再优化）.
8. No speculative abstraction（不为想象中的未来过度设计）.
9. Small, testable, reversible changes（小步、可验证、可回退）.
10. Local-first（本地优先）.
11. Human-in-the-loop（人在回路中）用于高风险、低置信度或无法可靠自动处理的环节.

## Validation and testing

正式 v0.5.2 freeze CI（冻结持续集成）：

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

最终确定性测试：

```text
510 passed on Python 3.11
Python 3.14 also passes the complete CI workflow
```

真实出版社网络不进入 deterministic CI（确定性持续集成），因为访问政策和网络状态本身会变化。

固定真实网络压力测试集：

```text
benchmarks/cdi_acquisition_10.json
benchmarks/seawater_desalination_10.json
```

Runner：

```text
scripts/manual_multiroute_acceptance.py
```

2026-09-17 的同环境 20 篇压力测试：

```text
CDI                       4 / 10 VERIFIED
Seawater desalination     2 / 10 VERIFIED
------------------------------------------
Combined                  6 / 20 = 30%
```

该小型困难语料用于暴露路径解析、访问阻断和错误验证问题，**不是通用下载成功率**。测试中没有观察到 false `VERIFIED`；当前剩余主要瓶颈已经转向 publisher/index access layer（出版社/索引访问层），而不是 PDF 身份验证层。

## Scope boundary

v0.5 明确不负责：

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

这些不是 v0.5 “漏掉的功能”，而是应当保持独立边界的后续能力层。

## Documentation

v0.6 获取率最大化规范：

```text
docs/v0.6-acquisition-maximization.md
```

完整 v0.5 最终规范：

```text
docs/v0.5.2-multi-route-acquisition.md
```

历史层记录：

```text
docs/v0.5.0-direct-acquisition.md
docs/v0.5.1-route-resolution.md
```

Discovery 历史：

```text
docs/v0.4-discovery.md
docs/v0.4.1-discovery-reliability.md
docs/v0.4.2-discovery-performance.md
docs/v0.4.2-provider-assessment.md
```

## Next: v0.7 Content Parsing

v0.5 解决：

> **怎样在无需认证的 HTTP(S) 世界里可靠获得正确论文。**

v0.6 补上：

> **怎样在用户具有合法访问条件时，把官方认证 API、机构权限、浏览器登录态和必要的人机协作纳入统一获取系统，最大化最终 VERIFIED 获取率。**

v0.6 稳定后，v0.7 才进入：

```text
Verified local article
↓
Content Parsing
↓
structured scientific document
↓
Knowledge organization
↓
Workflow / Agent callable capability
```

这样 Acquisition（获取）层先真正闭合，再向上构建 Parsing（解析）和知识层。

## Project direction

Aletheia Nexus 的长期定位是：

```text
scientific object identification
→ scientific information acquisition
→ trustworthy local artifacts
→ content parsing
→ knowledge organization
→ Workflow / Agent callable capabilities
→ laboratory research infrastructure
```

长期真正有价值的资产不是某一个模型、脚本或 Agent，而是能够持续积累、迁移、复用和组合的：

```text
data
knowledge
tools
workflows
provenance
evaluation rules
historical decisions
researcher / laboratory context
```

最终目标是让这些可靠的底层能力不断提高个人研究者和实验室的科研杠杆。