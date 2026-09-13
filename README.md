# Aletheia Nexus

> **A local-first scientific knowledge acquisition infrastructure.**  
> 面向科研场景的本地优先科学知识获取基础设施。

Aletheia Nexus 的目标不是做一个简单的“论文下载脚本”，而是逐步构建一套 **可靠、可验证、可扩展、可自动化** 的科研知识获取基础设施。

它试图解决的是一条完整链路：

```text
科研对象标识
    ↓
身份标准化
    ↓
元数据解析
    ↓
全文来源发现
    ↓
全文获取
    ↓
文件验证
    ↓
内容解析
    ↓
知识组织
    ↓
Agent / Lab / World
```

当前版本：

```text
Aletheia Nexus v0.3.2
Metadata Stabilization
```

当前阶段已经完成：

```text
DOI Core
+
Metadata Resolution
+
Stable Transport Layer
+
Retry / Batch Infrastructure
+
Automated Quality Checks
```

下一阶段：

```text
v0.4
Full-text Candidate Discovery
全文候选来源发现
```

---

## 1. Why Aletheia Nexus

科研文献获取看起来像一个简单问题：

```text
输入 DOI
↓
下载 PDF
```

但真正可靠的科研知识获取系统需要处理更多问题：

```text
这个输入真的是 DOI 吗？

这个 DOI 属于哪个注册机构？

对应的科研对象到底是什么？

Crossref 和 DataCite 返回的数据怎么统一？

一次 API 请求失败意味着文献不存在吗？

429、网络超时、404、5xx 应该如何区分？

同一篇文献有哪些可能的全文来源？

下载回来的文件真的是 PDF 吗？

这个 PDF 真的是目标论文吗？

多个来源冲突时应该相信谁？

如何保存来源、状态和失败原因？

如何让后续 Agent 能稳定调用这些能力？
```

因此 Aletheia Nexus 的核心思想是：

> **先建立可靠的科研知识获取基础设施，再在其上构建自动化、Agent 和科学知识系统。**

---

## 2. Long-term Architecture

Aletheia Nexus 的长期结构规划：

```text
Aletheia Nexus
│
├─ Acquire
│  ├─ Identifier
│  ├─ Metadata
│  ├─ Discovery
│  └─ Acquisition
│
├─ Parse
│
├─ Knowledge
│
├─ Agent
│
├─ Lab
│
└─ World
```

各层职责：

```text
Acquire
→ 找到并可靠获取科研信息

Parse
→ 从 PDF / HTML / Supplementary 等内容中提取结构化信息

Knowledge
→ 构建可检索、可追踪来源的科研知识层

Agent
→ 让 AI Agent 调用稳定的科研工具完成复杂任务

Lab
→ 与实验室数据、实验流程、ELN、自动化设备等连接

World
→ 面向更高层的科学模型、科学世界模型与知识推理
```

当前主要开发范围：

```text
Acquire
├─ DOI Core          ✅
├─ Metadata          ✅
├─ Discovery         ← Next
└─ Acquisition
```

---

## 3. Design Principles

Aletheia Nexus 当前遵循以下设计原则。

### 3.1 Identity before acquisition

先确认：

```text
“我要找的科研对象到底是什么”
```

再处理：

```text
“从哪里获得全文”
```

身份解析和全文获取不应混在一起。

---

### 3.2 Locate and Download are different problems

```text
Locate
→ 找到候选全文来源

Download
→ 从某个来源真正获取内容
```

“找到了链接”和“成功得到正确全文”不是同一件事。

---

### 3.3 HTTP 200 does not mean success

网络请求成功只说明服务器返回了内容。

它不代表：

```text
这是 PDF
这是目标论文
文件完整
内容可以解析
身份匹配
```

因此未来的 Acquisition 层会继续进行文件和身份验证。

---

### 3.4 One source failure does not mean the work does not exist

例如：

```text
Crossref 没找到
≠
科研对象一定不存在
```

