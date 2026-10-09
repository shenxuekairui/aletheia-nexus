# CNKI 验证与 AN 接入设计（v3）

## 定位与调用顺序

CNKI 是 AN 的机构浏览器获取 Provider，不是独立的身份判断或知识入库系统。

```text
调用方提供 DOI / 题名 / 元数据
  → 本地文件导入（显式提供时优先）
  → 公开发现和直接获取
  → 适用的官方 API
  → 注册的 CNKI Provider：机构浏览器 → 题名检索 → 详情筛选 → PDF
  → 同一 PDF 结构 / 正文身份 / 文档角色验证器
  → VERIFIED：正常存储 + 溯源 → 上层使用
    未验证：_unverified + 溯源 → 本地复核，不视为入库成功
```

`acquire_full_text_maximized()` 和 `acquire_full_text_batch_maximized()` 使用已有注册机制调用 CNKI，公开获取或官方 API 成功后不再开启 CNKI。分流规则由 `cnki_routing.py` 集中维护：

| 输入证据 | 默认行为 |
| --- | --- |
| CNKI 来源链接、明确 CNKI 文献 ID、`.cnki.` / CJCU DOI | 公开来源和官方 API 后进入 CNKI |
| 登记元数据的中文题名或中文期刊 | 公开来源和官方 API 后进入 CNKI |
| 只有用户提供的中文题名，没有可靠来源 | 先走完原有出版社浏览器路线，再考虑 CNKI；原路线待认证或已触发下载时不切换 |
| 英文元数据或已知外文出版社，仅用户题名是中文译名 | 不因译名转入 CNKI |
| 普通英文文献，无 CNKI 线索 | 原有流程，不自动访问 CNKI |
| 无 DOI 的中文题名 / 明确 CNKI ID | 使用书目请求进入 CNKI，不调用 DOI 解析器 |

来源包括 discovery、实际落地页和元数据 URL，仅真正 `cnki.net` 域名及其子域有效。`source_preference="cnki"` 显式使用 CNKI-only；`"exclude_cnki"` 排除 CNKI Provider（不是网络域名防火墙，原 DOI 解析器仍可能正常跳转）。默认 `"auto"`。`cnki_enabled=False` 始终有效。显式本地 PDF 导入始终优先于上述网络选择。

只希望测试知网也可使用 `acquire_cnki_pdf()`。有 DOI 时仍是 DOI 身份优先，但知网检索入口使用题名：已有题名直接使用，否则解析 DOI 元数据。新 `PaperRequest` 允许 DOI、题名、作者、期刊、年、卷、期、页和 CNKI ID；裸 DOI 字符串调用不变。无 DOI 文献使用 `cnki:<database>:<filename>` 或 `bibliographic:<sha256>` 身份，不伪造 DOI。兼容结果对象的 DOI 字段为空字符串；CLI/sidecar 中输出 `null`。

## 验证 v3：字节获取、论文身份、来源分别验证

1. 下载层：只能使用当前页面提供的 PDF 控件/订单 URL，同一浏览器会话保留机构权限；CAJ 不转存成 PDF。登录、验证码和 MFA 交给用户，权限拒绝不绕过。

   默认使用修复版浏览器原生点击 PDF 控件并捕获附件/响应，保留页面脚本、网络栈与机构状态。`cnki_context_request=True` / `--cnki-context-request` 可显式选择同 Cookie 的 HTTP 传输；仅使用已观察到的订单 URL 或同源 PDF，不猜链接。HTTP 路线遇到权限拒绝、CAJ、超限、网络错误或上下文关闭不会盲目重放原生下载；只有明确返回非 PDF 的普通订单页允许执行已观察到的页面动作。浏览器测试的 APIRequestContext 必须单独模拟或禁止出网，因为 Playwright 的页面 route 不覆盖该传输；附件与弹窗仍验证真实原生事件。
2. 文件层：检查 PDF 魔数、可解析性、页数、加密状态、大小限制，计算实际文件 SHA-256。哈希证明字节一致，不证明下载的是目标论文。
3. 身份层：以 PDF 首页/正文为依据，详情元数据和检索得分不能单独生成 VERIFIED。恢复全角字符、DOI 分隔符附近换行和空格、排版长横线，以及中文期刊 j.cnki/j.issn 的固定结构；不拼接任意英语单词，不放宽用户输入 DOI 的语法。
4. 冲突层：首页声明 DOI 与目标冲突时，即使题名完全匹配也拒绝；多重声明需复核。已知 DOI 必须在 PDF 中确认，或由详情 DOI 一致 + PDF 精确题名和作者共同证明。无 DOI 必须有 PDF 精确题名、作者以及期刊/年份，或调用方明确的 CNKI ID 加 PDF 题名作者证据。候选新发现的 DOI 不能单独证明选对了文章；近似标题不直接验证。
5. 溯源层：CNKI 使用 policy=`cnki_bibliographic/v3`，记录原请求、独立观察的书目字段、真实 article_id、首页声明 DOI、判断依据、下载方式和源 URL。非 CNKI 的裸 DOI 流程继续使用原验证器。复用 AN access-acquisition-record/v1 的兼容字段扩展；URL 脱敏，不保存 Cookies、密码或认证令牌。

