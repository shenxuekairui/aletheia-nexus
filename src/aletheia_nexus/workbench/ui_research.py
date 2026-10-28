"""Source-scoped parsing/search, reviewable research plans and evidence results."""

from __future__ import annotations

import json
from copy import deepcopy

from .labels import CHOICES, GRID_LOCALE, value_label
from .ui_common import guard, json_text, json_view, parameter_editor, rows_table

FIELD_TYPES = {
    "string": "文本",
    "number": "数字",
    "integer": "整数",
    "boolean": "是或否",
    "string_list": "文本列表",
}


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
            read_options = parameter_editor(
                current,
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
        with ui.card().classes("an-card w-full"):
            with ui.row().classes("an-toolbar w-full"):
                query = (
                    ui.input("关键词 / 带引号短语").props("outlined").classes("grow")
                )
                mode = ui.select(
                    {"and": "全部关键词", "or": "任一关键词"},
                    value="and",
                    label="组合方式",
                ).classes("w-32")
                exact = ui.checkbox("整个查询作精确短语")
                scope = ui.select(
                    ["全部文库", "当前选择清单", *self.ctx.library.collections()],
                    value="全部文库",
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
                offset = ui.number("证据偏移量", value=0, min=0, step=50)
                view = ui.select(
                    ["证据视图", "论文视图"], value="证据视图", label="展示方式"
                )
            status = ui.label(
                "尚未检索。已有CLI解析工件会按身份发现；未解析论文不会自动产生全文命中。"
            ).classes("an-info w-full")
        results_area = ui.column().classes("w-full")
        state = {"table": None, "report": None}

        def selected_ids():
            if scope.value == "当前选择清单":
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
                        "选择并开始AI研究",
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
            add_selected()
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

            status.set_text("正在检查所选来源与关键词索引…")
            report = await run.io_bound(
                self.ctx.research.search,
                query.value,
                selected_ids(),
                include_si=True,
                mode=mode.value,
                exact=exact.value,
                role=None if role.value == "all" else role.value,
                section_type=section.value or None,
                limit=int(size.value),
                offset=int(offset.value),
            )
            display(report)

        async def turn_page(direction):
            offset.set_value(max(0, offset.value + direction * size.value))
            await search()

        with ui.row().classes("an-toolbar"):
            ui.button("检索本地原文", icon="search", on_click=guard(search))
            ui.button(
                "解析当前范围",
                icon="document_scanner",
                on_click=guard(lambda: self.parse_dialog(selected_ids())),
            ).props("outline")

    def research_page(self):
        from nicegui import ui

        from aletheia_nexus.research_planner import DEFAULT_MODEL

        self.title(
            "AI 研究",
            "从当前选择清单创建有范围、字段和预算的科研任务；先审计划，再授权执行。",
        )
        ids = self.ctx.library.selection()
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
            read_model = parameter_editor(model_options)
            read_budget = parameter_editor(
                {
                    "max_calls": 10,
                    "max_cost": 2.0,
                    "max_input_characters": 100000,
                    "max_images": 6,
                    "max_output_tokens": 65536,
                    "max_repair_rounds": 1,
                    "max_supplement_rounds": 1,
                    "max_review_rounds": 0,
                    **(self.current_task or {}).get("budget", {}),
                }
            )
            planning_cost = ui.number(
                "自然语言规划单独费用上限（按模型计费币种）", value=0.5, min=0.01
            )
            planning_consent = ui.checkbox(
                "我授权仅将科研目标和选中文献元数据发送给DeepSeek生成计划（单独计费）",
                value=False,
            )
        plan_area = ui.column().classes("w-full")
        state = {
            "fields": None,
            "documents": None,
            "expert": None,
            "use_expert": None,
            "plan_job": None,
            "loaded": False,
        }

        def render_plan(task):
            self.current_task = task
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

                def add_field():
                    from uuid import uuid4

                    rows = state["fields"].options["rowData"]
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
                    state["fields"].update()

                async def remove_fields():
                    selected = await state["fields"].get_selected_rows()
                    keys = {r["id"] for r in selected}
                    state["fields"].options["rowData"] = [
                        r
                        for r in await state["fields"].get_client_data()
                        if r["id"] not in keys
                    ]
                    state["fields"].update()

                with ui.row().classes("an-toolbar"):
                    ui.button("添加字段", icon="add", on_click=add_field).props("flat")
                    ui.button(
                        "移除选中字段", icon="remove", on_click=guard(remove_fields)
                    ).props("flat")
                document_rows = []
                for doc in task["documents"]:
                    source = self.ctx.research.app.check_document(doc, "direct")
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
                        }
                    )
                state["documents"] = ui.aggrid(
                    {
                        "localeText": GRID_LOCALE,
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
                                    "editable": key in {"pages", "image_pages"},
                                    "width": 180,
                                }
                                for key, label in (
                                    ("role", "主文/SI"),
                                    ("page_count", "物理页数"),
                                    ("identity", "身份依据"),
                                    ("pages", "文本页码（留空全部）"),
                                    ("image_pages", "图像页码（留空不发图）"),
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
                    "页码支持 1,3,5-8；SI页码独立。仅图像模式必须明确给出页码。远程材料限于启用的来源及页码。"
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
                    )
                    reverse_types = {v: k for k, v in FIELD_TYPES.items()}
                    value["fields"] = [
                        {
                            **r,
                            "type": reverse_types.get(r["type"], r["type"]),
                            "unit": r.get("unit") or None,
                        }
                        for r in await state["fields"].get_client_data()
                    ]
                    by_id = {d["id"]: d for d in value["documents"]}
                    docs = []
                    for row in await state["documents"].get_client_data():
                        if not row.get("enabled"):
                            continue
                        doc = deepcopy(by_id[row["id"]])
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
                    checked = self.ctx.research.app.validate_research_task(value)
                    check_area.clear()
                    with check_area:
                        ui.label(checked["plan"]).classes(
                            "whitespace-pre-wrap an-info w-full"
                        )
                        json_view(checked, label="实际指纹与来源身份快照")
                    return checked["task"]

                async def execute():
                    task_value = await validate()
                    grant = consent.value
                    if task_value["mode"] != "local" and not grant:
                        raise ValueError("请明确授权本计划的文献材料外发和费用")
                    self.current_task = task_value
                    self.submit(
                        "research",
                        task_value["objective"][:80],
                        [d["id"] for d in task_value["documents"]],
                        lambda c: self.ctx.research.execute(
                            task_value, consent=grant, context=c
                        ),
                        {"task": task_value},
                    )

                with ui.row().classes("an-toolbar"):
                    ui.button(
                        "验证并预览实际计划",
                        icon="fact_check",
                        on_click=guard(validate),
                    )
                    ui.button(
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
                    context=context,
                )
                task["include_steps"] = steps
                task["synthesize"] = synthesis
                return {"task": task}

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
            receipt = self.submit(
                "research",
                "自然语言科研规划（仅元数据）",
                ids,
                lambda c: self.ctx.research.plan(
                    goal_value,
                    ids,
                    include_si=si,
                    consent=True,
                    model=model,
                    max_cost=options["max_cost"],
                    max_calls=options["max_calls"],
                    planning_max_cost=cost,
                ),
                {"goal": goal_value, "planning_max_cost": cost, "model": model},
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
        options = {
            r[
                "path"
            ]: f"{r['objective'][:60]} · {r['records']} 条 · 修订 {r['revisions']}"
            for r in rows
        }
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
        self.current_result = current
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
                                    "confirmation": result["validation"]
                                    .get("record_states", {})
                                    .get(record["id"], ""),
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
                    with ui.row().classes("an-toolbar"):
                        ui.button(
                            "核对选中数据的证据",
                            icon="picture_as_pdf",
                            on_click=guard(lambda: show_selected()),
                        )
                        ui.button(
                            "人工修订 / 确认",
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
                    for index, claim in enumerate(result["response"].get("claims", [])):
                        with ui.card().classes("an-card w-full"):
                            ui.label(
                                f"主张 {index + 1} · {value_label(claim.get('nature', ''))}"
                            ).classes("text-xs an-muted")
                            ui.label(claim["text"])
                            for citation in claim.get("citations", []):
                                ui.button(
                                    f"核对 {citation.get('source_id')} · 第{citation.get('page')}页",
                                    on_click=guard(lambda c=citation: show_citation(c)),
                                ).props("flat dense")
                    json_view(
                        result["response"].get("issues", []), label="诊断信息与材料不足"
                    )
                    json_view(
                        result["response"].get("requests", []),
                        label="补充材料请求 / 缺失SI",
                    )
                    json_view(result["response"], label="模型结构化结果原始值")
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
            if not table.selected:
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
                    ui.button(
                        f"其它引用 · {citation['source_id']} 第{citation['page']}页",
                        on_click=guard(lambda c=citation: show_citation(c)),
                    ).props("flat")

    def revision_dialog(self, path, result):
        from nicegui import ui

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
            ui.label("人工修订结果（创建新版本）").classes("text-xl font-semibold")
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
                        types = {f["id"]: f["type"] for f in result["task"]["fields"]}
                        for field_id, value in original["fields"].items():
                            ui.label(field_id).classes("font-semibold")
                            field_type = types[field_id]
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
                            context = ui.textarea(
                                "适用对象、阶段与条件", value=value.get("context", "")
                            ).classes("w-full")
                            state["controls"][field_id] = (field_type, control, context)
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
                confirm.set_enabled(kind != "issue")
                confirm.set_value(False)

            def save():
                kind = target.value.split(":", 1)[0]
                if state["expert_mode"].value:
                    replacement = json.loads(state["expert"].value)
                else:
                    replacement = deepcopy(state["replacement"])
                    if kind == "record":
                        for key, (field_type, control, context) in state[
                            "controls"
                        ].items():
                            value = control.value
                            if field_type == "string_list":
                                value = [
                                    v.strip() for v in value.splitlines() if v.strip()
                                ]
                            elif field_type == "integer" and value is not None:
                                if int(value) != value:
                                    raise ValueError("整数类型不能保存小数")
                                value = int(value)
                            elif field_type == "boolean":
                                value = {"true": True, "false": False, "null": None}[
                                    value
                                ]
                            replacement["fields"][key]["value"] = value
                            replacement["fields"][key]["context"] = context.value
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
                    confirm=confirm.value if kind != "issue" else False,
                    human=True,
                )
                self.current_result = receipt["result"]
                dialog.close()
                self.page_content.refresh()

            target.on_value_change(lambda _: load())
            load()
            ui.button("保存独立修订版本", icon="save", on_click=guard(save))
            ui.button("关闭", on_click=dialog.close).props("flat")
        dialog.open()