不同数据库、注册机构和全文来源需要被明确区分。

---

### 3.5 Temporary and permanent failures are different

例如：

```text
网络超时
429 Rate Limit（请求限流）
5xx Server Error（服务端错误）

→ 可能值得重试
```

而：

```text
非法 DOI
确定的 404
不支持的注册机构
无法解析的数据结构

→ 重试通常没有意义
```

---

### 3.6 External complexity should terminate at module boundaries

当前 Metadata（元数据）架构遵循：

```text
HTTP / JSON 复杂性
→ transport.py

Crossref 数据结构
→ crossref.py

DataCite 数据结构
→ datacite.py

注册机构识别与路由
→ resolver.py

临时错误恢复
→ retry.py

批量任务组织
→ batch.py
```

每一种复杂性尽量只存在一个地方。

---

### 3.7 Correctness before premature optimization

当前优先级：

```text
正确性
↓
鲁棒性
↓
可读性
↓
可维护性
↓
稳定性
↓
可扩展性
↓
性能优化
```

在真实性能瓶颈出现之前，不提前引入复杂异步架构、并发控制和缓存系统。

---

## 4. Current Capabilities

### DOI Core

当前支持：

```python
normalize_doi()
normalize_dois()
extract_dois()
looks_like_doi()
```

可以处理：

```text
标准 DOI

DOI:
doi:

https://doi.org/
http://doi.org/
https://dx.doi.org/
doi.org/

大小写混合
前后空格
URL 百分号编码
正文标点
括号 / 引号 / 方括号
中英文文本边界
复杂历史 DOI 后缀
批量标准化
稳定去重
自然语言 DOI 提取
```

示例：

```python
from aletheia_nexus.core.identifiers.doi import normalize_doi

doi = normalize_doi(
    "https://doi.org/10.1038/NPHYS1170"
)

print(doi)
```

输出：

```text
10.1038/nphys1170
```

---

## 5. Metadata Resolution

v0.3 建立了统一 Metadata Resolution（元数据解析）链路。

```text
Raw DOI / DOI URL
        ↓
DOI Normalization
DOI 标准化
        ↓
Registration Agency Detection
DOI 注册机构识别
        ↓
   ┌──────────────┐
   │              │
Crossref       DataCite
   │              │
   └──────┬───────┘
          ↓
    PaperMetadata
          ↓
Retry / Batch
```

当前正式支持：

```text
Crossref
DataCite
```

例如：

```text
10.1038/nphys1170
→ Crossref

10.5281/zenodo.31780
→ DataCite
```

对于已识别但尚未支持的 DOI Registration Agency（DOI 注册机构），系统会返回明确的：

```text
UNSUPPORTED_AGENCY
```

而不是错误地将其视为：

```text
NOT_FOUND
```

---

## 6. Metadata Architecture

v0.3.2 对 Metadata 层进行了稳定化重构。

当前内部结构：

```text
metadata/
│
├─ __init__.py
│
├─ exceptions.py
│
├─ transport.py
│
├─ crossref.py
│
├─ datacite.py
│
├─ resolver.py
│
├─ retry.py
│
└─ batch.py
```

数据流：

```text
Application
     ↓
Public Metadata API
     ↓
Resolver
     ↓
Registration Agency
     ↓
┌───────────────┐
│               │
Crossref     DataCite
│               │
└───────┬───────┘
        ↓
    Transport
        ↓
      HTTP
```

其中：

```text
transport.py
→ HTTP 请求
→ User-Agent
→ HTTP 状态语义
→ 网络异常
→ JSON 解码

crossref.py
→ Crossref schema → PaperMetadata

datacite.py
→ DataCite schema → PaperMetadata

resolver.py
→ DOI Registration Agency
→ Provider Routing

retry.py
→ Retry
→ Exponential Backoff

batch.py
→ 批量查询
→ 去重
→ 错误隔离
→ 稳定状态
```

---

## 7. Shared Transport Layer

