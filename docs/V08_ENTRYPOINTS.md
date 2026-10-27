# v0.8 开发版：中文科研入口与本地 MCP

本功能位于 `feat/v0.8-extraction`，尚未正式发布。两个入口共用
`ResearchApplication → research-task/v1 → run_task → export_results`。
规划只决定要整理什么，科研提取才读取论文；计划不是已核实的科学结论。

## 安装和密钥

在源码目录、Python >=3.11 环境运行：

```powershell
pip install -e ".[mcp]"
```

只使用自带 CLI 可以 `pip install -e .`。MCP 是可选依赖，使用官方 Python SDK v2
`MCPServer`，最低2.3；普通获取、解析、检索和导出不依赖 MCP。
视觉补充沿用已有 Poppler `pdftoppm`，需在 PATH 中；不可用会明确记录材料缺口。

在 Windows“编辑账户的环境变量”中新建用户变量 `DEEPSEEK_API_KEY`，重开终端。
当前终端也可读取已设置值：

```powershell
$env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
```

不要把密钥发到聊天、写进任务或 MCP JSON。第一版规划与科研调用均使用现有 DeepSeek
Responses API，不把 Qwen Token Plan 接入无人值守科研服务。

## 从 PDF 文件夹开始

```powershell
aletheia-nexus research ask "整理这些论文的研究对象、方法、主要结果和作者报告的局限，生成中文对比表，保留原文来源" --papers "F:\papers" --output-dir "F:\results\an08"
```

也可只运行 `aletheia-nexus research ask`，再输入目录和中文目标。
默认只读所选目录内的 PDF，不递归扩大范围，也不联网获取新论文。

先在结果目录创建登记和解析副本，复用通过来源检查的既有工件。原始 PDF 与旧规范工件
不覆盖；派生 PDF 使用内容哈希目录与短文件名 `paper.pdf`，减少 Windows 长文件名导致
的页面渲染失败。未知标题、DOI、角色明确提醒；未登记文件按“独立主文、角色未确认”
登记，不猜测 SI 归属。已有 SI 请用 `aletheia-nexus import --help` 的 supplement/parent
选项先登记，再选主文与对应 SI，避免把附件当成独立论文。

交互有两次不同许可：

1. 发送中文目标与文献元数据给规划 API，不发送全文。
2. 预览中文计划后选 `e`，按显示的范围、模型与预算发送论文材料并执行。

计划展示文献、字段说明、步骤/跨文献比较、原页图片、SI 范围、模型、调用/费用上限和
输出格式。选 `m` 可在编辑器修改保存的任务并重读，`s` 只保存，`c` 取消。
模型可能扩展细分字段，请核对需求；证据定位也不等于科学内容已核实。

默认科研上限为10次HTTP、估算2 CNY；规划单独最多2次、估算0.5 CNY。
可设 `--max-calls`、`--max-cost`、`--planning-max-cost`，或用 `--model-config` 指向
既有 MODEL 契约配置。单价/用量估算不是账单，未知用量保留预留额。
没有 Key 时明确报错；既有手工任务仍可用 `research run`，不会假装理解自然语言。

## 非交互：先审计划，再按指纹批准

```powershell
aletheia-nexus research ask "提取方法和实验条件" --papers "F:\papers" --output-dir "F:\results\an08" --non-interactive --allow-planning --save-only
```

查看打印的计划及任务文件，确认后执行：

```powershell
aletheia-nexus research ask --papers "F:\papers" --output-dir "F:\results\an08" --task "打印出的task.json路径" --non-interactive --execute --allow-remote --confirm-plan "打印出的计划指纹"
```

第二条不重新调用规划。指纹绑定任务、PDF/来源记录、解析工件、模型、预算与允许目录；
材料或任务变化需重新预览。非交互没有默认上传许可。

## MCP：本地 stdio

```powershell
aletheia-nexus mcp serve --allow-dir "F:\papers" --workspace "F:\results\an08"
```

不监听网络端口。重复 `--allow-dir` 可增加授权目录，不要默认开放整盘/主目录。
工作区保存新材料、任务和导出，也属于可读范围，内部 `.authorizations` 目录除外。
目录穿越和越界的工件内嵌定位会拒绝。

复制 [Windows stdio 配置](../examples/mcp-stdio-windows.json)，改成自己的绝对路径。
常见客户端使用 `mcpServers` 包装；若不支持 `cwd`，删除该项即可，绝对 Python 路径
与已安装模块仍能启动。默认禁止远程模型，本地查询不需要 Key。

允许远程时需加 `--enable-remote`，还要将环境变量传给子进程。部分客户端过滤环境变量，
Windows 可以用附带脚本读取用户变量，避免把 Key 写进 JSON：

