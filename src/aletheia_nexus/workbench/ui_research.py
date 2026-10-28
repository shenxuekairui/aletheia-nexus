"""Source-scoped parsing/search, reviewable research plans and evidence results."""

from __future__ import annotations

import json
import re
from copy import deepcopy

from .labels import CHOICES, GRID_LOCALE, value_label
from .messages import user_message
from .ui_common import guard, json_text, json_view, parameter_editor, rows_table
from .ui_grids import read_edited_grid
from .ui_parameters import parameter_sections
from .ui_presets import preset_controls
from .ui_revisions import render_revision_history, revised_field

FIELD_TYPES = {
    "string": "文本",
    "number": "数字",
    "integer": "整数",
    "boolean": "是或否",
    "string_list": "文本列表",
}


def active_research_task(jobs, task):
    """Find only an identical full contract still awaiting a safe terminal state."""
    from aletheia_nexus.processing.contracts import digest

    from .jobs import TERMINAL

    fingerprint = digest(task)
    for job in jobs:
        if job.get("kind") != "research" or job.get("status") in TERMINAL:
            continue
        parameters = job.get("parameters") or {}
        if parameters.get("task_fingerprint") == fingerprint:
            return job
        existing = parameters.get("task")
        if isinstance(existing, dict) and digest(existing) == fingerprint:
            return job
    return None


def result_version_label(row):
    if row.get("comparison"):
        title = "跨论文比较"
        if row.get("paper_count"):
            title += f" · {row['paper_count']} 篇"
    else:
        title = (row.get("title") or row["objective"])[:65]
    counts = []
    if row.get("records"):
        counts.append(f"{row['records']} 条记录")
    if row.get("claims"):
        counts.append(f"{row['claims']} 项主张")
    return (
        title
        + " · "
        + " / ".join(counts or ["尚无研究条目"])
        + f" · 修订 {row['revisions']} · {row.get('run', '')[-8:]}"
    )


def result_source_names(sources, material_papers, papers):
    """Readable aliases only; immutable source identity remains the audit record."""
    numbers, parent_keys = {}, {}
    for source in sources:
        identity = source["identity"]
        if identity.get("document_role") != "ARTICLE":
            continue
        key = material_papers.get(source["id"]) or source["id"]
        numbers.setdefault(key, len(numbers) + 1)
        parent_keys.setdefault(
            (identity.get("pdf_sha256"), identity.get("article_id")), []
        ).append(key)
    aliases, supplement_counts = {}, {}
    for source in sources:
        identity, sid = source["identity"], source["id"]
        paper_id = material_papers.get(sid)
        paper = papers.get(paper_id) or {}
        preferred = next(
            (
                value.strip()
                for value in (paper.get("custom_name"), paper.get("title_zh"))
                if isinstance(value, str) and value.strip()
            ),
            identity.get("title") or "未命名来源",
        )
        key = paper_id or sid
        if identity.get("document_role") == "ARTICLE":
            reference = f"文献{numbers[key]}"
        else:
            if key not in numbers:
                parent = identity.get("parent") or {}
                matches = (
                    parent_keys.get((parent["pdf_sha256"], parent["article_id"]), [])
                    if parent.get("pdf_sha256") and parent.get("article_id")
                    else []
                )
                key = matches[0] if len(matches) == 1 else None
            if key in numbers:
                supplement_counts[key] = supplement_counts.get(key, 0) + 1
                reference = f"文献{numbers[key]}的SI{supplement_counts[key]}"
            else:
                reference = f"补充材料{len(aliases) + 1}"
        aliases[sid] = {"reference": reference, "title": preferred}
    return aliases


def display_claim_text(text, aliases):
    if not aliases:
        return text
    pattern = (
        r"(?<![A-Za-z0-9_-])(?:"
        + "|".join(re.escape(sid) for sid in sorted(aliases, key=len, reverse=True))
        + r")(?![A-Za-z0-9_-])"
    )
    return re.sub(pattern, lambda match: aliases[match[0]]["reference"], text)


def citation_button_text(citation, sources, *, prefix="核对", aliases=None):
    identity = sources.get(citation.get("source_id"), {})
    original_title = identity.get("title") or "未匹配来源"
    alias = (aliases or {}).get(citation.get("source_id"), {})
    title = " ".join((alias.get("title") or original_title).split())
    short = title if len(title) <= 32 else title[:32] + "…"
    role = " · SI" if identity.get("document_role") == "SUPPLEMENT" else ""
    page = f"物理第{citation['page']}页" if citation.get("page") else "页码待核对"
    reference = alias.get("reference")
    text = f"{prefix} {reference + ' · ' if reference else ''}{short}{role} · {page}"
    tooltip = f"{original_title}\n来源编号：{citation.get('source_id', '')}\n{page}"
    return text, tooltip


def render_parse_summary(diagnostics):
    from nicegui import ui

    coverage = (diagnostics.get("quality") or {}).get("page_coverage") or {}
    parser = diagnostics.get("parser") or {}
    checked = diagnostics.get("source_check") or {}
    with ui.row().classes("an-toolbar w-full"):
        ui.badge(value_label(diagnostics.get("status"))).props("outline")
        ui.label(
            f"页覆盖：{coverage.get('parsed', '—')} / {coverage.get('total', '—')}"
        )
        ui.label(f"解析器版本：{parser.get('version', '—')}")
        ui.label(
            "来源检查："
            + (
                "通过"
                if checked.get("ok")
                else "未通过"
                if checked.get("ok") is False
                else "尚未检查"
            )
        )
    warnings, errors = diagnostics.get("warnings", []), diagnostics.get("errors", [])
    ui.label(
        f"提示 {len(warnings)} 项 · 错误 {len(errors)} 项；处理覆盖不表示科学信息准确率。"
    ).classes("an-muted text-sm")
    for label, items in (("错误", errors), ("提示", warnings)):
        for item in items[:20]:
            page = item.get("page") if isinstance(item, dict) else None
            ui.label(
                f"{label}{' · 物理第' + str(page) + '页' if page else ''}：{user_message(item)}"
            ).classes("an-info w-full")
        if len(items) > 20:
            ui.label(f"另有 {len(items) - 20} 项{label}，完整原始诊断保留在专家区。")


def render_material_requests(
    result, *, open_request=None, new_task=None, open_parent=None
):
    from nicegui import ui

    sources = {d["id"]: d["identity"] for d in result.get("sources", [])}
    issues = result["response"].get("issues", [])
    requests = result["response"].get("requests", [])
    with ui.expansion(
        f"材料不足与诊断（{len(issues)} 项）", icon="info", value=bool(issues)
    ).classes("w-full"):
        for issue in issues:
            source = sources.get(issue.get("source_id"), {})
            ui.label(
                (source.get("title", "") + "：" if source else "")
                + issue.get("detail", "请查看诊断记录")
            ).classes("an-info w-full whitespace-pre-wrap")
    with ui.expansion(
        f"需要补充的研究材料（{len(requests)} 项）",
        icon="post_add",
        value=bool(requests),
    ).classes("w-full"):
        for i, request in enumerate(requests):
            source = sources.get(request.get("source_id"), {})
            with ui.card().classes("an-card w-full"):
                ui.label(source.get("title") or "所选文献的材料请求").classes(
                    "font-semibold"
                )
                pages = request.get("pages") or []
                ui.label(
                    "物理 PDF 页码："
                    + (
                        "、".join(map(str, pages))
                        if pages
                        else "尚未指定，需要人工确认材料"
                    )
                )
                ui.label(request.get("reason", "请核对材料需求")).classes(
                    "whitespace-pre-wrap"
                )
                ui.label(
                    "如缺少 SI，先在所属论文详情显式关联附件，再建立固定新快照；旧结果保留，重新执行需审阅计划并授权。"
                ).classes("an-muted text-sm")
                with ui.row().classes("an-toolbar"):
                    if open_parent:
                        ui.button(
                            "关联 SI / 检查所属论文",
                            on_click=guard(lambda n=i: open_parent(n)),
                        ).props("outline")
                    if open_request and pages:
                        ui.button(
                            "查看请求原页",
                            on_click=guard(lambda r=request: open_request(r)),
                        ).props("flat")
                    if new_task:
                        ui.button(
                            "创建补充材料的新任务",
                            icon="science",
                            on_click=guard(lambda n=i: new_task(n)),
                        )


