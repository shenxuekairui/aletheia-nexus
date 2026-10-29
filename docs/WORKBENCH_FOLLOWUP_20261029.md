# 工作台真实反馈收尾检查点

## 授权与边界

用户明确要求持续完成实际使用反馈、检查同类缺陷，最后推送通过 CI 的分支；允许 DeepSeek 测试合计 30 CNY。
只修改 `F:/AI4S/github/aletheia-nexus-workbench` 的 `feat/v0.8-local-workbench`。
不修改原科学开发目录 `F:/AI4S/github/aletheia-nexus`、`an-0-8` 自动化，不发行、不打标签、不合并主分支。
前一交付阶段只读核对的原科学目录为 `0ff48e2fae19afcbf2b41c7cfdd59d493a018af8`、tracked clean；两个原有未跟踪调试文件保留。
此历史核对不代表随后其他独立科研任务没有进展；本轮不写入该目录。

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
| `0aebd42` | 远端 Windows 测试在默认 cp1252 下读取 UTF-8 回执失败，3 处测试读取已明确编码，18 项及 cp1252 定向回归通过；新提交远端 CI 仍待核对。 |
| `837f209` | 阅读器外壳未交付 PDF 的普通中文说明与单篇重试提示；原始诊断、来源门禁和已有文件状态保留，86 项相关回归通过。 |
| `774b8d8`、`80751d0` | 原生阅读器只操作已确认归属的本机保存控件，优先保存以避免失败重取干扰当前交付；新增精准中文交付诊断，不改正文来源门禁。 |
| `c79b000`、`4b69edb` | 附着标签标题发现及正文/PDF 缓存读取增加有界等待；不以超时当作获取成功。 |
| `16165f5`、`59d135a` | 提交与异步回调保持稳定客户端上下文，避免进度重建删除事件父容器；任务成功创建不因通知显示失败误导为未提交。 |

前一交付阶段的业务源码为 `2864992`，文档提交为 `d69823c59231933d9c464ef2126b8421eb8a47ce`。
该阶段已完成分支推送、离线包全新安装及正式界面验收；下文“尚未安装 / 尚未推送 / 服务仍旧版”的早期待办已不再代表现状。
随后真实单篇 ACS 正文曾出现“阅读器已响应但文件未交付”。目前已完成所选 `human-handoff` 会话下的同篇真实 GUI 下载、核验及入库；
独立空库 `default` 会话也已完成同篇正文的真实 GUI 重试，使用原生阅读器交付并通过原来源门禁；
两次成功分别记录，不扩展为所有出版社、会话或附件均支持。
新修复的最终提交、包和 CI 仍须另行核对；不能沿用 `d69823c` 或更早版本的验收。

## 验证证据

所有本机相对证据下列以 `F:/AI4S/outputs/AN08_workbench_20261029/` 为根。

- 该阶段首轮完整 3604 passed / 134 skipped；第二轮 3670 passed / 136 skipped（239.25 秒）；
  冻结源码最终全套 3682 passed / 138 skipped（212.20 秒），见 `final/followup-source-frozen-full-suite.log`。
  这些是前一冻结阶段的结果，不代表随后 ACS 修复的完整回归或远端 CI 已通过。
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
- 原真实用户 25 篇任务 `0fb9ede0cec544d3bb272dc192c7d6a5` 的历史回执为 PARTIAL 终态：24 正文 VERIFIED/1 EXHAUSTED；
  SI 2 完成/21 失败/1 未发现/1 未尝试；3 次旧批末标题调用估算 0.012626 CNY，无未知费用；26 解析文件 1 PARSED/25 PARTIAL。
  `final/followup-25-task-summary.json` 绑定原回执哈希，未重跑原批次。
- 1920×1080、1280×900 DOM 几何无页面横向溢出。早期缩放截图工具会裁右，不当作完整布局证据；
  已查看的 API/来源选择完整截图有效。
