# CNKI 自动化获取

CNKI Provider 自动完成标题解析、检索、候选排序、详情页打开、PDF 获取、SHA-256、正文身份校验和溯源存储。验证码、机构登录和 MFA 交给用户在本地浏览器中完成；完成后程序继续原来的获取步骤。机构权限、PDF 是否存在和网站可用性仍决定实际下载结果。

## 直接按 DOI 或标题获取

先按主使用说明安装 `.[browser]` 和 Playwright Chromium。然后从仓库根目录运行：

```powershell
python scripts/download_cnki.py --doi "10.16560/j.cnki.gzhx.20230412" --output-dir downloads/cnki
python scripts/download_cnki.py --title "论文的完整标题" --author "第一作者" --output-dir downloads/cnki
python scripts/download_cnki.py --doi "10.7503/cjcu20250333" --title "已知的中文标题" --profile cnki
```

- DOI 模式：优先复用已有标题，再解析 Crossref/DataCite；中文 DOI 的回退包含 CHNDOI 和适用的 CJCU 官方页面。已给出标题时直接使用该标题检索。
- 标题模式：不需要先给 DOI；作者参数可以重复。先从所选详情页读取唯一 DOI，否则尝试 PDF 首页的唯一 DOI。现有存储模型以真实 DOI 为标识，无法确认唯一 DOI 的论文会报告失败，临时文件会被清理。
- 标题与作者只用于检索、排序和身份核验。不同 DOI 的详情页会被跳过；结果列表中靠后的候选可以继续尝试。最终仍必须通过统一的 PDF 结构、身份和正文角色校验。

默认复用专用持久浏览器 profile，机构 VPN/校园网由用户事先连接。要复用已打开且启用了调试端口的浏览器，可传 `--cdp-endpoint http://127.0.0.1:9222`。程序不会修改日常浏览器 profile，也不会自动输入账号密码。

## 人工认证与恢复

默认 CLI 在可见浏览器中等待人工认证完成，没有固定认证超时。控制台会提示当前认证类型；认证完成后重新观察页面，必要时恢复检索或重试一次 PDF 控件。

`--interaction-timeout 180` 将等待上限设为 180 秒。`--non-interactive` 立即返回待人工处理状态；无界面模式需要同时传 `--headless --non-interactive`。进程可用 Ctrl+C 取消。

待认证页面可能出现在搜索页、详情页、下载后的新标签页或 iframe。Provider 会捕获这些阶段的认证并将状态返回为 `INTERACTION_REQUIRED`。独立 CLI 在超时返回后关闭自己创建的浏览器会话；希望返回后保留现场时，应使用调用者持有的 `BrowserSession` 或连接外部浏览器。

若浏览器意外关闭且此前尚无人工认证或文件获取记录，复用同一配置重建连接/上下文并重试一次。人工认证过程中关闭页面会结束当前获取，避免重复请求。

## 批量模式

原来的 `batch_v06_download.py` 仍优先尝试公开来源，未获取的适用论文再进入 CNKI：

```powershell
python scripts/batch_v06_download.py dois.txt --cnki --stop-on-interaction --output-dir downloads/my-batch
```

`--cnki-all-titles` 对英文标题也尝试 CNKI；`--cnki-max-results 8` 设置最多检查的搜索结果行数。中文标题、中文期刊、含 `.cnki.` 的 DOI 和 CJCU DOI 默认适用；`--no-cnki` 关闭自动回退。批次共用浏览器 profile，成功文件受现有 checkpoint 机制保护。`--stop-on-interaction` 确保未完成认证时不继续后续论文。

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

成功文件使用原有 DOI/hash 命名和 access sidecar，包含来源页、真实下载路线、`cnki`、`CNKIProvider`、`cnki_authenticated_browser`、`playwright_institution_auth`、搜索标题、候选标题/分数、下载方式、DOI 解析来源、SHA-256 和身份检查结果。URL 查询值经过脱敏；不保存 cookie、账号、口令或会话凭据。

| 状态 | 含义 |
| --- | --- |
| `VERIFIED` | PDF 结构、论文身份和正文角色验证通过 |
| `RETRIEVED_UNVERIFIED` | 文件获取成功，正文身份/角色未通过；默认不保留 |
| `INTERACTION_REQUIRED` | 需要人工认证且仍未完成 |
| `ENTITLEMENT_REQUIRED` | 明确权限限制，或等待后没有可用 PDF 控件 |
| `NO_FILE_CANDIDATES` | 无足够相近的标题候选，或只有 CAJ |
| `PAGE_MISMATCH` | 已检查详情页与目标论文不一致 |
| `RETRIEVAL_FAILED` | 下载失败、无唯一 DOI、超限或 PDF 无效 |
| `NAVIGATION_ERROR` / `ERROR` | 页面/浏览器阶段失败；记录阶段和异常类型 |

CLI 成功返回 0，待认证返回 2，其他获取结果返回 1。

中文 PDF 的逐字空格会作精确紧凑标题匹配：至少 12 个字符且包含至少 8 个汉字，并限定 PDF 首页。短通用标题、只出现在后续参考文献中的标题、打不开的加密文件和补充材料仍不能据此晋升为正文。

## 离线验证范围

2026-10-08 的实现验证使用单元测试和完全拦截网络请求的本地 Chromium 页面。覆盖候选 DOI 冲突、标题排版、错误元数据、跨标签页捕获、无关标签页隔离、认证交接/恢复、文件大小限制、临时文件清理、标题模式和一次浏览器恢复。

本地工作树的全量回归为 `781 passed, 11 skipped`；随后启用浏览器测试，7 个现有场景和 4 个 CNKI 场景共 `11 passed`。本次修改文件的 Ruff 检查通过。工作树中已有的其他未提交开发内容未包含在 CNKI 提交中。

Chromium 场景覆盖延迟渲染的检索框/结果列表、内联 PDF、同页附件、新标签页附件以及持久会话 API；不会访问真实 CNKI，也不会执行机构登录。本轮没有重跑此前的 7 个在线 DOI，因此离线通过不代表当前机构订阅下的成功率。

```powershell
python -m pytest -q tests/acquire/access tests/acquire/fulltext/test_identity.py
$env:AN_RUN_BROWSER_SMOKE="1"
python -m pytest -q tests/acquire/access/test_cnki_browser_integration.py
```

页面结构变化可能需要更新选择器。本轮没有取得 CNKI 当前在线页面结构的验证证据；在获得真实机构会话后可另行进行在线验收。