v0.3.2 引入统一 Transport Layer（传输层）。

Provider 不再分别实现：

```text
HTTP 请求
Timeout
Connection Error
404
429
4xx
5xx
JSON Decode
```

这些行为统一由：

```text
transport.py
```

负责。

这样未来如果引入：

```text
httpx.Client
Connection Pooling（连接池）
统一超时配置
请求日志
更高级的 Retry-After 支持
```

只需要修改 Transport 层，而不需要重新修改 Crossref、DataCite 和 Resolver。

User-Agent（用户代理标识）也会自动读取当前安装版本：

```text
Aletheia-Nexus/0.3.2
```

而不再在多个模块中手工维护版本字符串。

---

## 8. Unified Metadata Model

不同数据源的数据结构差异很大。

例如：

```text
Crossref
→ author
→ container-title
→ published

DataCite
→ creators
→ relatedItems
→ dates
```

Aletheia Nexus 会将它们统一转换为：

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

因此上层代码不需要关心：

```text
数据来自 Crossref
还是 DataCite
```

只需要面对统一模型。

> 当前名称仍为 `PaperMetadata` 以保持 API 稳定。  
> DataCite 本身也可能描述 Presentation、Dataset、Documentation 等非传统论文科研对象，未来如有实际需求，可进一步演化为更通用的 Work Metadata 模型。

---

## 9. DataCite Publication Resolution

DataCite 的出版信息可能来自：

```text
relatedItems
```

或旧式 / 兼容字段：

```text
container
```

Aletheia Nexus 当前优先采用：

```text
relationType = IsPublishedIn
```

对应的 `relatedItems` 信息。

并将：

```text
journal
ISSN
volume
issue
firstPage
lastPage
```

作为一个完整 publication source（出版信息来源）解析。

原则：

```text
如果存在可用 IsPublishedIn
→ 整组采用 relatedItems

否则
→ fallback 到 container
```

不会把两个来源中的字段任意拼接。

例如不会产生：

```text
relatedItems.firstPage = 249
+
container.lastPage = 18
↓
249-18
```

这种跨来源污染。

---

## 10. Installation

要求：

```text
Python >= 3.11
```

建议使用 Virtual Environment（Python 虚拟环境）。

Windows PowerShell：

```powershell
python -m venv .venv
```

激活：

```powershell
.\.venv\Scripts\Activate.ps1
```

安装项目和开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

验证版本：

```powershell
python -c "import importlib.metadata as m; print(m.version('aletheia-nexus'))"
```

当前应输出：

```text
0.3.2
```

---

## 11. Basic Usage

### Single DOI

推荐从统一 Public API（公开接口）导入：

```python
from aletheia_nexus.acquire.metadata import get_metadata

paper = get_metadata(
    "10.1038/nphys1170"
)

print(paper.doi)
print(paper.title)
print(paper.authors)
print(paper.journal)
print(paper.year)
```

系统内部自动执行：

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

## 12. DOI Registration Agency

也可以单独查询 DOI 注册机构：

```python
from aletheia_nexus.acquire.metadata import (
    get_doi_agency,
)

agency = get_doi_agency(
    "10.1038/nphys1170"
)

print(agency)
```

当前可能得到：

```text
crossref
datacite
```

其他已识别但尚未实现的注册机构会抛出：

```python
UnsupportedAgencyError
```

---

## 13. Retry

对于网络和服务端临时错误，可以使用：

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

当前采用 Exponential Backoff（指数退避）。

例如：

```text
第 1 次失败
↓
等待 1 秒

第 2 次失败
↓
等待 2 秒

第 3 次请求
↓
成功 → 返回
失败 → 抛出最终异常
```

默认会重试：

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

这是因为：

```text
网络暂时不可用
429 限流
5xx 服务异常

→ 有可能自行恢复
```

而：

```text
DOI 不存在
请求本身有问题
返回数据结构损坏
注册机构尚未支持

→ 单纯重复请求通常没有意义
```

