# Aletheia Nexus

[English README](README.en.md) · [使用说明](docs/USER_MANUAL.md) · [贡献指南](CONTRIBUTING.md) · [安全报告](SECURITY.md) · [版本记录](docs/RELEASE_HISTORY.md)

> **把科学文献转换成经过验证、可追溯来源、可直接供 AI 使用的数据。**

Aletheia Nexus（AN）是一个 **local-first（本地优先）** 的科研知识基础设施项目。它从科学文献这一最基础的科研对象出发，把“找到一篇论文”拆成可以验证和积累的工程链：

```text
DOI / 科研对象
      ↓
发现与合法获取
      ↓
VERIFIED 主论文 + provenance（来源记录）
      ↓
source-linked canonical document（可追溯规范文档）
      ↓
Markdown / JSONL / structure-aware chunks
      ↓
LLM / RAG / Workflow / Agent / Knowledge
```

AN 不把“浏览器里打开了一个 PDF”当作成功，也不把“PDF 能提取出文字”当作可信数据。它关心的是：

- **这是不是目标论文的主文档？**
- **这些字节从哪里来，是否发生过变化？**
- **解析后的文本、章节、引用、图表证据能否回到原始页码和位置？**
- **失败和不确定性是否被明确记录？**
- **这些结果能否脱离某个特定模型、云 API 或向量数据库长期保存和复用？**

这也是 AN 的核心路线：先把底层证据和数据契约做可靠，再向 Knowledge、Workflow、Agent 和更高层科研智能继续构建。

---

## v0.7：从可信论文到 AI-ready 科学数据

v0.6 解决的是：

> **“我拿到的究竟是不是我要的那篇论文？”**

v0.7 进一步解决：

> **“机器产生的结构化信息，能不能稳定回到原始科学证据？”**

当前 v0.7 链路已经形成：

```text
VERIFIED PDF
    ↓
严格输入门：DOI / role / schema / SHA-256 / page count
    ↓
native-first extraction + optional OCR
    ↓
canonical PageGeometry
    ↓
sections / blocks / references / figures / tables
    ↓
page / bbox / source anchors
    ↓
parsed-document/v2
    ↓
Markdown / JSONL / structure-aware chunks
```

这里的 **AI-ready data（AI 可用数据）** 不是“已经让模型理解了论文”。

它指一种长期稳定、模型无关的科学文档工件：具有明确身份、来源、结构、位置、质量状态和不确定性，可以直接交给 LLM、RAG、Agent 或后续知识抽取系统，而不必再次从 PDF 开始猜。

---

## 当前能力

| 层 | 当前能力 | 状态 |
| --- | --- | --- |
| **Identity / Metadata** | DOI 标准化；Crossref / DataCite 元数据解析 | Implemented |
| **Discovery** | 汇集元数据、OpenAlex、Unpaywall、PMC 等全文线索 | Implemented |
| **Acquisition** | 有界公开 HTTP 获取、官方接口、持久浏览器会话、批量与续跑 | Implemented / Experimental |
| **Verification** | PDF 结构、DOI/标题身份、主文档/补充材料角色验证；SHA-256 与来源记录 | Implemented |
| **Parse** | 原生文本优先；章节、文本块、引用、图表证据、表格单元、页码/bbox 来源锚点 | Implemented |
| **OCR** | 可选 Poppler + Tesseract 真实链路；方向校正、deskew、资源预算、显式降级 | Implemented |
| **Search** | 在 parsed artifact 上检索并可重新验证本地来源 | Implemented |
| **AI Export** | 确定性 Markdown、JSONL、结构感知 chunks；每个 chunk 独立可追溯 | Implemented |
| **Scientific semantics** | 催化剂、实验条件、measurement、claim、relation 等科学语义抽取 | Planned |
| **Knowledge / Workflow / Agent** | 科研记忆、知识组织、工作流、Agent 调用 | Planned |

### Acquire 的可信边界

只有通过完整验证的目标主文档才会成为：

```text
VERIFIED
```

AN 不提供订阅、不绕过付费墙、不代答 CAPTCHA。需要机构登录、MFA 或验证码时，由用户在自己的可见浏览器中完成；程序只在合法访问条件下继续。

