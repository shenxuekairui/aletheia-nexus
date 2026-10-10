# Aletheia Nexus

[English README](README.en.md) · [使用说明](docs/USER_MANUAL.md) · [v0.7.1 发布说明](docs/RELEASE_NOTES_v0.7.1.md) · [贡献指南](CONTRIBUTING.md) · [安全报告](SECURITY.md)

> **从一篇论文的可信获取，走向可积累、可协作、可演化的科研知识基础设施。**

Aletheia Nexus（AN）是一个 **local-first（本地优先）的科研知识基础设施项目**。当前从文献入手：帮助研究者获取和核验论文，在本地整理保存，再把经过验证的 PDF 转换为带有原文位置、可供 AI 使用的结构化数据。

简单来说，你可以交给 AN 一个 DOI 或一份文献清单，得到的不只是下载文件，还包括“这是不是目标论文、从哪里获得、文件是否改变过”的记录。继续解析后，提取出的内容可以回到原始 PDF 的页码和位置。

AN 目前以 Python 包和命令行工具提供这些能力，不是带图形界面的文献管理器，也不是已经能够独立完成科研的 Agent。

## 为什么做 AN

我们关心的不只是“如何把论文下载下来”，而是一个更长期的问题：

> **当 AI、软件工程、Workflow（工作流）和 Agent（智能体）真正进入科研之后，研究者和实验室需要怎样的一层基础设施，才能让数据、证据、知识、工具与方法持续积累，而不是每一次都从头开始？**

越来越强的模型，并不会自动形成可靠的科研系统。真正能够长期产生价值的，还有模型之外那些可以被保存、验证、迁移和复用的东西：原始数据、证据来源、处理过程、实验规则、工具、工作流，以及研究者逐渐形成的方法和判断。

这些内容今天往往散落在浏览器、下载文件夹、脚本、笔记和聊天记录里。项目结束、人员离开或工具更换后，许多积累又重新消失。AN 希望让科研活动逐渐产生属于研究者自己的数字资产，而不是把知识与科研历史完全交给某一个平台或模型。

因此，我们选择从一个可以严格检验的问题开始：**先让一篇论文成为可信、可追溯、可长期复用的本地科研工件。** 再由可靠的数据和工具，逐步走向知识、工作流与 Agent。

> **稳定能力先工具化，确定流程再工作流化，只有真正开放的判断才交给 Agent。**

底层越可靠，高层智能才越有意义。人的科学判断，始终应处在这个系统的中心。

## 现在可以做什么

v0.7.1 将文献获取、本地整理和带来源解析连接成一条工作流：

```text
DOI / 文献清单（知网也支持题名）
        ↓
查找来源 → 使用公开或已有合法权限获取
        ↓
核验目标正文 → 保存 PDF 和来源记录 → 按文件夹与标签整理
        ↓
解析已验证且有 DOI 的论文 → 保留章节、页码和原文位置
        ↓
检索 / Markdown / JSONL / 带来源的结构化分块
        ↓
供研究者或下游 LLM、RAG、Workflow、Agent 使用
```

| 你要做的事 | AN 提供的能力 |
| --- | --- |
| 找到论文 | DOI 标准化，Crossref / DataCite 元数据，OpenAlex / Unpaywall / PMC 等全文线索 |
| 获取正文 | 公开 HTTP、已授权官方接口、浏览器机构会话；批量顺序处理与断点续跑 |
| 获取知网期刊论文 | DOI 或题名输入；结合书目信息分流、检索和核验，不把所有失败请求都送往知网 |
| 确认拿对文件 | PDF 结构、论文身份、正文/附件角色检查；记录来源和 SHA-256 文件校验值 |
| 在本地整理 | 输入时指定文件夹、名称和标签；默认按“年份-期刊-标题”命名，按条件查看文献 |
| 读取与定位内容 | 原生文本优先解析、可选 OCR；章节、文本块、参考文献和图表观测证据保留页码及位置 |
| 交给其他工具 | 检索解析结果；导出 Markdown、JSONL 或结构感知分块，不绑定模型或向量数据库 |

这些能力不等于全库覆盖或每篇必定成功。在线获取取决于来源、机构权限与站点状态；版式解析也会明确报告不完整结果。科学语义理解、知识图谱和 Agent 自主研究仍属于后续方向。

## 快速开始

