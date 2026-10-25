"""CLI for opt-in, local-persisted literature processing."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

from aletheia_nexus.processing.contracts import EXPORT_FORMATS, export_formats
from aletheia_nexus.processing.engine import run_task, write_json
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import (
    export_results,
    revise_result,
    verify_result,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus research",
        description="本地保存的文献整理、字段提取与比较；远程 AI 必须显式启用。",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="运行或恢复一个 JSON 科研任务")
    run.add_argument("task", type=Path)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument(
        "--allow-remote", action="store_true", help="还需任务 allow_remote=true"
    )
    run.add_argument("--no-resume", action="store_true")
    run.add_argument("--mode", choices=["local", "parsed", "hybrid", "direct"])
    export = commands.add_parser("export", help="从本地结果重新导出，不调用 AI")
    export.add_argument("results", type=Path, nargs="+")
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument(
        "--formats",
        nargs="+",
        choices=EXPORT_FORMATS,
        help="本次导出格式；省略时使用任务配置",
    )
    revision = commands.add_parser("revise", help="保存人工修订的派生版本，保留旧结果")
    revision.add_argument("result", type=Path)
    revision.add_argument("revision", type=Path)
    revision.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            task = json.loads(args.task.read_text(encoding="utf-8-sig"))
            if args.mode:
                task["mode"] = args.mode
            manifest = run_task(
                task,
                base_dir=args.task.resolve().parent,
                output_dir=args.output_dir,
                allow_remote=args.allow_remote,
                resume=not args.no_resume,
            )
            print(f"{manifest['status']} · {manifest['run_directory']}")
            for row in manifest["items"]:
                print(
                    f"  {row['id']}: {row['status']}"
                    + (f" ({row['error']})" if row.get("error") else "")
                )
            print(
                f"HTTP attempts: {manifest['usage']['http_attempts']}; "
                + " / ".join([*manifest["outputs"], "manifest.json"])
            )
            return 0 if manifest["status"] in {"COMPLETED", "PREPARED"} else 1
        if args.command == "export":
            results = [
                json.loads(p.read_text(encoding="utf-8-sig")) for p in args.results
            ]
            for result in results:
                verify_result(result)
            task = results[0]["task"]
            comparable = ("type", "objective", "fields", "rules")
            if any(any(r["task"][k] != task[k] for k in comparable) for r in results):
                raise ValueError(
                    "export requires the same question, field definitions, type and rules"
                )
            export_task = deepcopy(task)
            if args.formats:
                export_task["export_formats"] = args.formats
            outputs = export_results(results, export_task, args.output_dir)
            write_json(
                args.output_dir / "export-manifest.json",
                {
                    "schema": "aletheia-nexus/research-export/v1",
                    "inputs": [
                        {
                            "path": str(path.resolve()),
                            "result_id": result["artifact_id"],
                        }
                        for path, result in zip(args.results, results, strict=True)
                    ],
                    "contract": {k: task[k] for k in comparable},
                    "export_formats": export_formats(export_task),
                    "outputs": outputs,
                },
            )
            print(str(args.output_dir.resolve()))
        else:
            result = json.loads(args.result.read_text(encoding="utf-8-sig"))
            revision = json.loads(args.revision.read_text(encoding="utf-8-sig"))
            updated = revise_result(result, revision)
            write_json(args.output, updated)
            print(str(args.output.resolve()))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # Never echo a provider response, key, request body or arbitrary exception repr.
        code = exc.code if isinstance(exc, ProcessingError) else type(exc).__name__
        print(f"Research task failed: {code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
