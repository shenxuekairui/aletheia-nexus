# 原生 SI 路线修复与复测（2026-11-03）

[English](SI_NATIVE_CORPUS_FIX_20261103.en.md)

后续核对更正：Royal Society 三篇 `COMPLETED` 样本只保存了审稿文件；同版本 PMC XML 还引用 Figshare SI/数据，当前原生未跟进，属于发现遗漏。原始状态和计数保留，不能视为完整取得 SI。[清单证据](validation/si-royal-external-inventory-20261103.json)与[非 OA 独立实测](SI_NON_OA_BENCHMARK_20261103.md)补充了这些限制；本报告的合并判断仅针对当时列明的具体修复，不代表原生 SI 全面验收。

本轮优先修复[120 篇实测](SI_SCALE_BENCHMARK_20261103.md)暴露的原生获取问题，产品代码为 `a65cc4b`。**原生路线可以覆盖更多公开资源，但不能保证取得所有出版社的全部正文和 SI。** 需要订阅或登录的资源应使用有权限的官方接口或会话；未公开、已删除、版本无法核实或源站拒绝交付的文件仍可能失败。

这不是仅由实现方式决定：Crossref 的全文链接仍可能要求订阅、登录或许可，见[官方访问说明](https://www.crossref.org/documentation/retrieve-metadata/text-and-data-mining/#access-and-rate-limits)；PMC 也明确只有部分内容可供自动获取和复用，见[官方开放子集说明](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/)。

## 修复范围

| 问题 | 修改及边界 |
| --- | --- |
| PMC 标题误拒绝 | 将 `<i>`、`<sup>`、`<sub>` 等标记转为可见文本，再按原有 Unicode/标点规则严格比较。保留原始来源；不采用模糊匹配，DOI、PMCID、版本、开放状态和撤稿门禁继续有效。诊断单列失败条件。 |
| 文件名与实际格式不一致 | 强字节签名与受限 ZIP 成员识别优先，可将实际为 PNG 的 `.jpg` 保存为 `.png`、实际 OOXML 的 `.doc` 保存为 `.docx`。记录声明/检测格式及纠正标志；不改写文件内容，不将无效 OOXML 降级为通用 ZIP。 |
| 格式缺口 | 增加 MPG/MPEG、RAR 和 Python 文本附件保存。检查基本签名或文本边界，不执行脚本、不自动解压、不声称这些文件已解析。 |
| 空 JATS 占位节点 | 仅当完全空的 `local-data` 节点在同一继承语境已有明确、合法的 SI/源数据文件时，记为占位诊断。真正缺链接、有描述但无文件、其他语境或只有占位节点仍报覆盖不完整。 |
| 旧版 PMC 链接 | 官方 NCBI 域名下的 `articles/instance/<数字>/...` 可用于发现 PMCID；正文仍由官方清单获取并核对 DOI 与实际 PDF，不能把链接中的 SI 当正文。 |
| 原生 HTTP 回退中的站点链接 | 没有文件证据的通用审稿/帮助链接不再作为文件候选；保留明确文件、受支持 MIME、下载属性和明确下载端点。覆盖此前 IOP RSS、Cambridge 帮助页形态；这不是完整的出版社 HTML 路线重新验收。 |

CLI、工作台、MCP 继续使用共享获取和附件服务，没有增加另一套下载引擎、数据库或执行器。正文验证后联动 SI、仅补 SI、来源/哈希复用和独立附件角色保持原有流程。

## 真实网络复测

使用原冻结清单中的同一批 120 篇、26 个出版社/品牌分层，未替换 DOI；原清单 SHA-256 保持 `a4fbd89422feeef92ed3c58b06d11a1f2c4e2eacd2ff74a0b8c90742c0011790`。本轮单列原生流程，不再对全部样本额外运行纯出版社 HTML 实验。原生流程仍允许产品正常的 HTTP 回退。每文件容量采用产品默认 **100 MiB**，因此不能直接与首轮 **16 MiB** 的结果计算提升率。

另外从首轮 104 篇阳性标记组中取全部 27 篇非 COMPLETED 样本，在独立旧代码检出 `1c14dce` 上按同样 100 MiB 上限实测。其产品源码与 `ada8b63` 相同，执行清单及实际检出版本分别记录。旧组 2 个进程、新组 4 个进程；均为公开 HTTP、20 秒请求超时、最多 20 份附件、240 秒每篇，无浏览器、登录账户或模型调用。属于已暴露样本回归，不是独立留出集或同时同网络条件的因果实验。

首次新组后半段出现全局 TLS 故障：从 `073` 起连续 40 篇新正文只有 ConnectError，8 篇历史正文的 SI 也连接失败；`071`、`072` 的 SI 已受影响。NCBI、Europe PMC、Figshare 和 example.com 独立探测均为 `SSL: UNEXPECTED_EOF_WHILE_READING`，已记录的本地代理路径也失败。该轮原始结果为 66 COMPLETED、1 PARTIAL、12 FAILED、1 NOT_FOUND、40 NOT_ATTEMPTED，完整保留在 `current/run` 与 `audit-final.json`。没有关闭证书校验或修改网络设置。

随后网络恢复，2026-11-03 12:37:36 UTC 的四服务探测均返回 200。用**相同清单与代码、全新输出目录**重新执行全部 120 篇，同时重跑旧版 27 篇，以下均为这次完整独立复测的原始结果，不是从不同运行拼接的分数：

| 分组 | 篇数 | 正文已验证 | 至少一份 SUPPLEMENT | 附件流程 COMPLETED |
| --- | ---: | ---: | ---: | ---: |
| HAS_SUPPL:Y | 104 | 104 | 96 | 99 |
| HAS_SUPPL:N 对照 | 8 | 8 | 0 | 0 |
| 历史困难样本 | 5 | 5（复用） | 0 | 0 |
| 历史成功回归 | 3 | 3（复用） | 3 | 3 |

全部正文为 **112 VERIFIED、8 EXISTING_VERIFIED**；SI 为 **102 COMPLETED、4 NOT_FOUND、12 FAILED、2 INTERACTION_REQUIRED**。阳性标记组的流程完成率为 99/104（95.2%），不等于人工确认的 SI 完整率：COMPLETED 只表示已发现附件处理完成；部分只有源数据/审稿等角色。8 篇对照无附件登记，但多数回退页面受阻，不能据此推断全站误报率。样本依旧偏向 OA/PMC 和生物医学，26 个品牌分层也不等于 26 家独立公司。

共保存 **218 份、218 个不同 SHA-256** 的附件，覆盖 **17 种扩展名**；193 SUPPLEMENT、21 SOURCE_DATA、3 PEER_REVIEW、1 REPORTING_SUMMARY。逐项重算字节哈希，核对父文 DOI、正文哈希、来源记录哈希，无失败。当前 XML 主文范围参考中未发现 COMPLETED 样本的文件数短缺；9 篇独立 XML 查询不可用，另 8 篇历史样本不含该参考。计数检查不是同版本或人工科学内容金标准。

**同为 100 MiB 的 27 篇问题回归：旧版 8 COMPLETED，新版 24 COMPLETED。** 以下列出代表性实际交付，全部 27 篇状态保留在机器审计中：

| 样本 | 同容量旧版 → 新版 | 实际结果 |
| --- | --- | --- |
| 017 IEEE | INTERACTION_REQUIRED → COMPLETED | 标记标题恢复，1 PDF |
| 025 Biologists | 正文 EXHAUSTED → 正文 VERIFIED、SI COMPLETED | 旧版 PMC 链接识别，1 PDF |
| 030 Wiley | PARTIAL → COMPLETED | 7 份 DOCX/MP4，空占位节点单列 |
| 036 PNAS | FAILED → COMPLETED | 标记标题恢复，1 PDF |
| 040 Taylor & Francis | PARTIAL → COMPLETED | 1 DOCX、1 PNG；原声明 JPG，文件字节保持 |
| 041 SAGE | FAILED → COMPLETED | 标记标题恢复，1 DOC |
| 050 PeerJ | FAILED → COMPLETED | 1 RAR，未解压 |
| 068 BMJ | FAILED → COMPLETED | 标记标题恢复，2 PDF |
| 076 PeerJ | FAILED → COMPLETED | 1 Python 文件，未执行 |
| 082 Wiley | PARTIAL → COMPLETED | 空占位诊断，1 DOCX |
| 085 Science | FAILED → COMPLETED | 标记标题恢复，PDF + ZIP |
| 093 SAGE | PARTIAL → COMPLETED | 2 DOCX，其中一份原声明 DOC |
| 102 PeerJ | FAILED → COMPLETED | 标记标题恢复，1 XLSX |
| 103 Biologists | 正文 EXHAUSTED → 正文 VERIFIED、SI COMPLETED | 1 PDF + 11 XLSX |
| 104 Copernicus | FAILED → COMPLETED | 标记标题恢复，1 PDF |

`028 ACS` 首次受影响轮次只有 PDF + 3 MPG，另一个对象 403；网络恢复后的完整运行通过官方 PMC 清单取得 PDF + **4 MPG** 并 COMPLETED，先前 PARTIAL 记录没有修改。其在另一来源清单下保存副本属于新来源登记，不冒充已有文件复用。

阳性标记组剩余 5 篇非完成，逐项原因如下：

- `066 Taylor & Francis` 和 `069 IEEE`：文件 HTTP 200 后传输网络失败。另在完整文库副本中补测均 COMPLETED，分别保存 ZIP、MP4；完整组仍保留 FAILED，不将补测拼入 99/104。
- `045 AIP`、`097 AIP`：当前 XML 没有 supplementary-material 节点，出版社回退 403。前者的数据可用性声明要求向作者索取，后者链接到 XFEL 外部数据集 DOI；均不能直接当作可下载 SI 文件。HAS_SUPPL:Y 不能作为主文 SI 金标准，也不能据此断言出版社原页没有 SI。
- `008 PLOS`：NOT_FOUND；额外 DOC/DOCX 属审稿子文档，不登记为主文 SI。

5 篇历史困难样本仍未取得 SI：Wiley/RSC 页面拒绝访问，Springer 未发现受支持入口，MDPI/Elsevier 页面身份未确认。不能把新取 PMC 正文成功与旧来源正文补 SI 混为一谈。

对格式纠正/新增格式选取 5 篇，在完整文库副本上实际执行复用：**11/11 REUSED**，覆盖 PNG、RAR、MPG、Python 和 DOCX；所有原文库文件与复制后正文/来源记录保持不变。另做 4 篇已知页面回退回归：Cambridge COMPLETED（1 PDF）、PLOS NOT_FOUND，IOP 一篇数据页跳转超出允许文件域名而拒绝、一篇遇验证挑战；均无 RSS 登记。这只是具体缺陷回归，不能代表出版社 HTML 普遍可用。

机器数据见[原生修复审计](validation/si-native-corpus-20261103.json)和[完整 120 篇 CSV](validation/si-native-corpus-cases-20261103.csv)。[新组清单](../benchmarks/si_publishers_20261103/native-current-manifest.json)、[旧组清单](../benchmarks/si_publishers_20261103/native-baseline-manifest.json)保留各自源码版本与上限。原始正文、附件、receipt、HTTP、XML 和 stdout 位于 `F:/AI4S/outputs/AN_SI_NATIVE_FIX_20261103/`；最终完整组为 `recovered/run` 与 `recovered-baseline/run`，首次网络故障组仍在 `current/run`。没有提交全文/媒体或覆盖旧版历史。

复现新组时设置当前源码，再用新输出目录执行；脚本会拒绝与清单产品源码不一致的检出：

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/benchmark_si_publishers.py run --manifest benchmarks/si_publishers_20261103/native-current-manifest.json --output F:/AI4S/outputs/native-retest/run
python scripts/summarize_si_publishers.py --root F:/AI4S/outputs/native-retest
```

8 篇历史正文路径需要先在本机恢复；缺失应如实报告。不要用占位文件替换，也不要复用已有输出目录覆盖旧结果。

## 自动化与安装验证

- 新增 42 个测试场景：标题标记、各身份门禁的准确诊断、空占位边界、真实格式纠正、非法格式拒绝、仅存储不执行、复用与原始来源保持、RSS/帮助页排除、官方旧版 PMC 链接及错误 DOI 拒绝。
- 完整套件：**4178 passed、148 skipped，293.97 秒**。[完整输出](validation/si-native-corpus-pytest.txt)。跳过项保持测试套件原有条件，不能称为全部测试均执行。
- wheel 包含的 228 个 Python 文件与 `a65cc4b` 产品源码一致，SHA-256 为 `6b020cce18f7aec04ae0e6f984fd503dbfeb52a8012a2383ff2cdc1a9e227389`。
- 独立目录安装该 wheel，从 **C:/Windows/System32** 运行原生附件、PMC 正文及获取联动相关测试：**107 passed，2.76 秒**。[安装输出](validation/si-native-corpus-installed-pytest.txt)。这是已安装包入口/路径与获取逻辑测试，不冒充本轮手工启动了工作台 GUI。
- Ruff 与 Git 空白检查通过。未合并、未发布。

## 验收判断

**本次限定范围的原生缺陷修复达到合并条件**：完整套件、独立安装、同容量旧版对照、120 篇实测与格式复用检查均完成，没有发现本轮修复带来的身份门禁放宽或文件完整性失败。仅推送供审阅，没有执行合并或发布。更广泛的“所有出版社 SI 完整获取”目标仍未通过，5 篇历史困难样本与受限页面回退仍待增强；不能承诺仅靠原生 HTTP 即可取得所有资源。
