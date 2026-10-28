"""Explicit official-page attachments, independent of main-PDF verification.

Only DOI-bound scholarly pages and explicit attachment links are considered.
Generic site crawling, authentication escalation, archive extraction and guessing
article identity from filenames are deliberately absent.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from aletheia_nexus.acquire.fulltext.resolution.identity import (
    classify_page_type,
    validate_page_identity,
)
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html
from aletheia_nexus.acquire.fulltext.resolution.transport import retrieve_page
from aletheia_nexus.acquire.fulltext.transport import retrieve_to_temp
from aletheia_nexus.acquire.fulltext.validation import inspect_pdf
from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.urls import redact_url_for_record

_SCHEMA = "aletheia-nexus/attachment-source/v1"
_SUFFIXES = {
    ".pdf",
    ".xlsx",
    ".xls",
    ".csv",
    ".tsv",
    ".txt",
    ".docx",
    ".pptx",
    ".zip",
    ".cif",
    ".mol",
    ".sdf",
    ".json",
    ".xml",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".mp4",
    ".mov",
}
_OFFICIAL_GROUPS = (
    (
        "nature.com",
        "springer.com",
        "springeropen.com",
        "springernature.com",
        "springer-cdn.com",
    ),
    ("acs.org", "acs.figshare.com"),
    ("rsc.org",),
    ("wiley.com",),
    ("sciencedirect.com", "elsevier.com", "els-cdn.com"),
    ("science.org", "sciencemag.org"),
    ("plos.org",),
    ("mdpi.com", "mdpi-res.com"),
    ("pnas.org",),
    ("frontiersin.org",),
)


def _under(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _official_link(page: str, link: str) -> bool:
    origin = (urlsplit(page).hostname or "").casefold()
    target = (urlsplit(link).hostname or "").casefold()
    if origin == target:
        return True
    return any(
        any(_under(origin, d) for d in group) and any(_under(target, d) for d in group)
        for group in _OFFICIAL_GROUPS
    )


def attachment_role(label: str, url: str = "") -> str | None:
    """Keep peer-review, reporting and source data distinct from actual SI."""
    text = " ".join((label, unquote(urlsplit(url).path))).casefold()
    if re.search(r"peer[\s_-]*review|review[\s_-]*(?:file|history)|审稿", text):
        return "PEER_REVIEW"
    if re.search(r"reporting[\s_-]*summary|reporting[\s_-]*checklist", text):
        return "REPORTING_SUMMARY"
    if re.search(r"source[\s_-]*data|原始数据", text):
        return "SOURCE_DATA"
    if re.search(
        r"supplement(?:ary|al)?[\s_-]*(?:information|material|data|file|appendix|tables?|figures?)|supporting[\s_-]*(?:information|material|data)|补充(?:信息|材料)|(?:^|[/_])(?:moesm\d+[_-]esm|suppinfo|supporting_info)",
        text,
    ):
        return "SUPPLEMENT"
    return None


def discover_attachments(
    html: str, page_url: str, *, doi: str, title: str | None = None
) -> dict:
    parsed = parse_html(html)
    identity = validate_page_identity(
        target_doi=doi, parsed=parsed, expected_title=title
    )
    page_type = classify_page_type(parsed, identity)
    if page_type.value in {"CHALLENGE", "LOGIN", "ACCESS_DENIED"}:
        return {
            "status": "INTERACTION_REQUIRED",
            "items": [],
            "page_type": page_type.value,
        }
    # A title-only match is insufficient for automatic parent association.
    if identity.metadata_dois != (doi,) or not identity.doi_match:
        return {"status": "IDENTITY_NOT_CONFIRMED", "items": []}
    found, seen, excluded = [], set(), []
    for link in parsed.links:
        label = " ".join(filter(None, (link.text, link.title_attr)))
        url = urljoin(page_url, link.url)
        role = attachment_role(label, url)
        if role is None or url in seen:
            continue
        seen.add(url)
        if not _official_link(page_url, url):
            excluded.append(
                {
                    "url": redact_url_for_record(url),
                    "reason": "attachment_host_not_covered",
                    "role": role,
                }
            )
            continue
        suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
        if suffix not in _SUFFIXES:
            excluded.append(
                {
                    "url": redact_url_for_record(url),
                    "reason": "attachment_extension_not_supported",
                    "role": role,
                }
            )
            continue
        found.append({"url": url, "role": role, "label": label, "extension": suffix})
    return {
        "status": "DISCOVERED" if found else "NOT_FOUND",
        "items": found,
        "excluded": excluded,
        "page_url": redact_url_for_record(page_url),
        "parent_identity": "sole_scholarly_doi",
    }


def _validate_attachment(path: Path, suffix: str) -> dict:
    if path.stat().st_size == 0:
        raise ValueError("empty_attachment")
    with path.open("rb") as handle:
        prefix = handle.read(1024).lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<script")):
        raise ValueError("attachment_is_html_or_login_page")
    if suffix == ".pdf":
        report = inspect_pdf(path, text_pages=0).report
        if not report.valid_pdf:
            raise ValueError("invalid_supplement_pdf")
        return {"type": "pdf", "page_count": report.page_count, "parseable": True}
    if suffix in {".zip", ".xlsx", ".docx", ".pptx"}:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if (
                len(names) > 10000
                or sum(i.file_size for i in archive.infolist()) > 2 * 1024**3
            ):
                raise ValueError("archive_declared_contents_exceed_limit")
            if any(i.flag_bits & 1 for i in archive.infolist()):
                raise ValueError("encrypted_attachment_archive")
            expected = {
                ".xlsx": "xl/workbook.xml",
                ".docx": "word/document.xml",
                ".pptx": "ppt/presentation.xml",
            }.get(suffix)
            if expected and (
                expected not in names or "[Content_Types].xml" not in names
            ):
                raise ValueError("invalid_office_attachment")
        return {"type": suffix[1:], "parseable": False, "archive_extracted": False}
    if suffix in {".txt", ".csv", ".tsv", ".json", ".xml", ".cif", ".mol", ".sdf"}:
        # Check text plausibility without promising a domain-specific parser.
        if b"\x00" in prefix:
            raise ValueError("binary_content_in_text_attachment")
    elif suffix == ".xls" and not prefix.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise ValueError("invalid_legacy_excel_attachment")
    elif suffix == ".png" and not prefix.startswith(b"\x89png\r\n\x1a\n"):
        raise ValueError("invalid_png_attachment")
    elif suffix in {".jpg", ".jpeg"} and not prefix.startswith(b"\xff\xd8\xff"):
        raise ValueError("invalid_jpeg_attachment")
    return {"type": suffix[1:], "parseable": False, "opened": False}


def _receipt_path(path: Path) -> Path:
    return path.parent / "json" / (path.name + ".attachment.json")


def _write_new_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _known_attachment(main, directory: Path, attachment: dict, library=None):
    if not directory.is_dir():
        return None
    url_key = hashlib.sha256(attachment["url"].encode()).hexdigest()
    receipts = [
        (receipt_path, directory / receipt_path.name.removesuffix(".attachment.json"))
        for receipt_path in (directory / "json").glob("*.attachment.json")
    ]
    # Library locators remain valid after safe rename/category moves, while the
    # original attachment-source receipt stays immutable at its historical path.
    if library is not None and hasattr(library, "scan"):
        for paper in library.scan()["items"]:
            if paper.get("pdf_sha256") != main.pdf_sha256:
                continue
            for item in paper.get("attachments", []):
                source = item.get("source")
                if isinstance(source, str):
                    try:
                        receipt_path = library.path(source, existing=True)
                        candidate = library.path(item["path"], existing=True)
                        receipts.append((receipt_path, candidate))
                    except (OSError, ValueError):
                        continue
    for receipt_path, candidate in receipts:
        try:
            receipt = json.loads(receipt_path.read_text("utf-8"))
            if (
                receipt.get("schema") == _SCHEMA
                and receipt.get("parent", {}).get("pdf_sha256") == main.pdf_sha256
                and receipt.get("parent", {}).get("article_id") == main.article_id
                and receipt.get("parent", {}).get("sidecar_sha256")
                == main.sidecar_sha256
                and receipt.get("role") == attachment["role"]
                and receipt.get("source_url_sha256") == url_key
                and candidate.is_file()
                and sha256_file(candidate) == receipt.get("sha256")
            ):
                return {
                    "status": "REUSED",
                    "path": str(candidate),
                    "role": receipt["role"],
                    "sha256": receipt["sha256"],
                    "source_record": str(receipt_path),
                }
        except (OSError, ValueError, KeyError):
            continue
    return None


def acquire_supplements(
    main_pdf,
    *,
    library=None,
    page_urls=None,
    max_files=20,
    max_bytes=100 * 1024 * 1024,
    timeout=30.0,
    page_fetch=None,
    file_fetch=None,
) -> dict:
    """Save attachments in one classification-level SI directory.

    PDF SI uses AN's existing REGISTERED/DECLARED source contract plus an
    immutable official-link receipt. Main acquisition evidence stays unchanged.
    Other roles are retained distinctly and never enter the parser as SI.
    """
    main = validate_parser_input(main_pdf)
    if main.document_role != "ARTICLE":
        raise ValueError("attachments require a main article")
    if not main.doi:
        return {
            "status": "NOT_SUPPORTED",
            "items": [],
            "reason": "automatic_SI_requires_DOI_bound_official_page",
        }
    if type(max_files) is not int or not 1 <= max_files <= 100:
        raise ValueError("SI file limit must be 1..100")
    sidecar = json.loads(main.sidecar_path.read_text("utf-8"))
    candidates = list(page_urls or [])
    if page_urls is None:
        source_page = sidecar.get("access", {}).get("source_page_url")
        if source_page:
            candidates.append(source_page)
        candidate = sidecar.get("candidate", {})
        if (
            candidate.get("host_type") == "publisher"
            and candidate.get("url_type") == "landing_page"
        ):
            candidates.append(candidate["url"])
        candidates.append("https://doi.org/" + main.doi)
    directory = main.pdf_path.parent / "SI"
    if (
        directory.is_symlink()
        or (hasattr(directory, "is_junction") and directory.is_junction())
        or not directory.resolve().is_relative_to(main.pdf_path.parent.resolve())
    ):
        raise ValueError("unsafe_SI_directory")
    records = directory / "json"
    if (
        records.is_symlink()
        or (hasattr(records, "is_junction") and records.is_junction())
        or not records.resolve().is_relative_to(directory.resolve())
    ):
        raise ValueError("unsafe_SI_record_directory")
    discoveries, errors, seen = [], [], set()
    page_fetch, file_fetch = page_fetch or retrieve_page, file_fetch or retrieve_to_temp
    for url in dict.fromkeys(candidates):
        try:
            page = page_fetch(url, timeout=timeout, max_bytes=5 * 1024 * 1024)
            if not page.text or page.body_truncated:
                errors.append(
                    {"status": "INVALID_PAGE", "page": redact_url_for_record(url)}
                )
                continue
            # Automatic resolver destinations must belong to a covered official
            # publisher. Explicit pages with publisher provenance may use the
            # generic same-host adapter; no arbitrary untrusted host is crawled.
            host = (urlsplit(page.final_url).hostname or "").casefold()
            official = any(_under(host, d) for group in _OFFICIAL_GROUPS for d in group)
            official = official or (
                sidecar.get("candidate", {}).get("host_type") == "publisher"
                and _official_link(sidecar["candidate"]["url"], page.final_url)
            )
            if not official:
                errors.append(
                    {
                        "status": "PUBLISHER_NOT_COVERED",
                        "page": redact_url_for_record(page.final_url),
                    }
                )
                continue
            discovery = discover_attachments(
                page.text, page.final_url, doi=main.doi, title=main.title
            )
            for attachment in discovery["items"]:
                if attachment["url"] not in seen:
                    seen.add(attachment["url"])
                    discoveries.append({**attachment, "page": discovery["page_url"]})
            if discovery["status"] != "DISCOVERED":
                errors.append(
                    {
                        "status": discovery["status"],
                        "page": redact_url_for_record(page.final_url),
                    }
                )
            if discoveries:
                break
        except Exception as exc:
            errors.append(
                {
                    "status": "PAGE_FAILED",
                    "error": type(exc).__name__,
                    "page": redact_url_for_record(url),
                }
            )
    items = []
    for attachment in discoveries[:max_files]:
        known = _known_attachment(main, directory, attachment, library)
        if known:
            items.append(known)
            if library:
                library.register_attachment(
                    main.pdf_path,
                    known["path"],
                    role=known["role"],
                    source_record=known["source_record"],
                )
            continue
        temporary = None
        target = None
        created = False
        try:
            directory.mkdir(parents=True, exist_ok=True)
            resource = file_fetch(
                attachment["url"],
                output_dir=directory,
                max_bytes=max_bytes,
                timeout=timeout,
            )
            temporary = resource.local_path
            validation = _validate_attachment(temporary, attachment["extension"])
            if resource.sha256 == main.pdf_sha256:
                raise ValueError("attachment_duplicates_main_article")
            role = attachment["role"]
            suffix_label = {
                "SUPPLEMENT": "SI",
                "SOURCE_DATA": "SourceData",
                "PEER_REVIEW": "PeerReview",
                "REPORTING_SUMMARY": "ReportingSummary",
            }[role]
            number = 1
            while True:
                target = (
                    directory
                    / f"{main.pdf_path.stem}__{suffix_label}-{number:02d}{attachment['extension']}"
                )
                if target.is_symlink() or _receipt_path(target).is_symlink():
                    raise ValueError("attachment_target_is_symbolic_link")
                if (
                    acquisition_sidecar_path(target).exists()
                    or _receipt_path(target).exists()
                ):
                    number += 1
                    continue
                try:
                    # Exclusive creation protects against concurrent downloads;
                    # no successful attachment can be overwritten.
                    with target.open("xb") as output, temporary.open("rb") as source:
                        created = True
                        shutil.copyfileobj(source, output)
                    break
                except FileExistsError:
                    number += 1
            if sha256_file(target) != resource.sha256:
                raise ValueError("attachment_changed_during_copy")
            receipt = {
                "schema": _SCHEMA,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "role": role,
                "status": "SAVED",
                "parent": {
                    "article_id": main.article_id,
                    "pdf_sha256": main.pdf_sha256,
                    "sidecar_sha256": main.sidecar_sha256,
                    "doi": main.doi,
                },
                "sha256": resource.sha256,
                "source_page": attachment["page"],
                "source_url": redact_url_for_record(attachment["url"]),
                "source_url_sha256": hashlib.sha256(
                    attachment["url"].encode()
                ).hexdigest(),
                "final_url": redact_url_for_record(resource.final_url),
                "link_label": attachment["label"],
                "association_basis": "sole_scholarly_DOI_on_official_page_and_explicit_attachment_link",
                "validation": validation,
            }
            if attachment["extension"] == ".pdf" and role == "SUPPLEMENT":
                register_local_pdf(
                    target,
                    output_dir=directory,
                    title=f"{main.title or main.doi} — Supplementary Information",
                    role="SUPPLEMENT",
                    parent_pdf=main.pdf_path,
                    parent_sidecar=main.sidecar_path,
                )
            record = _receipt_path(target)
            _write_new_json(record, receipt)
            if library:
                library.register_attachment(
                    main.pdf_path, target, role=role, source_record=record
                )
            items.append(
                {
                    "status": "SAVED",
                    "path": str(target),
                    "role": role,
                    "sha256": resource.sha256,
                    "source_record": str(record),
                    "parseable": validation["parseable"],
                    "identity_status": "DECLARED"
                    if role == "SUPPLEMENT" and attachment["extension"] == ".pdf"
                    else "OFFICIAL_LINK",
                }
            )
        except Exception as exc:
            # Once a complete receipt exists, retain the durable downloaded
            # evidence even if optional mutable library registration failed.
            if created and target and not _receipt_path(target).exists():
                target.unlink(missing_ok=True)
                acquisition_sidecar_path(target).unlink(missing_ok=True)
            reason = (
                str(exc)
                if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+", str(exc))
                else type(exc).__name__
            )
            items.append(
                {
                    "status": "FAILED",
                    "role": attachment["role"],
                    "error": reason,
                    "error_type": type(exc).__name__,
                    "source_url": redact_url_for_record(attachment["url"]),
                }
            )
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    saved = sum(i["status"] in {"SAVED", "REUSED"} for i in items)
    return {
        "status": "COMPLETED"
        if saved and saved == len(items)
        else "PARTIAL"
        if saved
        else "FAILED"
        if items
        else "NOT_FOUND",
        "items": items,
        "discovered": len(discoveries),
        "truncated": len(discoveries) > max_files,
        "errors": errors,
        "si_directory": str(directory) if directory.exists() else None,
        "main_status_unchanged": True,
    }
