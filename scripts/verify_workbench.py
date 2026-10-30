"""Reproducible isolated workbench acceptance; remote operations are opt-in.

python scripts/verify_workbench.py --output NEW_DIRECTORY
Append --remote-titles / --remote-research only with explicit API permission.
Fixtures are synthetic, not scientific quality benchmarks or verified acquisitions.
"""

from __future__ import annotations

import argparse
import json
import runpy
from pathlib import Path

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.ui_cli import create_context
from aletheia_nexus.workbench.settings import atomic_json


def run(output: Path, *, remote_titles=False, remote_research=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    incoming = output / "incoming"
    incoming.mkdir()
    write_pdf = runpy.run_path(
        str(Path(__file__).with_name("generate_v07_fixtures.py"))
    )["_write_pdf"]
    context = create_context(output / "library", output / "workspace")
    library = context.library
    report = {
        "synthetic_materials": True,
        "scientific_quality_acceptance": False,
        "checks": {},
        "remote_titles_authorized": remote_titles,
        "remote_research_authorized": remote_research,
    }
    try:
        titles = [
            "Highly accurate protein structure prediction with AlphaFold",
            "Attention Is All You Need",
            "Selective reduction of CO2 on Cu(I): workbench synthetic fixture",
        ]
        ids, originals = [], {}
        for n, title in enumerate(titles, 1):
            pdf = incoming / f"paper-{n}.pdf"
            write_pdf(
                pdf,
                [
                    [
                        (50, 730, 15, "SYNTHETIC WORKBENCH ACCEPTANCE FIXTURE"),
                        (50, 690, 11, f"Sample {n}: measured at 25 C for 2 h."),
                        (
                            50,
                            660,
                            11,
                            "No actual scientific finding is asserted by this fixture.",
                        ),
                    ]
                ],
                title=title,
            )
            row = library.import_pdf(
                pdf, title=title, folder="羧酸还原", tags=["验收", "待阅读"]
            )
            ids.append(row["id"])
            library.update_metadata(row["id"], year=2026, journal="Fixture Journal")
            si = incoming / f"paper-{n}__SI-01.pdf"
            write_pdf(
                si,
                [
                    [
                        (50, 730, 15, f"SUPPLEMENT TO SYNTHETIC FIXTURE {n}"),
                        (50, 690, 11, "A control sample was measured for 1 h."),
                    ]
                ],
                title=f"Synthetic supplement {n}",
            )
            registered = register_local_pdf(
                si,
                output_dir=Path(row["pdf_path"]).parent / "SI",
                title=f"Supplement {n}",
                role="SUPPLEMENT",
                parent_pdf=row["pdf_path"],
            )
            library.register_attachment(row["pdf_path"], registered)
            originals[row["id"]] = {
                "pdf": sha256_file(Path(row["pdf_path"])),
                "sidecar": sha256_file(Path(row["sidecar_path"])),
                "si": sha256_file(registered),
            }
        assert len(library.scan()["items"]) == 3
        assert len(list((output / "library" / "羧酸还原").glob("*.pdf"))) == 3
        assert len(list((output / "library" / "羧酸还原" / "SI").glob("*.pdf"))) == 3
        report["checks"]["category_shared_si"] = True
        library.set_selection(ids)
        library.save_collection("验收固定集合", ids)
        library.save_filter(
            "待阅读验收", {"tags": ["验收", "待阅读"], "tag_mode": "AND"}
        )
        view = {
            "columns": [
                "title",
                "title_zh",
                "first_author",
                "journal",
                "tags",
                "si_count",
                "parse_status",
            ],
            "column_state": [{"colId": "title_zh", "width": 321, "sort": "asc"}],
            "title_mode": "bilingual",
        }
        library.save_view("验收自定义视图", view)
        report["checks"]["selection_collection_filter_view"] = True
        if remote_titles:
            # Existing project rates, explicitly recorded estimates, not a bill.
            translated = context.translation.translate(
                ids,
                {"max_calls": 1, "max_cost": 0.2, "max_output_tokens": 1024},
                consent=True,
            )
            report["translation"] = translated
            assert translated["status"] == "COMPLETED", translated
            cached = context.translation.translate(ids)
            assert not cached["calls"]
            report["checks"]["real_translation_and_zero_call_cache"] = True
        else:
            for paper_id, title in zip(
                ids,
                ("蛋白质结构预测验收", "注意力模型验收", "Cu(I)上CO2选择性还原验收"),
                strict=True,
            ):
                context.translation.edit(paper_id, title, confirmed=True)
        parsed = context.research.parse(ids)
        assert all(row["status"] == "PARSED" for row in parsed["items"]), parsed
        report["parse"] = parsed
        query = context.research.search("measured", ids, include_si=True, limit=2)
        assert query["total_hits"] >= 6
        assert len(query["hits"]) == 2
        report["search"] = query
        report["evidence_export"] = context.research.export_evidence(query["hits"])
        report["checks"]["parse_search_evidence"] = True
        model = {
            "name": "deepseek-flash",
            "reasoning_effort": "none",
            "timeout_seconds": 90,
            "max_retries": 0,
            "input_cost_per_million": 2,
            "output_cost_per_million": 8,
            "currency": "CNY",
        }
        task = context.research.local_plan(
            "Read the synthetic fixture only; report the stated measurement temperature, not a scientific conclusion.",
            ids[:1],
            fields=[
                {
                    "id": "temperature",
                    "type": "string",
                    "description": "Stated measurement temperature in the synthetic fixture",
                }
            ],
            mode="parsed" if remote_research else "local",
            model=model,
            budget={
                "max_calls": 1,
                "max_cost": 0.2,
                "max_output_tokens": 2048,
                "max_review_rounds": 0,
                "max_repair_rounds": 0,
                "max_supplement_rounds": 0,
            },
        )
        artifact_hashes = {
            v["document"]["artifact"]: sha256_file(Path(v["document"]["artifact"]))
            for material in context.research.versions(ids[0], include_si=True)
            for v in material["versions"]
        }
        preview = library.preview_rename(
            ids, "{year}-{journal}-{title_zh}", folder="已整理/羧酸还原"
        )
        report["rename_preview"] = preview
        assert preview["executable"] == 3, preview
        operation = library.execute_rename(preview)
        assert operation["status"] == "COMPLETED", operation
        report["file_operation"] = operation["id"]
        for paper_id in ids:
            row = library.get(paper_id)
            assert (
                Path(row["pdf_path"]).parent
                == output / "library" / "已整理" / "羧酸还原"
            )
            assert sha256_file(Path(row["pdf_path"])) == originals[paper_id]["pdf"]
            assert (
                sha256_file(Path(row["sidecar_path"])) == originals[paper_id]["sidecar"]
            )
            assert row["si_count"] == 1
            si = Path(row["attachments"][0]["path"])
            assert si.parent == Path(row["pdf_path"]).parent / "SI"
            assert si.stem.startswith(Path(row["pdf_path"]).stem + "__SI-")
            assert sha256_file(si) == originals[paper_id]["si"]
        for path, fingerprint in artifact_hashes.items():
            assert sha256_file(Path(path)) == fingerprint
        report["checks"]["actual_chinese_rename_move_immutable_evidence"] = True
        execution = context.research.execute(task, consent=remote_research)
        report["execution"] = execution
        assert execution["status"] in {"PREPARED", "COMPLETED", "PARTIAL"}, execution
        report["checks"]["frozen_task_runs_after_move"] = True
        if remote_research:
            results = context.research.results()
            assert results, execution
            report["research_export"] = context.research.export(
                [results[0]["path"]], name="验收结果"
            )
        # Reopen every persistent application object without changing sources.
        context.research.close()
        context.jobs.close(wait=True)
        context = create_context(output / "library", output / "workspace")
        assert context.library.selection() == ids
        assert context.library.views()["验收自定义视图"] == view
        assert context.library.collections()["验收固定集合"] == ids
        assert context.research.search("measured", ids)["total_hits"] >= 6
        report["checks"]["restart_persistence"] = True
        report["status"] = "PASSED"
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2500]}
        raise
    finally:
        atomic_json(output / "acceptance.json", report)
        context.jobs.close(wait=True)
        context.research.close()
    return report


