"""Human-facing planning/confirmation commands; never execute model-generated code."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import ResearchApplication, read_json
from aletheia_nexus.research_planner import draft_task, planning_request


def _consent(message: str, *, interactive: bool) -> bool:
    return interactive and input(message + " [y/N]：").strip().lower() in {
        "y",
        "yes",
        "是",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aletheia-nexus research")
    commands = parser.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="用中文生成科研任务；预览并确认后执行")
    ask.add_argument("goal", nargs="?")
    ask.add_argument("--papers", type=Path)
    ask.add_argument("--output-dir", type=Path)
    ask.add_argument(
        "--task", type=Path, help="使用已保存/编辑的任务，不重新调用规划API"
    )
    ask.add_argument("--model-config", type=Path)
    ask.add_argument(
        "--max-cost", type=float, default=2, help="科研提取费用估算上限CNY"
    )
    ask.add_argument("--max-calls", type=int, default=10)
    ask.add_argument("--planning-max-cost", type=float, default=0.5)
    ask.add_argument(
        "--allow-planning", action="store_true", help="同意发送指令及文献元数据"
    )
    ask.add_argument(
        "--allow-remote", action="store_true", help="同意按已确认计划发送论文内容"
    )
    ask.add_argument("--confirm-plan", help="非交互执行必须匹配预览的任务指纹")
    ask.add_argument("--execute", action="store_true")
    ask.add_argument("--save-only", action="store_true")
    ask.add_argument("--non-interactive", action="store_true")
    authorize = commands.add_parser(
        "authorize", help="本机审阅并签发一次性MCP规划/科研/公共获取授权"
    )
    authorize.add_argument("request", type=Path)
    authorize.add_argument(
        "--approve-fingerprint", help="已审阅请求的绑定指纹，显式非交互批准"
    )
    args = parser.parse_args(argv)
    app = None
    try:
        interactive = sys.stdin.isatty() and not getattr(args, "non_interactive", False)
        if args.command == "authorize":
            request = read_json(args.request.resolve())
            if request.get("schema") != "aletheia-nexus/local-authorization-request/v1":
                raise ValueError("not an authorization request")
            app = ResearchApplication(
                request["roots"],
                request["workspace"],
                remote=True,
                network=request["scope"] == "acquire",
            )
            scope, payload = request["scope"], request["payload"]
            binding = app.binding(scope, payload)
            if request["binding"] != binding:
                raise ProcessingError("authorization_request_changed")
            if scope == "execute":
                print(app.validate_research_task(payload)["plan"])
            elif scope == "acquire":
                from .research_acquisition import public_acquisition_plan

                print(public_acquisition_plan(app, payload)["plan"])
            else:
                print("规划仅发送用户目标及文献元数据，不发送论文全文。")
                print(payload["goal"])
                for doc in payload["metadata"]:
                    print(f"  {doc['id']} · {doc['title']}")
                print(
                    f"规划模型：{payload['model']['name']}；上限：{payload['planning_budget']}"
                )
            print("绑定指纹：" + binding)
            if args.approve_fingerprint != binding and not _consent(
                "确认签发本次授权？", interactive=interactive
            ):
                raise ProcessingError("local_authorization_required")
            print("一次性授权（只交给当前AN MCP调用）：")
            print(app.authorize(scope, payload))
            return 0
        papers = args.papers
        if papers is None:
            if not interactive:
                parser.error("非交互模式需要 --papers")
            papers = Path(input("论文目录：").strip())
        output = args.output_dir
        if output is None:
            if not interactive:
                parser.error("非交互模式需要 --output-dir")
            output = Path(
                input("结果目录 [./research-results]：").strip() or "./research-results"
            )
        app = ResearchApplication([papers], output, remote=True)
        if args.task:
            checked = app.validate_research_task(read_json(args.task.resolve()))
            task_file = args.task.resolve()
        else:
            goal = args.goal
            if not goal and interactive:
                goal = input("请用中文描述科研整理目标：").strip()
            if not goal:
                parser.error("请提供科研目标或 --task")
            listing = app.list_documents(str(papers.resolve()))
            paths = [
                d["path"] for d in listing["documents"] if d["status"] != "UNAVAILABLE"
            ]
            if not paths:
                raise ValueError("目录没有可读PDF")
            print(f"选定{len(paths)}份PDF；登记和解析副本只写入 {app.workspace}")
            prepared = app.prepare_documents(paths)
            for failure in prepared["failures"]:
                print(
                    f"准备失败：{failure['path']} · {failure['error']}", file=sys.stderr
                )
            for warning in dict.fromkeys(prepared["warnings"]):
                print(warning)
            if not prepared["documents"]:
                raise ValueError("没有成功准备的文献")
            if prepared["failures"] and not interactive:
                raise ProcessingError("document_scope_incomplete_review_required")
            if prepared["failures"] and not _consent(
                "仅处理准备成功的文献？", interactive=interactive
            ):
                return 0
            model = read_json(args.model_config) if args.model_config else None
            request = planning_request(
                app,
                goal,
                prepared["documents"],
                model=model,
                max_cost=args.max_cost,
                max_calls=args.max_calls,
                planning_max_cost=args.planning_max_cost,
            )
            print(
                f"规划API：{request['model']['name']}；最多"
                f"{request['planning_budget']['max_calls']}次，估算上限"
                f"{request['planning_budget']['max_cost']} {request['model']['currency']}。"
            )
            if not args.allow_planning and not _consent(
                "同意向规划模型发送上述目标及文献元数据？", interactive=interactive
            ):
                raise ProcessingError("planning_authorization_required")
            checked = draft_task(
                app, request, authorization=app.authorize("plan", request)
            )
            task_file = Path(checked["task_file"])
        while True:
            print(checked["plan"])
            print(f"任务文件：{task_file}")
            fingerprint = app.binding("execute", checked["task"])
            print("计划指纹：" + fingerprint)
            if args.save_only:
                return 0
            if not interactive:
                if not args.execute:
                    print(
                        "已保存计划；使用 --task、--execute、--allow-remote 和 --confirm-plan 确认后执行。"
                    )
                    return 0
                if args.confirm_plan != fingerprint:
                    raise ProcessingError("reviewed_plan_fingerprint_required")
                if checked["task"]["mode"] != "local" and not args.allow_remote:
                    raise ProcessingError("extraction_authorization_required")
                break
            action = (
                input(
                    "按上述范围和预算发送论文并执行[e] / 编辑后重读[m] / 只保存[s] / 取消[c]："
                )
                .strip()
                .lower()
            )
            if action in {"s", "c", ""}:
                return 0
            if action == "m":
                input("请在编辑器修改上述文件，保存后按回车：")
                checked = app.validate_research_task(read_json(task_file))
                continue
            if action == "e":
                break
        task = checked["task"]
        if app.binding("execute", task) != fingerprint:
            raise ProcessingError("reviewed_plan_sources_changed")
        token = app.authorize("execute", task) if task["mode"] != "local" else None
        job = app.execute_research_task(task, authorization=token, background=False)
        print(f"{job['status']} · {job.get('run_directory', job['directory'])}")
        if job.get("usage"):
            print("科研调用用量：" + str(job["usage"]))
        return 0 if job["status"] in {"COMPLETED", "PREPARED", "PARTIAL"} else 1
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(
            "Research entry failed: " + ResearchApplication.error_code(exc),
            file=sys.stderr,
        )
        return 2
    finally:
        if app:
            app.close()


if __name__ == "__main__":
    raise SystemExit(main())
