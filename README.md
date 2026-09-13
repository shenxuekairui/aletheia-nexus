# Aletheia Nexus

**A local-first scientific knowledge acquisition infrastructure.**

Aletheia Nexus 是一个面向科研场景的本地优先（local-first）科学知识获取基础设施。

项目目标不是简单实现“下载论文”，而是逐步建立一条可靠、可验证、可扩展的科研知识获取链路：

```text
文献标识符
    ↓
元数据解析
    ↓
全文候选发现
    ↓
全文获取
    ↓
PDF 验证
    ↓
结构化解析
    ↓
知识组织
    ↓
Agent / Lab / World
```

当前版本：

```text
Aletheia Nexus v0.3.0
Metadata Resolution
```

---

# 1. Project Vision

Aletheia Nexus 的长期结构规划为：

```text
Aletheia Nexus
├─ Acquire
│  ├─ Metadata
│  ├─ Discovery
│  └─ Acquisition
│
├─ Parse
├─ Knowledge
├─ Agent
├─ Lab
└─ World
```

当前主要开发：

```text
Acquire
└─ Metadata
```

核心设计原则：

- 元数据获取与全文下载分离
- 文献身份识别与下载来源分离
- 不把 HTTP 200 等同于成功
- 不把某一个数据库“查不到”等同于文献不存在
- 外部数据源统一转换为内部标准模型
- 临时错误与永久错误采用不同处理策略
- 自动化行为必须具有明确状态和可测试性
- 先保证正确性和可维护性，再优化并发与性能

---

# 2. Current Status

## v0.1 — Basic DOI

完成最基础的 DOI（Digital Object Identifier，数字对象唯一标识符）处理：

```text
DOI / DOI URL
↓
标准 DOI
```

主要能力：

- DOI 基础标准化
- `doi.org` URL 处理
- 基础单元测试

---

## v0.2 — DOI Core

建立较完整的 DOI 核心层。

主要能力：

```text
normalize_doi()
normalize_dois()
extract_dois()
looks_like_doi()
```

支持：

- 单 DOI 标准化
- 批量 DOI 标准化
- 自然语言文本中的 DOI 提取
- DOI URL
- `DOI:` 标签
- 中英文标点
- 包裹符号
- URL query parameter（查询参数）
- URL fragment（片段）
- 大小写统一
- 稳定去重
- 历史复杂 DOI
- 常见假阳性控制
- 非法输入识别

V0.2 建立了一套独立的现实 DOI 测试规范，并完成自动化回归测试。

---

## v0.3 — Metadata Resolution

V0.3 将系统从：

```text
“我知道这是哪个 DOI”
```

升级为：

```text
“我知道这个 DOI 对应什么科研对象”
```

完整链路：

```text
原始 DOI / DOI URL
        ↓
DOI Core
        ↓
DOI Registration Agency Detection
（DOI 注册机构识别）
        ↓
   ┌───────────────┐
   ↓               ↓
Crossref         DataCite
   ↓               ↓
   └───────┬───────┘
           ↓
     PaperMetadata
           ↓
Retry + Exponential Backoff
（自动重试 + 指数退避）
           ↓
Unified Batch Resolution
（统一批量解析）
           ↓
MetadataLookupResult
```

---

# 3. Supported Metadata Sources

当前正式支持：

```text
Crossref
DataCite
```

系统可以自动识别 DOI 的 Registration Agency（注册机构），并将 DOI 路由到对应数据源。

例如：

```text
10.1038/nphys1170
→ Crossref

10.5281/zenodo.31780
→ DataCite
```

Crossref 与 DataCite 可以覆盖大量主流科研 DOI，但并不代表全部科研文献或全部 DOI 注册机构。

暂未支持的 DOI 注册机构会被明确标记为：

```text
UNSUPPORTED_AGENCY
```

而不会被错误判断为：

```text
NOT_FOUND
```

---

# 4. Unified Metadata Model

不同元数据服务返回的数据结构差异很大。

例如：

```text
Crossref JSON
DataCite JSON
```

最终都会转换为 Aletheia Nexus 自己的统一模型：

```python
PaperMetadata
```

当前字段：

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

因此上层模块不需要关心：

```text
数据来自 Crossref
还是 DataCite
```

只需要处理统一的：

```python
PaperMetadata
```

---

# 5. Installation

项目使用 Python：

```text
Python >= 3.11
```

建议在虚拟环境（virtual environment）中开发。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装项目及开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

验证安装：

```powershell
python -c "import importlib.metadata as m; print(m.version('aletheia-nexus'))"
```

