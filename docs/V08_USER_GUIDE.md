# v0.8 开发版：AI 文献整理与知识提取

这是未发布开发功能，真实留出评测尚未达到科学验收目标；关键实验条件应查看原文。
各路径的正确率、遗漏及完整记录结果见 [验收记录](V08_ACCEPTANCE.md)。
原有 acquire、import、parse、search、
export、EvidenceJudge 接口继续使用。新功能入口为 `aletheia-nexus research`。

## 快速开始

在当前源码环境安装开发版后，复制 `examples/research-theme.json`，把文献路径改为自己
的 `.parsed.json` 路径。路径相对于任务 JSON 所在目录解析，也支持绝对路径。
未登记的 PDF 先使用既有 `import` 命令，正文与 SI 的登记方式见
[科研流程](V072_RESEARCH_WORKFLOW.md)。不要为 AI 绕过来源校验。

```powershell
python -m pip install -e ".[dev]"
aletheia-nexus research run task.json --output-dir research-output
```

示例默认 `mode=local`、`allow_remote=false`，只准备任务材料，不调用 AI。
原有本地功能也不需要 API Key。正式提取时，把任务改为 `mode=hybrid`、
`allow_remote=true`，然后显式增加 `--allow-remote`：

```powershell
aletheia-nexus research run task.json --output-dir research-output --allow-remote
```

## 模型和密钥

