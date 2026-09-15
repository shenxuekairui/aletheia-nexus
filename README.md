# Aletheia Nexus

> **A local-first scientific knowledge acquisition infrastructure.**  
> 面向科研场景的本地优先科学知识获取基础设施。

Aletheia Nexus 不是一个单纯的“论文下载脚本”。它希望把科研知识获取过程中容易被忽略的身份识别、来源发现、失败语义、可追溯性、验证和后续自动化拆成清晰、可靠、可测试的基础能力，为未来的 Workflow（工作流）、Agent（智能体）和实验室级科研智能系统提供稳定底座。

当前稳定版本：

```text
Aletheia Nexus v0.4.2
Full-text Discovery
全文候选来源发现
```

当前开发分支：

```text
Aletheia Nexus v0.5.0
Direct PDF Acquisition
直接 PDF 获取与验证
```

当前阶段：

```text
Identifier / DOI Core      ✅
Metadata Resolution        ✅
Full-text Discovery        ✅
Reliability & Observability✅
Discovery Performance      ✅

Direct PDF Acquisition     🚧 v0.5.0
Landing Page Resolution    → v0.5.1
Multi-route Acquisition    → v0.5.2
Authenticated Acquisition → later
```

> **v0.4 的边界：Discovery 负责回答“哪里可能有全文？”。v0.5 开始负责真正获取文件并验证“拿到的是不是目标论文正文”。**

---

## 1. Why Aletheia Nexus

表面上，科研文献获取似乎只是：

```text
DOI
↓
PDF
```

但一个可靠系统真正需要回答的是：

```text
输入真的是 DOI 吗？
↓
它对应什么科研对象？
↓
元数据来自哪里？
↓
有哪些可能的全文路径？
↓
这个链接是出版社、仓储、索引还是解析入口？
↓
数据源失败意味着什么？值得重试吗？
↓
多个来源重复或冲突时如何处理？
↓
哪个路径最值得下一步尝试？
↓
实际下载回来的内容真的是目标论文吗？
```

因此项目采取分层路线：

```text
科研对象标识
    ↓
身份标准化
    ↓
元数据解析
    ↓
全文来源发现        ← v0.4 已完成
    ↓
直接 PDF 获取       ← v0.5.0 开发中
    ↓
Landing Page → PDF  ← v0.5.1
    ↓
多路径自动尝试      ← v0.5.2
    ↓
授权获取 / 人在回路 ← later
    ↓
内容解析
    ↓
知识组织
    ↓
Agent / Lab / World
```

核心原则是：

> **先建立可靠、可验证的底层能力，再向更高层自动化和智能推进。**

---

## 2. Architecture

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

当前开发重点仍在 `Acquire`：

```text
Raw input
   ↓
Identifier
   ↓
Normalized DOI
   ↓
Metadata Resolution
   ↓
PaperMetadata
   ↓
Discovery Providers
   ├─ OpenAlex
   └─ Unpaywall
   ↓
FullTextCandidate
   ↓
URL normalization
   ↓
Deduplication + provenance merge
   ↓
Acquisition-oriented ranking
   ↓
DiscoveryResult
   ↓
[v0.5.0] Direct PDF Acquisition
   ↓
PDF + identity validation
   ↓
Verified local file
```

Metadata（元数据）、Discovery（全文发现）和 Fulltext Acquisition（全文获取）目前保留独立的 transport / retry 语义。虽然它们都可能涉及 HTTP、Retry（重试）和错误映射，但业务含义不同；在没有稳定重复之前，项目不为了“减少几行代码”提前抽象成一个复杂公共框架。

---

## 3. Design Principles

Aletheia Nexus 当前遵循以下工程原则：

1. **Correctness before automation（正确性优先于自动化）**：宁可明确未知，也不静默制造确定答案。
2. **Identity before acquisition（先确认身份，再获取内容）**：对象识别和文件获取不混在一起。
3. **Locate and download are different problems（发现与下载是不同问题）**：发现 Candidate 不等于拿到正确文件。
4. **Downloaded is not verified（下载成功不等于验证成功）**：HTTP 200、`application/pdf` 或“能打开”都不等于目标论文已经验证成功。
5. **Temporary and permanent failures are different（临时失败与永久失败不同）**：只对合理的临时错误重试。
6. **External complexity terminates at module boundaries（外部复杂性止于模块边界）**：Provider、Transport、Retry、Batch 各自负责明确问题。
7. **Provenance over black-box results（保留来源而不是只给黑箱结果）**：Candidate 和文件获取都保留 provenance（来源追踪）。
8. **Measure before optimize（先测量，再优化）**：性能优化来自真实 Benchmark，而不是提前设计。
9. **Small, testable, reversible changes（小步、可测试、可回退）**：稳定层不因为下一层需求反复重构。
10. **Local-first（本地优先）**：核心数据、状态和长期知识应尽可能由研究者或实验室掌控。

