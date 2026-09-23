# Aletheia Nexus 0.6 使用说明书

本手册面向需要按 DOI 获取、核验并批量保存论文正文 PDF 的研究人员。当前代码为 `0.6.0.dev0` 发布候选；稳定标签须通过项目规定的正式验收。AN 的目标是尽可能使用公开路径、已授权的官方 API 和用户自己的浏览器会话获取文件；只有 PDF 结构、论文身份和正文角色都通过检查，才标记为 `VERIFIED`。AN 不提供订阅权限，也不会代替用户输入密码、MFA 或验证码。

## 1. 环境与安装

要求 Python 3.11 或更高版本；本次发布候选已在 3.11 和 3.14 本地验证。Windows PowerShell 示例（命令在仓库根目录执行）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,browser]"
python -m playwright install chromium
python -c "import importlib.metadata as m; print(m.version('aletheia-nexus'))"
```

只使用公开 HTTP 路径时，可安装 `.[dev]`，不必安装浏览器依赖。正式使用时可将输出目录放在仓库外，以便代码与下载文件分开管理。需要联网访问 DOI、元数据服务和出版社；机构授权仍由出版社和当前账号决定。

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

可直接参考仓库里的 [`benchmarks/user_20260923_20_with_titles.json`](../benchmarks/user_20260923_20_with_titles.json)。清单中的 DOI 会标准化并去重；若要保留重复项，使用 `--keep-duplicates`。

## 3. 最常用的批量运行方式

以下命令在可见浏览器中顺序处理论文。若登录、MFA 或 CAPTCHA 被识别，AN 会暂停在页面上；用户完成后自动续跑。不传 `--interaction-timeout` 时没有预设等待上限。

```powershell
python -u scripts/batch_v06_download.py dois.json `
  --output-dir downloads/my-batch `
  --cdp-endpoint http://127.0.0.1:9222 `
  --cdp-navigate
```

当指定的本机调试端点尚未运行时，CLI 默认自动启动 AN 专用 Edge/Chrome，使用持久配置目录，逐篇打开页面。同一个浏览器会话会复用有效的 cookie 与机构认证状态；AN 不会读取、打印或写入 cookie 值。`--cdp-navigate` 表示批量任务逐篇导航；不加时会优先尝试接管当前已打开的匹配论文标签。

如只需公开路径和不等待人工操作：

```powershell
python -u scripts/batch_v06_download.py dois.txt `
  --output-dir downloads/unattended `
  --non-interactive
```

无人值守不等于绕过登录。遇到需要账号、订阅或验证的站点，AN 会记录相应状态；若站点未给出可识别的访问提示，也可能是 `EXHAUSTED`，需要查看报告诊断。

### 常用开关

| 参数 | 用途 |
| --- | --- |
| `--output-dir DIR` | 保存 PDF、逐篇记录、检查点和批次报告。 |
| `--cdp-endpoint URL` | 连接本机 AN 浏览器调试端点。 |
| `--cdp-navigate` | 为批次逐篇导航，不强行复用当前标签。 |
| `--interaction-timeout N` | 最多等待人工登录/验证 N 秒；省略则持续等待。 |
| `--stop-on-interaction` | 当前 DOI 仍需交互时停止整批；默认继续后续 DOI。 |
| `--non-interactive` | 无人值守，不等待人工登录或验证码。 |
| `--no-resume` | 不复用检查点，重新尝试所有输入。 |
| `--local-pdf DOI=PATH` | 导入已有 PDF，并重新执行完整验证。可重复传入。 |
| `--manual-ieee-fallback` | IEEE 自动获取失败时，才提示输入用户自行保存的本地 PDF 路径。 |
| `--keep-unverified` | 保留未通过正文身份验证的 PDF，便于诊断。 |
| `--fail-on-unverified` | 任意有效 DOI 未 `VERIFIED` 时以非零状态退出。 |
| `--unpaywall-email EMAIL` | 为适用的开放获取发现服务提供联系邮箱。 |

所有参数可运行 `python scripts/batch_v06_download.py --help` 查看。遇到慢站点可以适度增大 `--base-timeout`、`--request-timeout`、`--max-source-routes` 和 `--max-pdf-candidates`；预算增加会延长批次运行时间，不能创造未获得的订阅权限。

## 4. 登录与机构选择

1. AN 打开论文或 PDF 的可见浏览器页面。
2. 若出现机构选择、登录、MFA 或验证码，用户在该浏览器内完成。
3. AN 观察页面是否离开验证状态；恢复后重试目标 DOI 并继续后续论文。

Elsevier 等站点可能按网络 IP 自动推荐机构。即使 AN 复用同一浏览器配置，出版社仍可能重新选择机构。若自动选中的机构没有该期刊权限，请在网站提供的入口切换至有权限的机构；AN 不修改系统代理或伪造机构身份。切换成功后的 cookie 可能被复用，但不保证永久有效。

如果确认没有订阅权限，可关闭该登录页或按 `Ctrl+C` 结束等待，随后报告会显示 `INTERACTION_REQUIRED`；这与“已确认无权限”的人工判断应分别记录，不要把没有完成的登录自动解释成 `ENTITLEMENT_REQUIRED`。若出版社明确显示购买或无权限页面，AN 才可能自动归类 `ENTITLEMENT_REQUIRED`。

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
- **打开了 PDF 却显示 `SUPPLEMENT`：** 查看报告中的 `identity.evidence`、实际 PDF 首页及来源 URL。ACS 正文首页可能含“Supporting Information”导航文字，不能单凭该词判断为附件；当前规则结合首页标题与 Abstract 识别正文。
- **`EXHAUSTED`：** 先分清 403/挑战、没有 PDF 候选、标题不匹配和实际购买页。单纯增大重试次数通常不能解决订阅缺失。
- **机构自动选错：** 在出版社提供的机构选择界面切换；AN 不强制改写机构 cookie，也不保证按 IP 跳转的网站永久记住选择。

## 8. 开发验证与项目边界

```powershell
python -m pip check
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
python -m compileall -q src scripts
python -m pytest -q
.\scripts\verify_v06_rc.ps1 -Browser
```

该脚本与单元测试不替代实际机构环境中的授权验证。建议用固定 DOI 集、已确认有权限的阳性对照、每篇报告及人工抽查共同评估结果。AN 0.6 负责获取与核验；深层内容解析和科研知识组织属于后续版本。
