# 120 篇跨出版社 SI 通用实测（2026-11-03）

[English](SI_SCALE_BENCHMARK_20261103.en.md)

已完成 **120 篇、26 个出版社/品牌分层**的真实网络测试。被测产品为 `ada8b63`，本轮没有修改产品获取引擎，也没有用夹具代替网络。**当前不建议按跨出版社通用 SI 目标合并：已确认的 RSS 误关联和网页/文件混淆应先修复。** 先前小样本报告的合并判断不适用于本轮扩大后的验收口径。

## 冻结协议与范围

- [冻结清单](../benchmarks/si_publishers_20261103/manifest.json)在任何正文/SI 测试前生成，SHA-256 为 `a4fbd89422feeef92ed3c58b06d11a1f2c4e2eacd2ff74a0b8c90742c0011790`。104 篇为 Europe PMC `HAS_SUPPL:Y`，每个分层 4 篇；另有 8 篇 `HAS_SUPPL:N` 对照和 8 篇已知历史样本。Nature 与 Springer/BMC 属同一出版集团，26 个分层不等于 26 家独立公司。
- 从 DOI 前缀对应的前 40 条 core 记录中，固定 2021–2024 首次发表日期、OA/PDF 可用条件，用固定种子的 SHA-256 排序、不同期刊优先选取。没有依据下载成败替换样本。候选池与排序并非出版社全部论文的随机抽样，且明显偏向 Europe PMC 收录的开放获取、生物医学材料。[采样指纹](../benchmarks/si_publishers_20261103/sampling-evidence.json)保留原查询与本机原始池位置。
- `HAS_SUPPL` 是广义附加材料标记，可能仅指审稿历史、作者回复或源数据，**不是“正文一定有 SI”的人工金标准**。测试后核对 XML 的主文/子文档归属，未改动冻结清单、首轮状态或分母。
- 正常入口：112 篇新获取正文并联动原生 SI；8 篇历史文献只在独立副本上补 SI。再对同篇执行出版社 DOI 入口的纯 HTML 发现/下载，显式关闭 PMC/Figshare 清单回退。没有已验证正文的 2 篇只做页面发现尝试，不伪造正文来下载或关联 SI。
- Windows Python 3.14.3，公开 HTTP，无浏览器、账户登录或模型调用；每次网络超时 20 秒、最多 20 个附件、首轮每文件 16 MiB，每篇总时限 240 秒，4 个独立进程。全组耗时 924.19 秒，记录 1512 次 HTTP 请求（含独立 XML 参考查询）。120 篇均执行，无总时限或磁盘预算跳过；2 篇正文未验证，其后页面 HTTP 拒绝抛到验证脚本，保留 `EXCEPTION` 记录，未算通过。