def resume_delivery(output: Path):
    """Finish local delivery after a failure; never issue an API request."""
    report_path = output.resolve() / "acceptance.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("checks", {}).get("frozen_task_runs_after_move"):
        raise ValueError("This receipt has not reached the local delivery boundary")
    previous = output / "acceptance.before-recovery.json"
    if not previous.exists():
        atomic_json(previous, report)
    context = create_context(output / "library", output / "workspace")
    try:
        rows = context.research.results()
        if report.get("remote_research_authorized"):
            if not rows:
                raise ValueError(
                    "No saved research results; do not retry remote calls implicitly"
                )
            report["research_export"] = context.research.export(
                [rows[0]["path"]], name="验收结果"
            )
        ids = context.library.selection()
        assert len(ids) == 3
        assert (
            context.library.views()["验收自定义视图"]["column_state"][0]["width"] == 321
        )
        assert context.library.collections()["验收固定集合"] == ids
        assert context.research.search("measured", ids)["total_hits"] >= 6
        report["checks"]["restart_persistence"] = True
        report["status"] = "PASSED"
        report["recovery"] = {
            "previous_failure": report.pop("error", None),
            "remote_calls": 0,
            "note": "Saved model response retained; delivery resumed locally",
        }
        atomic_json(report_path, report)
    finally:
        context.jobs.close(wait=True)
        context.research.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--remote-titles", action="store_true")
    parser.add_argument("--remote-research", action="store_true")
    parser.add_argument(
        "--resume-delivery",
        action="store_true",
        help="仅恢复已有结果的本地导出和重启验证，不调用模型",
    )
    arguments = parser.parse_args()
    receipt = (
        resume_delivery(arguments.output)
        if arguments.resume_delivery
        else run(
            arguments.output,
            remote_titles=arguments.remote_titles,
            remote_research=arguments.remote_research,
        )
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "checks": receipt["checks"],
                "report": str(arguments.output.resolve() / "acceptance.json"),
            },
            ensure_ascii=False,
        )
    )
