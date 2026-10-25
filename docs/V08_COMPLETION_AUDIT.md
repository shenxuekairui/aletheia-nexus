# v0.8 需求逐项交付审计

2026-10-26，开发版本 `0.8.0.dev0`。本次重新对照原任务书、当前实现、测试和保存的
真实运行记录，检查是否还有功能空壳或未验证的必要路径。论文、图像、密钥和完整
科研结果保存在用户本地；公开仓库仅包含代码、自制夹具、示例配置和汇总报告。

结论：阶段 1–5 的核心功能已实现，阶段 6 的工程检查、真实执行与科学评阅已执行。
当前自动提取的科研性能未达到初步目标，不能宣布科学验收通过。可交付开发分支供
审阅，继续保持草稿 PR；不合并、不打标签、不发布正式版本。

## 判定依据

原任务书将 90% 字段查准率、约 80% 完整记录正确率、95% 实际证据支持率称为
初步目标，并要求报告失败。实际在提取前冻结的 `fresh-holdout/review-protocol.json`
也明确：这些是 preliminary targets；未达到时必须披露，不能声称目标已验证。
本审计不降低这些数字、不重算分母、不删除失败，也不把无限重复调参作为开发结束条件。
“功能已实现”“工程检查通过”“评测已执行”“科研目标已达到”分别判断。

用户随后授权 GPT 逐项核对原文替代人工，本轮参考与修订因此全部保持 assistant
标记。人类专家标准和人工核对耗时没有测得，不能由助手执行时间或模型分数替代。

## 功能、证据及限制

下表测试名来自 `tests/processing/`，除特别说明外使用自制 PDF / Mock；真实执行
证据另列，不能将两者混为一谈。运行与逐项科研错误详见 [验收记录](V08_ACCEPTANCE.md)。

