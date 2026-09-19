import argparse
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserSession,
    ElsevierAccessConfig,
    MaximizedAcquisitionStatus,
    acquire_full_text_maximized,
)
from aletheia_nexus.acquire.access.security import redact_url_for_record
from aletheia_nexus.core.identifiers.doi import normalize_doi

DEFAULT_BENCHMARKS = (
    Path("benchmarks/cdi_acquisition_10.json"),
    Path("benchmarks/seawater_desalination_10.json"),
)


def _package_version() -> str:
    try:
        return version("aletheia-nexus")
    except PackageNotFoundError:
        return "dev"


def _report_payload(
    *,
    records: list[dict[str, object]],
    benchmark_paths: list[Path],
    entitled_benchmark_paths: list[Path],
    config: BrowserAccessConfig,
    base_verified: int,
    verified: int,
    entitled_total: int,
    entitled_verified: int,
    elsevier_enabled: bool,
    elsevier_recovered: int,
    browser_recovered: int,
    interaction_cases: int,
    entitled_controls: int,
    entitled_verified: int,
    final_statuses: Counter[str],
    challenge_kinds: Counter[str],
) -> dict[str, object]:
    return {
        "schema": "aletheia-nexus/v0.6-access-acceptance/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aletheia_nexus_version": _package_version(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.system(),
            "platform_release": platform.release(),
        },
        "corpus": {
            "stress_benchmarks": [str(path) for path in benchmark_paths],
            "entitled_positive_control_benchmarks": [
                str(path) for path in entitled_benchmark_paths
            ],
            "case_count": len(records),
            "entitled_positive_control_count": entitled_total,
        },
        "official_api": {
            "elsevier_enabled": elsevier_enabled,
        },
        "browser": {
            "profile_name": config.profile_name,
            "channel": config.channel,
            "headless": config.headless,
            "interactive": config.interactive,
            "max_source_routes": config.max_source_routes,
            "max_pdf_candidates": config.max_pdf_candidates,
        },
        "summary": {
            "v0.5_verified": base_verified,
            "v0.6_verified": verified,
            "entitled_positive_controls_verified": entitled_verified,
            "entitled_positive_controls_total": entitled_total,
            "entitled_positive_controls_passed": (
                entitled_total > 0 and entitled_verified == entitled_total
            ),
            "elsevier_recovered": elsevier_recovered,
            "browser_recovered": browser_recovered,
            "interaction_cases": interaction_cases,
            "entitled_controls": entitled_controls,
            "entitled_verified": entitled_verified,
            "entitled_failures": entitled_controls - entitled_verified,
            "final_statuses": dict(sorted(final_statuses.items())),
            "challenge_kinds": dict(sorted(challenge_kinds.items())),
        },
        "records": records,
    }