---

## 4. Installation

要求：

```text
Python >= 3.11
```

推荐使用 Virtual Environment（Python 虚拟环境）。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

检查安装版本：

```powershell
python -c "import importlib.metadata as m; print(m.version('aletheia-nexus'))"
```

在当前 v0.5.0 开发分支上应输出：

```text
0.5.0
```

---

## 5. DOI Core

当前 DOI 基础能力：

```python
normalize_doi()
normalize_dois()
extract_dois()
looks_like_doi()
```

示例：

```python
from aletheia_nexus.core.identifiers.doi import normalize_doi

doi = normalize_doi("https://doi.org/10.1038/NPHYS1170")
print(doi)
```

输出：

```text
10.1038/nphys1170
```

DOI Core 可以处理常见 DOI URL / prefix、大小写、空格、正文标点、百分号编码、包裹符号、复杂历史后缀，并支持批量标准化、稳定去重和自然语言文本中的 DOI 提取。

---

## 6. Metadata Resolution

Metadata 层负责把规范 DOI 解析为统一科研对象元数据。

当前正式支持：

```text
Crossref
DataCite
```

推荐通过统一 Public API（公开接口）使用：

```python
from aletheia_nexus.acquire.metadata import get_metadata

paper = get_metadata("10.1038/nphys1170")

print(paper.doi)
print(paper.title)
print(paper.authors)
print(paper.journal)
print(paper.year)
```

统一模型 `PaperMetadata` 当前字段：

```text
doi
title
authors
journal
issn
published_date
year
publisher
work_type
volume
issue
pages
url
```

Metadata 层还提供：

```python
get_doi_agency()
get_metadata_with_retry()
get_metadata_batch()
```

并明确区分：

```text
NOT_FOUND
UNSUPPORTED_AGENCY
NETWORK_ERROR
RATE_LIMIT
REQUEST_ERROR
SERVICE_ERROR
PARSE_ERROR
```

不会把不同失败原因压缩成一个模糊的 “failed”。

---

## 7. Full-text Discovery

v0.4 新增 Full-text Discovery（全文候选来源发现）。

### Single DOI

```python
from aletheia_nexus.acquire.discovery import discover_full_text

result = discover_full_text(
    "10.1002/anie.201406668",
    unpaywall_email="you@example.com",
)

print(result.doi)

for candidate in result.candidates:
    print(candidate.url)
    print(candidate.url_type)
    print(candidate.access_type)
    print(candidate.version)
    print(candidate.host_type)
    print(candidate.provenance)
```

当前默认 Discovery Provider（发现数据源）：

```text
OpenAlex
Unpaywall
```

Unpaywall 需要邮箱参数；若未提供，系统会明确标记该 Provider 为：

```text
SKIPPED
```

而不是把它伪装成查询失败。

OpenAlex API key 当前是可选配置。

---

## 8. Candidate Contract

统一候选模型：

```python
FullTextCandidate
```

主要字段：

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

### 8.1 `PDF` does not mean verified PDF

```text
CandidateUrlType.PDF
```

表示：

> Provider-reported PDF candidate（数据源报告的 PDF 候选路径）

它**不表示** Aletheia Nexus 已经下载并验证了 PDF。

例如一个 Provider 可能把 Handle resolver（Handle 解析入口）报告成 PDF 路径。真正的：

```text
Content-Type
%PDF magic bytes
文件完整性
可解析性
正文 / Supporting Information 区分
DOI / title / author 身份匹配
```

属于 v0.5 Acquisition + Validation（获取与验证）。

### 8.2 Version is provider-reported

```text
published
accepted
submitted
unknown
```

是 Provider-reported scholarly version（数据源报告的学术版本），不是 AN 独立核验后的事实。

### 8.3 HostType

当前路径类型：

