"""Check that a live v0.6 report demonstrates browser-backed entitlement.

The acquisition runner's historical freeze gate counts any VERIFIED control.
This stricter, offline check rejects a control satisfied by the public v0.5
path or an unrelated official API. It still cannot prove the human's account
or subscription: that requires a same-session manual attestation and PDF review.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "aletheia-nexus/v0.6-access-acceptance/v2"
SUMMARY_SCHEMA = "aletheia-nexus/institutional-access-review/v1"
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_-]{1,39}$")


def evaluate(
    report: dict[str, object], *, institution_id: str, expected_profile: str
) -> dict[str, object]:
    """Return a privacy-minimal machine-gate result for one institution."""

    if not _SAFE_ID.fullmatch(institution_id):
        raise ValueError("institution_id must be a short lowercase safe label")
    if not _SAFE_ID.fullmatch(expected_profile):
        raise ValueError("expected_profile must be a short lowercase safe label")

    issues: list[str] = []
    if report.get("schema") != SCHEMA:
        issues.append("unexpected source report schema")
    if report.get("aletheia_nexus_version") != "0.6.1":
        issues.append("source report is not from the 0.6.1 version lineage")
    revision = report.get("source_revision")
    revision = revision if isinstance(revision, dict) else {}
    commit = revision.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        issues.append("source report lacks a valid code commit")
    if revision.get("dirty") is not False:
        issues.append("source code was not a clean committed revision")

    browser = report.get("browser")
    browser = browser if isinstance(browser, dict) else {}
    if browser.get("profile_name") != expected_profile:
        issues.append("browser profile does not match the expected institution profile")
    if browser.get("headless") is not False or browser.get("interactive") is not True:
        issues.append("browser was not in visible interactive mode")
    launch_mode = browser.get("launch_mode")
    if launch_mode == "an_playwright":
        if browser.get("external_cdp_attach") is not False:
            issues.append("Playwright launch mode conflicts with CDP attachment")
    elif launch_mode == "an_dedicated_cdp":
        if browser.get("external_cdp_attach") is not True:
            issues.append("dedicated CDP launch mode lacks CDP attachment")
    else:
        issues.append("browser was not started in an AN-dedicated profile")

    official_api = report.get("official_api")
    official_api = official_api if isinstance(official_api, dict) else {}
    if official_api.get("elsevier_enabled") is not False:
        issues.append("Elsevier API must be disabled for browser-only qualification")

    corpus = report.get("corpus")
    corpus = corpus if isinstance(corpus, dict) else {}
    summary = report.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    records = report.get("records")
    records = records if isinstance(records, list) else []
    controls = [
        record
        for record in records
        if isinstance(record, dict) and record.get("entitled_control") is True
    ]
    stress = [
        record
        for record in records
        if isinstance(record, dict) and record.get("stress_case") is True
    ]
    families = {
        str(record.get("access_family") or "").strip().casefold() for record in controls
    }
    families.discard("")

    if len(controls) < 3 or corpus.get("entitled_positive_control_count") != len(
        controls
    ):
        issues.append("report does not contain three consistent entitled controls")
    if len(families) < 2:
        issues.append("entitled controls cover fewer than two access families")
    if len(stress) < 20 or corpus.get("stress_case_count") != len(stress):
        issues.append("fixed stress corpus is incomplete")
    if summary.get("runner_errors") != 0:
        issues.append("acceptance runner recorded an error")
    if summary.get("freeze_gate_passed") is not True:
        issues.append("historical v0.6 freeze gate did not pass")
    if (
        not isinstance(summary.get("v0.6_only_recoveries"), int)
        or summary.get("v0.6_only_recoveries", 0) < 1
    ):
        issues.append("no v0.6-only recovery was recorded")
    if corpus.get("case_count") != len(records):
        issues.append("source report case count does not match its records")

    browser_verified = 0
    seen_dois: set[str] = set()
    for index, record in enumerate(controls, start=1):
        doi = record.get("doi")
        if not isinstance(doi, str) or not doi.startswith("10.") or doi in seen_dois:
            issues.append(f"control #{index} has an invalid or duplicate DOI")
        else:
            seen_dois.add(doi)
        if record.get("status") != "VERIFIED":
            issues.append(f"control #{index} was not VERIFIED")
            continue
        if record.get("base_status") == "VERIFIED":
            issues.append(f"control #{index} was verified by the public base path")
            continue
        api_attempt = record.get("elsevier_attempt")
        if isinstance(api_attempt, dict) and api_attempt.get("status") == "VERIFIED":
            issues.append(f"control #{index} was verified by the official API")
            continue
        attempts = record.get("browser_attempts")
        if not isinstance(attempts, list) or not any(
            isinstance(attempt, dict) and attempt.get("status") == "VERIFIED"
            for attempt in attempts
        ):
            issues.append(f"control #{index} lacks a verified browser attempt")
            continue
        browser_verified += 1

    return {
        "schema": SUMMARY_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "single-institution, multiple-access-families",
        "institution_id": institution_id,
        "release_version": report.get("aletheia_nexus_version"),
        "code_commit": commit if isinstance(commit, str) else None,
        "profile_name": browser.get("profile_name"),
        "browser_launch_mode": launch_mode,
        "stress_cases": len(stress),
        "entitled_controls": len(controls),
        "entitled_access_families": sorted(families),
        "browser_verified_controls": browser_verified,
        "machine_gate_passed": not issues,
        "manual_pdf_and_session_review": "pending",
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Local v0.6 acceptance JSON report")
    parser.add_argument("--institution-id", required=True)
    parser.add_argument("--expected-profile", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("source report must be a JSON object")
        result = evaluate(
            payload,
            institution_id=args.institution_id,
            expected_profile=args.expected_profile,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"Could not validate the local acceptance report: {exc}")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["machine_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
