# v0.8 开发版：中文科研入口与本地 MCP

本功能位于 `feat/v0.8-extraction`，尚未正式发布。两个入口共用
`ResearchApplication → research-task/v1 → run_task → export_results`。
规划只决定要整理什么，科研提取才读取论文；计划不是已核实的科学结论。
代码 `8e3e82b` 的实际CLI、官方SDK协议与工程验收已完成；科研成绩和最终边界见
[交付报告](V08_DELIVERY_REPORT.md)。下方命令适用于开发版，不表示已经发布正式版本。

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

计划中的图片列表是初始输入。`hybrid` 可在已选文献、补充轮次、图片数、调用和费用预算内
按模型请求补读同一PDF的原页；不自动下载或绑定新SI。补页建立新的来源包和材料指纹，
原PDF及旧工件保持原样。

默认科研上限为10次HTTP、估算2 CNY；规划单独最多2次、估算0.5 CNY。
可设 `--max-calls`、`--max-cost`、`--planning-max-cost`，或用 `--model-config` 指向
既有 MODEL 契约配置。单价/用量估算不是账单，未知用量保留预留额。
没有 Key 时明确报错；既有手工任务仍可用 `research run`，不会假装理解自然语言。

当前执行策略为 `direct` 与 `source_first`。`field_independent` 经新论文复验后已退役，
旧任务直接执行会明确拒绝；历史结果仍可读取、核验、修订和导出。另存任务并显式选择
可用策略后，需重新预览和授权，程序不会静默替换旧策略。

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

### 输入超限时显式调整

默认请求字符上限为100000；加载任务时保留其已有值。先读成功后，加入首读稿可能才使
组装超限。程序会先尝试可逆编码，仅省略重复默认标记，不删除正文、读法或图片；仍超限
则显示文献和 `input_budget_exceeded`，保留已完成的首读与原失败记录。

需要更大输入时，无需手写JSON或重调规划API：

```powershell
aletheia-nexus research ask --papers "F:\papers" --output-dir "F:\results\an08" --task "已保存的task.json路径" --max-input-characters 200000 --non-interactive --save-only
```

该参数须为正整数；程序另存任务副本并显示新计划指纹。使用新打印的任务路径和指纹，
再按上面的执行命令批准。旧指纹不能批准变更后的预算；论文范围、费用和调用次数上限
保留原值。省略该参数不会自动增加输入限额；新自然语言任务也可显式使用同一参数。

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
| `list_documents` | 列举PDF；`catalog=true`读取既有文库标签、父文关系与完整性，支持folder/tag/query筛选 | 否 |
| `update_document_tags` | 增删工作区PDF副本的文库标签，保留来源与解析证据 | 否 |
| `find_paper_candidates` | 按题名/书目查询最多5个Crossref候选；需选择DOI后另行获取 | 需独立discover许可；不调用AI |
| `get_acquisition_status` | 读取既有获取/登记状态，可对明确指定PDF核验当前完整性与身份依据 | 否 |
| `acquire_documents` | 公共DOI批量获取、身份验证与断点恢复；返回异步job_id | 需独立公共获取许可；不调用AI |
| `prepare_documents` | 准备明确选择的PDF，隔离失败，在工作区建副本 | 否 |
| `prepare_documents_job` | 在后台准备明确选择的PDF，返回job_id并复用有效解析 | 否 |
| `import_local_document` | 用明确元数据登记主文或显式指定父文的SI副本；仅为DECLARED | 否 |
| `parse_document` | 对已登记文献显式生成独立的新解析工件，保留旧版 | 否 |
| `draft_research_task` | 直接验证客户端任务；或从自然语言规划 | 只有自然语言分支需规划许可 |
| `validate_research_task` | 校验来源/字段/预算，返回计划及批准请求 | 否 |
| `execute_research_task` | 现有引擎异步执行，返回job_id | 科研模式需独立许可 |
| `get_run_status` | 查询状态、错误、原生清单和费用 | 否 |
| `export_research_results` | 重导出兼容结果为Markdown/CSV/JSONL | 否 |
| `search_documents` | 对选定文献做已有表格/图注感知检索，保留覆盖情况 | 否 |
| `read_native_table` | 本地读取明确选定XLSX的原生单元格与范围，保留来源及读取限制 | 否 |
| `read_document_context` | 读取完整原页上下文、表格、图注和位置 | 否 |
| `read_original_page` | 返回原页图片；可按显示页归一化坐标放大指定区域，保留来源/范围 | 否 |
| `read_original_page_text` | 读取选定原页的PDF文字层，保留列对齐空白、来源与截断状态，不要求已有解析工件 | 否 |
| `get_parse_diagnostics` | 查看解析质量、失败诊断和当前来源核验 | 否 |
| `read_research_result` | 读取既有字段、引用、验证和修订历史 | 否 |
| `revise_research_result` | 显式助手修订一个既有记录/主张/诊断，独立保存并导出，始终不确认为人工审阅 | 否 |
| `list_research_runs` | 查看本地历史运行与已记录费用，kind区分科研与获取 | 否 |