```text
PUBLISHER
REPOSITORY
INDEX
RESOLVER
UNKNOWN
```

真实 Benchmark 已证明需要区分：

```text
doi.org / hdl.handle.net
→ RESOLVER

PubMed / DOAJ
→ INDEX

PMC
→ REPOSITORY
```

系统不会维护一张庞大的出版社域名硬编码表。

### 8.4 Ranking is acquisition priority

Candidate 排序回答的是：

> **下一步 Acquisition 应优先尝试哪个路径？**

而不是：

> **哪个版本在学术意义上最权威？**

当前排序主要考虑 OA、Provider-reported PDF、版本、路径类型和 best-location signal（最佳位置提示）。

`is_best` 也是 Provider 侧信号，不应解释成 AN 已验证的“全局最佳全文”。

---

## 9. URL Normalization and Deduplication

Discovery Provider 是外部输入，因此 Candidate URL 在进入后续 Acquisition 前会进行基础校验与标准化：

```text
只接受 HTTP / HTTPS
必须存在 hostname
拒绝 URL 内嵌账号密码
移除 fragment
去除安全的 Markdown / quote wrapper
统一 scheme / host 大小写
```

真实语料还发现了持久解析器的等价 URL：

```text
http://hdl.handle.net/...
https://hdl.handle.net/...
```

以及旧 DOI resolver：

```text
http://doi.org/...
https://dx.doi.org/...
https://www.doi.org/...
```

v0.4.2 只对这些已经有真实证据支持的 Resolver（解析器）做更强 canonicalization（规范化），不会把普通网站的 HTTP 全局强制改成 HTTPS。

相同规范 URL 会合并 provenance。`license` 和 `source_name` 只有在非空报告一致时才保留；来源冲突时保持未知，不静默选择某个 Provider 的值。

---

## 10. Reliability

### Provider failure isolation

一个 Provider 失败不会自动拖垮另一个 Provider。

例如：

```text
OpenAlex NETWORK_ERROR
+
Unpaywall SUCCESS
↓
仍然保留可用 Candidate
↓
Batch 可表达 PARTIAL_SUCCESS
```

### Retry

仅以下临时错误自动 Retry（重试）：

```text
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
```

不自动重试：

```text
NOT_FOUND
REQUEST_ERROR
PARSE_ERROR
CONFIGURATION_ERROR
```

Retry 使用有界 Exponential Backoff（指数退避），并保留：

```text
attempts
elapsed_seconds
final error
```

未知编程错误不会被伪装成普通 Provider failure，而是继续显式抛出。

---

## 11. Batch Discovery

```python
from aletheia_nexus.acquire.discovery import discover_full_text_batch

results = discover_full_text_batch(
    [
        "10.1002/anie.201406668",
        "10.1038/s41467-024-49639-6",
    ],
    unpaywall_email="you@example.com",
)

for item in results:
    print(item.input_value, item.doi, item.status, item.elapsed_seconds)
```

Batch（批处理）当前支持：

```text
DOI 标准化
稳定去重
原输入保留
单条失败隔离
单条耗时
Provider 配置透传
```

Batch 状态：

```text
SUCCESS
PARTIAL_SUCCESS
NO_CANDIDATES
NOT_FOUND
INVALID_DOI
ERROR
```

当前 Batch item 仍顺序执行；每个 DOI 内的 OpenAlex 与 Unpaywall 使用 Provider-level Bounded Concurrency（数据源级有限并发）。这是经过真实性能数据验证后引入的最小并发层级。

---

## 12. Observability and Provider Evaluation

Discovery 运行结果保留：

```text
source / provider
status
attempts
elapsed_seconds
error
candidates
provenance
```

Provider-level 并发后，Benchmark 不再错误地把各 Provider 耗时之和当成墙钟时间，而区分：

```text
provider work sum
provider critical path
provider overlap factor
discovery wall time
coordination estimate
batch wrapper overhead
```

v0.4.2 还提供：

```python
from aletheia_nexus.acquire.discovery import summarize_provider_contributions
```

用于统计：

```text
candidate routes
unique routes
shared routes
exclusive metadata contributions
metadata disagreements
```

Provider 冲突只被记录，不在评价层擅自决定哪个来源更权威。

---

## 13. Real-network Benchmark

仓库保留可复现的 30 篇水电解跨出版社 Benchmark corpus（基准语料）：

```text
benchmarks/discovery_water_electrolysis_30.txt
```

