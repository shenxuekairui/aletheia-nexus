# v0.8.2：启动体验与本地数据存储管理

[English](RELEASE_NOTES_v0.8.2.en.md)

本页描述 v0.8.2 源码；不代表已上传 PyPI 或 GitHub Releases。

- 默认工作区和文库使用用户主目录，不再在 `C:\Windows\System32` 等启动目录中创建数据目录，无需管理员权限。
- 新增“设置 → 数据存储管理”，分别查看和调整文献库、JSON 索引、工作区的位置，支持选择文件夹、打开文件夹、迁移或使用新空目录。
- 迁移复制后逐文件校验，保留旧目录；目标非空、嵌套、任务未结束或复制失败时不切换。完成后重启，避免旧会话继续写入。
- CLI/UI/MCP 共享用户级路径配置：显式参数 > 已保存路径 > 默认值。新增 `--library-state-dir`，保留原有参数。MCP 新增 `get_library_catalog` 读取共享索引与集合。
- 保留 v0.8.1 的 JSON 数据结构。迁移不改写科研工件；历史绝对路径通过迁移映射解析，文献、索引、任务和成果可以继续读取与更新。已保存的 Windows 工作区凭据复制到新工作区对应的用户凭据目标，密钥不写入数据文件。

Windows PowerShell 推荐启动：

```powershell
aletheia-nexus ui --library "$env:USERPROFILE\AN-Library" --workspace "$env:USERPROFILE\AN-Workspace"
```

也可省略参数，自动使用保存位置或 `~/.aletheia-nexus/library` 和 `~/.aletheia-nexus/workbench`。
启动后访问 `http://127.0.0.1:8080`。关闭服务后重新运行命令，无需重新安装。
迁移后请省略旧的路径参数或更新为新位置。

升级用户首次从原启动目录运行，或通过 `--workspace` 指向原工作区，再通过界面迁移。
详见[工作台使用手册](WORKBENCH_USER_GUIDE.md#数据存储管理)和[工程验收](V082_STORAGE_ACCEPTANCE.md)。