读取工具会把允许目录中的内容返回给宿主客户端；宿主自身模型是否向远程发送内容，
由该客户端的隐私与批准机制负责。AN 的 `--enable-remote` 控制的是 AN 自己的模型调用。
检索直接复用 v0.7 的表格/图注内容单元和证据包，不把字面未命中解释为科学事实缺失。
`read_document_context` 超出字符预算时明确跳过完整上下文，不截断表头或悄悄漏行。
跨盘的手工PDF/工件组合需先 `prepare_documents` 在工作区准备，再进行文库检索。

### 读取原页的布局文本

可以说：“读取这篇论文第12页的原生文字层，保留表格列对齐；疑问处再给我原页图片。”
客户端调用 `read_original_page_text(document, page=12)`，`document` 沿用登记或准备工具
返回的文献对象。无需解析、Poppler、OCR或API Key；只访问已允许目录中的指定PDF。
这也适合需要文字输入的客户端，原有 `read_original_page` 图片接口继续可用。

结果的 `text` 是 pypdf 从PDF文字层派生的布局文本，保留空间对齐的空白和换行；同时返回
原PDF身份、物理页码、提取引擎/版本、文本哈希和稳定派生标识。它不会改原PDF或既有规范
解析工件，也不会自动进入AN的科研模型输入或改变默认提取策略。

默认最多返回40000字符，可用 `max_characters` 调整为1–200000。`text_truncated=true`
表示只交付开头片段，`total_characters` 给出该次提取的总长度；需要完整上下文时增大限制
或读取原页图片。该字符限制与 `read_document_context` 的整段预算策略不同。
`has_native_text=false` 只表示本次没有得到文字层内容，不能据此判定论文未报告所需信息。

布局文本仍可能有字形编码、旋转和阅读顺序问题；图像、曲线、图例之间的关系不会因提取
文字而自动读懂，跨页表头也不自动补齐。可读的列对齐是另一种原文读取视图，不代表表格
或科学关系已经正确理解。宿主客户端如何使用返回内容，仍遵循上方的客户端隐私边界。

### 放大原页的局部区域

可以说：“放大这页的双纵轴子图，把两个轴、系列标记和必要图例都包括进来。”
客户端先读取整页，再调用同一工具的可选参数
`read_original_page(document, page=7, region=[0.4, 0.45, 0.65, 0.7])`。
这里是坐标用法示例，不能据此推断任意论文的图都在该位置。

`region=[左,上,右,下]` 的值为0–1，相对于**完整、已显示旋转方向的PDF CropBox**，
左上角为原点；不是相对于上一次裁剪图片。结果用3200长边的原页栅格生成，返回实际
像素取整后的范围、原请求范围、原页栅格尺寸、像素区域及图片哈希。原PDF保持只读。
不传 `region` 时仍返回原来的整页视图，不改变普通科研任务的图片输入。

选区可以漏掉图例、共享表头、轴或脚注；合法坐标不保证上下文充分，也不确认科学含义。
必要时回到整页或扩大选区。此接口只提供可追溯的源区域读取，AN当前科研请求契约仍只
自动补页，尚未默认启用模型自主选区、图像纠错或新的多轮提取策略。

