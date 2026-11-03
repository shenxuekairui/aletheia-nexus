# SI 原生获取增强与验收（2026-11-03）

[English](SI_NATIVE_ACQUISITION.en.md)

后续通用规则、多格式、多份 SI 与原文获取集成的改动和独立实测见 [SI 跨出版社能力验收](SI_PUBLISHER_COVERAGE.md)；下文保留本轮 ACS 增强时的原始口径。

本次从 `1ac4e07` 开发，分支 `feat/si-native-reliability`。这里的“原生”指程序内置 HTTP、结构化清单和页面解析能力；不是模型推测链接或依赖助手手工下载。版本号仍为开发中的 0.8.2，不表示已发布。

## 原有缺口与改动

原先 SI 主要依赖已核验的 PMC 清单或官方文章页的明确文件链接。部分 ACS 文章页面无可用锚点、HTTP 被拒绝，或者对应 PMC 清单版本不一致时，原流程无法交付 SI；重复打开浏览器并不能保证实际保存文件。

本轮增加以下能力，继续复用现有附件复制、来源登记和 PDF SI 解析：

- **ACS 官方 Figshare 清单**：已有 PMC 路线没有发现文件时，按父文 DOI 查询公开记录。逐条核对 `resource_doi`、去除 HTML 排版后的完整父文题名、形如父 DOI 加 `.sNNN` 的补充材料 DOI、ACS 记录主机及编号，随后读取该记录的公开文件清单。公开、无保密/禁运限制且具备文件 ID、大小、MD5 的文件才可下载。
- **HTTP 文件交付**：仅允许清单的 Figshare 文件 ID，以及同文件 ID、文件名对应的 ACS 存储重定向。不为所有附件开放整个 Figshare 或 Amazon 主机。下载时校验清单大小、MD5、内容 SHA-256 和原有格式门禁，成功后才关联父文。
- **重复补取**：旧来源 receipt 的 SHA-256 通过后，还要匹配当前清单的大小和 MD5，才能复用。清单冲突时不会因旧 URL 相同而静默复用，也不覆盖旧附件。
- **官方 HTML**：增加明确的 `citation_supplementary_material`、`citation_supplementary_material_url` 和 `rel=supplement/supplementary` 识别；正确处理官方范围内的 base URL。仍要求文章页有唯一匹配 DOI，不把主文 PDF 或任意外站链接自动视为 SI。
- **直接请求兼容**：附件 HTTP 请求携带已核验来源页的 Referer，去除查询参数，不复制浏览器 Cookie。对于已记录的 Elsevier linkinghub PII，直接加入对应 ScienceDirect 文章页候选；这不代表能越过文章页访问限制。
- **中文诊断**：清单不完整、归属冲突、文件超限、大小/校验失败等保持明确错误及中文说明。

