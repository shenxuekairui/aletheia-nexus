import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

from aletheia_nexus.acquire.fulltext import (
    FullTextAcquisitionStatus,
    acquire_full_text,
)

DEFAULT_CORPUS = Path("benchmarks/cdi_acquisition_10.json")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a benchmark corpus through v0.5.2 multi-route acquisition."
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("real_network_acceptance/v0.5.2-multiroute"),
    )
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--max-routes", type=int, default=16)
    parser.add_argument("--max-files", type=int, default=24)
    parser.add_argument("--max-route-depth", type=int, default=2)
    parser.add_argument("--max-expansions-per-page", type=int, default=4)
    parser.add_argument("--discovery-attempts", type=int, default=2)
    parser.add_argument("--route-attempts", type=int, default=1)
    parser.add_argument("--file-attempts", type=int, default=1)
    parser.add_argument(
        "--no-doi-fallback",
        action="store_true",
        help="Disable the final DOI resolver fallback for comparison runs.",
    )
    return parser.parse_args()


def _read_cases(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("benchmark corpus must contain a JSON list")
    required = {"id", "doi", "title", "publisher"}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"benchmark case {index} must be an object")
        missing = required.difference(item)
        if missing:
            raise ValueError(
                f"benchmark case {index} is missing required fields: {sorted(missing)}"
            )
    return payload


def _provider_record(provider_result) -> dict[str, object]:
    return {
        "provider": provider_result.provider.value,
        "status": provider_result.status.value,
        "attempts": provider_result.attempts,
        "elapsed_seconds": round(provider_result.elapsed_seconds, 4),
        "candidate_count": len(provider_result.candidates),
        "error": provider_result.error,
    }


def _route_record(attempt) -> dict[str, object]:
    result = attempt.result
    page = result.page
    return {
        "origin": attempt.origin.value,
        "depth": attempt.depth,
        "parent_url": attempt.parent_url,
        "expansion_method": attempt.expansion_method,
        "evidence": list(attempt.evidence),
        "input_url": attempt.candidate.url,
        "status": result.status.value,
        "network_attempts": result.attempts,
        "elapsed_seconds": round(result.elapsed_seconds, 4),
        "page_final_url": page.final_url if page else None,
        "page_type": result.page_type.value if result.page_type else None,
        "identity": result.identity.status.value if result.identity else None,
        "derived_count": len(result.candidates),
        "error": result.error,
    }


def _file_record(attempt) -> dict[str, object]:
    result = attempt.result
    retrieved = result.retrieved
    return {
        "origin": attempt.origin.value,
        "input_url": attempt.candidate.url,
        "status": result.status.value,
        "network_attempts": result.attempts,
        "elapsed_seconds": round(result.elapsed_seconds, 4),
        "final_url": retrieved.final_url if retrieved else None,
        "size_bytes": retrieved.size_bytes if retrieved else None,
        "derivation_method": (
            attempt.derivation_method.value if attempt.derivation_method else None
        ),
        "role_hint": attempt.role_hint.value,
        "parent_url": attempt.parent_url,
        "evidence": list(attempt.evidence),
        "error": result.error,
    }


def _case_record(
    case: dict[str, str], result, elapsed_seconds: float
) -> dict[str, object]:
    verified = result.verified_result
    verified_url = None
    if verified is not None and verified.retrieved is not None:
        verified_url = verified.retrieved.final_url

    return {
        "id": case["id"],
        "doi": case["doi"],
        "title": case["title"],
        "publisher": case["publisher"],
        "route_goal": case.get("route_goal"),
        "status": result.status.value,
        "verified_url": verified_url,
        "elapsed_seconds": round(elapsed_seconds, 4),
        "discovery_candidate_count": len(result.discovery.candidates),
        "providers": [_provider_record(item) for item in result.discovery.providers],
        "route_attempt_count": len(result.route_attempts),
        "page_route_attempt_count": result.page_route_attempts,
        "file_attempt_count": len(result.file_attempts),
        "route_expansions_enqueued": result.route_expansions_enqueued,
        "max_route_depth_reached": result.max_route_depth_reached,
        "duplicate_file_candidates_skipped": result.duplicate_file_candidates_skipped,
        "duplicate_route_candidates_skipped": result.duplicate_route_candidates_skipped,
        "supplement_candidates_skipped": result.supplement_candidates_skipped,
        "routes": [_route_record(attempt) for attempt in result.route_attempts],
        "files": [_file_record(attempt) for attempt in result.file_attempts],
        "message": result.message,
    }


