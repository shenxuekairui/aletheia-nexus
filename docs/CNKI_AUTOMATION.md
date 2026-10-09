# CNKI 自动化获取

接入与验证规则详见 [CNKI 接入设计](CNKI_INTEGRATION_DESIGN.md) 和 [v3 验收报告](CNKI_V3_INTEGRATION_REPORT.md)。v3 保留 DOI 排版修复与冲突保护，新增无 DOI 书目验证、保守分流和批量书目请求。默认将可解析但未验证的 PDF 和溯源隔离保存到 `_unverified/`，不计为成功。可用 `--no-cnki-keep-unverified` 禁用。

默认同会话获取既支持页面上的 CNKI PDF 订单 URL，也支持明确的同源 `.pdf` 链接，以避免内嵌预览器兼容问题；不猜测地址，不绕过认证。需要原生下载时使用 `--no-cnki-context-request`。

CNKI Provider 自动完成标题解析、检索、候选排序、详情页打开、PDF 获取、SHA-256、正文身份校验和溯源存储。验证码、机构登录和 MFA 交给用户在本地浏览器中完成；完成后程序继续原来的获取步骤。机构权限、PDF 是否存在和网站可用性仍决定实际下载结果。

## 直接按 DOI 或标题获取

先按主使用说明安装 `.[browser]`。持久下载要求修复版 Chromium/Edge/Chrome >=155；Playwright 1.63 自带的 Chromium 153 受上游缺陷影响，不能用于正式下载。Windows 可将官方稳定版 Chrome for Testing 解压到 AN 独立目录（不安装系统浏览器、不清理机构会话）：

```powershell
python scripts/install_an_browser.py
```

然后从仓库根目录运行：

```powershell
python scripts/download_cnki.py --doi "10.16560/j.cnki.gzhx.20230412" --output-dir downloads/cnki
python scripts/download_cnki.py --title "论文的完整标题" --author "第一作者" --output-dir downloads/cnki
python scripts/download_cnki.py --doi "10.7503/cjcu20250333" --title "已知的中文标题" --profile cnki
```

- DOI 模式：优先复用已有标题，再解析 Crossref/DataCite；中文 DOI 的回退包含 CHNDOI 和适用的 CJCU 官方页面。已给出标题时直接使用该标题检索。
- 标题模式：不需要先给 DOI；作者参数可以重复。真实 DOI 缺失时使用 CNKI 文献 ID 或书目哈希。验证必须有 PDF 题名、作者及出版信息，信息可从详情页补齐。新发现的 DOI 不是选对文章的充分证据。支持 `--journal`、`--year`、`--volume`、`--issue`、`--pages`、`--cnki-id`；同名候选无法区分时返回 `AMBIGUOUS`。
- 标题与作者只用于检索、排序和身份核验。不同 DOI 的详情页会被跳过；结果列表中靠后的候选可以继续尝试。最终仍必须通过统一的 PDF 结构、身份和正文角色校验。
- 中文标题选择“篇名”字段；`-`、`+`、`*`、`/` 等化学式符号用半角引号保护，避免被当作检索运算符。无合适候选时，最多追加一次无化学式标点的中文长短语检索，候选仍按原完整标题校验。英文元数据保留主题检索，以兼容知网的中文译名。
- 首轮候选全部与详情页身份冲突或获取未成功时，也会尝试上述一次短语回退；跨查询去重相同候选。溯源中的检索字段记录实际观察值，无法确认时为 `null`，不把计划使用的篇名字段写成既成事实。
- 长英文标题遵守检索框的 `maxlength`，在词边界截断检索词，不截断用于身份校验的原题名。仅对长英文查询返回且标有“（英文）”的中文标题开放跨语言候选；详情页 DOI 冲突仍拒绝，中文译名本身不构成 PDF 身份通过的证据。

默认复用专用持久浏览器 profile，机构 VPN/校园网由用户事先连接。要复用已打开且启用了调试端口的浏览器，可传 `--cdp-endpoint http://127.0.0.1:9222`。程序不会修改日常浏览器 profile，也不会自动输入账号密码。

