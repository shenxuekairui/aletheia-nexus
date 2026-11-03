# 非 OA 论文的原生 SI 获取实测（2026-11-03）

[English](SI_NON_OA_BENCHMARK_20261103.en.md)

后续已实现 CLI/UI/MCP 独立 SI 入口，并对本清单重测；新增官方托管路线及真实“失败→成功”结果见[独立 SI 获取验收（2026-11-04）](SI_INDEPENDENT_20261104.md)。下文保留原始基线，探测交付不追记成当时的产品成功。

此前跨出版社测试为取得正文和 XML 参考，使用了 OA/PMC 候选，存在明显选择偏差；不能据此判断非 OA 论文或所有出版社的 SI 能否获取。本轮独立补测 **54 篇元数据标记为 closed 的论文、19 个出版社/品牌分层**，加 4 篇已知 OA 回归对照，全部真实执行，无登录、浏览器、付费 API 或模型调用。产品代码保持 `6c7d587`（产品源码与 `a65cc4b` 相同），没有为测试修改获取逻辑。

**非 OA 正文与 SI 的访问权限必须分开。** 本轮有 4 篇正文未取得，但匿名原生 HTTP 成功下载了对应 SI；当前产品联动流程要求正文先验证，因而这 4 篇在独立探测中成功、在正常流程中仍未开始 SI。探测结果不登记到虚构正文，也不冒充产品功能已完成。

## 冻结协议与实际范围