### 经批准获取公共全文

默认不启用获取。需要此能力时启动：

```powershell
aletheia-nexus mcp serve --allow-dir "F:\papers" --workspace "F:\results\an08" --enable-acquisition
```

或复制 [公共获取 stdio 配置](../examples/mcp-stdio-windows-acquisition.json)，修改绝对路径。
使用 `start_an_mcp.ps1` 时增加 `-EnableAcquisition`；它与 `-EnableRemote` 分开，
公共下载不需要 DeepSeek Key，也不授予模型调用权限。

在客户端说：“获取 DOI 10.1371/journal.pone.0310216，核对来源后准备解析，先给获取计划。”
客户端调用 `acquire_documents(papers=[{"doi":"10.1371/journal.pone.0310216"}])`。
每篇可附 `title` 作为身份约束，每批最多10篇；仅有题名时先通过`find_paper_candidates`
查询并选择DOI。本工具不自动获取SI或登录机构。
这些既有 CLI 能力尚未全部封装进 MCP，公共获取失败不会自动打开浏览器、使用官方凭据或扩大权限。

工具先返回中文范围和 `authorization_request` 文件，不联网。按本节下方的
`research authorize` 命令在独立终端审阅后，将一次性授权交给当前工具的 `authorization`。
批准绑定 DOI/题名、允许目录、固定的公共路径限制和恢复断点；不能用 `confirmed=true` 代替。
原规划/科研授权不能用于获取，获取授权也不能用于 AI。授权仅使用一次。

批准后返回 `job_id`，通过 `get_run_status` 查看逐篇结果与本地 `pdf`/`sidecar`。
服务端复用已有批量获取、PDF/身份验证及断点机制，每篇最多4条路线与4个文件候选；
路线/文件请求超时30秒，各路径/文件最多尝试1次。`COMPLETED/PARTIAL/FAILED`
区分全成、部分和未交付，公开路径原状态与异常类型分别保留。后台执行不会占住stdio请求。
成功文件可直接交给 `prepare_documents`，保留下载来源记录，不降格为人工声明或覆盖旧PDF。

恢复失败或中断时，用同一 `papers` 加 `resume_job_id` 再请求计划、重新批准。
恢复写入新任务目录：复制并复核已验证文件，只重试失败项；旧断点、PDF、来源与历史不改。
原任务仍运行时不能恢复；断点改变后旧批准失效；已有损坏断点明确报错。
若进程在首个断点前退出，计划明确说明从头获取选定范围，不自动信任遗留文件。

公共获取工具覆盖公共主文；题名可先用`find_paper_candidates`查询候选，核对后另行授权获取。
候选顺序不代表身份确认；机构会话仍复用原CLI的人机协作，不启用公网服务。
本次用官方SDK2.3.0真实stdio客户端完成模拟网络的授权/恢复/解析测试；另实际下载并
核验上述公共 DOI、准备12页解析成功，模型调用0。再以新服务进程、不可用HTTP代理恢复，
有效文件复用、获取尝试0，原PDF/来源记录/断点哈希不变。真实桌面 AI 客户端中的手工会话仍另行验收。

### 获取记录与当前来源检查

`get_acquisition_status(sidecar="F:/papers/json/paper.acquisition.json")` 可查看既有
获取记录，包括 `AUTH_REQUIRED` 等未交付状态；不要求存在解析工件或成功下载的PDF。
只读记录时 `current_check.status=NOT_CHECKED`，历史 `VERIFIED` 不能证明当前文件仍完整。

显式加入 `pdf="F:/papers/paper.pdf"` 后，复用现有来源门禁检查哈希、页数、记录状态和身份。
可同时给 `expected_doi` 核对预期DOI；不提供PDF时不能要求此项核验。
返回值分开保留 `recorded_status` 与 `current_check`，例如旧记录仍为 `VERIFIED`，当前
检查可能是 `FAILED/PDF_HASH_MISMATCH`。本地登记即使通过完整性检查也仍为
`REGISTERED/DECLARED`、`identity_verified=false`；检查通过不等于科学内容正确。