声明 DOI 只来自有 DOI 标签的首页前置内容，参考文献区域不参与；缺少冒号的独立 DOI 标签行亦可识别。真正匹配和排版修复后的匹配遵循同一冲突边界。

## 失败文件与结果契约

`BrowserAccessConfig.cnki_keep_unverified=True` 默认将可解析但未验证的 CNKI 文件保存在 `_unverified/`，包括无 DOI 文件，附带 sidecar。该设置只改变保留策略，不改变状态，不影响其他 Provider 的默认清理策略。

可用 `--no-cnki-keep-unverified` 关闭此策略（若同时显式启用通用 `--keep-unverified`，通用保留仍生效）。无效 PDF、CAJ 和超限文件仍被拒绝。隔离文件可能包含有机构使用限制的全文，仅在本地保存，不自动公开。使用方只能把 `VERIFIED` 视为成功；不得遍历 `_unverified` 并盲目入库。

`BrowserAccessAttempt.file_attempts` 保存所有尝试；`result` 优先返回 VERIFIED，否则返回题名证据最强的结果，避免最后一个错误候选掩盖先前真正论文的失败证据。顶层 evidence 会保留具体身份结论和首页 DOI，即使关闭文件保留也可看到拒绝原因。

## 浏览器、批量与恢复

调用方持有一个 `BrowserSession` 并逐篇传入，复用机构会话和已完成的认证。Python 临时会话的生命周期与调用方持有会话不同；独立 CNKI CLI 默认在批次结束后保持窗口。批量兼容裸 DOI 列表和 DOI→题名映射，也支持混合 `PaperRequest`。书目请求的断点键涵盖全部输入约束，改作者/期刊/年份后不会复用旧请求；恢复前继续核对文件 SHA-256。

候选默认检查 20 行。无 DOI 的候选得分无法区分、或仍有未检查行时返回 `AMBIGUOUS`，不消费下载来盲选；可补充作者/期刊/年份、明确 CNKI ID 或提高行数。额外约束冲突拒绝，未能确认则不标 VERIFIED。`AMBIGUOUS` 与 `RETRIEVED_UNVERIFIED` 已贯通单篇、批量和报告，不再变成 runner 错误。当前不自动遍历无限分页。

只有初始搜索控件尚未渲染、没有认证历史、没有下载副作用时，允许重新打开搜索页一次；重试仍失败时明确返回 NAVIGATION_ERROR。不能在人工认证中重载页面，也不能自动重放已开始的下载。网络请求失败、没有 PDF、身份不匹配、机构权限不足分别保留，不混成登录需求。

浏览器版本安全检查、手动认证和下载捕获仍复用现有 AN 实现；本次不增加常驻浏览器取证服务，也不安装账号登录自动化、验证码破解或 CAJ 转 PDF。

## 使用示例

```python
from aletheia_nexus.acquire.access import (
    BrowserAccessConfig, BrowserSession, acquire_full_text_maximized,
)

config = BrowserAccessConfig(profile_name="institution", wait_for_interaction=True)
with BrowserSession(config) as session:
    result = acquire_full_text_maximized(
        "10.19343/j.cnki.11-1302/c.2025.07.009",
        expected_title="农业新质生产力、农业支持保护政策与农业经济高水平发展",
        output_dir="downloads", browser_session=session,
    )
    if result.verified_result is not None:
        print(result.verified_result.file_path)
    # GUI/服务调用方自行控制 session 生命周期，不在每篇结束后关闭。
```

## 验收与边界

历史 v2/v3 修复与测试保留在旧报告中。当前分支的分流、无 DOI、现场页面适配和验收边界见 [最终集成验收](CNKI_FINAL_INTEGRATION_REPORT.md)，不能用离线重验替代在线下载结果。

本次 CNKI 获取不使用 OCR 来放宽身份判定，不实现后台常驻浏览器或自动查找所有历史下载。无 DOI 获取记录已有真实 CNKI ID / 书目哈希，但 v0.7 的后续解析入口仍要求真实 DOI；不会伪造标识符。现有解析层的可选 OCR 功能保留。学校订阅范围、只提供 CAJ 的论文和网站临时故障仍会影响下载。
