"""Download CNKI articles sequentially by DOI, or one article by title."""

import argparse
import json
from pathlib import Path

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserSession,
    acquire_cnki_pdf,
)


def _interaction_notice(challenge, url):
    print(
        f"CNKI 需要手动认证（{challenge.kind.value}）。"
        "请在浏览器中完成认证，完成后自动继续。",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doi", action="append", help="Repeat for a sequential CNKI batch."
    )
    parser.add_argument("--title")
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--journal")
    parser.add_argument("--year", type=int)
    parser.add_argument("--volume")
    parser.add_argument("--issue")
    parser.add_argument("--pages")
    parser.add_argument("--cnki-id")
    parser.add_argument("--output-dir", type=Path, default=Path("downloads/cnki"))
    parser.add_argument("--profile", default="default")
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument("--channel")
    parser.add_argument("--executable-path", type=Path)
    parser.add_argument("--direct-connection", action="store_true")
    parser.add_argument(
        "--cnki-context-request",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use the observed PDF order URL with the browser cookie jar (default).",
    )
    parser.add_argument(
        "--keep-browser-open",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep the interactive AN browser until you close it (default).",
    )
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--interaction-timeout", type=float)
    parser.add_argument("--navigation-timeout", type=float, default=45.0)
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--keep-unverified", action="store_true")
    parser.add_argument(
        "--cnki-keep-unverified",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep valid but unverified PDFs in _unverified for local review (default).",
    )
    args = parser.parse_args()
    if not args.doi and not args.title:
        parser.error("provide --doi or --title (or both)")
    if args.headless and not args.non_interactive:
        parser.error("--headless requires --non-interactive")
    if (
        any(
            (
                args.title,
                args.author,
                args.journal,
                args.year,
                args.volume,
                args.issue,
                args.pages,
                args.cnki_id,
            )
        )
        and args.doi
        and len(args.doi) > 1
    ):
        parser.error("bibliographic constraints can only be used with a single DOI")
    config = BrowserAccessConfig(
        profile_name=args.profile,
        profile_root=args.profile_root,
        channel=args.channel,
        executable_path=args.executable_path,
        direct_connection=args.direct_connection,
        cnki_context_request=args.cnki_context_request,
        cdp_endpoint=args.cdp_endpoint,
        headless=args.headless,
        interactive=not args.non_interactive,
        wait_for_interaction=(
            not args.non_interactive and args.interaction_timeout is None
        ),
        interaction_timeout=(
            180.0 if args.interaction_timeout is None else args.interaction_timeout
        ),
        interaction_callback=_interaction_notice,
        navigation_timeout=args.navigation_timeout,
        cnki_max_results=args.max_results,
        keep_unverified=args.keep_unverified,
        cnki_keep_unverified=args.cnki_keep_unverified,
    )
    with BrowserSession(config) as session:
        exit_code = 0
        dois = args.doi or [None]
        for index, doi in enumerate(dois, 1):
            if len(dois) > 1:
                print(f"[{index}/{len(dois)}] CNKI {doi}", flush=True)
            attempt = acquire_cnki_pdf(
                doi=doi,
                title=args.title,
                authors=tuple(args.author),
                journal=args.journal,
                year=args.year,
                volume=args.volume,
                issue=args.issue,
                pages=args.pages,
                cnki_id=args.cnki_id,
                output_dir=args.output_dir,
                browser_session=session,
            )
            _print_attempt(attempt)
            if attempt.status == BrowserAttemptStatus.INTERACTION_REQUIRED:
                exit_code = 2
                break
            if attempt.status != BrowserAttemptStatus.VERIFIED:
                exit_code = max(exit_code, 1)
            if "CNKI browser target closed" in attempt.evidence:
                break
        if args.keep_browser_open and config.interactive and not config.cdp_endpoint:
            print(
                "AN 浏览器将保持打开，直到你关闭窗口或按 Ctrl+C；不会自动重试下载。",
                flush=True,
            )
            try:
                session.wait_until_closed()
            except KeyboardInterrupt:
                pass
    return exit_code


def _print_attempt(attempt) -> None:
    result = attempt.result
    print(
        json.dumps(
            {
                "status": attempt.status.value,
                "doi": attempt.source_candidate.doi or None,
                "article_id": attempt.source_candidate.article_id,
                "source_url": attempt.final_url,
                "pdf_path": str(result.file_path)
                if result and result.file_path
                else None,
                "sidecar_path": (
                    str(result.sidecar_path) if result and result.sidecar_path else None
                ),
                "candidates_considered": attempt.candidates_considered,
                "interaction_used": attempt.interaction_used,
                "download_started": attempt.download_started,
                "evidence": list(attempt.evidence),
                "error": attempt.error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
