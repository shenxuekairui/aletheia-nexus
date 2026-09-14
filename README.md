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

当前稳定版本：

```text
Aletheia Nexus v0.3.2
Metadata Stabilization
```

当前开发分支：

```text
v0.4.1
Discovery Reliability Hardening
全文发现可靠性强化
```

v0.4.1 当前完成：

```text
OpenAlex / Unpaywall Discovery
+
Candidate URL Normalization
+
Provider Failure Isolation
+
Retry with Exponential Backoff
+
Structured Provider Status
+
Batch Discovery
+
Partial Success Semantics
+
Automated Quality Checks
+
Manual Real-network Acceptance Script
```

下一阶段仍然属于 v0.4 Discovery（发现层）的覆盖扩展与真实数据验收；真正的 PDF 下载、机构认证和文件验证继续留在 v0.5 Acquisition + Validation（获取与验证层）。

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
├─ Discovery         🚧 v0.4.1
└─ Acquisition       ⏳ v0.5
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
OpenAlex 没找到
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
普通 4xx 请求错误
无法解析的数据结构

→ 重试通常没有意义
```

---

### 3.6 External complexity should terminate at module boundaries

当前 Metadata（元数据）与 Discovery（发现）都遵循同一工程原则：

```text
HTTP / JSON 复杂性
→ transport.py

外部 Provider 数据结构
→ provider adapter

临时错误恢复
→ retry.py

批量任务组织
→ batch.py
```

但目前 Metadata 和 Discovery 仍保留各自的 transport.py。

原因是：

```text
Metadata 404
和
Discovery 404
```

并不天然具有相同业务语义。

在多个模块真正出现稳定、重复的传输需求之前，不提前抽象共享 Transport Layer（共享传输层）。

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

v0.4.1 的 Batch Discovery（批量发现）刻意保持顺序执行。

在真实性能瓶颈出现之前，不提前引入异步架构、并发控制、缓存系统和复杂限流调度。

---

## 4. DOI Core

当前支持：

```python
normalize_doi()
normalize_dois()
extract_dois()
looks_like_doi()
```

可以处理标准 DOI、DOI URL、大小写、前后空格、百分号编码、正文标点、复杂历史 DOI 后缀、批量标准化和稳定去重。

---

## 5. Metadata Resolution

v0.3 建立了统一 Metadata Resolution（元数据解析）链路：

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

当前正式支持 Crossref 与 DataCite。

---

## 6. Full-text Discovery

v0.4 建立 Full-text Candidate Discovery（全文候选来源发现）层。

当前数据流：

```text
DOI
↓
DOI Normalization
DOI 标准化
↓
Discovery Service
发现服务
↓
┌───────────────┐
│               │
OpenAlex     Unpaywall
│               │
└───────┬───────┘
        ↓
Candidate URL Validation
候选链接验证
        ↓
FullTextCandidate
全文候选
        ↓
Deduplication + Ranking
去重 + 排序
        ↓
