"""Installed command-line interface for reproducible literature acquisition."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from importlib import metadata, util
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from aletheia_nexus.acquire.access import (
    BatchAcquisitionItem,
    BatchItemStatus,
    BrowserAccessConfig,
    PaperRequest,
    acquire_full_text_batch_maximized,
    browser_profile_dir,
)
from aletheia_nexus.acquire.access.browser_engine.runtime import (
    fixed_installed_browser,
    fixed_portable_browser,
)
from aletheia_nexus.acquire.fulltext import (
    FullTextAcquisitionStatus,
    acquire_full_text,
)
from aletheia_nexus.content import (
    AdaptiveOcrBackend,
    ChunkConfig,
    ParserConfig,
    ParserInputError,
    TesseractOcrBackend,
    TesseractOcrConfig,
    export_jsonl,
    export_markdown,
    load_parsed_document,
    parse_document,
    serialize_chunks,
    write_ai_export,
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
        if not isinstance(row, dict) or not ("doi" in row or "title" in row):
            raise ValueError("Each JSON/CSV row must contain a doi or title field")
        if not row.get("doi") or any(
            row.get(key) not in (None, "")
            for key in (
                "title",
                "authors",
                "journal",
                "year",
                "volume",
                "issue",
                "pages",
                "cnki_id",
                "folder",
                "filename",
                "tags",
            )
        ):
            authors = row.get("authors")
            if authors is None or authors == "":
                authors = ()
            if isinstance(authors, str):
                authors = tuple(a.strip() for a in authors.split(";") if a.strip())
            elif not isinstance(authors, (list, tuple)):
                raise ValueError("authors must be a list or semicolon-separated string")
            year = row.get("year")
            tags = row.get("tags")
            if tags is None or tags == "":
                tags = ()
            if isinstance(tags, str):
                tags = tuple(t.strip() for t in tags.split(";") if t.strip())
            elif not isinstance(tags, (list, tuple)):
                raise ValueError("tags must be a list or semicolon-separated string")
            if isinstance(year, str):
                year = year.strip()
                if year and (len(year) != 4 or not year.isdigit()):
                    raise ValueError("year must be a four-digit integer")
                year = int(year) if year else None
            fields = {
                key: None if row.get(key) == "" else row.get(key)
                for key in (
                    "doi",
                    "title",
                    "journal",
                    "volume",
                    "issue",
                    "pages",
                    "cnki_id",
                    "folder",
                    "filename",
                )
            }
            values.append(
                PaperRequest(
                    **fields,
                    authors=tuple(authors),
                    year=year,
                    tags=tuple(tags),
                )
            )
            continue
        doi_value = row["doi"]
        values.append(doi_value)
    return values, titles


def _cdp_ready(endpoint: str) -> bool:
    try:
        with urlopen(f"{endpoint.rstrip('/')}/json/version", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _find_browser() -> Path:
    installed = fixed_installed_browser()
    portable = fixed_portable_browser()
    if installed:
        return installed[1]
    if portable:
        return portable
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


def _start_cdp_browser(
    endpoint: str, profile_dir: Path, *, use_system_proxy: bool = False
) -> None:
    parsed = urlsplit(endpoint)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not parsed.port:
        raise ValueError(
            "Automatic browser start requires a loopback CDP endpoint port"
        )
    profile_dir.mkdir(parents=True, exist_ok=True)
    browser_args = [
        str(_find_browser()),
        f"--remote-debugging-address={'::1' if parsed.hostname == '::1' else '127.0.0.1'}",
        f"--remote-debugging-port={parsed.port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    if not use_system_proxy:
        browser_args.insert(4, "--no-proxy-server")
    subprocess.Popen(
        browser_args,
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
        "requested_title": result.base_result.requested_title,
        "validation_title": result.base_result.expected_title,
        "title_source": result.base_result.title_source.value,
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
                                "policy": file_attempt.result.identity_validation.policy,
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
                "input": asdict(item.input_value)
                if isinstance(item.input_value, PaperRequest)
                else item.input_value,
                "request_key": item.request_key,
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


def _acquire_public_organized(doi, *, request, output_dir, **kwargs):
    from aletheia_nexus.acquire.fulltext.storage import organized_output
    from aletheia_nexus.core.organization import destination

    organization = request
    directory = (
        destination(output_dir, organization.folder) if organization else output_dir
    )
    with organized_output(organization):
        return acquire_full_text(doi, output_dir=directory, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aletheia-nexus acquire",
        description=(
            "Sequential, resumable literature acquisition. Input may be "
            "newline DOI text, JSON, or CSV; citation rows support doi, title, "
            "authors, journal, year, volume, issue, pages and cnki_id."
        ),
    )
    parser.add_argument(
        "input", nargs="?", help="One DOI, or a TXT/JSON/CSV citation list"
    )
    parser.add_argument("--title", help="Exact title; DOI optional for CNKI citations")
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--journal")
    parser.add_argument("--year", type=int)
    parser.add_argument("--volume")
    parser.add_argument("--issue")
    parser.add_argument("--pages")
    parser.add_argument("--cnki-id")
    parser.add_argument(
        "--source", choices=("auto", "cnki", "exclude_cnki"), default="auto"
    )
    cnki_switch = parser.add_mutually_exclusive_group()
    cnki_switch.add_argument("--cnki", dest="no_cnki", action="store_false")
    cnki_switch.add_argument("--no-cnki", action="store_true")
    parser.set_defaults(no_cnki=False)
    parser.add_argument("--cnki-all-titles", action="store_true")
    parser.add_argument("--cnki-max-results", type=int, default=20)
    parser.add_argument(
        "--cnki-refresh-retry", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--no-cnki-keep-unverified", action="store_true")
    parser.add_argument(
        "--cnki-context-request",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Opt into cookie-jar HTTP delivery; CNKI uses native browser delivery by default.",
    )
    parser.add_argument("--executable-path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("downloads"))
    parser.add_argument(
        "--folder", help="Relative category folder; enables readable PDF names."
    )
    parser.add_argument(
        "--filename", help="Optional readable filename label (not a path)."
    )
    parser.add_argument(
        "--tag", action="append", default=[], help="Repeat for classification tags."
    )
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="Try public sources for one DOI; no browser installation is needed.",
    )
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--profile", default="human-handoff")
    parser.add_argument("--profile-root", type=Path, default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument(
        "--browser-launch-mode",
        choices=("auto", "normal", "managed"),
        default="auto",
        help="Default auto uses ordinary visible launch and keeps the browser open; "
        "headless stays managed. Use managed for the previous launch behavior.",
    )
    parser.add_argument(
        "--browser-use-system-proxy",
        action="store_true",
        help=(
            "Let a newly launched dedicated browser use the OS proxy settings "
            "instead of AN's direct-connection default. Authentication traffic "
            "may pass through the configured proxy; an already attached CDP "
            "browser keeps its own network settings."
        ),
    )
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
        help="Return a non-zero exit code unless every requested citation is VERIFIED.",
    )
    args = parser.parse_args(argv)

    if args.headless and not args.non_interactive:
        parser.error("--headless requires --non-interactive")
    citation_fields = dict(
        title=args.title,
        authors=tuple(args.author),
        journal=args.journal,
        year=args.year,
        volume=args.volume,
        issue=args.issue,
        pages=args.pages,
        cnki_id=args.cnki_id,
        folder=args.folder,
        filename=args.filename,
        tags=tuple(args.tag),
    )
    input_path = Path(args.input) if args.input else None
    if input_path is not None and input_path.is_file():
        if any(citation_fields.values()):
            parser.error(
                "For batch input, put bibliographic fields in each JSON/CSV row"
            )
        try:
            values, titles = _load_inputs(input_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"Could not read DOI input: {exc}")
    else:
        try:
            values, titles = (
                (
                    [PaperRequest(doi=args.input, **citation_fields)]
                    if any(citation_fields.values())
                    else [normalize_doi(args.input)]
                ),
                {},
            )
        except (TypeError, ValueError):
            parser.error("Provide a DOI, an existing input file, or --title")
    if args.no_cnki and args.source == "cnki":
        parser.error("--no-cnki conflicts with --source cnki")
    if args.public_only:
        if len(values) != 1:
            parser.error("--public-only currently accepts one DOI at a time")
        if args.local_pdf:
            parser.error("--public-only cannot be combined with --local-pdf")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        citation = values[0] if isinstance(values[0], PaperRequest) else None
        if citation is not None and not citation.doi:
            parser.error(
                "--public-only requires a DOI; title-only CNKI uses browser access"
            )
        if args.source == "cnki":
            parser.error("--public-only cannot use --source cnki")
        doi = citation.doi if citation else normalize_doi(values[0])
        result = _acquire_public_organized(
            doi,
            request=citation,
            output_dir=args.output_dir,
            expected_title=citation.title if citation else titles.get(doi),
            unpaywall_email=args.unpaywall_email,
            openalex_api_key=args.openalex_api_key,
            metadata_mailto=args.metadata_mailto,
            timeout=args.base_timeout,
            max_route_attempts=args.max_route_attempts,
            max_file_attempts=args.max_file_attempts,
            discovery_max_attempts=args.discovery_max_attempts,
            metadata_max_attempts=args.metadata_max_attempts,
            max_attempts_per_route=args.max_attempts_per_route,
            max_attempts_per_file=args.max_attempts_per_file,
            keep_unverified=args.keep_unverified,
        )
        print(f"{doi}: {result.status.value}")
        if result.verified_result is not None:
            print(f"PDF: {result.verified_result.retrieved.local_path}")
        if result.message:
            print(result.message)
        if (
            args.fail_on_unverified
            and result.status != FullTextAcquisitionStatus.VERIFIED
        ):
            return 4
        return 0
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
        launch_mode=args.browser_launch_mode,
        executable_path=args.executable_path,
        use_system_proxy=args.browser_use_system_proxy,
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
        cnki_enabled=not args.no_cnki,
        cnki_search_all_titles=args.cnki_all_titles,
        cnki_max_results=args.cnki_max_results,
        cnki_context_request=args.cnki_context_request,
        cnki_keep_unverified=not args.no_cnki_keep_unverified,
        cnki_refresh_retry=args.cnki_refresh_retry,
    )
    if (
        args.start_browser_if_needed
        and args.cdp_endpoint
        and not _cdp_ready(args.cdp_endpoint)
    ):
        _start_cdp_browser(
            args.cdp_endpoint,
            browser_profile_dir(config),
            use_system_proxy=config.use_system_proxy,
        )

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
        source_preference=args.source,
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
        item.status != BatchItemStatus.VERIFIED for item in result.items
    ):
        return 4
    return 0


def parse_main(argv: list[str] | None = None) -> int:
    """Run the experimental parser only after its acquisition-evidence gate."""

    parser = argparse.ArgumentParser(
        prog="aletheia-nexus parse",
        description="Parse a VERIFIED PDF into source-linked structured JSON.",
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--doi", required=True)
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-pages", type=int, default=2000)
    parser.add_argument("--max-blocks", type=int, default=200_000)
    parser.add_argument("--max-text-characters", type=int, default=20_000_000)
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable native-first selective OCR through Poppler and Tesseract.",
    )
    parser.add_argument("--ocr-languages", default="eng")
    parser.add_argument("--ocr-max-raster-pixels", type=int, default=50_000_000)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace an existing parsed output.",
    )
    parser.add_argument(
        "--no-merge-paragraph-lines",
        action="store_true",
        help="Keep each positioned PDF text line as a separate block.",
    )
    parser.add_argument(
        "--fail-on-partial",
        action="store_true",
        help="Return status 6 when parsing is PARTIAL or FAILED.",
    )
    args = parser.parse_args(argv)
    try:
        config = ParserConfig(
            max_pages=args.max_pages,
            max_blocks=args.max_blocks,
            max_text_characters=args.max_text_characters,
            merge_paragraph_lines=not args.no_merge_paragraph_lines,
        )
        backend = None
        if args.ocr:
            backend = AdaptiveOcrBackend(
                ocr_backends=(
                    TesseractOcrBackend(
                        TesseractOcrConfig(
                            languages=args.ocr_languages,
                            max_raster_pixels=args.ocr_max_raster_pixels,
                        )
                    ),
                )
            )
        result = parse_document(
            args.pdf,
            args.doi,
            sidecar_path=args.sidecar,
            output_path=args.output,
            config=config,
            backend=backend,
            overwrite=args.overwrite,
        )
    except ParserInputError as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except (OSError, ValueError) as exc:
        print(f"Could not write parsed artifact: {exc}", file=sys.stderr)
        return 2
    print(f"{result.source.doi}: {result.status}")
    print(f"Parsed artifact: {result.output_path}")
    quality = result.document["quality"]
    print(
        "Objects: "
        f"{len(result.document['sections'])} sections, "
        f"{len(result.document['references'])} references, "
        f"{len(result.document['figures'])} figures, "
        f"{len(result.document['tables'])} tables; "
        f"anchor coverage {quality['anchor_coverage']['ratio']:.1%}"
    )
    if args.fail_on_partial and result.status != "PARSED":
        return 6
    return 0


def search_main(argv: list[str] | None = None) -> int:
    """Search parsed blocks and print their source locations."""

    parser = argparse.ArgumentParser(
        prog="aletheia-nexus search",
        description="Search a validated parsed artifact with PDF source anchors.",
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("query")
    parser.add_argument("--section-type")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--verify-sources",
        action="store_true",
        help="Require the local PDF and acquisition sidecar hashes to still match.",
    )
    args = parser.parse_args(argv)
    try:
        artifact = load_parsed_document(args.artifact)
        if args.verify_sources:
            checks = artifact.verify_local_sources()
            if not all(checks.values()):
                failed = ", ".join(
                    name for name, passed in checks.items() if not passed
                )
                print(f"Source integrity failed: {failed}", file=sys.stderr)
                return 7
        hits = artifact.search(
            args.query, section_type=args.section_type, limit=args.limit
        )
    except (OSError, ValueError) as exc:
        print(f"Could not search parsed artifact: {exc}", file=sys.stderr)
        return 2
    for hit in hits:
        section = f" [{hit.section_heading}]" if hit.section_heading else ""
        bbox = f" bbox={list(hit.bbox)}" if hit.bbox else ""
        print(f"page {hit.page}{section} score={hit.score:.3f}{bbox}\n  {hit.text}")
    print(f"Hits: {len(hits)}")
    return 0


def export_main(argv: list[str] | None = None) -> int:
    """Export a validated canonical document without reparsing its PDF."""

    parser = argparse.ArgumentParser(
        prog="aletheia-nexus export",
        description="Create deterministic Markdown, JSONL, or chunk JSON views.",
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--format", choices=("markdown", "jsonl", "chunks"), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        artifact = load_parsed_document(args.artifact)
        config = ChunkConfig(max_characters=args.max_chars)
        serializers = {
            "markdown": export_markdown,
            "jsonl": export_jsonl,
            "chunks": serialize_chunks,
        }
        payload = serializers[args.format](artifact, config=config)
        output = write_ai_export(args.output, payload, overwrite=args.overwrite)
    except (OSError, ValueError) as exc:
        print(f"Could not export parsed artifact: {exc}", file=sys.stderr)
        return 7
    print(f"Exported {args.format}: {output}")
    return 0


def library_main(argv: list[str] | None = None) -> int:
    from aletheia_nexus.library import scan_library, update_tags

    if argv and argv[0] == "tag":
        parser = argparse.ArgumentParser(prog="aletheia-nexus library tag")
        parser.add_argument("pdf", type=Path)
        parser.add_argument("--add", action="append", default=[])
        parser.add_argument("--remove", action="append", default=[])
        args = parser.parse_args(argv[1:])
        if not args.add and not args.remove:
            parser.error("Provide --add or --remove")
        try:
            tags = update_tags(args.pdf, add=args.add, remove=args.remove)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            parser.error(str(exc))
        print(json.dumps({"tags": tags}, ensure_ascii=False))
        return 0

    parser = argparse.ArgumentParser(
        prog="aletheia-nexus library",
        epilog="Edit labels: aletheia-nexus library tag PAPER.pdf --add LABEL --remove LABEL",
    )
    parser.add_argument("root", type=Path, nargs="?", default=Path("downloads"))
    parser.add_argument("--folder", help="Filter a folder and its subfolders.")
    parser.add_argument("--tag", help="Filter by exact tag.")
    parser.add_argument("--query", help="Search titles, DOI, filenames and tags.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        catalog = scan_library(
            args.root, folder=args.folder, tag=args.tag, query=args.query
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
    else:
        for item in catalog["items"]:
            print(
                f"[{item['integrity']}] {item['folder'] or '.'} | {item['title'] or item['doi']}"
            )
            print(f"  {item['pdf_path']}  Tags: {', '.join(item['tags'])}")
        print(
            f"{len(catalog['items'])} papers; {len(catalog['warnings'])} unreadable records"
        )
    return 0


def entrypoint(argv: list[str] | None = None) -> int:
    """Dispatch the stable installed CLI without importing optional Playwright."""

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(
            "Aletheia Nexus — verifiable paper acquisition and parsing\n\n"
            "Usage:\n"
            "  aletheia-nexus acquire DOI [options]\n"
            "  aletheia-nexus acquire INPUT.txt [options]\n"
            "  aletheia-nexus acquire --title TITLE [options]\n"
            "  aletheia-nexus parse PAPER.pdf --doi DOI [options]\n"
            "  aletheia-nexus search PAPER.parsed.json QUERY [options]\n"
            "  aletheia-nexus export PAPER.parsed.json --format FORMAT --output PATH\n"
            "  aletheia-nexus doctor\n"
            "  aletheia-nexus browser-install\n"
            "  aletheia-nexus library [DIRECTORY] [--folder NAME] [--tag TAG]\n"
            "  aletheia-nexus --version\n\n"
            "Use 'aletheia-nexus COMMAND --help' for command options."
        )
        return 0
    if args[0] in {"-V", "--version"}:
        try:
            version = metadata.version("aletheia-nexus")
        except metadata.PackageNotFoundError:
            version = "source checkout (not installed)"
        print(f"aletheia-nexus {version}")
        return 0
    if args[0] == "doctor":
        if args[1:] in (["-h"], ["--help"]):
            print(
                "Usage: aletheia-nexus doctor\n"
                "Check local Python, browser, and OCR executable setup."
            )
            return 0
        if len(args) != 1:
            print("doctor takes no arguments", file=sys.stderr)
            return 2
        print(f"Python: {sys.version.split()[0]}")
        has_playwright = util.find_spec("playwright") is not None
        print(f"Browser extra: {'installed' if has_playwright else 'not installed'}")
        has_chromium = False
        if has_playwright:
            try:
                from playwright.sync_api import sync_playwright

                with sync_playwright() as driver:
                    has_chromium = Path(driver.chromium.executable_path).is_file()
            except Exception:
                pass
            print(
                f"Playwright Chromium binary: {'present' if has_chromium else 'missing'}"
            )
        if not has_playwright or not has_chromium:
            print(
                "Public HTTP acquisition is available. For interactive browser "
                "access, run:\n"
                '  python -m pip install "aletheia-nexus[browser]"\n'
                "  python -m playwright install chromium"
            )
        safe_runtime = fixed_installed_browser() or fixed_portable_browser()
        print(
            f"Fixed AN/installed runtime: {'available' if safe_runtime else 'not detected'}"
        )
        print(
            "Persistent download safety is checked at launch; Chromium 152-154 "
            "is blocked. Provision a private fixed runtime on Windows/Linux x64:\n"
            "  aletheia-nexus browser-install\n"
            "Or select an updated browser with acquire --executable-path PATH."
        )
        poppler = shutil.which("pdftoppm")
        tesseract = shutil.which("tesseract")
        print(f"Poppler OCR renderer: {'ready' if poppler else 'missing'}")
        print(f"Tesseract OCR engine: {'ready' if tesseract else 'missing'}")
        if not poppler or not tesseract:
            print(
                "Selective OCR remains optional; install Poppler and Tesseract "
                "and ensure pdftoppm/tesseract are on PATH to use parse --ocr."
            )
        return 0
    if args[0] == "browser-install":
        parser = argparse.ArgumentParser(
            prog="aletheia-nexus browser-install",
            description="Provision official stable Chrome for Testing in AN's private directory; no profiles or system browsers are modified.",
        )
        parser.parse_args(args[1:])
        from aletheia_nexus.acquire.access.browser_engine.installer import (
            main as install,
        )

        try:
            return install()
        except (
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
            StopIteration,
            subprocess.SubprocessError,
        ) as exc:
            print(f"Browser provisioning failed: {type(exc).__name__}", file=sys.stderr)
            return 2
    if args[0] == "acquire":
        return main(args[1:])
    if args[0] == "parse":
        return parse_main(args[1:])
    if args[0] == "search":
        return search_main(args[1:])
    if args[0] == "export":
        return export_main(args[1:])
    if args[0] == "library":
        return library_main(args[1:])
    print(f"Unknown command: {args[0]!r}. Use --help.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(entrypoint())