def _write_report(
    path: Path,
    *,
    records: list[dict[str, object]],
    benchmark_paths: list[Path],
    entitled_benchmark_paths: list[Path],
    config: BrowserAccessConfig,
    base_verified: int,
    verified: int,
    entitled_total: int,
    entitled_verified: int,
    elsevier_enabled: bool,
    elsevier_recovered: int,
    browser_recovered: int,
    interaction_cases: int,
    entitled_controls: int,
    entitled_verified: int,
    final_statuses: Counter[str],
    challenge_kinds: Counter[str],
) -> None:
    payload = _report_payload(
        records=records,
        benchmark_paths=benchmark_paths,
        entitled_benchmark_paths=entitled_benchmark_paths,
        config=config,
        base_verified=base_verified,
        verified=verified,
        entitled_total=entitled_total,
        entitled_verified=entitled_verified,
        elsevier_enabled=elsevier_enabled,
        elsevier_recovered=elsevier_recovered,
        browser_recovered=browser_recovered,
        interaction_cases=interaction_cases,
        entitled_controls=entitled_controls,
        entitled_verified=entitled_verified,
        final_statuses=final_statuses,
        challenge_kinds=challenge_kinds,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_cases(
    paths: list[Path],
    dois: list[str],
    entitled_dois: list[str],
) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    by_doi: dict[str, dict[str, object]] = {}

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Benchmark must contain a JSON list: {path}")
        for item in payload:
            doi = normalize_doi(str(item["doi"]))
            if doi in by_doi:
                continue
            case: dict[str, object] = {
                "doi": doi,
                "title": str(item.get("title") or "").strip() or None,
                "id": str(item.get("id") or doi),
                "entitled_control": False,
            }
            by_doi[doi] = case
            cases.append(case)

    for doi in dois:
        value = normalize_doi(doi)
        if value not in by_doi:
            case = {
                "doi": value,
                "title": None,
                "id": value,
                "entitled_control": False,
            }
            by_doi[value] = case
            cases.append(case)

    for doi in entitled_dois:
        value = normalize_doi(doi)
        case = by_doi.get(value)
        if case is None:
            case = {
                "doi": value,
                "title": None,
                "id": value,
                "entitled_control": True,
            }
            by_doi[value] = case
            cases.append(case)
        else:
            case["entitled_control"] = True

    return cases


def _interaction_notice(challenge, url: str) -> None:
    safe_url = redact_url_for_record(url)
    print()
    print("USER INTERACTION REQUIRED")
    print(f"Challenge: {challenge.kind.value}")
    print(f"Browser:   {safe_url}")
    print(
        "Complete the legitimate login / institutional SSO / MFA / CAPTCHA "
        "in the opened browser. AN will continue automatically."
    )
    print()


def _error_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(":", 1)[0][:120]


def _serialize(result) -> dict[str, object]:
    browser_attempts = []
    for attempt in result.browser_attempts:
        browser_attempts.append(
            {
                "source_url": redact_url_for_record(attempt.source_url),
                "final_url": redact_url_for_record(attempt.final_url),
                "status": attempt.status.value,
                "interaction_used": attempt.interaction_used,
                "challenges": [
                    {
                        "kind": report.kind.value,
                        "evidence": list(report.evidence),
                    }
                    for report in attempt.challenge_history
                ],
                "file_attempts": [
                    {
                        "url": redact_url_for_record(file_attempt.candidate.url),
                        "method": file_attempt.method,
                        "status": (
                            file_attempt.result.status.value
                            if file_attempt.result is not None
                            else None
                        ),
                        "error_type": _error_type(file_attempt.error),
                    }
                    for file_attempt in attempt.file_attempts
                ],
                "error_type": _error_type(attempt.error),
                "elapsed_seconds": attempt.elapsed_seconds,
            }
        )

    return {
        "doi": result.doi,
        "status": result.status.value,
        "base_status": result.base_result.status.value,
        "verified_path": (
            str(result.verified_path) if result.verified_path is not None else None
        ),
        "elsevier_attempt": (
            {
                "status": result.elsevier_attempt.status.value,
                "http_status": result.elsevier_attempt.http_status,
                "credential_modes": list(result.elsevier_attempt.credential_modes),
                "error_type": _error_type(result.elsevier_attempt.error),
            }
            if result.elsevier_attempt is not None
            else None
        ),
        "browser_attempts": browser_attempts,
        "elapsed_seconds": result.elapsed_seconds,
        "message": result.message,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed v0.6 authenticated-access acceptance corpus."
    )
    parser.add_argument(
        "--benchmark",
        action="append",
        type=Path,
        default=[],
        help="JSON benchmark path. Repeat to combine corpora.",
    )
    parser.add_argument(
        "--entitled-benchmark",
        action="append",
        type=Path,
        default=[],
        help=(
            "JSON benchmark containing papers manually confirmed downloadable "
            "with the same account/institution environment. Repeat as needed."
        ),
    )
    parser.add_argument(
        "--require-entitled-controls",
        action="store_true",
        help=(
            "Return a non-zero exit status unless at least one entitled positive "
            "control is supplied and every such control finishes VERIFIED."
        ),
    )
    parser.add_argument(
        "--doi",
        action="append",
        default=[],
        help="Additional DOI to test. Repeat as needed.",
    )
    parser.add_argument(
        "--entitled-doi",
        action="append",
        default=[],
        help=(
            "DOI manually confirmed downloadable with the same account/institution. "
            "Repeat for positive controls; any failure makes the runner exit non-zero."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("downloads/v06"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("v06-access-acceptance.json"),
    )
    parser.add_argument("--profile", default="institution")
    parser.add_argument("--profile-root", type=Path, default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--interaction-timeout", type=float, default=180.0)
    parser.add_argument("--unpaywall-email", default=None)
    parser.add_argument("--openalex-api-key", default=None)
    parser.add_argument("--metadata-mailto", default=None)
    parser.add_argument(
        "--no-elsevier-api",
        action="store_true",
        help="Ignore ELSEVIER_* environment credentials even if configured.",
    )
    args = parser.parse_args()
    if args.headless and not args.non_interactive:
        parser.error("--headless requires --non-interactive")

    benchmark_paths = args.benchmark or list(DEFAULT_BENCHMARKS)
    cases = _load_cases(benchmark_paths, args.doi, args.entitled_doi)
    if not cases:
        raise SystemExit("No acceptance cases were provided")

    config = BrowserAccessConfig(
        profile_name=args.profile,
        profile_root=args.profile_root,
        channel=args.channel,
        headless=args.headless,
        interactive=not args.non_interactive,
        interaction_timeout=args.interaction_timeout,
        interaction_callback=(None if args.non_interactive else _interaction_notice),
    )

    elsevier_config = None if args.no_elsevier_api else ElsevierAccessConfig.from_env()

    records: list[dict[str, object]] = []
    verified = 0
    base_verified = 0
    elsevier_recovered = 0
    interaction_cases = 0
    entitled_controls = sum(bool(case["entitled_control"]) for case in cases)
    entitled_verified = 0
    browser_recovered = 0
    entitled_total = sum(bool(case["expected_entitled"]) for case in cases)
    entitled_verified = 0
    final_statuses: Counter[str] = Counter()
    challenge_kinds: Counter[str] = Counter()

    with BrowserSession(config) as browser_session:
        for index, case in enumerate(cases, start=1):
            doi = str(case["doi"])
            title = case["title"]
            print(f"[{index}/{len(cases)}] {doi}")
            result = acquire_full_text_maximized(
                doi,
                output_dir=args.output_dir,
                browser_session=browser_session,
                elsevier_config=elsevier_config,
                expected_title=title,
                unpaywall_email=args.unpaywall_email,
                openalex_api_key=args.openalex_api_key,
                metadata_mailto=args.metadata_mailto,
            )
            record = _serialize(result)
            record["entitled_control"] = bool(case["entitled_control"])
            records.append(record)

            if result.base_result.status.value == "VERIFIED":
                base_verified += 1
            if result.status == MaximizedAcquisitionStatus.VERIFIED:
                verified += 1
                if bool(case["expected_entitled"]):
                    entitled_verified += 1
                if bool(case["entitled_control"]):
                    entitled_verified += 1
                if (
                    result.elsevier_attempt is not None
                    and result.elsevier_attempt.status.value == "VERIFIED"
                ):
                    elsevier_recovered += 1
                elif result.base_result.status.value != "VERIFIED":
                    browser_recovered += 1
            final_statuses[result.status.value] += 1
            for attempt in result.browser_attempts:
                for report in attempt.challenge_history:
                    challenge_kinds[report.kind.value] += 1
            if any(attempt.interaction_used for attempt in result.browser_attempts):
                interaction_cases += 1

            print(
                f"  base={result.base_result.status.value} "
                f"final={result.status.value} "
                f"verified={result.verified_path or '-'}"
            )

            _write_report(
                args.report,
                records=records,
                benchmark_paths=benchmark_paths,
                entitled_benchmark_paths=entitled_benchmark_paths,
                config=config,
                base_verified=base_verified,
                verified=verified,
                entitled_total=entitled_total,
                entitled_verified=entitled_verified,
                elsevier_enabled=elsevier_config is not None,
                elsevier_recovered=elsevier_recovered,
                browser_recovered=browser_recovered,
                interaction_cases=interaction_cases,
                entitled_controls=entitled_controls,
                entitled_verified=entitled_verified,
                final_statuses=final_statuses,
                challenge_kinds=challenge_kinds,
            )

    print()
    print("Aletheia Nexus v0.6 acceptance summary")
    print(f"Cases:              {len(cases)}")
    print(f"v0.5 VERIFIED:      {base_verified}")
    print(f"v0.6 VERIFIED:      {verified}")
    print(
        "Entitled controls:  "
        f"{entitled_verified}/{entitled_total if entitled_total else '-'}"
    )
    print(f"Elsevier recovered: {elsevier_recovered}")
    print(f"Browser recovered:  {browser_recovered}")
    print(f"Interaction cases:  {interaction_cases}")
    print(f"Entitled controls:  {entitled_verified}/{entitled_controls}")
    print("Final statuses:")
    for name, count in sorted(final_statuses.items()):
        print(f"  {name:<22} {count}")
    print("Challenge observations:")
    if challenge_kinds:
        for name, count in sorted(challenge_kinds.items()):
            print(f"  {name:<22} {count}")
    else:
        print("  (none)")
    print(f"Report:             {args.report}")

    entitled_failures = entitled_controls - entitled_verified
    if entitled_failures:
        print(
            f"FAIL: {entitled_failures} manually confirmed entitled control(s) "
            "were not VERIFIED."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
