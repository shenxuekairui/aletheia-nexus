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
Tests:     707 passed, 6 skipped on Python 3.11
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
captured PDF response / authenticated request / browser or PDF-viewer save
↓
原有 PDF + paper identity + document-role validation
↓
VERIFIED
```

对于 Wiley 等把已授权文献放在 Chromium 内置 PDF 查看器中的站点，AN 会在
标题与当前论文匹配后调用查看器自身的 Save 控件，将文件写入隔离的临时目录，
再执行同一套 PDF 结构、论文身份和文档角色验证。该路径只保存浏览器已经取得的
文件，不绕过登录、CAPTCHA、订阅或机构权限。

核心原则仍然是：**浏览器和认证只能提高“拿到文件”的能力，不能降低
`VERIFIED` 标准。**

Elsevier ScienceDirect 官方 API 可选配置使用环境变量，避免把密钥写进代码或命令行：

```text
ELSEVIER_API_KEY
ELSEVIER_INST_TOKEN      # optional
ELSEVIER_BEARER_TOKEN    # optional
```

顶层 `acquire_full_text_maximized()` 默认会自动发现这些环境变量；也可以
显式传入 `ElsevierAccessConfig`。如需完全禁用官方 API 自动发现，可设置
`auto_official_api=False`。API key、institution token 和 bearer token
只进入请求 header，不进入 `.acquisition.json`。

真实验收时，固定 20 篇困难集只负责测覆盖率；还必须加入
**Entitled Positive Controls（已确认有权限的阳性对照）**，也就是你已经
人工确认在**同一机构 / 账号 / 网络环境**下能下载的论文。任何一篇阳性对照
不能 `VERIFIED`，0.6 都不能视为完成。

少量论文可以直接传 DOI：

```powershell
python scripts/manual_v06_access_acceptance.py `
  --entitled-doi 10.xxxx/example1 `
  --entitled-doi 10.xxxx/example2
```

正式冻结先从仓库模板复制一份本地文件：

```powershell
Copy-Item benchmarks/v06_entitled_positive_controls.example.json `
  benchmarks/v06_entitled_positive_controls.local.json
```

然后把其中 3 条示例替换成你**人工确认在同一机构/账号/网络环境下能下载**
的真实论文。正式冻结必须 ≥3 篇、覆盖 ≥2 个出版社/访问家族。每条记录都要填写
`access_family`（例如 `elsevier-sciencedirect`、`springer-nature`）。

正式 `--require-entitled-controls` 冻结门会同时要求：

```text
stress cases >= 20
entitled controls >= 3
每个 entitled control 都有 access_family
distinct access families >= 2
全部 entitled controls = VERIFIED
v0.6-only recovery >= 1
RUNNER_ERROR = 0
```

然后运行：

```powershell
python scripts/manual_v06_access_acceptance.py `
  --entitled-benchmark benchmarks/v06_entitled_positive_controls.local.json `
  --require-entitled-controls
```

该本地文件已加入 `.gitignore`，不会被误当成通用公开 benchmark。

如果 GitHub Actions runner（GitHub Actions 执行机）不可用，可以先在本机运行与
CI 同级的确定性 Release Candidate（发布候选）检查：

```powershell
.\scripts\verify_v06_rc.ps1
```

如果本机已经安装 Playwright Chromium，并希望连同真实浏览器集成测试一起跑：

```powershell
.\scripts\verify_v06_rc.ps1 -Browser
```

该脚本依次检查 `pip check`、Ruff format（格式）、Ruff lint（静态检查）、
`compileall` 和完整 `pytest`；`-Browser` 额外启动真实 Chromium 并运行
access-layer browser integration tests（访问层浏览器集成测试）。它是 CI 的
独立验证路径，但不能替代正式机构环境的 live acceptance（真实验收）。

批量任务建议复用一个 live BrowserSession（实时浏览器会话），而不是每篇
论文重新启动浏览器：

