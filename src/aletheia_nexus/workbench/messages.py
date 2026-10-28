"""Chinese explanations at the UI boundary, without changing public error codes.

``error_record`` retains the redacted original diagnostic for an expert/details
panel. ``user_message`` is for ordinary controls and task summaries. Unknown
failures remain failures and their original reason is never discarded.
"""

from __future__ import annotations

import errno
import json
import os
import re
from enum import Enum

_MESSAGES = {}


def _add(keys, message):
    for key in keys:
        _MESSAGES[key.casefold()] = message


_add(
    ("Unreadable library record",),
    "该来源记录或对应文件无法读取或未通过核验。请检查所列路径、缺失文件和原始来源记录；恢复正确材料后重新扫描。",
)
_add(
    ("Unreadable library labels; acquisition labels retained",),
    "独立标签记录无法读取或与文件不匹配，暂时保留原来源中的标签。请检查可变标签记录，原 PDF 和来源证据未被改写。",
)
_add(
    ("identical source copies share one paper identity",),
    "发现内容与来源完全相同的多个副本，已按同一论文身份计数。请检查所列重复路径及历史引用，再决定是否整理副本。",
)


_add(
    ("pdf_not_found", "FileNotFoundError"),
    "找不到所选文件。请检查文件是否被移动、删除或位于未连接的磁盘，再刷新文献库。",
)
_add(
    ("sidecar_not_found",),
    "缺少与 PDF 对应的来源记录。请恢复原始来源文件；已有本地 PDF 可通过“导入”登记，不能将缺失记录当作来源核验成功。",
)
_add(
    ("unverified_path", "status_not_verified", "retrieved_unverified"),
    "该文件尚未通过来源核验，不能直接作为已验证正文进入后续处理。请查看获取诊断，或明确登记为用户提供的本地文献。",
)
_add(
    (
        "invalid_sidecar",
        "unknown_sidecar_schema",
        "invalid_recorded_hash",
        "unsupported_acquisition_record",
        "existing acquisition evidence is incomplete; import cannot promote or replace it",
    ),
    "来源记录损坏、不完整或版本不受支持。请恢复对应的原始记录，或重新获取；系统不会改写证据来使其通过核验。",
)
_add(
    (
        "pdf_validation_failed",
        "pdf_unreadable",
        "invalid_pdf",
        "invalid_supplement_pdf",
    ),
    "文件不是可读取的有效 PDF，或需要密码。请检查是否误存了登录页面、下载是否完整，以及 PDF 是否能正常打开。",
)
_add(
    (
        "pdf_hash_mismatch",
        "sidEcar_changed",
        "workspace_source_hash_mismatch",
        "workspace_pdf_hash_mismatch",
        "main PDF hash does not match source evidence",
        "attachment hash does not match its registry",
    ),
    "文件内容与保存的来源指纹不一致。请保留现有证据并恢复正确文件，或作为新的来源版本登记；不要用同名文件替换原始材料。",
)
_add(
    (
        "identity_not_matched",
        "source_identity_mismatch",
        "historical_source_identity_mismatch",
        "page_mismatch",
        "mismatch",
    ),
    "文献身份与记录不一致。请核对 DOI、标题、正文及附件归属，恢复正确材料后再继续；不会自动把相近论文当作同一来源。",
)
_add(
    ("doi_mismatch",),
    "输入的 DOI 与文件来源记录不一致。请核对文献身份并选择正确记录，不要修改原始来源中的 DOI 来绕过检查。",
)
_add(
    ("page_count_mismatch",),
    "PDF 实际页数与来源记录不同，文件可能已被替换。请恢复原始 PDF，或将新文件登记为独立来源。",
)
_add(
    (
        "document_not_article",
        "known SUPPLEMENT cannot be imported as an ARTICLE; use import_attachment(parent_id, path) to associate it explicitly",
    ),
    "所选文件属于 SI 或其它附件，不能作为独立正文导入。请打开对应论文的详情，通过“关联本地附件”明确指定所属正文。",
)
_add(
    ("original bibliographic identity is immutable",),
    "真实书目原题、DOI 和来源身份不能通过此操作覆盖。请使用“自定义显示名称”或单独编辑中文译名；来源证据保持不变。",
)
_add(
    ("a confirmed/manual translation requires explicit manual replacement",),
    "已有人工编辑或确认的译名受到保护。请在文献详情中明确手工修改，不会用模型结果自动覆盖。",
)
_add(
    (
        "source_changed_while_copying",
        "source_changed_after_authorization",
        "PDF changed while copying",
        "source record changed while copying",
        "import changed during publication",
        "attachment source changed while copying",
        "attachment source evidence changed while copying",
        "attachment_changed_during_copy",
        "file changed during move",
    ),
    "操作期间文件或来源记录发生变化，已停止继续处理。请等待其它程序完成写入，检查文件完整性后重新预览或重新导入。",
)
_add(
    ("source_already_registered_use_prepare_documents",),
    "该文件已有来源记录。请直接选择已有文献或解析版本；不要重新登记来覆盖原始身份。",
)
_add(
    ("existing attachment changed; restore it before reimport",),
    "已登记附件的内容发生变化。请先恢复正确附件，或为变更后的文件保留独立来源，再重新导入。",
)
_add(
    ("parent moved during attachment preparation; retry with its new location",),
    "准备附件时所属正文已被移动。请刷新文献库，再从该论文的新位置关联附件。",
)
_add(
    (
        "existing source evidence declares another parent or an ARTICLE; it cannot be relabelled",
        "attachment source record has a different parent or role",
    ),
    "该文件的原始记录指向其它正文，或明确声明为独立论文。请选择正确附件与所属正文，系统不会篡改原记录来重新归属。",
)
_add(
    (
        "the main article cannot be imported as its own attachment",
        "an article cannot be its own attachment",
        "attachment_duplicates_main_article",
    ),
    "所选附件与正文是同一份文件。请改选真正的 SI 或其它附件，避免重复登记正文。",
)
_add(
    ("attachments must be in the parent category's shared SI directory",),
    "附件应存放在所属正文分类目录内唯一的 SI/ 子目录。请使用“关联本地附件”或分类迁移功能，由系统同步整理。",
)
_add(
    (
        "select an existing parent paper",
        "attachment parent must be a registered main article",
        "attachments require a main article",
    ),
    "请先在文献库中选择已登记的正文，再明确关联其 SI 或其它附件。",
)
_add(
    ("unsupported attachment role",),
    "附件角色不受支持。请选择 SI、源数据、报告摘要、同行评审材料或其它附件，并核对实际用途。",
)
_add(
    (
        "unsupported local attachment extension; executable and active HTML files are not accepted",
    ),
    "此附件类型暂不接受；可执行文件和可运行的网页文件不能导入。请选择受支持的数据、文档、图片或媒体附件。",
)
_add(
    ("local attachment exceeds the 200 MiB limit",),
    "本地附件超过 200 MiB 上限。请保留原文件，并选用较小的受支持附件；系统未自动截断或解析它。",
)
_add(("empty_attachment",), "附件为空文件。请重新下载或选择完整文件后重试。")
_add(
    ("attachment_is_html_or_login_page",),
    "下载内容是网页或登录页面，并非真正的附件。请完成必要登录，或从官方页面手动取得附件后关联。",
)
_add(
    ("archive_declared_contents_exceed_limit",),
    "压缩包声明的文件数或解压后大小超过安全上限，已拒绝导入。请检查原始附件；系统未展开压缩包。",
)
_add(
    ("encrypted_attachment_archive",),
    "压缩包已加密，当前不能验证其内容。请取得可读取的官方附件或保留在外部；系统未尝试破解密码。",
)
_add(
    ("invalid_office_attachment", "invalid_legacy_excel_attachment"),
    "附件内容与所声明的办公文档格式不符。请确认下载完整、扩展名正确，并检查是否误存了登录页面。",
)
_add(
    ("binary_content_in_text_attachment",),
    "附件声明为文本，却包含二进制内容。请核对文件类型和真实扩展名后重新导入。",
)
_add(
    ("invalid_png_attachment", "invalid_jpeg_attachment"),
    "图片内容与扩展名不符或文件不完整。请检查原始图片后重新选择。",
)
_add(
    (
        "unsafe_si_directory",
        "unsafe_si_record_directory",
        "attachment_target_is_symbolic_link",
        "symbolic links are not permitted for library files",
        "library state must not be a symbolic link",
        "library lock must not be a symbolic link",
        "source PDF must not be a symbolic link",
        "source records must not be symbolic links",
        "source record must not be a symbolic link",
        "source labels must not be symbolic links",
        "attachment source must not be a symbolic link",
        "state files cannot be symbolic links",
        "settings cannot be a symbolic link",
        "Symbolic links cannot be served",
        "Selected path became a symbolic link",
    ),
    "所选文件或目录是符号链接、目录联接或不安全的跳转位置。请直接选择授权文库内的真实文件或目录，避免越界读写。",
)
_add(
    (
        "path_outside_allowed_directories",
        "path is outside the selected library",
        "File is outside the current workbench",
        "checkpoint source outside library",
        "acquisition output outside library",
        "reference adapter directory is outside authorized roots",
    ),
    "路径超出当前明确授权的文库或工作区。请改选允许范围内的位置，或在设置中明确切换文库。",
)
_add(
    ("authorization_directory_private", "Private credentials cannot be served"),
    "认证或密钥目录不能通过工作台读取或下载。请选择论文、附件或科研结果文件。",
)
_add(
    ("Selected file changed location", "Selected file bytes changed"),
    "此前选中的文件位置或内容已变化。请关闭旧预览，从当前文库重新打开经过核验的文件。",
)
_add(
    (
        "attachment target exceeds the portable 240-character path limit",
        "target path exceeds the portable 240-character limit",
    ),
    "目标完整路径超过 240 字符的兼容上限。请缩短文库路径、分类名称或文件基础名称，再重新预览。",
)
_add(
    ("case-insensitive target collision",),
    "目标名称在忽略大小写后与已有文件冲突。请调整名称或使用预览中的身份短码，系统不会覆盖现有文件。",
)
_add(
    ("filename template contains an unsupported field", "invalid filename template"),
    "命名模板包含当前不支持的字段或格式。请使用界面列出的年份、期刊、第一作者、原题、中文译名或自定义名称字段。",
)
_add(
    ("filename has no available metadata",),
    "当前模板所需的元数据全部缺失，无法生成有意义的文件名。请补齐信息、选择原题回退，或手工填写最终名称。",
)
_add(
    ("missing Chinese translation; translate here or choose original-title fallback",),
    "缺少中文译名。可在当前整理流程中授权补译、回退使用原题，或跳过此篇后继续其它论文。",
)
_add(
    ("missing translation policy must be fallback or skip",),
    "请选择缺失译名时的处理方式：补译后预览、回退原题或跳过缺失项。",
)
_add(
    (
        "rename preview belongs to a different library",
        "operation belongs to a different library",
    ),
    "这份预览或文件操作记录属于另一个文库。请切换到原文库，或为当前文库重新生成预览。",
)
_add(
    ("rename preview changed; generate a new preview",),
    "预览内容已被修改或失效，尚未开始文件移动。请应用逐篇修改并重新预检，再确认执行。",
)
_add(
    ("invalid operation ID",),
    "文件操作记录编号无效。请从任务中心选择已保存的真实记录，保留原始恢复文件。",
)
_add(
    ("file operation owner exited before completion",),
    "文件操作进程在完成前已退出。请在任务中心查看迁移日志并执行核验后的恢复或回滚，不要手工覆盖目标文件。",
)
_add(
    (
        "unknown paper identity",
        "selection contains unknown paper identities",
        "collection contains unknown papers",
        "Selected paper is unavailable; refresh the library selection",
    ),
    "所选论文已不在当前文库，或选择记录已经失效。请刷新文库、检查缺失文件，并重新确认实际操作范围。",
)
_add(
    ("invalid selection mode",),
    "选择清单操作不受支持。请使用替换、追加或移除选择的界面操作。",
)
_add(
    ("tags must be non-empty labels of at most 80 characters", "invalid tag group"),
    "标签不能为空、不能包含控制字符，且最多 80 字符。请检查标签及分组中的输入。",
)
_add(
    ("provide a name of at most 100 characters",),
    "名称不能为空，且最多 100 字符。请缩短名称后保存。",
)
_add(
    ("preset name must contain 1–120 characters",),
    "预设名称须为 1–120 字符。请填写便于识别的名称后保存。",
)
_add(
    ("view requires a column list",),
    "表格视图缺少显示列。请至少选择需要显示的列，再保存视图。",
)
_add(
    ("unsupported filter rules",),
    "保存筛选包含不支持的条件。请从当前界面重新设置目录、标签、关键词或解析状态。",
)
_add(
    (
        "unsupported library registry schema",
        "unsupported workbench settings version",
        "Invalid workbench document index",
        "invalid named library section",
        "unsupported reference adapter",
    ),
    "本地元数据的版本或结构不受当前程序支持。请保留原文件并使用匹配版本，或从备份恢复；系统不会静默重写它。",
)
_add(
    ("Do not save API keys, tokens, passwords or cookies",),
    "设置和预设不能保存 API 密钥、认证令牌、密码或登录 Cookie。请使用系统环境变量或现有浏览器会话配置。",
)
_add(
    (
        "unsupported acquisition checkpoint schema",
        "invalid acquisition checkpoint records",
    ),
    "获取检查点的版本或内容无效。请保留旧检查点，核对原任务后新建恢复任务，不能用文件存在代替来源核验。",
)
_add(
    ("checkpoint relocation requires one hash-and-source-verified library match",),
    "无法把旧检查点唯一对应到当前文库中内容与来源指纹均一致的正文。请核对重复副本或缺失文件，再重新确认恢复范围。",
)
_add(
    ("checkpoint must be inside acquisition state directory",),
    "检查点必须位于本工作台的获取任务目录。请从任务中心选择该工作区保存的检查点。",
)
_add(
    (
        "acquisition options must be an object",
        "unsupported browser options",
        "Unsupported parsing option",
    ),
    "配置结构或选项不受当前版本支持。请恢复该模块的默认设置，再逐项修改界面已提供的参数。",
)
_add(
    ("interaction_policy must be wait, skip or pause",),
    "人工验证策略无效。请选择等待处理、跳过当前论文或暂停批次。",
)
_add(
    ("source_preference must be auto, cnki or exclude_cnki",),
    "来源策略无效。请选择自动来源、知网或排除知网。",
)
_add(
    ("disable public_only only after explicitly enabling browser access",),
    "机构或浏览器获取需要明确启用浏览器访问。请先选择机构浏览器策略，再调整仅公开获取选项。",
)
_add(
    (
        "CNKI requires the explicitly enabled institutional browser strategy",
        "title-only CNKI acquisition requires the explicitly enabled institutional browser strategy",
    ),
    "知网标题获取需要明确启用机构浏览器。请选择相应策略，使用已有合法访问权限，并按提示完成人工登录。",
)
_add(
    (
        "official authenticated APIs require the full access strategy; public_only disables them",
    ),
    "当前“仅公开获取”策略不会使用已授权的官方 API。请核对权限后选择完整获取策略，并在环境中配置对应凭据。",
)
_add(
    ("item attempts and SI limits must be positive",),
    "每篇尝试次数与 SI 数量上限必须大于零。请检查高级获取设置。",
)
_add(
    ("provide pasted lines or a TXT, CSV, JSON paper list",),
    "请输入 DOI 或标题，或选择受支持的 TXT、CSV、JSON 文献清单。",
)
_add(
    ("select at least one paper", "select a PDF", "Select evidence first"),
    "请先选择需要处理的论文、PDF 或证据，再执行此操作。",
)
_add(
    ("resolve and confirm English title identity before acquisition",),
    "英文标题尚未完成身份解析。请查看候选的作者、年份、期刊和 DOI，并人工确认正确论文后再获取全文。",
)
_add(
    ("title candidate limit must be 1..30",),
    "标题候选数量必须为 1–30。请调整标题解析设置。",
)
_add(
    ("invalid Crossref title search response",),
    "书目服务返回的标题检索内容无效。请稍后重试，或手工输入经过核对的 DOI；不会猜测或编造 DOI。",
)
_add(
    ("acquisition engine returned an unverified main document",),
    "获取引擎尚未交付通过来源核验的正文。请查看逐篇诊断与隔离文件，不能将其显示为获取成功。",
)
_add(
    ("interaction timeout cannot be negative",),
    "人工等待时间不能为负数。请选择不限时等待，或填写大于等于零的有效秒数。",
)
_add(
    ("This workspace already has an active task manager",),
    "该工作区已有后台任务进程占用。请使用已打开的工作台，或关闭原进程后再启动；不要同时改写同一任务目录。",
)
_add(
    ("task manager is closed",),
    "后台任务调度器已关闭。请重新打开工作台，确认中断任务后再提交操作。",
)
_add(
    ("unknown previous task",),
    "找不到要恢复的历史任务。请核对工作区，并从已有记录中新建经过确认的恢复任务。",
)
_add(
    (
        "A finished task cannot be resumed automatically; create a reviewed recovery task",
    ),
    "该任务已经结束，不能直接恢复原进程。请检查已有结果和费用，再创建明确授权的恢复或重试任务。",
)
_add(
    ("unsupported task control",),
    "当前任务不支持此控制操作。请使用界面提供的暂停、继续、跳过或取消入口。",
)
_add(
    (
        "cancelled_at_safe_boundary",
        "cancelled_during_interaction",
        "user_skipped_interaction",
    ),
    "任务已按人工选择在安全边界停止或跳过当前项；已完成的文件与结果保留。请在任务中心查看逐项记录。",
)
_add(
    ("OCR and new_version must be booleans",),
    "OCR 和新建解析版本选项必须为开启或关闭。请使用界面开关重新设置。",
)
_add(
    ("Invalid OCR language selection",),
    "OCR 语言格式无效。请填写已安装的语言代码，多种语言用加号连接，例如 eng+chi_sim。",
)
_add(
    (
        "Parsed version is outside this selected paper",
        "Unknown parsed version; select a recorded immutable artifact",
    ),
    "所选解析版本不属于当前论文，或版本记录已失效。请从该论文保存的版本列表中重新选择。",
)
_add(
    (
        "Selected materials contain unparsed/failed sources",
        "Resolve unavailable selected materials before planning",
        "parser_problem",
    ),
    "所选材料包含尚未解析、解析失败或不可读取的来源。请先查看解析诊断并完成必要解析，再创建科研任务。",
)
_add(
    ("Search page size/offset out of range",),
    "检索分页的起始位置或每页数量超出范围。请使用有效的分页设置重新检索。",
)
_add(
    ("Export display name must contain 1–200 characters",),
    "导出显示名称须为 1–200 字符。请填写较短且便于识别的名称。",
)
_add(
    ("page_out_of_bounds", "page_out_of_range", "Invalid physical PDF page"),
    "物理 PDF 页码超出实际页数。请从第一页开始计数，并检查正文与 SI 各自独立的页码范围。",
)
_add(
    (
        "explicit_planning_consent_required",
        "explicit_research_consent_required",
        "title_translation_remote_consent_required",
        "remote_requires_task_permission_and_cost_limit",
        "local_authorization_required",
    ),
    "尚未授权这次远程模型请求。请核对实际文献或标题范围、模型参数和费用上限，再明确确认外发与预算；系统不会默认上传文库。",
)
_add(
    ("explicit_human_revision_required",),
    "人工修订或确认必须由用户明确执行。请核对证据、填写修改理由，再保存新的结果版本。",
)
_add(
    ("remote_disabled", "network_disabled"),
    "当前入口未启用所需的网络或远程模型权限。请核对任务范围，并通过工作台提供的明确授权流程启用。",
)
_add(
    ("missing_api_key",),
    "未配置模型 API 密钥。请在启动工作台的系统环境中设置相应密钥后重新启动；不要把密钥填入任务或预设。",
)
_add(
    ("authorization_expired_or_changed", "authorization_missing_or_used"),
    "本次授权已过期、已使用，或任务材料发生变化。请重新检查实际范围和预算，获得新的明确授权后继续。",
)
_add(
    ("call_budget_exhausted",),
    "模型请求次数已达到本任务上限，后续请求已停止。请先查看已有结果和调用记录，再决定是否创建新的授权任务。",
)
_add(
    ("cost_budget_exhausted",),
    "预计费用将超过本任务上限，尚未继续发送请求。请查看已用额度和保留结果，再明确调整预算。",
)
_add(
    ("cost_estimate_unavailable",),
    "费用估算信息不足，无法在设定上限内继续请求。请补齐模型单价或核对前次未知用量；未返回用量的请求可能已计费。",
)
_add(
    ("request_body_budget_exceeded",),
    "本次发送的文本或图片超过请求材料预算。请缩小文献、页码或图片范围，再重新检查任务。",
)
_add(
    ("authentication_failed", "auth_required"),
    "当前来源或 API 需要有效认证。请检查密钥或使用已授权的浏览器完成人工登录，确认后再继续。",
)
_add(
    ("permission_denied", "access_denied", "access_blocked", "entitlement_required"),
    "当前账号或机构没有所需访问权限，或来源已明确拒绝访问。请核对合法授权；系统不会绕过订阅、验证码或权限控制。",
)
_add(
    ("quota_exhausted",),
    "模型服务余额或调用额度不足。请核对服务商账户与账单，确认后再手工重试。",
)
_add(
    ("rate_limited",),
    "来源或模型服务正在限流。请停止连续重试，等待服务允许后再恢复；增加请求间隔不代表可以绕过限制。",
)
_add(
    ("timeout", "ReadTimeout", "ConnectTimeout", "TimeoutError"),
    "请求超时，尚不能确认远程操作是否完成；模型请求可能已计费。请保留当前检查点，核对调用记录和服务商账单后再决定是否重试。",
)
_add(
    (
        "network_error",
        "ConnectError",
        "ProxyError",
        "RemoteProtocolError",
        "request_error",
    ),
    "网络、代理或连接异常。请检查网络设置；涉及模型的请求可能已经发出，核对调用记录后再重试。",
)
_add(
    (
        "service_error",
        "invalid_response",
        "retrieval_failed",
        "navigation_error",
        "redirect_error",
    ),
    "来源服务返回错误、无效响应或导航失败。请查看具体来源诊断，检查网络与访问权限后再手工重试。",
)
_add(
    ("browser_unavailable",),
    "机构浏览器不可用。请安装浏览器可选依赖及所需浏览器，检查会话配置，再重新启动工作台。",
)
_add(
    ("interaction_required",),
    "当前论文需要人工登录或验证。请在可见浏览器中完成操作，再选择继续、跳过当前论文或暂停批次。",
)
_add(
    ("ambiguous",),
    "找到多个相近候选，尚未确定论文身份。请结合作者、年份、期刊和 DOI 人工确认，系统不会自动选第一项。",
)
_add(
    ("not_found", "no_file_candidates", "exhausted"),
    "当前受支持路线未找到可验证的目标文件。请检查书目身份、合法访问权限或改用手动导入；这不代表论文或 SI 一定不存在。",
)
_add(
    ("unsafe_url",),
    "下载地址未通过安全检查。请使用受支持的公开或官方来源，不会访问本机、内网或不安全跳转地址。",
)
_add(
    ("too_large",),
    "文件超过当前下载或处理大小上限。请核对文件类型和参数，必要时选择更小的合法来源。",
)
_add(
    ("translation_identity_mismatch",),
    "模型返回的标题编号有缺失、重复或不匹配，本批译名未按错误顺序写入。请检查响应并明确重试，原题保持不变。",
)
_add(
    ("invalid_title_translation", "translation must contain 1–5000 characters"),
    "译名为空、过长或不符合要求。请填写 1–5000 字符的有效译名，或检查模型响应后重试。",
)
_add(
    ("paper has no original title", "original title exceeds 5000 characters"),
    "原始标题缺失或超过 5000 字符，无法安全发起标题翻译。请核对书目来源或输入清单。",
)
_add(
    ("original title changed during translation",),
    "翻译过程中原始标题发生变化，结果未套用到新的身份。请刷新书目并重新确认需要翻译的标题。",
)
_add(
    ("invalid target language",),
    "目标语言设置无效。请使用界面提供的语言选项或有效语言代码。",
)
_add(
    ("translation timeout must be 1–300 seconds",),
    "标题翻译超时须为 1–300 秒。请调整翻译高级设置。",
)
_add(
    ("translation retries must be 0–3",),
    "标题翻译自动重试次数须为 0–3。未知计费请求应先核对记录，再决定是否手工重试。",
)
_add(
    ("previous_call_requires_review",),
    "前一次模型请求需要人工检查，后续标题已暂缓处理。请查看失败原因、未知费用和已缓存译名后再恢复。",
)
_add(
    ("model_refusal",),
    "模型拒绝处理此次请求。请查看服务诊断并调整任务描述；原材料和已有结果保留。",
)
_add(
    (
        "model_incomplete",
        "invalid_model_output",
        "invalid_json",
        "schema_validation_failed",
        "response_schema_invalid",
    ),
    "模型响应不完整或未符合科研结果格式。请保留原始响应，核对已用费用，再决定是否调整输出预算或明确重试。",
)
_add(
    ("job_owner_unavailable",),
    "无法取得任务的运行归属锁。请检查是否已有相同工作区的后台进程，不要重复启动可能收费的任务。",
)
_add(
    ("SI file limit must be 1..100",),
    "每篇论文的 SI 数量上限须为 1–100。请调整获取高级设置。",
)
_add(
    ("BadZipFile",),
    "压缩包或办公文档内部格式损坏。请取得完整的原始附件后重试；系统未展开或运行它。",
)
_add(
    ("PermissionError",),
    "文件被占用或当前用户没有访问权限。请检查目录权限，并关闭占用该文件的程序后重试。",
)
_add(
    ("ModuleNotFoundError", "ImportError"),
    "运行所需的可选组件尚未安装或无法加载。请打开“设置 → 环境诊断”，按安装指南补齐对应组件后重新启动。",
)
_add(
    ("Figure OCR requires the optional 'image-ocr' dependencies",),
    "图内文字识别所需的可选组件尚未安装。请按安装指南配置图像 OCR 依赖，再明确启用此功能。",
)
_add(
    ("OCR dpi must be at least 300",),
    "OCR 图像分辨率至少为 300 DPI。请提高解析设置中的分辨率。",
)
_add(
    ("OCR languages cannot be empty",),
    "OCR 语言不能为空。请选用已安装的语言代码，例如 eng 或 eng+chi_sim。",
)
_add(
    ("image_ocr must be tesseract or rapidocr",),
    "OCR 引擎不受支持。请选择当前已安装的 Tesseract 或 RapidOCR 引擎。",
)
_add(
    ("renderer and tesseract commands are required",),
    "缺少 PDF 渲染器或 OCR 程序配置。请在环境诊断中检查 Poppler 和 Tesseract，再重新解析。",
)

