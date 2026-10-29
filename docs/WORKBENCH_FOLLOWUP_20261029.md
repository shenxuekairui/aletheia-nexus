# 工作台真实反馈收尾检查点

## 授权与边界

用户明确要求持续完成实际使用反馈、检查同类缺陷，最后推送通过 CI 的分支；允许 DeepSeek 测试合计 30 CNY。
只修改 `F:/AI4S/github/aletheia-nexus-workbench` 的 `feat/v0.8-local-workbench`。
不修改原科学开发目录 `F:/AI4S/github/aletheia-nexus`、`an-0-8` 自动化，不发行、不打标签、不合并主分支。
原科学目录本轮仍为 `0ff48e2fae19afcbf2b41c7cfdd59d493a018af8`、tracked clean；两个原有未跟踪调试文件保留。

## 已完成的本轮实现

| 增量提交 | 实际行为 |
| --- | --- |
| `d0234d9`、`2ef2f37` | 图形选择来源文件夹、空路径拒绝、不同导入失败中文提示；真实 PDF 导入/复用及当时 10 CI 已通过。 |
| `3d43c75` | 正文人工验证默认自动检测，可关闭；合作式 pause/skip/cancel 不误判 PDF 成功。 |
| `bdb7cd0` | 设置顶部 API、启动读取凭据、官方端点冻结、会话/可选 Windows 用户凭据及真实默认值。 |
| `51177c7` | 整批共享原生翻译账本；科学 HTML 只在命名呈现清理，原题/译名/来源不改。 |
| `16bba44` | 常用登录/间隔/自动重试；单篇或几篇明确重试；逐篇翻译→命名→解析；同 PDF 论文归并、来源独立、研究前明确选源；主页状态刷新；批量整理防重复付费及分类 picker。 |
| `29c88cc`、`fb65a48` | 文库标题/期刊普通文本呈现，常用说明准确；切换板块回到标题，不继承长证据页滚动位置。 |
| `2864992` | SI 自有官方文章页/同家中转跟随、原生 PDF bytes/stream/受归属限制的本机保存；排除云保存控件，保留无法自动保存的自有阅读页供人工。 |

业务源码冻结于 `2864992`；最终文档提交之后仍须核对**最后推送 SHA**的 CI，不沿用旧绿灯。
所有子智能体已冻结，主线统一提交/推送。

## 验证证据

所有本机相对证据下列以 `F:/AI4S/outputs/AN08_workbench_20261029/` 为根。

- 首轮完整 3604 passed / 134 skipped；第二轮 3670 passed / 136 skipped（239.25 秒）。
  最后业务冻结全套正在运行：`final/followup-source-frozen-full-suite.log`；必须读取最终结果。
- SI 最后确定性 223 passed / 1 symlink skip；真实本地 Chromium native Save 双同 URL 页、云按钮零点击、
  原正文两模式 8 个 VERIFIED PDF 共 4 项通过（77.17 秒）。
  `si-article-recovery/native-save-and-main-regression.log`、`targeted-native-save-final.log`。
  本地合成夹具曾发现同名 `#save` 实为云盘入口，未使用真实文件/账户；现仅本机下载控件可点击。
- `final/followup-gui/acceptance.json`：独立真实 PDF 副本两份同指纹来源→1 论文行；来源模式可看 2 行，清单 1 篇/2 来源；
  解析前明确选一份，任务 `f91478b483214ad2818a9369b0d8de70` 只收 1 ID，真实解析 PARTIAL；
  hydroamination 查询 42 命中、1 部分覆盖/1 未覆盖；原页 6/10 的图像实际加载 1132×1600；
  从命中直接进研究，任务 `5ca3353560724d2bb58ac38c08975473` 固定 1 正文/0 附件，本地计划已验证，远程/额外页授权全 False。
- `final/followup-gui/per-paper-real-acceptance.json`：GUI 实际获取两篇 Nature，已有分类/新建分类各一、标签分别正确、正文均 VERIFIED；
  每篇翻译后按年份-期刊-中文标题命名，第一篇整理完成先于第二篇交付。任务 `5281f3c5876f47c3b75b34e1df54ee48` COMPLETED；
  2 次真实仅标题调用，整批 cap 0.10 CNY / 4 请求，估算 0.002294 CNY，billing_uncertain=false。
- API CLI 与 GUI 各一次官方模型列表 GET 成功，没有生成内容/传论文/保存真实密钥。
  `final/api-check/acceptance.json`；截图 `final/followup-gui/api-settings.png`。
