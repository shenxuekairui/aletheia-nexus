"""Local storage settings for ordinary desktop users."""

from pathlib import Path
from string import ascii_uppercase

from .storage import check_real_path, open_folder
from .ui_common import guard

STORAGE_TYPES = (
    ("library", "文献库位置", "论文 PDF、SI（补充材料）及其他文献文件"),
    (
        "library_state_dir",
        "文库索引 / 数据库位置",
        "论文登记信息、分类、标签、文献集合等 JSON 文件和目录（library.json）",
    ),
    (
        "workspace",
        "工作区位置",
        "工作台设置、任务记录、解析结果、科研分析成果及运行数据",
    ),
)


def choose_folder(initial, selected):
    """A local folder picker that also works without a native GUI toolkit."""
    from nicegui import ui

    current = Path(initial)
    while not current.is_dir() and current != current.parent:
        current = current.parent
    with ui.dialog() as dialog, ui.card().classes("w-[760px] max-w-[95vw]"):
        ui.label("选择文件夹").classes("text-xl font-semibold")
        location = (
            ui.input("当前目录", value=str(current)).classes("w-full").props("outlined")
        )
        with ui.row().classes("w-full"):
            ui.button(
                "上一级",
                icon="arrow_upward",
                on_click=guard(lambda: browse(Path(location.value).parent)),
            ).props("flat")
            ui.button("转到", on_click=guard(lambda: browse(location.value))).props(
                "flat"
            )
            for drive in (Path(f"{letter}:/") for letter in ascii_uppercase):
                if drive.is_dir():
                    ui.button(
                        str(drive), on_click=guard(lambda p=drive: browse(p))
                    ).props("flat")
        entries = ui.column().classes("w-full max-h-72 overflow-auto")

        def browse(value):
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValueError("请输入完整绝对路径")
            check_real_path(path)
            folders = sorted(
                (p for p in path.iterdir() if p.is_dir()),
                key=lambda p: p.name.casefold(),
            )
            location.set_value(str(path))
            entries.clear()
            with entries:
                for folder in folders:
                    ui.button(
                        folder.name,
                        icon="folder",
                        on_click=guard(lambda p=folder: browse(p)),
                    ).props("flat align=left").classes("w-full")

        browse(current)
        ui.label(
            "选择已有文件夹后，可在修改位置中追加新文件夹名称。目标必须为空。 "
        ).classes("an-muted text-sm")
        with ui.row():
            ui.button(
                "选择此文件夹",
                on_click=lambda: (selected(location.value), dialog.close()),
            )
            ui.button("取消", on_click=dialog.close).props("flat")
    dialog.open()


def storage_dialog(context):
    from nicegui import run, ui

    manager = context.storage
    path_labels, modify_buttons = {}, []
    with ui.dialog() as dialog, ui.card().classes("w-[1000px] max-w-[95vw] an-card"):
        ui.label("数据存储管理").classes("an-title")
        ui.label(
            "迁移会复制并校验数据，保留原目录；切换后请重新启动工作台。运行中的任务完成前不能迁移。"
        ).classes("an-info w-full")
        status = (
            ui.label().classes("w-full text-sm").props("role=status aria-live=polite")
        )
        if manager.restart_required:
            status.set_text(
                "位置已保存，请关闭当前服务后重新启动。省略原来的路径参数，或将其更新为下方新路径。"
            )
        for kind, title, purpose in STORAGE_TYPES:
            with ui.card().classes("an-card w-full p-5"):
                ui.label(title).classes("text-lg font-semibold")
                ui.label(purpose).classes("an-muted text-sm")
                path_labels[kind] = ui.label(str(getattr(manager.paths, kind))).classes(
                    "w-full break-all font-mono text-sm"
                )
                with ui.row():
                    modify_buttons.append(
                        ui.button(
                            "修改位置",
                            icon="drive_file_move",
                            on_click=guard(lambda k=kind, t=title: change_dialog(k, t)),
                        )
                        .props("outline")
                        .set_enabled(not manager.restart_required)
                    )
                    ui.button(
                        "打开文件夹",
                        icon="folder_open",
                        on_click=guard(
                            lambda k=kind: open_folder(getattr(manager.paths, k))
                        ),
                    ).props("flat")
        ui.label(f"路径配置独立保存在：{manager.preferences.path}").classes(
            "an-muted text-xs break-all"
        )
        ui.button("关闭", on_click=dialog.close).props("flat")

    def change_dialog(kind, title):
        with ui.dialog() as change, ui.card().classes("w-[760px] max-w-[95vw] an-card"):
            ui.label(f"修改{title}").classes("text-xl font-semibold")
            ui.label(f"当前位置：{getattr(manager.paths, kind)}").classes(
                "break-all text-sm"
            )
            target = (
                ui.input("新文件夹完整路径", placeholder="例如 D:\\AN-Library")
                .classes("w-full")
                .props("outlined")
            )
            ui.button(
                "选择新的文件夹",
                icon="folder",
                on_click=guard(
                    lambda: choose_folder(
                        getattr(manager.paths, kind), target.set_value
                    )
                ),
            ).props("flat")
            ui.label(
                "迁移现有数据并切换：复制全部数据，校验成功后生效，原数据保留。使用新的空目录：从空目录开始，不复制、不覆盖文件。索引或工作区为空时不会显示原有记录。"
            ).classes("an-muted text-sm")
            progress = ui.label().props("role=status aria-live=polite")
            buttons = []

            async def apply(migrate):
                for button in buttons:
                    button.disable()
                progress.set_text(
                    "正在复制和校验，请等待…" if migrate else "正在检查新目录…"
                )
                try:
                    result = await run.io_bound(
                        manager.change, kind, target.value, migrate=migrate
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    progress.set_text(f"未切换，继续使用原位置：{exc}")
                    for button in buttons:
                        button.enable()
                    return
                progress.set_text(
                    f"已保存新位置，校验复制 {result['files']} 个文件。请关闭当前服务并重新启动工作台。启动时省略旧路径参数，或将参数更新为新路径。"
                )
                status.set_text("位置已保存，需要重新启动；当前会话已停止写入。")
                for key, label in path_labels.items():
                    label.set_text(str(getattr(manager.paths, key)))
                for button in modify_buttons:
                    button.disable()
                target.disable()

            with ui.row():
                buttons.append(
                    ui.button(
                        "迁移现有数据并切换",
                        icon="content_copy",
                        on_click=lambda: apply(True),
                    )
                )
                buttons.append(
                    ui.button("使用新的空目录", on_click=lambda: apply(False)).props(
                        "outline"
                    )
                )
                ui.button("关闭", on_click=change.close).props("flat")
        change.open()

    dialog.open()