_add(
    ("explicit_supplement_page_consent_required",),
    "补充材料页面需要本次明确授权。请核对所属文献、实际补充页码、外发范围及预算，再确认是否发送给模型。",
)

_PREFIXES = (
    (
        "source changed after preview:",
        "预览后来源文件发生变化：",
        "请重新核对文件并生成预览。",
    ),
    (
        "references changed after preview:",
        "预览后历史引用发生变化：",
        "请重新检查引用风险后生成预览。",
    ),
    (
        "legacy explicit references require review:",
        "发现需要人工审查的历史路径引用：",
        "已拒绝此项移动；请保留旧文件，使用可追溯恢复方案或独立材料副本。",
    ),
    (
        "target already exists or is duplicated:",
        "目标文件已存在或本批名称重复：",
        "请修改最终名称并重新预检，系统不会覆盖它。",
    ),
    (
        "rollback would overwrite changed source:",
        "回滚可能覆盖已变化的原路径文件：",
        "请先核对该文件与操作日志，保留所有副本后再恢复。",
    ),
    (
        "rollback target changed:",
        "回滚目标内容已变化：",
        "请保留该文件并核对迁移日志，不会自动覆盖或删除变化后的内容。",
    ),
    (
        "rollback file missing or changed:",
        "回滚所需文件缺失或内容已变化：",
        "请根据迁移日志恢复正确文件，再重试回滚。",
    ),
    (
        "OCR executable is unavailable:",
        "本地 OCR 程序不可用：",
        "请在环境诊断中检查 Poppler、Tesseract 及系统路径配置。",
    ),
)
_FIELDS = {
    "batch_size": "每批标题数量",
    "max_calls": "模型请求次数上限",
    "max_output_tokens": "输出 Token 上限",
    "max_cost": "费用上限",
    "input_cost_per_million": "每百万输入 Token 估算单价",
    "output_cost_per_million": "每百万输出 Token 估算单价",
    "min_interval_seconds": "请求最小间隔",
    "interaction_timeout": "人工等待超时",
    "bulk_interval": "普通文献获取间隔",
    "cnki_interval": "知网文献获取间隔",
    "public_only": "仅公开获取",
    "include_si": "同时获取 SI",
    "heading_font_ratio": "标题字体比例",
    "min_text_characters": "最少文本字符数",
    "column_split_ratio": "分栏判定比例",
    "merge_paragraph_lines": "段落行合并",
    "page_segmentation_mode": "OCR 版面模式",
    "max_raster_pixels": "OCR 图像像素上限",
    "max_pages": "最大页数",
    "max_text_blocks": "文本块上限",
    "timeout_seconds": "单次请求超时",
    "min_native_characters": "原生文本最低字符数",
}
_SECRET_NAME = re.compile(
    r"api[_-]?key|secret|password|cookie|authorization|access[_-]?token", re.I
)
_UNKNOWN = "操作未完成，当前原因尚无已核实的中文说明。请展开“原始诊断”查看完整原因，保留记录后再处理；系统未自动将其当作成功。"