首版只提供 DeepSeek Responses API 适配器，模型配置使用 `deepseek-flash`。
它支持文本、图像和 JSON Schema；依据 [DeepSeek Responses API 文档](https://api-docs.deepseek.com/api/create-response/)。
普通自动化测试使用 Mock，不发送论文。设置环境变量 `DEEPSEEK_API_KEY`；
不要把密钥放入任务、源码、命令参数或结果文件，也不要在聊天中发送。

Windows：打开“编辑账户的环境变量”，在用户变量中新建 `DEEPSEEK_API_KEY`，
值为密钥，不加引号。**新开的终端**继承此变量。已有 PowerShell 终端可显式刷新：

```powershell
$env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
```

不要打印这个变量。Linux/macOS 可通过终端或系统安全配置给进程提供同名环境变量。
程序不保存请求头和原始错误响应；记录HTTP状态码、固定错误类别、模型、提示词指纹、输入指纹、
耗时、可获得的 Token 数和费用估算。模型可能拒绝、截断或产生无法核验的输出，均不
作为成功结果静默接受。JSON 结构有效也不保证科学正确。

费用配置包括 `currency`、`input_cost_per_million`、`output_cost_per_million`，
以及可选的 `cached_input_cost_per_million`；省略缓存价格时按普通输入价保守计算。
预算使用同一币种的 `budget.max_cost`。当前示例按 2026-10-25 官方高峰未命中缓存
价格（输入 2 元、输出 8 元/百万 Token）作保守估算；不据此承诺未来价格。
[官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)。配置缓存单价后，仅对
服务返回的缓存命中 Token 计优惠；缺少明细时不猜测缓存量。没有自动时段定价切换，
跨时段任务宜用高峰价格控制预算，再与服务商账单核对。

调用前按 UTF-8 输入字节、图像余量和最大输出预留费用；收到完整用量后按配置单价
结算估计费用，保留原预留记录。没有完整用量的失败/超时仍按预留占用预算，因为服务
可能已计费。这是保守的程序预算，不是服务商账单硬上限。`max_cost`、
`max_calls` 限制一次运行，重跑有自己的预算；跨任务的总体限额须另行累计。
返回用量缺失时明确记录 unknown，不能解释为零费用。没有自动充值或模型路由。

默认 `reasoning_effort=none`，温度固定为 0；可显式配置 low/high/max。
`max_output_tokens` 包含推理 Token。实测长文在 low/9000 时出现截断，不能只按最终
可见 JSON 长度估计输出预算。`model_incomplete` 保留截断候选和原因，不当作成功。

跨任务的累计评测可用仓库脚本（所有相关运行必须使用同一输出根目录）：

```powershell
python scripts/run_v08_evaluation.py task-a.json task-b.json --output-dir research-evaluation --max-total-cny 100 --allow-remote
```

脚本串行执行并持有系统文件锁，避免多个评测同时花费同一余额。HTTP 前记录预留；
已经花费和未知计费的调用都纳入累计限制。单独运行 `research run` 的其他输出目录
不自动纳入这个台账；服务商实际账单仍需在账户中核对。

## 同一任务契约支持四类用途

`type` 可为 `organize`、`extract`、`procedure`、`compare`，共用同一提取引擎。
`objective` 写研究问题；`fields` 每项包含唯一 `id`、含义 `description` 和类型。
支持 string、number、integer、boolean、string_list；可加 label、unit、scope。
单位是期望描述，不触发自动换算。字段应说明对象、条件和范围；拆成更小的字段便于
核对，但不能保证更完整或更准确。开发配对实验中，拆分仍保留条件错配，并出现了
额外的引用校验失败；应先用少量原文比较任务配置的效果。

文献列表中的 `id` 是任务内简短标识，不能重复。每项可设置：

| 配置 | 用途 |
| --- | --- |
| artifact | 已有规范解析文件；只读，重新校验来源 |
| pdf / sidecar | 显式指定原文件位置，用于移动后的工件或原页直读 |
| pages | 选定的 PDF 页码，从 1 开始；不是论文印刷页码 |
| image_pages | 发送哪些原页图像，仅 hybrid/direct 可用 |
| notes | 用户备注，作为上下文而非原文事实 |
| corrections | 任务级人工读法覆盖层，详见下节 |

正文和 SI 使用不同文献 ID、不同 PDF 和各自页码；已登记为 SUPPLEMENT 的来源依据
原有 parent 哈希与正文归组。必须把 SI 明确列入任务，模型不能自行读取未授权文件。

任务级 `query` 使用现有文库检索选择上下文；显式 `pages` 优先。`context_pages`
控制相邻页范围。无 query/pages 时尝试全文；超过预算明确失败，应缩小范围或调整预算，
不会默默截断文本。材料包保留完整追溯信息，发送给模型时去除重复的几何与诊断视图。

`rules` 用自然语言说明保留差异、阶段划分和输出语言。`synthesize=true` 会在单篇
提取后追加跨文献整理；比较结果仍引用原文，失败时保留已有单篇结果。

只需要笔记或信息表时，可设置 `"include_steps": false`，要求每条记录的 `steps`
和每字段的 `step_ids` 都为空。此项同时进入模型输出约束与本地校验，避免只在文字
规则里要求不生成步骤而被忽略。若模型仍生成步骤，使用已有的一次修复机会；再次
失败则明确失败，不静默删去步骤后当作成功。`true` 允许整理有来源的操作步骤，并不
要求给缺少操作描述的论文编造流程。省略该项时保持旧任务允许步骤的行为；旧结果
仍可读取、修订和导出。更改此项会改变任务指纹，不能复用不兼容的旧结果。

`export_formats` 选择派生结果的导出格式，例如 `["markdown", "csv"]`。允许 markdown、
csv、jsonl，省略时全部导出；列表必须非空且不重复。原始结果 JSON、任务和运行清单
始终保留。local 模式尚未提取字段，仍保存原文材料报告和材料包，不生成虚假的结果表。

## 处理路径和材料补充

- local：只建立本地任务材料包；零远程调用。
- parsed：只把选定的 v0.7 文本与表格观测发送给模型，用于文本基线。
- hybrid：文本加显式选择的图像；模型请求补页时加入相应文本和页面图像。
- direct：发送指定的原页图像，不发送解析文本；提供 pdf 时无需解析工件。

原页模式需要 PATH 中存在 `pdftoppm`（Poppler）。单页按 CropBox 渲染，长边
1600 像素，最多等待 60 秒；可读性仍须核对。`verify_original=true` 要求把所选页
一起作为图像输入。首版没有 PDF 文件上传或整篇自动视觉扫描。

模型可以请求任务范围内的页。`max_supplement_rounds` 默认 1，最多 3；并受
max_images、max_input_characters、max_output_tokens、max_calls、max_cost 限制。
如果没有新增材料，不再次调用。文件缺失、渲染失败或预算不足时保留已有候选结果，
记录原因；无法解决的材料缺口留给用户。模型不能自己重写 PDF 或启动任意解析命令。

补页后重新从当前材料提取完整任务，只传递此前待查问题、当前与新增的文本/图像页
覆盖，不把整份旧答案当作新输入。旧候选仍保存在运行目录，补充处理失败时可保留它
及其原材料包。此策略减少沿用旧“未提供”判断的机会，不能保证模型充分利用材料，
也不把页面覆盖当作科学支持。提示词v8与旧版本缓存不兼容，旧结果仍可离线查看和导出。

解析问题请先区分：补充邻页/SI、在新文件重跑解析，还是修改模型任务。不要仅因为
模型无法提取就不断增加解析规则。`PARSED` 不代表科学语义已正确。

核对关键数字或化学式时，可以另存一个少字段的extract任务，仅选择相关原页，
分别查看parsed与hybrid结果，并保留原始批次结果。实际开发检查中，这种小范围任务
纠正过视觉直读的近似号、化学式下标和元素归属错误；增加图像分辨率或reasoning
强度则没有稳定收益。它是核对方法，不是自动科学认证，也不能据此删除其他差异。

对已经生成的某一条主张，也可以复制
[原文支持复核示例](../examples/research-source-review.json)，填写原文路径、相关页码和
候选主张，并在备注记录旧结果ID及字段名。配置默认local，改为parsed并显式启用远程
后，仍通过同一个`research run`执行。若需要原页图像，改为hybrid并填写image_pages。
建议每项任务只复核一个明确主张，避免成对候选相互提示答案。
supported、contradicted、insufficient是模型的辅助判定；同时阅读context和引用。
开发测试出现过“解释已经发现对象不符，判定仍为supported”的错误，所以不按这一
标签自动删除、改写或确认旧结果。复核结果作为独立派生记录保存。

人工修订读法时，把以下对象放入对应文献的 `corrections` 列表：

```json
{
  "block_id": "从该工件复制真实块ID",
  "original": "完整原始块文本",
  "replacement": "修订后的读法",
  "reason": "修订所依据的原页和理由",
  "author": "修订人",
  "at": "2026-10-25"
}
```

original 必须精确匹配原块；旧读法仍保留。修改任务即形成新的材料指纹和结果，
不会命中旧配置缓存。补充页只改变派生材料包，不改变规范解析工件。

## 结果、恢复与修订

每次运行创建新的 `runs/<运行ID>/`，保存 task.json、manifest.json、逐文献
package/candidate/result JSON、页面图像，以及 report.md、table.csv、records.jsonl。
报告默认展示整理结果、字段、操作步骤和轻量引用；详细诊断留在本地文件。
CSV 防止以公式执行模型文字，原值和原单位完整保留在结构化记录中。
选择 jsonl 且结果包含独立主张或跨文献结论时，同时生成 claims.jsonl，保存主张、性质、
来源、结果身份和核对状态；records.jsonl 继续只包含字段记录，方便已有处理脚本使用。

字段区分原文报告、规范化、所给材料未报告、有歧义、未确认；主张另区分直接报告、
作者解释、AI 归纳。不同对象、实验阶段保存在不同记录中，条件通过 step_ids 关联步骤。
摘要没有单个原始值时允许 raw_value 为空，原读法保存在 citations 中；数值、布尔值
和 normalized 字段必须保留 raw_value。not_reported的value/raw_value/unit都为null，
原因放context；定性的“环境温度”等仍可作为reported值，不能因缺少数值而判未报告。
步骤关联的科学正确性不能由 ID 存在证明。
程序校验引用是否来自已发送的块/页面，文本短引文须匹配原读法或人工覆盖层；
空白和排印连字视为等价，但不会归一化负号、上下标或单位。视觉引用始终待核对。
引用有效不表示证据实际支持科学主张。报告将待核对事项折叠，详细状态留在 JSON。

`max_repair_rounds` 默认为 1，可设为 0。输出格式或引用校验失败时，最多给模型一次
具体错误反馈，要求依据同一材料修正；这不同于 max_supplement_rounds 的补页过程。
一次反馈会列出所有已发现的引用问题，避免只修第一处后再次为剩余错误付费。
填错块ID或页码时，反馈还会给出同篇已提供材料中最多三个精确引句匹配位置；
模型仍须重新判断上下文。系统不自动迁移引用，不扩大材料范围，不放宽符号匹配。
二者共享总预算。鉴权失败、拒绝和截断不盲目重复；失败候选以 rejected 文件保留。
候选可能包含错误的科学内容，不能作为有效提取结果使用。

再次执行相同命令会重新核对文件和输入指纹，复用有效结果，重试失败文献；
任务、提示词、Provider 配置、材料或人工备注改变时不错误复用。`--no-resume`
强制重跑。中断后已有结果保留。输出 status=PARTIAL 时先看 manifest 的具体原因；
缺少参数或原文歧义可以是有用的部分结果，不必反复付费重试。
模型反复请求已提供材料时，保存并复用明确的 PARTIAL 状态；不会升级为完整成功。

离线重新导出：

```powershell
aletheia-nexus research export paper1.result.json paper2.result.json --output-dir edited-export
aletheia-nexus research export paper1.result.json --output-dir csv-export --formats csv
```

`--formats` 只改变这次离线导出，不修改原结果或再次调用模型。省略时使用首个结果的
任务配置；需要改变格式时优先使用此命令，避免修改任务后重新运行整个提取流程。

同一问题、字段定义、类型和规则的结果，可以来自不同文献范围或处理模式后合并导出；
例如一篇用 parsed，另一篇用 direct。每条记录保留原结果/材料身份，CSV 也保存
result_id；不会因为字段同名就合并不同含义。同一来源 ID 对应不同 PDF 哈希时拒绝
合并。原文入口重新检查本地 PDF 哈希，原文件已变化时显示定位提示。

人工修改科研结果时，复制目标记录的完整对象到 revision.json 的 replacement；
同时填写 record_id、author、at、reason、confirm（布尔值）。运行：

```powershell
aletheia-nexus research revise paper1.result.json revision.json --output paper1.revised.json
aletheia-nexus research export paper1.revised.json --output-dir revised-export
```

修订结果含父结果 ID、修改前内容和理由；confirm=true 是用户对整条记录的明确确认。
模型响应契约没有人工确认字段。输出目标已存在时拒绝覆盖；原始 PDF、sidecar 和
规范解析工件也受到已有写入保护。

单篇摘要中的独立主张和跨文献结论也可用同一 revise 命令修订：把 record_id 换成
claim_index（从 0 开始，对应原结果 response.claims 的位置），replacement 填完整
的 text、nature、citations 对象，其余 author、at、reason、confirm 要求相同。
修订仍检查引用；后续以 confirm=false 改写会撤销该主张的人工确认，不影响未改动的
记录或其他主张。请只在实际完成人工核对后设置 confirm=true。

AI生成的诊断也可能错误。例如模型读错符号后，可能把问题归为“原文歧义”。可用
`issue_index`（从0开始，对应response.issues）定位诊断，replacement填写完整的
kind、detail、source_id、page对象，通过同一revise命令保存新版本。诊断修订的
confirm必须为false；只替换选中诊断，不删除或重排索引，旧诊断保留在history中。
它不会自动改动相关字段或主张；这些内容应分别修订，防止表格和摘要不一致。

所有修订可声明`authority`为human或assistant。为兼容既有人工修订文件，省略时
按human处理；助手或脚本产生的模型复核必须显式填写assistant，并设置confirm=false。
带assistant来源的修订不能申请人工确认；它修改的记录/主张仍保留待核对或证据
不足状态。若原记录曾由人工确认，后续助手改写会撤销该记录的确认，其他未改动
记录不受影响。authority记录修订来源，不是账号认证或科学正确性的保证。

诊断修订示例（示例数据，需按实际原文填写）：

```json
{
  "issue_index": 0,
  "replacement": {
    "kind": "strategy_problem",
    "detail": "原页中的近似号被模型误读为负号；相关字段另行修订，旧读法保留。",
    "source_id": "paper1",
    "page": 1
  },
  "authority": "assistant",
  "author": "执行原文复核的助手",
  "at": "2026-10-26",
  "reason": "复核所选原页后修正错误归因；不是人工确认。",
  "confirm": false
}
```

## 当前验收边界

自动化测试验证工程行为，不能证明领域正确率。真实 API 连通测试、开发集论文结果、
助手原页复核、真正人工标注和独立留出评测必须分别记录。20–30 篇/100 字段/40 记录
的正式评测完成前，不承诺查准率 90% 或支持率 95%。另见 [设计与审计](V08_DESIGN.md)。
评分定义和评阅文件格式见 [评测口径](V08_EVALUATION.md)，实际执行见
[验收记录](V08_ACCEPTANCE.md)。