常见非成功状态包括：

- `INTERACTION_REQUIRED`：需要用户完成页面交互；
- `ENTITLEMENT_REQUIRED`：当前合法会话没有正文权限或页面要求购买；
- `EXHAUSTED`：当前路径与预算已用尽，但没有得到可验证主文档。

这些状态都是科研工作流中的有效信息，而不是需要被静默隐藏的“失败”。

### Parse 的可信边界

v0.7 parser 只接受仍然满足以下条件的输入：

```text
VERIFIED
+
DOI match
+
main-document role
+
PDF SHA-256 match
+
acquisition sidecar SHA-256 match
+
readable PDF
+
page-count consistency
```

解析得到的 `aletheia-nexus/parsed-document/v2` 是新的独立工件，不覆盖原始 PDF 和 acquisition record。

它记录：

- stable source / parsed artifact identity；
- sections、blocks、references；
- figure / table 的**观测证据**；
- page + normalized bbox；
- extraction method、confidence、engine agreement；
- warnings、errors、PARTIAL / PARSED 等质量状态；
- parser/backend configuration 与关键 runtime provenance。

**`PARSED` 不等于“论文内容 scientifically true（科学上正确）”。**

图表被识别到 caption、region 或 positioned cells，也不等于系统已经理解其科学含义。v0.7 明确把“文档证据表示”和“科学语义解释”分开。

---

## AI-ready 导出

Canonical parsed artifact 是 Source of Truth（真源）；AI 导出只是确定性的派生视图。

### Markdown

```bash
aletheia-nexus export PAPER.parsed.json \
  --format markdown \
  --output PAPER.ai.md
```

适合：

- LLM context；
- 人工审阅；
- prompt attachment；
- 轻量文档处理。

### JSONL

```bash
aletheia-nexus export PAPER.parsed.json \
  --format jsonl \
  --output PAPER.ai.jsonl
```

适合：

- 数据管道；
- 流式读取；
- 后续知识抽取；
- 模型训练/推理前处理。

### Structure-aware chunks（结构感知分块）

```bash
aletheia-nexus export PAPER.parsed.json \
  --format chunks \
  --output PAPER.chunks.json
```

chunk 优先保留 section、heading、caption、reference、equation 和 table object 等结构边界，而不是简单每 N 个 token 切一刀。

每个 chunk 独立保留：

```text
source_artifact_id
parsed_artifact_id
block_ids
anchor_ids
pages
page/bbox evidence
```

因此可以形成：

```text
chunk
  ↓
block
  ↓
anchor
  ↓
page / bbox
  ↓
source artifact
  ↓
原始 PDF
```

AN 核心不绑定 OpenAI、Claude、Gemini、embedding 模型或 vector database。它只提供稳定的数据边界，下游消费者可以自由选择模型和基础设施。

---

## 快速开始

需要 Python 3.11 或更高版本。

### 安装最新已发布版本

```bash
python -m pip install -U aletheia-nexus
aletheia-nexus --version
aletheia-nexus doctor
```