接口语义依据 [Europe PMC 官方 REST 说明](https://dev.europepmc.org/RestfulWebService)及[查询字段参考](https://europepmc.org/docs/EBI_Europe_PMC_Web_Service_Reference.pdf)。只使用其公开文献元数据与 XML；未将本地论文上传。

## 首轮结果

| 分组 | 篇数 | 正文已验证 | 至少一份 SUPPLEMENT | 原生附件流程 COMPLETED | HTML 路线至少一份 SUPPLEMENT | HTML 路线 COMPLETED |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HAS_SUPPL:Y | 104 | 102 | 84 | 77 | 9 | 3 |
| HAS_SUPPL:N 对照 | 8 | 8 | 0 | 0 | 0 | 0 |
| 历史困难样本 | 5 | 5（复用） | 0 | 0 | 0 | 0 |
| 历史成功回归 | 3 | 3（复用） | 3 | 3 | 1 | 0 |

原生列允许正常产品的 PMC、ACS Figshare 等可信清单；HTML 列单独评估 DOI 文章页的通用规则，不能把两列相加当作成功率。`COMPLETED` 只说明程序发现的附件均处理完成，可能仅包含审稿文件等其他角色，不等于正文 SI 已全部取得，也不是科学内容确认。8 篇对照没有被登记为 SI；其中多数页面回退受限，因此不能据此估计全站点误报率。

26 个分层的 104 篇首轮结果：

| 出版社/品牌分层 | 篇数 | 正文 | 原生 SUPPLEMENT 篇 | 原生 COMPLETED 篇 | HTML SUPPLEMENT 篇 | HTML COMPLETED 篇 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Elsevier | 4 | 4 | 4 | 4 | 0 | 0 |
| ACS | 4 | 4 | 3 | 1 | 0 | 0 |
| RSC | 4 | 4 | 4 | 4 | 0 | 0 |
| Wiley | 4 | 4 | 4 | 2 | 0 | 0 |
| Springer BMC | 4 | 4 | 4 | 4 | 2 | 2 |
| Nature | 4 | 4 | 4 | 4 | 1 | 1 |
| Science | 4 | 4 | 3 | 3 | 0 | 0 |
| PLOS | 4 | 4 | 3 | 2 | 2 | 0 |
| MDPI | 4 | 4 | 4 | 4 | 0 | 0 |
| PNAS | 4 | 4 | 3 | 1 | 0 | 0 |
| Frontiers | 4 | 4 | 3 | 3 | 0 | 0 |
| OUP | 4 | 4 | 4 | 4 | 0 | 0 |
| Cambridge | 4 | 4 | 4 | 4 | 4 | 0 |
| Taylor Francis | 4 | 4 | 4 | 3 | 0 | 0 |
| SAGE | 4 | 4 | 3 | 2 | 0 | 0 |
| BMJ | 4 | 4 | 3 | 3 | 0 | 0 |
| IEEE | 4 | 4 | 3 | 3 | 0 | 0 |
| IOP | 4 | 4 | 3 | 3 | 0 | 0 |
| AIP | 4 | 4 | 2 | 2 | 0 | 0 |
| APS | 4 | 4 | 4 | 4 | 0 | 0 |
| eLife | 4 | 4 | 4 | 3 | 0 | 0 |
| Karger | 4 | 4 | 4 | 4 | 0 | 0 |
| Royal Society | 4 | 4 | 1 | 4 | 0 | 0 |
| PeerJ | 4 | 4 | 1 | 1 | 0 | 0 |
| Biologists | 4 | 2 | 2 | 2 | 0 | 0 |
| Copernicus | 4 | 4 | 3 | 3 | 0 | 0 |

阳性标记组有 87 篇取得某类附件，其中 84 篇包含 SUPPLEMENT。原生阶段共保存 176 份附件结果（152 SUPPLEMENT、20 SOURCE_DATA、3 PEER_REVIEW、1 REPORTING_SUMMARY）；HTML 阶段保存 44 份（含下文两份误分类 RSS）。220 条保存结果对应 181 个不同 SHA-256，不能称为 220 个独立文件。逐一重算 SHA-256 并核对父文 DOI、PDF 哈希、来源记录哈希，**无字节/父文记录校验失败**。语义误关联仍可通过这些检查，因此单列审计。

原生阶段实际扩展名为 PDF、DOC、DOCX、XLS、XLSX、PPTX、ZIP、MP4、JPEG、GIF、CIF，涵盖一篇多份、视频和数据包；源数据/审稿文件角色分别保留。正文来源中 113 篇为 PMC，另有 5 篇来自其他真实来源；2 篇未取得正文。此分布不能证明出版社页面普遍可用。

## 100 MiB 容量诊断与复用回归

以下是看到首轮结果后选取的诊断组，不是新盲测，也没有替换首轮 16 MiB 状态。7 篇仅提高到产品默认的每文件 100 MiB，继续复用已经验证的正文、使用独立文库；20 份数量及 20 秒网络上限保留。

| 样本 | 首轮 | 100 MiB 复测 | 保存份数 | 超过 16 MiB 的文件 |
| --- | --- | --- | ---: | ---: |
| 030-Wiley | PARTIAL | PARTIAL | 7 | 2 |
| 054-ACS | PARTIAL | COMPLETED | 2 | 1 |
| 062-PNAS | PARTIAL | COMPLETED | 4 | 3 |
| 073-eLife | PARTIAL | COMPLETED | 16 | 1 |
| 080-ACS | FAILED | COMPLETED | 3 | 3 |
| 086-PLOS | PARTIAL | COMPLETED | 5 | 1 |
| 088-PNAS | PARTIAL | COMPLETED | 3 | 1 |

6 篇为 COMPLETED，Wiley 一篇为 PARTIAL：7 个明确文件均保存，但仍有缺少链接的节点诊断。共保存 40 份，其中 12 份超过 16 MiB，额外覆盖 MOV/TIF。不能将这些首轮容量限制解释为出版社获取能力缺失。

另从首轮成功样本按扩展名覆盖选出 7 篇（非独立留出集），复用检查 **44/44 REUSED**，覆盖全部 11 种原生阶段扩展名；SHA/父文检查及源文件保持检查全部通过。所有 100 MiB 和复用组的正文 PDF、来源记录均保持，旧附件没有覆盖。详细结果见[后续诊断数据](validation/si-scale-followup-20261103.json)。

## 确定问题、限制及核对更正

1. **通用语境误关联，应优先修复。** `018-IOP` 与 `044-IOP` 的期刊 RSS 1.0/RDF 被保存成 PEER_REVIEW。文件内容的 RSS 命名空间、期刊 feed URL、SHA-256 均保留在[机器审计](validation/si-scale-observations-20261103.json)。这是真实误分类，不计为正确科研附件。HTML 链接在宽泛的审稿语境下还会请求站点帮助页、登录入口；需要收紧语境边界和文件证据。
2. **目录网页不能作为附件文件处理。** PLOS `008` 的 peerReview 页面以 `text/html` 返回后被交给文件格式判断，报 `attachment_type_not_confirmed`；IOP `/data` 也出现网页/文件混淆。应识别目录页、继续有限跟进或明确不支持，不能用 HTTP 200 证明文件交付。
3. **格式支持缺口。** ACS `028` 的 4 个 MPG 视频、PeerJ `050` 的 RAR、`076` 的 Python 源码未保存；PDF 或其他成功文件仍保留。建议后续按实际格式补充受限保存能力，不执行脚本、不自动解压。现有格式失败不掩盖为完整取得。
4. **源文件扩展名与内容不一致。** Taylor & Francis `040` 的 `.jpg` 实际开头为 PNG 签名，已用独立有界 HTTP 探测确认；按当前声明格式拒绝是保守门禁行为。[头部诊断](validation/si-scale-image-header-20261103.json)独立保存，未将它计为下载成功。
5. **身份/版本门禁和网络限制单列。** IEEE、PNAS、SAGE、BMJ、Science 等部分样本被 PMC 身份/版本/开放状态核对拒绝，页面回退受阻；不能为提高分数放宽门禁。2 篇 Biologists 正文失败。历史 5 篇困难样本仍未取得 SI；新获取正文走 PMC 后的成功不能代替旧来源正文补取的结果。
6. **PLOS 初步“漏 SI”判断已更正。** `008` 的两份 DOC/DOCX 属于 `aggregated-review-documents`、`author-comment` 子文档；`034` 和 `060` 的额外条目也属于作者回复。原始全树 XML 参考计数保留，最终审计增加主文/子文档区分，排除它们后没有发现原生 COMPLETED 样本的主文 supplementary-material 文件数短缺。此结果仍不是同版本或人工内容金标准。原生路线排除审稿子文档是正确行为。

## 复核、复现与交付

[逐篇 CSV](validation/si-scale-cases-20261103.csv)与[完整机器汇总](validation/si-scale-observations-20261103.json)包含全部 120 篇状态，失败与异常没有删去。原始正文、SI、来源 receipt、逐请求 HTTP 状态、XML、脚本指纹和 stdout 在本机 `F:/AI4S/outputs/AN_SI_SCALE_20261103/`，没有把全文/媒体提交到仓库。

运行已冻结的同源代码（源码有差异会拒绝），使用新的输出目录：

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/benchmark_si_publishers.py run --manifest benchmarks/si_publishers_20261103/manifest.json --output F:/AI4S/outputs/si-scale-rerun/run
python scripts/summarize_si_publishers.py --root F:/AI4S/outputs/si-scale-rerun
python scripts/benchmark_si_followup.py --root F:/AI4S/outputs/si-scale-rerun
```

清单包含 8 篇历史样本的本机正文路径；跨机器运行须先恢复对应来源文件，缺失必须报告，不可用占位正文补齐。API 元数据与网络会改变，新的运行需要独立记录。首次执行脚本 SHA 在采样证据中；提交的测试工具随后仅补充源码一致性、恢复及并发计数保护，未更改被测产品或重写首轮输出。

本轮只增加实测工具、冻结清单及中英文报告，不修改产品获取逻辑。Ruff、脚本编译、CLI 参数和已完成目录的无网络恢复检查通过；没有为这些测试工具重跑完整产品套件。上一轮 `4136 passed / 148 skipped` 保持原测试记录，不冒称本次新增通过。

**验收判断：大规模测试已完成，跨出版社通用 SI 功能验收暂不通过。先修复确定的误关联与网页/文件区分，再在同一清单上独立复测；格式扩展和可信入口增强另列。** 没有合并或发布。
