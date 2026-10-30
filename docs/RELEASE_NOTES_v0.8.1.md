# 溯光（Aletheia Nexus）v0.8.1 — 安装包验收修正

[English](RELEASE_NOTES_v0.8.1.en.md) · [完整功能介绍](RELEASE_NOTES_v0.8.0.md) · [当前验收](V08_RELEASE_ACCEPTANCE.md)

本说明更新于2026-10-30，对应 `release/v0.8.1` 修正。0.8.1 的最终检查、标签、GitHub Release 与 PyPI 上传须按实际结果分别记录；本文不以版本号代替发布或公开安装证据。

## 为什么增加补丁版本

v0.8.0 已合入 main，并创建了不可变的版本标签和 GitHub Release。该 Release 触发的独立 PyPI 发布流程中，安装包环境的测试使用宽泛文件匹配选择缓存，误将首读证据清单缓存当作最终科研结果缓存。选择依赖目录枚举顺序，使这项验收在安装包环境失败。

本次更正测试的缓存选择，使其明确检查目标科研结果，继续验证原有缓存兼容与重放要求。版本标识和文档同步更新为0.8.1。科研提取、解析、获取、UI、CLI 与 MCP 的产品运行行为沿用0.8.0；本补丁不产生新的科学准确率成绩。

具体修正在 `tests/processing/test_json_closure.py`：按结果契约及首次运行清单的 `result_id` 唯一识别结果缓存，同时覆盖“首读缓存先出现”和“结果缓存先出现”两种枚举顺序。原有闭合恢复、摘要/轨迹篡改与缓存重建断言保留，并核对首读缓存字节不变。

## 发行状态与历史保留

| 版本 | GitHub 状态 | PyPI 状态 |
| --- | --- | --- |
| 0.8.0 | 原标签与 [GitHub Release](https://github.com/shenxuekairui/aletheia-nexus/releases/tag/v0.8.0)保留 | 安装包验收失败后，上传任务跳过，没有上传0.8.0 |
| 0.8.1 | 按修正提交与最终检查发布；以实际标签和 Release 为准 | 以0.8.1实际文件与公开安装验证为准 |

原失败和工作流记录保留，不能把 GitHub Release 已存在写成 PyPI 已发行，也不能用旧提交的绿色检查代替修正提交的验收。不移动或重写v0.8.0及更早的标签。

## 能力、安装与边界

完整功能见 [v0.8.0 功能说明](RELEASE_NOTES_v0.8.0.md)：本地工作台、自然语言任务、23个本地 MCP 工具共用科研引擎；新 AI 计划默认先读后组装，旧任务、来源、结果和缓存保持其原义。

确认 [PyPI 项目页](https://pypi.org/project/aletheia-nexus/)已显示0.8.1及对应文件后，可在 Python>=3.11 环境安装：

```powershell
python -m pip install "aletheia-nexus[ui,mcp]==0.8.1"
aletheia-nexus --version
aletheia-nexus ui --library "D:\文献库"
```

尚未公开时，可从已检查的修正源码安装 `python -m pip install -e ".[ui,mcp]"`。浏览器、Poppler与OCR仍按实际功能另行配置；模型密钥与远程内容授权分开。

科研质量继续按 [当前质量说明](V08_STATUS.md)与 [十篇工作流对照](V08_TEN_PAPER_COMPARISON.md)的原始批次解释。助手源审不是专家人工金标准，历史答案复用不是新留出评测，工程修复不当作科学准确率提高。

本补丁的实际测试、安装包、云端和发布结果统一记入 [整合验收](V08_RELEASE_ACCEPTANCE.md)，不在检查完成前预填通过数或发行校验和。