---

## 14. Batch Resolution

批量获取元数据：

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
输入逐条 DOI 标准化
↓
标准化后稳定去重
↓
注册机构自动识别
↓
数据源自动路由
↓
Retry
↓
逐条错误隔离
↓
稳定状态输出
```

其中一条 DOI 失败不会使整个批次终止。

可能结果：

```text
SUCCESS        10.1038/nphys1170
SUCCESS        10.5281/zenodo.31780
NOT_FOUND      10.9999/not-real-doi
INVALID_DOI    -
```

---

## 15. Metadata Status Model

Batch API（批处理接口）使用稳定状态：

| Status | 含义 |
|---|---|
| `SUCCESS` | 元数据解析成功 |
| `INVALID_DOI` | 输入无法标准化为合法 DOI |
| `NOT_FOUND` | DOI / 对应元数据未找到 |
| `UNSUPPORTED_AGENCY` | DOI 注册机构暂未支持 |
| `REQUEST_ERROR` | 普通 HTTP 4xx 请求错误 |
| `NETWORK_ERROR` | 网络连接或超时错误 |
| `RATE_LIMITED` | API 返回 HTTP 429 |
| `SERVICE_ERROR` | 服务端错误或异常 HTTP 状态 |
| `PARSE_ERROR` | 返回数据结构无法可靠解析 |

Batch 返回：

```python
MetadataLookupResult
```

其中包含：

```text
input_value
doi
status
metadata
error
```

因此系统既保留：

```text
原始输入
```

也保留：

```text
标准化 DOI
最终状态
解析结果
失败原因
```

---

## 16. Exception Model

Metadata 层使用统一异常体系：

```text
MetadataError
│
├─ MetadataNotFoundError
├─ MetadataNetworkError
├─ MetadataRequestError
├─ MetadataServiceError
├─ MetadataParseError
├─ RateLimitError
└─ UnsupportedAgencyError
```

上层可以精确捕获：

```python
from aletheia_nexus.acquire.metadata import (
    MetadataNetworkError,
)

try:
    ...
except MetadataNetworkError:
    ...
```

也可以统一处理：

```python
from aletheia_nexus.acquire.metadata import (
    MetadataError,
)

try:
    ...
except MetadataError:
    ...
```

---

## 17. HTTP Semantics

Transport Layer 当前约定：

```text
404
→ MetadataNotFoundError

429
→ RateLimitError

其他 4xx
→ MetadataRequestError

5xx
→ MetadataServiceError

Timeout / Connection Error
→ MetadataNetworkError

Invalid JSON
→ MetadataParseError
```

这套语义同时服务于：

```text
异常处理
Retry 决策
Batch 状态映射
未来日志与任务调度
```

---

## 18. Public Metadata API

推荐从：

```python
aletheia_nexus.acquire.metadata
```

统一导入。

当前公开 API：

```python
from aletheia_nexus.acquire.metadata import (
    DoiAgency,
    MetadataError,
    MetadataLookupResult,
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    MetadataStatus,
    PaperMetadata,
    RateLimitError,
    UnsupportedAgencyError,
    get_doi_agency,
    get_metadata,
    get_metadata_batch,
    get_metadata_with_retry,
)
```

上层模块不应依赖：

```text
crossref.py
datacite.py
transport.py
resolver.py
retry.py
batch.py
```

的内部实现细节。

这样未来内部可以继续优化，而不需要破坏上层代码。

---

## 19. Source Structure

当前主要源码结构：

```text
src/
└─ aletheia_nexus/
   │
   ├─ core/
   │  │
   │  ├─ models.py
   │  │  └─ PaperMetadata
   │  │
   │  └─ identifiers/
   │     └─ doi.py
   │
   └─ acquire/
      │
      └─ metadata/
         ├─ __init__.py
         ├─ exceptions.py
         ├─ transport.py
         ├─ crossref.py
         ├─ datacite.py
         ├─ resolver.py
         ├─ retry.py
         └─ batch.py