Windows 可见模式未指定 `--channel` 时，优先使用已安装且 >=155 的稳定版 Edge/Chrome，否则选择 `install_an_browser.py` 部署的 AN 专用运行时；headless 也可使用该运行时。其余平台可升级到包含上游修复的 Playwright Chromium。实际启动或连接后，152–154 会被拒绝开始下载，并给出版本错误，不删除任何 History/Cookie。可用 `--executable-path PATH` 指定修复版二进制，不能与 `--channel` 或 `--cdp-endpoint` 同时使用。不要让不同浏览器同时写同一配置；跨引擎/版本切换建议新建专用 `--profile`，新配置可能需要再次人工认证。

根因是 [Chromium 556160935](https://issues.chromium.org/issues/556160935)：DevTools 下载代理遗漏历史加载能力，复用带下载历史的配置时可能访问已释放的下载对象。[Edge 团队确认在 155 修复](https://github.com/MicrosoftEdge/DevTools/issues/461)。换新配置首次成功、切换 CDP 端口或使用同会话 HTTP 请求，不单独作为根因消除证据；回归测试必须包含下载后关闭、复用配置再次原生下载。

默认保留系统网络设置，不再强制绕过代理；仅明确需要直连时使用 `--direct-connection`。该参数只影响新启动的 AN 浏览器，不修改系统设置或已连接的 CDP 浏览器。

先等待页面/机构会话初始化，再从明确的 PDF 按钮读取真实地址。针对已实地验证的 `bar.cnki.net/bar/download/order`，默认优先通过同一 BrowserContext 请求，复用机构 Cookie，避免本机原生下载链路的浏览器崩溃；其他按钮仍走原生点击。无认证信号的 JavaScript 壳页可回退原生流程，权限拒绝、CAJ、超限或上下文关闭不触发重放。需要明确测试原生路径时使用 `--no-cnki-context-request`（Python 配置为 `cnki_context_request=False`）。这不生成下载地址、不绕过登录或权限、不复制 Cookie 到另一个会话。

单篇交互 CLI 默认在返回结果后保持 AN 窗口，直到用户关闭窗口或按 Ctrl+C；此期间不会重新触发下载。需要自动退出时传 `--no-keep-browser-open`；非交互/headless 不等待，CDP 会话始终由原调用者管理。Python 的临时会话 API 仍会在返回时清理；需要保留认证现场时应传入调用者持有的 `BrowserSession`。

直接 CNKI 批量测试可以重复 `--doi`，共用一个 BrowserSession，不经过公开来源回退：

```powershell
python scripts/download_cnki.py --doi "10.7503/cjcu20250333" --doi "10.13822/j.cnki.hxsj.2024.0476" --profile cnki
```

同一进程依次完成全部 DOI，最后才保持窗口；已验证结果不因后续失败丢失。普通单篇无 PDF/身份失败允许继续下一篇，未解决认证或浏览器关闭则停止，不重放已开始的下载。多 DOI 不允许共用一个 `--title`。返回码：全部 VERIFIED 为 0，有失败为 1，未解决认证为 2。

“自动登录”过渡页本身不再视为个人账号登录：等待其完成机构 IP 初始化或出现真正的登录表单。程序请求返回登录 URL、但页面已自动跳转且无可见认证时，不再直接返回 `INTERACTION_REQUIRED`；最多尝试一次已初始化的同会话请求。反复返回访问页但无可见认证会报告获取失败，不会反复要求用户登录。真实验证码、MFA、登录表单及权限拒绝仍保留人工/终止边界。

## 人工认证与恢复

默认 CLI 在可见浏览器中等待人工认证完成，没有固定认证超时。控制台会提示当前认证类型；认证完成后重新观察页面，必要时恢复检索或重试一次 PDF 控件。

不传配置的直接 Python API 同样默认等待人工认证。提示消失后还需连续两次观察到已渲染内容；认证弹窗自行关闭时，只回到存活、无认证提示且已就绪的父页面。已开始的 PDF 响应会等待完成，不立即重复点击下载。

`--interaction-timeout 180` 将等待上限设为 180 秒。`--non-interactive` 立即返回待人工处理状态；无界面模式需要同时传 `--headless --non-interactive`。进程可用 Ctrl+C 取消。

待认证页面可能出现在搜索页、详情页、下载后的新标签页或 iframe。Provider 会捕获这些阶段的认证并将状态返回为 `INTERACTION_REQUIRED`。独立 CLI 在超时返回后关闭自己创建的浏览器会话；希望返回后保留现场时，应使用调用者持有的 `BrowserSession` 或连接外部浏览器。

若浏览器意外关闭且此前尚无人工认证、PDF 请求或下载触发记录，复用同一配置重建连接/上下文并重试一次。`download_started` 在 PDF 请求/点击时记录，不依赖保存成功；已开始的下载不会被会话重连、通用来源回退或批次内部重试重复执行。认证页面及其父页面在人工等待期间不作清理；整个会话关闭时报告失败，不伪造认证完成。

## 批量模式

原来的 `batch_v06_download.py` 仍优先尝试公开来源，未获取的适用论文再进入 CNKI：

```powershell
python scripts/batch_v06_download.py dois.txt --cnki --stop-on-interaction --output-dir downloads/my-batch
```

`--source auto` 默认保守分流，`--source cnki` 指定 CNKI-only，`--source exclude_cnki` 排除 CNKI Provider；`--no-cnki` 是总开关。普通英文论文不自动进 CNKI，用户提供的中文译名不覆盖英文登记元数据。只有中文题名的弱线索要等原有出版社浏览器路线结束才尝试。`--cnki-all-titles` 是显式扩大范围；`--cnki-max-results` 默认 20。批次共用浏览器 profile、成功断点和 SHA-256 检查。未解决认证默认停止；仅显式 `--continue-after-interaction` 或 `stop_on_interaction=False` 才继续。

JSON/CSV 输入还支持无 DOI 的 `title`、`authors`、`journal`、`year`、`volume`、`issue`、`pages`、`cnki_id`；JSON 作者为列表，CSV 作者用英文分号分隔。原 DOI 字符串列表及 DOI/title 行继续兼容。

## Python API

```python
from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserSession,
    acquire_cnki_pdf,
)

config = BrowserAccessConfig(
    profile_name="cnki",
    wait_for_interaction=True,
    cnki_max_results=5,
)
with BrowserSession(config) as session:
    attempt = acquire_cnki_pdf(
        title="论文的完整标题",
        authors=("第一作者",),
        output_dir="downloads/cnki",
        browser_session=session,
    )
    print(attempt.status, attempt.result)
```

可以传 `doi`、`title`，或两者同时传。传入会话时在该会话上配置参数，不再传 `config`。同一会话仅供顺序调用使用。

## 文件、状态与溯源

下载兼容详情页附件、新标签页附件和浏览器直接返回的 PDF 响应。只捕获当前详情页及其子标签页，避免将其他浏览器标签页的文件混入此次获取。CAJ 下载按钮、CAJ URL 和 CAJ 文件名均不作为 PDF 晋升。

针对实地观察到的 PDF 控件地址 `https://bar.cnki.net/bar/download/order`，优先通过原 `BrowserContext.request` 获取该控件原有 URL，复用机构会话并保留重定向安全检查。成功路线为 `cnki_pdf_control_request`，不再触发第二次原生下载；登录/验证码仍显示在浏览器中交给用户，权限不足、CAJ、超限都不通过重新点击规避。仅当返回无认证信号的 JavaScript 壳页、尚未取得 PDF 时，才回到原生控件流程。其他 PDF 控件继续使用原生下载/响应捕获。

临时附件标签页正常关闭不再被直接视为整个浏览器断开。若下载事件已发生但保存失败，并且当前检索/详情页仍然存活，则最多使用同一个 `BrowserContext.request` 对该 PDF 控件产生的 URL 进行一次恢复（人工认证后允许再试一次）；复用同一 Cookie 会话、验证重定向 URL、检查文件大小和 CAJ 标记，并继续执行原有身份门槛。HTML 登录/验证码会显示在浏览器中交给用户；整个上下文已关闭时不会伪造成功或无限重试。恢复路线记录为 `cnki_pdf_context_request_recovery`。

成功文件使用真实 DOI 或独立 article_id/hash 命名和 access sidecar，包含原请求、观察书目、来源页、下载路线、Provider、搜索题名、候选题名/分数、下载方式、DOI 来源、SHA-256 和身份检查结果。无 DOI 字段为 `null`，不写虚构 DOI。URL 查询值脱敏，不保存 cookie、账号、口令或会话凭据。

| 状态 | 含义 |
| --- | --- |
| `VERIFIED` | PDF 结构、论文身份和正文角色验证通过 |
| `RETRIEVED_UNVERIFIED` | 文件获取成功，正文身份/角色未通过；默认不保留 |
| `INTERACTION_REQUIRED` | 需要人工认证且仍未完成 |
| `ENTITLEMENT_REQUIRED` | 明确权限限制，或等待后没有可用 PDF 控件 |
| `NO_FILE_CANDIDATES` | 无足够相近的标题候选，或只有 CAJ |
| `PAGE_MISMATCH` | 已检查详情页与目标论文不一致 |
| `RETRIEVAL_FAILED` | 下载失败、超限或 PDF 无效 |
| `AMBIGUOUS` | 多个候选无法区分，补充书目信息或 CNKI ID |
| `NAVIGATION_ERROR` / `ERROR` | 页面/浏览器阶段失败；记录阶段和异常类型 |

CLI 成功返回 0，待认证返回 2，其他获取结果返回 1。

中文 PDF 的逐字空格会作精确紧凑标题匹配：至少 12 个字符且包含至少 8 个汉字，并限定 PDF 首页。短通用标题、只出现在后续参考文献中的标题、打不开的加密文件和补充材料仍不能据此晋升为正文。

PDF 文本专用 DOI 提取支持全角字符和 DOI 标点附近的排版空白；用户输入的 DOI 语法验证仍然严格。紧凑标题匹配将 `CO_2`、`CO₂`、`CO 2` 等下标排版视为等价，但不会删除任意单词间空白来拼接 DOI，也不会把后续参考文献中的 DOI 当作首页正文身份。

首页参考文献区域之前的明确 `DOI:` 标记若唯一且与目标冲突，即使题名相同也不能晋升。全角化学式先做兼容规范化再处理下标，正文角色与加密文件门槛保持不变。

## 2026-10-09 在线诊断与边界

对原 7 篇 DOI 的真实知网测试发现：英文元数据对应中文译名会被原相似度筛选排除；未引用的化学式标点导致主题检索返回不相关论文；PDF 全角 DOI 和 `CO_2` 排版导致身份漏判。上面的修复分别覆盖这些问题。

修复后 #3、#6 已在线检索到完整标题和作者一致的结果。#8（`10.13822/j.cnki.hxsj.2023.0002`）在独立 Chromium 配置中重新从知网下载，并通过 DOI、首页标题、结构和 SHA-256 检查。其他下载重试出现过保存时上下文关闭；后续全量重测在 #3 明确检测到机构认证，批次已停止。**尚不能宣称修改后 7/7 在线验证成功，也不能仅凭一次 Chromium 成功把问题归因于 Edge。**

本轮工作树回归 `799 passed, 14 skipped`，显式启用浏览器模拟场景 `14 passed`，修改文件 Ruff 检查通过。浏览器模拟使用拦截页面，不会自动登录真实知网。

此处早期默认引擎说明已被上方“Windows 可见模式优先系统 Edge/Chrome”的修复替代。不要将日常浏览器用户目录用于 AN 测试。外部 CDP 会话仍只断开、不关闭；机构登录、验证码、MFA 和订阅权限仍由用户处理。

## 离线验证范围

2026-10-08 的实现验证使用单元测试和完全拦截网络请求的本地 Chromium 页面。覆盖候选 DOI 冲突、标题排版、错误元数据、跨标签页捕获、无关标签页隔离、认证交接/恢复、文件大小限制、临时文件清理、标题模式和一次浏览器恢复。

本地工作树的全量回归为 `781 passed, 11 skipped`；随后启用浏览器测试，7 个现有场景和 4 个 CNKI 场景共 `11 passed`。本次修改文件的 Ruff 检查通过。工作树中已有的其他未提交开发内容未包含在 CNKI 提交中。

Chromium 场景覆盖延迟渲染的检索框/结果列表、内联 PDF、同页附件、新标签页附件以及持久会话 API；不会访问真实 CNKI，也不会执行机构登录。本轮没有重跑此前的 7 个在线 DOI，因此离线通过不代表当前机构订阅下的成功率。

```powershell
python -m pytest -q tests/acquire/access tests/acquire/fulltext/test_identity.py
$env:AN_RUN_BROWSER_SMOKE="1"
python -m pytest -q tests/acquire/access/test_cnki_browser_integration.py
```

页面结构变化可能需要更新选择器。上面的早期离线测试数字为历史记录；后续现场证据及本次功能修复验收见 [CNKI_FINAL_FIX_REPORT.md](CNKI_FINAL_FIX_REPORT.md)。模拟测试不代表真实订阅权限或七篇在线下载全部成功。
