from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from aletheia_nexus.acquire.discovery import CandidateUrlType, discover_full_text
from aletheia_nexus.acquire.fulltext import (
    AcquisitionStatus,
    ResolutionStatus,
    acquire_direct_pdf,
    resolve_full_text_route,
)


def _load_cases(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Corpus must be a JSON list")
    cases: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each corpus entry must be an object")
        cases.append({str(key): str(value) for key, value in item.items()})
    return cases


def _candidate_record(candidate) -> dict[str, object]:
    return {
        "url": candidate.url,
        "url_type": candidate.url_type.value,
        "access_type": candidate.access_type.value,
        "version": candidate.version.value,
        "host_type": candidate.host_type.value,
        "license": candidate.license,
        "source_name": candidate.source_name,
        "is_best": candidate.is_best,
        "provenance": [provider.value for provider in candidate.provenance],
    }


def _resolution_record(result) -> dict[str, object]:
    record: dict[str, object] = {
        "status": result.status.value,
        "page_type": result.page_type.value if result.page_type else None,
        "attempts": result.attempts,
        "elapsed_seconds": result.elapsed_seconds,
        "error": result.error,
        "derived_candidates": [
            {
                "candidate": _candidate_record(item.candidate),
                "parent_url": item.parent_url,
                "source_page_url": item.source_page_url,
                "method": item.method.value,
                "role_hint": item.role_hint.value,
                "evidence": list(item.evidence),
                "priority": item.priority,
            }
            for item in result.candidates
        ],
    }
    if result.page:
        record["page"] = {
            "requested_url": result.page.requested_url,
            "final_url": result.page.final_url,
            "http_status": result.page.http_status,
            "content_type": result.page.content_type,
            "size_bytes": result.page.size_bytes,
            "redirects": [
                {
                    "from_url": hop.from_url,
                    "status_code": hop.status_code,
                    "location": hop.location,
                    "to_url": hop.to_url,
                }
                for hop in result.page.redirects
            ],
            "is_pdf_response": result.page.is_pdf_response,
            "body_truncated": result.page.body_truncated,
        }
    if result.identity:
        record["identity"] = {
            "status": result.identity.status.value,
            "doi_match": result.identity.doi_match,
            "title_similarity": result.identity.title_similarity,
            "evidence": list(result.identity.evidence),
        }
    return record


def _acquisition_record(result) -> dict[str, object]:
    record: dict[str, object] = {
        "status": result.status.value,
        "error": result.error,
        "attempts": result.attempts,
        "elapsed_seconds": result.elapsed_seconds,
        "file_path": str(result.file_path) if result.file_path else None,
        "sidecar_path": str(result.sidecar_path) if result.sidecar_path else None,
    }
    if result.retrieved:
        record["retrieved"] = {
            "requested_url": result.retrieved.requested_url,
            "final_url": result.retrieved.final_url,
            "http_status": result.retrieved.http_status,
            "content_type": result.retrieved.content_type,
            "size_bytes": result.retrieved.size_bytes,
            "sha256": result.retrieved.sha256,
        }
    if result.pdf_validation:
        record["pdf_validation"] = {
            "valid_pdf": result.pdf_validation.valid_pdf,
            "magic_bytes_ok": result.pdf_validation.magic_bytes_ok,
            "parseable": result.pdf_validation.parseable,
            "page_count": result.pdf_validation.page_count,
            "encrypted": result.pdf_validation.encrypted,
            "warning": result.pdf_validation.warning,
        }
    if result.identity_validation:
        record["identity_validation"] = {
            "status": result.identity_validation.status.value,
            "document_role": result.identity_validation.document_role.value,
            "doi_match": result.identity_validation.doi_match,
            "title_similarity": result.identity_validation.title_similarity,
            "evidence": list(result.identity_validation.evidence),
        }
    return record


def _write_markdown(summary: dict[str, object], path: Path) -> None:
    rows = summary["papers"]
    lines = [
        "# CDI 10-paper route-resolution acceptance",
        "",
        f"Total elapsed: {summary['elapsed_seconds']:.2f} s",
        "",
        "| # | DOI | Publisher | Discovery | Routes resolved | Derived PDFs | Final |",
        "|---:|---|---|---:|---:|---:|---|",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    str(row["doi"]),
                    str(row["publisher"]),
                    str(row.get("discovery_candidate_count", 0)),
                    str(row.get("resolved_route_count", 0)),
                    str(row.get("derived_pdf_candidate_count", 0)),
                    str(row.get("final_status", "ERROR")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Status counts", ""])
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run real-network acceptance for Discovery + v0.5.1 Route Resolution "
            "+ v0.5.0 file validation on the fixed CDI corpus."
        )
    )
    parser.add_argument(
        "--corpus",
        default="benchmarks/cdi_acquisition_10.json",
    )
    parser.add_argument(
        "--output-dir",
        default="local_acceptance/cdi_10_route_resolution",
    )
    parser.add_argument("--max-routes", type=int, default=12)
    parser.add_argument("--max-file-candidates", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    unpaywall_email = os.environ.get("UNPAYWALL_EMAIL")
    openalex_api_key = os.environ.get("OPENALEX_API_KEY")
    cases = _load_cases(corpus_path)

    print(f"Corpus: {corpus_path}")
    print(f"Output: {output_root}")
    print(
        "Unpaywall: "
        + ("enabled" if unpaywall_email else "skipped (UNPAYWALL_EMAIL not set)")
    )
    print()

    started = time.perf_counter()
    papers: list[dict[str, object]] = []
    status_counts: dict[str, int] = {}

    for index, case in enumerate(cases, start=1):
        doi = case["doi"]
        title = case["title"]
        print("=" * 88)
        print(f"[{index}/{len(cases)}] {doi}")
        print(title)
        print(f"Publisher: {case['publisher']}")

        row: dict[str, object] = {
            **case,
            "providers": [],
            "discovery_candidates": [],
            "resolutions": [],
            "file_attempts": [],
        }

        try:
            discovery = discover_full_text(
                doi,
                unpaywall_email=unpaywall_email,
                openalex_api_key=openalex_api_key,
                max_attempts=2,
                backoff_base=0.5,
            )
        except Exception as exc:
            row["final_status"] = "DISCOVERY_EXCEPTION"
            row["error"] = f"{type(exc).__name__}: {exc}"
            papers.append(row)
            status_counts["DISCOVERY_EXCEPTION"] = (
                status_counts.get("DISCOVERY_EXCEPTION", 0) + 1
            )
            print(f"Discovery exception: {type(exc).__name__}: {exc}")
            continue

        row["providers"] = [
            {
                "provider": provider.provider.value,
                "status": provider.status.value,
                "candidate_count": len(provider.candidates),
                "attempts": provider.attempts,
                "elapsed_seconds": provider.elapsed_seconds,
                "error": provider.error,
            }
            for provider in discovery.providers
        ]
        row["discovery_candidates"] = [
            _candidate_record(candidate) for candidate in discovery.candidates
        ]
        row["discovery_candidate_count"] = len(discovery.candidates)

        file_candidates: list[tuple[object, str]] = []
        seen_file_urls: set[str] = set()
        resolved_route_count = 0
        resolution_statuses: dict[str, int] = {}

        def add_file_candidate(candidate, origin: str) -> None:
            if candidate.url in seen_file_urls:
                return
            seen_file_urls.add(candidate.url)
            file_candidates.append((candidate, origin))

        for candidate in discovery.candidates:
            if candidate.url_type == CandidateUrlType.PDF:
                add_file_candidate(candidate, "provider_pdf")

        route_candidates = [
            candidate
            for candidate in discovery.candidates
            if candidate.url_type != CandidateUrlType.PDF
        ][: args.max_routes]

        for route_index, candidate in enumerate(route_candidates, start=1):
            result = resolve_full_text_route(
                candidate,
                expected_title=title,
                max_attempts=1,
                timeout=args.timeout,
            )
            status = result.status.value
            resolution_statuses[status] = resolution_statuses.get(status, 0) + 1
            row["resolutions"].append(
                {
                    "source_candidate": _candidate_record(candidate),
                    "result": _resolution_record(result),
                }
            )
            print(
                f"  route[{route_index}] {candidate.url_type.value} "
                f"{candidate.host_type.value}: {status} -> "
                f"{len(result.candidates)} derived"
            )
            if result.status == ResolutionStatus.RESOLVED:
                resolved_route_count += 1
                for derived in result.candidates:
                    add_file_candidate(
                        derived.candidate,
                        f"derived:{derived.method.value}",
                    )

        row["resolution_status_counts"] = resolution_statuses
        row["resolved_route_count"] = resolved_route_count
        row["derived_pdf_candidate_count"] = len(
            [origin for _, origin in file_candidates if origin.startswith("derived:")]
        )
        row["combined_file_candidate_count"] = len(file_candidates)

        verified_source: str | None = None
        attempted_statuses: list[str] = []
        paper_dir = output_root / f"{index:02d}"

        for file_index, (candidate, origin) in enumerate(
            file_candidates[: args.max_file_candidates],
            start=1,
        ):
            result = acquire_direct_pdf(
                candidate,
                output_dir=paper_dir,
                expected_title=title,
                max_attempts=1,
                timeout=args.timeout,
            )
            attempted_statuses.append(result.status.value)
            row["file_attempts"].append(
                {
                    "origin": origin,
                    "candidate": _candidate_record(candidate),
                    "result": _acquisition_record(result),
                }
            )
            print(
                f"    file[{file_index}] {origin}: {result.status.value} "
                f"{candidate.url}"
            )
            if result.status == AcquisitionStatus.VERIFIED:
                verified_source = candidate.url
                break

        if verified_source:
            final_status = "VERIFIED"
        elif not file_candidates:
            final_status = "NO_FILE_CANDIDATE"
        elif attempted_statuses:
            final_status = " | ".join(attempted_statuses)
        else:
            final_status = "NO_ATTEMPT"

        row["verified_source"] = verified_source
        row["final_status"] = final_status
        status_counts[final_status] = status_counts.get(final_status, 0) + 1
        papers.append(row)
        print(f"Final: {final_status}")

    elapsed = time.perf_counter() - started
    summary: dict[str, object] = {
        "corpus": str(corpus_path),
        "paper_count": len(cases),
        "elapsed_seconds": elapsed,
        "unpaywall_enabled": bool(unpaywall_email),
        "openalex_api_key_configured": bool(openalex_api_key),
        "status_counts": status_counts,
        "papers": papers,
    }

    json_path = output_root / "summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path = output_root / "summary.md"
    _write_markdown(summary, md_path)

    print("=" * 88)
    print("BATCH COMPLETE")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print("Status counts:")
    for key, value in sorted(status_counts.items()):
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