```

测试结构：

```text
tests/
│
├─ core/
│  └─ identifiers/
│
└─ acquire/
   └─ metadata/
      ├─ test_transport.py
      ├─ test_crossref.py
      ├─ test_datacite.py
      ├─ test_resolver.py
      ├─ test_retry.py
      ├─ test_batch.py
      └─ test_public_api.py
```

人工真实网络验收：

```text
scripts/
└─ manual_metadata_acceptance.py
```

持续集成：

```text
.github/
└─ workflows/
   └─ tests.yml
```

---

## 20. Testing

项目使用：

```text
pytest
```

运行全部自动测试：

```powershell
python -m pytest -q
```

自动测试主要使用 mock / monkeypatch（模拟 / 运行时替换）隔离真实网络，因此不会因为 Crossref、DataCite 或本地网络暂时异常而随机失败。

当前测试覆盖核心包括：

```text
DOI normalization
DOI extraction
DOI realistic boundary cases
DOI deduplication

Crossref schema parsing
Crossref malformed records

DataCite schema parsing
DataCite relatedItems
DataCite container fallback
publication source consistency

DOI agency detection
provider routing

shared transport
HTTP error semantics
JSON errors
network errors

retry behavior
exponential backoff

batch isolation
batch deduplication
stable statuses

public API
```

---

## 21. Code Quality

开发环境使用：

```text
Ruff
```

进行 Python Static Analysis（静态代码检查）和自动格式化。

自动修复可安全处理的问题：

```powershell
ruff check . --fix
```

格式化：

```powershell
ruff format .
```

检查：

```powershell
ruff check .
```

检查格式：

```powershell
ruff format --check .
```

源码语法检查：

```powershell
python -m compileall -q src
```

---

## 22. Continuous Integration

项目通过 GitHub Actions 进行 CI（持续集成）。

当前自动测试矩阵：

```text
Python 3.11
Python 3.14
```

每次：

```text
push
pull request
manual workflow dispatch
```

都会执行：

```text
Checkout
↓
Set up Python
↓
Install project
↓
Ruff formatting check
↓
Ruff static checks
↓
Python compile check
↓
pytest
```

只有这些步骤全部通过，当前代码才被认为处于稳定状态。

---

## 23. Manual Real-network Acceptance Test

除了 mock 自动测试，还提供真实网络验收：

```powershell
python scripts\manual_metadata_acceptance.py
```

它会真实访问：

```text
Crossref
DataCite
```

并验证：

```text
真实 Crossref DOI

真实 DataCite DOI

DOI 标准化

标准化后去重

语法有效但不存在的 DOI

非法 DOI

非字符串输入

稳定状态分类
```

成功时：

```text
FINAL RESULT: PASS
```

并返回：

```text
exit code 0
```

失败时：

```text
FINAL RESULT: FAIL
```

并返回：

```text
exit code 1
```

真实联网验收不会默认作为普通 CI 的硬依赖，因为外部 API 和网络本身可能临时不可用。

---

## 24. Development Verification

一次完整的本地验证建议执行：

```powershell
ruff check . --fix
ruff format .
ruff check .
ruff format --check .
python -m compileall -q src
python -m pytest -q
python scripts\manual_metadata_acceptance.py
```

然后检查：

```powershell
git status
git diff --stat
```

确认无误后再提交。

---

## 25. What v0.3.2 Does Not Do

当前版本解决的是：

```text
科研对象 DOI
↓
可靠身份标准化
↓
注册机构识别
↓
统一元数据
```

它暂时不负责：

```text
开放获取状态发现
全文候选链接发现
出版社全文定位
机构订阅权限
CARSI / SSO
浏览器登录
PDF 下载
PDF 完整性验证
PDF 身份匹配
正文结构化解析
Zotero 自动入库
SQLite 文献状态数据库
全文知识抽取
Agent 自动研究
```

这些属于后续阶段。

---

## 26. Roadmap

### v0.1 — Basic DOI ✅

```text
基础 DOI 标准化
基础 doi.org URL 支持
```

---

### v0.2 — DOI Core ✅

```text
normalize_doi
normalize_dois
extract_dois
looks_like_doi

