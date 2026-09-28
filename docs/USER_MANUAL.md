# Aletheia Nexus 使用说明书

本手册面向需要按 DOI 获取、核验并批量保存论文正文 PDF 的研究人员。`v0.6.1` 新增正式 CLI 与 PyPI 安装入口；实际可安装版本以 [PyPI 项目页](https://pypi.org/project/aletheia-nexus/)为准。AN 的目标是尽可能使用公开路径、已授权的官方 API 和用户自己的浏览器会话获取文件；只有 PDF 结构、论文身份和正文角色都通过检查，才标记为 `VERIFIED`。AN 不提供订阅权限，也不会代替用户输入密码、MFA 或验证码。

## 1. 环境与安装

要求 Python 3.11 或更高版本。Windows PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install aletheia-nexus
aletheia-nexus doctor
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir downloads/first-paper
```

公开 HTTP 路径无需浏览器依赖，单 DOI 的 `--public-only` 可以用于首次体验；外部来源不能提供可信正文时会如实返回非成功状态。需要交互式浏览器时，再执行 `python -m pip install "aletheia-nexus[browser]"` 和 `python -m playwright install chromium`。开发者从仓库根目录执行 `python -m pip install -e ".[dev,browser]"`。如果 PyPI 项目页尚未显示目标版本，不要误以为仅有 GitHub Release 就代表上传成功。正式使用时可将输出目录放在仓库外，以便代码与下载文件分开管理。需要联网访问 DOI、元数据服务和出版社；机构授权仍由出版社和当前账号决定。浏览器使用独立的持久配置目录，可能包含登录状态，应像账号资料一样保护，不要提交或分享。

## 2. 准备 DOI 清单

批量命令支持以下三种输入：

- `.txt`：每行一个 DOI；空行与 `#` 开头的注释行跳过。
- `.json`：字符串或包含 `doi`、可选 `title` 的对象组成的列表。
- `.csv`：`doi` 列，可选 `title` 列。

推荐为困难论文提供准确标题。标题可帮助 AN 区分正文、补充材料以及网页指向的错误论文；特别是 PDF 内未印 DOI、标题文字提取错乱、或需要导入已有文件时。

```json
[
  {"doi": "10.1021/example", "title": "The Exact Article Title"},
  "10.1038/example"
]
```

真实 DOI-only 输入可参考仓库里的 [`benchmarks/user_20260923_20_with_titles.json`](../benchmarks/user_20260923_20_with_titles.json)（仅 2 篇附显式标题）；如需可重复的获取层测试，请用全部 20 篇都固定 DOI、准确标题、出版社和年份的 [`benchmarks/user_20260923_20_frozen.json`](../benchmarks/user_20260923_20_frozen.json)。`publisher` 和 `year` 是基准集的记录字段，当前批量 CLI 使用 DOI 与 `title`，不会把它们当作访问凭据。两份输入的 DOI 会标准化并去重；若要保留重复项，使用 `--keep-duplicates`。详情见 [`benchmarks/README.md`](../benchmarks/README.md)。

## 3. 最常用的批量运行方式

以下命令在可见浏览器中顺序处理论文。若登录、MFA 或 CAPTCHA 被识别，AN 会暂停在页面上；用户完成后自动续跑。不传 `--interaction-timeout` 时没有预设等待上限。

```powershell
aletheia-nexus acquire dois.json `
  --output-dir downloads/my-batch `
  --cdp-endpoint http://127.0.0.1:9222 `
  --cdp-navigate
```

当指定的本机调试端点尚未运行时，CLI 默认自动启动 AN 专用 Edge/Chrome，使用持久配置目录，逐篇打开页面。同一个浏览器会话会复用有效的 cookie 与机构认证状态；AN 不会读取、打印或写入 cookie 值。`--cdp-navigate` 表示批量任务逐篇导航；不加时会优先尝试接管当前已打开的匹配论文标签。专用浏览器默认强制直连；若普通浏览器依靠 Windows 系统代理而 AN 持续落入验证页，可在知晓认证流量也会经过所配置代理后，显式加 `--browser-use-system-proxy`。该选项只影响新启动的 AN 浏览器；附加到已运行的 CDP 浏览器时，网络设置仍由该浏览器决定。

Windows 上若 AN 自带的 Playwright 浏览器反复遇到验证、但普通 Edge 能打开同一篇论文，可先用**单篇 DOI**试下面的独立 Edge 路径（仅在信任当前系统代理时保留最后一个参数）：

```powershell
aletheia-nexus acquire 10.1039/D6TA02244H `
  --output-dir downloads/edge-check `
  --profile my-institution `
  --cdp-endpoint http://127.0.0.1:9222 `
  --cdp-navigate `
  --browser-use-system-proxy `
  --interaction-timeout 180
```

AN 会在该本机端口未被占用时启动独立 Edge，不修改日常 Edge；若端口已有浏览器，则会附加到现有会话，运行前务必确认那是你期望的 AN 浏览器。调试端口只应绑定本机，使用完毕关闭该专用浏览器。这个方式不会绕过验证码或保证出版社放行。

未指定 `--cdp-endpoint` 时，AN 使用安装的 Playwright Chromium 与专用持久配置；指定端点时才可能自动启动本机 Edge/Chrome。默认配置名为 `human-handoff`，目录在用户主目录的 `.aletheia-nexus/browser-profiles/` 下。若需隔离不同机构或账号，分别使用 `--profile NAME`；需要自定保存位置时用 `--profile-root DIR`。若 CDP 端点已经有浏览器在运行，AN 会附加到那个现有会话，**单改 `--profile` 不会切换它的实际配置**；机构隔离还应使用各自的浏览器进程与端口。不要把专用配置目录当作普通报告共享或上传。已自行启动并附加的 CDP 浏览器保持其原有网络设置；AN 不会修改该浏览器的代理。

如需无人值守运行（不等待人工登录或验证码）：

```powershell
aletheia-nexus acquire dois.txt `
  --output-dir downloads/unattended `
  --non-interactive
```

`--non-interactive` **不会禁用浏览器或官方 API**：已经有效的授权会话仍可能被复用，也可能自动打开浏览器；它只禁止等待人工操作。无人值守不等于绕过登录。遇到需要账号、订阅或验证的站点，AN 会记录相应状态；若站点未给出可识别的访问提示，也可能是 `EXHAUSTED`，需要查看报告诊断。若上层脚本要求每个有效 DOI 都成功，请再加 `--fail-on-unverified`。

当 OpenAlex 候选包含 PMC 记录时，AN 会先查询 PMC Article Datasets 的官方 AWS 公共数据桶，并优先验证其中的 PDF。该路径适配了 PMC 于 2026 年 8 月完成的数据分发迁移，不抓取 PMC 文章网页，也不依赖已下线的旧 OA Web Service。若文章不属于可自动获取的数据集、没有 PDF、已撤回，或元数据 DOI 不一致，AN 不会把该对象当作候选。

### 常用开关

| 参数 | 用途 |
| --- | --- |
| `--output-dir DIR` | 保存 PDF、逐篇记录、检查点和批次报告。 |
| `--cdp-endpoint URL` | 连接本机 AN 浏览器调试端点。 |
| `--cdp-navigate` | 为批次逐篇导航，不强行复用当前标签。 |
| `--profile NAME` / `--profile-root DIR` | 隔离并保存特定机构或账号的浏览器状态。 |
| `--no-start-browser-if-needed` | 本机 CDP 端点不可用时不自动启动 Edge/Chrome。 |
| `--browser-use-system-proxy` | 新启动的 AN 浏览器采用操作系统代理设置；默认仍强制直连。代理可能接触站点请求和认证会话，请只在信任当前代理时启用。 |
| `--interaction-timeout N` | 最多等待人工登录/验证 N 秒；省略则持续等待。 |
| `--stop-on-interaction` | 当前 DOI 仍需交互时停止整批；默认继续后续 DOI。 |
| `--non-interactive` | 无人值守，不等待人工登录或验证码。 |
| `--no-resume` | 不复用检查点，重新尝试所有输入。 |
| `--local-pdf DOI=PATH` | 导入已有 PDF，并重新执行完整验证。可重复传入。 |
| `--manual-ieee-fallback` | 交互式终端中 IEEE 自动获取失败时，才提示输入用户自行保存的本地 PDF 路径。 |
| `--keep-unverified` | 保留未通过正文身份验证的 PDF，便于诊断。 |
| `--fail-on-unverified` | 任意有效 DOI 未 `VERIFIED` 时以非零状态退出。 |
| `--unpaywall-email EMAIL` | 为适用的开放获取发现服务提供联系邮箱。 |
| `--cnki` / `--no-cnki` | 启用或关闭 CNKI 浏览器 Provider；默认启用。 |
| `--cnki-all-titles` | 对所有未获取文献尝试 CNKI，包括登记元数据仅有英文标题的论文。 |
| `--cnki-max-results N` | CNKI 标题/作者匹配时检查的最大结果数；默认 5。 |

所有参数可运行 `aletheia-nexus acquire --help` 查看；旧 `scripts/batch_v06_download.py` 保留兼容入口。遇到慢站点可以适度增大 `--base-timeout`、`--request-timeout`、`--max-source-routes` 和 `--max-pdf-candidates`；预算增加会延长批次运行时间，不能创造未获得的订阅权限。

## 4. 登录与机构选择

1. AN 打开论文或 PDF 的可见浏览器页面。
2. 若出现机构选择、登录、MFA 或验证码，用户在该浏览器内完成。
3. AN 只观察页面，不在等待循环中主动刷新。验证提示消失后须连续数次保持可用状态；AN 优先读取浏览器已收到的 PDF/下载，必要时才对同一目标作一次受限重试，然后继续后续论文。

Elsevier 等站点可能按网络 IP 自动推荐机构。即使 AN 复用同一浏览器配置，出版社仍可能重新选择机构。若自动选中的机构没有该期刊权限，请在网站提供的入口切换至有权限的机构；AN 不修改系统代理或伪造机构身份。切换成功后的 cookie 可能被复用，但不保证永久有效。

如果确认没有订阅权限，可以关闭当前挑战页面，或设置有限的 `--interaction-timeout N`；当前 DOI 可结束为 `INTERACTION_REQUIRED`，默认继续后续 DOI。这与“已确认无权限”的人工判断应分别记录，不要把没有完成的登录自动解释成 `ENTITLEMENT_REQUIRED`。`Ctrl+C` 会中断整个命令：之前已写入检查点的论文仍可在下次复用，但本次完整 `batch-report.json` 不保证更新。若出版社明确显示购买或无权限页面，AN 才可能自动归类 `ENTITLEMENT_REQUIRED`。

IEEE DOI 也进入同一浏览器流程。出现已记住的 “Access Through …” 机构按钮时，AN 会尝试点击、等待约 5 秒并重试 PDF；账号密码、MFA 和其他人工验证仍由用户完成。所有文件都受同样的正文验证规则约束。

### CNKI（中国知网）

公开来源和适用的官方接口失败后，浏览器 Provider 会对元数据标题含中文的论文尝试 CNKI。它先复用 Crossref/DataCite 已解析的标题与作者，按标题检索并用作者辅助排序，打开详情页时捕获新标签，只选择明确的 PDF 下载控件；CAJ 链接不会作为 PDF 保存。下载结果仍须通过统一的 PDF 结构和 DOI/标题身份校验，成功文件的 sidecar 会记录 `cnki_authenticated_browser`、来源页和 SHA-256，但不记录 cookie 或凭据。

默认配置不会让每篇外文文献都访问 CNKI。需要显式扩大范围或完全关闭时，可在 Python API 中设置：

```python
BrowserAccessConfig(
    cnki_enabled=True,
    cnki_search_all_titles=True,  # 默认 False，仅自动处理中文标题
    cnki_max_results=5,
)
```

若出现知网滑块或验证码，AN 不代答、不模拟拖动；可见浏览器会等待用户操作，并通过 `interaction_callback` 报告 `CAPTCHA`。超时或禁用交互时结果为 `INTERACTION_REQUIRED`。是否能够下载 PDF 仍取决于当前校园网、机构 VPN、登录会话与订阅范围；只有 CAJ 或无 PDF 权限时不会伪装成成功。

## 5. 断点续跑与文件核验

每次批次会在输出目录写入：

```text
downloads/my-batch/
  batch-checkpoint.json
  batch-report.json
  <doi-slug>-<hash>.pdf
  <doi-slug>-<hash>.acquisition.json
```

再次执行相同命令时，AN 只直接复用仍存在且 SHA-256 与检查点一致的 `VERIFIED` 文件。其他状态都会重新尝试。不要手工把未核验 PDF 改名冒充成功文件；检查点不会因此信任它。成功 PDF 的 `.acquisition.json` 保存来源、PDF 结构、DOI/标题匹配与正文/附件判断，但会对短期签名 URL 脱敏。检查点不保存 cookie、token、URL 或异常消息。

`batch-report.json` 的 `items` 给出每篇 `status`、`verified_path`、是否 `resumed` 和安全诊断；`status_counts` 是当前这一次运行的统计。若要把多个独立复测合并成一个语料结果，应按 DOI 去重并保留每次运行的报告，不要将单篇复测冒充为一次完整批次。

默认退出码 `0` 只表示批次正常处理结束，**不表示全部论文都已 `VERIFIED`**。退出码 `2` 表示至少一篇出现 `RUNNER_ERROR`，`3` 表示配置为遇到交互就暂停而批次已暂停，`4` 表示使用了 `--fail-on-unverified` 且有有效 DOI 未验证成功。无效 DOI 仍需在报告中逐项检查。不要仅凭进程退出码或 PDF 文件名判定科学验证成功。

### 如何理解状态

| 状态 | 含义与下一步 |
| --- | --- |
| `VERIFIED` | 有可解析 PDF，目标论文身份及正文角色通过验证。 |
| `INTERACTION_REQUIRED` / `AUTH_REQUIRED` | 需要或未完成用户登录、机构认证、MFA、验证码等；完成后续跑。 |
| `ENTITLEMENT_REQUIRED` | 出版社明确显示当前会话缺少正文授权；换有权限的合法账号后再试。 |
| `ACCESS_DENIED` | 站点拒绝访问或明确封锁请求；检查网站状态与正常访问条件。 |
| `EXHAUSTED` | 已尝试路径但没有验证成功，不等同于无权限；查看 `diagnostics`。 |
| `BROWSER_UNAVAILABLE` | 浏览器未启动、无法连接或调试连接超时。 |
| `UNSAFE_URL` / `INVALID_DOI` | URL 不符合安全约束，或 DOI 输入无效。 |
| `RUNNER_ERROR` / `ERROR` | 程序或单篇流程异常；保留报告并复现。 |
| `DEFERRED` | 按配置在交互节点停止后尚未处理的后续 DOI。 |

`RETRIEVED_UNVERIFIED`、`SUPPLEMENT`、`INVALID_PDF` 等可能出现在逐篇诊断中；它们不是成功文件。尤其是同一 DOI 的免费补充材料不能替代正文。AN 的首页标题规则允许处理 PDF 提取器连写标题的情况；若只在后续页面找到目标 DOI，且首页没有匹配标题，也不会标记 `VERIFIED`。

## 6. 已有 PDF 与官方 API

合法取得 PDF 后，可以用 `--local-pdf "DOI=C:\path\paper.pdf"` 导入。AN 复制原件，重新核验，不修改来源文件。若 PDF 不印 DOI，建议在 JSON/CSV 输入中同时提供准确 `title`；否则身份信息不足可能返回未验证状态。

Elsevier 官方 Article Retrieval API 是可选路径。凭据只通过环境变量提供，不写入命令行、仓库或报告：

```text
ELSEVIER_API_KEY
ELSEVIER_INST_TOKEN      # 可选
ELSEVIER_BEARER_TOKEN    # 可选
```

没有密钥时仍可运行公开路径与已授权的浏览器路径。`--no-elsevier-api` 可关闭 API 自动发现。AN 不尝试绕过订阅、CAPTCHA 或访问控制。

## 7. v0.7 带来源内容解析

解析器只接受已有 `.acquisition.json` 的 `VERIFIED` 正文 PDF。它在运行前重新检查来源记录版本、正文状态、DOI、PDF SHA-256、可读性和页数，不会从检查点猜测证据，也不会在解析阶段重新下载文件：

```powershell
aletheia-nexus parse downloads\paper.pdf --doi 10.1234/example
```

默认输出与 PDF 同目录、同文件名的 `.parsed.json`，原 PDF 与 `.acquisition.json` 保持不变。需要显式路径时使用 `--sidecar` 和 `--output`。已有输出默认视为冲突，不会静默覆盖；只有明确使用 `--overwrite` 才会替换。批处理或 CI 若不允许降级结果，可加 `--fail-on-partial`；输入门失败退出码为 `5`，`PARTIAL`/`FAILED` 在该选项下退出码为 `6`。

输出 schema 为 `aletheia-nexus/parsed-document/v2`；未发布的 v1 草案不作为兼容承诺。v2 包含路径无关的 source/parsed `artifact_id`、来源 DOI 与哈希、流水线/后端版本、配置与执行指纹、页面 MediaBox/CropBox/旋转、质量覆盖率、章节、合并段落、结构化引用、图表证据及表格单元。每个文本块使用统一的 `pdf-cropbox-display-bottom-left-normalized/v1` 页码/bbox 和文本 span；本机绝对路径不进入工件，安全的相对 locator 只用于重新核验且不参与身份计算。基线框由 PDF 文本矩阵和字体大小估算，明确标为 `bbox_precision: estimated`，不冒充逐字形精确框。状态始终显式为 `PARSED`、`PARTIAL` 或 `FAILED`。

默认后端读取 PDF 原生文本与页面图像资源，不做隐式 OCR；扫描页或文本极少页面会明确输出 `PARTIAL` 与 `PAGE_WITHOUT_TEXT`/`SPARSE_TEXT`，不会伪造坐标。需要扫描页支持时安装 `aletheia-nexus[ocr]`、安装 Poppler/Tesseract，并使用 `--ocr`。可用 `--ocr-languages` 和 `--ocr-max-raster-pixels` 控制语言与单页内存预算；预算会在渲染前考虑 PDF `/UserUnit`，并在渲染后按实际像素再次检查。OCR 只在原生字符过少、乱码、图像主导或图像区域缺少文本锚点时触发；原生文本与 OCR 重叠时保留原生文本，OCR 仅补空白区域。引擎置信度和多引擎一致性分开记录；失败、超时或无资源会保留 native evidence，并给出稳定的机器可读降级原因。完整配置见[v0.7 OCR](V07_OCR.md)。

解析流水线会合并同栏连续文本行、恢复章节语义与显式未解析引用；图表字段只陈述 `caption-observed`、`caption-and-region-observed` 或 `caption-and-cell-evidence-observed`，并始终写明 `interpretation_status: not-interpreted`。通用 OCR 不等于表格、公式或图表理解，专用解析器须通过区域接口接入。解析成功也不等于论文结论为真。

可用 `--max-pages`、`--max-blocks`、`--max-text-characters` 控制资源上限，或用 `--no-merge-paragraph-lines` 保留逐行块。达到上限时输出 `PARTIAL`，不会静默截断。解析结果可直接做带来源检索：

```powershell
aletheia-nexus search downloads\paper.parsed.json "experimental condition" `
  --section-type methods --verify-sources
```

每个命中包含章节、PDF 页、归一化 bbox 和原文；`--verify-sources` 会重新核对 PDF 与 acquisition sidecar 的 SHA-256。Python 调用方可使用 `ParsedArtifact.search()`、`section_text()`、`locate()` 和 `verify_local_sources()`。模块边界与自定义后端约束见[v0.7 架构](V07_ARCHITECTURE.md)。

下游不需要重新解析 PDF。可从规范工件导出三种确定性派生视图：

```powershell
aletheia-nexus export downloads\paper.parsed.json --format markdown `
  --output downloads\paper.ai.md
aletheia-nexus export downloads\paper.parsed.json --format jsonl `
  --output downloads\paper.ai.jsonl
aletheia-nexus export downloads\paper.parsed.json --format chunks `
  --output downloads\paper.chunks.json --max-chars 6000
```

每个 chunk 都可独立追溯，显式带 source/parsed artifact ID、block/anchor/page 标识及 `block → anchor → page/bbox` 证据链。分块优先保留 section 与 table object 边界，并隔离 heading、caption、equation 和 reference。导出文件默认拒绝覆盖；即使显式使用 `--overwrite`，也只能替换已有派生输出，不能覆盖 canonical parsed artifact、原 PDF 或 acquisition sidecar。

公开回归使用 `benchmarks/v07_fixtures/` 中项目自编、Apache-2.0 可再分发的小型 PDF；运行 `python scripts/evaluate_v07_parser.py` 可复核输入门、逐页 gold 文本、锚点、章节、双栏顺序和图表证据。`benchmarks/v07_public_oa/` 另定义三篇按哈希冻结、按需下载的 OA 资格集。二者都不代表对所有出版社版式或科学语义的泛化质量。

## 8. 故障排查

- **浏览器连接超时：** 先确认 `http://127.0.0.1:9222/json/version` 可访问。即使端点响应，浏览器内部调试连接也可能卡住；关闭仅用于 AN 的浏览器后重跑，持久配置目录中的登录状态通常仍在。不要关闭日常浏览器或删除整个用户配置目录。
- **`TargetClosedError` 且配置目录有锁：** 通常表示同一 AN 浏览器配置已被另一个 Edge/Chrome 进程占用。连接现有进程时传入它的 `--cdp-endpoint`；否则只关闭专用 AN 浏览器，或为新运行指定不同的 `--profile`。不要让两个浏览器进程同时写同一配置目录。
- **登录完成却未继续：** 确认返回到同一 AN 浏览器会话；若站点在新标签完成认证，AN 会检查新旧出版社标签和仍留空白的身份验证标签。若仍卡住，可安全中断并从检查点重跑，保留现场与报告用于复现。
- **ScienceDirect / RSC 验证页反复出现：** 等待期间 AN 不主动刷新网页；站点自身可能重定向或重建验证组件。检查页面是否仍显示验证码、是否已返回目标论文，以及当前机构是否有授权。AN 不会把短暂空白当作验证成功；重复验证或超时应记为需人工处理，避免连续对同一 PDF 地址发请求。不要通过增大重试次数来应对站点风控。
- **普通 Edge 能打开、AN Edge 却循环验证：** 核对两者是否走相同的代理/网络出口。AN 默认强制直连，即使 Windows 系统代理已启用；关闭 TUN 不会自动取消系统代理，也不会改变 AN 的启动参数。信任该代理时，可显式选择 `--browser-use-system-proxy`，并用单篇 DOI 验证；这不保证站点一定接受受控浏览器。
- **打开了 PDF 却显示 `SUPPLEMENT`：** 查看报告中的 `identity.evidence`、实际 PDF 首页及来源 URL。ACS 正文首页可能含“Supporting Information”导航文字，不能单凭该词判断为附件；当前规则结合首页标题与 Abstract 识别正文。
- **`EXHAUSTED`：** 先分清 403/挑战、没有 PDF 候选、标题不匹配和实际购买页。单纯增大重试次数通常不能解决订阅缺失。
- **机构自动选错：** 在出版社提供的机构选择界面切换；AN 不强制改写机构 cookie，也不保证按 IP 跳转的网站永久记住选择。

## 9. 开发验证与项目边界

```powershell
python -m pip install -e ".[dev,browser]"
python -m pip check
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
python -m compileall -q src scripts
python scripts/verify_frozen_benchmark.py
python scripts/evaluate_v07_parser.py
python -m pytest -q
python scripts/verify_v07_rc.py --browser-smoke --ocr-smoke --public-oa `
  --report qualification-report.json
```

这些脚本与单元测试不替代实际机构环境中的授权验证，也不证明解析器适配所有真实论文版式。AN 0.7 将获取与核验衔接到带来源锚点的原生文本优先解析，并提供可选选择性 OCR；科学主张解释和科研知识组织仍属于后续能力。

v0.7 检查脚本会优先导入当前仓库的 `src`，避免复用环境时测到其他 checkout。`--browser-smoke` 需要 browser extra 和 Chromium；`--ocr-smoke` 需要 ocr extra、Poppler 与 Tesseract。缺少组件时应补齐环境后重跑，不能把跳过或 `PARTIAL` 写成通过。私有语料资格脚本要求非空输入且每篇都完成 `PARSED`；缺文件、哈希改变或部分解析会使检查失败。

## 10. 合并 main 前的发布检查

v0.7.0 的最终 PR 必须直接面向 `main`；不要把功能分支直接推送到
`main`，也不要把受版权保护的真实论文、机构配置、Cookie、令牌或带
签名参数的报告加入提交。维护者应留存最终提交 SHA、测试输出和私有
报告路径；代码门槛失败或缺证时不合并、不打稳定标签。

1. 在最终代码上运行第 9 节的 Ruff、编译、冻结基准、解析评测和完整
   测试。Python 3.11–3.14 都须通过；专用 job 还须运行真实 Chromium、
   Poppler + Tesseract 和 clean-wheel 安装验证。
2. 对固定的 24 篇回归集和 14 篇获取验证集核对输入哈希、逐篇状态、
   正文、定位、结构和重复语义对象。CropBox 外隐藏文本等变化须结合可见页
   解释，不以原生文本层逐字符守恒作为发布门。私有 PDF 与输出留在 Git
   忽略目录；解析完成或回归一致不得写成“视觉内容或语义 100% 正确”。
3. 对 PMC 云路径至少完成一个公开 DOI 烟测，确认候选来自官方桶、元数据
   DOI 一致、最终 PDF 为 `VERIFIED` 正文且 sidecar 哈希匹配。外部服务烟测
   不能替代确定性测试，也不能解释为通用获取成功率。
4. 将 `pyproject.toml` 版本固定为 `0.7.0`，更新发布说明和历史；从干净
   提交构建 sdist/wheel，执行依赖检查，并从 wheel 的全新临时环境验证
   `aletheia-nexus --version`、`doctor` 和核心导入。GitHub Release 本身不
   证明 PyPI 已上传，仍须检查项目页和全新安装。
5. 推送功能分支并更新现有 PR。在**最终提交**上等待 Python 3.11–3.14、
   Linux/Windows Chromium、OCR 和 package jobs 均为实际 `success`；
   `skipped`、取消或旧提交的绿色结果均不能替代。通过评审后由维护者合并
   PR，再对合并后的 `main` 提交打不可变的 `v0.7.0` 标签并发布。

旧版本的机构授权与发布证据继续按[版本与验收记录](RELEASE_HISTORY.md)
和[v0.7 前准备记录](PRE_V07_READINESS.md)解释；不能把历史累计单篇复测、
单机构结果或本轮公开 PMC 烟测倒填成跨机构资格证明。
