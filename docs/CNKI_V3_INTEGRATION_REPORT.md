# CNKI v3 接入与验收报告

日期：2026-10-09。范围：AN 单篇、批量、CNKI Provider、身份验证、存储与溯源；本轮未提交或推送代码。

## 结论

CNKI 已接入 AN 正式入口，不只是一份独立下载脚本。保留裸 DOI API、公开发现、官方 API 和原出版社浏览器路线；增加保守分流、无 DOI 书目请求、候选歧义状态及对应断点恢复。

本轮没有重新下载全部 20 篇。采用常规回归、真实浏览器隔离测试、既有 PDF 离线复核，以及必要的在线补测；这些证据分开报告。

## 分流边界

| 情形 | 处理 |
| --- | --- |
| 显式提供本地 PDF | 本地导入优先，不开网络；支持书目身份 |
| 裸 DOI 或含 DOI 的 `PaperRequest`，默认 auto | 保持公开来源 → 官方 API 的顺序 |
| 已观察 CNKI 来源、CNKI ID、已知 CNKI/CJCU DOI、中文登记题名或期刊 | 原便捷来源未成功后使用 CNKI Provider |
| 只有调用者输入的中文题名，没有可靠来源 | 原有出版社浏览器先行；未解决认证或已触发下载时不切换 |
| 英文登记元数据/已知外文出版社，仅用户输入中文译名 | 不因翻译题名转入 CNKI |
| 普通英文文献，没有 CNKI 线索 | 不自动访问 CNKI |
| 无 DOI 的中文题名 | 书目请求直接进入适用的 CNKI 路线；不生成假 DOI |
| 明确指定 `source_preference="cnki"` | CNKI-only，不把出版社下载当作 CNKI 成功 |
| `source_preference="exclude_cnki"` / `cnki_enabled=False` | 正式入口不调 CNKI Provider；并非 DOI 解析器的域名防火墙 |

分流是有依据的启发式判断，不等于完整的 CNKI 收录目录。提供准确来源/文献 ID 比仅凭语言更可靠。`cnki_search_all_titles=True` 仅供调用方显式扩大范围，默认关闭。

## 实施的修复

1. `PaperRequest`：真实 DOI 可选，支持题名、作者、期刊、年、卷、期、页和 CNKI 文献 ID。无 DOI 文件使用独立 `article_id`，原字符串 DOI 接口不变。
2. 验证 v3：有 DOI 时优先核对 DOI；PDF 未印 DOI 时，必须有独立详情 DOI 一致及 PDF 精确题名、作者证据。无 DOI 时需要 PDF 精确题名、作者、期刊/年份，或调用方指定且已确认的 CNKI ID。候选新发现的 DOI 不单独作为选对文章的证明。
3. 新版 kcms2 页面：从明确的 `DOI：` 元数据条目提取 DOI；从 `#authorpart` 读取作者，排除机构；从 `.top-tip` 读取发表信息，避免把平台上线时间当作发表年份；只读取公开文献 ID 字段，不读取会话令牌。
4. 消歧：详情字段冲突在下载前拒绝；得分难以区分或存在未检查行时返回 `AMBIGUOUS`。默认最多检查 20 行；不是无限分页检索。不能确认的额外约束不会被悄悄忽略。
5. 状态贯通：`AMBIGUOUS`、`RETRIEVED_UNVERIFIED` 进入正式单篇、批量与报告。没有 PDF 控件不再直接推断为“机构无权限”。
6. 断点：书目请求以全部约束的指纹区分。同题名不同作者不会误去重；请求改变或文件哈希变化后不复用旧成功。裸 DOI 的原断点格式继续支持。
7. 溯源：保持既有 sidecar schema，增加原始书目请求、实际观察书目、article_id 和 `cnki_bibliographic/v3`。身份失败保存在 `_unverified`，不混入 VERIFIED。

## 验证结果

### 自动化回归

- 全套常规测试：`934 passed, 19 skipped`。19 项跳过的是需显式启用的浏览器测试。
- 随后单独启用真实 Chromium 隔离测试：`19 passed`，包含无 DOI、内联 PDF、原生附件、弹窗、持久配置复用和认证后的续传。隔离测试不请求真实 CNKI、不自动认证。
- Ruff 检查通过；`git diff --check` 无空白错误。
- 新增边界覆盖英文文献不误分流、中文译名保护、弱线索延后、已成功/待认证/已触发下载时不转移、来源伪装、显式分流、无 DOI 验证及批量恢复、同名不同作者、缺失/冲突字段和 JSON 输入输出。