现实边界测试
批量标准化
稳定去重
复杂 DOI 支持
```

---

### v0.3 — Metadata Resolution ✅

```text
PaperMetadata
Crossref
DataCite
DOI Registration Agency
Retry
Batch
Stable Error Model
```

---

### v0.3.1 — Reliability Hardening ✅

```text
更严格的外部数据验证
更明确的错误语义
Retry 参数安全检查
DataCite 解析增强
Batch 稳定性增强
```

---

### v0.3.2 — Metadata Stabilization ✅

```text
Shared Transport Layer
统一 HTTP / JSON 处理

Dynamic User-Agent
动态版本 User-Agent

DataCite publication source consistency
DataCite 出版来源一致性

Ruff
自动格式化与静态检查

GitHub Actions
Python 3.11 / 3.14 CI

Manual real-network acceptance
真实联网验收
```

至此 Metadata 层进入稳定阶段。

---

### v0.4 — Full-text Candidate Discovery 🚧

下一阶段目标：

```text
PaperMetadata
↓
多个合法全文来源
↓
标准化 Candidate
↓
排序
↓
交给 Acquisition
```

计划研究的数据源包括：

```text
Unpaywall
OpenAlex
Semantic Scholar
Europe PMC
Crossref links
DataCite links
Publisher landing pages
Publisher APIs / TDM endpoints
```

核心原则：

```text
Discovery
只负责：

“哪里可能有全文？”

不负责：

“最终是否成功下载？”
```

未来可能形成：

```text
FullTextCandidate
├─ source
├─ url
├─ access_type
├─ version
├─ confidence
└─ provenance
```

---

### v0.5 — Acquisition + PDF Validation

目标：

```text
Candidate
↓
Acquisition Backend
↓
Download
↓
File Validation
↓
Identity Validation
↓
Canonical Storage
```

计划逐步支持：

```text
Direct HTTP

Official Publisher APIs

Institutional Browser Access

Playwright Browser Automation

Human-in-the-loop SSO / CAPTCHA

PDF signature validation

PDF parseability

Page count validation

DOI / title / author identity matching

SHA-256

.part temporary files

atomic rename

conflict preservation
```

成功定义将不再是：

```text
HTTP 200
```

而是：

```text
文件成功获取
+
文件格式正确
+
可以解析
+
目标身份匹配
```

---

## 27. Future Direction

随着 Acquire 层成熟，Aletheia Nexus 将继续向：

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

推进。

长期目标不是单个工具，而是一套可以被：

```text
人
Python
Workflow
Agent
科研自动化系统
```

共同调用的科研知识基础设施。

最终希望实现：

```text
文献检索
↓
可靠获取
↓
结构化解析
↓
证据追踪
↓
知识组织
↓
Agent 推理
↓
实验设计与科研工作流
```

---

## 28. Project Philosophy

Aletheia Nexus 当前最重要的工程原则可以概括为：

> **Correctness before automation.**  
> 自动化之前先保证正确性。

> **Identity before acquisition.**  
> 获取之前先确认身份。

> **Explicit failure is better than silent corruption.**  
> 明确失败优于悄悄产生错误数据。

> **External complexity should stop at clear module boundaries.**  
> 外部复杂性应终止在清晰的模块边界。

> **Every layer should have one primary responsibility.**  
> 每一层只承担一种主要复杂性。

> **Build for extension, but abstract only when real duplication appears.**  
> 为扩展留下空间，但只在真实重复出现时进行抽象。

---

## 29. Version

Current release:

```text
Aletheia Nexus
v0.3.2
Metadata Stabilization
```

Current development focus:

```text
v0.4
Full-text Candidate Discovery
```