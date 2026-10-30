# 溯光（Aletheia Nexus）

[English](https://github.com/shenxuekairui/aletheia-nexus/blob/main/README.en.md) · [使用手册](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md) · [本地工作台](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/WORKBENCH_USER_GUIDE.md) · [科研与 MCP](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.md) · [贡献](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md)

> **从一篇论文的可信获取，走向可积累、可协作、可演化的科研知识基础设施。**

溯光（Aletheia Nexus，简称 AN）是一个**本地优先的科研知识基础设施项目**。它从文献入手，将论文获取、本地管理、结构化阅读、AI 信息整理和原文核对连接起来，让阅读笔记、实验条件、比较表和研究过程成为你能够持续保存、修订与复用的资料。

当你开始一个课题、比较不同方法、准备实验或撰写综述时，不必每次重新翻找下载目录、复制段落、整理同一批表格。溯光希望让这些工作形成可接续的积累：知道资料来自哪里，保留当时的处理过程，也能够在新的问题下继续使用。

## 为什么做 AN

我们关心的不只是如何获取论文，而是一个更长期的问题：

> **当 AI、软件工程、Workflow 和 Agent 进入科研之后，研究者和实验室需要怎样的一层基础设施，才能让数据、证据、知识、工具与方法持续积累？**

越来越强的模型，并不会自动形成可靠的科研系统。原始数据、证据来源、处理过程、实验规则，以及研究者逐渐形成的方法与判断，都需要有自己的保存和组织方式。

今天，这些内容往往散落在浏览器、下载文件夹、脚本、笔记和聊天记录中。项目结束、人员离开或工具更换后，积累容易丢失。我们选择从一件可以具体检验的事开始：**让一篇论文成为可阅读、可追溯、可长期复用的本地科研资料。** 再从可靠的数据和工具，逐步走向知识组织、可组合工作流与必要的 Agent 协作。

> **稳定能力先工具化，确定流程再工作流化，开放式判断才交给 Agent。研究者的科学判断始终处于中心。**

## 现在可以怎样帮助你

| 你要完成的工作 | 可以得到的资料与能力 |
| --- | --- |
| 准备一个研究主题 | 从 DOI、题名、文献清单或本地 PDF 开始，组织论文、关联 SI、整理阅读材料与笔记 |
| 比较实验与方法 | 自定义提取对象、方法、参数、操作步骤和结果，保留原始值、单位、实验范围与来源，导出比较表 |
| 围绕科研问题查证 | 检索本地原文，整理相关证据、不同解释及未解决问题，并回到正文、图表和补充材料核对 |
| 维护自己的文库 | 导入与批量获取、分类与标签、标题翻译、预览后改名或迁移、解析版本和本地任务历史 |
| 持续修订与复用 | 在结果与原文之间定位，保存修订版本，导出 Markdown、CSV、JSONL 与必要的来源信息 |
| 让外部 AI 使用文库 | 通过本地 MCP 调用获取、解析、检索、科研任务及结果能力，复用同一套底层服务 |

材料可以沿一条连续的工作流积累：

```text
论文与补充材料
    ↓
本地文库：来源、分类、标签与文件
    ↓
带页码和位置的阅读材料、表格、原页与证据
    ↓
研究问题 → 阅读笔记 / 信息表 / 实验流程 / 跨文献比较
    ↓
核对、修订、导出 → 下一次实验、综述或科研工作流
```

这些能力服务于不同科研任务，共用通用字段和执行体系，不要求将某一学科的问题套进固定模板。

## 三种使用入口

- **本地科研工作台**：用中文界面完成文献获取、文库管理、科研检索、AI 研究和成果核对。适合从文件夹和具体科研需求开始。
- **命令行**：批量处理、自动化脚本和可重复执行的任务；`research ask` 接受自然语言，无需先手写任务 JSON。
- **MCP 服务**：让支持 MCP 的 AI 客户端组合使用溯光的本地工具。客户端已有结构化任务时，不必额外调用一次规划模型。

三个入口共用核心能力、来源与结果体系，资料不会只留在某一次聊天中。

## 快速开始

需要 Python 3.11 或更新版本，建议使用虚拟环境。安装发布包后打开本地工作台：

```bash
python -m pip install "aletheia-nexus[ui,mcp]>=0.8.0"
aletheia-nexus --version
aletheia-nexus doctor
aletheia-nexus ui --library "./library"
```

浏览器默认打开 `http://127.0.0.1:8080`。可以导入自己的 PDF 文件夹，也可以先获取一篇公开论文；仅需命令行与本地解析时，安装 `python -m pip install aletheia-nexus` 即可。若从源码开始，在克隆的项目目录内使用 `python -m pip install -e ".[ui,mcp]"`。

UI 和 MCP 为可选依赖。浏览器二进制、Poppler 或 OCR 引擎按环境诊断和使用手册另行配置；安装 Playwright Python 包不会自动准备所有浏览器运行时。已发布安装包的版本与文件请核对 [PyPI](https://pypi.org/project/aletheia-nexus/)和 [GitHub Releases](https://github.com/shenxuekairui/aletheia-nexus/releases)，不要将源码进展当作发行状态。

### 从一句科研需求开始

在工作台选择论文，输入需要整理的内容；也可通过命令行：

```bash
aletheia-nexus research ask "整理这些论文的研究对象、方法、主要结果和局限，生成中文对比表并保留原文来源" --papers "./papers" --output-dir "./results"
```

先核对任务草案、文献范围、字段、模型和预算，再确认执行。任务、原始响应、来源关联、结果和失败记录保存在输出目录，可继续查看、修订和导出。

新建 AI 计划默认先阅读材料再组织字段，也可在计划中选择单轮提取。已有任务保持原策略；程序不会替用户增加调用次数或费用上限。

内置 AI 工作流目前使用 DeepSeek；可在工作台设置或本机 `DEEPSEEK_API_KEY` 环境变量中配置密钥。规划只发送目标及必要元数据，发送论文内容另行授权。配置密钥不会自动启用远程处理；本地管理、解析、检索和已有结果导出不需要模型 API。

### 获取论文或接入其他 AI

```bash
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir "./library"
aletheia-nexus mcp serve --allow-dir "./papers" --workspace "./results"
```

获取支持公开来源及已有合法机构权限；需要登录或验证码时，在专用浏览器中由用户完成。MCP 默认使用本地 stdio，文献访问受允许目录限制，远程操作需要独立授权。详细配置见[自然语言与 MCP 指南](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.md)。

## 你的资料，持续保留在本地

原文、解析工件、任务、历史和导出文件由用户掌控；外部模型是一种可替换的能力来源。核心本地功能不依赖某家模型、向量数据库或云端账号系统。来源与历史随资料保存，支持后续工具和工作流继续使用。

AI 仍可能漏掉信息、误读图表或混淆实验对象与条件；解析成功、结构化格式通过或引用位置存在，都不能自动证明科学内容正确。重要结论应核对原文，尤其是复杂图表、单位、实验阶段和正文与 SI 的关系。软件会保存待核对项与失败，研究者可以保留不确定性并修订结果。

当前能力边界、评测方法和真实表现见[科研质量说明](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_STATUS.md)及[最新十篇对照](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_TEN_PAPER_COMPARISON.md)。这些记录与工程验收分开，不把示例、助手复核或开发集改善当作专家认证与普适性能承诺。

## 文档与参与

主要文档以中文为主，并提供独立英文对照：

| 主题 | 中文 | English |
| --- | --- | --- |
| 安装与常用流程 | [使用手册](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.md) | [User manual](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/USER_MANUAL.en.md) |
| 图形工作台 | [工作台指南](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/WORKBENCH_USER_GUIDE.md) | [Workbench guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/WORKBENCH_USER_GUIDE.en.md) |
| 科研整理与提取 | [科研指南](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_USER_GUIDE.md) | [Research guide](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_USER_GUIDE.en.md) |
| 自然语言与 MCP | [入口与配置](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.md) | [Entrypoints and configuration](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_ENTRYPOINTS.en.md) |
| 科研质量与最新对照 | [质量说明](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_STATUS.md) · [十篇对照](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_TEN_PAPER_COMPARISON.md) | [Quality](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_STATUS.en.md) · [Ten-paper comparison](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_TEN_PAPER_COMPARISON.en.md) |
| 版本与验收 | [发布说明](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_NOTES_v0.8.0.md) · [版本记录](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_HISTORY.md) · [验收](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_RELEASE_ACCEPTANCE.md) | [Release notes](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_NOTES_v0.8.0.en.md) · [Release history](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/RELEASE_HISTORY.en.md) · [Acceptance](https://github.com/shenxuekairui/aletheia-nexus/blob/main/docs/V08_RELEASE_ACCEPTANCE.en.md) |

欢迎通过 [Issues](https://github.com/shenxuekairui/aletheia-nexus/issues)反馈真实科研需求与使用问题，或按[贡献指南](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CONTRIBUTING.md)参与开发和文档改进。社区遵循[行为准则](https://github.com/shenxuekairui/aletheia-nexus/blob/main/CODE_OF_CONDUCT.md)，敏感信息按[安全说明](https://github.com/shenxuekairui/aletheia-nexus/blob/main/SECURITY.md)报告。

代码采用 [Apache-2.0 许可证](https://github.com/shenxuekairui/aletheia-nexus/blob/main/LICENSE)。论文及其他第三方材料保留各自的版权和使用条件；本项目的代码许可证不代表这些材料可自由再分发。