| 任务书要求 | 实现与工程证据 | 真实执行 / 边界 |
| --- | --- | --- |
| 一、二、九、阶段 1：审计与复用 | [设计](V08_DESIGN.md)记录 v0.7.3 基线 2204 通过；复用来源门槛、ParsedArtifact、Corpus、evidence、write_ai_export；EvidenceJudge 保持原职责 | 没有重写 v0.7、改旧标签或引入数据库；PARSED 不解释为科学正确 |
| 5.1：一个真实可替换 Provider | `provider.py` 的 Provider 协议与 DeepSeekProvider；`test_real_adapter_with_mock_http_and_cli_export` | 实际 DeepSeek Flash 文本与图像调用；不是只预留接口 |
| 5.1：结构输出、超时、限流、重试与错误 | 闭合响应契约、本地验证；`test_error_classification_and_bounded_retry`、`test_http_budget_includes_retries`、`test_invalid_and_refused_output_not_blindly_retried` | 实际保留网络、截断、坏 JSON、坏引文；格式有效不能证明科学语义 |
| 5.1：模型、提示、用量、费用与密钥 | 调用清单保存配置/提示指纹/输入哈希/耗时/可得 Token；`test_call_reservation_is_durable_before_network`、`test_rejected_candidate_diagnostics_redact_secret` | 密钥仅环境变量；658 次历史 HTTP，估算费用与未知用量分开；本次审计零模型调用 |
| 5.1、六 A、11.1：明确启用与本地模式 | Task allow_remote 与 CLI --allow-remote 双开关；`test_both_remote_gates_required`、`test_local_never_touches_provider_or_environment` | 本地模式准备材料、原有功能可用；不会伪造提取表 |
| 5.2：通用任务与字段 | `contracts.py`；organize/extract/procedure/compare 共用引擎；string/number/integer/boolean/string_list、单位/范围/规则、版本化 JSON | 三类任务实际执行；没有材料合成专属业务模型；示例字段可改 |
| 5.3 第一层：上下文、页面、SI、备注 | `materials.build_package` 复用检索/完整页证据；`test_requested_page_adds_real_material_then_reuses_final_result`、`test_linked_si_is_grouped_with_main_and_keeps_local_page_numbers` | 实际首页→第 1/6/7 页补充；实际正文/SI 联读；只访问任务列出的文件 |
| 5.3 第二层：解析修正 | 内容流资源保护、矢量文字预算、主要字体变化处段落边界；`tests/content/test_paragraph_font_boundaries.py` | 三篇新文件重解析，13 处边界恢复；旧文件不变；未证明科学准确率提高 |
| 5.3 第三层：处理策略 | 有界结构/引用反馈；补页后只传当前材料与待查问题，保留旧候选 | prompt v8；字段拆分、阶段拆分、额外模型评审等无稳定收益方案未默认采用 |
| 5.3：版本化包与人工读法覆盖层 | task-package/v1，builder 3；来源/PDF/解析身份、块、页、图像、备注、原值/修订值/理由/作者/时间、父包和配置指纹 | `test_corrections_and_human_revision_preserve_history`；原 PDF 与规范工件只读，补页不等同解析改写 |
| 5.3：不足原因与停止条件 | material_insufficient/parser_problem/strategy_problem/source_ambiguous/not_reported/access_restricted/conflict；最多 3 轮补充、1 轮结构修复及资源总预算 | `test_useless_repeated_requests_stop_and_remain_partial`、`test_failure_after_supplement_preserves_previous_candidate`；原页仍不够时保留 PARTIAL |
| 5.4：内容整理 | 用户目标/字段/规则生成笔记、方法/结果/局限、支持/反对材料；nature 区分 reported/author_interpretation/ai_synthesis | A 开发集 19/20 篇保存；不是只做固定摘要，也不是 19 篇均科学正确 |
| 5.5：表格与字段含义 | 原值、单位、context、status、来源；不同字段定义拒绝合并；CSV 防公式注入；`test_export_combines_modes_but_not_different_field_meanings` | 真实多论文表及离线导出；无自动换算，不为填表猜值 |
| 5.6：实验阶段和有序步骤 | subject/stage/steps/order/step_ids；未报告/歧义/规范化/未确认区分；include_steps=false 有 schema 与本地校验 | C 包含合成和性能测试，开发集 20/20 保存；模型仍有阶段错配，不能称自动复现级可靠 |
| 5.7：跨文献问题与比较 | `_compare` 使用单篇结果及原始证据；`test_compare_uses_original_citations`、`test_comparison_sends_images_checks_budget_and_keeps_individual_results` | 八篇比较稿已逐项原文复核、21 次助手修订；原自动结果与失败论文保留 |
| 5.8：保存、重读、导出和复用 | result/manifest/task JSON，Markdown、table.csv、claims.csv、records.jsonl、claims.jsonl；独立 export/revise 命令 | 三类单篇资料和八篇比较稿均实际导出；只含 claims 的比较也有可编辑 CSV |
| 六 B/C：混合与原页路径 | parsed 文本基线、hybrid 文本+图像、direct 指定页图像且无需解析文本；`test_direct_page_images_need_no_parsed_artifact` | 同十篇、A/B/C、三路径冻结对照均执行；整篇任意长度 PDF 上传是明确未实现的可选范围 |
| 六、5.3：独立文本/图像选页 | 新增 `test_hybrid_image_only_page_is_citable_without_expanding_text_scope`；文本页与图像页覆盖取并集，文本块选择不扩大 | 审计先重现 FAILED，再修复通过；视觉读法仍为 visual-unverified，不能引用未发送的解析块 |
| 七：来源与状态 | 精确引文、源哈希、块/页/bbox、模型配置及 revision history；source_located 不等于支持；`test_invalid_model_references_and_confirmation_rejected` | v7 全部非空输出定位 268/268，但支持仅 247/268；两者单独报告 |
| 七：修改不伪装人工确认 | `revise_result` 新建子结果，保留 before/parent/reason；`test_assistant_revisions_revoke_confirmation_and_cannot_self_confirm` | 三单篇 26 次、八篇比较 21 次助手修订均 confirm=false；不计为自动准确率提升 |
| 八：批量与失败恢复 | 逐文献检查点、失败隔离、缓存、KeyboardInterrupt 记录；`test_failed_document_recovers_without_repeating_success`、`test_interruption_checkpoints_and_resume` | 实际 A 12→14→19/20、C 14→17→20/20；实际有 4 篇缓存零调用复用 |
| 八：不错误复用 | 任务/材料/Provider/提示指纹、源哈希复核；`test_changed_inputs_never_reuse_cache`；新 builder 隔离旧输入 | 旧结果仍可离线验证/导出；新任务变化不能伪装恢复成功 |
| 八：累计成本 | 每 HTTP 前持久预留，已知用量结算，未知保留；评测脚本文件锁；`test_cost_ledger_lock_excludes_parallel_spend_and_releases` | 同一累计台账保守 63.968134/100 CNY；是配置费率估计，不能冒称服务商账单 |
| 九、11.1：兼容与工程回归 | v3 工件格式不变、v2 兼容、旧后端可不提供字体；完整测试、冻结夹具、干净 wheel 和 CI 分别记录 | 真实论文未进入公共夹具；当前本地与远端测试快照必须分别识别 |
| 11.2–11.3、阶段 6：真实评测 | 冻结计划/原文参考/字段及完整记录分母、全部实际输出审核、独立计定位与支持 | 20 篇开发集 + 另 10 篇留出对照；GPT 参考，领域分布窄；留出后已用于调参，不能再称新留出 |

