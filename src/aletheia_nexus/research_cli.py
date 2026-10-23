"""Commands for a local research corpus and selected evidence bundles."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from aletheia_nexus.content.batch import parse_batch
from aletheia_nexus.content.corpus import load_corpus, search_corpus
from aletheia_nexus.content.evidence import (
    build_evidence_pack,
    evidence_markdown,
    select_hits,
)
from aletheia_nexus.content.export import write_ai_export
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.parsing_cli import (
    add_parsing_options,
    parser_config,
    parsing_backend,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def import_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus import",
        description="Register a researcher-supplied local PDF. Identity is declared, not automatically verified.",
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--doi")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--role", choices=("ARTICLE", "SUPPLEMENT"), default="ARTICLE")
    parser.add_argument(
        "--parent", type=Path, help="Main article PDF, required for a supplement."
    )
    parser.add_argument("--parent-sidecar", type=Path)
    args = parser.parse_args(argv)
    try:
        pdf = register_local_pdf(
            args.pdf,
            output_dir=args.output_dir,
            title=args.title,
            doi=args.doi,
            role=args.role,
            parent_pdf=args.parent,
            parent_sidecar=args.parent_sidecar,
        )
    except (OSError, ValueError) as exc:
        print(f"Could not register PDF: {exc}", file=sys.stderr)
        return 2
    print(f"REGISTERED (identity: local declaration): {pdf}")
    return 0


def batch_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus parse-batch",
        description="Parse local PDFs; resume unchanged completed artifacts and report partial/failed files.",
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--retry-partial", action="store_true")
    add_parsing_options(parser)
    args = parser.parse_args(argv)
    try:
        engine = parsing_backend(args)
        result = parse_batch(
            args.root,
            config=parser_config(args),
            backend=engine,
            resume=not args.no_resume,
            retry_partial=args.retry_partial,
            report_path=args.report,
            progress=lambda row: print(
                f"{row['pdf']}: {row['status']}"
                + (" (resumed)" if row.get("resumed") else ""),
                flush=True,
            ),
        )
    except KeyboardInterrupt:
        print(
            "Interrupted. Completed artifacts and the coverage report are saved; rerun to resume.",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError) as exc:
        print(f"Could not parse corpus: {exc}", file=sys.stderr)
        return 2
    print(_json(result["counts"]).strip())
    print(f"Report: {args.report or args.root / 'parse-report.json'}")
    return 0 if result["complete"] else 6


def search_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus search",
        description="Search local paragraphs, observed table/figure context and bounded nearby text. Default AND requires all terms in one evidence unit; quotes preserve a phrase. Context is not an interpreted experimental relationship.",
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("query")
    parser.add_argument("--mode", choices=("and", "or"), default="and")
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--role", choices=("ARTICLE", "SUPPLEMENT"))
    parser.add_argument("--section-type")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        help="Save numbered results for reproducible selection/export.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--verify-sources",
        action="store_true",
        help="Corpus sources are always checked.",
    )
    args = parser.parse_args(argv)
    try:
        report = search_corpus(
            args.root,
            args.query,
            mode=args.mode,
            exact=args.exact,
            limit=args.limit,
            role=args.role,
            section_type=args.section_type,
        )
        if args.output:
            report["corpus_root"] = os.path.relpath(
                args.root.resolve(), args.output.resolve().parent
            )
            write_ai_export(args.output, _json(report), overwrite=args.overwrite)
    except (OSError, ValueError) as exc:
        print(f"Could not search corpus: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(_json(report), end="")
    else:
        for hit in report["hits"]:
            source = hit["source"]
            print(
                f"{hit['number']}. {source.get('title') or source.get('doi') or hit['pdf']} [{source.get('document_role', 'ARTICLE')}] PDF pages {hit['pages']}; {hit['status']}"
                + ("; uncertain — check original PDF" if hit["uncertain"] else "")
            )
            print(
                f"   {hit['id']}\n   {hit['text']}\n   Source: {args.root / hit['pdf']}"
            )
            print(f"   Reading: {hit.get('reading_role', 'primary')}")
            if hit["kind"] in {"table", "figure", "context"}:
                print(
                    "   Observed layout context; experimental relationships are not verified."
                )
            for row in hit.get("matching_rows", []):
                print(f"   Matching observed row {row['row']}: {row['text']}")
            for location in hit.get("review_locations", []):
                for warning in location.get("local_warnings", []):
                    print(
                        f"   PDF page {location['page']} — {warning['code']}: {warning.get('detail', '')}"
                    )
                for difference in location.get("reading_differences", []):
                    if (
                        difference.get("status")
                        == "partial-reading-needs-source-alignment"
                    ):
                        print(
                            f"   PDF page {location['page']} partial alternative: {difference['alternative_text']!r}; align at the source, without treating surrounding prose as missing."
                        )
                    for change in difference["changes"]:
                        print(
                            f"   PDF page {location['page']} unresolved reading: {change['primary']!r} / alternative {change['alternative']!r}"
                        )
                if location.get("alternative_block_ids"):
                    print(
                        f"   Alternatives at {location['id']}: {', '.join(location['alternative_block_ids'])}; retain them in the selected evidence export."
                    )
        coverage = report["coverage"]
        print(
            f"Hits: {report['returned_hits']}/{report['total_hits']}; documents searched in scope: {report['search_scope']['searched_documents']}/{coverage['searched_documents']}; completed documents in corpus: {coverage['completed']}; partial: {coverage['partial']}; unsearched: {len(coverage['unsearched'])}; duplicates: {len(coverage['duplicates'])}"
        )
        if not coverage["complete"]:
            print("Incomplete coverage: absence of a hit is not evidence of absence.")
            print(
                _json(
                    {
                        "unsearched": coverage["unsearched"],
                        "partial_documents": [
                            {
                                "artifact": item["artifact"],
                                "status": item["status"],
                                "warning_codes": sorted(
                                    {w["code"] for w in item["warnings"]}
                                ),
                                "page_coverage": item["quality"]["page_coverage"],
                            }
                            for item in coverage["partial_documents"]
                        ],
                    }
                ).strip()
            )
    return 0


def export_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus export",
        description="Export a corpus or selected search evidence with source context and a coverage manifest.",
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument(
        "--select", help="Comma-separated result numbers or stable IDs from --results."
    )
    parser.add_argument(
        "--context-pages",
        type=int,
        default=1,
        help="Include this many PDF pages before/after each hit.",
    )
    parser.add_argument(
        "--context-page",
        action="append",
        default=[],
        metavar="RESULT=PAGE",
        help="Add a condition page for a selected result; repeat as needed.",
    )
    parser.add_argument("--budget-chars", type=int)
    parser.add_argument(
        "--format", choices=("markdown", "json", "jsonl"), default="markdown"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show size, scope and omissions without writing.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.results) != bool(args.select):
        parser.error("--results and --select must be used together")
    if not args.output and not args.preview:
        parser.error("--output is required unless --preview is used")
    try:
        report = (
            json.loads(args.results.read_text(encoding="utf-8"))
            if args.results
            else None
        )
        extras = {}
        for item in args.context_page:
            key, page = item.rsplit("=", 1)
            extras.setdefault(key, []).append(int(page))
        pack = build_evidence_pack(
            args.root,
            report=report,
            selectors=[v.strip() for v in args.select.split(",")]
            if args.select
            else None,
            context_pages=args.context_pages,
            extra_pages=extras,
            max_characters=args.budget_chars,
        )
        if args.output:
            pack["corpus_root"] = os.path.relpath(
                args.root.resolve(), args.output.resolve().parent
            )
        if args.format == "markdown":
            payload = evidence_markdown(pack)
        elif args.format == "jsonl":
            payload = (
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in [
                        {
                            "record_type": "manifest",
                            **{k: v for k, v in pack.items() if k != "included"},
                        },
                        *[
                            {"record_type": "document", **item}
                            for item in pack["included"]
                        ],
                    ]
                )
                + "\n"
            )
        else:
            payload = _json(pack)
        print(
            _json(
                {
                    "scope": pack["scope"],
                    "size": pack["size"],
                    "serialized_bytes": len(payload.encode("utf-8")),
                    "included_documents": len(pack["included"]),
                    "skipped": pack["skipped"],
                    "coverage": pack["coverage"],
                }
            ).strip()
        )
        if not args.preview:
            if (
                args.output.is_file()
                and args.output.read_text(encoding="utf-8") == payload
            ):
                print(f"Unchanged export (resumed): {args.output}")
            else:
                write_ai_export(args.output, payload, overwrite=args.overwrite)
                print(f"Exported: {args.output}")
    except (OSError, ValueError) as exc:
        print(f"Could not export evidence: {exc}", file=sys.stderr)
        return 7
    return 0


def open_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus open-source",
        description="Resolve a result to its verified local PDF and 1-based page. Optionally launch the system reader.",
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("selection")
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.results.read_text(encoding="utf-8"))
        hit = select_hits(report, [args.selection])[0]
        corpus = load_corpus(args.root)
        pack = build_evidence_pack(
            corpus, report=report, selectors=[args.selection], context_pages=0
        )
        item = pack["included"][0]
        pdf = corpus.root / item["pdf"]
        print(
            f"PDF: {pdf}\nPDF pages (1-based): {item['pages_requested']}\nResult: {hit['id']}"
        )
        if args.launch:
            if sys.platform == "win32":
                os.startfile(pdf)
            else:
                subprocess.Popen(
                    ["open" if sys.platform == "darwin" else "xdg-open", str(pdf)]
                )
            print(
                "Opened in the system reader; use the PDF page number above if it does not jump to the page."
            )
    except (OSError, ValueError) as exc:
        print(f"Could not locate source: {exc}", file=sys.stderr)
        return 7
    return 0
