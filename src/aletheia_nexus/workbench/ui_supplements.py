"""Ordinary SI acquisition without a main PDF, backed by the shared service."""

from .labels import value_label
from .standalone_supplements import StandaloneSupplementService
from .ui_common import guard


def independent_si_dialog(page):
    from nicegui import run, ui

    with ui.dialog() as dialog, ui.card().classes("w-[1000px] max-w-[96vw]"):
        ui.label("单独获取 SI").classes("text-xl font-semibold")
        ui.label(
            "不需要先下载正文。按 DOI 从公开来源获取 SI 和数据附件；"
            "先保存为“尚未关联正文”，之后可关联已入库的正文。"
        ).classes("an-info w-full")
        value = (
            ui.textarea("论文 DOI（每行一篇）")
            .props("outlined rows=4")
            .classes("w-full")
        )
        with ui.row().classes("w-full"):
            limit = ui.number(
                "每篇最多附件数", value=20, min=1, max=100, step=1
            ).classes("w-48")
            maximum = ui.number(
                "单文件上限（MiB）", value=100, min=1, max=2048, step=1
            ).classes("w-48")
            peer_review = ui.checkbox("同时获取审稿材料", value=False)
        ui.label(
            "默认只尝试公开原生路线，不调用 AI；保存附件不等于已解析其内容。"
        ).classes("an-muted text-sm")

        def start():
            preview = page.ctx.acquisition.preview_inputs(value.value or "")
            requests = [
                item["request"] for item in preview["items"] if not item["duplicate"]
            ]
            if (
                preview["errors"]
                or not requests
                or any(not item.get("doi") for item in requests)
            ):
                raise ValueError(
                    "请输入每篇论文的可靠 DOI；请先修正缺少 DOI 或格式错误的条目。"
                )
            options = {
                "max_files": int(limit.value),
                "max_bytes": int(maximum.value * 1024**2),
                "include_peer_review": bool(peer_review.value),
            }
            page.submit(
                "si_acquisition",
                f"单独获取 {len(requests)} 篇论文的 SI",
                [item["doi"] for item in requests],
                lambda context: StandaloneSupplementService(
                    page.ctx.library
                ).acquire_many(requests, context=context, **options),
                {
                    "library": str(page.ctx.library.root),
                    "requests": requests,
                    "options": options,
                },
            )

        with ui.row():
            ui.button("开始单独获取 SI", icon="download", on_click=guard(start))
            ui.button(
                "刷新已保存附件", icon="refresh", on_click=lambda: saved.refresh()
            ).props("outline")
            ui.button("关闭", on_click=dialog.close).props("flat")

        @ui.refreshable
        def saved():
            service = StandaloneSupplementService(page.ctx.library)
            result = service.list()
            ui.label(
                f"已独立保存 {len(result['items'])} 份；尚未关联正文 {result['pending']} 份"
            ).classes("font-medium")
            for warning in result["warnings"]:
                ui.label(
                    f"有附件未通过当前完整性检查：{warning['source_record']}"
                ).classes("text-orange-9")
            if not result["items"]:
                ui.label("任务完成后点击“刷新已保存附件”查看文件。").classes("an-muted")
                return
            rows = [
                {
                    **item,
                    "role_label": value_label(item["role"]),
                    "association": "已关联正文"
                    if item["bound_paper_ids"]
                    else "尚未关联正文",
                }
                for item in result["items"]
            ]
            table = ui.table(
                columns=[
                    {"name": key, "field": key, "label": label, "align": "left"}
                    for key, label in [
                        ("doi", "论文 DOI"),
                        ("filename", "附件文件"),
                        ("role_label", "用途"),
                        ("association", "正文关联"),
                    ]
                ],
                rows=rows,
                row_key="id",
                selection="single",
                pagination=10,
            ).classes("w-full")

            def selected():
                if page.ctx.library.root != service.library.root:
                    raise ValueError("文库已切换，请刷新后重新选择附件。")
                if len(table.selected) != 1:
                    raise ValueError("请先选择一份已保存的附件。")
                return service.get(table.selected[0]["id"])

            def open_file():
                item = selected()
                ui.navigate.to(page.files.register(item["path"]), new_tab=True)

            def bind():
                item = selected()
                papers = [
                    row
                    for row in page.ctx.library.scan()["items"]
                    if row.get("doi") == item["doi"]
                ]
                if not papers:
                    raise ValueError(
                        "文库中还没有同 DOI 的正文。请先获取或导入正文；独立 SI 会继续保留。"
                    )
                with (
                    ui.dialog() as association,
                    ui.card().classes("w-[700px] max-w-[95vw]"),
                ):
                    ui.label("选择所属正文").classes("text-lg font-semibold")
                    target = ui.select(
                        {
                            paper["id"]: f"{paper['title']} · {paper['filename']}"
                            for paper in papers
                        },
                        value=papers[0]["id"],
                        label="同 DOI 的已入库正文",
                    ).classes("w-full")
                    ui.label(
                        "将重新核对 DOI、题名及文件哈希，保留独立下载原件和来源记录。"
                    ).classes("an-muted")

                    async def confirm():
                        paper = page.ctx.library.get(target.value)
                        await run.io_bound(
                            service.bind, paper["pdf_path"], [item["id"]]
                        )
                        association.close()
                        saved.refresh()
                        ui.notify(
                            "附件已关联到所选正文；原始下载记录已保留。",
                            type="positive",
                        )

                    ui.button("关联所选正文", on_click=guard(confirm))
                    ui.button("取消", on_click=association.close).props("flat")
                association.open()

            with ui.row():
                ui.button(
                    "打开所选附件", icon="open_in_new", on_click=guard(open_file)
                ).props("outline")
                ui.button("关联已有正文", icon="link", on_click=guard(bind)).props(
                    "outline"
                )

        saved()
    dialog.open()
