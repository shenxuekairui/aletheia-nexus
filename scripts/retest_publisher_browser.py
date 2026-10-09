"""Publisher-only live runner; authentication stays in the user's browser.

Example: python scripts/retest_publisher_browser.py papers.json --output-dir
downloads/publisher-check --cdp-endpoint http://127.0.0.1:9222
The manifest is a JSON list of DOI/title rows with a url or Crossref primary URL.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from aletheia_nexus.acquire.access import BrowserAccessConfig, BrowserSession
from aletheia_nexus.acquire.access.audit import (
    audit_verified_pdf,
    summarize_attempt_history,
)
from aletheia_nexus.acquire.access.security import redact_url_for_record
from aletheia_nexus.acquire.discovery.models import CandidateUrlType, FullTextCandidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--profile", default="publisher-check")
    parser.add_argument("--doi", action="append", default=[])
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--interaction-timeout", type=float, default=180)
    args = parser.parse_args()
    rows = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "report.json"
    report = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": {}}
    )

    def notice(challenge, url):
        print(
            f"Waiting for {challenge.kind.value}; complete verification in the browser.",
            flush=True,
        )

    config = BrowserAccessConfig(
        profile_name=args.profile,
        cdp_endpoint=args.cdp_endpoint,
        cdp_resume_existing_page=False,
        interactive=not args.non_interactive,
        interaction_timeout=0 if args.non_interactive else args.interaction_timeout,
        interaction_callback=notice,
        navigation_timeout=45,
        request_timeout=30,
        max_source_routes=2,
        max_pdf_candidates=8,
    )
    with BrowserSession(config) as session:
        for row in rows:
            doi = row["doi"]
            if args.doi and doi not in args.doi:
                continue
            url = (
                row.get("url")
                or row.get("resource", {}).get("primary", {}).get("URL")
                or f"https://doi.org/{doi}"
            )
            event = {
                "at": datetime.now(timezone.utc).isoformat(),
                "doi": doi,
                "publisher_group": row.get("publisher_group"),
                "verified_path": None,
            }
            print(f"START {doi}", flush=True)
            try:
                result = session.acquire(
                    doi=doi,
                    routes=[
                        FullTextCandidate(
                            doi=doi,
                            url=url,
                            provenance=(),
                            url_type=CandidateUrlType.LANDING_PAGE,
                        )
                    ],
                    output_dir=args.output_dir,
                    expected_title=row.get("title"),
                )
                event.update(
                    status="VERIFIED"
                    if result.verified_result
                    else result.attempts[-1].status.value
                    if result.attempts
                    else "EXHAUSTED",
                    verified_path=str(result.verified_result.file_path)
                    if result.verified_result
                    else None,
                    elapsed_seconds=result.elapsed_seconds,
                    attempts=[
                        {
                            "status": a.status.value,
                            "final_url": redact_url_for_record(a.final_url),
                            "interaction_used": a.interaction_used,
                            "evidence": list(a.evidence),
                            "challenges": [c.kind.value for c in a.challenge_history],
                            "files": [
                                {
                                    "method": f.method,
                                    "error": f.error,
                                    "status": f.result.status.value
                                    if f.result
                                    else None,
                                }
                                for f in a.file_attempts
                            ],
                        }
                        for a in result.attempts
                    ],
                )
            except Exception as exc:
                event.update(status="RUNNER_ERROR", error=type(exc).__name__)
            # Deliberately outside the acquisition exception handler.
            if event["verified_path"]:
                event["audit"] = audit_verified_pdf(event["verified_path"], doi=doi)
            events = report["items"].get(doi, {}).get("attempt_history", [])
            report["items"][doi] = summarize_attempt_history([*events, event])
            report["updated_at"] = datetime.now(timezone.utc).isoformat()
            temporary = path.with_suffix(".json.part")
            temporary.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(path)
            print(f"END {doi}: {event['status']}", flush=True)


if __name__ == "__main__":
    main()