- `final/followup-fresh/package-acceptance.json` 为 PASSED：`d69823c` wheel 在全新 Python 3.11.16 环境，
  由记录哈希的本地依赖 wheelhouse 首次非 editable、`--no-index` 安装；214 个已安装 Python 源文件与 wheel 原字节一致，
  pip check、CLI/UI help、仓库外导入、临时 localhost HTTP/Origin/Host/WebSocket 安全检查通过，临时服务已停止。
  wheel 为 858928 字节，SHA-256 `fdc7ad58a813655fbae14eaf990e42cae16ee7df4f4724dcc6d62203da5007e5`。
  这是已完成的离线首装，不宣称新的联网依赖解析或 ACS 后续修复已包含其中。
- `final/followup-service/gui-acceptance.json` 记录正式界面已切到 `d69823c` 阶段：导航滚动从 863.33 回到 0，
  原 25 篇进度如实显示 24 成功/1 失败；实际预览并切换重试范围，逐行“只选这篇”有效，默认关闭付费重译。
  该次只预览而没有提交重试（任务数 22→22），不代表失败论文已下载成功。
- `final/acs-main-recovery/gui-human-acceptance.json` 记录后续真实 GUI 单篇重试：任务
  `ccded31292944e67b12259bb01e06337`、UI 源码 `16165f5`，DOI `10.1021/acs.jpcc.4c00353`。
  使用 `human-handoff`、`cdp_endpoint=null`、`launch_mode=auto`，不是本地 PDF 导入，也不是旧正文断点复用。
  正文获取耗时 14.03 秒，HTTP 200，9,011,274 字节、8 页，正文 VERIFIED，正常命名入库完成。
  **实际交付方法为 `context_request`，这次真实成功不能冒称为 ACS 原生阅读器保存路线也已验证成功。**
  SI 为 NOT_FOUND，仅表示本次页面没有发现受支持附件，不证明论文不存在 SI；自动解析覆盖 8/8，
  但保留真实警告而为 PARTIAL，故任务总状态仍为 PARTIAL。标题翻译未选择、模型调用 0；本次操作未出现 deleted-slot 错误。
- `final/acs-main-recovery/full-suite-16165f5.log` 保留当时完整回归的 1 failed / 3752 passed / 146 skipped：
  单一失败是测试绕过 UI guard 后在新 asyncio task 缺少事件客户端上下文。`59d135a` 修复测试调用与正常异步回调上下文，
  95 项相关回归通过；最新完整回归、最后提交 CI 与新安装包仍待主线补入，不沿用旧绿灯。
- `final/acs-profile-repro/default-success-acceptance.json` 记录 `f4949d8` 下的真实 GUI 重试，任务
  `af67df64128b40488cd5990376d4a323` 为 COMPLETED，耗时 25.873 秒，正文 VERIFIED。
  实际参数是 `profile_name=default`、`cdp_endpoint=null`、`launch_mode=auto`，
  未传入本地 PDF，`resumed=false`，正文之外的 SI、解析和标题翻译均未选择，模型调用为 0。
  交付方法为 `browser_viewer_save`，来源记录 HTTP 200、9,011,274 字节、8 页，命名入库完成。
  独立只读复核当前 PDF 与 sidecar：ARTICLE / acquisition_verified，DOI 相符，双哈希与任务/来源记录一致。
  此证据证明真实字节经原生阅读器交付并通过核验；**不代表独立抓包证实了新的网络传输，也不排除浏览器缓存参与。**
  原失败任务不被改写，成功重试沿 `resume_of` 保留追溯；两个会话的 PDF/来源哈希独立保存，不按 DOI 强并身份。
- `c030d3e` 已提交标题纯文本显示及旧成功任务的普通状态投影：已验证正文不再附旧候选失败重试建议，
  SI 和明确后处理状态独立保留，原始诊断/不可变回执不改；相关回归 69 项通过。
  `final/closeout-workflow` 的本地合成六闭环检查全 true、远程关闭，依赖与静态检查通过；
  新全套日志 `final/acs-main-recovery/full-suite-closeout.log` 已完成：**3766 passed / 147 skipped，230.63 秒**；
  532 个 Python 文件的格式与 lint 检查、依赖检查、冻结基准检查均通过。可选真实浏览器测试与出版社实测单独记录。
