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
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx

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
from aletheia_nexus.core.identifiers.doi import normalize_doi
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
    ("pmc.ncbi.nlm.nih.gov", "pmc-oa-opendata.s3.amazonaws.com"),
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


class _AttachmentSections(HTMLParser):
    """Associate links with explicit scholarly section headings, not keywords in references."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings, self.links = {}, {}
        self.level, self.text = None, []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self.level, self.text = int(tag[1]), []
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                roles = [role for _, role in sorted(self.headings.items()) if role]
                self.links[href] = roles[-1] if roles else None

    def handle_data(self, data):
        if self.level is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if self.level is not None and tag == f"h{self.level}":
            self.headings = {
                level: role
                for level, role in self.headings.items()
                if level < self.level
            }
            self.headings[self.level] = attachment_role(" ".join(self.text))
            self.level, self.text = None, []


def _attachment_details(link, url, *, page_url, doi, section_role):
    """Recognize documented publisher routes only after the parent DOI gate."""
    label = " ".join(filter(None, (link.text, link.title_attr)))
    role = attachment_role(label, url)
    parts, page = urlsplit(url), urlsplit(page_url)
    suffix = Path(unquote(parts.path)).suffix.lower()
    host = (parts.hostname or "").casefold()
    page_host = (page.hostname or "").casefold()
    if _under(host, "wiley.com") and parts.path == "/action/downloadSupplement":
        query = parse_qs(parts.query, keep_blank_values=True)
        try:
            matched_doi = (
                len(query.get("doi", [])) == 1 and normalize_doi(query["doi"][0]) == doi
            )
        except (TypeError, ValueError):
            matched_doi = False
        names = query.get("file", [])
        if not matched_doi or len(names) != 1 or re.search(r"[/\\]", names[0]):
            return None, "publisher_attachment_identity_mismatch"
        suffix, role = Path(names[0]).suffix.lower(), role or "SUPPLEMENT"
    elif (
        any(_under(host, domain) for domain in ("acs.org", "rsc.org"))
        and "/article-supplement/" in parts.path
    ):
        target = re.fullmatch(
            r"/([^/]+)/article-supplement/(\d+)/pdf/([^/]+)/?", parts.path
        )
        parent = re.match(r"/([^/]+)/article/(?:\d+/){3}(\d+)(?:/|$)", page.path)
        token_pattern = r"_si_\d+" if _under(host, "acs.org") else r"\d+_suppl"
        token = (
            re.fullmatch(
                re.escape(doi.split("/", 1)[1]) + token_pattern, target[3], re.I
            )
            if target
            else None
        )
        if (
            not target
            or not parent
            or (target[1], target[2]) != (parent[1], parent[2])
            or not token
        ):
            return None, "publisher_attachment_identity_mismatch"
        suffix, role = ".pdf", role or "SUPPLEMENT"
    elif (
        any(_under(host, domain) for domain in ("science.org", "acs.org", "wiley.com"))
        and "/doi/suppl/" in parts.path
    ):
        decoded = unquote(parts.path)
        prefixes = (f"/doi/suppl/{doi}/suppl_file/", f"/doi/suppl/{doi}/supinfo/")
        prefix = next(
            (p for p in prefixes if decoded.casefold().startswith(p.casefold())), None
        )
        if not prefix or "/" in decoded[len(prefix) :]:
            return None, "publisher_attachment_identity_mismatch"
        suffix, role = Path(decoded).suffix.lower(), role or "SUPPLEMENT"
    elif _under(page_host, "sciencedirect.com") and _under(host, "els-cdn.com"):
        component = re.fullmatch(
            r"/content/image/1-s2\.0-(S\d+)-mmc\d+(\.[A-Za-z0-9]+)", parts.path
        )
        if component:
            parent = re.search(r"/pii/(S\d+)(?:/|$)", page.path)
            if not parent or parent[1] != component[1]:
                return None, "publisher_attachment_identity_mismatch"
            role = role or section_role
    elif role is None:
        role = section_role
    if role is None:
        return None, None
    if suffix not in _SUFFIXES:
        return None, "attachment_extension_not_supported"
    return {"url": url, "role": role, "label": label, "extension": suffix}, None


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
    contexts = _AttachmentSections()
    contexts.feed(html)
    found, seen, excluded = [], set(), []
    for link in parsed.links:
        url = urljoin(page_url, link.url)
        attachment, problem = _attachment_details(
            link,
            url,
            page_url=page_url,
            doi=doi,
            section_role=contexts.links.get(link.url),
        )
        if (attachment is None and problem is None) or url in seen:
            continue
        seen.add(url)
        if not _official_link(page_url, url):
            excluded.append(
                {
                    "url": redact_url_for_record(url),
                    "reason": "attachment_host_not_covered",
                    "role": attachment["role"] if attachment else None,
                }
            )
            continue
        if problem:
            excluded.append(
                {
                    "url": redact_url_for_record(url),
                    "reason": problem,
                    "role": None,
                }
            )
            continue
        found.append(attachment)
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
            if any(
                path.is_symlink()
                or (hasattr(path, "is_junction") and path.is_junction())
                for path in (receipt_path, candidate)
            ):
                continue
            receipt = json.loads(receipt_path.read_text("utf-8"))
            if not isinstance(receipt, dict) or not isinstance(
                receipt.get("parent"), dict
            ):
                continue
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


def _retrieve_official_file(url, *, source_page, diagnostics=None, **kwargs):
    """Reuse the streaming transport, rejecting off-publisher redirects before HTTP."""

    class OfficialClient(httpx.Client):
        def stream(self, method, target, *args, **request_options):
            if not _official_link(source_page, str(target)):
                raise ValueError("attachment_redirect_host_not_covered")
            return super().stream(method, target, *args, **request_options)

    def response_observed(response):
        if diagnostics is not None:
            diagnostics.append(
                {
                    "status": "HTTP_FILE_RESPONSE",
                    "http_status": response.status_code,
                    "url": redact_url_for_record(str(response.url)),
                    "content_type": response.headers.get("content-type"),
                    "content_length": response.headers.get("content-length"),
                }
            )

    with OfficialClient(
        follow_redirects=False, event_hooks={"response": [response_observed]}
    ) as client:
        return retrieve_to_temp(url, client=client, **kwargs)


def _source_page_candidates(sidecar, doi):
    from .supplements_browser import _looks_like_pdf_url

    pages = []
    for url in (
        sidecar.get("access", {}).get("source_page_url"),
        sidecar.get("candidate", {}).get("url"),
    ):
        if not url:
            continue
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        if any(_under(host, d) for d in ("wiley.com", "acs.org", "science.org")):
            pages.append(f"{parsed.scheme}://{parsed.netloc}/doi/{doi}")
        elif _under(host, "nature.com") and parsed.path.endswith(".pdf"):
            pages.append(f"{parsed.scheme}://{parsed.netloc}{parsed.path[:-4]}")
        elif (
            sidecar.get("candidate", {}).get("host_type") == "publisher"
            and sidecar.get("candidate", {}).get("url_type") == "landing_page"
        ) or url == sidecar.get("access", {}).get("source_page_url"):
            if not _looks_like_pdf_url(url):
                pages.append(url)
    pages.append("https://doi.org/" + doi)
    return list(dict.fromkeys(pages))


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
    browser_session=None,
) -> dict:
    """Save attachments in one classification-level SI directory.

    PDF SI uses AN's existing REGISTERED/DECLARED source contract plus an
    immutable official-link receipt. Main acquisition evidence stays unchanged.
    Other roles are retained distinctly and never enter the parser as SI.
    """
    main = validate_parser_input(main_pdf)
    browser = None
    if browser_session is not None:
        from .supplements_browser import SupplementBrowserTransport

        browser = SupplementBrowserTransport(
            browser_session, doi=main.doi, title=main.title
        )
    result = None
    try:
        result = _acquire_supplements(
            main,
            library=library,
            page_urls=page_urls,
            max_files=max_files,
            max_bytes=max_bytes,
            timeout=timeout,
            page_fetch=page_fetch,
            file_fetch=file_fetch,
            browser=browser,
        )
    finally:
        if browser is not None:
            previous = len(browser.diagnostics)
            browser.close()
            if result is not None:
                result.setdefault("diagnostics", []).extend(
                    browser.diagnostics[previous:]
                )
    return result


def _acquire_supplements(
    main,
    *,
    library,
    page_urls,
    max_files,
    max_bytes,
    timeout,
    page_fetch,
    file_fetch,
    browser,
):
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
    candidates = (
        list(page_urls)
        if page_urls is not None
        else _source_page_candidates(sidecar, main.doi)
    )
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
    discoveries, errors, seen, diagnostics = [], [], set(), []
    page_fetch = page_fetch or retrieve_page
    repository_provenance = None
    if page_urls is None:
        from .supplement_repositories import discover_pmc_attachments

        repository = discover_pmc_attachments(
            sidecar, doi=main.doi, title=main.title, timeout=timeout
        )
        if repository["status"] != "NOT_SUPPORTED":
            repository_provenance = repository.get("provenance")
            for item in repository.get("items", []):
                discoveries.append(
                    {**item, "page": item.get("page") or repository["page_url"]}
                )
                seen.add(item["url"])
            for item in repository.get("diagnostics", []):
                diagnostics.append(item)
            errors.extend(repository.get("errors", []))
            if repository["status"] not in {
                "DISCOVERED",
                "COMPLETED",
                "NOT_FOUND",
            } and not repository.get("errors"):
                errors.append(
                    {"status": repository["status"], "source": "official_PMC_metadata"}
                )
    for url in dict.fromkeys(candidates):
        if discoveries:
            break
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
            diagnostics.append(
                {
                    "status": discovery["status"],
                    "page": redact_url_for_record(page.final_url),
                    "transport": "http",
                }
            )
            if discovery["status"] not in {"DISCOVERED", "NOT_FOUND"}:
                errors.append(
                    {
                        "status": discovery["status"],
                        "page": redact_url_for_record(page.final_url),
                    }
                )
            if discoveries:
                diagnostics.extend(errors)
                errors = []
                break
        except Exception as exc:
            errors.append(
                {
                    "status": "PAGE_FAILED",
                    "error": type(exc).__name__,
                    "page": redact_url_for_record(url),
                }
            )
    # Use only a session the caller explicitly authorized for this task. Startup
    # follows the existing normal launcher/lease and reuses that named profile.
    # Existing tabs are observed only; a missing article is loaded in an owned
    # temporary tab. Clear owned pages live until all attachment fetches finish.
    if browser is not None and not discoveries:
        try:
            page = browser.page_fetch(
                candidates[0] if candidates else "https://doi.org/" + main.doi,
                timeout=timeout,
                max_bytes=5 * 1024 * 1024,
            )
            discovery = discover_attachments(
                page.text, page.final_url, doi=main.doi, title=main.title
            )
            diagnostics.extend(errors)
            errors = []
            diagnostics.append(
                {
                    "status": discovery["status"],
                    "page": discovery.get("page_url"),
                    "transport": getattr(page, "transport", "browser_existing_DOM"),
                }
            )
            for attachment in discovery["items"]:
                if attachment["url"] not in seen:
                    seen.add(attachment["url"])
                    discoveries.append(
                        {
                            **attachment,
                            "page": discovery["page_url"],
                            "transport": "browser_session",
                        }
                    )
            if discovery["status"] not in {"DISCOVERED", "NOT_FOUND"}:
                errors.append(
                    {"status": discovery["status"], "transport": "browser_existing_DOM"}
                )
        except Exception as exc:
            errors.append(
                {
                    "status": "INTERACTION_REQUIRED"
                    if str(exc) == "attachment_interaction_required"
                    else "BROWSER_PAGE_UNAVAILABLE",
                    "error": str(exc)
                    if re.fullmatch(r"[a-z_]+", str(exc))
                    else type(exc).__name__,
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
        transport = "http"
        file_diagnostics = []
        try:
            directory.mkdir(parents=True, exist_ok=True)

            def retrieve_file(use_browser=False):
                nonlocal temporary, transport
                if use_browser:
                    transport = "browser_session"
                    resource = browser.file_fetch(
                        attachment["url"],
                        source_page=attachment["page"],
                        extension=attachment["extension"],
                        output_dir=directory,
                        max_bytes=max_bytes,
                        timeout=timeout,
                        diagnostics=file_diagnostics,
                    )
                elif file_fetch is not None:
                    resource = file_fetch(
                        attachment["url"],
                        output_dir=directory,
                        max_bytes=max_bytes,
                        timeout=timeout,
                    )
                else:
                    resource = _retrieve_official_file(
                        attachment["url"],
                        source_page=attachment["page"],
                        output_dir=directory,
                        max_bytes=max_bytes,
                        timeout=timeout,
                        diagnostics=file_diagnostics,
                    )
                temporary = resource.local_path
                if not _official_link(attachment["page"], resource.final_url) or any(
                    not _official_link(attachment["page"], hop.to_url)
                    for hop in getattr(resource, "redirects", ())
                ):
                    raise ValueError("attachment_redirect_host_not_covered")
                if temporary.stat().st_size > max_bytes:
                    raise ValueError("attachment_exceeds_byte_limit")
                if attachment.get("expected_md5"):
                    with temporary.open("rb") as check:
                        if (
                            hashlib.file_digest(check, "md5").hexdigest()
                            != attachment["expected_md5"]
                        ):
                            raise ValueError("official_attachment_checksum_mismatch")
                validation = _validate_attachment(temporary, attachment["extension"])
                return resource, validation

            try:
                # A DOM discovery may point to a public CDN; the discovery's
                # session does not require every file to use browser delivery.
                resource, validation = retrieve_file(False)
            except Exception as exc:
                if (
                    browser is None
                    or transport == "browser_session"
                    or file_fetch is not None
                ):
                    raise
                file_diagnostics.append(
                    {"status": "HTTP_DELIVERY_FAILED", "error": type(exc).__name__}
                )
                if temporary:
                    temporary.unlink(missing_ok=True)
                    temporary = None
                resource, validation = retrieve_file(True)
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
                "association_basis": attachment.get(
                    "association_basis",
                    "sole_scholarly_DOI_on_official_page_and_explicit_attachment_link",
                ),
                "association_evidence": attachment.get("evidence"),
                "repository_provenance": repository_provenance,
                "transport": transport,
                "transport_diagnostics": file_diagnostics,
                "retrieval": {
                    "http_status": getattr(resource, "http_status", None),
                    "content_type": getattr(resource, "content_type", None),
                    "size_bytes": target.stat().st_size,
                    "elapsed_seconds": getattr(resource, "elapsed_seconds", None),
                    "redirects": [
                        {
                            "from_url": redact_url_for_record(hop.from_url),
                            "to_url": redact_url_for_record(hop.to_url),
                            "status": hop.status_code,
                        }
                        for hop in getattr(resource, "redirects", ())
                    ],
                },
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
                    "transport": transport,
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
                    "status": "INTERACTION_REQUIRED"
                    if reason == "attachment_interaction_required"
                    else "FAILED",
                    "role": attachment["role"],
                    "error": reason,
                    "error_type": type(exc).__name__,
                    "source_url": redact_url_for_record(attachment["url"]),
                    "diagnostics": file_diagnostics,
                }
            )
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    saved = sum(i["status"] in {"SAVED", "REUSED"} for i in items)
    return {
        "status": "COMPLETED"
        if saved
        and saved == len(items)
        and len(discoveries) <= max_files
        and not errors
        else "PARTIAL"
        if saved
        else "INTERACTION_REQUIRED"
        if any(item["status"] == "INTERACTION_REQUIRED" for item in [*items, *errors])
        else "FAILED"
        if items or errors
        else "NOT_FOUND",
        "items": items,
        "discovered": len(discoveries),
        "truncated": len(discoveries) > max_files,
        "errors": errors,
        "diagnostics": diagnostics
        + (browser.diagnostics if browser is not None else []),
        "browser_handoff_scope": "DOI_confirmed_official_existing_or_owned_article_tabs"
        if browser is not None
        else None,
        "si_directory": str(directory) if directory.exists() else None,
        "main_status_unchanged": True,
    }
