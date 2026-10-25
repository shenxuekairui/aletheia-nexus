# v0.8 评测口径与执行方法

工程通过、在线 API 返回、引用可定位和科学正确是四件不同的事。评测输出应同时保留
失败、遗漏、部分结果和成本；不能只挑选成功记录计算准确率。真实论文、原页图片和
标注留在用户本地，不进入可再分发的测试夹具。普通测试仅用自制论文和 Mock。

## 三类任务和三条路径

A 为研究主题整理，B 为科研问题证据整理，C 为实验条件与过程提取。三者都通过
同一 Task、Provider、Package、Result 和批处理引擎。材料合成是 C 的测试任务配置，
并无专用业务模块。比较 parsed/hybrid/direct 时固定问题、字段、论文、页码、模型、
提示词与预算，仅改变输入路径。不同阶段的调参结果不得混作同一对照实验。

原页直读仍有指定页的覆盖范围，不代表读过完整论文。图像引用需要人工核对，不能与
自动精确匹配的文本块引用混为一种验证强度。PDF 页码定位成功不等于支持主张。

`scripts/run_v08_evaluation.py` 执行任务并累计费用；它不评判科学正确性。
`scripts/score_v08_review.py` 只统计已有评阅，不自动调用 AI 评分。

## 在运行前冻结参考与分母

建议 20–30 篇真实论文、100 个字段判断和 40 条完整记录，三个场景都覆盖。
开发集和留出集按文献分组，正文和 SI 必须归到同组；同一论文不同页不构成独立留出。
留出集禁止用于提示词调参。先测基线，再冻结正式门槛；候选门槛为查准率 90%、完整
记录正确率 80%、引用定位率 100%、实际支持率 95%，不是已经实现的性能承诺。

计划文件结构如下（这是配置示例，不是实际成绩）：

```json
{
  "schema": "aletheia-nexus/evaluation-plan/v1",
  "split": "development",
  "reference_authority": "assistant",
  "frozen_at": "带时区的冻结时间",
  "cases": [
    {"id": "paper1-stage1-temperature", "record_id": "paper1-stage1",
     "kind": "field", "expected_present": true,
     "expected": "核对原页后填写的标准读法、单位和关联步骤",
     "source": "原PDF身份/哈希与页码"},
    {"id": "paper1-uncertainty", "record_id": "paper1-stage1",
     "kind": "field", "expected_present": false, "check_uncertainty": true,
     "expected": "已检查范围未报告此条件，不得用测试条件填入制备阶段"}
  ]
}
```

若有实际人工标准，填入 `reference_authority=human`；助手原页核对必须标为
assistant。用户已明确选择本轮使用 GPT 原文复核代替人工，本轮参考与评阅遵循
assistant 类别；不再将等待人工标注列为开发阻塞。保存计划的 SHA-256
（`processing.contracts.digest(plan)`）并归档原文件。
脚本验证哈希，防止更换分母；冻结时间、独立性和评阅人身份仍需组织上的真实保证。

评阅文件含 plan_sha256、reviewer、reviewer_kind、run_ids 和 judgments。
每项 judgment 必须包含 id、present、correct、association_error、citation_resolvable、
evidence_support 和 rationale；要求检查不确定性时另填 uncertainty_correct。
evidence_support 为 supported/unsupported/uncertain/not_applicable。未输出时
citation_resolvable 可为 null。错误状态下无结果也必须评阅，预期字段均计为遗漏，
不得删掉该论文。新增的多余主张单独登记 claim 案例并说明评阅覆盖；不能把未评阅
主张默认为正确。正式留出计划应事先规定如何审计这类多余输出并固定补充登记规则。

```powershell
python scripts/score_v08_review.py plan.json review.json --output score.json
```

## 指标定义

- 字段查准率：已输出且正确的字段 / 已输出字段；正确包含对象、阶段、步骤、值和单位。
- 字段查全率：已输出且正确的字段 / 原文在既定覆盖范围内实际报告的预期字段。
- 完整记录正确率：记录的全部预定义字段与操作步骤检查都正确 / 预定义记录；缺失
  信息也须正确处理。报告明确该指标覆盖预定义检查，另审核全部实际输出。
- 引用可定位率、实际支持率：分别报告评阅中已输出字段/主张的可定位数和受支持数，
  uncertain 不计为 supported。一个字段有多条引用时按字段/主张组计，须明确此分母，
  不得称为逐引用数。程序运行报告可以另行统计逐引用定位数。
- 单列条件关联错误、遗漏、不确定性处理，以及逐项错误理由。
- case 可携带 baseline_correct，用相同口径报告新错误和修复旧错误。
  没有基线判断时这两项为 null，不能解释为“AI 没有引入错误”。

分母为零时指标为 null。缺少任何冻结案例或重复案例时拒绝评分。
human_holdout_review 只反映填写的分组与评阅类别，不是身份认证，也不表示达到发布门槛。

除正确率外，按运行清单报告费用估计、实际返回 Token、未知费用、HTTP 次数与耗时。
人工核对时间必须由评阅人实际计时；没有计时就写“未测”，不能由 Token 数推算。

## 已执行与未执行的边界

2026-10-25 已执行真实 DeepSeek Flash 连通、三场景三路径开发对照、原页抽查和批量
任务。开发集原页抽查发现条件数值正确但 step_ids 过宽的问题，已据此改进提示。
这属于助手复核，不是 100 字段的人类专家标准，也不是独立留出验收。
具体运行、失败和测试日志见 [验收记录](V08_ACCEPTANCE.md)；未通过正式验收时保持开发版。

## 全量输出审核

冻结计划设置 `output_audit_policy=all_emitted`，在预定义案例评分之外，逐项审阅
实际输出的每个字段、步骤及独立主张，包括额外输出。工具绑定运行、结果与原 PDF
哈希，核对来源仍存在且内容未变；缺失的输出判断、重复项、变更的结果均拒绝评分。
失败的文献保留在运行清单和固定分母中。未报告字段的空值判断也要审阅，不能靠
少输出或不输出提高表面正确率。草稿不产生分数。

```powershell
python scripts/score_v08_review.py plan.json --run-dir RUN_DIRECTORY --prepare-output-review --output review-draft.json
python scripts/score_v08_review.py plan.json review.json --run-dir RUN_DIRECTORY --output score.json
```

多次运行可重复传入 `--run-dir`。GPT 审阅填写 reviewer_kind=assistant；
`human_holdout_review=false` 在此情形是正确的来源标记，不代表未执行 GPT 审核。