- `final/real-bulk-closeout/acceptance.json` 补充 **25 篇不同真实 PDF** 的隔离副本批量整理，45.612 秒通过：
  24 篇复用缓存中文译名，1 篇明确回退原题，2 份真实 SI 分置两分类的共享 `SI/`，再单篇携 SI 交换分类。
  26 份旧解析工件仍可定位，245/245 受保护原文件哈希不变；没有网络或模型调用。
  这是共享应用服务的真实文件验收，不能冒称新一轮 GUI 或付费翻译验收。
- 最终真实文库检查发现，多来源论文的 SI 合计混入“条关联”文字，会触发表格数字列的 Invalid Number。
  显示投影现保留数字合计，恢复正常显示及数值排序；不修改来源、关联或文库文件。相关 12 项回归通过，
  后续最终提交的完整回归、实际界面与 CI 结果仍由上述最终交付回执记录。

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
- `final/si-final-retake/acceptance.json` 为后续真实有界复测：Wiley、RSC、Elsevier 各尝试一次，
  三项均为 INTERACTION_REQUIRED、附件保存均为 0，不能宣称三家自动获取 SI 已验收成功。
  复用已存在的 `human-handoff` 会话和独立正文副本，0 主文获取调用、0 模型调用、0 新浏览器启动，
  没有自动解决验证或操作原有标签；原始及副本正文/来源全部哈希不变。
  人工验证页保留，完成合法操作后仍须审阅范围再仅补 SI，或在文献详情明确关联人工保存的附件。

### ACS 阅读器交付问题：已证实与待验收分开

主线与获取智能体在隔离的全新 Edge 155 上确认，当前页所属的内置阅读器使用 `edge_pdf/index.html`，
其本机保存按钮为 `button#save`（“保存(Ctrl+S)”），不位于 Chrome 的 `viewer-download-controls` 内。
原有安全选择器因此没有把该按钮确认为可用的本机保存控件，`ready=false`；页面可打开但文件交付未完成。
这解释的是已复现的阅读器结构不匹配，不代表已证明账户、订阅权限或第三方扩展故障。
所属页绑定的实证见 `si-article-recovery/edge-owned-viewer-diagnostic/summary.json`；
实际控件诊断见 `si-article-recovery/edge-local-control-diagnostic/controls.json`。
`774b8d8` 已只接入确认的内置 Edge 控件，继续要求当前页归属与合法来源检查，不泛点 `#save` 或云保存。
隔离的 Chrome/Edge 155 与 loopback 自编 PDF 已复现另一个顺序问题：先失败的页面 fetch 再保存会取消原生交付，
将受归属限制的本机保存前置后，真实浏览器保存的 2733 字节与夹具完全一致，并通过原主文 VERIFIED 门禁；
另一同 URL 标签未被操作。证据为 `si-article-recovery/main-viewer-live-5.log`，属于本地夹具验收。
真实 ACS 的 `human-handoff` 成功实际使用 `context_request`，后续独立 `default` GUI 重试成功实际使用 `browser_viewer_save`。
这两条真实交付证据及本地夹具分别留档；原生保存证明取得并核验文件字节，不排除浏览器缓存，也不等于另行抓包验证新请求。

cacheguard 开关对照和原始 stream 原型的负结果保留在 `si-article-recovery/cache-routing-*`、
`cdp-original-stream-run*` 试验目录。它们没有提供可宣称成功的新下载路线，不作为关闭安全 guard 的依据。
`final/acs-profile-repro/default` 是独立空文库的真实 GUI 正文对照，不运行标题翻译、SI 或解析，现已完成上述单篇成功验收。
这不证明所有 `default` 会话配置都已修复。新工作区的 UI 默认会话原本就是 `human-handoff`，
正式工作区里的 `default` 是被保留的旧显式设置，未为这次对照修改厂默认或静默覆盖用户偏好。
旧失败回执、旧离线包和各次试验记录均保留。