以 [PyPI 项目页](https://pypi.org/project/aletheia-nexus/)实际可见版本为准。

### 获取一篇公开可访问论文

```bash
aletheia-nexus acquire 10.1371/journal.pone.0310216 \
  --public-only \
  --output-dir downloads/first-paper
```

公开路径正常工作并不保证每篇论文都能获取；没有可验证正文时，返回 `EXHAUSTED` 是合法结果。

### 浏览器与机构访问

```bash
python -m pip install "aletheia-nexus[browser]"
python -m playwright install chromium

aletheia-nexus acquire papers.json \
  --output-dir downloads/papers \
  --fail-on-unverified
```

浏览器能力用于复用用户**已有的合法访问条件**，不是绕过访问控制。

### 解析 VERIFIED 论文

```bash
aletheia-nexus parse downloads/paper.pdf \
  --doi 10.1234/example
```

默认写出：

```text
paper.parsed.json
```

搜索并验证来源：

```bash
aletheia-nexus search PAPER.parsed.json QUERY --verify-sources
```

### 启用真实 OCR

OCR 需要安装 Poppler 与 Tesseract：

```bash
aletheia-nexus parse downloads/paper.pdf \
  --doi 10.1234/example \
  --ocr
```

Native text（原生文本）仍是权威来源；OCR 只作为补充。OCR 超时、资源不足、依赖缺失或 backend 失败会显式降级，不会把已经可靠取得的 native evidence 一起丢掉。

详细参数见 [中文使用说明书](docs/USER_MANUAL.md)。

---

## 为什么不是“PDF 转 Markdown”就够了？

科研场景里，真正昂贵的错误通常不是“少一个换行符”，而是：

- 下载到了 Supporting Information，却被当成正文；
- PDF 身份错了，但下游 Agent 不知道；
- OCR 坐标和原生文本坐标不是一个体系；
- 文档移动到 NAS 或另一台电脑后，身份依赖绝对路径而失效；
- 一个 figure 只有 caption，却被上层系统误解成“图已完整解析”；
- 一次 parser 更新静默覆盖了旧结果，无法复核历史分析；
- RAG 找到一个 chunk，却无法回到它对应的原始证据。

AN 把这些问题视为**科研数据基础设施问题**，而不是 prompt engineering 问题。

因此 v0.7 的重点不是增加更多“聪明”的模型，而是建立：

```text
Identity
→ Integrity
→ Transformation
→ Location
→ Uncertainty
→ Consumption
```

这条可信链。

---

## 验证与证据

AN 不把一个单一“准确率”作为全部质量证明，而是使用不同层次的验证证据。

### 自动化与 CI

v0.7 发布候选 PR 的最终验证包括：

- Python 3.11 deterministic suite：**886 passed / 8 skipped**；
- Windows/Python 3.11：**886 passed / 8 skipped**；
- Python 3.12 / 3.13 / 3.14 compatibility jobs：全部通过；
- Linux real Chromium：**7 passed**；
- Windows real Chromium：**7 passed**；
- real Poppler + Tesseract raster-only OCR smoke：**1 passed**；
- wheel / sdist build、`twine check`、clean-wheel install、`pip check`、CLI `doctor`：全部通过；
- frozen parser evaluator 会生成机器可读 `parser-evaluation.json` 并由 CI 保存。

### Frozen synthetic gold

自编、可再分发的固定夹具用于精确回归：

- 4/4 gate decisions；
- 32/32 anchored blocks；
- 6/6 selected anchors；
- 10/10 sections；
- 18/18 structural assertions；
- 886/886 gold characters；
- 0 deletion / insertion / substitution。

Synthetic fixtures 不是为了证明“真实世界 100% 正确”，而是为了把重要边界条件锁成确定性回归测试。

### Real-layout evidence

公开证据还包括 3 篇 hash-frozen Open Access（开放获取）真实论文的版式 qualification；PDF 按需从官方来源获取，不提交到仓库。

另有私有真实版式压力集累计 **38 篇 / 655 页**，用于 broader layout/runtime stress testing（更广泛版式与运行压力验证）。这些结果证明的是解析完成、来源锚点与聚合诊断，**不是人工标注的科学语义准确率，也不是“所有视觉信息零损失”声明。**

### 真实使用反馈

项目已经收到独立用户的首次本地部署与实际批量使用反馈，包括 1/1、3/3、6/6 的 `VERIFIED` 批次结果。该反馈证明了实际本地工作流可以运行，但由于对方没有完整记录 clean PyPI 安装、OS/Python 和三分钟首次使用时间，**严格的 three-minute onboarding（3 分钟首次上手）目标仍未被独立验证**。

完整证据口径见 [版本与验收记录](docs/RELEASE_HISTORY.md)。

---

## 项目结构

```text
src/aletheia_nexus/
├── core/identifiers/          # DOI 等科研对象标识
├── acquire/
│   ├── metadata/              # 元数据
│   ├── discovery/             # 全文候选发现
│   ├── fulltext/              # 获取、身份与主文档验证
│   └── access/                # API / browser / human handoff
└── content/
    ├── gate.py                # VERIFIED 输入门
    ├── geometry.py            # canonical PageGeometry
    ├── backends/              # native / OCR / specialist backends
    ├── parser.py              # 结构解析
    ├── schema.py              # parsed-document/v2 contract
    ├── artifact.py            # 可移植工件访问与来源复核
    ├── export.py              # Markdown / JSONL / chunks
    └── evaluation.py          # parser qualification

benchmarks/                    # 冻结基准与来源说明
scripts/                       # RC / qualification / compatibility tools
tests/                         # deterministic + browser/OCR integration tests
```

---

## 工程原则

AN 的长期开发遵循几个简单原则：

1. **正确性优先于自动化。**
2. **明确失败优于静默产生错误结果。**
3. **稳定能力做成工具和 Skill，确定流程做成 Workflow，开放决策再交给 Agent。**
4. **原始证据和 canonical artifact 不应被派生结果反向覆盖。**
5. **路径只是位置，hash 和 provenance 才决定科研工件身份。**
6. **自动化必须保留来源、状态、处理过程和不确定性。**
7. **Local-first：核心科研资产应可保存、迁移、导出和恢复。**
8. **只抽象已经真实出现的重复，不为想象中的未来提前增加复杂度。**
9. **Human-in-the-loop（人在回路中）是访问控制和科学判断的正常边界。**
10. **一个版本达到足够稳定后，应停止无收益重构，进入下一层。**

---

## 路线图

```text
Identity / Metadata
        ↓
Discovery
        ↓
Acquisition
        ↓
Verification
        ↓
Canonical Document          ← v0.7
        ↓
AI Consumption Views        ← v0.7
        ↓
Scientific Semantic Layer   ← next
        ↓
Knowledge
        ↓
Workflow / Skill
        ↓
Agent
        ↓
Lab Scientific Intelligence
```

下一层重点不是继续堆 PDF parser，而是开始建立 Scientific Semantic Layer（科学语义层）：

```text
entity
method
condition
measurement
claim
relation
```

例如在电催化论文中，未来可以进一步结构化：

```text
Catalyst
Reaction
Substrate
Electrolyte
Potential
Current density
FE
Yield
Selectivity
Temperature
pH
Mechanism
Evidence
```

这些仍属于后续版本，不是 v0.7 已交付能力。

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [使用说明书](docs/USER_MANUAL.md) | 安装、获取、浏览器、解析、OCR、导出、故障处理 |
| [v0.7 Parsing Contract](docs/V07_PARSING_CONTRACT.md) | 输入门、schema、artifact、质量边界 |
| [v0.7 Architecture](docs/V07_ARCHITECTURE.md) | backend、geometry、parser、证据链 |
| [v0.7 OCR](docs/V07_OCR.md) | native-first OCR、坐标、资源预算、运行时依赖 |
| [v0.7.0 发布说明](docs/RELEASE_NOTES_v0.7.0.md) | 本版本功能、验证证据与明确边界 |
| [版本与验收记录](docs/RELEASE_HISTORY.md) | 历史测试、真实网络与资格证据口径 |
| [CI 架构](docs/CI_ARCHITECTURE.md) | 自动化测试与发布门 |
| [Benchmark 说明](benchmarks/README.md) | 固定语料、公开/私有证据边界 |

---

## 参与项目

如果你愿意试用 AN，欢迎：

- 报告一个可复现的错误；
- 提供合法可公开的测试夹具；
- 补充新的论文版式；
- 测试新的机构/出版社合法访问路径；
- 讨论科学语义层、Knowledge、Workflow 或 Agent 的数据契约。

已经有独立用户提交了真实本地部署反馈；如果你是第一次使用，也欢迎在 [Issue #3](https://github.com/shenxuekairui/aletheia-nexus/issues/3) 继续记录安装体验和问题。

请不要在公开 issue 中提交论文 PDF、Cookie、token、机构登录截图、signed URL 或未脱敏的本地路径。安全问题请使用仓库的 private vulnerability reporting（私密漏洞报告）。

---

## License

项目代码采用 [Apache License 2.0](LICENSE)。

第三方论文、补充材料和其他科研内容仍受各自版权、许可证和访问条件约束。AN 的开源许可不会自动赋予这些内容的再分发权利。

---

*Aletheia* 意为“真理”，*Nexus* 意为“连接”。

AN 想做的不是一个更聪明的下载脚本，而是一层可以被长期信任的科研数据与知识基础设施：**让每一个结论，都有机会回到它真正来自的证据。**
