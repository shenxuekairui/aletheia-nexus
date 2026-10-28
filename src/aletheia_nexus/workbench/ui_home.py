"""A real workspace overview and an in-application, Chinese operating guide."""

from __future__ import annotations

GUIDE = [
    (
        "首次使用",
        "十分钟开始：先完成一篇文献的小闭环",
        [
            "第一步：可先使用主页显示的当前文库，也可点击“查看 / 更换文库”或右上角“设置”，填写本地文库目录。已有 AN 文库可直接打开；分类负责实际保存位置，标签和集合用于逻辑组织。",
            "第二步：点击“导入本地 PDF”，在弹窗中选择本地文件即可，不需要填写文件路径。也可点“粘贴 DOI / 标题”，输入第一篇文献后预览，再由你启动获取。主页的公开示例只填入 DOI，不会立即下载。",
            "第三步：打开文献库，勾选论文并点击“解析已勾选 → 开始解析”。完成后进入“科研检索”，输入正文中的一个关键词，打开命中证据的原页。遇到部分解析，先查看页覆盖和警告。",
            "完成上述小闭环无需 API 密钥或远程模型。接着可添加标签、保存集合和选择材料；准备好后，再到“AI 研究”本地创建可编辑计划，审阅范围与预算。",
            "只上传单个 PDF 时按用户声明身份登记。已有 AN 资料可直接打开原文库，或从带来源记录的本地路径导入，以保留已有有效来源；解析状态仍不代表科学内容准确。",
            "工作区保存任务历史、科研材料快照、翻译缓存和成果。备份时同时保留文库与工作区。文库切换前需要结束正在进行的任务，旧浏览器页面需刷新。",
        ],
    ),
    (
        "获取论文",
        "确认身份，再获取正文与 SI",
        [
            "粘贴 DOI、中英文完整标题，或上传 TXT、CSV、JSON 清单，先点击“手动整理并预览”。“1. DOI”等编号会正确识别；完全相同的论文与设置可去重。同一 DOI 的分类、标签或书目约束不同会列出冲突，需停用多余候选或统一设置。错误行会列出原因。",
            "杂乱文字可用“AI 整理输入”：先确认模型、费用上限和本次文字外发授权，完成后核对出处、目录和标签，再“确认采用并预览”。模型只整理输入，不补造 DOI；待确认标题仍需查询书目。关闭窗口不会取消整理，再打开可查看上次结果，不再次收费。",
            "较长清单可点击“使用大批量整理建议”，一次调整输出容量与显示的费用上限，再核对并授权。重复说明会合并显示，完整原文出处和请求账本在专家区域按需打开。",
            "同一批论文可以分别放入多个目录。右侧“本批多个目录”按组显示篇数和保存位置，每组点击“设置目录与标签”可选择已有目录或新建目录。单篇可在右侧展开选择，也可双击表中最终目录或标签打开同一设置窗口。批次默认目录只作用于没有单独指定的位置。",
            "不必制作 CSV：用“A. 羧酸还原”或“[羧酸还原]”开始一组，下面粘贴编号 DOI；该组继承你明确写下的分类。需要父子目录时用“## 电催化”及“### 羧酸还原”，形成“电催化/羧酸还原”。这不是模型对研究主题的自动判断。",
            "组头可写“A. 羧酸还原 | 标签=待读,电催化”，也可在组内另起一行写“标签=待读,电催化”。逐篇覆盖示例：“10.1038/s41467-019-08805-x | 分类=电催化/重点 | 标签=已读”；字段之间也可使用制表符。逐篇标签替换组标签，不会自动合并。",
            "未指定字段时跟随组设置，组也未指定时跟随批次默认。写“分类=/”或“分类=根目录”明确保存到文库根；写“标签=”或“标签=[]”明确不加标签。非法目录会报错，系统不会静默改名或沿用前一组。",
            "预览后仍可逐篇调整：双击最终目录或标签打开本篇设置；勾选多行后点击“设置所选”批量修改。两种入口使用同一窗口，目录可继承默认、指定分类或明确放文库根目录，标签可追加、替换或明确清空。新分类仅是保存位置，不影响论文身份。",
            "没有 DOI 的英文标题需先选中表中论文，再点击“解析 / 确认当前选中标题”。根据标题、作者、年份、期刊核对候选；相近结果不会被自动当成同一论文。中文标题继续使用 CNKI 身份核对流程。",
            "设置分类目录、标签和主文/SI统一命名模板。分类中正文直接平铺，所有关联附件共用该分类的 SI/ 子目录。正文成功与 SI 获取状态独立报告。",
            "命名下拉包含“自定义模板”，也可直接编辑“实际模板”，例如 {year}-{journal}-{title_zh}，填写名称后保存复用。缺少译名时按现有原题回退；付费翻译需单独授权。保存命名模板不改动已有文件；已有文献在文库“批量整理”中预览并执行。",
            "自动 SI 获取尝试 DOI 一致的官方页面；正文来自受支持官方开放仓储时，也会核对同版本元数据与明确附件清单。受保护附件可能无法取得；非 PDF 附件先保存和登记，不承诺能够解析。",
            "正文通过验证不等于附件入口已放行；若提示附件另需验证，请保留 AN 浏览器的论文页与附件页，人工完成后从“重试获取失败 / 补取 SI”选择“仅补取 SI”，并使用同一会话。软件不会保证通过验证码或越过访问权限，未取得的附件仍如实显示。",
            "新工作区默认“公开 + 机构浏览器”：公开路线先行，必要时打开 AN 独立的可见会话；也可改为“仅公开获取”。“检查本次浏览器配置”只检查依赖和配置，不代表已登录或具有访问权限。实际打开仍经过浏览器运行时和安全版本检查，登录与验证码由你完成。",
            "开始后直接查看本页获取进度，正文与 SI 分别显示；需要人工处理时可继续、跳过或取消，完整渠道、目录和检查点在“全部任务与历史”。关闭或刷新页面不取消任务，重新进入获取页可查看已保存进度。进程退出后则如实标记中断，须核对后恢复。",
            "新工作区默认不限时等待人工操作、普通论文间隔1秒、尝试 SI，并自动使用原生文本解析成功材料；OCR和入库后标题翻译关闭，已有保存偏好保持原样。开启标题翻译仍需明确确认仅标题外发与本批费用上限。",
        ],
    ),
    (
        "文库整理",
        "原题、译名、显示名与文件名各司其职",
        [
            "双击文献查看详情、来源、关联附件和原文。原始书目标题保持独立；中文译名可编辑并人工确认；显示名称只影响展示，不等于磁盘文件改名。",
            "缺中文标题时，直接勾选一篇或多篇并点击“补中文标题”。单篇可手动填写，多篇默认只补缺失；先显示缓存和待外发范围，授权后才调用 DeepSeek。已有人工译名受保护，任务与费用保存在任务中心。可用“未翻译”筛选快速找出缺失项目，不必先打开改名窗口。",
            "勾选文献后加入“当前文献选择清单”。清单可跨页面累积并去重；“全选当前页面”与“加入全部筛选结果”对应不同范围，界面会显示实际数量。",
            "“批量整理”支持标题翻译、命名模板、逐篇名称覆盖、标签和分类移动。需要中文命名时，可在同一窗口补齐缺失译名。生成完整主文与 SI 路径预览，检查冲突和历史引用风险，再确认实际文件操作。",
            "主文与 SI 共享同一基础名称。分类移动只迁移当前论文的关联附件，不会搬走整个 SI/。不安全的历史显式引用会阻止相关项目执行；其它可执行项目仍单独列出。",
            "新工作区的获取命名默认“年份-期刊-中文标题”，没有译名时使用原题，不会自动付费翻译。也可直接选择“年份-期刊-原题”或修改实际模板并保存。补中文标题只更新译名，已有文件需预览后另行执行改名。",
            "表格可显示原题、译名、作者、期刊、标签、SI数量、解析状态等。拖动表头调整顺序和宽度，点击表头排序；在“列 / 排序 / 视图”保存，并在重启后继续使用。",
            "固定研究集合保存具体论文成员；保存筛选保存可重新运行的条件；表格视图保存展示方式。删除全库标签可能减少保存筛选的限制条件，应重新核对结果。",
        ],
    ),
    (
        "解析检索",
        "先确认覆盖，再解读命中",
        [
            "从选择清单、文献详情或检索范围启动解析。可复用匹配参数的已有版本，也可创建独立新版本；OCR需本机相应引擎、语言数据和 Poppler。",
            "在解析窗口查看页数、警告、失败与来源检查，并可切换未来任务使用的解析版本。已有科研任务绑定的版本不会因此改变。",
            "关键词可用“全部词语”或“任意词语”，引号保留短语；还可限定分类、标签、研究集合、正文/SI和章节。检索结果同时报告总命中数、分页与未覆盖来源。",
            "证据视图适合检查段落、表格和图注；论文视图按当前证据页归并。未命中不表示论文没有报告，词语出现在一起也不证明形成了科学关系。",
            "勾选命中论文可加入选择清单、直接进入 AI 研究，或导出原文证据包。打开原文后默认显示可靠的物理页图像，SI 的页码独立于正文。",
        ],
    ),
    (
        "AI研究",
        "明确材料、字段、模型与预算",
        [
            "先从文库或检索结果建立选择清单。在“AI 研究”输入自然语言目标，明确是否包括关联 PDF SI。",
            "“本地创建可编辑计划”不调用模型。若希望模型解释自然语言目标并生成字段，单独授权仅文献元数据的规划请求，并设置规划费用上限。",
            "编辑字段的名称、类型、对象、阶段、条件和单位。核对实际材料、解析版本、文本页码及原页图像页码；仅图像模式必须明确选页。",
            "模型、请求次数、输入字符、图片、输出 Token、复核轮数与费用上限均可编辑。点击“验证并预览实际计划”，核对范围和指纹，再明确授权选定文献内容外发。",
            "执行后可关闭页面，任务仍在后台进行。失败或中断不会自动重发可能收费的请求；从任务中心载入原契约，查看既有结果与费用不确定性后再决定继续。",
        ],
    ),
    (
        "成果核对",
        "有引用的结果，可回到原文核对",
        [
            "在“研究成果”选择结果或修订版本。左侧显示结构化字段、实验步骤、主张和材料不足诊断；右侧用于原文核对。",
            "结构化数据可点击“核对选中数据的证据”；主张型结果不显示空数据表，可直接点击各项主张下的“核对”按钮。右侧定位原文物理页码并展示引用；也可切换完整 PDF 或放大原页区域。",
            "跨篇结果按实际论文数和主张数显示。正文中的“文献1”等阅读名称对应展开的文献对照，优先使用已保存中文译名或显示名；原始模型文本与来源编号仍保存在专家区，不被显示名称覆盖。",
            "来源定位、科学判断和人工确认是独立状态。模型结果仍需研究者核对，不能因为解析成功或引用可定位就认定科学结论准确。",
            "人工修改时填写修订人和理由。只有明确逐项核对后才勾选人工确认；保存会生成新版本，保留模型原始结果与修改历史。",
            "可导出 Markdown、CSV、JSONL及原生结果审计信息。也可基于历史结果的固定材料范围创建新任务，无需再次输入文件路径。",
        ],
    ),
    (
        "任务恢复",
        "看清停止边界与既有结果",
        [
            "获取页直接显示正文与 SI 的逐篇进度；任务中心统一查看获取、导入、解析、翻译、重命名和科研任务。简要进度自动刷新，详细诊断可手动刷新并展开阅读。",
            "暂停、跳过和取消在服务支持的安全边界生效。获取结束进入翻译、整理或解析后，不再提供按论文跳过。正在进行的请求或原子文件事务需先结束；取消不撤回已完成或可能收费的请求。",
            "获取任务可审阅原始参数与检查点后恢复，成功项仍要通过当前来源核验。标题翻译可复用缓存与已确认译名；重新请求需要再次检查范围和预算。",
            "任务结束后点击“重试获取失败 / 补取 SI”，默认只勾选未成功项，可仅补 SI 或只选部分论文。核对篇数、最终目录和标签，必要时本次改用机构浏览器。已验证正文仍经来源门禁后复用；付费标题翻译不会默认重做。",
            "浏览器仍在等待登录时，验证后继续才会接着当前尝试。若当前论文已经返回需要权限的失败结果，论文边界的继续只调度后续论文；本篇需之后核对检查点并恢复未成功项，不能把继续当作已经下载成功。",
            "重命名和分类移动保存独立操作日志。出现中断或恢复要求时，在“文件操作日志与验证回滚”检查逐步路径，并执行经过哈希验证的回滚。",
            "进程终止后的未完成任务标为中断。费用未知会保留待核对状态，不当作零费用，也不自动重新执行。",
        ],
    ),
    (
        "设置说明",
        "简单默认与专业参数并存",
        [
            "常用设置直接显示；高级参数可展开；专家区域保留原始任务契约与诊断字段。界面中的参数名称、单位和帮助对应后端实际参数。",
            "全局默认影响以后新建任务；命名预设保存一组可复用参数；本次任务临时修改不会隐式改变旧任务。预设不保存 API 密钥或认证 Cookie。",
            "普通论文间隔用于下一篇调度，CNKI间隔用于CNKI路线，失败退避用于重试；它们与单次网络、导航、登录等待超时分别生效。",
            "默认仅绑定本机地址。远程模型的 API 密钥从系统环境读取，设置中心只显示是否可用；默认不上传整个文库。",
            "若原页图像不可用，在设置的环境诊断检查 Poppler；OCR另外需要已安装的 OCR 引擎和语言数据。完整 PDF 可在支持的桌面浏览器中打开。",
        ],
    ),
]


