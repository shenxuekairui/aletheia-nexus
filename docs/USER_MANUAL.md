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

所有参数可运行 `aletheia-nexus acquire --help` 查看；旧 `scripts/batch_v06_download.py` 保留兼容入口。遇到慢站点可以适度增大 `--base-timeout`、`--request-timeout`、`--max-source-routes` 和 `--max-pdf-candidates`；预算增加会延长批次运行时间，不能创造未获得的订阅权限。

## 4. 登录与机构选择

1. AN 打开论文或 PDF 的可见浏览器页面。
2. 若出现机构选择、登录、MFA 或验证码，用户在该浏览器内完成。
3. AN 只观察页面，不在等待循环中主动刷新。验证提示消失后须连续数次保持可用状态；AN 优先读取浏览器已收到的 PDF/下载，必要时才对同一目标作一次受限重试，然后继续后续论文。

Elsevier 等站点可能按网络 IP 自动推荐机构。即使 AN 复用同一浏览器配置，出版社仍可能重新选择机构。若自动选中的机构没有该期刊权限，请在网站提供的入口切换至有权限的机构；AN 不修改系统代理或伪造机构身份。切换成功后的 cookie 可能被复用，但不保证永久有效。

如果确认没有订阅权限，可以关闭当前挑战页面，或设置有限的 `--interaction-timeout N`；当前 DOI 可结束为 `INTERACTION_REQUIRED`，默认继续后续 DOI。这与“已确认无权限”的人工判断应分别记录，不要把没有完成的登录自动解释成 `ENTITLEMENT_REQUIRED`。`Ctrl+C` 会中断整个命令：之前已写入检查点的论文仍可在下次复用，但本次完整 `batch-report.json` 不保证更新。若出版社明确显示购买或无权限页面，AN 才可能自动归类 `ENTITLEMENT_REQUIRED`。

IEEE DOI 也进入同一浏览器流程。出现已记住的 “Access Through …” 机构按钮时，AN 会尝试点击、等待约 5 秒并重试 PDF；账号密码、MFA 和其他人工验证仍由用户完成。所有文件都受同样的正文验证规则约束。

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

## 7. 故障排查

- **浏览器连接超时：** 先确认 `http://127.0.0.1:9222/json/version` 可访问。即使端点响应，浏览器内部调试连接也可能卡住；关闭仅用于 AN 的浏览器后重跑，持久配置目录中的登录状态通常仍在。不要关闭日常浏览器或删除整个用户配置目录。
- **登录完成却未继续：** 确认返回到同一 AN 浏览器会话；若站点在新标签完成认证，AN 会检查新旧出版社标签和仍留空白的身份验证标签。若仍卡住，可安全中断并从检查点重跑，保留现场与报告用于复现。
- **ScienceDirect / RSC 验证页反复出现：** 等待期间 AN 不主动刷新网页；站点自身可能重定向或重建验证组件。检查页面是否仍显示验证码、是否已返回目标论文，以及当前机构是否有授权。AN 不会把短暂空白当作验证成功；重复验证或超时应记为需人工处理，避免连续对同一 PDF 地址发请求。不要通过增大重试次数来应对站点风控。
- **普通 Edge 能打开、AN Edge 却循环验证：** 核对两者是否走相同的代理/网络出口。AN 默认强制直连，即使 Windows 系统代理已启用；关闭 TUN 不会自动取消系统代理，也不会改变 AN 的启动参数。信任该代理时，可显式选择 `--browser-use-system-proxy`，并用单篇 DOI 验证；这不保证站点一定接受受控浏览器。
- **打开了 PDF 却显示 `SUPPLEMENT`：** 查看报告中的 `identity.evidence`、实际 PDF 首页及来源 URL。ACS 正文首页可能含“Supporting Information”导航文字，不能单凭该词判断为附件；当前规则结合首页标题与 Abstract 识别正文。
- **`EXHAUSTED`：** 先分清 403/挑战、没有 PDF 候选、标题不匹配和实际购买页。单纯增大重试次数通常不能解决订阅缺失。
- **机构自动选错：** 在出版社提供的机构选择界面切换；AN 不强制改写机构 cookie，也不保证按 IP 跳转的网站永久记住选择。

## 8. 开发验证与项目边界

