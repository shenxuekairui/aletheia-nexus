# Aletheia Nexus v0.7.0 — 从可信论文到可追溯的 AI-ready 科学数据

本文件记录已合入上游并打标签的 v0.7.0。后续出版社获取修复及其独立验证记录见[版本与验收记录](RELEASE_HISTORY.md)，不回填为该标签的测试结果。

v0.7.0 是 Aletheia Nexus 从“论文可信获取”走向“科研数据基础设施”的第二个关键版本。

如果说 v0.6 主要回答：

> **我拿到的究竟是不是我要的那篇论文？**

那么 v0.7 开始回答：

> **机器产生的结构化信息，能不能稳定回到原始科学证据，并成为后续 AI 可以直接使用的长期数据资产？**

本版本建立了完整的：

```text
VERIFIED PDF
        ↓
source-linked canonical scientific document
        ↓
model-agnostic AI-ready data
```

链路。

它不加入 embedding（向量嵌入）、vector database（向量数据库）、LLM summary（大模型摘要）、科学 claim 抽取或 Agent；这些能力被刻意留在稳定数据边界之后。

---

## 一、本版本最重要的变化

### 1. 从 VERIFIED PDF 建立 Canonical Scientific Document

v0.7 新增严格的 Parse trust boundary（解析信任边界）。

只有仍然满足以下条件的论文才能进入解析：

```text
VERIFIED
+
目标 DOI 一致
+
主文档角色正确
+
PDF SHA-256 一致
+
acquisition sidecar SHA-256 一致
+
PDF 可读
+
page count 一致
```

解析前和解析后都会重新检查关键来源文件，避免文件在处理中被替换却仍然得到“成功”结果。

最终生成独立的：

```text
aletheia-nexus/parsed-document/v2
```

原始 PDF、获取记录和解析工件彼此分离，派生结果不会成为新的 Source of Truth（真源）。

---

### 2. 建立统一 PageGeometry（页面几何）

Native text、PDF image、OCR 和未来 specialist backend 不再各自定义坐标。

v0.7 使用统一 canonical coordinate system（规范坐标系），处理：

- MediaBox / CropBox；
- 非零页面原点；
- PDF `/Rotate`；
- OCR orientation；
- deskew；
- raster pixel → PDF coordinate；
- clipping；
- normalized bbox。

最终 page/bbox 使用稳定、规范化的页面坐标表达。

目标不是宣称像素级完美，而是保证：

> **坐标可以带不确定性，但不能生活在错误的坐标系里。**

---

### 3. Native-first OCR 正式成为可执行能力

v0.7 提供真实：

```text
PDF
↓
Poppler / pdftoppm
↓
Tesseract
↓
TSV coordinates
↓
canonical geometry
↓
parsed-document/v2
```

链路。

OCR 采用 native-first 原则：

```text
native extraction
      ↓
已有可靠证据
      ↓
是否需要 OCR？
      ├── 否 → 保留 native
      └── 是 → OCR 补充
                  ↓
                failure
                  ↓
             KEEP NATIVE
             + explicit warning
```

OCR 或其他 optional backend 失败不会再抹掉已经可靠取得的 native evidence。

本版本还加入：

- OCR orientation correction；
- deskew inverse mapping；
- raster resource budget；
- PDF `/UserUnit` 预估；
- 渲染后真实 pixel count 二次检查；
- machine-readable failure reason；
- extraction confidence 与 engine agreement 分离。

Tesseract、Poppler、Pillow、pypdf 等关键运行环境以及实际 OCR 配置会进入 backend execution provenance（执行来源记录），但不会写入本机绝对 executable 路径。

---

### 4. Parsed artifact 变成可迁移的长期数据资产

v0.7 将：

```text
Identity（身份）
```

与：

```text
Locator（本地位置）
```

分开。

工件身份不再依赖：

```text
C:\Users\...
F:\papers\...
/home/...
```

而由 DOI、SHA-256、schema、execution fingerprint 等稳定信息决定。

因此文件移动到：

```text
另一目录
NAS
实验室服务器
新电脑
```

只要来源文件 hash 不变，仍然可以重新验证其身份。

本版本同时加入稳定：

```text
source_artifact_id
parsed_artifact_id
```

为未来 Knowledge / Workflow / Agent 建立长期引用基础。

---

### 5. Schema 与 backend runtime validation 收紧

`parsed-document/v2` 现在进一步检查：