## 本轮审计发现并修复的问题

hybrid 的 `pages=[1]`、`image_pages=[2]` 原来会发送第 2 页图像，却仍将该页记作遗漏，
拒绝其视觉引用并浪费一次修复机会。新测试先真实复现 FAILED。修复仅使包的
`pages_requested` 表示文本或图像已提供的页；`blocks` 仍只有所选文本页，具体图像
仍由 `images` 列出。没有把图像页偷偷加入解析文本输入。

材料包 builder 从 2 升为 3，避免旧覆盖语义命中缓存；包 schema 仍为 v1，旧结果可读。
视觉引文不做逐字文本认证，始终保存为 visual-unverified。对未提供解析块的引用仍拒绝。
工作流测试 64 项通过，包含零额外模型调用的缓存复用及源文件不变断言。

本地日志根目录为 `outputs/AN08_20261025/completion-audit/final-development/`
（用户工作区外置产物，不随软件安装）。测试、构建、安装与实际源文件检查详见其中
`engineering-checks.json`；当前结果摘要见 [交付状态](V08_STATUS.md)。

## 科研结果与未达到的目标

不更改既有评分：冻结 v6 三路径字段查准率为 57.6% / 56.6% / 35.3%，完整记录
2/40、3/40、1/40；后续 v7 开发回归查准率 76/143（53.1%）、查全率 76/197
（38.6%）、完整记录 1/40。字段复合口径包含完整条件、对象与阶段，不是单值 OCR。
全部非空输出的支持率 247/268（92.2%）仍低于初步 95% 目标，定位 100% 不补偿语义错误。

原文助手修订使三个示例和一个八篇比较稿成为可继续使用的资料，但没有修正全部
历史自动结果。旧分数、错误、失败、模型新引入的错误和参考勘误都保留。本轮未
重新跑全套 prompt v8 评分，不能用 v7 或三个开发案例代称当前整体准确率。

后续科研质量工作应优先：在未参与调参的跨领域样本上冻结新参考；针对条件/对象
关联及复合引用覆盖评阅；如更换模型需另行固定模型、预算与对照。此前无收益的
策略不自动采用。人类专家核对、真实人工时间、全篇 PDF 直传及更多 Provider 不属于
本轮已验证能力。出版社测试仍为 7/12 篇 PDF 核验通过，余下访问限制没有伪装成成功。

## 最终交付索引

| 任务书最终交付项 | 查阅位置 |
| --- | --- |
| 1 当前状态、2 模块职责、3 架构理由 | [当前状态](V08_STATUS.md)、[设计](V08_DESIGN.md)、本审计 |
| 4 命令配置、6 Provider 与密钥 | [中文指南](V08_USER_GUIDE.md)、`examples/research-*.json`（默认 local） |
| 5 真实测试结果 | [验收记录](V08_ACCEPTANCE.md)、本地完整日志与 GitHub 对应提交的 CI |
| 7 实际评测、8 局限及后续 | [评测口径](V08_EVALUATION.md)、[当前状态](V08_STATUS.md)、本审计 |
| 9 v0.7 兼容性 | [设计](V08_DESIGN.md)、冻结解析夹具与全量回归 |
| 10 三类任务的实际资料 | 用户本地 `AN08_20261025/deliverables/README.md`；含原始结果、评分及助手修订入口 |

仅向已授权 public 仓库的开发分支交付代码和文档；保持 PR 为草稿。提交代码不表示
科研性能验收通过，也不等于合并或发布。用户的后续提交/推送授权替代最初的禁止推送要求。