## 当前服务和接续顺序

1. `final/followup-service/service.json` 记录正式 8098 在无活动任务时已更新到 `d69823c`，
   当时 launcher PID 38392、业务源码 `2864992`，工作区仍为
   `F:/AI4S/outputs/AN08_workbench_20261028/real/workspace`，没有停止浏览器进程。
   这是阶段启动记录，不是当前进程保证；ACS 接续期间是否有活动任务必须由主线现场核对，不能按旧 PID 盲目重启。
2. `final/followup-gui/cleanup.json` 确认独立 8097 的自有 Python 14900/55052 已在任务终态后停止，
   临时 tab11 已关闭、viewport 已恢复，没有停止出版社浏览器。旧“临时服务尚待清理”是历史待办。
3. `final/followup-package/` 的 wheel/sdist、源码清单、twine 严格检查和离线依赖解析已完成；
   `final/followup-fresh/package-acceptance.json` 已完成上述全新安装验收。保留旧报告和包哈希，
   后续 ACS 修复冻结后应使用新提交另建验收记录，不能覆盖成“旧包已含新修复”。
4. `human-handoff` 与独立 `default` 的真实同篇正文交付均已验收，`c030d3e` 完整本地回归已通过。
   页面已打开、PDF 字节已取得、正文身份已验证、文件已保存是不同结果。
   原始 `NativePdfViewerPlaceholder` 诊断保留；工作台已补中文说明及仅重试该篇的提示，来源身份标准不降低。
   Edge 控件结构与保存顺序有隔离实证；原生保存的真实成功不排除缓存参与，其余会话、SI 和不同路线仍以各自结果为准。
5. `d69823c` 已推送；`final/ci-d69823c-readonly-check.json` 已确认 FAILED：8 项成功、2 个 Windows job 失败，
   均涉及同一新测试按默认 cp1252 读取 UTF-8 回执。`0aebd42` 已明确相关 3 处读取编码并通过定向回归；
   这不代表新提交的远端结果已通过，不能把旧失败写成仅“尚未确认”或全绿。
   新修复提交后核对最后 SHA 的 Tests + Local workbench 所有必需 job；失败读日志修复再推，
   不以旧 CI、workflow 存在或本地绿灯代替。
6. 更新最终本机交付回执（新 SHA、包/源码哈希、CI、服务、预算及人工清单），只读核对原科学目录边界；
   无可自主解决的交付阻断时才能 complete goal，停止本 `an` 心跳（不动 `an-0-8`）。不宣称全出版社或科学提取质量达标。

正式界面随后在确认 25 个历史任务均为终态后加载 `c030d3e`，仍使用原工作区和文库。
`final/acs-main-recovery/runtime-c030d3e/service.json` 记录源码哈希、原回执哈希和启动进程；没有停止出版社浏览器。
新界面已实际打开获取页并核对旧成功回执：显示正文成功 1、失败 0，标题排版标签不再直出，失败建议不再混入成功结果。
临时 8097 验收页及其自有 Python 服务已清理，原 PDF 与回执不改。
最终提交的远端 Tests / Local workbench 共 10 项结果、冻结源码构建和全新 Python 3.11 安装结果由
`final/closeout-ci/ci-current.json`、`final/acs-main-package/`、`final/acs-main-fresh/` 及
`final/closeout-delivery.json` 分别记录；交付须核对同一最终提交，不能沿用旧包或旧绿灯。

## 费用与连续任务

持续任务 `an` 已 ACTIVE，每 10 分钟接续本线程；状态无变化保持安静，只通知实质进展、失败、完成或需人工。
30 CNY 是总授权上限，不是账户余额。此前已知估算 3.285544、用户新 25 篇 0.012626、本轮新两标题 0.002294 分开记录；
不是供应商总账，用户其他自主规范化/翻译账本需另外核对，未知费用不得重发。本轮无其它新增生成式调用。
