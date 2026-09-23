"""Download a DOI collection through the resumable v0.6 access pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from aletheia_nexus.acquire.access import (
    BatchAcquisitionItem,
    BatchItemStatus,
    BrowserAccessConfig,
    acquire_full_text_batch_maximized,
    browser_profile_dir,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi


def _load_inputs(path: Path) -> tuple[list[object], dict[str, str]]:
    """Load newline text, JSON, or CSV without interpreting credentials."""

    suffix = path.suffix.lower()
    values: list[object] = []
    titles: dict[str, str] = {}

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON input must be a list")
        rows = payload
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = [
            line.strip()
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    for row in rows:
        if isinstance(row, str):
            values.append(row)
            continue
        if not isinstance(row, dict) or "doi" not in row:
            raise ValueError("Each JSON/CSV row must contain a doi field")
        doi_value = row["doi"]
        values.append(doi_value)
        title = row.get("title")
        if isinstance(title, str) and title.strip():
            try:
                normalized_doi = normalize_doi(doi_value)
            except (TypeError, ValueError):
                continue
            titles[normalized_doi] = title.strip()
    return values, titles


def _cdp_ready(endpoint: str) -> bool:
    try:
        with urlopen(f"{endpoint.rstrip('/')}/json/version", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _find_browser() -> Path:
    candidates = [
        Path.home() / "AppData/Local/Microsoft/Edge/Application/msedge.exe",
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find Edge or Chrome in standard Windows paths")


def _start_cdp_browser(endpoint: str, profile_dir: Path) -> None:
    parsed = urlsplit(endpoint)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not parsed.port:
        raise ValueError(
            "Automatic browser start requires a loopback CDP endpoint port"
        )
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(_find_browser()),
            f"--remote-debugging-port={parsed.port}",
            f"--user-data-dir={profile_dir}",
            "--no-proxy-server",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if _cdp_ready(endpoint):
            return
        time.sleep(0.25)
    raise RuntimeError("Browser started but the CDP endpoint did not become ready")


def _progress(item: BatchAcquisitionItem, index: int, total: int) -> None:
    path = f" -> {item.verified_path}" if item.verified_path else ""
    resumed = " [resumed]" if item.resumed else ""
    print(
        f"[{index}/{total}] {item.doi or item.input_value}: {item.status}{resumed}{path}",
        flush=True,
    )
    if item.status == BatchItemStatus.INTERACTION_REQUIRED and item.result:
        print(f"  {item.result.message}", flush=True)


def _interaction_notice(challenge, url: str) -> None:
    print(
        "\n[interaction required] "
        f"{challenge.kind.value} at {url}\n"
        "Complete the login/CAPTCHA/MFA in the visible browser. "
        "AN is paused and will continue automatically when the challenge clears. "
        "Press Ctrl+C to cancel.\n",
        flush=True,
    )


def _manual_pdf_prompt(doi: str) -> Path | None:
    print(
        "\n[IEEE browser fallback] Automatic page download did not finish. Open "
        f"https://doi.org/{doi} in your own browser, use your authorized "
        "account to save this single article PDF, then enter its full local "
        "path. Leave blank to continue with INTERACTION_REQUIRED.\n",
        flush=True,
    )
    try:
        chosen = input("PDF path: ").strip().strip('"')
    except EOFError:
        return None
    return Path(chosen) if chosen else None


def _safe_diagnostics(item: BatchAcquisitionItem) -> dict | None:
    """Return useful status evidence without URLs, credentials, or paper text."""

    result = item.result
    if result is None:
        return None
    return {
        "message": result.message,
        "base_status": result.base_result.status.value,
        "browser_attempts": [
            {
                "status": attempt.status.value,
                "error": attempt.error,
                "interaction_used": attempt.interaction_used,
                "candidates_considered": attempt.candidates_considered,
                "challenge_history": [
                    {
                        "kind": challenge.kind.value,
                        "evidence": list(challenge.evidence),
                    }
                    for challenge in attempt.challenge_history
                ],
                "file_attempts": [
                    {
                        "method": file_attempt.method,
                        "error": file_attempt.error,
                        "status": (
                            file_attempt.result.status.value
                            if file_attempt.result is not None
                            else None
                        ),
                        "identity": (
                            {
                                "status": (
                                    file_attempt.result.identity_validation.status.value
                                ),
                                "document_role": (
                                    file_attempt.result.identity_validation.document_role.value
                                ),
                                "doi_match": (
                                    file_attempt.result.identity_validation.doi_match
                                ),
                                "title_similarity": (
                                    file_attempt.result.identity_validation.title_similarity
                                ),
                                "evidence": list(
                                    file_attempt.result.identity_validation.evidence
                                ),
                            }
                            if file_attempt.result is not None
                            and file_attempt.result.identity_validation is not None
                            else None
                        ),
                    }
                    for file_attempt in attempt.file_attempts
                ],
            }
            for attempt in result.browser_attempts
        ],
    }


def _write_report(path: Path, result) -> None:
    payload = {
        "schema": "aletheia-nexus/access-batch-report/v1",
        "elapsed_seconds": result.elapsed_seconds,
        "halted_for_interaction": result.halted_for_interaction,
        "status_counts": result.status_counts,
        "items": [
            {
                "input": item.input_value,
                "doi": item.doi,
                "status": item.status.value,
                "verified_path": (
                    str(item.verified_path.resolve()) if item.verified_path else None
                ),
                "resumed": item.resumed,
                "attempts": item.attempts,
                "error": item.error,
                "elapsed_seconds": item.elapsed_seconds,
                "diagnostics": _safe_diagnostics(item),
            }
            for item in result.items
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sequential, resumable v0.6 literature acquisition. Input may be "
            "newline text, JSON, or CSV; JSON/CSV rows use doi and optional title."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("downloads/v06-batch"))
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--profile", default="human-handoff")
    parser.add_argument("--profile-root", type=Path, default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--cdp-endpoint", default=None)
    parser.add_argument(
        "--cdp-navigate",
        action="store_true",
        help=(
            "With --cdp-endpoint, open and navigate a temporary tab per route "
            "instead of resuming the browser's current page."
        ),
    )
    parser.add_argument(
        "--start-browser-if-needed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Automatically start AN's dedicated direct-connection Edge/Chrome "
            "when a configured loopback CDP endpoint is unavailable (default: "
            "enabled; disable with --no-start-browser-if-needed)."
        ),
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument(
        "--manual-ieee-fallback",
        action="store_true",
        help="Prompt for a locally saved IEEE PDF if automatic acquisition fails.",
    )
    parser.add_argument(
        "--local-pdf",
        action="append",
        default=[],
        metavar="DOI=PATH",
        help="Import a user-downloaded PDF for this DOI through normal validation.",
    )
    parser.add_argument(
        "--interaction-timeout",
        type=float,
        default=None,
        help=(
            "Maximum seconds to wait for login/CAPTCHA/MFA. In interactive mode, "
            "omitting this option waits until the challenge clears or the user "
            "cancels."
        ),
    )
    parser.add_argument("--navigation-timeout", type=float, default=45.0)
    parser.add_argument("--request-timeout", type=float, default=45.0)
    parser.add_argument("--max-source-routes", type=int, default=12)
    parser.add_argument("--max-pdf-candidates", type=int, default=12)
    parser.add_argument("--base-timeout", type=float, default=30.0)
    parser.add_argument("--max-route-attempts", type=int, default=16)
    parser.add_argument("--max-file-attempts", type=int, default=24)
    parser.add_argument("--discovery-max-attempts", type=int, default=3)
    parser.add_argument("--metadata-max-attempts", type=int, default=2)
    parser.add_argument("--max-attempts-per-route", type=int, default=2)
    parser.add_argument("--max-attempts-per-file", type=int, default=2)
    parser.add_argument(
        "--stop-on-interaction",
        action="store_true",
        help=(
            "Stop the whole batch after an unresolved login/CAPTCHA/MFA. By "
            "default only the current DOI ends and later items continue."
        ),
    )
    parser.add_argument(
        "--continue-after-interaction",
        dest="stop_on_interaction",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(stop_on_interaction=False)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--keep-duplicates", action="store_true")
    parser.add_argument(
        "--keep-unverified",
        action="store_true",
        help="Keep valid PDFs that fail article identity/role verification.",
    )
    parser.add_argument("--max-item-attempts", type=int, default=2)
    parser.add_argument("--retry-backoff", type=float, default=1.0)
    parser.add_argument("--unpaywall-email", default=None)
    parser.add_argument("--openalex-api-key", default=None)
    parser.add_argument("--metadata-mailto", default=None)
    parser.add_argument("--no-elsevier-api", action="store_true")
    parser.add_argument(
        "--fail-on-unverified",
        action="store_true",
        help="Return a non-zero exit code unless every valid DOI is VERIFIED.",
    )
    args = parser.parse_args()

    if args.headless and not args.non_interactive:
        parser.error("--headless requires --non-interactive")
    values, titles = _load_inputs(args.input)
    local_pdfs = {}
    for entry in args.local_pdf:
        if "=" not in entry:
            parser.error("--local-pdf must use DOI=PATH")
        doi, path = entry.split("=", 1)
        if not doi or not path:
            parser.error("--local-pdf must use a non-empty DOI and path")
        local_pdfs[doi] = Path(path.strip('"'))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.checkpoint or args.output_dir / "batch-checkpoint.json"
    report = args.report or args.output_dir / "batch-report.json"
    config = BrowserAccessConfig(
        profile_name=args.profile,
        profile_root=args.profile_root,
        channel=args.channel,
        cdp_endpoint=args.cdp_endpoint,
        cdp_resume_existing_page=not args.cdp_navigate,
        headless=args.headless,
        interactive=not args.non_interactive,
        wait_for_interaction=(
            not args.non_interactive and args.interaction_timeout is None
        ),
        interaction_callback=(None if args.non_interactive else _interaction_notice),
        interaction_timeout=(
            0 if args.interaction_timeout is None else args.interaction_timeout
        ),
        navigation_timeout=args.navigation_timeout,
        request_timeout=args.request_timeout,
        max_source_routes=args.max_source_routes,
        max_pdf_candidates=args.max_pdf_candidates,
        keep_unverified=args.keep_unverified,
    )
    if (
        args.start_browser_if_needed
        and args.cdp_endpoint
        and not _cdp_ready(args.cdp_endpoint)
    ):
        _start_cdp_browser(args.cdp_endpoint, browser_profile_dir(config))

    result = acquire_full_text_batch_maximized(
        values,
        output_dir=args.output_dir,
        expected_titles=titles,
        local_pdfs=local_pdfs,
        manual_file_callback=(
            _manual_pdf_prompt
            if args.manual_ieee_fallback
            and not args.non_interactive
            and sys.stdin.isatty()
            else None
        ),
        browser_config=config,
        checkpoint_path=checkpoint,
        resume=not args.no_resume,
        deduplicate=not args.keep_duplicates,
        stop_on_interaction=args.stop_on_interaction,
        max_item_attempts=args.max_item_attempts,
        retry_backoff=args.retry_backoff,
        progress_callback=_progress,
        unpaywall_email=args.unpaywall_email,
        openalex_api_key=args.openalex_api_key,
        metadata_mailto=args.metadata_mailto,
        auto_official_api=not args.no_elsevier_api,
        timeout=args.base_timeout,
        max_route_attempts=args.max_route_attempts,
        max_file_attempts=args.max_file_attempts,
        discovery_max_attempts=args.discovery_max_attempts,
        metadata_max_attempts=args.metadata_max_attempts,
        max_attempts_per_route=args.max_attempts_per_route,
        max_attempts_per_file=args.max_attempts_per_file,
        keep_unverified=args.keep_unverified,
    )
    _write_report(report, result)

    counts = Counter(item.status.value for item in result.items)
    print("\nBatch summary")
    print(f"VERIFIED: {counts[BatchItemStatus.VERIFIED.value]}/{len(result.items)}")
    for status, count in sorted(counts.items()):
        if status != BatchItemStatus.VERIFIED.value:
            print(f"{status}: {count}")
    print(f"Checkpoint: {checkpoint}")
    print(f"Report: {report}")

    if counts[BatchItemStatus.RUNNER_ERROR.value]:
        return 2
    if result.halted_for_interaction:
        return 3
    if args.fail_on_unverified and any(
        item.doi is not None and item.status != BatchItemStatus.VERIFIED
        for item in result.items
    ):
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
