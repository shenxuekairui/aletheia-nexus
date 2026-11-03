# 跨出版社、多格式 SI 获取与集成验收

[English](SI_PUBLISHER_COVERAGE.en.md)

后续 [120 篇跨出版社实测](SI_SCALE_BENCHMARK_20261103.md)发现通用语境误关联与网页/文件区分问题，当前暂不建议合并。下文保留此前小样本的结果及当时判断，不将其延伸为大规模验收通过。

2026-11-03，从 `8c1c9ba` 继续开发，分支 `feat/si-publisher-coverage`，源码仍为开发中的 0.8.2。本轮在已有 PMC、ACS Figshare 和浏览器会话能力上增加通用发现规则、困难交付适配与原文获取集成测试。**具备通用规则不表示每个出版社或每篇论文都能自动取得全部 SI。**

## 实现

- **通用页面规则**：识别附件的语义区块、标题层级、`aria-label`、明确的 `data-href` 下载按钮、已有附件元数据/rel 链接，以及 JSON-LD Article 的 `associatedMedia`、`hasPart`、`supplementaryMaterial`。不执行网页脚本。语境解析忽略脚本/模板内的伪锚点及导航、页脚区块，保留原有明确脚本 PDF URL 提取；参考文献标题切断先前的附件语境。普通链接上限 4096，发现附件上限 256，截断明确记录，长文章不会因为前 256 个普通链接而漏掉末尾 SI。
- **归属门禁**：仍要求页面级唯一匹配父文 DOI。JSON-LD 顶层或 `@graph` 文章的 DOI 参与同一冲突检查，不从其引用列表推导父文。已知出版社/CDN 族继续受限；未列名出版社可通过实际 DOI 解析重定向及唯一父文 DOI 建立来源，只自动使用同主机附件。未将任意外站、仓库或云主机全局加入白名单。
- **补充材料目录页**：跟进文章页明确链接的目录页，例如 MDPI `/s1`。最多 2 页、1 层，目录页重新核对 DOI、主机和完整响应，不递归爬站；来源记录保存文章页与目录页的关联证据。超限、登录、身份冲突或网络失败保持不完整状态。
- **困难路线**：PLOS `article/file` 接口逐个核对 `type=supplementary`、父 DOI 与 `.sNNN`，拒绝正文、图文件、重复/冲突参数。允许官方接口交付到对应 PLOS corpus R2 对象，逐跳绑定具体父文、SI 编号和文件名，不开放整个 Cloudflare 存储。RSC 已记录的 articlepdf 路线加入同 DOI 的 articlehtml/articlelanding 候选；Springer PDF 来源补文章入口；PNAS、Taylor & Francis、SAGE 补 DOI 路径关联校验；补充多家出版社的官方 CDN 关系。`Client Challenge` 不解释为“没有 SI”。
- **无扩展名与多格式**：结合链接 MIME、已核验交付地址、响应 `Content-Disposition` 的扩展名提示、实际文件签名及 ZIP/Office 成员确定格式。远程文件名不成为本地路径，也不原样进入诊断。新增 DOC/PPT、RTF、OpenDocument、GIF/GZIP 等保存类型；已有 PDF、DOCX/XLSX/PPTX、XLS、CSV/TSV、文本、化学结构、图片、音视频等保留。格式未知、假 HTML、容器不符、超限会失败，明确但尚未处理的格式不会被悄悄计为全部取得。
- **多份 SI 与原文集成**：继续通过 `AcquisitionService` 在正文核验后调用同一附件服务。每个文件独立落盘、哈希、父文关联、来源登记及错误状态；一个失败不丢弃其他成功文件。恢复时正文走原检查点，成功附件复核来源/哈希后 REUSED，失败项可单独重试。默认 20 份、最高 100 份，单文件上限独立设置，达到数量上限报告 PARTIAL。

PDF SI 继续为 DECLARED SUPPLEMENT，不提升为主文 VERIFIED 或科学内容确认。只有 SUPPLEMENT 角色的 PDF 进入现有解析；源数据、审稿材料、报告摘要和非 PDF 附件保留独立角色。Office/图片等做适用的容器或签名检查，不宣称验证科学内容；压缩包不展开，文件不执行。没有替换原文引擎、改变数据库或新增登录权限。

## 工程测试与真实交付分别计数

新增 **95 项自动化测试**：27 组页面模板（含独立未知出版社）验证通用规则；14 组无扩展名格式响应验证文件类型与现有内容门禁；另覆盖 JSON-LD 归属冲突、长页面、引用/导航排除、PLOS 查询及云对象绑定、目录页边界、header 文件名、多份混合格式、部分失败、去重和原件保持。这些是合成工程夹具，不能算作 27 家出版社真实下载成功。

其中 5 项使用真实正文获取引擎和真实 SI 流程，仅将 HTTP 响应替换为夹具，不替换获取服务或附件服务：