def page_numbers(value):
    """Parse an explicit, bounded set of physical PDF pages from a small UI field."""
    result = []
    if not value or not str(value).strip():
        return result
    for part in str(value).replace("，", ",").split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(n.strip()) for n in part.split("-", 1))
            if not 1 <= start <= end <= 100000 or end - start > 5000:
                raise ValueError("页码范围无效或过长")
            result.extend(range(start, end + 1))
        else:
            number = int(part)
            if not 1 <= number <= 100000:
                raise ValueError("使用从1开始的物理PDF页码")
            result.append(number)
    return sorted(set(result))


class ResearchPages:
    async def parse_diagnostics_dialog(self, document):
        from nicegui import run, ui

        diagnostics = await run.io_bound(
            self.ctx.research.app.get_parse_diagnostics, document
        )
        with ui.dialog() as dialog, ui.card().classes("w-[950px] max-w-[95vw]"):
            ui.label("解析状态与真实覆盖").classes("text-xl font-semibold")
            render_parse_summary(diagnostics)
            ui.button(
                "查看来源 PDF",
                icon="picture_as_pdf",
                on_click=guard(lambda: self.show_pdf(document)),
            ).props("outline")
            json_view(diagnostics, label="完整解析诊断与配置")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def parse_dialog(self, ids):
        from nicegui import ui

        if not ids:
            raise ValueError("请先选择论文")
        ids = list(dict.fromkeys(ids))
        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[1100px] max-w-[95vw] an-card"),
        ):
            ui.label(f"解析选中文献 · {len(ids)} 篇论文").classes(
                "text-xl font-semibold"
            )
            ui.label(
                "解析创建可追溯版本；已解析、部分解析代表处理覆盖状态，不能代表科学抽取准确率。"
            )
            include_si = ui.checkbox("包括已关联的PDF SI", value=True)
            current = {
                **self.ctx.research.parser_options(),
                **self.ctx.settings.get("parsing", {}),
            }
            read_options = parameter_sections(
                current,
                common=("ocr", "ocr_languages", "max_pages", "new_version"),
                advanced=(
                    "ocr_dpi",
                    "image_ocr",
                    "ocr_timeout_seconds",
                    "ocr_max_raster_pixels",
                    "merge_paragraph_lines",
                    "max_blocks",
                    "max_text_characters",
                ),
                expert=(
                    "column_split_ratio",
                    "heading_font_ratio",
                    "min_text_characters",
                ),
                labels={
                    "ocr": "启用原生优先OCR",
                    "ocr_languages": "OCR语言（例如eng或eng+chi_sim）",
                    "max_pages": "最大页数",
                    "new_version": "强制创建新版本（不覆盖旧版）",
                    "max_blocks": "最大文本块数",
                    "max_text_characters": "最大文本字符数",
                    "ocr_dpi": "OCR DPI（至少300）",
                    "ocr_timeout_seconds": "OCR每步超时（秒）",
                    "ocr_max_raster_pixels": "最大栅格像素",
                    "merge_paragraph_lines": "合并段落行",
                    "image_ocr": "图片OCR引擎",
                },
            )
            preset_controls(
                self.ctx.settings,
                "parsing",
                read_options,
                read_options.apply,
                title="解析参数预设",
            )
            with ui.expansion("已有版本与真实诊断", icon="history").classes("w-full"):
                for paper_id in ids[:20]:
                    for material in self.ctx.research.versions(
                        paper_id, include_si=True
                    ):
                        for version in reversed(material["versions"]):
                            artifact = version["document"]["artifact"]
                            with ui.row().classes("an-toolbar"):
                                ui.label(
                                    f"{material['id']} · {version['created_at']} · "
                                    f"{'当前版本' if material['active_artifact'] == artifact else '历史版本'}"
                                )
                                ui.button(
                                    "使用此解析版本",
                                    on_click=guard(
                                        lambda p=paper_id, a=artifact, m=material["id"]: (
                                            self.ctx.research.select_version(
                                                p, a, material_id=m
                                            ),
                                            ui.notify(
                                                "已切换未来任务的解析版本；历史任务不变。"
                                            ),
                                        )
                                    ),
                                ).props("flat dense")
                                ui.button(
                                    "查看状态 / 页覆盖 / 警告",
                                    on_click=guard(
                                        lambda d=version["document"]: (
                                            self.parse_diagnostics_dialog(d)
                                        )
                                    ),
                                ).props("outline dense")
                            json_view(version, label="解析版本与参数")
                if len(ids) > 20:
                    ui.label("此处仅显示前20篇；所有选中文件仍会处理。")

            def start():
                options = read_options()
                si = include_si.value
                self.submit(
                    "parse",
                    f"解析 {len(ids)} 篇论文及选定附件",
                    ids,
                    lambda c: self.ctx.research.parse(
                        ids, options, context=c, include_si=si
                    ),
                    options,
                )

            ui.button("开始解析", icon="document_scanner", on_click=guard(start))
            ui.button(
                "保存为解析默认",
                on_click=guard(
                    lambda: self.ctx.settings.set("parsing", read_options())
                ),
            ).props("flat")
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()

    def search_page(self):
        from nicegui import ui

        self.title(
            "科研检索",
            "搜索已解析正文与SI的关键词、精确短语和原文证据；不会将字面匹配推断为科学关系。",
        )
        library = self.ctx.library.scan()["items"]
        draft = getattr(self, "search_draft", {})
        handoff = getattr(self, "search_handoff", None) or draft.get("handoff")
        self.search_handoff = None
        handoff_label = f"本次文库勾选（{len(handoff['ids'])} 篇）" if handoff else None
        scopes = ["全部文库", "当前选择清单", *self.ctx.library.collections()]
        if handoff_label:
            scopes.insert(0, handoff_label)
        chosen_scope = handoff_label if handoff else draft.get("scope", "全部文库")
        if chosen_scope not in scopes:
            chosen_scope = "全部文库"
        with ui.card().classes("an-card w-full"):
            with ui.row().classes("an-toolbar w-full"):
                query = (
                    ui.input("关键词 / 带引号短语", value=draft.get("query", ""))
                    .props("outlined")
                    .classes("grow")
                )
                mode = ui.select(
                    {"and": "全部关键词", "or": "任一关键词"},
                    value=draft.get("mode", "and"),
                    label="组合方式",
                ).classes("w-32")
                exact = ui.checkbox(
                    "整个查询作精确短语", value=draft.get("exact", False)
                )
                scope = ui.select(
                    scopes,
                    value=chosen_scope,
                    label="检索范围",
                ).classes("min-w-44")
            with ui.row().classes("an-toolbar w-full"):
                folder = ui.select(
                    ["", *sorted({r["folder"] for r in library if r["folder"]})],
                    value="",
                    label="分类目录",
                ).props("clearable")
                tags = ui.select(
                    sorted({t for r in library for t in r["tags"]}),
                    multiple=True,
                    value=[],
                    label="标签",
                ).props("use-chips")
                role = ui.select(
                    {"all": "正文 + PDF SI", "ARTICLE": "仅正文", "SUPPLEMENT": "仅SI"},
                    value="all",
                    label="来源角色",
                )
                section = ui.select(
                    {
                        v: value_label(v) if v else "全部章节"
                        for v in [
                            "",
                            "abstract",
                            "introduction",
                            "methods",
                            "results",
                            "results-discussion",
                            "discussion",
                            "conclusion",
                            "references",
                        ]
                    },
                    value="",
                    label="章节类型",
                )
                size = ui.number("每页证据条数", value=50, min=1, max=500, step=1)
                with ui.expansion("高级 · 指定检索起点", icon="tune"):
                    offset = ui.number("证据偏移量", value=0, min=0, step=50)
                view = ui.select(
                    ["证据视图", "论文视图"], value="证据视图", label="展示方式"
                )
            status = ui.label(
                "尚未检索。已有CLI解析工件会按身份发现；未解析论文不会自动产生全文命中。"
            ).classes("an-info w-full")
        results_area = ui.column().classes("w-full")
        state = {"table": None, "report": None, "searching": False}

        def selected_ids():
            if handoff_label and scope.value == handoff_label:
                ids = handoff["ids"]
            elif scope.value == "当前选择清单":
                ids = self.ctx.library.selection()
            elif scope.value != "全部文库":
                ids = self.ctx.library.collections()[scope.value]
            else:
                ids = [r["id"] for r in library]
            return [
                r["id"]
                for r in self.ctx.library.scan(
                    ids=ids, folder=folder.value or None, tags=tags.value
                )["items"]
            ]

        def display(report):
            state["report"] = report
            self.search_report = report
            results_area.clear()
            coverage = report["coverage"]
            status.set_text(
                f"返回 {report['returned_hits']} / {report['total_hits']} 条证据（偏移 {report['offset']}）；"
                f"检索 {coverage['searched_documents']} 份PDF；完整解析 {coverage['completed']}、"
                f"部分解析 {coverage['partial']}、未覆盖 {len(coverage['unsearched'])}。未命中不表示未报告。"
            )
            with results_area:
                if view.value == "论文视图":
                    grouped = {}
                    for h in report["hits"]:
                        group = grouped.setdefault(
                            h["paper_id"],
                            {
                                "id": h["paper_id"],
                                "title": self.ctx.library.get(h["paper_id"])["title"],
                                "current_page_hits": 0,
                                "pages": set(),
                            },
                        )
                        group["current_page_hits"] += 1
                        group["pages"].update(h["pages"])
                    rows = [
                        {**v, "pages": ",".join(map(str, sorted(v["pages"])))}
                        for v in grouped.values()
                    ]
                    ui.label(
                        "论文归并仅针对本页证据；全部命中数与覆盖见上方，可翻页继续检查。"
                    )
                else:
                    rows = [
                        {
                            "id": h["id"],
                            "number": h["number"],
                            "title": h["source"].get("title", ""),
                            "role": h["source"].get("document_role", "ARTICLE"),
                            "pages": ",".join(map(str, h["pages"])),
                            "kind": h["kind"],
                            "text": h["text"],
                            "status": h["status"],
                        }
                        for h in report["hits"]
                    ]
                labels = {
                    "number": "序号",
                    "title": "论文",
                    "role": "正文 / SI",
                    "pages": "物理页码",
                    "kind": "原文类型",
                    "text": "命中原文",
                    "status": "解析状态",
                    "current_page_hits": "本页命中数",
                }
                keys = [
                    key
                    for key in (
                        "title",
                        "role",
                        "pages",
                        "text",
                        "kind",
                        "status",
                        "current_page_hits",
                    )
                    if rows and key in rows[0]
                ]
                columns = [
                    {
                        "name": key,
                        "label": labels[key],
                        "field": key,
                        "align": "left",
                        "sortable": key != "text",
                        "style": "white-space:pre-wrap;min-width:360px;max-width:660px"
                        if key == "text"
                        else "white-space:normal;min-width:160px;max-width:300px"
                        if key == "title"
                        else "",
                    }
                    for key in keys
                ]
                state["table"] = rows_table(rows, columns=columns, selection="multiple")
                with ui.row().classes("an-toolbar"):
                    ui.button(
                        "选择命中论文",
                        icon="playlist_add",
                        on_click=guard(add_selected),
                    )
                    ui.button(
                        "仅用选中论文开始研究",
                        icon="science",
                        on_click=guard(start_research),
                    ).props("outline")
                    ui.button(
                        "查看选中原文", icon="picture_as_pdf", on_click=guard(show_hit)
                    ).props("outline")
                    ui.button(
                        "导出选中原文证据",
                        icon="file_download",
                        on_click=guard(export_evidence),
                    ).props("outline")
                    ui.button("上一页", on_click=guard(lambda: turn_page(-1))).props(
                        "flat"
                    )
                    ui.button("下一页", on_click=guard(lambda: turn_page(1))).props(
                        "flat"
                    )
                json_view(
                    {
                        "coverage": report["coverage"],
                        "search_scope": report["search_scope"],
                        "interpretation": report["interpretation"],
                    },
                    label="检索覆盖、排除范围与限制",
                )

        def selected_hits():
            if state["table"] is None or not state["table"].selected:
                raise ValueError("请勾选证据或论文")
            wanted = {r["id"] for r in state["table"].selected}
            return [
                h
                for h in state["report"]["hits"]
                if (h["paper_id"] if view.value == "论文视图" else h["id"]) in wanted
            ]

        def add_selected():
            ids = list(dict.fromkeys(h["paper_id"] for h in selected_hits()))
            self.ctx.library.set_selection(ids, mode="add")
            ui.notify(f"已添加 {len(ids)} 篇论文，SI范围在AI执行前另行确认。")

        def start_research():
            ids = list(dict.fromkeys(h["paper_id"] for h in selected_hits()))
            self.ctx.library.set_selection(ids, mode="replace")
            self.current_task = None
            self.navigate("AI 研究")

        def show_hit():
            hit = selected_hits()[0]
            with ui.dialog() as dialog, ui.card().classes("w-[1200px] max-w-[96vw]"):
                ui.label(hit["text"]).classes("whitespace-pre-wrap an-info")
                self.show_pdf(
                    hit["document"],
                    page=hit["pages"][0],
                    container=ui.column().classes("w-full"),
                )
                json_view(hit, label="来源块、表格/图注上下文与定位")
                ui.button("关闭", on_click=dialog.close).props("flat")
            dialog.open()

        def export_evidence():
            result = self.ctx.research.export_evidence(selected_hits())
            with results_area:
                self.output_links(result)
            ui.notify("证据包已保存，保留原文与来源。", type="positive")

        async def search():
            from nicegui import run

            if state["searching"]:
                return

            def form():
                return (
                    query.value,
                    mode.value,
                    exact.value,
                    scope.value,
                    folder.value,
                    tuple(tags.value or []),
                    role.value,
                    section.value,
                    size.value,
                    offset.value,
                )

            captured = form()
            ids = selected_ids()
            state["searching"] = True
            search_button.disable()
            searching.set_visibility(True)
            try:
                self.search_draft = {
                    "query": query.value,
                    "mode": mode.value,
                    "exact": exact.value,
                    "scope": scope.value,
                    "handoff": handoff,
                }
                status.set_text(
                    f"正在核对 {len(ids)} 篇论文及选定 PDF SI，并检索关键词；首次全库检索需要更多时间…"
                )
                report = await run.io_bound(
                    self.ctx.research.search,
                    query.value,
                    ids,
                    include_si=True,
                    mode=mode.value,
                    exact=exact.value,
                    role=None if role.value == "all" else role.value,
                    section_type=section.value or None,
                    limit=int(size.value),
                    offset=int(offset.value),
                )
                if results_area.is_deleted:
                    return
                self.ctx.library  # Reject results from a library switched during the query.
                if form() != captured or selected_ids() != ids:
                    status.set_text(
                        "检索期间条件或材料选择已修改。请按当前条件重新检索，本次结果未替换当前预览。"
                    )
                    return
                display(report)
            finally:
                state["searching"] = False
                if not search_button.is_deleted:
                    search_button.enable()
                    searching.set_visibility(False)

        async def turn_page(direction):
            if state["searching"]:
                return
            offset.set_value(max(0, offset.value + direction * size.value))
            await search()

        with ui.row().classes("an-toolbar"):
            search_button = ui.button(
                "检索本地原文", icon="search", on_click=guard(search)
            )
            searching = ui.spinner(size="sm")
            searching.set_visibility(False)
            ui.button(
                "解析当前范围",
                icon="document_scanner",
                on_click=guard(lambda: self.parse_dialog(selected_ids())),
            ).props("outline")
        query.on("keydown.enter", guard(search))

    def research_page(self):
        from nicegui import ui

        from aletheia_nexus.research_planner import DEFAULT_MODEL

        self.title(
            "AI 研究",
            "从当前选择清单创建有范围、字段和预算的科研任务；先审计划，再授权执行。",
        )
        ids = self.ctx.library.selection()
        if not ids and not self.current_task:
            with ui.card().classes("an-card w-full gap-3"):
                ui.label("先选择研究材料").classes("text-xl font-semibold")
                ui.label(
                    "在文献库勾选论文并加入选择清单，或检索后直接使用选中论文。选好后再填写研究目标；默认不会调用模型。"
                )
                with ui.row().classes("an-toolbar"):
                    ui.button(
                        "到文献库选论文",
                        icon="local_library",
                        on_click=lambda: self.navigate("文献库"),
                    )
                    ui.button(
                        "先检索原文",
                        icon="search",
                        on_click=lambda: self.navigate("科研检索"),
                    ).props("outline")
            return
        ui.label(f"当前选择 {len(ids)} 篇论文").classes("an-info w-full")
        with ui.row().classes("an-toolbar"):
            ui.button(
                "检查选择清单", icon="checklist", on_click=guard(self.selection_dialog)
            ).props("outline")
            ui.button(
                "解析所选论文",
                icon="document_scanner",
                on_click=guard(lambda: self.parse_dialog(ids)),
            ).props("outline")
        goal = (
            ui.textarea(
                "科研目标（自然语言）",
                value=(self.current_task or {}).get("objective", ""),
            )
            .props(
                'outlined rows=3 placeholder="例如：提取底物、催化剂、电位、产物、法拉第效率及支持机理的原文证据"'
            )
            .classes("w-full")
        )
        with ui.row().classes("an-toolbar"):
            include_si = ui.checkbox("材料包括已关联PDF SI", value=False)
            mode = ui.select(
                {
                    "local": "本地准备（零AI调用）",
                    "parsed": "解析文本",
                    "hybrid": "文本 + 指定原页图像",
                    "direct": "仅指定原页图像",
                },
                value=(self.current_task or {}).get("mode", "local"),
                label="处理材料",
            )
            task_type = ui.select(
                CHOICES["type"],
                value=(self.current_task or {}).get("type", "extract"),
                label="任务类型",
            )
            include_steps = ui.checkbox(
                "包括实验步骤",
                value=(self.current_task or {}).get("include_steps", False),
            )
            compare = ui.checkbox(
                "跨论文比较", value=(self.current_task or {}).get("synthesize", False)
            )
        with ui.expansion("模型、调用及费用预算", icon="tune", value=True).classes(
            "an-card w-full"
        ):
            model_options = {
                **DEFAULT_MODEL,
                "min_interval_seconds": 1,
                **(self.current_task or {}).get("model", {}),
            }
            read_model = parameter_sections(
                model_options,
                common=("name", "reasoning_effort", "currency"),
                advanced=tuple(
                    k
                    for k in model_options
                    if k not in {"name", "reasoning_effort", "currency"}
                ),
            )
            read_budget = parameter_sections(
                {
                    "max_calls": 10,
                    "max_cost": 2.0,
                    "max_input_characters": 100000,
                    "max_images": 6,
                    "max_output_tokens": 65536,
                    "max_repair_rounds": 1,
                    "max_supplement_rounds": 0,
                    "max_review_rounds": 0,
                    **(self.current_task or {}).get("budget", {}),
                },
                common=("max_calls", "max_cost", "max_images", "max_output_tokens"),
                advanced=(
                    "max_input_characters",
                    "max_repair_rounds",
                    "max_supplement_rounds",
                    "max_review_rounds",
                ),
            )
            planning_cost = ui.number(
                "自然语言规划单独费用上限（按模型计费币种）", value=0.5, min=0.01
            )
            ui.label(
                "规划与科研执行分别计费：规划每次按最多 16384 输出 Token 预留，"
                "最多 2 次请求（含草案纠错/失败重试）；单次预留超过上限时不会发送请求。"
            ).classes("an-muted text-sm")
            planning_consent = ui.checkbox(
                "我授权仅将科研目标和选中文献元数据发送给DeepSeek生成计划（单独计费）",
                value=False,
            )
            extra_pages_consent = ui.checkbox(
                "本次授权模型在已选文献内按材料请求补充其它页（仍受补充轮数、图片和费用上限限制）",
                value=False,
            )
            ui.label(
                "未勾选时补充轮数必须为0；历史任务和预设不会继承本次额外页授权。"
            ).classes("an-muted text-sm")

            with ui.expansion("研究规则与取材范围", icon="rule").classes("w-full"):
                read_material_options = parameter_editor(
                    {
                        "rules": (self.current_task or {}).get("rules", []),
                        "query": (self.current_task or {}).get("query", ""),
                        "context_pages": (self.current_task or {}).get(
                            "context_pages", 1
                        ),
                    }
                )
                ui.label(
                    "规则逐行填写；取材关键词用于原文筛选，上下文页数为0–10。明确选页优先，命中不代表科学关系成立。"
                ).classes("an-muted text-sm")

            def read_preset():
                return {
                    "model": read_model(),
                    "budget": read_budget(),
                    "mode": mode.value,
                    "type": task_type.value,
                    "include_steps": include_steps.value,
                    "synthesize": compare.value,
                    **read_material_options(),
                }

            def apply_preset(parameters):
                allowed = {
                    "model",
                    "budget",
                    "mode",
                    "type",
                    "include_steps",
                    "synthesize",
                    "rules",
                    "query",
                    "context_pages",
                }
                if not isinstance(parameters, dict) or set(parameters) - allowed:
                    raise ValueError(
                        "科研预设只接受模型、预算、取材、规则、材料模式、任务类型、步骤和比较参数"
                    )
                pending = []
                for key, read in (("model", read_model), ("budget", read_budget)):
                    if key in parameters:
                        pending.extend(read._pending_updates(parameters[key]))
                pending.extend(
                    read_material_options._pending_updates(
                        {
                            k: parameters[k]
                            for k in ("rules", "query", "context_pages")
                            if k in parameters
                        }
                    )
                )
                if "mode" in parameters and parameters["mode"] not in CHOICES["mode"]:
                    raise ValueError("科研预设中的材料模式不受支持")
                if "type" in parameters and parameters["type"] not in CHOICES["type"]:
                    raise ValueError("科研预设中的任务类型不受支持")
                for key in ("include_steps", "synthesize"):
                    if key in parameters and type(parameters[key]) is not bool:
                        raise ValueError("科研预设的步骤与比较选项必须为是或否")
                for element, value in pending:
                    element.set_value(value)
                for key, element in (
                    ("mode", mode),
                    ("type", task_type),
                    ("include_steps", include_steps),
                    ("synthesize", compare),
                ):
                    if key in parameters:
                        element.set_value(parameters[key])
                planning_consent.set_value(False)
                extra_pages_consent.set_value(False)
                if state.get("content_consent") is not None:
                    state["content_consent"].set_value(False)

            preset_controls(
                self.ctx.settings,
                "research",
                read_preset,
                apply_preset,
                title="科研模型与预算预设",
            )
        plan_area = ui.column().classes("w-full")
        state = {
            "fields": None,
            "documents": None,
            "expert": None,
            "use_expert": None,
            "plan_job": None,
            "loaded": False,
            "content_consent": None,
            "executing": False,
        }

        def render_plan(task):
            self.current_task = task
            goal.set_value(task["objective"])
            mode.set_value(task["mode"])
            task_type.set_value(task["type"])
            include_steps.set_value(bool(task.get("include_steps")))
            compare.set_value(bool(task.get("synthesize")))
            read_model.apply(task.get("model", {}))
            read_budget.apply(task.get("budget", {}))
            read_material_options.apply(
                {
                    "rules": task.get("rules", []),
                    "query": task.get("query", ""),
                    "context_pages": task.get("context_pages", 1),
                }
            )
            planning_consent.set_value(False)
            extra_pages_consent.set_value(False)
            plan_area.clear()
            with plan_area:
                ui.label("可编辑研究计划").classes("font-semibold text-xl")
                ui.label(
                    "文献和解析版本已固定为来源快照；标签、集合与后续解析变化不会改变这个任务。"
                )
                field_rows = [
                    {
                        "id": f["id"],
                        "label": f.get("label", ""),
                        "type": FIELD_TYPES[f["type"]],
                        "description": f["description"],
                        "unit": f.get("unit") or "",
                        "scope": f.get("scope", ""),
                    }
                    for f in task["fields"]
                ]
                state["fields"] = ui.aggrid(
                    {
                        "localeText": GRID_LOCALE,
                        "stopEditingWhenCellsLoseFocus": True,
                        "columnDefs": [
                            {
                                "field": key,
                                "editable": True,
                                "headerName": label,
                                "width": width,
                                "hide": key == "id",
                                **(
                                    {
                                        "cellEditor": "agSelectCellEditor",
                                        "cellEditorParams": {
                                            "values": list(FIELD_TYPES.values())
                                        },
                                    }
                                    if key == "type"
                                    else {}
                                ),
                            }
                            for key, label, width in (
                                ("id", "字段编号", 150),
                                ("label", "字段名", 180),
                                ("type", "类型", 150),
                                ("description", "对象、阶段、条件与字段要求", 450),
                                ("unit", "单位", 120),
                                ("scope", "范围", 180),
                            )
                        ],
                        "rowData": field_rows,
                        "rowSelection": "multiple",
                        "defaultColDef": {"resizable": True},
                    },
                    theme="quartz",
                ).classes("h-56 w-full")

                async def add_field():
                    from uuid import uuid4

                    rows = await read_edited_grid(state["fields"])
                    rows.append(
                        {
                            "id": "field_" + uuid4().hex[:10],
                            "label": "新字段",
                            "type": "文本",
                            "description": "请明确提取对象、阶段与条件",
                            "unit": "",
                            "scope": "",
                        }
                    )
                    state["fields"].options["rowData"] = rows
                    state["fields"].update()

                async def remove_fields():
                    rows = await read_edited_grid(state["fields"])
                    selected = await state["fields"].get_selected_rows()
                    keys = {r["id"] for r in selected}
                    state["fields"].options["rowData"] = [
                        r for r in rows if r["id"] not in keys
                    ]
                    state["fields"].update()

                with ui.row().classes("an-toolbar"):
                    ui.button("添加字段", icon="add", on_click=guard(add_field)).props(
                        "flat"
                    )
                    ui.button(
                        "移除选中字段", icon="remove", on_click=guard(remove_fields)
                    ).props("flat")
                document_rows = []
                article_count = 0
                for doc in task["documents"]:
                    source = self.ctx.research.app.check_document(doc, "direct")
                    article_count += source.identity["document_role"] == "ARTICLE"
                    document_rows.append(
                        {
                            "id": doc["id"],
                            "enabled": True,
                            "title": source.identity["title"],
                            "role": value_label(source.identity["document_role"]),
                            "page_count": source.identity["page_count"],
                            "identity": value_label(source.identity["identity_basis"]),
                            "pages": ",".join(map(str, doc.get("pages", []))),
                            "image_pages": ",".join(
                                map(str, doc.get("image_pages", []))
                            ),
                            "artifact": doc.get("artifact", ""),
                            "image_layout": "整页与分块"
                            if doc.get("image_layout") == "page_and_tiles"
                            else "整页",
                        }
                    )
                ui.label(
                    f"本计划固定材料：{article_count} 篇正文、"
                    f"{len(document_rows) - article_count} 份附件。"
                    "此范围独立于当前选择清单；“发送”列决定本次启用材料，执行前预览会再次核对。"
                ).classes("an-info w-full")
                state["documents"] = ui.aggrid(
                    {
                        "localeText": GRID_LOCALE,
                        "stopEditingWhenCellsLoseFocus": True,
                        "columnDefs": [
                            {
                                "field": "enabled",
                                "headerName": "发送",
                                "editable": True,
                                "width": 90,
                            },
                            {"field": "title", "headerName": "实际来源", "width": 350},
                            *(
                                {
                                    "field": key,
                                    "headerName": label,
                                    "editable": key
                                    in {"pages", "image_pages", "image_layout"},
                                    **(
                                        {
                                            "cellEditor": "agSelectCellEditor",
                                            "cellEditorParams": {
                                                "values": ["整页", "整页与分块"]
                                            },
                                        }
                                        if key == "image_layout"
                                        else {}
                                    ),
                                    "width": 180,
                                }
                                for key, label in (
                                    ("role", "主文/SI"),
                                    ("page_count", "物理页数"),
                                    ("identity", "身份依据"),
                                    ("pages", "文本页码（留空全部）"),
                                    ("image_pages", "图像页码（留空不发图）"),
                                    ("image_layout", "图像处理（高级）"),
                                    ("artifact", "固定解析版本"),
                                )
                            ),
                        ],
                        "rowData": document_rows,
                        "defaultColDef": {"resizable": True},
                    },
                    theme="quartz",
                ).classes("h-56 w-full")
                ui.label(
                    "页码支持 1,3,5-8；SI页码独立。仅图像模式必须明确给出页码。默认限于已选页；允许补充其它页须重新勾选上方授权。"
                ).classes("an-info w-full")
                with ui.expansion(
                    "专家 · 实际研究任务契约", icon="data_object"
                ).classes("w-full"):
                    state["use_expert"] = ui.checkbox(
                        "使用下方专家契约代替上方表单", value=False
                    )
                    state["expert"] = (
                        ui.textarea("research-task/v1", value=json_text(task))
                        .props("autogrow")
                        .classes("w-full font-mono")
                    )
                consent = ui.checkbox(
                    "我已核对实际材料和预算，授权将本计划选中的文献内容发送到配置的远程模型（可能收费）",
                    value=False,
                )
                state["content_consent"] = consent
                check_area = ui.column().classes("w-full")

                async def collect():
                    if state["use_expert"].value:
                        return json.loads(state["expert"].value)
                    value = deepcopy(self.current_task)
                    value.update(
                        objective=goal.value,
                        type=task_type.value,
                        mode=mode.value,
                        allow_remote=mode.value != "local",
                        include_steps=include_steps.value,
                        synthesize=compare.value,
                        model=read_model(),
                        budget=read_budget(),
                        rules=read_material_options()["rules"],
                        context_pages=read_material_options()["context_pages"],
                    )
                    query_value = read_material_options()["query"].strip()
                    if query_value:
                        value["query"] = query_value
                    else:
                        value.pop("query", None)
                    reverse_types = {v: k for k, v in FIELD_TYPES.items()}
                    value["fields"] = [
                        {
                            **r,
                            "type": reverse_types.get(r["type"], r["type"]),
                            "unit": r.get("unit") or None,
                        }
                        for r in await read_edited_grid(state["fields"])
                    ]
                    by_id = {d["id"]: d for d in value["documents"]}
                    docs = []
                    for row in await read_edited_grid(state["documents"]):
                        if not row.get("enabled"):
                            continue
                        doc = deepcopy(by_id[row["id"]])
                        layout = {"整页": "page", "整页与分块": "page_and_tiles"}[
                            row["image_layout"]
                        ]
                        if layout != "page" or "image_layout" in doc:
                            doc["image_layout"] = layout
                        for key in ("pages", "image_pages"):
                            selected = page_numbers(row[key])
                            if selected:
                                doc[key] = selected
                            else:
                                doc.pop(key, None)
                        docs.append(doc)
                    value["documents"] = docs
                    return value

                async def validate():
                    value = await collect()
                    if (
                        value.get("mode", "local") != "local"
                        and value.get("budget", {}).get("max_supplement_rounds", 1) > 0
                        and not extra_pages_consent.value
                    ):
                        raise ValueError(
                            "补充轮数大于0会允许同文献其它页外发；请明确授权，或将补充轮数设为0"
                        )
                    checked = self.ctx.research.validate_plan(value)
                    check_area.clear()
                    with check_area:
                        ui.label(checked["plan"]).classes(
                            "whitespace-pre-wrap an-info w-full"
                        )
                        json_view(checked, label="实际指纹与来源身份快照")
                    return checked["task"]

                async def execute():
                    if state["executing"]:
                        ui.notify("正在核对并提交本计划，请等待；无需重复点击。")
                        return
                    state["executing"] = True
                    execute_button.disable()
                    try:
                        task_value = await validate()
                        grant = consent.value
                        extra_grant = extra_pages_consent.value
                        if task_value["mode"] != "local" and not grant:
                            raise ValueError("请明确授权本计划的文献材料外发和费用")
                        existing = active_research_task(
                            self.ctx.jobs.list(), task_value
                        )
                        if existing is not None:
                            ui.notify(
                                "相同材料、页码及预算的计划已在任务中心排队或执行，未重复提交。"
                                f"任务：{existing.get('id', existing.get('job_id', ''))}",
                                type="warning",
                            )
                            return
                        self.current_task = task_value
                        from aletheia_nexus.processing.contracts import digest

                        self.submit(
                            "research",
                            task_value["objective"][:80],
                            [d["id"] for d in task_value["documents"]],
                            lambda c: self.ctx.research.execute(
                                task_value,
                                consent=grant,
                                allow_extra_pages=extra_grant,
                                context=c,
                            ),
                            {
                                "task": task_value,
                                "task_fingerprint": digest(task_value),
                                "extra_pages_authorized": extra_grant,
                            },
                        )
                    finally:
                        state["executing"] = False
                        if not execute_button.is_deleted:
                            execute_button.enable()

                with ui.row().classes("an-toolbar"):
                    ui.button(
                        "验证并预览实际计划",
                        icon="fact_check",
                        on_click=guard(validate),
                    )
                    execute_button = ui.button(
                        "执行已核对计划", icon="play_arrow", on_click=guard(execute)
                    )
                    ui.button(
                        "查看任务中心",
                        icon="pending_actions",
                        on_click=guard(self.task_dialog),
                    ).props("outline")

        def local_plan():
            # This creates a contract from the goal, not an AI interpretation.
            goal_value, si, model, budget, kind = (
                goal.value,
                include_si.value,
                read_model(),
                read_budget(),
                task_type.value,
            )
            steps, synthesis = include_steps.value, compare.value
            requested_mode = mode.value
            material_options = read_material_options()
            parse_options = {
                **self.ctx.research.parser_options(),
                **self.ctx.settings.get("parsing", {}),
            }
            if not goal_value.strip() or not ids:
                raise ValueError("请先选择论文并输入科研目标")

            def worker(context):
                task = self.ctx.research.local_plan(
                    goal_value,
                    ids,
                    include_si=si,
                    model=model,
                    budget=budget,
                    mode="local",
                    task_type=kind,
                    parse_options=parse_options,
                    context=context,
                )
                task["include_steps"] = steps
                task["synthesize"] = synthesis
                return {
                    **self.ctx.research.configure_plan(task, material_options),
                    "requested_mode": requested_mode,
                }

            receipt = self.submit(
                "research",
                "本地准备研究计划（零模型调用）",
                ids,
                worker,
                {
                    "goal": goal_value,
                    "include_si": si,
                    "model": model,
                    "budget": budget,
                    "material_options": material_options,
                    "parse_options": parse_options,
                },
            )
            state.update(
                plan_job=receipt.get("job_id", receipt.get("id")), loaded=False
            )

        def remote_plan():
            if not planning_consent.value:
                raise ValueError("请先授权仅元数据的规划请求")
            options = read_budget()
            goal_value, si, model = goal.value, include_si.value, read_model()
            cost = planning_cost.value
            material_options = read_material_options()
            parse_options = {
                **self.ctx.research.parser_options(),
                **self.ctx.settings.get("parsing", {}),
            }

            def worker(context):
                planned = self.ctx.research.plan(
                    goal_value,
                    ids,
                    include_si=si,
                    consent=True,
                    model=model,
                    max_cost=options["max_cost"],
                    max_calls=options["max_calls"],
                    planning_max_cost=cost,
                    budget=options,
                    parse_options=parse_options,
                    context=context,
                )
                return self.ctx.research.configure_plan(
                    planned["task"], material_options, previous=planned
                )

            receipt = self.submit(
                "research",
                "自然语言科研规划（仅元数据）",
                ids,
                worker,
                {
                    "goal": goal_value,
                    "planning_max_cost": cost,
                    "model": model,
                    "parse_options": parse_options,
                },
            )
            state.update(
                plan_job=receipt.get("job_id", receipt.get("id")), loaded=False
            )

        def load_plan():
            if not state["plan_job"] or state["loaded"]:
                return
            job = self.ctx.jobs.get(state["plan_job"])
            if isinstance(job.get("result"), dict) and job["result"].get("task"):
                state["loaded"] = True
                render_plan(job["result"]["task"])
                if job["result"].get("requested_mode"):
                    mode.set_value(job["result"]["requested_mode"])
            elif job["status"] in {"FAILED", "INTERRUPTED", "CANCELLED"}:
                state["loaded"] = True
                ui.notify(
                    f"规划任务{value_label(job['status'])}，请在任务中心查看原因。",
                    type="warning",
                )

        with ui.row().classes("an-toolbar"):
            ui.button(
                "本地创建可编辑计划（零模型调用）",
                icon="edit_note",
                on_click=guard(local_plan),
            )
            ui.button(
                "授权自然语言规划", icon="auto_awesome", on_click=guard(remote_plan)
            ).props("outline")
        ui.timer(2, guard(load_plan))
        if self.current_task:
            render_plan(self.current_task)

    def results_page(self):
        from nicegui import ui

        self.title(
            "研究成果",
            "左侧研究结果，右侧原始PDF；引用可定位不代表科学支持已核实，人工修订保留原版本。",
        )
        rows = self.ctx.research.results()
        if not rows:
            ui.label(
                "尚无模型科研结果；本地准备任务的材料包、报告与状态可在任务中心查看。"
            )
            return
        options = {r["path"]: result_version_label(r) for r in rows}
        current = (
            self.current_result if self.current_result in options else rows[0]["path"]
        )
        selected = ui.select(options, value=current, label="结果版本").classes("w-full")
        selected.on_value_change(
            lambda e: (
                setattr(self, "current_result", e.value),
                self.page_content.refresh(),
            )
        )
        result = self.ctx.research.read_result(current)
        citation_sources = {s["id"]: s["identity"] for s in result["sources"]}
        self.current_result = current
        material_papers = self.ctx.research.result_material_papers(current)
        current_papers = {
            paper_id: self.ctx.library.get(paper_id)
            for paper_id in set(material_papers.values())
            if paper_id
        }
        aliases = result_source_names(
            result["sources"], material_papers, current_papers
        )

        def open_material_parent(index):
            request = result["response"]["requests"][index]
            paper_id = material_papers.get(request["source_id"])
            if paper_id is None:
                raise ValueError(
                    "请求所属论文不在当前文库，请先导入保留来源的正文，再显式关联 SI"
                )
            self.details_dialog(paper_id)

        async def new_material_task(index):
            import asyncio

            from .jobs import TERMINAL

            receipt = self.submit(
                "research",
                "准备补充材料的新研究计划",
                [],
                lambda c: self.ctx.research.supplement_task(current, index, context=c),
                {"parent_result": current, "material_request_index": index},
            )
            job_id = receipt.get("id", receipt.get("job_id"))
            while receipt["status"] not in TERMINAL:
                await asyncio.sleep(0.3)
                receipt = self.ctx.jobs.get(job_id)
            prepared = receipt.get("result") or {}
            if not prepared.get("task"):
                raise ValueError(
                    "补充材料计划未完成，请在任务中心查看原因；旧结果保持不变"
                )
            self.current_task = prepared["task"]
            self.navigate("AI 研究")
            ui.notify(
                "新快照已准备，尚未调用模型。请核对新增 SI、选页与预算后重新授权。",
                type="positive",
            )

        with ui.splitter(value=52).classes("w-full") as splitter:
            with splitter.before:
                with ui.column().classes("w-full pr-3"):
                    ui.label(result["task"]["objective"]).classes(
                        "text-lg font-semibold"
                    )
                    ui.label(
                        "科学判断、引用定位与人工确认分别记录；发现错误可保存独立修订版本。"
                    ).classes("an-info w-full")
                    flattened = []
                    field_labels = {
                        f["id"]: f.get("label") or f["id"]
                        for f in result["task"]["fields"]
                    }
                    for record in result["response"].get("records", []):
                        for key, value in record["fields"].items():
                            flattened.append(
                                {
                                    "id": record["id"] + ":" + key,
                                    "record": record["id"],
                                    "subject": record.get("subject", ""),
                                    "stage": value_label(record.get("stage", "")),
                                    "field": field_labels[key],
                                    "_field": key,
                                    "value": (
                                        "未报告 / 待核对"
                                        if value.get("value") is None
                                        else "；".join(map(str, value["value"]))
                                        if isinstance(value["value"], list)
                                        else str(value["value"])
                                    ),
                                    "unit": value.get("unit") or "",
                                    "status": value.get("status", ""),
                                    "confirmation": value_label(
                                        result["validation"]
                                        .get("record_states", {})
                                        .get(record["id"], "")
                                    ),
                                    "context": value.get("context", ""),
                                }
                            )
                    result_labels = {
                        "subject": "研究对象",
                        "stage": "阶段",
                        "field": "字段",
                        "value": "结果",
                        "unit": "单位",
                        "status": "报告状态",
                        "confirmation": "核对状态",
                        "context": "适用条件",
                    }
                    table = None
                    if flattened:
                        table = rows_table(
                            flattened,
                            columns=[
                                {
                                    "name": key,
                                    "label": label,
                                    "field": key,
                                    "align": "left",
                                    "sortable": True,
                                    "style": "white-space:pre-wrap;min-width:140px;max-width:320px",
                                }
                                for key, label in result_labels.items()
                            ],
                            selection="single",
                        )
                    elif result["response"].get("claims"):
                        ui.label(
                            "本结果以研究主张交付，请逐条核对下方引用；没有结构化记录不表示研究主张已通过科学核验。"
                        ).classes("an-info w-full")
                    else:
                        ui.label(
                            "本结果没有可展示的研究数据或主张。请查看诊断与材料请求，核对实际处理范围。"
                        ).classes("an-info w-full")
                    with ui.row().classes("an-toolbar"):
                        if table is not None:
                            ui.button(
                                "核对选中数据的证据",
                                icon="picture_as_pdf",
                                on_click=guard(lambda: show_selected()),
                            )
                        ui.button(
                            "修订 / 人工确认",
                            icon="edit",
                            on_click=guard(
                                lambda: self.revision_dialog(current, result)
                            ),
                        ).props("outline")
                    for record in result["response"].get("records", []):
                        if record.get("steps"):
                            with ui.expansion(
                                f"实验步骤 · {record['id']}",
                                icon="format_list_numbered",
                            ).classes("w-full"):
                                rows_table(record["steps"], row_key="id")
                    if result["response"].get("claims"):
                        with ui.expansion(
                            "文献对照（阅读名称）", icon="menu_book", value=True
                        ).classes("w-full"):
                            for alias in aliases.values():
                                name = alias["title"]
                                short = name if len(name) <= 40 else name[:40] + "…"
                                ui.label(f"{alias['reference']}《{short}》")
                            ui.label(
                                "当前显示名称仅便于阅读；模型原始文本与来源编号保留在下方专家区。"
                            ).classes("an-muted text-sm")
                    for index, claim in enumerate(result["response"].get("claims", [])):
                        with ui.card().classes("an-card w-full"):
                            ui.label(
                                f"主张 {index + 1} · {value_label(claim.get('nature', ''))}"
                            ).classes("text-xs an-muted")
                            ui.label(display_claim_text(claim["text"], aliases))
                            for citation in claim.get("citations", []):
                                label, tooltip = citation_button_text(
                                    citation, citation_sources, aliases=aliases
                                )
                                ui.button(
                                    label,
                                    on_click=guard(lambda c=citation: show_citation(c)),
                                ).props("flat dense").tooltip(tooltip)
                    render_material_requests(
                        result,
                        open_request=lambda r: show_citation(
                            {
                                "source_id": r["source_id"],
                                "page": r["pages"][0],
                                "quote": "",
                            }
                        ),
                        new_task=new_material_task,
                        open_parent=open_material_parent,
                    )
                    json_view(
                        result["response"].get("issues", []), label="诊断信息与材料不足"
                    )
                    json_view(
                        result["response"].get("requests", []),
                        label="补充材料请求 / 缺失SI",
                    )
                    json_view(result["response"], label="模型结构化结果原始值")
                    render_revision_history(result)
                    json_view(
                        result["history"], label="修订历史（AI / 人工 / 人工确认）"
                    )
                    json_view(
                        {
                            "task": result["task"],
                            "sources": result["sources"],
                            "validation": result["validation"],
                            "provider": result["provider"],
                        },
                        label="任务参数、来源与审计",
                    )
                    export_area = ui.column().classes("w-full")
                    formats = ui.select(
                        {
                            "markdown": "可读研究报告（Markdown）",
                            "csv": "结构化数据表（CSV）",
                            "jsonl": "逐行原生数据（JSONL）",
                        },
                        value=["markdown", "csv", "jsonl"],
                        multiple=True,
                        label="导出格式",
                    ).props("use-chips")

                    def export():
                        report = self.ctx.research.export(
                            [current], formats=formats.value
                        )
                        export_area.clear()
                        with export_area:
                            self.output_links(report)
                            for warning in report.get("warnings", []):
                                ui.label(warning).classes("an-info w-full")
                            ui.label(
                                "原生结果包包含完整任务、材料包、历史、图像和校验清单；原PDF按原始来源定位与哈希另行备份。"
                            ).classes("an-muted text-sm")

                    ui.button(
                        "导出此版本", icon="download", on_click=guard(export)
                    ).props("outline")

                    def reuse():
                        task = deepcopy(result["task"])
                        from uuid import uuid4

                        task["id"] = "ui_" + uuid4().hex[:12]
                        self.current_task = task
                        self.navigate("AI 研究")

                    ui.button(
                        "基于此范围创建新任务", icon="science", on_click=guard(reuse)
                    ).props("flat")
            with splitter.after:
                pdf_area = ui.column().classes("w-full pl-3")
                with pdf_area:
                    ui.icon("picture_as_pdf", size="4rem").classes(
                        "an-muted self-center mt-20"
                    )
                    ui.label("点击左侧数据的证据，定位原文物理页码。")

        def show_citation(citation):
            document = self.ctx.research.citation_document(
                current, citation["source_id"]
            )
            self.show_pdf(document, page=citation["page"], container=pdf_area)
            with pdf_area:
                ui.label(
                    citation.get("quote") or "引用未保存摘录，请核对整页。"
                ).classes("an-info w-full whitespace-pre-wrap")
                if document.get("artifact"):
                    report = self.ctx.research.app.read_document_context(
                        document, pages=[citation["page"]], context_pages=1
                    )
                    json_view(report, label="原文前后页、来源块与布局上下文")

        def show_selected():
            if table is None or not table.selected:
                raise ValueError("请先选择一条研究数据")
            chosen = table.selected[0]
            record = next(
                r for r in result["response"]["records"] if r["id"] == chosen["record"]
            )
            citations = record["fields"][chosen["_field"]].get("citations", [])
            if not citations:
                raise ValueError("此项没有已保存引用，不能自动声称有原文支持")
            show_citation(citations[0])
            with pdf_area:
                for citation in citations[1:]:
                    label, tooltip = citation_button_text(
                        citation, citation_sources, prefix="其它引用", aliases=aliases
                    )
                    ui.button(
                        label,
                        on_click=guard(lambda c=citation: show_citation(c)),
                    ).props("flat").tooltip(tooltip)

    def revision_dialog(self, path, result):
        from nicegui import ui

        from aletheia_nexus.processing.contracts import NATURE
        from aletheia_nexus.processing.results import FIELD_STATUS, NATURE_LABELS

        choices = {
            "record:" + r["id"]: "记录 " + r["id"]
            for r in result["response"].get("records", [])
        }
        choices.update(
            {
                f"claim:{i}": "主张 " + str(i + 1)
                for i, _ in enumerate(result["response"].get("claims", []))
            }
        )
        choices.update(
            {
                f"issue:{i}": "诊断 " + str(i + 1)
                for i, _ in enumerate(result["response"].get("issues", []))
            }
        )
        if not choices:
            raise ValueError("此结果没有可修订条目")
        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[1000px] max-w-[95vw] an-card"),
        ):
            ui.label("修订结果（创建新版本）").classes("text-xl font-semibold")
            authority = ui.select(
                {"human": "人工修订", "assistant": "AI 辅助修订"},
                value="human",
                label="修订来源",
            ).classes("w-full")
            ui.label(
                "请如实记录修订来源。AI 辅助修订保留为待人工核对，不能作人工科学确认；"
                "保存本地修订不会调用模型或产生新的 API 费用。"
            ).classes("an-muted text-sm")
            target = ui.select(
                choices, value=next(iter(choices)), label="修订条目"
            ).classes("w-full")
            editor = ui.column().classes("w-full")
            author = ui.input("修订人", value="本地研究者").classes("w-full")
            reason = ui.textarea("修改理由 / 核对依据").classes("w-full")
            confirm = ui.checkbox(
                "我已逐项核对此记录/主张的全部科学内容与证据，标为人工确认", value=False
            )
            state = {"target": None, "replacement": None, "controls": {}}

            def update_confirmation():
                confirm.set_value(False)
                confirm.set_enabled(
                    authority.value == "human" and not target.value.startswith("issue:")
                )

            def load():
                kind, key = target.value.split(":", 1)
                if kind == "record":
                    original = next(
                        r for r in result["response"]["records"] if r["id"] == key
                    )
                    state["target"] = {"record_id": key}
                else:
                    original = result["response"][
                        "claims" if kind == "claim" else "issues"
                    ][int(key)]
                    state["target"] = {
                        "claim_index" if kind == "claim" else "issue_index": int(key)
                    }
                state["replacement"] = deepcopy(original)
                state["controls"] = {}
                editor.clear()
                with editor:
                    if kind == "record":
                        definitions = {f["id"]: f for f in result["task"]["fields"]}
                        for field_id, value in original["fields"].items():
                            definition = definitions[field_id]
                            ui.label(definition.get("label") or field_id).classes(
                                "font-semibold"
                            )
                            field_type = definition["type"]
                            status = ui.select(
                                FIELD_STATUS,
                                value=value["status"],
                                label="科学报告状态",
                            ).classes("w-full")
                            editors = ui.column().classes("w-full")
                            with editors:
                                raw = ui.textarea(
                                    "原文值（保留原文拼写；无单一原文值时可留空）",
                                    value=value.get("raw_value") or "",
                                ).classes("w-full")
                                unit = None
                                if (
                                    field_type in {"number", "integer"}
                                    or value.get("unit") is not None
                                    or definition.get("unit") is not None
                                ):
                                    unit = ui.input(
                                        "单位（没有单位时留空）",
                                        value=value.get("unit") or "",
                                    ).classes("w-full")
                                nature = ui.select(
                                    {
                                        "__none__": "请选择内容来源性质",
                                        **{k: NATURE_LABELS[k] for k in NATURE["enum"]},
                                    },
                                    value=value.get("nature") or "__none__",
                                    label="科学内容性质",
                                ).classes("w-full")
                            missing_note = ui.label(
                                "当前材料未报告：此版会保存空值、空原文值和空单位；请在条件中解释核对范围。"
                            ).classes("an-muted text-sm")

                            def show_field(
                                editors=editors, status=status, note=missing_note
                            ):
                                editors.set_visibility(status.value != "not_reported")
                                note.set_visibility(status.value == "not_reported")

                            status.on_value_change(
                                lambda _, update=show_field: update()
                            )
                            show_field()
                            if field_type in {"number", "integer"}:
                                control = ui.number("值", value=value.get("value"))
                            elif field_type == "boolean":
                                control = ui.select(
                                    {"true": "是", "false": "否", "null": "未报告"},
                                    value="null"
                                    if value.get("value") is None
                                    else str(value["value"]).lower(),
                                    label="值",
                                )
                            else:
                                val = value.get("value")
                                control = ui.textarea(
                                    "值（列表每行一项）"
                                    if field_type == "string_list"
                                    else "值",
                                    value="\n".join(val)
                                    if isinstance(val, list)
                                    else (val or ""),
                                ).classes("w-full")
                            control.move(editors, target_index=0)
                            context = ui.textarea(
                                "适用对象、阶段与条件", value=value.get("context", "")
                            ).classes("w-full")
                            state["controls"][field_id] = {
                                "kind": field_type,
                                "value": control,
                                "context": context,
                                "raw_value": raw,
                                "unit": unit,
                                "status": status,
                                "nature": nature,
                            }
                    else:
                        state["text"] = ui.textarea(
                            "主张" if kind == "claim" else "诊断说明",
                            value=original.get("text", original.get("detail", "")),
                        ).classes("w-full")
                    with ui.expansion(
                        "专家：完整替代条目（包括引用）", icon="data_object"
                    ).classes("w-full"):
                        state["expert_mode"] = ui.checkbox(
                            "使用完整条目编辑器", value=False
                        )
                        state["expert"] = (
                            ui.textarea("条目 JSON", value=json_text(original))
                            .props("autogrow")
                            .classes("w-full")
                        )
                    json_view(original, label="不可变父版本条目")
                update_confirmation()

            def save():
                kind = target.value.split(":", 1)[0]
                if state["expert_mode"].value:
                    replacement = json.loads(state["expert"].value)
                else:
                    replacement = deepcopy(state["replacement"])
                    if kind == "record":
                        for key, controls in state["controls"].items():
                            replacement["fields"][key] = revised_field(
                                replacement["fields"][key],
                                controls["kind"],
                                {
                                    name: element.value
                                    for name, element in controls.items()
                                    if name != "kind" and element is not None
                                },
                            )
                    else:
                        replacement["text" if kind == "claim" else "detail"] = state[
                            "text"
                        ].value
                receipt = self.ctx.research.revise(
                    path,
                    state["target"],
                    replacement,
                    reason=reason.value,
                    author=author.value,
                    confirm=confirm.value
                    if kind != "issue" and authority.value == "human"
                    else False,
                    human=authority.value == "human",
                    authority=authority.value,
                )
                self.current_result = receipt["result"]
                dialog.close()
                self.page_content.refresh()

            target.on_value_change(lambda _: load())
            authority.on_value_change(lambda _: update_confirmation())
            load()
            ui.button("保存独立修订版本", icon="save", on_click=guard(save))
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()