需要 Python 3.11 或更高版本。以下命令均为单行，可在常见终端中运行。本文对应 v0.7.1 源码；实际已发布版本以 [PyPI 项目页](https://pypi.org/project/aletheia-nexus/)为准。

### 1. 安装并检查环境

```bash
python -m pip install -U aletheia-nexus
aletheia-nexus --version
aletheia-nexus doctor
```

基础安装不需要浏览器，也不需要模型 API Key。获取在线文献仍需要网络；本地优先不等于所有步骤都离线。

### 2. 先获取一篇公开论文

```bash
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir downloads/first-paper
```

检查结果是否为 `VERIFIED`。这表示拿到了通过身份与正文核验的 PDF；仅有文件、页面打开成功或命令正常结束，都不代表验证成功。若公开来源暂时无法提供可验证正文，AN 会如实返回非成功状态。

### 3. 使用浏览器和机构权限

```bash
python -m pip install -U "aletheia-nexus[browser]"
python -m playwright install chromium
aletheia-nexus acquire 10.7503/cjcu20250333 --output-dir downloads/papers
```

默认以普通启动方式打开 AN 专用浏览器，优先使用可用的 Chrome/Edge，采用独立配置和直连网络，不读取或改动日常浏览器配置。任务结束后保留窗口；下次使用同一配置可以继续复用会话。结束使用后可手动关闭该 AN 窗口。

机构 IP、校园网或 VPN 已有权限可以直接复用；仍需登录或验证码时，请在这个窗口完成，AN 会等待后继续。**AN 不提供订阅、不绕过付费墙，也不代答验证码。** 浏览器配置无法保证网站不再要求验证。

需要程序托管窗口生命周期时可用 `--browser-launch-mode managed`。Windows / Linux x64 的独立浏览器运行时可通过 `aletheia-nexus browser-install` 安装；网络、浏览器选择和故障处理见[使用说明](docs/USER_MANUAL.md)。

### 4. 批量获取并分类保存

将下面内容保存为 `papers.json`，按需替换 DOI、文件夹与标签：

```json
[
  {
    "doi": "10.7503/cjcu20250333",
    "folder": "化学/待读",
    "tags": ["待读", "重点"]
  }
]
```

```bash
aletheia-nexus acquire papers.json --output-dir downloads/library --fail-on-unverified
aletheia-nexus library downloads/library --folder "化学" --tag "待读"
aletheia-nexus library downloads/library --query "催化"
```

也支持每行一个 DOI 的 TXT，以及带书目字段的 CSV。JSON/CSV 可以提供题名、作者、期刊和年份，帮助准确匹配；知网文献没有 DOI 时也可以按题名获取，建议同时填写作者与年份以区分相似文章。详见[输入说明](docs/USER_MANUAL.md#2-准备文献清单)和[完整示例](examples/classified-papers.json)。

新文件默认采用 **年份-期刊-标题**，末尾附加身份与内容短码以避免同名覆盖；缺失字段省略，不虚构元数据。可通过 `filename` 自定义可读名称。旧文件不会批量改名，分类也不会由模型自行猜测。

再次执行同一批次时，会先核对文件与来源记录再续跑。标签可以单独修改，不改动 PDF 或原始获取证据：

```bash
aletheia-nexus library tag "实际论文路径.pdf" --add "已阅读" --remove "待读"
```

### 5. 解析、检索并导出

将下面的 `PAPER.pdf` 换成已获取文件的实际路径，DOI 换成该论文的真实 DOI。解析需要保留同目录的 `.acquisition.json` 来源记录：

```bash
aletheia-nexus parse PAPER.pdf --doi 10.1371/journal.pone.0310216
aletheia-nexus search PAPER.parsed.json "Methods" --verify-sources
aletheia-nexus export PAPER.parsed.json --format markdown --output PAPER.ai.md
aletheia-nexus export PAPER.parsed.json --format jsonl --output PAPER.ai.jsonl
aletheia-nexus export PAPER.parsed.json --format chunks --output PAPER.chunks.json
```

解析结果是独立的 `.parsed.json` 文件，原 PDF 与来源记录保持不变。Markdown 便于阅读或交给模型，JSONL 便于数据处理，结构化分块适合下游检索和 RAG；这些都是同一解析结果的派生视图。

扫描页需要 OCR 时，另行安装 Poppler 与 Tesseract，再安装可选依赖并启用：

```bash
python -m pip install -U "aletheia-nexus[ocr]"
aletheia-nexus parse PAPER.pdf --doi 10.1371/journal.pone.0310216 --ocr
```

OCR 只补充原生文本不足的部分。依赖缺失、超时或版式无法完整处理时会报告降级，不把不完整结果伪装成完整解析。**当前无 DOI 的知网文献可以获取和核验，但还不能进入要求真实 DOI 的解析通道。**

## 可信，不只是“下载成功”

科研中昂贵的错误，往往不是少一个换行，而是把附件当正文、把另一篇文章交给模型，或提取出了无法再定位来源的内容。AN 把这些问题当作数据基础设施问题，而不只是提示词问题。

### 文件与身份

所有获取路径使用共同的正文验证边界：文件可读还不够，身份和角色也必须符合目标。题名相似、证据不足或身份冲突时，不会为了提高成功率而直接接受第一条结果。来源记录保存校验值，后续使用可以发现文件被修改。

### 内容与来源

解析前会重新检查 `VERIFIED` 状态、DOI、正文角色、文件与来源记录的哈希及页数。解析后的文本块、引用和图表观测证据保留来源位置；导出的分块也能沿这条链返回原文：

```text
分块 → 文本块 → 来源锚点 → PDF 页码与位置 → 原始论文
```

**`PARSED` 表示完成了相应文档解析，不表示论文结论正确，也不表示系统理解了全部图表和科学含义。** 不完整解析使用 `PARTIAL` 等明确状态。

### 权限与人工边界

`INTERACTION_REQUIRED` 表示需要人工交互；`ENTITLEMENT_REQUIRED` 表示当前会话缺少正文权限；`EXHAUSTED` 表示已尝试的路径没有得到可验证正文。这些状态帮助研究者决定下一步，而不是被隐藏的失败。

知网目前以期刊论文为重点，支持 PDF，不将 CAJ 转为 PDF，也不承诺识别或下载全库。自动恢复是有限的，不会通过反复刷新登录页、破解验证码或放宽身份校验来追求“全自动”。

### 本地保存与迁移

PDF、来源记录、解析结果和标签保存在本地，不要求数据库、后台索引或模型服务。移动或备份文献时应保留配套文件。浏览器配置可能包含登录状态，应像账号资料一样保护；本地优先不意味着这些文件可以随意公开。

## 工程原则与发展方向

AN 坚持正确性优先于自动化、明确失败优于静默错误；原始证据不被派生结果反向覆盖，稳定数据不依赖某个模型或平台。只抽象已经真实出现的重复，不为想象中的未来提前增加复杂度。

当前重点是把文献这一起点做好。长期路线是：

```text
可信科研对象与数据 → 可验证工具 → 可复现工作流 → 可积累知识 → 有上下文的 Agent
```

下一层会逐步关注实体、方法、实验条件、测量、主张与证据之间的关系。它们是未来的科学语义层，不是本版本已经交付的自动知识理解能力。

## 验证与文档

项目使用确定性回归、真实浏览器夹具、解析基准和安装包验证来检查功能边界；真实出版社访问记录与这些测试分开说明。特定环境的通过结果，不代表通用下载成功率，也不代表科学语义准确率。

| 文档 | 适合何时阅读 |
| --- | --- |
| [使用说明书](docs/USER_MANUAL.md) | 安装、输入、批量获取、本地管理、解析、OCR 与故障处理 |
| [v0.7.1 发布说明](docs/RELEASE_NOTES_v0.7.1.md) | 理解本版本、升级变化与使用边界 |
| [版本与验收记录](docs/RELEASE_HISTORY.md) | 查阅各版本的测试范围、结果和发布状态 |
| [CNKI 使用说明](docs/CNKI_AUTOMATION.md) | 知网输入、合法机构访问及限制 |
| [解析契约](docs/V07_PARSING_CONTRACT.md) · [架构](docs/V07_ARCHITECTURE.md) · [OCR](docs/V07_OCR.md) | 接入解析结果、开发后端或了解技术边界 |
| [CI 架构](docs/CI_ARCHITECTURE.md) · [Benchmark](benchmarks/README.md) | 复现工程验证与评测 |

## 参与项目

欢迎报告可复现问题、提供可合法公开的测试夹具、反馈机构访问与首次使用体验，也欢迎讨论科研知识、工作流和 Agent 的下一步。首次试用可在 [Issue #3](https://github.com/shenxuekairui/aletheia-nexus/issues/3) 记录反馈；代码贡献见[贡献指南](CONTRIBUTING.md)。

请勿在公开 issue 中提交受版权保护的论文 PDF、Cookie、令牌、机构登录截图、带签名的 URL 或未脱敏的本地路径。安全问题请遵循[安全报告说明](SECURITY.md)。

项目代码采用 [Apache License 2.0](LICENSE)。第三方论文与科研内容仍受各自版权、许可证和访问条件约束；AN 的开源许可不会赋予这些内容再分发权利。

*Aletheia* 意为“真理”，*Nexus* 意为“连接”。AN 想做的不是一个更聪明的下载脚本，而是一层可以被长期信任的科研数据与知识基础设施：**让每一个结论，都有机会回到它真正来自的证据。**