| 情况 | 检查 |
| --- | --- |
| 正文与 SI 全部成功 | 正文 VERIFIED，同时保存 PDF、XLSX、CSV；文库仍为一篇正文 |
| 一个附件是登录 HTML | 保留另外两份，SI/总任务 PARTIAL，正文 VERIFIED |
| 数量限制为 2 | 保存两份并标记截断/PARTIAL |
| 正文身份不符 | 正文不计成功，不开始 SI 文件获取 |
| 关闭 SI | 只取得正文，不请求 SI 文件 |

前三项均检查恢复不重新请求正文、成功 SI 为 REUSED、主文 PDF/来源字节不变。混合格式存储测试还检查独立文件 receipt 和文库关联。

## Windows 真实网络观察

使用本机普通 Python 3.14 环境及公开 HTTP；无浏览器、付费模型或账户登录。已有论文用独立副本文库，不修改原文件。PLOS 集成场景是真实新获取正文，并经现有引擎核验；其他困难样本只补 SI。每次最多 20 份、每文件 25 MiB，网络超时 15–20 秒。正文 PDF 与 SI 来源、大小和哈希见[机器记录](validation/si-coverage-live-20261103.json)。

| 来源/场景 | 上一版 | 本轮实际结果 |
| --- | --- | --- |
| PLOS `10.1371/journal.pone.0039704`，官方页面 | NOT_FOUND，0 份 | COMPLETED，12 份（7 XLS + 5 DOC），全部来自原生 HTTP；再次全部 REUSED |
| 同一 PLOS，PMC 版本清单 | 复测 PARTIAL，7 份；5 份 DOC 未支持 | 原文获取入口：正文 VERIFIED、SI COMPLETED，12 份；检查点恢复正文 resumed、12 份 REUSED |
| ACS `10.1021/acsomega.6c02245` | 既有增强路线成功 | COMPLETED，1 份 PDF，既有路线保留 |
| Science `10.1126/sciadv.aeb1911` | 既有路线成功 | COMPLETED，1 份 PDF |
| RSC `10.1039/d4cc01176g` | 历史受限 | FAILED，页面 HTTP 受阻，0 份 |
| Wiley `10.1002/cctc.202201687` | 历史受限 | FAILED，页面 HTTP 受阻，0 份 |
| Elsevier `10.1016/j.elecom.2022.107204` | 历史受限 | FAILED，页面 HTTP 受阻，0 份 |
| MDPI `10.3390/nano13050931` | 历史未取得 | FAILED，页面访问受阻/超时，0 份 |
| Springer `10.1007/s11814-019-0365-0` | 历史未发现 | NOT_FOUND，未找到明确附件；独立 HTTP 探测另收到 Client Challenge，不能推断论文无 SI |

PLOS 两条本轮路线的 12 个文件 SHA-256 逐个相同，总计 **5,552,640 字节**。旧版安装包 SI 源文件与 `8c1c9ba` 对应源码一致。旧版 PMC 首次因 XML 请求超时失败，另存 20 秒超时的复测后取得 7 份；初次失败保留，不删除。新直连路线首次发现 12 个链接但因未支持的 PLOS 云重定向全部失败，收窄到具体对象的适配完成后，另存复测取得全部文件；不把首次失败改写为成功。原始目录：`F:/AI4S/outputs/AN_SI_COVERAGE_20261103/`。

PLOS 的附件形式和数据托管依据见[官方 Supporting Information 说明](https://journals.plos.org/plosone/s/supporting-information)。云交付规则依据本轮官方文件响应实测，不将其作为永久接口稳定性承诺。该小样本不用于计算跨出版社总体成功率，亦未进行人工科研内容验收。

## 验证及交付

完整测试：**4136 passed、148 skipped、零失败，302.40 秒**，见[全量输出](validation/si-coverage-pytest.txt)。跳过项沿用浏览器实测、外部 OCR、系统符号链接权限等运行条件，不计为通过。安装包从 `C:\Windows\System32` 运行新增用例：**95 passed**，见[安装包测试](validation/si-coverage-installed-pytest.txt)；确认导入的是隔离安装目录。wheel 的 228 个 Python 源文件与工作树逐字节一致，SHA-256：`217181e8ee9aba90fbd8ba5e3aff1eaf1430f14153f7ad61e3f1738ab42576de`。安装包仅用于验证，未发布。

README、中英文工作台手册及本说明同步更新，上一轮 ACS 记录保持原口径。主要文件：`supplements.py`、新增 `supplement_markup.py`、`supplement_formats.py`、`supplement_pages.py`、`supplement_plos.py`、中文状态/诊断及两个测试文件。

全仓 Ruff、compileall、Git 空白检查、修改文档的本地链接及报告断言检查通过。

判断：达到本轮代码合并条件，未合并或发布。剩余访问受限的来源需要合法会话或手动关联，不能用通用规则保证自动取得，也不宣称“所有出版社 SI 全部成功”。
