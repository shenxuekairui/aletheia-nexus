"""Independent public SI acquisition, using the shared library service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .storage_paths import PathPreferences
from .workbench.library import LibraryService
from .workbench.standalone_supplements import StandaloneSupplementService


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus si", description="按 DOI 单独获取 SI，无需先取得正文。"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    acquire = commands.add_parser(
        "acquire", help="获取公开 SI，先按 DOI 保存，之后可关联正文"
    )
    acquire.add_argument("dois", nargs="+")
    acquire.add_argument("--title", help="单篇论文的预期原题")
    acquire.add_argument("--max-files", type=int, default=20)
    acquire.add_argument("--max-bytes", type=int, default=100 * 1024**2)
    acquire.add_argument("--timeout", type=float, default=30)
    acquire.add_argument("--include-peer-review", action="store_true")
    listing = commands.add_parser("list", help="查看独立获取的附件")
    listing.add_argument("--pending-only", action="store_true")
    attach = commands.add_parser(
        "attach", help="按 DOI/题名和哈希核对后关联已入库正文，保留原件"
    )
    attach.add_argument("--main-pdf", type=Path, required=True)
    attach.add_argument(
        "--attachment-id", action="append", help="省略时关联该 DOI 的全部独立附件"
    )
    for command in [acquire, listing, attach]:
        command.add_argument("--library", type=Path)
        command.add_argument("--library-state-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        paths = PathPreferences().resolve(
            library=args.library, library_state_dir=args.library_state_dir
        )
        service = StandaloneSupplementService(
            LibraryService(paths.library, paths.library_state_dir)
        )
        if args.command == "acquire":
            if args.title and len(args.dois) != 1:
                raise ValueError("--title 仅适用于单篇 DOI")
            result = service.acquire_many(
                [
                    {"doi": doi, **({"title": args.title} if args.title else {})}
                    for doi in args.dois
                ],
                max_files=args.max_files,
                max_bytes=args.max_bytes,
                timeout=args.timeout,
                include_peer_review=args.include_peer_review,
            )
        elif args.command == "list":
            result = service.list(pending_only=args.pending_only)
        else:
            result = service.bind(args.main_pdf, args.attachment_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status", "COMPLETED") == "COMPLETED" else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"SI 操作失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