当前应输出：

```text
0.3.0
```

---

# 6. Basic Usage

## Single DOI Metadata

统一入口：

```python
from aletheia_nexus.acquire.metadata import get_metadata

paper = get_metadata(
    "10.1038/nphys1170"
)

print(paper.title)
print(paper.authors)
print(paper.journal)
print(paper.year)
```

系统内部自动完成：

```text
DOI 标准化
↓
注册机构识别
↓
Crossref / DataCite 路由
↓
元数据解析
↓
PaperMetadata
```

---

# 7. Retry

对于临时故障，可以使用：

```python
from aletheia_nexus.acquire.metadata import (
    get_metadata_with_retry,
)

paper = get_metadata_with_retry(
    "10.1038/nphys1170",
    max_attempts=3,
    backoff_base=1.0,
)
```

默认指数退避：

```text
第一次失败
→ 等待 1 秒

第二次失败
→ 等待 2 秒

第三次请求
→ 成功则返回
→ 仍失败则抛出最终异常
```

当前会自动重试：

```text
MetadataNetworkError
RateLimitError
MetadataServiceError
```

不会重试：

```text
MetadataNotFoundError
MetadataRequestError
MetadataParseError
UnsupportedAgencyError
```

也就是说：

```text
网络临时波动
429 请求限流
5xx 服务端错误
→ 可以重试
```

而：

```text
DOI 不存在
普通 4xx 请求错误
响应结构无法解析
暂不支持的注册机构
→ 重试通常没有意义
```

---

# 8. Batch Metadata Resolution

批量查询统一使用：

```python
from aletheia_nexus.acquire.metadata import (
    get_metadata_batch,
)

results = get_metadata_batch(
    [
        "10.1038/nphys1170",
        "10.5281/zenodo.31780",
        "10.9999/not-real-doi",
        "not a doi",
    ],
    max_attempts=3,
    backoff_base=1.0,
)

for result in results:
    print(
        result.status,
        result.doi,
    )
```

批量层支持：

```text
DOI 标准化
稳定去重
多数据源自动路由
逐条独立查询
自动重试
逐条错误隔离
保持输入顺序
保存原始输入
```

其中一条 DOI 失败不会终止整个批次。

例如：

```text
SUCCESS        10.1038/nphys1170
SUCCESS        10.5281/zenodo.31780
NOT_FOUND      10.9999/not-real-doi
INVALID_DOI    -
```

---

# 9. Batch Status

每一条批量结果都会对应一个稳定状态。

```text
SUCCESS
INVALID_DOI
NOT_FOUND
UNSUPPORTED_AGENCY
REQUEST_ERROR
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
PARSE_ERROR
```

含义：

| Status | Meaning |
|---|---|
| `SUCCESS` | 元数据解析成功 |
| `INVALID_DOI` | 输入不是合法 DOI |
| `NOT_FOUND` | 对应 DOI / 元数据未找到 |
| `UNSUPPORTED_AGENCY` | DOI 注册机构暂未支持 |
| `REQUEST_ERROR` | 普通 HTTP 4xx 请求错误 |
| `NETWORK_ERROR` | 网络连接或超时错误 |
| `RATE_LIMITED` | API 返回 429，请求被限流 |
| `SERVICE_ERROR` | API 服务端 5xx 错误 |
| `PARSE_ERROR` | 返回数据无法正确解析 |

---

# 10. Exception Model

元数据模块采用统一异常体系：

```text
MetadataError
├─ MetadataNotFoundError
├─ MetadataNetworkError
├─ MetadataRequestError
├─ MetadataServiceError
├─ MetadataParseError
├─ RateLimitError
└─ UnsupportedAgencyError
```

因此上层既可以：

```python
except MetadataNetworkError:
    ...
```

精确处理某种问题，也可以：

```python
except MetadataError:
    ...
```

统一捕获所有元数据层异常。

---

# 11. HTTP Error Semantics

当前 HTTP 状态码约定：

```text
404
→ MetadataNotFoundError

429
→ RateLimitError

其他 4xx
→ MetadataRequestError

5xx
→ MetadataServiceError
```

这一区分非常重要，因为它决定了系统是否应该自动重试。

---

# 12. Testing

项目使用：

```text
pytest
```

运行全部测试：

```powershell
python -m pytest -v
```

检查 Python 源码语法：

```powershell
python -m compileall -q src
```

当前测试覆盖：