覆盖 AAAS、Wiley、ACS、RSC、Nature Portfolio、Elsevier、Springer、MDPI、Frontiers、IOP、ECS、ECSJ/J-STAGE、AIP、Taylor & Francis、Oxford 等不同出版生态。

同一 30 篇、同一两 Provider 的真实网络结果：

| Metric | v0.4.1 sequential | v0.4.2 provider concurrency |
| --- | ---: | ---: |
| Discovery SUCCESS | 30 / 30 | 30 / 30 |
| Batch elapsed | 66.484 s | **32.783 s** |
| Speedup | 1.00× | **2.03×** |
| Elapsed reduction | — | **50.7%** |
| Works with OA candidate | 20 | 20 |
| Works with PDF candidate | 15 | 15 |
| Works with non-resolver route | 24 | 24 |
| Works with publisher/repository route | 17 | 17 |

v0.4.2 最终得到 97 个 merged candidates（合并候选）。相较早期 98 个减少 1 个，是因为等价 Handle HTTP/HTTPS 路径被正确合并，不是覆盖率下降。

> 这是一组化学 / 能源领域的工程验收语料，不代表所有学科的全球覆盖率结论。

手动复测：

```powershell
$env:UNPAYWALL_EMAIL = "you@example.com"
python scripts/manual_discovery_acceptance.py `
  --doi-file benchmarks/discovery_water_electrolysis_30.txt `
  --baseline-seconds 66.484
```

如有 OpenAlex API key：

```powershell
$env:OPENALEX_API_KEY = "your-key"
```

真实网络验收脚本刻意不进入 CI，避免把外部服务波动变成代码测试不稳定。

---

## 14. Why Not Add More Providers Yet

30 篇当前语料中：

```text
OpenAlex unique routes      41
OpenAlex + Unpaywall shared 56
Unpaywall unique routes      0
```

这不能证明 Unpaywall 在所有学科都没有价值，但说明当前最明显的实际缺口不是“缺第三个广域学术图谱 API”，而是：

```text
Known landing / repository route
↓
实际访问页面
↓
解析真实文件入口
↓
下载
↓
验证是否为目标正文
```

因此 v0.4 不继续堆叠 Provider。

当前候选方向：

```text
Semantic Scholar
→ 最值得未来用 gap corpus（缺口语料集）先测的广域候选

Crossref link
→ 更适合作为已有 Metadata 能力的后备 acquisition hint

CORE
→ 机构仓储缺口出现稳定证据时再评估

Europe PMC
→ 未来生物医学 / 生命科学工作流的领域型候选
```

完整判断见：

```text
docs/v0.4.2-provider-assessment.md
```

---

## v0.5.0 Direct PDF Acquisition — In Development

第一版 v0.5 只解决一个明确问题：

```text
FullTextCandidate(url_type=PDF)
↓
安全访问
↓
流式下载
↓
PDF 文件验证
↓
DOI / 标题身份验证
↓
Supporting Information 判断
↓
VERIFIED local file
```

公开接口：

```python
from aletheia_nexus.acquire.fulltext import acquire_direct_pdf

result = acquire_direct_pdf(
    candidate,
    output_dir="downloads",
    expected_title="Optional known paper title",
)
```

第一版的核心成功条件：

```text
VERIFIED
=
valid PDF
+
identity MATCH
+
ARTICLE role
```

因此：

```text
HTTP 200              ≠ VERIFIED
application/pdf       ≠ VERIFIED
能正常打开 PDF        ≠ VERIFIED
目标论文身份未确认     ≠ VERIFIED
```

主要结果状态：

