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
v0.5.0 Direct PDF Acquisition
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

> **v0.4 的边界：Discovery 负责回答“哪里可能有全文？”。**  
> **v0.5 的边界：Acquisition 负责把候选路径变成可追溯、经过验证的本地文件结果。**

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
网页 → PDF          ← v0.5.1
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

Metadata（元数据）、Discovery（全文发现）和 Fulltext Acquisition（全文获取）保持明确的模块边界。它们虽然都可能涉及 HTTP、Retry（重试）和错误映射，但业务语义不同；项目不会为了“减少几行代码”提前抽象成复杂公共框架。

---

## 3. Design Principles

Aletheia Nexus 当前遵循以下工程原则：

1. **Correctness before automation（正确性优先于自动化）**：宁可明确未知，也不静默制造确定答案。
2. **Identity before acquisition（先确认身份，再获取内容）**：对象识别和文件获取不混在一起。
3. **Locate and download are different problems（发现与下载是不同问题）**：发现 Candidate 不等于拿到正确文件。
4. **Downloaded is not verified（下载成功不等于验证成功）**：只有文件格式、论文身份和文档角色证据足够时才允许标记为 `VERIFIED`。
5. **Temporary and permanent failures are different（临时失败与永久失败不同）**：只对合理的临时错误重试。
6. **External complexity terminates at module boundaries（外部复杂性止于模块边界）**：Provider、Transport、Retry、Batch 各自负责明确问题。
7. **Provenance over black-box results（保留来源而不是只给黑箱结果）**：Candidate 与获取结果保留 provenance（来源追踪）。
8. **Measure before optimize（先测量，再优化）**：性能优化针对真实瓶颈，而不是理论瓶颈。
9. **Small, testable, reversible changes（小步、可测试、可回退）**：稳定层不因为下一层需求反复重构。
10. **Local-first（本地优先）**：核心数据、文件、状态和长期知识应尽可能由研究者或实验室掌控。

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

在 v0.5.0 开发分支上应输出：

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

v0.4 的 Full-text Discovery（全文候选来源发现）已经稳定。

### Single DOI

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

当前默认 Discovery Provider（发现数据源）：

```text
OpenAlex
Unpaywall
```

Unpaywall 需要邮箱参数；若未提供，系统会明确标记该 Provider 为 `SKIPPED`，而不是把它伪装成查询失败。

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

### `PDF` does not mean verified PDF

```text
CandidateUrlType.PDF
```

表示：

> Provider-reported PDF candidate（数据源报告的 PDF 候选路径）

它**不表示** Aletheia Nexus 已经下载并验证了 PDF。

### Ranking is acquisition priority

Candidate 排序回答的是：

> **下一步 Acquisition 应优先尝试哪个路径？**

而不是：

> **哪个版本在学术意义上最权威？**

---

## 9. v0.5.0 Direct PDF Acquisition

v0.5.0 第一版只处理：

```text
FullTextCandidate
且 url_type = PDF
```

统一公开接口：

```python
from aletheia_nexus.acquire.fulltext import acquire_direct_pdf

result = acquire_direct_pdf(
    candidate,
    output_dir="downloads",
    expected_title="Optional known paper title",
)
```

处理链：

```text
PDF Candidate
↓
URL / network safety check
↓
manual redirect validation
↓
streaming download
↓
SHA-256
↓
PDF structural validation
↓
DOI / title identity evidence
↓
Supporting Information check
↓
VERIFIED or explicit non-verified status
```

### Success is deliberately strict

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
能被 PDF 阅读器打开   ≠ VERIFIED
目标 DOI / 标题吻合前 ≠ VERIFIED
```

### Stable acquisition outcomes

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

证据不足时使用 `RETRIEVED_UNVERIFIED`，而不是猜测。

### Storage

验证通过后保存：

```text
<safe-doi>-<sha256-prefix>.pdf
<safe-doi>-<sha256-prefix>.acquisition.json
```

sidecar（旁路记录）保留：

```text
目标 DOI / 标题
Candidate 来源与语义
请求 URL / 最终 URL
redirect chain
HTTP status / Content-Type
文件大小
SHA-256
PDF 验证
身份验证
文档角色
attempts / elapsed time
时间戳
```

未验证文件默认删除；如显式使用 `keep_unverified=True`，则进入 `_unverified/` 供 Human-in-the-loop（人在回路中）检查。

---

## 10. Reliability and Safety

### Retry

Discovery 与 Acquisition 都只对合理的临时错误自动重试。

v0.5.0 自动 Retry：

```text
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
```

不自动 Retry：

```text
AUTH_REQUIRED
NOT_FOUND
TOO_LARGE
UNSAFE_URL
REDIRECT_ERROR
REQUEST_ERROR
```

未知编程错误不会被伪装成普通 Acquisition failure，而是继续显式抛出。

### Retrieval safety

v0.5.0 开始真正访问外部 Candidate URL，因此比 v0.4 Discovery 增加更严格的网络安全边界：

```text
HTTP(S) only
hostname required
embedded credentials rejected
localhost / private / link-local / reserved network rejected
DNS result checked
redirect target re-checked on every hop
```

默认：

```text
max_bytes       100 MiB
max_redirects   8
timeout          30 s
max_attempts     3
```

---

## 11. Tests and CI

每次 Push / Pull Request 都运行：

```text
Python 3.11
Python 3.14

editable install
pip check
Ruff format check
Ruff static check
compileall src
pytest
```

真实第三方 API / 出版社网络请求不进入 CI，而由 `scripts/manual_*_acceptance.py` 负责人工真实网络验收，避免外部服务波动造成假回归。

v0.5.0 新增手工入口：

```powershell
python scripts/manual_direct_acquisition.py `
  --doi "10.xxxx/xxxx" `
  --url "https://.../paper.pdf" `
  --title "Paper title" `
  --output-dir "downloads"
```

---

## 12. Roadmap

```text
v0.1–0.2  DOI / Identifier              ✅
v0.3      Metadata Resolution            ✅
v0.4      Full-text Discovery            ✅
v0.5.0    Direct PDF Acquisition         🚧
v0.5.1    Landing Page Resolution        Next
v0.5.2    Multi-route Acquisition        Later
v0.5.x    Authenticated Acquisition      Later
```

v0.5.0 刻意不做：

```text
Landing Page → PDF
自动尝试多个 Candidate
CARSI / SSO
浏览器自动化
验证码处理
全文内容解析
知识组织
批量下载并发
```

这些问题只有在前一层能力稳定后才逐层加入。