- bbox 数值必须 finite；
- `x0 <= x1`、`y0 <= y1`；
- bbox 必须在规范范围；
- page number 与真实页面一致；
- width / height 必须有效；
- confidence / agreement 范围合法；
- warning / error 结构合法；
- backend geometry 与真实 PDF page 对齐；
- JSON 不允许 `NaN` / `Infinity`。

也就是说：

```text
Extraction Backend
        ↓
Runtime Validation
        ↓
Canonical Parser
```

本身成为新的明确 Trust Boundary（信任边界）。

---

### 6. 更诚实地表示 Figure / Table 证据

v0.7 不再把：

```text
找到 caption
```

等同于：

```text
图表已经被理解
```

Figure / Table 记录的是观测证据，例如：

- caption observed；
- caption + raster/vector region；
- caption + positioned cells；
- ambiguous；
- unassociated。

并明确：

```text
interpretation_status = not-interpreted
```

启发式 table structure 仍然保持 uncertain，不会仅因为检测到单元格就宣称结构已经确定。

这是为了让未来 Agent 读取的是“系统真正知道什么”，而不是被过度自信的 schema 字段误导。

---

## 二、AI-ready Consumption Layer

v0.7 在 Canonical Scientific Document 之上增加薄的 AI consumption/export layer（AI 消费/导出层）。

Canonical artifact 保持模型无关。

### Markdown

```bash
aletheia-nexus export PAPER.parsed.json \
  --format markdown \
  --output PAPER.ai.md
```

用于 LLM context、人工查看和 prompt attachment。

### JSONL

```bash
aletheia-nexus export PAPER.parsed.json \
  --format jsonl \
  --output PAPER.ai.jsonl
```

用于流式数据管道、后续知识抽取和模型前处理。

### Structure-aware chunks

```bash
aletheia-nexus export PAPER.parsed.json \
  --format chunks \
  --output PAPER.chunks.json
```

分块优先保留：

- section；
- heading；
- paragraph；
- caption；
- table object；
- equation；
- reference。

而不是每固定 N tokens 机械切割。

每个 chunk 都能够独立回答：

```text
我来自哪篇 canonical artifact？
对应哪些 blocks？
对应哪些 anchors？
来自哪些 pages？
如何回到原始 page / bbox？
```

因此证据链可以稳定保持：

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

Derived export 即使显式使用 `--overwrite`，也不能覆盖 canonical parsed artifact、原 PDF 或 acquisition sidecar。

---

## 三、Acquisition 层同步收口

v0.7 不是重新设计 v0.6 Acquisition，而是在保持原有可信边界的基础上完成若干收口。

包括：

- PMC 官方 Article Datasets route；
- PMC candidate 的 DOI / article / retraction / PDF 检查；
- 有界重试和版本错误隔离；
- title normalization 修正；
- browser profile-lock / diagnostics 修正；
- 继续复用统一 PDF identity + main-document role verification。

任何获取路径仍然必须最终收敛到同一个：

```text
VERIFIED
```

标准。

---

## 四、测试与资格证据

v0.7 不使用一个模糊的“总体准确率”概括所有质量，而是把不同证据分开记录。

### 最终 PR release-candidate CI

最终发布候选验证包括：

- Python 3.11 deterministic suite：**889 passed / 8 skipped**；
- Windows / Python 3.11：**889 passed / 8 skipped**；
- Python 3.12 / 3.13 / 3.14 compatibility jobs：全部通过；
- Linux real Chromium integration：**7 passed**；
- Windows real Chromium integration：**7 passed**；
- real Poppler + Tesseract raster-only OCR smoke：**1 passed**；
- wheel / sdist build：通过；
- `twine check`：通过；
- clean-wheel install：通过；
- `pip check`：通过；
- CLI `--version` / `doctor`：通过。

Frozen parser evaluator 已作为 CI 独立步骤运行，并上传机器可读：

```text
parser-evaluation.json
```

本次冻结 evaluator manifest SHA-256：

```text
1560fad286f80a735f72c40c7508b3b7e7ee13a86da7cfbe78d3e907613feecc
```

### Synthetic deterministic gold

自编、可再分发夹具的固定评测结果：

- 4/4 gate decisions；
- 32/32 anchored blocks；
- 6/6 selected anchors；
- 10/10 sections；
- 18/18 structural assertions；
- 886/886 gold characters；
- deletion = 0；
- insertion = 0；
- substitution = 0。

这些 synthetic fixtures 用于锁定 rotation、two-column、sparse/OCR、supplement rejection 等明确边界。

它们不是“真实世界所有论文都 100% 准确”的证明。

### Public OA real-layout qualification

建立了 3 篇 hash-frozen Open Access 真实论文资格集。