- [冻结清单](../benchmarks/si_closed_20261103/manifest.json) SHA-256 为 `6b479b1f1c724ae9da929a6c3876256b57ce9fe94fe60e256a42e6d53bd53ef1`，在正文/SI 交付测试前生成。所有 DOI 保留，未按获取结果替换。
- 计划 20 个 DOI 前缀分层：取 Crossref 发表日期 2021-01-01 至 2026-06-30、按发表日期降序的前 40 条 journal-article 记录，排除更正、撤稿、讣告标题。匹配 OpenAlex 唯一 DOI、类型 article/review，并要求 `is_oa=false` 且 `oa_status=closed`。按固定种子 SHA-256 排序、不同期刊优先，每层最多 3 篇。[采样证据](../benchmarks/si_closed_20261103/sampling-evidence.json)记录实际候选数、歧义与来源哈希。
- Science 只有 2 篇符合条件，PNAS 只有 1 篇，Royal Society 的 40 条候选中没有符合条件的论文；因此实际 54 篇、19 个非空分层。没有用 OA 论文补足缺口，也不据此断言这些出版体系不存在非 OA 论文。
- 4 篇 OA 对照来自上一轮已暴露的成功样本，用于检查正常原生流程和网络可用性，不是独立留出集。样本仍受有限候选池、时间段和元数据覆盖影响，不代表各出版社论文的随机总体。
- 元数据 closed 不等于逐篇人工确认的订阅权限，也不证明每篇都有 SI。部分 article 类型可能仍是短评、新闻或不含 SI 的论文。**没有“确有 SI”的独立人工金标准，不能用本轮交付篇数除以全部 54 篇当完整 SI 成功率。**
- Crossref 查询语义见[官方过滤器说明](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/)。OpenAlex 的 OA 定义包含任何免付费、免登录全文，closed 是其余情况，见[官方 OA 说明](https://help.openalex.org/data/works/open-access/)。这些字段可能滞后于源站现状。
- 首次采样阶段部分元数据请求失败，另有 OpenAlex 重复 DOI；这些原始记录保留。随后在交付测试前以有界元数据重试、排除歧义 DOI 重新冻结；成功的原始候选池按哈希复用，未依据 SI 获取结果重选样本。正式测试使用最终清单，不混合早期未执行的清单。

## 两条独立测量路径

1. **正常产品流程**：共享 AcquisitionService、公开来源、浏览器关闭、正文核验后联动 SI。保持真实门禁、来源记录及父文关联。
2. **无正文的独立 SI 探测**：复用现有 ACS Figshare、官方 DOI 页面、显式附件发现、允许域名跳转、流式下载和格式校验。确认官方清单的父文 DOI/题名，或官方页面唯一 DOI 后才请求明确附件；不猜文件名，不执行 JavaScript、不使用账户 cookie、不执行脚本、不解压。保存为未登记文件，没有正文 PDF 哈希，不声称已成为可直接解析的文库附件。

两者用独立进程和结果目录，默认每文件 100 MiB、每篇最多 20 份附件、请求超时 20 秒，每个阶段总时限 200 秒，4 个并发任务、5 GiB 磁盘预算。58 篇全部执行，无超时或预算跳过。独立探测不是新产品下载引擎，只用于区分 SI 可交付性与现有产品的正文前置条件。没有使用机构登录，不能声称已验证授权路线。

## 完整结果

| 分组 | 篇数 | 正文 VERIFIED | 正常流程 SI COMPLETED | 独立取得至少一份 SUPPLEMENT |
| --- | ---: | ---: | ---: | ---: |
| 元数据 closed | 54 | 0 | 0（54 篇均 NOT_ATTEMPTED） | 4 |
| 已知 OA 对照 | 4 | 4 | 4 | 1 |

closed 组正常正文状态为 51 EXHAUSTED、3 AUTH_REQUIRED。4 篇独立成功均未依赖 PMC：

| 论文 DOI | 出版社 | 独立保存 | 实际路径 |
| --- | --- | --- | --- |
| `10.1021/acsami.6c06732` | ACS | 1 PDF，2,329,969 字节 | 官方 ACS Figshare 清单 → Figshare 下载服务 → ACS S3 |
| `10.1021/acs.jpclett.6c01699` | ACS | 1 PDF，3,567,613 字节 | 同上，父文 DOI/题名及官方 MD5 均通过 |
| `10.1007/s11056-026-10197-y` | Springer | 1 DOCX，15,210,079 字节 | DOI 一致的文章页 → static-content.springer.com 明确附件 |
| `10.1007/s43450-026-00780-x` | Springer | 1 PDF，396,492 字节 | 同上，按明确官方链接保存 |

54 篇独立探测的原始状态归类：

| 结果 | 篇数 | 可说明与不能说明的内容 |
| --- | ---: | --- |
| 文件交付成功 | 4 | 已取得明确关联附件；不证明全部 SI 齐全或产品已登记 |
| 页面 HTTP 403 | 34 | 均为 AcquisitionAccessBlockedError；当前环境的公开 HTTP 请求被源站拒绝，不能仅凭 403 区分反爬、权限等原因，也不能证明 SI 文件本身收费 |
| 身份未确认 | 6 | Elsevier 3、IOP 3；收到页面但未满足唯一论文 DOI 门禁，未关联下载 |
| 登录/验证提示 | 6 | Nature 3 为 LOGIN，IEEE 3 为 CHALLENGE；未升级浏览器或账户 |
| 未发现受支持入口 | 4 | Cambridge 3、Springer 1；不能据此证明论文没有 SI |

每层实际结果如下。“取得 SI”只计独立探测实际保存的 SUPPLEMENT，不计正文、审稿或源数据：

| 出版社/品牌 | closed 样本 | 取得 SI |
| --- | ---: | ---: |
| Elsevier | 3 | 0 |
| ACS | 3 | 2 |
| RSC | 3 | 0 |
| Wiley | 3 | 0 |
| Springer | 3 | 2 |
| Nature | 3 | 0 |
| Science | 2 | 0 |
| OUP | 3 | 0 |
| Cambridge | 3 | 0 |
| Taylor & Francis | 3 | 0 |
| SAGE | 3 | 0 |
| BMJ | 3 | 0 |
| IEEE | 3 | 0 |
| IOP | 3 | 0 |
| AIP | 3 | 0 |
| APS | 3 | 0 |
| Royal Society | 0 | 未测，候选池无符合者 |
| Karger | 3 | 0 |
| Biologists | 3 | 0 |
| PNAS | 1 | 0 |

OA 对照的独立探测中，ACS 取得 1 份 SI；eLife 保存 9 份 SOURCE_DATA，仍有未完成项，记录 PARTIAL_DELIVERY；Wiley、Taylor & Francis 的页面路径返回 403。正常产品流程则通过其可用的存档路线，4 篇均完成正文/SI，说明页面可用性与存档可用性确实不同，不能将两路相加。

## 校验、局限与后续重点

本轮独立探测共保存 14 份文件（closed 4、OA 对照 10）。重新计算 SHA-256/MD5，与下载时记录和适用的官方清单比较；Springer 文件重新核对保存 HTML 的唯一 DOI。正常流程已保存附件也重算 SHA-256、核对既有父文检查。**未发现字节或父文证据校验失败。** 这些是工程校验，不是人工科学内容确认，也不能排除未发现附件。

结果暴露三项待完成工作：

- 产品需要明确支持“正文暂不可取得时的独立 SI 发现/交付”，同时设计真实的关联状态；本轮探测不代表该产品能力已上线。
- 继续增强官方仓库/API、HTML 中转、页面身份和明确附件入口。34 个 403 不应直接解释成“所有非 OA SI 都需机构权限”。
- Royal Society 先前的 3 篇审稿文件样本另有明确 Figshare 补充材料引用，当前原生未跟进。已核对同版本 PMC XML 与公开 Figshare `resource_doi`，见[补充材料清单证据](validation/si-royal-external-inventory-20261103.json)。这属于发现遗漏；原来的 COMPLETED 状态与计数保留，但不能视为完整取得 SI。其中一份 ZIP 约 184 MiB，还超过默认 100 MiB 上限。本次没有把这些 metadata inventory 计为交付成功。

只增加测试工具、冻结数据及报告。Ruff、脚本编译、CLI 参数、冻结分类/哈希、已完成目录无网络恢复和实际 58 篇执行已检查；产品源码未变，本轮未重跑完整产品套件。上一轮 **4178 passed / 148 skipped** 与独立安装 **107 passed** 是旧轮记录，不能冒称本轮新增执行。

**判断：非 OA 公开原生测试已完成，尚不能宣称原生路线可取得所有 SI；该总体功能不满足全面验收条件。** 这不撤销此前已修复的标题、格式等具体回归结果，也不把权限问题归咎于格式。没有合并或发布。

## 证据与复现

[完整机器审计](validation/si-closed-20261103.json)、[逐篇 CSV](validation/si-closed-cases-20261103.csv)保存全部 58 篇结果。原始 API 采样、HTML、正文、附件、逐请求状态、阶段 stdout 在本机 `F:/AI4S/outputs/AN_SI_CLOSED_20261103_final/`；较早采样及预检独立保存，没有提交论文全文或媒体。

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/benchmark_si_closed.py run --manifest benchmarks/si_closed_20261103/manifest.json --output F:/AI4S/outputs/si-closed-new/run
python scripts/summarize_si_closed.py --root F:/AI4S/outputs/si-closed-new/run
```

脚本会核对产品源码；请使用新输出目录保留历史。重新采样可运行 `scripts/sample_si_closed.py --output <新的目录>`，但新 API 返回不等于本轮冻结清单，必须另作记录。
