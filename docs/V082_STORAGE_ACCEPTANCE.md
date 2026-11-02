# v0.8.2 启动与存储管理验收

[English](V082_STORAGE_ACCEPTANCE.en.md) · 2026-11-02

## 范围与根因

基线：公开仓库最新 v0.8.1 主线 `403514f`。开发分支：`feat/v0.8.2-storage`。

原 `ui_cli.main()` 将默认工作区设为 `Path.cwd() / ".aletheia-nexus/workbench"`，
默认文库也落在启动目录下。Windows 普通用户从 System32 启动时，会向系统目录创建文件而遇到权限错误。
旧文库位置保存在工作区内部，更换工作区后也难以发现该设置。

修复采用项目已有用户主目录约定及 `atomic_json`，独立保存三个位置和迁移映射。
没有更换 JSON 数据结构、引入 SQLite 或修改获取、解析、检索和模型调用策略。

## 主要文件与界面

| 文件 | 作用 |
| --- | --- |
| `src/aletheia_nexus/storage_paths.py` | 用户级默认路径、显式/保存/默认优先级、旧工作区识别、迁移定位映射 |
| `src/aletheia_nexus/ui_cli.py` | UI 启动解析、独立索引参数、会话迁移状态与旧页面写入保护 |
| `src/aletheia_nexus/workbench/storage.py` | 目标检查、复制校验、保留原件、原生/MCP 活动任务检查、成功后原子切换、Windows 凭据目标复制 |
| `src/aletheia_nexus/workbench/ui_storage.py` | 数据存储管理对话页面、文件夹选择器、打开文件夹、两个切换选项、状态与重启提示 |
| `src/aletheia_nexus/workbench/ui.py` | 设置入口及切换后刷新页面的重启提示 |
| `src/aletheia_nexus/workbench/jobs.py` | 任务提交保护与历史任务路径投影 |
| `src/aletheia_nexus/workbench/research.py`、`research_app.py` | 保留规范工件原字节，在允许目录边界内解析迁移后的历史路径 |
| `src/aletheia_nexus/cli.py`、`mcp_server.py` | 文库默认位置统一；MCP 共享文库/索引/工作区，新增 `get_library_catalog` |
| `pyproject.toml` | 版本更新至 0.8.2 |

界面入口为“设置 → 数据存储管理”。依次展示文献库、文库索引 / 数据库、工作区的用途、完整路径、修改位置和打开文件夹。
修改位置后可选择文件夹或输入新绝对路径，再选“迁移现有数据并切换”或“使用新的空目录”。
成功后显示新路径、禁用继续修改并提示重启；其他旧页面不能继续写入。

## 路径与升级

| 项目 | 默认位置（未保存配置） | Windows 示例 |
| --- | --- | --- |
| 文库 | `~/.aletheia-nexus/library` | `C:\Users\carey\.aletheia-nexus\library` |
| 索引 | `<文库>/.an-workbench` | `C:\Users\carey\.aletheia-nexus\library\.an-workbench` |
| 工作区 | `~/.aletheia-nexus/workbench` | `C:\Users\carey\.aletheia-nexus\workbench` |
| 路径配置 | `~/.aletheia-nexus/storage-paths.json` | 独立于工作区保存 |

Linux/macOS 同样使用用户主目录，如 `/home/carey/.aletheia-nexus/workbench` 或 `/Users/carey/.aletheia-nexus/workbench`。
优先级为显式 CLI 参数 > 用户保存的位置 > 默认值。显式选择原目录会使用原副本，不会被历史迁移映射重定向。

```powershell
aletheia-nexus ui --library "$env:USERPROFILE\AN-Library" --workspace "$env:USERPROFILE\AN-Workspace"
# 独立索引示例
aletheia-nexus ui --library "D:\AN-Library" --library-state-dir "D:\AN-Index" --workspace "D:\AN-Workspace"
```

省略 `--workspace` 自动读取保存位置或用户级默认目录。启动后访问 `http://127.0.0.1:8080`；关闭服务后重新启动，无需重装。
迁移后须省略旧路径参数或更新它们。首次升级可从原启动目录识别已有 `.aletheia-nexus/workbench/settings.json`，
或显式传入旧工作区；现有 `.an-workbench/library.json`、标签和集合继续使用。未知的旧位置不会被猜测。

## 迁移验证

所有复制均保留原目录；目标须为空且不能与现有目录重叠；逐文件校验源和目标 SHA-256，失败时不保存新位置。
保留未完成副本便于诊断，不自动删除用户目录。迁移时拦截工作台活动任务并检查既有科研/MCP 作业归属锁；
复制期间仍应避免其他进程新发起写入。嵌套索引随文库复制，独立索引可单独迁移。

| 场景 | 结果 |
| --- | --- |
| 三类目录分别迁移后重开 | 文献、附件、标签、集合、自定义名称、解析版本、任务记录、规范科研结果读取与再导出通过 |
| 旧目录暂时离线 | 将测试原目录改名后，仅用新目录继续读取，验证未依赖旧目录回退 |
| Windows C→D | 真实卷间复制文库、独立索引、工作区；重开后 PDF、标签、集合、解析、任务、科研结果与导出通过 |
| 使用空目录 | 不复制数据、不覆盖文件，独立持久保存新位置 |
| 非空、嵌套、相同、文件或相对路径 | 拒绝切换，配置和原文件保持原状 |
| 磁盘复制异常、校验不符、配置写入失败 | 保持原位置、原件及旧路径配置，恢复任务提交能力 |
| 工作台或科研/MCP 任务活跃 | 提示等待任务完成，不开始迁移 |
| Windows 保存凭据 | 假凭据后端验证旧目标保留、新目标可读，密钥不进入 JSON 文件 |
| MCP | 真实 SDK stdio 读取独立保存的索引、标签、集合；显式允许目录仍保持原目录边界 |