PDF 不进入仓库，而是按需从官方 PMC Article Datasets 来源获取并重新核对 SHA-256。

公开 qualification 检查包括：

- parser status；
- page count；
- anchor coverage；
- selected required text；
- conservative reference / figure / table thresholds。

这是 real-layout qualification（真实版式资格证据），不是完整人工逐对象标注 benchmark。

### Private real-layout stress

私有真实论文压力集累计覆盖：

```text
38 papers
655 pages
```

其中历史冻结记录包括：

```text
24/24 papers — 436 pages
14/14 papers — 219 pages
```

这些 PDF、sidecar 与逐篇输出保持在本地，不进入公开仓库。

该证据支持真实版式、运行稳定性、来源锚点和聚合诊断，但不能解释为：

- scientific semantic accuracy = 100%；
- 所有图片均完整理解；
- universal table correctness；
- visual information loss = 0。

---

## 五、安全、隐私与版权

AN 会处理来自网络的不可信网页和 PDF，因此 v0.7 同步收紧依赖安全下限，包括 pypdf、Pillow、FontTools 等。

长期工件和诊断默认避免持久化：

- Cookie；
- Authorization header；
- account credentials；
- signed URL 中的敏感 token；
- 本机绝对路径。

以下派生文件默认进入 Git ignore：

```text
*.parsed.json
*.ai.md
*.ai.jsonl
*.chunks.json
qualification-report.json
```

因为 parsed/export artifact 可能包含大量受版权保护的论文文本或本地研究数据。

Public OA qualification 只提交 manifest、hash、license 和 gold assertions；真实论文 PDF 按需从官方来源获取。

AN 的 Apache-2.0 开源许可不会改变第三方论文自身的版权和再分发条件。

---

## 六、这个版本明确没有做什么

v0.7 不包含：

- embedding；
- vector database；
- semantic search；
- LLM summarization；
- scientific entity extraction；
- experimental condition extraction；
- measurement / claim / relation extraction；
- knowledge graph；
- MCP server；
- Agent；
- laboratory memory；
- plot digitization；
- spectroscopy interpretation；
- scientific image semantic understanding；
- universal table/chart/formula understanding。

这些并不是“不重要”。

恰恰因为它们重要，所以不应该在底层文档基础设施尚未稳定时提前混进来。

v0.7 的边界是：

> **可靠表示科学文档及其来源证据，而不是替上层系统解释科学事实。**

---

## 七、使用方式

安装最新已发布版本：

```bash
python -m pip install -U aletheia-nexus
aletheia-nexus doctor
```

获取论文：

```bash
aletheia-nexus acquire 10.1371/journal.pone.0310216 \
  --public-only \
  --output-dir downloads/paper
```

解析 VERIFIED PDF：

```bash
aletheia-nexus parse downloads/paper.pdf \
  --doi 10.1234/example
```

需要 OCR：

```bash
aletheia-nexus parse downloads/paper.pdf \
  --doi 10.1234/example \
  --ocr
```

搜索 canonical artifact：

```bash
aletheia-nexus search PAPER.parsed.json QUERY --verify-sources
```

生成 AI-ready 数据：

```bash
aletheia-nexus export PAPER.parsed.json --format markdown --output PAPER.ai.md
aletheia-nexus export PAPER.parsed.json --format jsonl --output PAPER.ai.jsonl
aletheia-nexus export PAPER.parsed.json --format chunks --output PAPER.chunks.json
```

详细安装、浏览器、机构登录、OCR 和故障处理见 [USER_MANUAL.md](USER_MANUAL.md)。

---

## 八、v0.7 的最终定位

Aletheia Nexus v0.7 完成的不是：

> “PDF 转文字”

也不是：

> “让 AI 自动读论文”

而是建立了一条更基础的科研数据链：

```text
Scientific Literature
        ↓
Verified Scientific Artifact
        ↓
Source-linked Canonical Document
        ↓
Model-agnostic AI-ready Data
```

从这一层开始，后续模型、RAG、Knowledge、Workflow 和 Agent 才有一个长期稳定的证据基础。

下一阶段将逐步进入 Scientific Semantic Layer（科学语义层）：

```text
entity
method
condition
measurement
claim
relation
```

也就是从：

> **“这段结构化信息来自论文哪里？”**

进一步走向：

> **“这些证据表达了什么科学对象、实验条件、结果和关系？”**

这将是 AN 从 Document Infrastructure（文档基础设施）继续进入 Scientific Knowledge Infrastructure（科学知识基础设施）的下一步。