```python
config = BrowserAccessConfig(
    profile_name="institution",
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

### v0.6 批量下载、断点续跑与权限处理

0.6 提供正式的顺序批量 API。它复用一个惰性启动的 `BrowserSession`，逐篇保存
原子检查点，并且只跳过仍然存在且 SHA-256 与检查点一致的 `VERIFIED` 文件：

```python
from aletheia_nexus.acquire.access import acquire_full_text_batch_maximized

batch = acquire_full_text_batch_maximized(
    ["10.1038/nphys1170", "10.1000/example"],
    output_dir="downloads/v06-batch",
    checkpoint_path="downloads/v06-batch/batch-checkpoint.json",
)

print(batch.status_counts)
```

权限、登录和验证按以下方式处理：

- 合法登录 cookie、机构 SSO 和短期 challenge 状态在同一批次复用；
- 已配置的 Elsevier 官方 API 凭据仍会优先用于适用论文；
- 登录、MFA、CAPTCHA 由可见浏览器中的 Human-in-the-loop 完成；
- IEEE Xplore 按其站点机器人使用条款走用户操作路径：AN 不自动访问或批量请求
  Xplore；用户自行下载单篇后，AN 接管指定的本地 PDF，执行同一套科学验证；
- 交互式 CLI 会立即打印挑战类型和安全脱敏后的页面地址，并持续等待，直到
  登录、MFA 或 CAPTCHA 真正消失；
- 用户按 `Ctrl+C` 取消、关闭挑战页面，或显式设置的交互超时耗尽后，当前 DOI
  返回 `INTERACTION_REQUIRED`，默认继续后续论文；只有显式传入
  `--stop-on-interaction` 才暂停整批；
- `AUTH_REQUIRED`、`INTERACTION_REQUIRED`、`ENTITLEMENT_REQUIRED` 和
  `ACCESS_DENIED` 分开报告，下一次运行会重新尝试；
- 检查点不记录 cookie、token、URL 或异常消息；只有验证成功且哈希一致的文件
  才会被断点续跑直接复用。

安装 editable package 后，也可以直接运行 CLI。输入支持每行一个 DOI 的文本、
JSON 列表，或包含 `doi` / 可选 `title` 列的 CSV：

```powershell
python scripts/batch_v06_download.py dois.csv `
  --output-dir downloads/v06-batch `
  --unpaywall-email you@example.com
```

IEEE DOI 在交互式终端会暂停并提示用户自行打开 DOI 链接、保存单篇 PDF、输入
本地路径；无人值守运行会返回 `INTERACTION_REQUIRED` 并继续后续项目。已下载的
文件可在重跑时显式提供，无需再次访问 Xplore：

```powershell
python scripts/batch_v06_download.py dois.csv `
  --output-dir downloads/v06-batch `
  --non-interactive `
  --local-pdf "10.1109/ICEET.2009.450=C:\path\to\paper.pdf"
```

将示例 DOI 和路径替换成真实值。AN 只复制并验证用户
指定的文件，不修改原件；错误论文或非 PDF 不能成为 `VERIFIED`。

CLI 默认写入 `batch-checkpoint.json` 和 `batch-report.json`，内部错误最多尝试两次。
交互模式下不传 `--interaction-timeout` 时，AN 会在可见浏览器挑战处持续等待并在
挑战解除后自动继续。可传 `--interaction-timeout N` 改为最多等待 N 秒；无人值守
任务应显式使用 `--non-interactive`。AN 不会自动重试明确的无权限或无订阅状态。

连接本机真实 Edge/Chrome 做大批量测试时，可以让 CLI 自动启动专用持久配置，
逐篇导航，并为公共解析和浏览器候选设置独立预算：

```powershell
python -u scripts/batch_v06_download.py dois.json `
  --output-dir downloads/v06-batch `
  --cdp-endpoint http://127.0.0.1:9222 `
  --cdp-navigate `
  --base-timeout 10 --request-timeout 15 `
  --max-route-attempts 4 --max-file-attempts 6 `
  --max-source-routes 3 --max-pdf-candidates 6
```

