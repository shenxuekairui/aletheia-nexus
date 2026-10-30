"""Explicit previews for mutable collections, filters and tag groups."""

import inspect
from copy import deepcopy

from .labels import value_label
from .ui_common import guard, json_view, rows_table, split_tags

SECTIONS = {
    "collections": "固定研究集合",
    "filters": "保存筛选规则",
    "tag_groups": "标签分组",
}


def collection_change(before, incoming, action):
    """Compute fixed membership by stable IDs, never by display title or path."""
    before, incoming = list(dict.fromkeys(before)), list(dict.fromkeys(incoming))
    if action == "replace":
        after = incoming
    elif action == "add":
        after = list(dict.fromkeys([*before, *incoming]))
    elif action == "remove":
        after = [paper_id for paper_id in before if paper_id not in incoming]
    else:
        raise ValueError("请选择替换、追加或移除成员。")
    return {
        "before": before,
        "after": after,
        "added": [paper_id for paper_id in after if paper_id not in before],
        "removed": [paper_id for paper_id in before if paper_id not in after],
    }


async def render_organization_dialog(
    controller,
    *,
    marked_ids=(),
    current_filters=None,
    on_updated=None,
    apply_filter=None,
):
    from nicegui import run, ui

    library = controller.ctx.library
    papers = await run.io_bound(library.scan)
    by_id = {row["id"]: row for row in papers["items"]}
    marked_ids = list(dict.fromkeys(marked_ids))
    current_filters = deepcopy(current_filters)
    state = {"pending": None, "loading": False}

    def catalog(section):
        return getattr(controller.ctx.library, section)()

    with ui.context.client.layout:
        dialog = ui.dialog()
    with dialog, ui.card().classes("w-[1100px] max-w-[96vw] an-card"):
        ui.label("管理集合、筛选与标签分组").classes("an-title")
        ui.label(
            "固定集合保存具体成员，筛选保存可重新运行的条件，标签分组组织标签。"
            "表格视图只决定列和显示方式，仍在“列 / 排序 / 视图”管理；这些修改不改变历史研究快照。"
        ).classes("an-info w-full")
        ui.label(
            "修改标签分组不会给论文批量添加、移除或重命名标签。请使用“标签与分组”处理论文标签。"
        ).classes("an-muted text-sm")
        with ui.row().classes("an-toolbar w-full"):
            section = ui.select(SECTIONS, value="collections", label="管理哪类对象")
            selected = ui.select([], value=None, label="选择已有对象").classes("grow")
        editor = ui.column().classes("w-full")
        preview_area = ui.column().classes("w-full")

        def reset_preview():
            state["pending"] = None
            preview_area.clear()

        def prepare(action, value=None):
            kind, name = section.value, selected.value
            objects = catalog(kind)
            if name not in objects:
                raise ValueError("该对象已不存在，请重新选择或刷新管理列表。")
            before = deepcopy(objects[name])
            if before != state.get("baseline"):
                raise ValueError("该对象已在其它窗口修改，请刷新后重新预览。")
            pending = {
                "section": kind,
                "name": name,
                "action": action,
                "before": before,
            }
            if action == "rename":
                value = (value or "").strip()
                if not value or len(value) > 100:
                    raise ValueError("请填写不超过100个字符的新名称。")
                if value != name and value in objects:
                    raise ValueError("新名称已存在，请选择其它名称；不会覆盖已有对象。")
                pending["value"] = value
            elif action == "members":
                pending.update(value)
            elif action == "save":
                pending["value"] = deepcopy(value)
            elif action == "delete" and kind == "collections":
                dependents = [
                    label
                    for label, rules in catalog("filters").items()
                    if rules.get("collection") == name
                ]
                if dependents:
                    raise ValueError(
                        "该集合仍被以下保存筛选使用，请先修改或删除这些筛选："
                        + "、".join(dependents)
                    )
            state["pending"] = pending
            preview_area.clear()
            with preview_area:
                ui.separator()
                ui.label("本次修改预览").classes("text-lg font-semibold")
                ui.label(f"{SECTIONS[kind]}：{name}")
                if action == "members":
                    ui.label(
                        f"原成员 {len(before)} 篇 → 新成员 {len(pending['after'])} 篇；"
                        f"新增 {len(pending['added'])} 篇，移除 {len(pending['removed'])} 篇。"
                    ).classes("an-info w-full")
                    rows_table(
                        [
                            {
                                "id": paper_id,
                                "title": (by_id.get(paper_id) or {}).get(
                                    "title", "已不在当前文库"
                                ),
                                "change": label,
                            }
                            for key, label in (
                                ("added", "加入集合"),
                                ("removed", "移出集合"),
                            )
                            for paper_id in pending[key]
                        ],
                        columns=[
                            {"name": key, "field": key, "label": label, "align": "left"}
                            for key, label in (
                                ("title", "论文"),
                                ("change", "成员变化"),
                            )
                        ],
                    )
                elif action == "rename":
                    ui.label(
                        f"名称：{name} → {value}；集合被保存筛选引用时会同步更新引用。"
                    )
                elif action == "delete":
                    ui.label(
                        "只删除这个组织对象；不删除论文、PDF、标签或历史科研结果。"
                    )
                else:
                    ui.label("原内容与拟保存内容如下，请核对后确认。")
                    render_value(kind, before)
                    ui.label("修改后").classes("font-semibold")
                    render_value(kind, pending["value"])
                confirmed = ui.checkbox(
                    "我已核对以上范围和变化，确认执行本次修改", value=False
                )

                async def commit():
                    if not confirmed.value or state["pending"] is not pending:
                        raise ValueError("请先预览并明确确认本次修改。")
                    fresh = catalog(kind)
                    if name not in fresh or fresh[name] != before:
                        raise ValueError("该对象已在其它窗口修改，请刷新后重新预览。")
                    service = controller.ctx.library
                    if action == "rename":
                        service.rename_named(kind, name, pending["value"])
                        if (
                            kind == "collections"
                            and current_filters is not None
                            and current_filters.get("collection") == name
                        ):
                            current_filters["collection"] = pending["value"]
                    elif action == "delete":
                        service.delete_named(kind, name)
                    elif action == "members":
                        service.save_collection(name, pending["after"])
                    else:
                        save = (
                            service.save_filter
                            if kind == "filters"
                            else service.save_tag_group
                        )
                        save(name, pending["value"])
                    change = {
                        **pending,
                        "new_name": pending["value"] if action == "rename" else None,
                    }
                    reset_preview()
                    reload_objects(name=change["new_name"] or name)
                    if on_updated:
                        result = on_updated(change)
                        if inspect.isawaitable(result):
                            await result
                    ui.notify(
                        "组织信息已更新；论文文件和历史研究快照未改变。",
                        type="positive",
                    )

                ui.button("确认执行本次修改", icon="check", on_click=guard(commit))
                json_view(pending, label="本次稳定成员身份与原始规则")

        def render_value(kind, value):
            if kind == "collections":
                ui.label(f"固定成员 {len(value)} 篇，不随筛选条件自动增减。")
                rows_table(
                    [
                        {
                            "id": paper_id,
                            "title": (by_id.get(paper_id) or {}).get(
                                "title", "已不在当前文库"
                            ),
                        }
                        for paper_id in value
                    ],
                    columns=[
                        {
                            "name": "title",
                            "field": "title",
                            "label": "成员论文",
                            "align": "left",
                        }
                    ],
                )
            elif kind == "filters":
                if not value:
                    ui.label("没有附加条件；运行时匹配当前文库全部论文。")
                for key, item in value.items():
                    label = {
                        "query": "标题 / DOI / 文件名关键词",
                        "folder": "分类目录",
                        "tags": "标签",
                        "tag_mode": "标签组合",
                        "ids": "指定文献",
                        "parsed": "解析状态",
                        "untranslated": "仅缺少中文标题",
                        "collection": "固定集合",
                    }.get(key, key)
                    if key == "ids" and isinstance(item, list):
                        text = f"{len(item)} 篇（其中 {sum(i not in by_id for i in item)} 篇不在当前文库）"
                    elif key == "tag_mode":
                        text = {"AND": "全部标签", "OR": "任一标签"}.get(
                            item, str(item)
                        )
                    elif key == "parsed" and type(item) is bool:
                        text = "已成功解析" if item else "未成功解析"
                    elif isinstance(item, list):
                        text = "、".join(map(str, item)) or "不限制"
                    else:
                        text = value_label(item)
                    ui.label(f"{label}：{text}").classes("break-all")
            else:
                ui.label(f"共 {len(value)} 个标签：" + ("、".join(value) or "空分组"))

        def render_editor():
            if state["loading"]:
                return
            reset_preview()
            editor.clear()
            objects = catalog(section.value)
            value = deepcopy(objects.get(selected.value))
            state["baseline"] = value
            with editor:
                if value is None:
                    ui.label(
                        "此类暂无对象。可从选择清单保存集合、文库保存筛选，或在标签与分组中新建分组。"
                    )
                    return
                render_value(section.value, value)
                if section.value == "collections":
                    tray = controller.ctx.library.selection()
                    source = ui.select(
                        {
                            "marked": f"本次表格勾选（{len(marked_ids)} 篇）",
                            "tray": f"全局选择清单（{len(tray)} 篇）",
                        },
                        value="marked" if marked_ids else "tray",
                        label="本次使用的成员范围",
                    ).classes("w-full")
                    action = ui.select(
                        {
                            "replace": "替换全部成员",
                            "add": "追加到集合",
                            "remove": "从集合移除",
                        },
                        value="add",
                        label="成员操作",
                    ).classes("w-full")

                    def preview_members():
                        incoming = marked_ids if source.value == "marked" else tray
                        if not incoming:
                            raise ValueError(
                                "本次成员范围为空，请先勾选论文或添加到全局选择清单。"
                            )
                        prepare(
                            "members", collection_change(value, incoming, action.value)
                        )

                    source.on_value_change(lambda _: reset_preview())
                    action.on_value_change(lambda _: reset_preview())
                    ui.button(
                        "预览成员变更", icon="groups", on_click=guard(preview_members)
                    )
                elif section.value == "filters":
                    if current_filters is not None:
                        ui.button(
                            "预览更新为当前文库筛选条件",
                            icon="filter_alt",
                            on_click=guard(lambda: prepare("save", current_filters)),
                        ).props("outline")
                    if apply_filter:

                        def apply_current_filter():
                            rules = deepcopy(catalog("filters")[selected.value])
                            dialog.close()
                            apply_filter(rules)

                        ui.button(
                            "在文库中运行此筛选", on_click=guard(apply_current_filter)
                        ).props("flat")
                else:
                    tags = controller.tag_input(
                        "修改组内标签（输入可查找，回车新建）", value
                    )
                    tags.on_value_change(lambda _: reset_preview())
                    ui.button(
                        "预览分组标签修改",
                        on_click=guard(lambda: prepare("save", split_tags(tags.value))),
                    )
                rename = ui.input(
                    "新名称（仅改组织名称）", value=selected.value
                ).classes("w-full")
                rename.on_value_change(lambda _: reset_preview())
                with ui.row().classes("an-toolbar"):
                    ui.button(
                        "预览重命名",
                        icon="edit",
                        on_click=guard(lambda: prepare("rename", rename.value)),
                    ).props("outline")
                    ui.button(
                        "预览删除",
                        icon="delete_outline",
                        on_click=guard(lambda: prepare("delete")),
                    ).props("flat")

        def reload_objects(*, name=None):
            objects = catalog(section.value)
            wanted = name if name in objects else selected.value
            if wanted not in objects:
                wanted = next(iter(objects), None)
            state["loading"] = True
            try:
                selected.set_options(list(objects), value=wanted)
            finally:
                state["loading"] = False
            render_editor()

        section.on_value_change(lambda _: reload_objects())
        selected.on_value_change(lambda _: render_editor())
        ui.button("刷新组织信息", icon="refresh", on_click=guard(reload_objects)).props(
            "flat"
        )
        ui.button("关闭", on_click=dialog.close).props("flat")
        reload_objects()
    dialog.open()
    return dialog