接口依据为 [Figshare 官方文章接口说明](https://docs.figshare.com/old_docs/api/articles/)和[官方 API 使用指南](https://info.figshare.com/user-guide/how-to-use-the-figshare-api/)。程序使用 `POST /v2/articles/search` 的 `resource_doi` 精确筛选及 `GET /v2/articles/{id}`，只查询公开元数据，不需要账户或密钥。发给接口的是父文 DOI，未发送论文全文。

## 范围与边界

只对 `10.1021/` 且父文具备有效题名的记录尝试该出版社清单，显式传入 `page_urls` 时保留原有定向页面行为。接口异常后保留诊断及原有页面回退；接口无结果不解释为“没有 SI”。原来的 PMC 版本/身份门禁仍保留，不将冲突 PMC 数据重新绑定给父文。

每次至多检查 10 个记录，清单至多 64 个文件，JSON 响应上限 2 MiB；现有单次附件数量和单文件字节上限继续生效。只读 API 不跟随重定向，不携带认证信息；命中限流不循环重试同一接口。无法处理的部分保留错误，不把部分清单报为全部完成。

此路径仍将 PDF SI 标为 **DECLARED SUPPLEMENT**，保留官方清单关联证据；不把来源归属、PDF 结构有效或下载成功提升为科学内容已确认。压缩包不自动解压，不执行附件。需要登录、验证码或特殊浏览器交付的其他来源继续遵守原有授权边界。

## 真实对照

使用已有已验证正文的独立文库副本，未重新下载主文、未修改原资料、未启动浏览器、未调用付费模型。原代码的核心 SI 源文件逐行核对与公开主线 `403514f` 一致。前后均设 20 秒网络超时、最多 3 个附件、每文件上限 15 MiB。

| 父文 DOI | 原代码 | 当前代码 | 实际结果 |
| --- | --- | --- | --- |
| `10.1021/acs.jpcc.4c00353` | FAILED | FAILED | Figshare 无匹配记录，文章页 HTTP 受阻；没有宣称论文无 SI |
| `10.1021/acsomega.6c02245` | FAILED | COMPLETED | 新增 Figshare 原生路线；保存 2,111,935 字节、10 页 PDF，复测 REUSED |
| `10.1021/acsomega.6c08217` | COMPLETED | COMPLETED | 原有 PMC 路线继续成功；保存 1,678,331 字节、11 页 PDF，复测 REUSED |
| `10.1021/ja0659323` | FAILED | COMPLETED | 新增 Figshare 原生路线；保存 354,191 字节、5 页 PDF，复测 REUSED |

四篇中新增两篇取得 SI，另有一篇保持原路线成功；**不能以此表示出版社总体成功率**。此前七家抽样的 ACS Omega 曾为 NOT_FOUND，本轮用同 DOI 公共 HTTP 对照的基线为 FAILED，二者是不同时间与会话条件，分别保留记录。

成功文件 SHA-256：

- ACS Omega `6c02245`：`160e997c0ab3a224afc9b4a2766b3b9ad84be8a921a38eb3d3c2ddea0ebcf9d7`
- ACS Omega `6c08217`：`788aab0dadfa13d3145d77134f249dc1ef6f20a6ec3a0783e07e899bd6cfe55d`
- JACS：`645b20a584f0e6330d22e4755a786abd6471355f13565e3f5daf815efb21d9ab`

具体校验值以[机器可读实测记录](validation/si-native-live-20261103.json)为准；本机完整原始结果和文件位于 `F:/AI4S/outputs/AN_SI_NATIVE_20261103/`，初次、对照与复测目录各自保留。

## 自动化与交付

新增 53 项测试，覆盖父文/官方主机/记录编号、禁运/保密状态、文件 ID/路径/大小/MD5、响应及候选上限、受限重定向、原件保持、重复复用和清单变更、原有 HTML 回退、附件角色区分、HTML 元数据、base URL 及去参数 Referer。新测试连同原有中文诊断检查 **97 passed**。

最终全套结果：**4041 passed, 148 skipped，零失败，337.71 秒**。[完整输出](validation/si-native-pytest.txt)保留原始结果。148 项跳过沿用既有的浏览器烟测、外部 OCR 和系统符号链接权限等条件，不计为通过。

首轮完整回归为 4040 passed、1 failed、148 skipped，失败是新增接口的 7 种后端字面量错误尚未全部提供中文解释；已补齐说明后重新运行完整套件通过。[首轮失败输出](validation/si-native-pytest-initial.txt)保留，没有修改测试断言掩盖问题。

wheel 已构建并安装到隔离目录，从 System32 运行两个新增测试文件，**53 passed**；[安装包测试输出](validation/si-native-installed-pytest.txt)单独保存。wheel 中全部 224 个 Python 源文件与最终工作树逐字节一致。wheel SHA-256 为 `36f5df2f4cf94a91ce0ab23f6ba8fb226fe4944801a55f18b2df7c1e8e99f925`。Ruff、compileall、Git 空白检查及修改文档的本地链接和报告哈希检查均通过。

接口失败、模板夹具与真实文件交付分别记录，未执行的人工或科研准确率验证不计为通过。判断：达到本轮代码合并条件；仍有一篇公开路径受限，不能宣称 SI 全覆盖。

主要修改：`workbench/supplement_figshare.py`、`workbench/supplements.py`、`workbench/messages.py` 及两个新增测试文件。没有改造数据库、替换获取引擎或新增浏览器权限。
