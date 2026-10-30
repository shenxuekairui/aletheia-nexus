"""Choose explicit raw material sources without changing catalogue identities."""

from __future__ import annotations

from .catalog_groups import catalog_groups
from .labels import value_label
from .ui_common import guard


def source_choice_groups(rows, selected_ids):
    """Only selected raw sources participate; other variants are never added."""
    ids = list(dict.fromkeys(selected_ids))
    available = {row["id"] for row in rows}
    if set(ids) - available:
        raise ValueError("部分已选来源已不在文库中，请刷新并重新选择。")
    return [
        group
        for group in catalog_groups(rows, matching_ids=ids, selected_ids=ids)
        if len(group["member_ids"]) > 1
    ]


def resolve_catalog_choices(rows, selected_ids, choices):
    """Validate one explicit choice per ambiguous group, retaining raw ID order."""
    ids = list(dict.fromkeys(selected_ids))
    groups = source_choice_groups(rows, ids)
    expected = {group["catalog_key"] for group in groups}
    if set(choices) != expected:
        raise ValueError("请为每篇有多个已选来源的论文选择本次使用的一份来源。")
    removed = set()
    for group in groups:
        chosen = choices[group["catalog_key"]]
        if chosen not in group["member_ids"]:
            raise ValueError("只能使用本次已明确选中的来源，请重新检查选择。")
        removed.update(set(group["member_ids"]) - {chosen})
    return [identity for identity in ids if identity not in removed]


def catalog_hit_rows(rows, hits):
    """Paper view only; original hit objects and per-source evidence stay intact."""
    ids = list(dict.fromkeys(hit["paper_id"] for hit in hits))
    source_choice_groups(rows, ids)  # Also reject missing raw-source locators.
    result = []
    by_paper = {}
    for hit in hits:
        by_paper.setdefault(hit["paper_id"], []).append(hit)
    for group in catalog_groups(rows, matching_ids=ids):
        matching = [
            hit
            for identity in group["member_ids"]
            for hit in by_paper.get(identity, ())
        ]
        result.append(
            {
                "id": group["id"],
                "catalog_key": group["catalog_key"],
                "member_ids": group["member_ids"],
                "title": group.get("title")
                or group.get("title_original")
                or "未命名论文",
                "source_count": len(group["member_ids"]),
                "current_page_hits": len(matching),
                "pages": ",".join(
                    map(
                        str, sorted({page for hit in matching for page in hit["pages"]})
                    )
                ),
            }
        )
    return result


async def choose_catalog_sources(library, ids):
    """Return exact reviewed IDs, or None when the user cancels the dialog."""
    from nicegui import run, ui

    rows = (await run.io_bound(library.scan, ids=ids))["items"]
    groups = source_choice_groups(rows, ids)
    if not groups:
        return list(dict.fromkeys(ids))
    with ui.dialog() as dialog, ui.card().classes("w-[1000px] max-w-[95vw]"):
        ui.label("选择本次实际使用的原始来源").classes("text-xl font-semibold")
        ui.label(
            "同一论文的相同 PDF 有多个已选来源记录。每篇本次使用一份，"
            "其 SI、解析版本和材料快照随该来源确定；原文库、选择清单与历史任务不变。"
        ).classes("an-info w-full")
        controls = {}
        for group in groups:
            with ui.card().classes("an-card w-full"):
                ui.label(
                    group.get("title") or group.get("title_original") or "未命名论文"
                ).classes("font-semibold whitespace-normal")
                options = {}
                for index, row in enumerate(group["matched_variants"], 1):
                    authors = row.get("authors") or []
                    if isinstance(authors, list):
                        authors = "、".join(str(author) for author in authors)
                    options[row["id"]] = (
                        f"来源 {index} · {row.get('pdf_path') or row.get('pdf') or '路径待检查'}\n"
                        f"作者：{authors or '—'} · 解析：{value_label(row.get('parse_status', 'UNPARSED'))}"
                        f" · 附件（含 SI）：{len(row.get('attachments') or [])} 份"
                    )
                controls[group["catalog_key"]] = ui.radio(options).classes(
                    "w-full whitespace-pre-wrap break-all"
                )

        def accept():
            selected = resolve_catalog_choices(
                rows, ids, {key: control.value for key, control in controls.items()}
            )
            dialog.submit(selected)

        with ui.row().classes("an-toolbar"):
            ui.button("使用所选来源继续", on_click=guard(accept))
            ui.button("取消", on_click=dialog.close).props("flat")
    return await dialog


def submit_catalog_sources(controller, ids, submit, *, on_finish=None):
    """Keep the one-source path immediate; multi-source review is awaitable."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError("请先选择论文。")
    library = controller.ctx.library
    root = library.root

    def checked(selected):
        if controller.ctx.library.root != root:
            raise ValueError("文库已切换，请在当前文库重新选择材料后再提交。")
        return submit(selected)

    if len(ids) == 1:
        try:
            return checked(ids)
        finally:
            if on_finish:
                on_finish()

    async def resolve():
        try:
            selected = await choose_catalog_sources(library, ids)
            if selected is not None:
                return checked(selected)
        finally:
            if on_finish:
                on_finish()

    return resolve()