```json
{
  "mcpServers": {
    "aletheia-nexus": {
      "command": "powershell.exe",
      "args": [
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        "F:/AI4S/github/aletheia-nexus/scripts/start_an_mcp.ps1",
        "-Python", "F:/AI4S/github/aletheia-nexus/.venv/Scripts/python.exe",
        "-Papers", "F:/AI4S/papers",
        "-Workspace", "F:/AI4S/results/an08", "-EnableRemote"
      ]
    }
  }
}
```

执行策略仅限该启动进程，脚本应来自你检查过的本地仓库，不修改系统策略。
密钥只通过环境传递。协议输出为 stdout，日志为 stderr。

## 在 MCP 客户端使用

可以说：“列出 F:/papers 的论文，准备本地材料，整理方法和主要结果，先给我计划。”

| 工具 | 作用 | 远程调用 |
| --- | --- | --- |
| `list_documents` | 列举允许目录内PDF、来源/解析状态 | 否 |
| `prepare_documents` | 准备明确选择的PDF，隔离失败，在工作区建副本 | 否 |
| `draft_research_task` | 直接验证客户端任务；或从自然语言规划 | 只有自然语言分支需规划许可 |
| `validate_research_task` | 校验来源/字段/预算，返回计划及批准请求 | 否 |
| `execute_research_task` | 现有引擎异步执行，返回job_id | 科研模式需独立许可 |
| `get_run_status` | 查询状态、错误、原生清单和费用 | 否 |
| `export_research_results` | 重导出兼容结果为Markdown/CSV/JSONL | 否 |
| `search_documents` | 对选定文献做已有表格/图注感知检索，保留覆盖情况 | 否 |
| `read_document_context` | 读取完整原页上下文、表格、图注和位置 | 否 |
| `read_original_page` | 以MCP图像返回原始PDF选页和来源身份 | 否 |
| `get_parse_diagnostics` | 查看解析质量、失败诊断和当前来源核验 | 否 |
| `read_research_result` | 读取既有字段、引用、验证和修订历史 | 否 |
| `list_research_runs` | 查看本地历史运行与已记录费用 | 否 |

读取工具会把允许目录中的内容返回给宿主客户端；宿主自身模型是否向远程发送内容，
由该客户端的隐私与批准机制负责。AN 的 `--enable-remote` 控制的是 AN 自己的模型调用。
检索直接复用 v0.7 的表格/图注内容单元和证据包，不把字面未命中解释为科学事实缺失。
`read_document_context` 超出字符预算时明确跳过完整上下文，不截断表头或悄悄漏行。
跨盘的手工PDF/工件组合需先 `prepare_documents` 在工作区准备，再进行文库检索。

客户端已有模型时，可直接生成任务并验证，不必再调用 AN 规划API。只有自然语言目标时，
AN先返回规划许可请求。元数据和论文内容不会因模型传入 `confirmed=true` 自动发送。

远程批准返回本地请求文件。你在独立终端运行：

```powershell
aletheia-nexus research authorize "返回的authorization_request路径"
```

核对范围和预算，确认后将一次性授权交给当前 AN 工具。规划授权不能用于提取；
任务、材料、预算或目录改变后重新批准。授权一小时内有效，使用一次即失效，MCP没有
签发工具。受信任CLI的 `--approve-fingerprint` 只用于已审请求，不应让模型自行调用。
这是对 MCP 参数的边界，不是针对任意同用户本机程序的 OS 沙箱。

保持客户端/服务打开，查询状态直至终态。stdio客户端断开可能终止服务器进程树。
重启后未完成任务标 `INTERRUPTED`，不自动重发收费请求；先检查工作区的原生 manifest
及已交付结果，再经新批准恢复。既有缓存规则不变：不稳定的材料补充失败不能冒充缓存，
恢复可能需要API。停止用 Ctrl+C，或禁用/删除客户端配置，不清除原文。

新任务通过操作系统文件锁识别运行进程，CLI执行时可由另一个MCP入口查询；进程退出后
返回 `INTERRUPTED`。旧任务没有运行归属记录时保留未知状态，不猜测其进程已经停止。

## 保存内容与验收边界

`materials/`、`preparations/` 保存登记/解析和选择记录；`planning/` 独立保存规划请求、
原始响应、task.json 和 `phase=task_planning` 的运行清单。`jobs/` 是统一进度，
`research/runs/` 是原生科研结果与来源包，`exports/` 是重新导出。
`PARTIAL`、诊断和AI判断不会变成人工确认。

工程通过不等于科研准确率提升。真实模型、客户端、失败、用量与局限见验收记录；
真实SDK协议测试与桌面AI客户端手工会话测试分别说明，不互相替代。