```text
VERIFIED
RETRIEVED_UNVERIFIED
SUPPLEMENT
MISMATCH
INVALID_PDF
AUTH_REQUIRED
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

安全与存储原则：

```text
每个 redirect 重新检查 URL
拒绝 localhost / private / link-local / reserved network
默认最大下载 100 MiB
下载时计算 SHA-256
先写临时文件
验证通过后原子移动
正式 PDF 旁保存 .acquisition.json 来源记录
```

证据不足的正常 PDF 返回 `RETRIEVED_UNVERIFIED`，默认不进入正式文件目录；如显式设置 `keep_unverified=True`，才保留到 `_unverified/` 供 Human-in-the-loop（人在回路中）检查。

完整 v0.5.0 设计记录见：

```text
docs/v0.5.0-direct-acquisition.md
```

---

## 15. Repository Layout

```text
aletheia-nexus/
│
├─ src/aletheia_nexus/
│  ├─ core/
│  │  └─ identifiers/
│  │
│  └─ acquire/
│     ├─ metadata/
│     ├─ discovery/
│     └─ fulltext/
│
├─ tests/
│  ├─ core/
│  └─ acquire/
│     ├─ metadata/
│     ├─ discovery/
│     └─ fulltext/
│
├─ scripts/
│  ├─ manual_metadata_acceptance.py
│  ├─ manual_discovery_acceptance.py
│  └─ manual_direct_acquisition.py
│
├─ benchmarks/
│  └─ discovery_water_electrolysis_30.txt
│
└─ docs/
```

测试代码只保存在 `tests/`，不会混入正式安装包。

---

## 16. Development and CI

本地质量检查：

```powershell
ruff format --check .
ruff check .
python -m compileall -q src
python -m pytest -q
python -m pip check
```

GitHub Actions 当前同时验证：

```text
Python 3.11
Python 3.14
```

每个环境执行：

```text
editable install
pip check
Ruff format
Ruff static checks
compileall
pytest
```

CI 只验证确定性代码行为；真实第三方 API / 出版社网络验收保留为手动测试。

v0.5.0 手工直接 PDF 验收入口：

```powershell
python scripts/manual_direct_acquisition.py `
  --doi "10.xxxx/xxxx" `
  --url "https://.../paper.pdf" `
  --title "Paper title" `
  --output-dir "downloads"
```

---

## 17. v0.4 Boundaries

v0.4 **没有**实现：

```text
真正下载 PDF
Content-Type / magic bytes 验证
PDF 完整性与可解析性验证
正文 vs Supplementary 区分
DOI / title / author 文件身份核验
Landing Page HTML → PDF 解析
机构订阅权限
CARSI / SSO
浏览器自动化
验证码处理
文件存储与冲突管理
```

这是 v0.4 的冻结边界。其中“直接 PDF 获取 + PDF/身份验证 + 基础本地存储”已经进入 v0.5.0 开发；Landing Page、多路径编排和授权获取仍属于后续 v0.5 小版本。

---

## 18. v0.5 Roadmap

当前按可靠性从低层向上推进：

```text
v0.5.0 Direct PDF Acquisition
直接 PDF 获取 + PDF/身份验证
↓
v0.5.1 Landing Page Resolution
落地页 → PDF 入口
↓
v0.5.2 Multi-route Acquisition
多个 Candidate 自动依次尝试
↓
v0.5.x Authenticated Acquisition
机构授权 / CARSI / SSO / Browser / Human-in-the-loop
```

目标是把当前：

```text
Paper Identity
→ Possible Sources
→ Access Paths
```

继续推进到：

```text
Acquisition Strategy
→ Retrieved File
→ Verified File
→ Traceable Scientific Object
```

高风险、低置信度、登录、验证码等步骤应允许 Human-in-the-loop（人在回路中），而不是为了“全自动”强行绕过真实边界。

---

## 19. Documentation

v0.4 相关文档：

```text
docs/v0.4-discovery.md
    最终 v0.4 Discovery 契约与冻结说明

docs/v0.4.1-discovery-reliability.md
    v0.4.1 可靠性与可观测性强化记录

docs/v0.4.2-discovery-performance.md
    v0.4.2 性能与评价记录

docs/v0.4.2-provider-assessment.md
    Provider 扩展评估
```

v0.5 开发文档：

```text
docs/v0.5.0-direct-acquisition.md
    Direct PDF Acquisition 第一版设计、边界与状态语义
```

v0.4.1 / v0.4.2 文档保留迭代和验收历史；`v0.4-discovery.md` 作为最终 v0.4 行为契约。v0.5 文档在对应小版本冻结后再形成最终契约。

---

## 20. Project Direction

Aletheia Nexus 的长期价值不只在于某个模型、某个脚本或某次自动下载，而在于持续积累：

```text
可靠的数据表示
来源与 provenance
稳定工具
失败语义
Benchmark
评价标准
工作流
历史决策
实验室知识
```

最终希望形成的是一套可以被研究者、Workflow 和 Agent 稳定复用的科研智能基础设施，而不是把所有问题都交给一个不可验证的“万能智能体”。