本工具不会跟随记录里的文件路径或URL、不重试获取、不写入或升级来源记录；PDF和sidecar
都必须处于本地配置允许范围。它没有 `confirmed` 或远程授权参数。公共DOI下载可使用
`acquire_documents` 的独立获取许可；机构会话仍需既有获取CLI及其访问设置。

### 显式助手修订结果

先用 `read_research_result` 读取结果，保留目标完整结构。调用
`revise_research_result(result="结果JSON路径", revision={...})` 时，`revision` 必须包含：

- 恰好一个既有目标：`record_id`，或从0起的 `claim_index` / `issue_index`。
- `replacement`：该记录、主张或诊断的完整替换对象；记录ID不得改变。
- `reason`：非空修订理由。

它复用现有修订及引用校验，不调用AI、下载或读取新的页，也不修改任务、来源包或原始文件。
结果所绑定的PDF、来源记录和规范解析工件须仍在允许目录内且与保存的身份一致。
来源缺失或改变时明确失败，不通过改路径/重解析偷偷迁移旧引用。

服务端固定 `authority=assistant`、`confirm=false`，写入UTC时刻和MCP握手中的客户端名称/版本。
工具不接受调用者提供的 `author`、`at`、`authority`、`confirm`；客户端自报名称仅作历史归属，
不是身份认证或人工批准。修订目标保持待核对，未改目标原有的人工审阅状态按现有规则保留。
不支持新增/删除记录、主张或诊断，也不编辑补充请求；每次仅修订一个既有目标。

新版本位于工作区 `revisions/<唯一ID>/result.json`，父结果、PDF和旧解析工件不覆盖。
完整JSON包含逐次修订理由、替换前内容和父结果ID，可再次读取、复制或导出；同目录同时生成
既有Markdown/CSV/JSONL科研资料导出。表格导出不是完整历史的替代，追溯请保留JSON。
本入口只校验结构、来源和引用位置，不能保证修订的科学内容正确。

### 明确登记与新版本解析

本地主文还没有来源记录时，可调用
`import_local_document(pdf="F:/papers/paper.pdf", title="论文标题", doi="10.xxxx/...")`。
DOI可省略；调用者提供的元数据仅记为 `REGISTERED/DECLARED`，不冒充下载验证。
导入在工作区保留PDF副本、原路径及文件名，返回 `document`；它不会覆盖原PDF或原来源记录。
已有登记/获取记录请用 `prepare_documents`，保留其来源记录。新SI可显式调用
`import_local_document(pdf="F:/papers/SI.pdf", title="补充材料", role="SUPPLEMENT", parent={"pdf": "主文PDF路径", "sidecar": "主文来源记录路径"})`。
父文必须是已登记或已验证的独立主文；SI不另填DOI，其引用随父文保留。父文归属仍为调用者的
`DECLARED`声明，不代表官方关联已验证；不按文件名猜测关系，也不接受 `confirmed`。

查既有文库时复用 `list_documents(directory="工作区路径", recursive=true, catalog=true, tag="待读", query="关键词")`；
`folder`按目录相对路径筛选。目录下未登记PDF仍用默认列举方式查看。
对工作区副本调用 `update_document_tags(pdf="副本PDF路径", add=["待读"], remove=["已读"])` 可增删标签。
仅标签文件可变，PDF、来源记录和解析证据保留；`--allow-dir`只授予读取权限，外部原库标签不会被修改。
题名公共发现需单独`discover`许可，不能复用`acquire`许可；机构登录/验证码会话继续走
既有获取CLI及其访问设置，公共DOI获取权限不因此扩大。

将返回的 `document` 交给 `parse_document(document=..., max_pages=2000)`，可显式用当前解析器
创建新版本。每次写入唯一的 `*.parsed.json`，可被现有 `load_corpus` 文库扫描；不会改名或覆盖
旧规范工件。`prepare_documents` 继续读取旧 `parsed-UUID.json`，也不会仅因解析器升级重新解析。
明确选择新版本时使用返回的 `document`；旧引用和旧结果仍绑定原工件。