- 原真实用户 25 篇任务 `0fb9ede0cec544d3bb272dc192c7d6a5` 已 PARTIAL 终态：24 正文 VERIFIED/1 EXHAUSTED；
  SI 2 完成/21 失败/1 未发现/1 未尝试；3 次旧批末标题调用估算 0.012626 CNY，无未知费用；26 解析文件 1 PARSED/25 PARTIAL。
  `final/followup-25-task-summary.json` 绑定原回执哈希，未重跑原批次。
- 1920×1080、1280×900 DOM 几何无页面横向溢出。早期缩放截图工具会裁右，不当作完整布局证据；
  已查看的 API/来源选择完整截图有效。主页曾继承上一页滚动偏移，已修，正式服务更新后需实机核对回顶。

## 真实 SI 覆盖与人工待办

只在独立副本文库做有界 SI-only 测试；全部原正文/来源及副本正文哈希保持，0 主文重下、0 模型调用。

- `si-article-recovery/real-seven/acceptance.json`：Science 真保存 1 SI；ACS/MDPI/Springer NOT_FOUND（不等于没有 SI）；
  RSC CAPTCHA 页保留；Elsevier linkinghub 中转未跟；Wiley 内嵌 PDF 未保存。首次失败证据保留。
- `real-inline-retake/acceptance.json`：Elsevier 修复已到正确 ScienceDirect 页，实际 CAPTCHA 保留；Wiley bytes/stream 仍受 403/阅读器占位限制。
- `real-native-wiley/acceptance.json`：真实 default msedge 中未确认安全的 owned 本机保存控件，SI 明确 INTERACTION_REQUIRED、saved=0；
  最终 `BROWSER_PDF_VIEWER_MANUAL_SAVE_REQUIRED.page_retained=true`，旧中间事件 false 不是最终关闭。
  不猜测是权限或扩展不兼容，不把本地 Chromium 成功冒称真实 Edge/Wiley 自动成功。
- Wiley 人工：在保留 PDF 页下载到本机（不要云保存），然后该正文详情添加本地 PDF SI，明确父文并保留人工声明关联身份；
  再次点补 SI 不保证当前阅读器自动保存。DOI `10.1002/cctc.202201687`。
- Elsevier `10.1016/j.elecom.2022.107204`、RSC `10.1039/d4cc01176g` 的人工验证页保留；用户完成后再只补所需项。
  不盲目继续请求，不解验证码、MFA 或订阅权限。

## 当前服务和接续顺序

1. 正式 8098 仍旧 `2ef2f37`：launcher PID 55184、listener 25136，工作区
   `F:/AI4S/outputs/AN08_workbench_20261028/real/workspace`；最近已查任务全终态，但重启前必须再查。
   检查确切 PID 命令/工作区，只停这两个自有 Python 进程，不停/导航/关闭 default Edge 或它的页面。
2. 独立 GUI 8097 launcher 14900 / listener 55052，工作区 `final/followup-gui/workspace`，已知 3 个任务全终态。
   测试后安全停止自有进程；Cua 临时 tab11 关闭，主 tab1 留作正式界面，恢复临时 viewport。
3. 当前 wheel 正在构建到 `final/followup-package/`，日志 `final/followup-build.log`；检查 twine、源码清单与 SHA。
   `final/followup-fresh/verify-fresh-wheel.py` 已准备新空 Python3.11 venv
   `C:/Users/carey/AppData/Local/Temp/an-workbench-followup-20261029/ui-311`，还未安装；只用当前 wheel 首次安装并验证。
4. 更新正式服务，记录新 PID/业务版本；实机核对导航回顶、原 25 篇真实进度终态、单篇/多篇重试预览及来源归并。
   不为测试重发已知需人工的 SI 或付费标题请求，不影响已存在的文库资料。
5. 最终文档及本轮验收、功能支持矩阵如实记录；推 public feature 分支，等最后 SHA 的 Tests + Local workbench 全 10 job 真实通过。
   失败读日志修复再推；不能只看到 workflow 存在或本地绿灯就算 CI 通过。
6. 写最终本机交付回执（当前 SHA、包/源码哈希、CI、服务、预算及人工清单），核对科学目录仍未改；
   无可自主解决的交付阻断时才能 complete goal，停止本 `an` 心跳（不动 `an-0-8`）。不宣称全出版社或科学提取质量达标。

## 费用与连续任务

持续任务 `an` 已 ACTIVE，每 10 分钟接续本线程；状态无变化保持安静，只通知实质进展、失败、完成或需人工。
30 CNY 是总授权上限，不是账户余额。此前已知估算 3.285544、用户新 25 篇 0.012626、本轮新两标题 0.002294 分开记录；
不是供应商总账，用户其他自主规范化/翻译账本需另外核对，未知费用不得重发。本轮无其它新增生成式调用。