def _render_markdown(summary: dict[str, object]) -> str:
    metrics = summary["metrics"]
    corpus_name = Path(str(summary["corpus"])).stem
    lines = [
        f"# v0.5.2 multi-route acceptance — {corpus_name}",
        "",
        f"- Corpus: `{summary['corpus']}`",
        f"- Elapsed: {summary['elapsed_seconds']:.2f} s",
        f"- DOI resolver fallback: {summary['doi_resolver_fallback']}",
        f"- VERIFIED: {metrics['verified_count']} / {metrics['paper_count']}",
        f"- Page route attempts: {metrics['page_route_attempts']}",
        f"- File attempts: {metrics['file_attempts']}",
        f"- Route expansions enqueued: {metrics['route_expansions_enqueued']}",
        f"- Maximum route depth reached: {metrics['max_route_depth_reached']}",
        f"- Duplicate file candidates skipped: {metrics['duplicate_file_candidates_skipped']}",
        f"- Duplicate route candidates skipped: {metrics['duplicate_route_candidates_skipped']}",
        f"- Supplement candidates skipped: {metrics['supplement_candidates_skipped']}",
        "",
        "## Paper outcomes",
        "",
        "| DOI | Final | Routes | Files | Expansions | Elapsed | Verified URL |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]

    for paper in summary["papers"]:
        url = paper["verified_url"] or ""
        lines.append(
            "| {doi} | {status} | {routes} | {files} | {expansions} | "
            "{elapsed:.2f}s | {url} |".format(
                doi=paper["doi"],
                status=paper["status"],
                routes=paper["page_route_attempt_count"],
                files=paper["file_attempt_count"],
                expansions=paper["route_expansions_enqueued"],
                elapsed=paper["elapsed_seconds"],
                url=url,
            )
        )

    lines.extend(["", "## Final status counts", ""])
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"- `{status}`: {count}")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This is a live-network acceptance run, not a deterministic CI test. ",
            "Third-party access behavior can change by time, IP, and request policy. ",
            "Stable release criteria should therefore combine verified acquisition, ",
            "explicit failure semantics, bounded request cost, and zero false VERIFIED ",
            "outcomes.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    cases = _read_cases(args.corpus)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    download_root = args.output_dir / "files"
    download_root.mkdir(parents=True, exist_ok=True)

    unpaywall_email = os.getenv("UNPAYWALL_EMAIL") or None
    openalex_api_key = os.getenv("OPENALEX_API_KEY") or None
    use_doi_fallback = not args.no_doi_fallback

    print(f"Corpus: {args.corpus}")
    print(f"Output: {args.output_dir}")
    print(f"Unpaywall: {'enabled' if unpaywall_email else 'skipped'}")
    print(f"DOI resolver fallback: {use_doi_fallback}")

    started_at = time.perf_counter()
    papers: list[dict[str, object]] = []

    for index, case in enumerate(cases, start=1):
        print("=" * 88)
        print(f"[{index}/{len(cases)}] {case['doi']}")
        print(case["title"])
        print(f"Publisher: {case['publisher']}")

        case_started = time.perf_counter()
        result = acquire_full_text(
            case["doi"],
            output_dir=download_root / case["id"],
            expected_title=case["title"],
            unpaywall_email=unpaywall_email,
            openalex_api_key=openalex_api_key,
            auto_metadata=False,
            max_route_attempts=args.max_routes,
            max_file_attempts=args.max_files,
            max_route_depth=args.max_route_depth,
            max_route_expansions_per_page=args.max_expansions_per_page,
            discovery_max_attempts=args.discovery_attempts,
            max_attempts_per_route=args.route_attempts,
            max_attempts_per_file=args.file_attempts,
            timeout=args.timeout,
            use_doi_resolver_fallback=use_doi_fallback,
        )
        elapsed = time.perf_counter() - case_started
        record = _case_record(case, result, elapsed)
        papers.append(record)

        print(
            "Final: {status} | page routes={routes} | files={files} | "
            "expansions={expansions} | {elapsed:.2f}s".format(
                status=result.status.value,
                routes=result.page_route_attempts,
                files=len(result.file_attempts),
                expansions=result.route_expansions_enqueued,
                elapsed=elapsed,
            )
        )
        for route in record["routes"]:
            print(
                "  route {origin} depth={depth}: {status} -> {count} files | {url}".format(
                    origin=route["origin"],
                    depth=route["depth"],
                    status=route["status"],
                    count=route["derived_count"],
                    url=route["input_url"],
                )
            )
        for file_result in record["files"]:
            print(
                "  file {origin}: {status} | {url}".format(
                    origin=file_result["origin"],
                    status=file_result["status"],
                    url=file_result["input_url"],
                )
            )

    elapsed_seconds = time.perf_counter() - started_at
    status_counts = Counter(str(paper["status"]) for paper in papers)
    verified_count = status_counts.get(FullTextAcquisitionStatus.VERIFIED.value, 0)

    metrics = {
        "paper_count": len(papers),
        "verified_count": verified_count,
        "page_route_attempts": sum(
            int(paper["page_route_attempt_count"]) for paper in papers
        ),
        "file_attempts": sum(int(paper["file_attempt_count"]) for paper in papers),
        "route_expansions_enqueued": sum(
            int(paper["route_expansions_enqueued"]) for paper in papers
        ),
        "max_route_depth_reached": max(
            (int(paper["max_route_depth_reached"]) for paper in papers),
            default=0,
        ),
        "duplicate_file_candidates_skipped": sum(
            int(paper["duplicate_file_candidates_skipped"]) for paper in papers
        ),
        "duplicate_route_candidates_skipped": sum(
            int(paper["duplicate_route_candidates_skipped"]) for paper in papers
        ),
        "supplement_candidates_skipped": sum(
            int(paper["supplement_candidates_skipped"]) for paper in papers
        ),
    }

    summary = {
        "schema": "aletheia-nexus/multiroute-acceptance/v1",
        "corpus": str(args.corpus),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "doi_resolver_fallback": use_doi_fallback,
        "unpaywall_enabled": bool(unpaywall_email),
        "settings": {
            "timeout": args.timeout,
            "max_routes": args.max_routes,
            "max_files": args.max_files,
            "max_route_depth": args.max_route_depth,
            "max_expansions_per_page": args.max_expansions_per_page,
            "discovery_attempts": args.discovery_attempts,
            "route_attempts": args.route_attempts,
            "file_attempts": args.file_attempts,
        },
        "metrics": metrics,
        "status_counts": dict(sorted(status_counts.items())),
        "papers": papers,
    }

    json_path = args.output_dir / "summary.json"
    md_path = args.output_dir / "summary.md"
    json_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    print("=" * 88)
    print("BATCH COMPLETE")
    print(f"Elapsed: {elapsed_seconds:.2f}s")
    print(f"VERIFIED: {verified_count}/{len(papers)}")
    print(f"Page route attempts: {metrics['page_route_attempts']}")
    print(f"File attempts: {metrics['file_attempts']}")
    print(f"Route expansions: {metrics['route_expansions_enqueued']}")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