```text
DOI normalization
DOI extraction
DOI batch processing
DOI realistic boundary cases

PaperMetadata

Crossref parsing
Crossref HTTP errors
Crossref network errors
Crossref malformed responses

DataCite parsing
DataCite field variations
DataCite HTTP errors
DataCite network errors
DataCite malformed responses

DOI agency detection
Crossref / DataCite routing
Unsupported agencies

Retry behavior
Exponential backoff
Retry / non-retry error classification

Unified batch resolution
Stable deduplication
Independent batch statuses

Public metadata API
```

测试中的外部 HTTP 请求主要通过 mock / monkeypatch（模拟 / 运行时替换）完成，因此自动测试不依赖真实 Crossref 或 DataCite 网络状态。

---

# 13. Current Source Structure

```text
src/
└─ aletheia_nexus/
   ├─ core/
   │  ├─ models.py
   │  │  └─ PaperMetadata
   │  │
   │  └─ identifiers/
   │     └─ doi.py
   │
   └─ acquire/
      └─ metadata/
         ├─ __init__.py
         ├─ exceptions.py
         ├─ crossref.py
         ├─ datacite.py
         ├─ resolver.py
         ├─ retry.py
         └─ batch.py
```

测试：

```text
tests/
├─ data/
│  └─ doi_v0_2_spec_cases.json
│
├─ core/
│  └─ identifiers/
│     ├─ test_doi.py
│     └─ test_doi_spec.py
│
└─ acquire/
   └─ metadata/
      ├─ test_crossref.py
      ├─ test_datacite.py
      ├─ test_resolver.py
      ├─ test_retry.py
      ├─ test_batch.py
      └─ test_public_api.py
```

---

# 14. Public Metadata API

V0.3 推荐从统一入口导入：

```python
from aletheia_nexus.acquire.metadata import (
    get_metadata,
    get_metadata_with_retry,
    get_metadata_batch,
)
```

而不是让上层直接依赖：

```text
crossref.py
datacite.py
resolver.py
retry.py
batch.py
```

内部文件结构以后可以继续重构，但公开 API 应尽量保持稳定。

---

# 15. What v0.3 Does Not Do

V0.3 只负责：

```text
DOI
↓
可靠的标准化元数据
```

它暂时不负责：

```text
寻找 PDF
判断开放获取状态
出版社全文链接发现
机构订阅权限
浏览器登录
SSO
PDF 下载
PDF 身份验证
PDF 内容解析
```

这些属于后续版本。

---

# 16. Roadmap

当前版本路线：

```text
v0.1
Basic DOI
✅

v0.2
DOI Core
✅

v0.3
Metadata Resolution
✅

v0.4
Full-text Candidate Discovery
→ 下一阶段

v0.5
Acquisition + PDF Validation
→ 后续阶段
```

## v0.4 — Discovery

目标：

```text
PaperMetadata
↓
发现可能的全文来源
↓
Full-text Candidates
```

计划考虑：

```text
Unpaywall
OpenAlex
Crossref links
DataCite links
publisher landing pages
publisher APIs
Europe PMC
其他合法公开全文来源
```

重点是：

> Discovery 只负责“在哪里可能获得全文”，不直接负责真正下载。

---

## v0.5 — Acquisition

目标：

```text
Full-text Candidate
↓
Download
↓
PDF Validation
↓
Identity Verification
↓
Canonical Storage
```

计划能力包括：

```text
Direct HTTP
Publisher APIs
Institutional browser / SSO
Playwright persistent browser profile
Human-in-the-loop authentication
PDF signature validation
PyMuPDF parse validation
DOI / title / author identity matching
SHA-256
atomic file writes
conflict preservation
```

---

# 17. Long-term Direction

Aletheia Nexus 最终希望形成：

```text
Acquire
↓
Parse
↓
Knowledge
↓
Agent
↓
Lab
↓
World
```

其中 Acquire 不只是一个下载器，而是整个系统的可信数据入口。

核心目标是：

```text
不是“尽可能下载一个 PDF”

而是：

确认目标文献
↓
寻找合法可用来源
↓
获取文件
↓
验证文件真实性
↓
形成可追溯的科研知识对象
```

---

# 18. Development Philosophy

Aletheia Nexus 当前遵循：

```text
Correctness before speed.
Reliability before concurrency.
Explicit states before silent failure.
Tests before large-scale automation.
Simple modules before premature abstraction.
```

即：

```text
正确性优先于速度
可靠性优先于并发
明确状态优先于静默失败
自动化测试优先于大规模自动化
简单模块优先于过早抽象
```

---

# License

To be determined.