DiscoveryResult
```

Discovery 只回答：

```text
“哪里可能有全文？”
```

不回答：

```text
“最终是否成功下载并验证了正确文件？”
```

后者属于 v0.5。

---

## 7. Discovery Reliability Hardening

v0.4.1 重点强化可靠性，而不是增加 Provider 数量。

### Retry（重试）

以下错误会采用 Exponential Backoff（指数退避）重试：

```text
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
```

以下错误不会重复请求：

```text
NOT_FOUND
REQUEST_ERROR
PARSE_ERROR
CONFIGURATION_ERROR
```

每个 Provider 独立重试，并在结果中记录：

```text
attempts
```

因此一个 Provider 暂时失败不会阻断其他 Provider。

### Provider Status（数据源状态）

当前 Provider 级状态：

```text
SUCCESS
NO_CANDIDATES
NOT_FOUND
SKIPPED
CONFIGURATION_ERROR
REQUEST_ERROR
NETWORK_ERROR
RATE_LIMITED
SERVICE_ERROR
PARSE_ERROR
ERROR
```

### Batch Discovery（批量发现）

公开接口：

```python
from aletheia_nexus.acquire.discovery import discover_full_text_batch
```

示例：

```python
results = discover_full_text_batch(
    [
        "10.1038/nphys1170",
        "https://doi.org/10.1038/NPHYS1170",
        "not a doi",
    ],
    unpaywall_email="person@example.org",
)
```

批量层执行：

```text
输入逐条标准化
↓
按标准化 DOI 稳定去重
↓
逐篇 Discovery
↓
Provider 独立重试与错误隔离
↓
候选去重与排序
↓
稳定 Batch Status
```

整体状态：

```text
SUCCESS
PARTIAL_SUCCESS
NO_CANDIDATES
NOT_FOUND
INVALID_DOI
ERROR
```

其中：

```text
PARTIAL_SUCCESS
```

表示至少已经取得有效候选，但一个或多个 Provider 发生真实失败。

这与：

```text
SUCCESS + 某 Provider 正常 NO_CANDIDATES
```

明确区分。

---

## 8. Candidate URL Safety

所有外部候选 URL 在进入 `FullTextCandidate` 前会统一进行标准化和验证。

当前处理包括：

```text
去除前后空格
Markdown 链接解包
安全包装字符清理
仅允许 HTTP / HTTPS
必须存在主机名
拒绝嵌入账号密码
拒绝空白字符污染
去除 URL fragment
统一 scheme / host 大小写
```

例如：

```text
[https://doi.org/10.1038/nphys1170](https://doi.org/10.1038/nphys1170)
```

会规范为：

```text
https://doi.org/10.1038/nphys1170
```

---

## 9. Public Discovery API

推荐统一从：

```python
aletheia_nexus.acquire.discovery
```

导入。

主要 API：

```python
from aletheia_nexus.acquire.discovery import (
    DiscoveryLookupResult,
    DiscoveryResult,
    DiscoveryStatus,
    FullTextCandidate,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
    discover_full_text,
    discover_full_text_batch,
)
```

上层代码不应依赖 OpenAlex、Unpaywall、Transport、Retry、Batch 的内部实现细节。

---

## 10. Manual Real-network Acceptance

自动测试使用 mock / monkeypatch（模拟 / 运行时替换）保证确定性。

真实 API 行为使用独立脚本验证：

```powershell
python scripts/manual_discovery_acceptance.py `
    --unpaywall-email "person@example.org" `
    10.1038/nphys1170
```

也可以通过环境变量提供：

```text
UNPAYWALL_EMAIL
OPENALEX_API_KEY
```

脚本会打印：

```text
Batch Status
Provider Status
Provider Attempts
Candidate URL
URL Type
Access Type
Version
Host Type
Provenance
```

人工真实网络验收不纳入 CI，以避免外部服务暂时异常造成随机测试失败。

---

## 11. Source Structure

当前 Discovery 结构：

```text
src/aletheia_nexus/acquire/discovery/
│
├─ __init__.py
├─ models.py
├─ exceptions.py
├─ urls.py
├─ transport.py
├─ ranking.py
├─ retry.py
├─ openalex.py
├─ unpaywall.py
├─ service.py
└─ batch.py
```

对应职责：

```text
models.py
→ 稳定领域对象与状态

urls.py
→ Candidate URL 标准化与验证

transport.py
→ HTTP / JSON 与网络错误语义

openalex.py / unpaywall.py
→ Provider Adapter（数据源适配器）

retry.py
→ 临时错误重试与指数退避

service.py
→ 多 Provider 协调、失败隔离、候选聚合

ranking.py
→ 去重、来源合并、候选排序

batch.py
→ 批量输入、稳定去重、整体状态
```

---

## 12. Testing

运行完整自动测试：

```powershell
python -m pytest -q
```

CI 当前同时验证：

```text
Python 3.11
Python 3.14
```

质量检查包括：

```text
ruff format --check .
ruff check .
python -m compileall -q src
python -m pytest -q
```

v0.4.1 测试重点包括：

```text
Candidate URL normalization
Provider parsing
Provider failure isolation
Retryable vs non-retryable failures
Exponential backoff
Attempt counting
Batch DOI normalization
Batch stable deduplication
Batch mixed input isolation
PARTIAL_SUCCESS semantics
Public API stability
```

---

## 13. Installation

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

当前正式发布版本仍然是：

```text
0.3.2
```

v0.4.1 尚处于开发分支，因此暂不修改正式包版本号。

---

## 14. Roadmap

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

v0.3.1
Reliability Hardening
✅

v0.3.2
Metadata Stabilization
✅

v0.4.0
Discovery Core
✅ development branch

v0.4.1
Discovery Reliability Hardening
✅ development branch

v0.4.x
Coverage Expansion + Real-corpus Acceptance
🚧

v0.5
Acquisition + PDF Validation
⏳
```

下一步不默认“继续加 API”。

应先用真实文献集回答：

```text
OpenAlex + Unpaywall 的实际覆盖率是多少？

缺失主要发生在哪些类型？

缺的是 OA 仓储、出版社入口、预印本，还是领域数据库？

新增 Provider 能解决多少真实缺口？
```

只有确认真实重复缺口后，再决定是否增加 Crossref Links、DataCite Links、Europe PMC、arXiv、CORE 或出版社专用适配器。

---

## License

当前项目处于早期开发阶段。