## Windows 与测试结果

Windows Python 3.14.3，NiceGUI 3.18.0；验收进程 `IsUserAnAdmin() == False`。
真实服务从 `C:\Windows\System32` 启动，HTTP 200，未指定工作区时使用隔离用户主目录。
已验证默认路径在真实桌面 `C:\Users\carey\Desktop`、`D:\`、`F:\` 启动间保持一致，均为 HTTP 200；显式文库、索引和工作区均生效。
wheel 在隔离安装目录报告 `aletheia-nexus 0.8.2`，UI/MCP 帮助正常；安装包的实际启动与 C→D 迁移测试 **2 passed**。
wheel 内全部 223 个 Python 源文件与最终工作树逐字节一致。
wheel SHA-256：`2285c1379f278441de1c72b635b8289715b36e69b433705d77bee5678d9150ec`。

最终完整套件：**3988 passed, 148 skipped，零失败，456.90 秒**。
[完整测试输出](validation/v082-pytest.txt)保留原始运行结果；Ruff、compileall、`git diff --check` 和 12 份修改文档的本地链接检查均通过。
最后一轮完整测试命令：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m pytest -q --tb=short --junitxml=验收结果.xml
python -m ruff check src tests
python -m compileall -q src
git diff --check
```

此前完整轮次为 **3984 passed, 148 skipped**，最终边界补充前的重点复测为 **34 passed**。
148 项跳过来自现有的显式启用浏览器烟测、外部 OCR 和 Windows 符号链接权限条件；没有把跳过算为通过。
本轮没有重新调用真实论文获取或付费模型，不据此声称科研准确率提高。

## 文档、交付与边界

更新中英文 README、安装/使用说明、工作台手册、CLI/MCP 指南，并新增中英文 v0.8.2 说明和本报告。
保留已有已发布版本说明；v0.8.2 源码与本地 wheel 不表示已经发布。

图形控制未完成实际视觉复核。自动打开的浏览器导航带跨站标记，被已有 loopback 保护拒绝；
继续通过 Windows 图形工具访问时，工具因不能可靠确认当前浏览器 URL 而停止。
遵循 [computer-use 技能](C:/Users/carey/.codex/plugins/cache/openai-bundled/computer-use/26.1021.31345/skills/computer-use/SKILL.md)
引用的[停止规则](C:/Users/carey/.codex/plugins/cache/openai-bundled/computer-use/26.1021.31345/docs/guidance.md)：
“If Computer Use reports that the turn ended or that the user stopped Computer Use, stop issuing app input.”
因此没有继续操作桌面或绕过访问保护。设置控件的两个选项、路径更新、打开目录回调和文件夹选择器已通过进程内交互测试；
服务启动及迁移通过真实 Windows 进程和文件系统验证，未将这些结果表述为人工视觉验收。

合并判断：**达到本次代码合并条件，建议合并**。依据为完整回归、设置控件交互、非管理员 Windows 启动及真实跨卷迁移验证；实际视觉复核的限制已如实记录，建议发布前补一次人工界面检查。本轮授权推送开发分支，不包含合并或正式发布。

## 推送前复核（2026-11-02）

对代码提交 `e87fbdf` 再次审阅路径优先级、迁移原子切换、原件保留、任务拦截及允许目录边界，未发现新的阻断问题，未修改运行时代码。
重新运行路径、MCP 存储、全部工作台、CLI、MCP stdio 与文库测试：**1173 passed, 18 skipped，零失败，196.75 秒**。
[复测完整输出](validation/v082-review-pytest.txt)与先前完整套件分别记录，不叠加计算通过数。Ruff 与 Git 空白检查再次通过。

本轮成功使用内置浏览器完成真实页面交互，补充了首次验收未完成的浏览器端功能复核：

1. 从 System32 以普通用户启动隔离文库，打开“设置 → 数据存储管理”和文件夹选择器。
2. 界面拒绝原目录作为目标，显示“未切换，继续使用原位置”，随后可正常重试。
3. 通过界面依次完成文库 C→D、嵌套索引独立迁移、工作区 C→D；每次均关闭服务并重新启动，自动读取保存位置。
4. 首次文库复制的 4 个文件哈希一致；原文库、旧索引和旧工作区保留。迁移后三个路径均在 D 盘。
5. 浏览器文献表仍显示测试论文及原标签；独立检查确认原研究集合保留。
6. 在迁移后的文献表中勾选论文并发起本地解析，任务中心显示“已完成”；再次打开上下文后，持久任务记录与解析工件来源检查通过。

[浏览器复核记录](validation/v082-browser-review.json)保存了上述检查结果。所有操作仅涉及新建的测试数据，没有外发论文或调用付费模型。
两种浏览器截图接口均返回无法捕获截图，因此本轮验证的是浏览器真实交互与 DOM 可见状态，仍不声称完成人工视觉或截图验收。
推送目标为公开仓库开发分支 `feat/v0.8.2-storage`；主分支、标签及发行包保持原状态。
