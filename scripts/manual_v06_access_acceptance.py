import argparse
import json
import platform
import subprocess
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
    browser_profile_dir,
)
from aletheia_nexus.acquire.access.security import redact_url_for_record
from aletheia_nexus.cli import _cdp_ready, _start_cdp_browser
from aletheia_nexus.core.identifiers.doi import normalize_doi

DEFAULT_BENCHMARKS = (
    Path("benchmarks/cdi_acquisition_10.json"),
    Path("benchmarks/seawater_desalination_10.json"),
)
MIN_FREEZE_ENTITLED_CONTROLS = 3
MIN_FREEZE_ACCESS_FAMILIES = 2
MIN_FREEZE_STRESS_CASES = 20
MIN_FREEZE_V06_ONLY_RECOVERIES = 1


def _package_version() -> str:
    try:
        return version("aletheia-nexus")
    except PackageNotFoundError:
        return "dev"


def _source_revision() -> dict[str, object]:
    """Record the exact local source state without disclosing file paths."""

    root = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None}
    return {"commit": commit, "dirty": bool(status)}


def _report_path(path: Path) -> str:
    """Return an auditable report path without exposing an absolute local directory."""

    value = Path(path)
    return value.name if value.is_absolute() else value.as_posix()


def _read_benchmark(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Benchmark must contain a JSON list: {path}")
    output: list[dict[str, object]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Benchmark item {index} must be a JSON object: {path}")
        doi = str(item.get("doi") or "").strip()
        if not doi:
            raise ValueError(f"Benchmark item {index} has no DOI: {path}")
        output.append(item)
    return output


def _load_cases(
    stress_paths: list[Path],
    entitled_paths: list[Path],
    dois: list[str],
    entitled_dois: list[str],
) -> list[dict[str, object]]:
    """Build one deduplicated acceptance corpus with explicit access expectations."""

    cases: list[dict[str, object]] = []
    by_doi: dict[str, dict[str, object]] = {}

    def add(
        *,
        doi: str,
        title: str | None,
        case_id: str,
        source: str | None,
        stress: bool,
        entitled: bool,
        access_family: str | None = None,
    ) -> None:
        raw = doi.strip()
        if not raw:
            return
        value = normalize_doi(raw)
        existing = by_doi.get(value)
        if existing is None:
            existing = {
                "doi": value,
                "title": title,
                "id": case_id,
                "stress_case": stress,
                "entitled_control": entitled,
                "access_family": access_family,
                "sources": [source] if source else [],
            }
            by_doi[value] = existing
            cases.append(existing)
            return

        existing["stress_case"] = bool(existing["stress_case"]) or stress
        existing["entitled_control"] = bool(existing["entitled_control"]) or entitled
        if access_family:
            prior_family = existing.get("access_family")
            if prior_family and prior_family != access_family:
                raise ValueError(
                    f"Conflicting access_family values for {value}: "
                    f"{prior_family!r} vs {access_family!r}"
                )
            existing["access_family"] = access_family
        if not existing["title"] and title:
            existing["title"] = title
        sources = existing["sources"]
        assert isinstance(sources, list)
        if source and source not in sources:
            sources.append(source)

    for path in stress_paths:
        for item in _read_benchmark(path):
            doi = str(item["doi"]).strip()
            add(
                doi=doi,
                title=str(item.get("title") or "").strip() or None,
                case_id=str(item.get("id") or doi),
                source=_report_path(path),
                stress=True,
                entitled=False,
                access_family=None,
            )

    for path in entitled_paths:
        for item in _read_benchmark(path):
            doi = str(item["doi"]).strip()
            add(
                doi=doi,
                title=str(item.get("title") or "").strip() or None,
                case_id=str(item.get("id") or doi),
                source=_report_path(path),
                stress=False,
                entitled=True,
                access_family=(
                    str(item.get("access_family") or "").strip().casefold() or None
                ),
            )

    for doi in dois:
        value = doi.strip()
        add(
            doi=value,
            title=None,
            case_id=value,
            source=None,
            stress=False,
            entitled=False,
            access_family=None,
        )

    for doi in entitled_dois:
        value = doi.strip()
        add(
            doi=value,
            title=None,
            case_id=value,
            source=None,
            stress=False,
            entitled=True,
            access_family=None,
        )

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
    base = result.base_result
    base_trace = {
        "discovery": {
            "candidate_count": len(base.discovery.candidates),
            "providers": [
                {
                    "provider": provider.provider.value,
                    "status": provider.status.value,
                    "candidate_count": len(provider.candidates),
                    "attempts": provider.attempts,
                }
                for provider in base.discovery.providers
            ],
        },
        "route_attempts": [
            {
                "url": redact_url_for_record(attempt.candidate.url),
                "origin": attempt.origin.value,
                "status": attempt.result.status.value,
                "depth": attempt.depth,
                "parent_url": redact_url_for_record(attempt.parent_url),
                "expansion_method": attempt.expansion_method,
                "page_type": (
                    attempt.result.page_type.value
                    if attempt.result.page_type is not None
                    else None
                ),
                "derived_candidate_count": len(attempt.result.candidates),
            }
            for attempt in base.route_attempts
        ],
        "file_attempts": [
            {
                "url": redact_url_for_record(attempt.candidate.url),
                "origin": attempt.origin.value,
                "status": attempt.result.status.value,
                "parent_url": redact_url_for_record(attempt.parent_url),
                "derivation_method": (
                    attempt.derivation_method.value
                    if attempt.derivation_method is not None
                    else None
                ),
                "role_hint": attempt.role_hint.value,
                "identity_status": (
                    attempt.result.identity_validation.status.value
                    if attempt.result.identity_validation is not None
                    else None
                ),
                "document_role": (
                    attempt.result.identity_validation.document_role.value
                    if attempt.result.identity_validation is not None
                    else None
                ),
            }
            for attempt in base.file_attempts
        ],
        "stats": {
            "duplicate_file_candidates_skipped": (
                base.duplicate_file_candidates_skipped
            ),
            "duplicate_route_candidates_skipped": (
                base.duplicate_route_candidates_skipped
            ),
            "supplement_candidates_skipped": base.supplement_candidates_skipped,
            "page_route_attempts": base.page_route_attempts,
            "route_expansions_enqueued": base.route_expansions_enqueued,
            "max_route_depth_reached": base.max_route_depth_reached,
        },
    }

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
        "base_trace": base_trace,
        "verified_path": (
            result.verified_path.name if result.verified_path is not None else None
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


def _runner_error_record(
    *,
    doi: str,
    case: dict[str, object],
    exc: Exception,
) -> dict[str, object]:
    """Serialize an unexpected per-case runner error without persisting its message."""

    return {
        "doi": doi,
        "status": "RUNNER_ERROR",
        "base_status": None,
        "verified_path": None,
        "elsevier_attempt": None,
        "browser_attempts": [],
        "elapsed_seconds": None,
        "message": None,
        "runner_error_type": type(exc).__name__,
        "case_id": case["id"],
        "stress_case": bool(case["stress_case"]),
        "entitled_control": bool(case["entitled_control"]),
        "access_family": case.get("access_family"),
        "sources": list(case["sources"]),
    }


def _report_payload(
    *,
    records: list[dict[str, object]],
    stress_paths: list[Path],
    entitled_paths: list[Path],
    config: BrowserAccessConfig,
    base_verified: int,
    verified: int,
    stress_base_verified: int,
    stress_verified: int,
    entitled_controls: int,
    entitled_verified: int,
    entitled_access_families: tuple[str, ...],
    entitled_controls_with_family: int,
    stress_cases: int,
    v06_only_recoveries: int,
    elsevier_enabled: bool,
    elsevier_recovered: int,
    browser_recovered: int,
    interaction_cases: int,
    runner_errors: int,
    final_statuses: Counter[str],
    challenge_kinds: Counter[str],
    browser_launch_mode: str = "an_playwright",
    source_revision: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema": "aletheia-nexus/v0.6-access-acceptance/v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aletheia_nexus_version": _package_version(),
        "source_revision": source_revision
        if source_revision is not None
        else _source_revision(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.system(),
            "platform_release": platform.release(),
        },
        "corpus": {
            "stress_benchmarks": [_report_path(path) for path in stress_paths],
            "entitled_positive_control_benchmarks": [
                _report_path(path) for path in entitled_paths
            ],
            "case_count": len(records),
            "entitled_positive_control_count": entitled_controls,
            "entitled_access_families": list(entitled_access_families),
            "stress_case_count": stress_cases,
        },
        "official_api": {
            "elsevier_enabled": elsevier_enabled,
        },
        "browser": {
            "profile_name": config.profile_name,
            "channel": config.channel,
            "external_cdp_attach": config.cdp_endpoint is not None,
            "launch_mode": browser_launch_mode,
            "headless": config.headless,
            "interactive": config.interactive,
            "max_source_routes": config.max_source_routes,
            "max_pdf_candidates": config.max_pdf_candidates,
        },
        "summary": {
            "v0.5_verified": base_verified,
            "v0.6_verified": verified,
            "stress_v0.5_verified": stress_base_verified,
            "stress_v0.6_verified": stress_verified,
            "stress_uplift_count": stress_verified - stress_base_verified,
            "stress_v0.5_verified_rate": (
                stress_base_verified / stress_cases if stress_cases else None
            ),
            "stress_v0.6_verified_rate": (
                stress_verified / stress_cases if stress_cases else None
            ),
            "elsevier_recovered": elsevier_recovered,
            "browser_recovered": browser_recovered,
            "v0.6_only_recoveries": v06_only_recoveries,
            "interaction_cases": interaction_cases,
            "runner_errors": runner_errors,
            "entitled_controls": entitled_controls,
            "entitled_verified": entitled_verified,
            "entitled_failures": entitled_controls - entitled_verified,
            "entitled_access_family_count": len(entitled_access_families),
            "entitled_access_families": list(entitled_access_families),
            "entitled_controls_with_family": entitled_controls_with_family,
            "entitled_controls_passed": (
                entitled_controls >= MIN_FREEZE_ENTITLED_CONTROLS
                and entitled_verified == entitled_controls
                and entitled_controls_with_family == entitled_controls
                and len(entitled_access_families) >= MIN_FREEZE_ACCESS_FAMILIES
            ),
            "freeze_gate_passed": (
                runner_errors == 0
                and entitled_controls >= MIN_FREEZE_ENTITLED_CONTROLS
                and entitled_verified == entitled_controls
                and entitled_controls_with_family == entitled_controls
                and len(entitled_access_families) >= MIN_FREEZE_ACCESS_FAMILIES
                and stress_cases >= MIN_FREEZE_STRESS_CASES
                and v06_only_recoveries >= MIN_FREEZE_V06_ONLY_RECOVERIES
            ),
            "final_statuses": dict(sorted(final_statuses.items())),
            "challenge_kinds": dict(sorted(challenge_kinds.items())),
        },
        "records": records,
    }


def _write_report(
    path: Path,
    *,
    records: list[dict[str, object]],
    stress_paths: list[Path],
    entitled_paths: list[Path],
    config: BrowserAccessConfig,
    base_verified: int,
    verified: int,
    stress_base_verified: int,
    stress_verified: int,
    entitled_controls: int,
    entitled_verified: int,
    entitled_access_families: tuple[str, ...],
    entitled_controls_with_family: int,
    stress_cases: int,
    v06_only_recoveries: int,
    elsevier_enabled: bool,
    elsevier_recovered: int,
    browser_recovered: int,
    interaction_cases: int,
    runner_errors: int,
    final_statuses: Counter[str],
    challenge_kinds: Counter[str],
    browser_launch_mode: str = "an_playwright",
    source_revision: dict[str, object] | None = None,
) -> None:
    payload = _report_payload(
        records=records,
        stress_paths=stress_paths,
        entitled_paths=entitled_paths,
        config=config,
        base_verified=base_verified,
        verified=verified,
        stress_base_verified=stress_base_verified,
        stress_verified=stress_verified,
        entitled_controls=entitled_controls,
        entitled_verified=entitled_verified,
        entitled_access_families=entitled_access_families,
        entitled_controls_with_family=entitled_controls_with_family,
        stress_cases=stress_cases,
        v06_only_recoveries=v06_only_recoveries,
        elsevier_enabled=elsevier_enabled,
        elsevier_recovered=elsevier_recovered,
        browser_recovered=browser_recovered,
        interaction_cases=interaction_cases,
        runner_errors=runner_errors,
        final_statuses=final_statuses,
        challenge_kinds=challenge_kinds,
        browser_launch_mode=browser_launch_mode,
        source_revision=source_revision,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _freeze_gate(
    *,
    entitled_controls: int,
    entitled_verified: int,
    require_entitled_controls: bool,
    entitled_access_families: tuple[str, ...] = (),
    entitled_controls_with_family: int = 0,
    stress_cases: int = 0,
    v06_only_recoveries: int = 0,
    runner_errors: int = 0,
) -> tuple[int, str | None]:
    """Evaluate the live-release access ceiling gate deterministically."""

    if runner_errors:
        return (
            4,
            f"{runner_errors} acceptance case(s) raised unexpected runner errors.",
        )

    entitled_failures = entitled_controls - entitled_verified
    if entitled_failures:
        return (
            2,
            (
                f"{entitled_failures} manually confirmed entitled control(s) "
                "were not VERIFIED."
            ),
        )
    if require_entitled_controls:
        if entitled_controls < MIN_FREEZE_ENTITLED_CONTROLS:
            return (
                3,
                (
                    "freeze acceptance requires at least "
                    f"{MIN_FREEZE_ENTITLED_CONTROLS} entitled positive controls; "
                    f"received {entitled_controls}."
                ),
            )
        if entitled_controls_with_family != entitled_controls:
            return (
                5,
                (
                    "freeze acceptance requires access_family on every entitled "
                    f"positive control; received {entitled_controls_with_family}/"
                    f"{entitled_controls} labeled controls."
                ),
            )
        if len(entitled_access_families) < MIN_FREEZE_ACCESS_FAMILIES:
            return (
                6,
                (
                    "freeze acceptance requires at least "
                    f"{MIN_FREEZE_ACCESS_FAMILIES} distinct publisher/access families; "
                    f"received {len(entitled_access_families)}. "
                    "Set access_family on entitled benchmark entries."
                ),
            )
        if stress_cases < MIN_FREEZE_STRESS_CASES:
            return (
                7,
                (
                    "freeze acceptance requires at least "
                    f"{MIN_FREEZE_STRESS_CASES} stress cases; "
                    f"received {stress_cases}."
                ),
            )
        if v06_only_recoveries < MIN_FREEZE_V06_ONLY_RECOVERIES:
            return (
                8,
                (
                    "freeze acceptance requires at least one real v0.6-only "
                    "recovery beyond the v0.5 baseline."
                ),
            )
    return 0, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the v0.6 acquisition-maximization live acceptance corpus."
    )
    parser.add_argument(
        "--benchmark",
        action="append",
        type=Path,
        default=[],
        help=(
            "Stress-corpus JSON path. Repeat to combine corpora. If omitted, "
            "the fixed CDI + seawater-desalination 20-paper corpus is used."
        ),
    )
    parser.add_argument(
        "--entitled-benchmark",
        action="append",
        type=Path,
        default=[],
        help=(
            "JSON corpus manually confirmed downloadable with this same "
            "account/institution/network environment. Repeat as needed."
        ),
    )
    parser.add_argument(
        "--doi",
        action="append",
        default=[],
        help="Additional ad-hoc DOI. Repeat as needed.",
    )
    parser.add_argument(
        "--entitled-doi",
        action="append",
        default=[],
        help=(
            "DOI manually confirmed downloadable with this same access environment. "
            "Repeat as needed. Any such failure makes the run fail."
        ),
    )
    parser.add_argument(
        "--require-entitled-controls",
        action="store_true",
        help=(
            "Freeze gate: require >=20 stress cases, >=3 entitled controls, "
            "access_family on every control, >=2 distinct access families, "
            "all controls VERIFIED, >=1 v0.6-only recovery, and zero unexpected "
            "runner errors."
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
    parser.add_argument(
        "--cdp-endpoint",
        default=None,
        help=(
            "Attach to a dedicated browser over a loopback CDP endpoint, for "
            "example http://127.0.0.1:9222. The current HTTP(S) tab is reused "
            "unless --cdp-navigate is set."
        ),
    )
    parser.add_argument(
        "--cdp-navigate",
        action="store_true",
        help="Open and navigate a temporary browser tab for each route.",
    )
    parser.add_argument(
        "--start-browser-if-needed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start a dedicated Edge/Chrome if the CDP endpoint is not running.",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--interaction-timeout", type=float, default=180.0)
    parser.add_argument(
        "--browser-use-system-proxy",
        action="store_true",
        help="Use the OS proxy settings for AN's newly launched browser.",
    )
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

    stress_paths = args.benchmark or list(DEFAULT_BENCHMARKS)
    entitled_paths = list(args.entitled_benchmark)
    cases = _load_cases(
        stress_paths,
        entitled_paths,
        args.doi,
        args.entitled_doi,
    )
    if not cases:
        raise SystemExit("No acceptance cases were provided")

    config = BrowserAccessConfig(
        profile_name=args.profile,
        profile_root=args.profile_root,
        channel=args.channel,
        use_system_proxy=args.browser_use_system_proxy,
        cdp_endpoint=args.cdp_endpoint,
        cdp_resume_existing_page=not args.cdp_navigate,
        headless=args.headless,
        interactive=not args.non_interactive,
        interaction_timeout=args.interaction_timeout,
        interaction_callback=(None if args.non_interactive else _interaction_notice),
    )
    browser_launch_mode = "an_playwright"
    if args.cdp_endpoint:
        browser_launch_mode = "attached_existing_cdp"
        if args.start_browser_if_needed and not _cdp_ready(args.cdp_endpoint):
            _start_cdp_browser(
                args.cdp_endpoint,
                browser_profile_dir(config),
                use_system_proxy=config.use_system_proxy,
            )
            browser_launch_mode = "an_dedicated_cdp"
    source_revision = _source_revision()
    elsevier_config = None if args.no_elsevier_api else ElsevierAccessConfig.from_env()

    records: list[dict[str, object]] = []
    verified = 0
    base_verified = 0
    stress_verified = 0
    stress_base_verified = 0
    elsevier_recovered = 0
    browser_recovered = 0
    interaction_cases = 0
    runner_errors = 0
    stress_cases = sum(bool(case["stress_case"]) for case in cases)
    entitled_controls = sum(bool(case["entitled_control"]) for case in cases)
    entitled_verified = 0
    entitled_controls_with_family = sum(
        bool(case["entitled_control"] and case.get("access_family")) for case in cases
    )
    entitled_access_families = tuple(
        sorted(
            {
                str(case["access_family"])
                for case in cases
                if case["entitled_control"] and case.get("access_family")
            }
        )
    )
    final_statuses: Counter[str] = Counter()
    challenge_kinds: Counter[str] = Counter()

    with BrowserSession(config) as browser_session:
        for index, case in enumerate(cases, start=1):
            doi = str(case["doi"])
            title = case["title"]
            print(f"[{index}/{len(cases)}] {doi}")

            try:
                result = acquire_full_text_maximized(
                    doi,
                    output_dir=args.output_dir,
                    browser_session=browser_session,
                    elsevier_config=elsevier_config,
                    auto_official_api=not args.no_elsevier_api,
                    expected_title=title if isinstance(title, str) else None,
                    unpaywall_email=args.unpaywall_email,
                    openalex_api_key=args.openalex_api_key,
                    metadata_mailto=args.metadata_mailto,
                )
            except Exception as exc:
                runner_errors += 1
                final_statuses["RUNNER_ERROR"] += 1
                records.append(
                    _runner_error_record(
                        doi=doi,
                        case=case,
                        exc=exc,
                    )
                )
                print(f"  runner_error={type(exc).__name__}")
                _write_report(
                    args.report,
                    records=records,
                    stress_paths=stress_paths,
                    entitled_paths=entitled_paths,
                    config=config,
                    base_verified=base_verified,
                    verified=verified,
                    stress_base_verified=stress_base_verified,
                    stress_verified=stress_verified,
                    entitled_controls=entitled_controls,
                    entitled_verified=entitled_verified,
                    entitled_access_families=entitled_access_families,
                    entitled_controls_with_family=entitled_controls_with_family,
                    stress_cases=stress_cases,
                    v06_only_recoveries=elsevier_recovered + browser_recovered,
                    elsevier_enabled=elsevier_config is not None,
                    elsevier_recovered=elsevier_recovered,
                    browser_recovered=browser_recovered,
                    interaction_cases=interaction_cases,
                    runner_errors=runner_errors,
                    final_statuses=final_statuses,
                    challenge_kinds=challenge_kinds,
                    browser_launch_mode=browser_launch_mode,
                    source_revision=source_revision,
                )
                continue

            record = _serialize(result)
            record.update(
                {
                    "case_id": case["id"],
                    "stress_case": bool(case["stress_case"]),
                    "entitled_control": bool(case["entitled_control"]),
                    "access_family": case.get("access_family"),
                    "sources": list(case["sources"]),
                }
            )
            records.append(record)

            if result.base_result.status.value == "VERIFIED":
                base_verified += 1
                if bool(case["stress_case"]):
                    stress_base_verified += 1
            if result.status == MaximizedAcquisitionStatus.VERIFIED:
                verified += 1
                if bool(case["stress_case"]):
                    stress_verified += 1
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

            label = " ENTITLED-CONTROL" if case["entitled_control"] else ""
            print(
                f"  base={result.base_result.status.value} "
                f"final={result.status.value} "
                f"verified={result.verified_path or '-'}{label}"
            )

            _write_report(
                args.report,
                records=records,
                stress_paths=stress_paths,
                entitled_paths=entitled_paths,
                config=config,
                base_verified=base_verified,
                verified=verified,
                stress_base_verified=stress_base_verified,
                stress_verified=stress_verified,
                entitled_controls=entitled_controls,
                entitled_verified=entitled_verified,
                entitled_access_families=entitled_access_families,
                entitled_controls_with_family=entitled_controls_with_family,
                stress_cases=stress_cases,
                v06_only_recoveries=elsevier_recovered + browser_recovered,
                elsevier_enabled=elsevier_config is not None,
                elsevier_recovered=elsevier_recovered,
                browser_recovered=browser_recovered,
                interaction_cases=interaction_cases,
                runner_errors=runner_errors,
                final_statuses=final_statuses,
                challenge_kinds=challenge_kinds,
                browser_launch_mode=browser_launch_mode,
                source_revision=source_revision,
            )

    print()
    print("Aletheia Nexus v0.6 acceptance summary")
    print(f"Cases:              {len(cases)}")
    print(f"Total v0.5 VERIFIED:{base_verified:>6}")
    print(f"Total v0.6 VERIFIED:{verified:>6}")
    print(
        "Stress v0.5/v0.6:   "
        f"{stress_base_verified}/{stress_cases} -> {stress_verified}/{stress_cases}"
    )
    print(f"Stress uplift:       {stress_verified - stress_base_verified:+d}")
    print(f"Entitled controls:  {entitled_verified}/{entitled_controls}")
    print(
        "Access families:    "
        f"{len(entitled_access_families)} "
        f"({', '.join(entitled_access_families) or '-'})"
    )
    print(f"Elsevier recovered: {elsevier_recovered}")
    print(f"Browser recovered:  {browser_recovered}")
    print(f"v0.6-only recovery: {elsevier_recovered + browser_recovered}")
    print(f"Stress cases:        {stress_cases}")
    print(f"Interaction cases:  {interaction_cases}")
    print(f"Runner errors:       {runner_errors}")
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

    exit_code, freeze_error = _freeze_gate(
        entitled_controls=entitled_controls,
        entitled_verified=entitled_verified,
        entitled_access_families=entitled_access_families,
        entitled_controls_with_family=entitled_controls_with_family,
        stress_cases=stress_cases,
        v06_only_recoveries=elsevier_recovered + browser_recovered,
        require_entitled_controls=args.require_entitled_controls,
        runner_errors=runner_errors,
    )
    if freeze_error is not None:
        print(f"FREEZE GATE FAILED: {freeze_error}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
