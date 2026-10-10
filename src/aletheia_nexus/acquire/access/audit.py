"""Non-destructive auditing of already acquired publisher files."""

import hashlib
import json
from pathlib import Path

from pypdf import PdfReader

from aletheia_nexus.core.identifiers.doi import normalize_doi


def audit_verified_pdf(path: str | Path, *, doi: str) -> dict[str, object]:
    """Keep integrity failures separate from optional text-extraction warnings.

    This audit never upgrades acquisition status or deletes acquisition evidence.
    In particular a font/text extraction failure does not undo a verified download.
    """
    pdf = Path(path)
    audit: dict[str, object] = {"status": "FAILED", "checks": {}, "warnings": []}
    try:
        meta = json.loads(
            pdf.with_suffix(".acquisition.json").read_text(encoding="utf-8")
        )
        digest = hashlib.sha256()
        with pdf.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        checks = {
            "sha256_matches": digest.hexdigest() == meta["retrieval"]["sha256"],
            "target_doi_matches": normalize_doi(meta["target"]["doi"])
            == normalize_doi(doi),
            "identity_matches": meta["identity_validation"]["status"] == "MATCH",
            "article_role": meta["identity_validation"]["document_role"] == "ARTICLE",
            "acquisition_verified": meta["status"] == "VERIFIED",
        }
        reader = PdfReader(pdf)
        audit.update(checks=checks, pages=len(reader.pages))
        if not all(checks.values()) or not reader.pages:
            return audit
        audit["status"] = "PASSED"
        try:
            audit["first_page_characters"] = len(reader.pages[0].extract_text() or "")
        except Exception as exc:
            audit.update(status="WARNING", warnings=[type(exc).__name__])
    except Exception as exc:
        audit["error"] = type(exc).__name__
    return audit


def summarize_attempt_history(events: list[dict[str, object]]) -> dict[str, object]:
    """Expose latest attempt and best successful file as distinct facts."""
    latest = events[-1] if events else None
    successes = [
        item
        for item in events
        if item.get("status") == "VERIFIED"
        and item.get("verified_path")
        and (item.get("audit") or {}).get("status") != "FAILED"
    ]
    best = successes[-1] if successes else None
    return {
        "latest_attempt": latest,
        "best_verified": best,
        "effective_status": "VERIFIED" if best else (latest or {}).get("status"),
        "attempt_history": list(events),
    }