默认采用原生文本；`ocr=true, ocr_languages="eng"` 才开启已有的本地原生优先选择性OCR，
依赖Poppler/Tesseract及已安装语言数据，不下载模型。工具不开放可执行文件路径等配置。
原生新版本不会替换既有OCR版本。返回真实 `status`、`parser`、`quality`、`warnings`、`errors`
及所用选项；页数上限、OCR缺依赖或不足材料可能得到 `PARTIAL/FAILED`，不能当成完整解析。
调用为同步本地操作；大文件/OCR可能较慢，可设置客户端超时或继续使用既有解析CLI。

解析器3.10.21补充识别 `Supplementary Figure/Table` 标题，主文和补充图表的同号标题
分别保留。旧工件不会自动升级，可通过 `parse_document` 保存独立新版本。标题可定位
仍不代表表格关系正确：实际SI中仍发现拆分小数和错列，密集表应使用 `read_original_page`
查看原页，或在科研任务 `image_pages` 中明确加入相应页面；保留原始值和不确定性。

客户端已有模型时，可直接生成任务并验证，不必再调用 AN 规划API。只有自然语言目标时，
AN先返回规划许可请求。元数据和论文内容不会因模型传入 `confirmed=true` 自动发送。

远程批准返回本地请求文件。你在独立终端运行：

```powershell
aletheia-nexus research authorize "返回的authorization_request路径"
```

核对范围和预算，确认后将一次性授权交给当前 AN 工具。规划、科研和公共获取授权相互隔离；
任务、源文件、预算或目录改变后重新批准；任务原已允许的同文献预算内补页沿原许可执行。
授权一小时内有效，使用一次即失效，MCP没有
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
`research/runs/` 是原生科研结果与来源包，`exports/` 是重新导出，`revisions/` 保存独立修订版本及导出。
`PARTIAL`、诊断和AI判断不会变成人工确认。

工程通过不等于科研准确率提升。真实模型、客户端、失败、用量与局限见验收记录；
真实SDK协议测试与桌面AI客户端手工会话测试分别说明，不互相替代。

### 当前版本实际执行记录（2026-10-30）

实际使用一份中文文件名的12页原始PDF，输入“研究对象、采用的方法、作者报告的主要结果”
三个字段的中文目标，规划API调用1次。主智能体依照用户既有授权，在本机复核保存的计划、
范围和预算后执行；这不是人类当场点击计划的记录，也不把科研结果标为人工已确认。

首读完成后，组装请求103776字符超过100000上限，第一次运行明确失败。修复后以同一任务
复用原首读，按可逆编码缩至89441字符；随后模型请求补读同一PDF第6–10页共5幅原页图，
使用已有的1轮补充和最多6图限制。科研总计4次HTTP、估算1.08986816 CNY（含首次失败的
首读），未提高原4次/3 CNY预算。规划另估算0.015262 CNY；两项均为配置单价估算。
最终得到1条记录、3个中文字段及Markdown/CSV，状态保留 `PARTIAL`，不代表全部科学内容正确。

另以官方Python SDK 2.3.0的独立stdio服务进程发现23个工具：经本地独立授权执行同一任务，
实际缓存命中且模型HTTP为0；再启动无密钥服务查询文献、诊断和历史、读取结果并重导出
Markdown/CSV/JSONL，同样0模型HTTP。原PDF和规范工件哈希不变。这是实际协议调用，
没有声称在某个桌面AI宿主中完成手工对话，也没有把直接调用Python函数算作MCP验收。

当前代码全量工程测试2763通过、0失败、119跳过；其中111个headless用例已有真实通过记录，
对应源码和测试Git子树与当前相同，按哈希复用未重复运行。另8个为可见浏览器2、真实OCR2、
Windows符号链接权限4，未执行。当前wheel构建、安装和SDK本地烟测通过；新私有环境显式
复用已有依赖，不属于全新联网依赖安装。完整交付与科学结果见[最终交付报告](V08_DELIVERY_REPORT.md)。