### 本机在线与文件证据

| 样本 | 本轮观察 |
| --- | --- |
| 旧 20 篇中的 #16：`10.13637/j.issn.1009-6094.2025.0192` | 实际请求返回 HTTP 200、PDF 4,214,800 字节，下载并验证成功。历史超时不能据此归因于订阅不足，也不能断言已证明当时的服务端根因 |
| 旧 20 篇的已保存 PDF | v3 仅靠 PDF 复核为 19 篇 MATCH；#5 无 PDF DOI，严格模式下需要详情证据，未通过率不能伪装为 20/20 |
| #5：膜下滴灌水稻品质性状的相关性及主成分分析 | 现场确认新版详情页的 DOI 行。补齐字段提取后重新获取，详情 DOI + PDF 题名/作者一致，VERIFIED；没有放松为题名相似即可通过 |
| 牛顿第二定律是经典力学之根 | 不提供 DOI 的书目请求下载并验证成功；随后只传题名，通过 AN 默认单篇入口再次成功。DOI 保持空，记录 `cnki:cjfq:gkwl202502042` |
| 硅粉和纤维材料对抗冲耐磨混凝土的性能影响试验 | 输入不提供 DOI；下载后在 PDF 中发现真实 `10.3969/j.issn.1006-3951.2025.06.009`，并独立核对题名、作者、期刊和年份，VERIFIED |
| 正式批量恢复 | #5 修复补测成功；已成功的两篇由 SHA-256 断点恢复，不重复下载；最终批量状态 3 VERIFIED |

两个新增样本依据期刊自己的 [物理与工程页面](https://gkwl.cbpt.cnki.net/portal/journal/portal/client/paper/9db7e8b2d33be75e09a8296d9ad7ba6f) 和 [云南水力发电页面](https://ynsd.cbpt.cnki.net/portal/journal/portal/client/paper/975e3e4f3f9c722329a4fa9f7e5208e0) 选取；页面 DOI 栏为空不保证原 PDF 没有 DOI，第二个样本正好验证了这一差异。

原始 PDF、机构 profile 和详细测试输出仅在仓库外本地目录 `../aletheia-nexus-local-tests/cnki-multidiscipline-20-20261009/`，不纳入 Git。关键记录：`diagnose16-v3.json`、`identity-revalidation-v3.json`、`v3-integration-checkpoint.json`、`v3-integration-downloads/*.acquisition.json`、`v3-title-only-result.json`。离线复核的 UNKNOWN 记录保留为真实历史，后续成功以在线 sidecar 为准。

## 使用

```python
from aletheia_nexus.acquire.access import (
    BrowserAccessConfig, BrowserSession, PaperRequest,
    acquire_full_text_maximized, acquire_full_text_batch_maximized,
)

config = BrowserAccessConfig(profile_name="institution", wait_for_interaction=True)
with BrowserSession(config) as session:
    # 默认分流；原有 DOI 字符串调用完全保留。
    result = acquire_full_text_maximized(
        PaperRequest(title="牛顿第二定律是经典力学之根"),
        output_dir="downloads", browser_session=session,
    )
    # 更完整的书目信息有助于同名消歧。
    batch = acquire_full_text_batch_maximized(
        [PaperRequest(title="牛顿第二定律是经典力学之根",
                      authors=("蒋最敏",), journal="物理与工程", year=2025)],
        output_dir="downloads", browser_session=session,
        checkpoint_path="downloads/checkpoint.json", source_preference="cnki",
    )
```

```powershell
python scripts/download_cnki.py --title "牛顿第二定律是经典力学之根" --author "蒋最敏" --journal "物理与工程" --year 2025 --profile institution
python scripts/batch_v06_download.py papers.json --source auto --profile institution
```

正式集成应持有并复用 `BrowserSession`。本轮程序正常关闭自身测试会话，未删除认证 profile，也未关闭用户的日常浏览器。验证码、真实登录/MFA 仍需用户手动完成；不绕过权限，不实现自动滑块。CAJ-only、扫描件缺少可提取证据、候选难以区分、网站结构变化或机构未订阅仍可能不能 VERIFIED，应保留具体状态，而不是承诺任何论文都能全自动成功。