```powershell
python -m pip install -e ".[dev,browser]"
python -m pip check
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
python -m compileall -q src scripts
python scripts/verify_frozen_benchmark.py
python -m pytest -q
.\scripts\verify_v06_rc.ps1 -Browser
```

该脚本与单元测试不替代实际机构环境中的授权验证。建议用固定 DOI 集、已确认有权限的阳性对照、每篇报告及人工抽查共同评估结果。AN 0.6 负责获取与核验；深层内容解析和科研知识组织属于后续版本。

## 9. 合并 main 前的发布检查

以下 1–5 项是**已完成的 v0.6.0 历史发布口径**，不是 v0.6.1 的待办清单。v0.6.1 须另外通过 Windows CI、wheel 安装烟测与 PyPI Trusted Publishing，详见[开发与发布计划](v0.6.1-development.md)。首个公开 `v0.6.0` 以代码正确性与可安装性为封板范围，不声称已对不同机构的授权覆盖完成正式资格验收。维护者应留存最终提交 SHA、测试输出和报告路径；代码门槛失败或缺证时保持草稿，不合并 `main`，不打稳定标签。

1. 在最终代码上分别以 Python 3.11 和 3.14 运行第 8 节的本地检查，确认 Ruff、依赖、完整确定性测试与固定基准集检查通过；在支持的环境执行真实 Chromium 集成测试。原私有开发仓库 `v0.5.2` 标签对应的历史 510 passed 与 v0.6 RC 的 734 passed、7 skipped 必须分开记录；公开仓库不携带旧标签。
2. 首个公开版的正式机构授权资格验收已由项目发起者决定**暂缓**。这项缺证必须在 README 和 GitHub Release 中显著披露；不能将此前 37/40、19/20 的累计单篇复测解释为新的完整批次或授权对照通过。代码级封板仍须完成本节其余门槛。
3. 后续补做授权资格验收时，准备本地 `benchmarks/v06_entitled_positive_controls.local.json`：从[模板](../benchmarks/v06_entitled_positive_controls.example.json)替换为同一机构、账号和网络环境下已人工确认可获取的至少 3 篇论文，覆盖至少 2 个 `access_family`。不要提交凭据或机构专属阳性对照。默认压力集是 CDI 与海水淡化各 10 篇；另有[固定标题的 20 篇用户集](../benchmarks/user_20260923_20_frozen.json)，若改用它，必须在结果中注明输入集。

   ```powershell
   python scripts/manual_v06_access_acceptance.py `
     --entitled-benchmark benchmarks/v06_entitled_positive_controls.local.json `
     --require-entitled-controls `
     --report downloads/v06-release-acceptance.json
   ```

   后续验收必须满足：压力论文不少于 20 篇、全部阳性对照 `VERIFIED`、至少一篇真正由 v0.6 路径相对 v0.5 恢复、`RUNNER_ERROR = 0`；还须人工抽查 PDF 与失败分类。公开困难集的覆盖率不是订阅权限证明。**这不是首个公开版发布当时已经通过的项目。**后续源码已完成一次单机构资格验收，证据范围与未解决事项见[v0.7 前准备记录](PRE_V07_READINESS.md)；不要倒填旧标签的发布证据。
4. 最终发布 PR 面向 `main`，核对差异、Apache-2.0 许可、版本号与公开历史；把 `pyproject.toml` 改为 `0.6.0` 并生成最终发布提交。将 PR 转为 ready，在**该最终提交**上等待 Python 3.11、3.14 与 Chromium 三个云端 job 的实际结论均为 `success`。草稿 PR 的 `skipped` 即使在 GitHub 显示绿色也不算通过；额度耗尽同样不算通过。详见[CI 架构](CI_ARCHITECTURE.md)。
5. 若开发期间使用过堆叠 PR，正式发布前保留一个包含完整 v0.6 差异、直接面向 `main` 的发布 PR；不要再把已被覆盖的底层 PR 重复合入。任一改动之后都重新核对最终 SHA 和完整 CI。代码级门槛通过后再合并，并给合并后的 `main` 提交打 `v0.6.0` 标签；GitHub Release 同时注明机构授权资格验收尚未完成。正式流程以[技术规范的退出标准](v0.6-acquisition-maximization.md#16-exit-criteria)为准。