def _redact(value):
    value = str(value)
    for name, secret in os.environ.items():
        if _SECRET_NAME.search(name) and len(secret) >= 8:
            value = value.replace(secret, "[已隐藏凭据]")
    value = re.sub(
        r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/-]+=*", "[已隐藏认证令牌]", value
    )
    value = re.sub(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@", r"\1[已隐藏登录凭据]@", value)
    value = re.sub(
        r"""(?i)(["']?(?:api[_-]?key|password|secret|access[_-]?token|token)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s&,;]+)""",
        r"\1[已隐藏凭据]",
        value,
    )
    return re.sub(r"(?i)\bcookie\s*:\s*[^\r\n]+", "Cookie：[已隐藏登录信息]", value)


def _parts(value):
    if isinstance(value, dict):
        code = value.get("code") or value.get("error_type") or value.get("type") or ""
        raw = (
            value.get("raw")
            or value.get("raw_message")
            or value.get("message")
            or value.get("error")
            or code
        )
    else:
        code = getattr(value, "code", "")
        if isinstance(value, Enum):
            code = value.value
        raw = str(value) if value is not None else ""
    if isinstance(code, Enum):
        code = code.value
    return _redact(code), _redact(raw)


def error_record(value) -> dict:
    """Return a Chinese message plus unchanged/redacted machine diagnostics."""
    code, raw = _parts(value)
    text = raw.strip()
    message = _MESSAGES.get(code.casefold()) or _MESSAGES.get(text.casefold())
    if message is None and ":" in text:
        message = _MESSAGES.get(text.split(":", 1)[0].casefold())
    if message is None:
        for prefix, lead, recovery in _PREFIXES:
            if text.casefold().startswith(prefix):
                message = lead + text[len(prefix) :].strip() + "。" + recovery
                break
    if message is None and isinstance(value, json.JSONDecodeError):
        message = f"配置或清单的 JSON 格式无效，位于第 {value.lineno} 行、第 {value.colno} 列。请检查括号、逗号和引号后重试。"
    if message is None and isinstance(value, OSError):
        error_number = getattr(value, "errno", None)
        windows_number = getattr(value, "winerror", None)
        if isinstance(value, FileNotFoundError):
            message = _MESSAGES["filenotfounderror"]
        elif isinstance(value, FileExistsError):
            message = "目标文件已存在。请调整名称并重新预览，系统不会覆盖原有文件。"
        elif error_number in {
            errno.EACCES,
            errno.EPERM,
            errno.EBUSY,
        } or windows_number in {5, 32, 33}:
            message = "文件被占用或当前用户没有读写权限。请关闭占用它的 PDF 阅读器、同步工具或其它程序，并检查目录权限后重试。"
        elif error_number == errno.ENOSPC or windows_number == 112:
            message = "磁盘空间不足，操作未完成。请释放空间并检查任务日志，确认文件恢复状态后再重试。"
        elif error_number == errno.ENAMETOOLONG or windows_number == 206:
            message = (
                "完整文件路径过长。请缩短文库路径、分类名称或最终文件名后重新预览。"
            )
        elif error_number in {errno.EXDEV, errno.ENOTSUP}:
            message = "当前文件系统不支持本次安全文件迁移。请使用同一磁盘内支持硬链接的目录，并查看日志确认回滚状态。"
        if message and getattr(value, "filename", None):
            message += " 相关路径：" + _redact(value.filename)
    if message is None and isinstance(value, BaseException):
        message = _MESSAGES.get(type(value).__name__.casefold())
    if message is None:
        match = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_.]*) must be between ([\d.]+) and ([\d.]+)", text
        )
        if match:
            field, low, high = match.groups()
            message = f"{_FIELDS.get(field, '指定参数')}须在 {low}–{high} 范围内。请调整对应设置后重试。"
        match = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_.]*) must be (boolean|a boolean|an integer|a positive integer|a finite non-negative number|a positive finite amount|a number|finite|positive)",
            text,
        )
        if message is None and match:
            field, rule = match.groups()
            rule_zh = {
                "boolean": "开启或关闭",
                "a boolean": "开启或关闭",
                "an integer": "整数",
                "a positive integer": "正整数",
                "a finite non-negative number": "大于等于零的有限数值",
                "a positive finite amount": "大于零的有限金额",
                "a number": "数值",
                "finite": "有限数值",
                "positive": "大于零的数值",
            }[rule]
            message = (
                f"{_FIELDS.get(field, '指定参数')}必须为{rule_zh}。请检查对应设置。"
            )
        if message is None and text.startswith(
            (
                "unknown translation options:",
                "unsupported acquisition options:",
                "paper fields:",
            )
        ):
            message = "输入包含当前版本不支持的字段。请使用界面提供的选项，或查看原始诊断确认具体字段。"
        if message is None and text.startswith("invalid ") and text[8:] in _FIELDS:
            message = _FIELDS[text[8:]] + "无效。请检查类型、数值范围及单位后重试。"
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.]*) cannot be negative", text)
        if message is None and match:
            message = (
                _FIELDS.get(match.group(1), "指定参数")
                + "不能为负数。请检查数值与单位。"
            )
        match = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_.]*) must be greater than ([\d.]+)", text
        )
        if message is None and match:
            message = (
                _FIELDS.get(match.group(1), "指定参数")
                + f"须大于 {match.group(2)}。请调整对应设置。"
            )
        if message is None and text.startswith("OCR command timed out after "):
            message = "本地 OCR 执行超时。请检查文件是否过大、缩小页码范围或调整 OCR 超时，再创建新的解析版本。"
        match = re.fullmatch(
            r"OCR command failed: (.+) exited with status (-?\d+)", text
        )
        if message is None and match:
            message = f"本地 OCR 程序 {match.group(1)} 执行失败，退出码为 {match.group(2)}。请检查环境诊断及输入 PDF，保留原解析记录后重试。"
    if message is None and re.match(r"^[\u4e00-\u9fff]", text):
        message = text
    if not code and isinstance(value, BaseException):
        code = type(value).__name__
    return {
        "message": message or _UNKNOWN,
        "code": code,
        "raw": raw,
        "known": message is not None,
    }


def user_message(value, *, include_detail=False) -> str:
    """Explain an error in Chinese; opt in to raw text only in expert details."""
    record = error_record(value)
    if include_detail and record["raw"] and record["raw"] != record["message"]:
        return record["message"] + "\n原始诊断：" + record["raw"]
    return record["message"]