def home_result_summary(result):
    parts = []
    if result.get("comparison"):
        parts.append(
            "跨论文比较"
            + (f" · {result['paper_count']} 篇" if result.get("paper_count") else "")
        )
    if result.get("records"):
        parts.append(f"{result['records']} 条结构化记录")
    if result.get("claims"):
        parts.append(f"{result['claims']} 项主张")
    if not result.get("records") and not result.get("claims"):
        parts.append("尚无已交付的数据或主张")
    parts.append(f"{result['revisions']} 次修订")
    return " · ".join(parts)


class HomePages:
    def start_with_example(self):
        """Fill a public example; acquisition still requires its own preview/start."""
        self.acquisition_example_text = "10.1038/s41467-019-08805-x"
        self.navigate("获取论文")

    def first_steps(self, active):
        from nicegui import ui

        with ui.card().classes("an-card w-full gap-4 mt-3"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.column().classes("gap-1"):
                    ui.label("十分钟开始").classes("an-section-title")
                    ui.label("先完成一篇文献的入库、解析和检索。").classes("an-muted")
                ui.button(
                    "查看首次操作指南", icon="menu_book", on_click=self.guide_dialog
                ).props("flat")
            with ui.grid(columns=3).classes("w-full an-parameter-grid gap-5"):
                with ui.column().classes("gap-3 min-w-0"):
                    ui.badge("01 · 确认文库").props("outline color=teal-7")
                    ui.label("可先使用当前目录，也可打开已有文库。").classes("text-sm")
                    ui.label(str(self.ctx.library.root)).classes(
                        "an-muted text-xs break-all"
                    )
                    ui.button(
                        "查看 / 更换文库",
                        icon="folder_open",
                        on_click=self.settings_dialog,
                    ).props("outline")
                with ui.column().classes("gap-3 min-w-0"):
                    ui.badge("02 · 放入第一篇").props("outline color=teal-7")
                    ui.label(
                        "已有 PDF 可直接导入；在线获取先确认 DOI 或标题。"
                    ).classes("text-sm")
                    ui.button(
                        "导入本地 PDF", icon="upload_file", on_click=self.import_dialog
                    ).props("unelevated color=teal-7")
                    ui.button(
                        "粘贴 DOI / 标题",
                        icon="content_paste",
                        on_click=lambda: self.navigate("获取论文"),
                    ).props("outline")
                    ui.button(
                        "填入公开论文示例",
                        icon="lightbulb_outline",
                        on_click=self.start_with_example,
                    ).props("flat dense")
                    ui.label("示例只填入 DOI，下载由你另行启动。").classes(
                        "an-muted text-xs"
                    )
                with ui.column().classes("gap-3 min-w-0"):
                    ui.badge("03 · 解析后搜一次").props("outline color=teal-7")
                    ui.label(
                        "在文库勾选论文，点击“解析已勾选”；完成后用正文关键词检索并核对原页。"
                    ).classes("text-sm")
                    ui.button(
                        "打开文库并解析",
                        icon="document_scanner",
                        on_click=lambda: self.navigate("文献库"),
                    ).props("outline")
                    ui.button(
                        "打开科研检索",
                        icon="manage_search",
                        on_click=lambda: self.navigate("科研检索"),
                    ).props("flat")
            ui.label("本地导入、原生解析和关键词检索无需 API 密钥或远程模型。").classes(
                "an-info text-sm w-full"
            )
            if active:
                ui.button(
                    f"查看正在处理的 {len(active)} 个任务",
                    icon="pending_actions",
                    on_click=self.task_dialog,
                ).props("outline")

    def home_page(self):
        from nicegui import ui

        from .jobs import TERMINAL
        from .labels import status_label, value_label

        papers = self.ctx.library.scan()["items"]
        jobs = self.ctx.jobs.list()
        active = [j for j in jobs if j["status"] not in TERMINAL]
        parsed = sum(r.get("parse_status") in {"PARSED", "PARTIAL"} for r in papers)
        supplements = sum(r.get("si_count", 0) for r in papers)
        selected = len(self.ctx.library.selection())
        with ui.card().classes("an-hero w-full"):
            with ui.row().classes("w-full justify-between items-start gap-10"):
                with ui.column().classes("gap-3 grow"):
                    ui.label("ALETHEIA NEXUS  /  本地科研工作台").classes(
                        "an-hero-kicker"
                    )
                    ui.label("从文献，到可信的研究积累。").classes("an-hero-title")
                    ui.label(
                        "获取、整理、检索与分析，在同一处完成。\n有引用的研究结果可回到原文核对，证据不足会明确提示。"
                    ).classes("an-hero-copy whitespace-pre-line")
                    with ui.row().classes("gap-3 mt-3"):
                        ui.button(
                            "开始获取论文",
                            icon="add",
                            on_click=lambda: self.navigate("获取论文"),
                        ).props("unelevated color=teal-7 size=lg")
                        ui.button(
                            "打开文献库",
                            icon="local_library",
                            on_click=lambda: self.navigate("文献库"),
                        ).props("outline color=white size=lg")
                with ui.column().classes("an-hero-aside gap-2"):
                    ui.icon("hub", size="58px").style("color:#7dd8ce")
                    ui.label("本地优先 · 证据可追溯").classes("font-semibold text-base")
                    ui.label("原文保留 · 版本独立 · 明确授权").classes(
                        "text-xs opacity-70"
                    )
                    ui.button(
                        "阅读操作指南", icon="menu_book", on_click=self.guide_dialog
                    ).props("flat color=white").classes("mt-2")
        if not papers:
            self.first_steps(active)
            return
        with ui.grid(columns=4).classes("w-full an-stat-grid gap-4 mt-2"):
            for number, label, icon, detail in (
                (len(papers), "文库论文", "description", "正文按逻辑身份计数"),
                (supplements, "关联 SI", "attach_file", "独立附件，不重复计论文"),
                (parsed, "已登记解析", "document_scanner", "完整与部分解析均可检查"),
                (
                    len(active),
                    "正在处理",
                    "pending_actions",
                    f"当前选择清单 {selected} 篇",
                ),
            ):
                with ui.card().classes("an-card an-stat-card"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(label).classes("an-muted text-sm")
                        ui.icon(icon, size="22px").style("color:#3e9091")
                    ui.label(str(number)).classes("an-stat-number")
                    ui.label(detail).classes("an-muted text-xs")
        with ui.row().classes("w-full items-center justify-between mt-5"):
            ui.label("继续你的研究").classes("an-section-title")
            ui.button(
                "完整操作指南", icon="help_outline", on_click=self.guide_dialog
            ).props("flat")
        with ui.grid(columns=4).classes("w-full an-stat-grid gap-4"):
            for number, title, detail, icon, page in (
                (
                    "01",
                    "获取与入库",
                    "DOI、中英文标题、清单或已有 PDF",
                    "cloud_download",
                    "获取论文",
                ),
                (
                    "02",
                    "整理与解析",
                    "标签、集合、中文命名与分类统一 SI",
                    "inventory_2",
                    "文献库",
                ),
                (
                    "03",
                    "检索与选材",
                    "按关键词检查原文证据，建立研究范围",
                    "manage_search",
                    "科研检索",
                ),
                (
                    "04",
                    "分析与核对",
                    "审阅任务计划、授权执行、回到原页",
                    "science",
                    "AI 研究",
                ),
            ):
                with ui.card().classes("an-card an-flow-card"):
                    with ui.row().classes("w-full justify-between items-center"):
                        ui.icon(icon, size="30px").style("color:#17678b")
                        ui.label(number).classes("an-step-number")
                    ui.label(title).classes("font-semibold text-lg mt-3")
                    ui.label(detail).classes("an-muted text-sm min-h-10")
                    ui.button(
                        {
                            "获取论文": "获取论文",
                            "文献库": "整理文库",
                            "科研检索": "检索原文",
                            "AI 研究": "新建研究",
                        }[page],
                        icon="arrow_forward",
                        on_click=lambda p=page: self.navigate(p),
                    ).props("flat dense").classes("mt-3")
        with ui.grid(columns=2).classes("w-full an-overview-grid gap-5 mt-5"):
            with ui.card().classes("an-card w-full gap-3"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("近期任务").classes("an-section-title")
                    ui.button(
                        "任务中心", icon="arrow_forward", on_click=self.task_dialog
                    ).props("flat dense")
                if not jobs:
                    ui.label(
                        "还没有任务。获取或导入第一篇文献后，处理历史会保存在这里。"
                    ).classes("an-muted py-5")
                for job in jobs[:4]:
                    with ui.row().classes("w-full items-center an-recent-row"):
                        ui.icon(
                            "task_alt"
                            if job["status"] in {"COMPLETED", "PARTIAL"}
                            else "pending_actions",
                            size="20px",
                        ).classes("an-muted")
                        with ui.column().classes("grow gap-0 min-w-0"):
                            ui.label(job["label"]).classes(
                                "font-medium text-sm truncate max-w-[400px]"
                            )
                            ui.label(
                                value_label(job.get("stage") or "任务已保存")
                            ).classes("an-muted text-xs")
                        ui.badge(status_label(job["status"])).props(
                            "outline color=teal-7"
                        )
            with ui.card().classes("an-card w-full gap-3"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("研究成果").classes("an-section-title")
                    ui.button(
                        "全部成果",
                        icon="arrow_forward",
                        on_click=lambda: self.navigate("研究成果"),
                    ).props("flat dense")
                results = self.ctx.research.results()[:3]
                if not results:
                    ui.label(
                        "审阅计划并执行科研任务后，可在这里继续核对、修订与导出。"
                    ).classes("an-muted py-5")
                for result in results:
                    with ui.column().classes("w-full an-recent-row gap-1"):
                        ui.label(result["objective"]).classes("font-medium text-sm")
                        ui.label(home_result_summary(result)).classes(
                            "an-muted text-xs"
                        )

                        def open_result(path=result["path"]):
                            self.current_result = path
                            self.navigate("研究成果")

                        ui.button(
                            "继续核对", icon="fact_check", on_click=open_result
                        ).props("flat dense")
        ui.label(
            "科研结果需要结合原文逐项判断；引用可定位与科学内容正确是两个独立的核对维度。"
        ).classes("an-muted text-xs mt-3")

    def guide_dialog(self):
        from nicegui import ui

        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[1050px] max-w-[96vw] an-card"),
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("工作台操作指南").classes("an-title")
                ui.button(icon="close", on_click=dialog.close).props("flat round")
            ui.label("从第一篇文献开始，逐步建立可追溯、可复用的研究资料。").classes(
                "an-muted"
            )
            query = (
                ui.input("查找操作，例如：中文命名、SI、费用、恢复", value="")
                .props("outlined clearable")
                .classes("w-full")
            )
            expansions = []
            with ui.scroll_area().classes("w-full h-[65vh]"):
                for i, (label, title, paragraphs) in enumerate(GUIDE):
                    with ui.expansion(
                        f"{i + 1:02d}  {label} · {title}",
                        value=i == 0,
                        icon="menu_book",
                    ).classes("w-full an-guide-section") as expansion:
                        for n, paragraph in enumerate(paragraphs, 1):
                            with ui.row().classes(
                                "w-full gap-3 items-start py-2 no-wrap"
                            ):
                                ui.badge(str(n)).props("outline color=teal-7").classes(
                                    "mt-1"
                                )
                                ui.label(paragraph).classes("text-sm leading-7 grow")
                    expansions.append(
                        (expansion, " ".join([label, title, *paragraphs]).casefold())
                    )

            def filter_sections():
                value = (query.value or "").strip().casefold()
                for expansion, text in expansions:
                    expansion.set_visibility(not value or value in text)
                    if value and value in text:
                        expansion.set_value(True)

            query.on_value_change(lambda _: filter_sections())
            ui.button("开始使用", icon="check", on_click=dialog.close)
        dialog.open()