AN 自动启动的浏览器始终带有进程级 `--no-proxy-server`，因此文献访问使用
直连，不读取 Windows 系统代理。它同时使用独立的 AN `user-data-dir`，不会修改
日常 Edge/Chrome 的代理、配置文件或启动方式。批量工具在本机 CDP 端点不可用时
会默认自动启动 AN 专用直连浏览器；无需提前
打开。只有显式传入 `--no-start-browser-if-needed` 才会禁止自动启动。对于用户
自行启动的外部 CDP 浏览器，AN 会继承该进程已有的网络设置，无法在附加后安全地
切换代理。

如果用户取消等待或挑战页面被关闭，认证标签会尽量保留；再次执行相同命令时，
AN 会优先复用标题强匹配的已放行标签，不会为同一篇反复新开标签。报告中的
`diagnostics` 只保存挑战类型、稳定状态和错误类别，不保存凭据、正文或签名 URL。

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
707 passed, 6 skipped on Python 3.11
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

2026-09-23 使用 v0.6 真实浏览器、独立直连配置、断点检查点和收紧的单路预算
复测：

```text
Fuel-cell classics       14 / 20 VERIFIED
CDI                       9 / 10 VERIFIED
Seawater desalination     8 / 10 VERIFIED
------------------------------------------
Combined                 31 / 40 = 77.5%
```

CDI 余下 1 篇为明确的 `ENTITLEMENT_REQUIRED`。海水淡化余下 ASCE 与 IEEE
在原始批次均为 `INTERACTION_REQUIRED`；IEEE 后续改为用户操作/本地文件导入，
不再自动请求 Xplore。MDPI 曾出现
Edge 已下载但 AN 未接管文件的情况；修复后使用 Browser-domain 完成事件和隔离
临时目录保存，真实单篇及 10 篇集内回归均为 `VERIFIED`。用户放弃 ASCE 机构
登录后，后续项目现会继续执行，不再被错误标成 `DEFERRED`。

燃料电池集中的 3 篇 ScienceDirect 在完成国科大机构认证后的独立真实回归为
3/3 `VERIFIED`；上表仍采用同一批次短预算结果（其中这 3 篇为
`EXHAUSTED`），避免把单篇结果混入批次统计。该差异表明短预算和站点挑战状态
仍会造成批次波动，而不是文件身份验证降级。

Nature 失败项的独立真实复测进一步定位到两个不同原因：
`10.1038/35104620` 与 `10.1038/nature02863` 的正确 PDF 可获取，但旧版
第一页文本提取顺序把标题排在前 200 个词之后，导致 `RETRIEVED_UNVERIFIED`。
现在 AN 优先尝试与 DOI 对应的 Nature 官方 PDF 路径，并允许第一页任意位置的
**完整标题精确匹配**（不扫描后续参考文献页）；两篇均已重新自动保存并
`VERIFIED`。`10.1038/nchem.367` 与 `10.1038/s44221-024-00340-4` 仍明确
要求购买文章，归类为 `ENTITLEMENT_REQUIRED`，未绕过订阅权限。这些单篇复测
不回填上面的原始 40 篇批次统计。

该小型困难语料用于暴露路径解析、访问阻断和错误验证问题，**不是通用下载成功率**。测试中没有观察到 false `VERIFIED`；剩余瓶颈既有 publisher/index access layer（出版社/索引访问层），也有 PDF 文本提取与身份判定的边界情况。

历史失败样本中，Wiley、Taylor & Francis、RSC、ACS 与 MDPI 已分别完成真实
浏览器回归。ACS 修复了空标题 PDF 标签页关联和首页导航文字导致的补充材料
误判；RSC/Wiley 的 Chromium PDF 查看器可自动保存后验证。所有真实测试均无
false `VERIFIED`。运行报告写入本地 `downloads/`，不提交可能含短期签名地址的
运行产物。

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
