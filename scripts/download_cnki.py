"""Download one CNKI article by DOI or title through a local browser profile."""

import argparse
import json
from pathlib import Path

from aletheia_nexus.acquire.access import (
    BrowserAccessConfig,
    BrowserAttemptStatus,
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
    parser.add_argument("--doi")
    parser.add_argument("--title")
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=Path("downloads/cnki"))
    parser.add_argument("--profile", default="default")
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument("--channel")
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--interaction-timeout", type=float)
    parser.add_argument("--navigation-timeout", type=float, default=45.0)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--keep-unverified", action="store_true")
    args = parser.parse_args()
    if not args.doi and not args.title:
        parser.error("provide --doi or --title (or both)")
    if args.headless and not args.non_interactive:
        parser.error("--headless requires --non-interactive")
    config = BrowserAccessConfig(
        profile_name=args.profile,
        profile_root=args.profile_root,
        channel=args.channel,
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
    )
    attempt = acquire_cnki_pdf(
        doi=args.doi,
        title=args.title,
        authors=tuple(args.author),
        output_dir=args.output_dir,
        config=config,
    )
    result = attempt.result
    print(
        json.dumps(
            {
                "status": attempt.status.value,
                "doi": attempt.source_candidate.doi or None,
                "source_url": attempt.final_url,
                "pdf_path": str(result.file_path)
                if result and result.file_path
                else None,
                "sidecar_path": (
                    str(result.sidecar_path) if result and result.sidecar_path else None
                ),
                "candidates_considered": attempt.candidates_considered,
                "interaction_used": attempt.interaction_used,
                "evidence": list(attempt.evidence),
                "error": attempt.error,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if attempt.status == BrowserAttemptStatus.VERIFIED:
        return 0
    return 2 if attempt.status == BrowserAttemptStatus.INTERACTION_REQUIRED else 1


if __name__ == "__main__":
    raise SystemExit(main())
