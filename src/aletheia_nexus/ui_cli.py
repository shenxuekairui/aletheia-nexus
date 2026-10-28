"""Optional local web entry point. Importing the stable CLI needs no UI extra."""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace


class ContextLease:
    """A stale browser page cannot silently write to a newly selected library."""

    def __init__(self, context):
        self._context, self._generation = context, context.generation

    def __getattr__(self, key):
        if key in {
            "root",
            "library",
            "acquisition",
            "research",
            "translation",
            "input_normalization",
            "switch_root",
        }:
            if self._generation != self._context.generation:
                raise ValueError(
                    "文库已在另一个页面切换；请刷新当前页面后继续，未执行此操作"
                )
        return getattr(self._context, key)


def create_context(root: Path, workspace: Path):
    from .workbench.acquisition import AcquisitionService
    from .workbench.input_normalization import InputNormalizationService
    from .workbench.jobs import TERMINAL, TaskManager
    from .workbench.library import LibraryService
    from .workbench.research import WorkbenchResearch
    from .workbench.settings import SettingsStore
    from .workbench.translation import TranslationService

    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    settings = SettingsStore(workspace)
    context = SimpleNamespace(
        workspace=workspace, settings=settings, jobs=TaskManager(workspace)
    )
    context.generation = 0
    context.input_normalization = InputNormalizationService(workspace)
    context.lease = lambda: ContextLease(context)

    def switch_root(value):
        target = Path(value).expanduser().resolve()
        if any(job["status"] not in TERMINAL for job in context.jobs.list()):
            raise ValueError("请等待后台任务结束后再切换文献库")
        target.mkdir(parents=True, exist_ok=True)
        library = LibraryService(
            target, target / ".an-workbench", reference_roots=[workspace]
        )
        research = WorkbenchResearch(library, workspace)
        acquisition = AcquisitionService(
            target, workspace / "acquisition", library=library
        )
        translation = TranslationService(library, workspace)
        if hasattr(context, "research"):
            context.research.close()
        context.root, context.library, context.research = target, library, research
        context.acquisition, context.translation = acquisition, translation
        context.generation += 1
        settings.set("library_root", str(target))

    context.switch_root = switch_root
    try:
        switch_root(root)
    except Exception:
        context.jobs.close(wait=True)
        raise
    return context


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus ui", description="启动本地科研工作台（仅 127.0.0.1）"
    )
    parser.add_argument(
        "--library",
        type=Path,
        help="授权管理的文库根目录；默认使用已保存目录或当前目录下的 library",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd() / ".aletheia-nexus" / "workbench",
        help="任务、设置、模型缓存及科研快照目录",
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1–65535")
    try:
        from nicegui import app, ui
    except ImportError:
        print(
            '本地工作台需要 UI 可选依赖：python -m pip install "aletheia-nexus[ui]"',
            file=sys.stderr,
        )
        return 2
    from .workbench.security import LoopbackGuard
    from .workbench.settings import SettingsStore
    from .workbench.ui import build_ui

    preferences = SettingsStore(args.workspace)
    root = args.library or Path(
        preferences.get("library_root", str(Path.cwd() / "library"))
    )
    context = create_context(root, args.workspace)
    app.add_middleware(LoopbackGuard, port=args.port)
    app.on_shutdown(lambda: context.jobs.close(wait=True))
    app.on_shutdown(lambda: context.research.close())
    build_ui(context)
    print(
        f"Aletheia Nexus: http://127.0.0.1:{args.port}\n文库：{context.root}\n工作区：{context.workspace}"
    )
    ui.run(
        host="127.0.0.1",
        port=args.port,
        reload=False,
        show=not args.no_open,
        title="Aletheia Nexus · 科研工作台",
        language="zh-CN",
        storage_secret=secrets.token_urlsafe(32),
        binding_refresh_interval=0.2,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
