"""Public ACS supplementary manifests, without browser or credential use.

Only exact parent DOI/title, ACS-hosted records and publisher supplement DOIs
authorize files. The generic attachment pipeline still owns saving/registration.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx

from aletheia_nexus.acquire.fulltext.http import build_user_agent, raise_for_http_status
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html
from aletheia_nexus.acquire.fulltext.safety import validate_safe_url
from aletheia_nexus.core.identifiers.doi import normalize_doi

API = "https://api.figshare.com/v2/articles"
BASIS = "official_ACS_Figshare_parent_DOI_title_and_file_manifest"
MAX_RECORDS = 10
MAX_FILES = 64
MAX_JSON_BYTES = 2 * 1024 * 1024


def _read_json(url, *, timeout, search=None):
    # No remote URL from a response is followed. Every endpoint is constructed
    # from the fixed API origin and a validated numeric ID; redirects are refused.
    url = validate_safe_url(url)
    with httpx.Client(follow_redirects=False) as client:
        with client.stream(
            "POST" if search is not None else "GET",
            url,
            json=search,
            timeout=timeout,
            headers={"User-Agent": build_user_agent(), "Accept": "application/json"},
        ) as response:
            raise_for_http_status(response.status_code, url)
            if response.status_code != 200:
                raise ValueError("figshare_metadata_unexpected_response")
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_JSON_BYTES:
                    raise ValueError("figshare_metadata_exceeds_limit")
    return json.loads(body), hashlib.sha256(body).hexdigest()


def _title(value):
    text = parse_html(value).visible_text if isinstance(value, str) else ""
    return "".join(
        c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum()
    )


def _record(record, identifier, doi, title):
    if not isinstance(record, dict) or record.get("id") != identifier:
        raise ValueError("figshare_record_identity_mismatch")
    if normalize_doi(record.get("resource_doi", "")) != doi or not re.fullmatch(
        re.escape(doi) + r"\.s\d+", normalize_doi(record.get("doi", ""))
    ):
        raise ValueError("figshare_parent_doi_mismatch")
    if not _title(title) or _title(record.get("resource_title")) != _title(title):
        raise ValueError("figshare_parent_title_mismatch")
    page = urlsplit(record.get("url_public_html", ""))
    if (
        page.scheme != "https"
        or page.netloc != "acs.figshare.com"
        or not page.path.startswith("/articles/")
        or page.path.rstrip("/").rsplit("/", 1)[-1] != str(identifier)
        or page.query
        or page.fragment
    ):
        raise ValueError("figshare_record_not_official_ACS")


def file_url_allowed(url, attachment):
    """Authorize only this manifest's file, including its scoped ACS S3 redirect."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.fragment:
        return False
    file_id = str(attachment.get("evidence", {}).get("file_id", ""))
    name = attachment.get("evidence", {}).get("filename", "")
    if not re.fullmatch(r"[1-9]\d*", file_id) or not name:
        return False
    if parts.netloc == "ndownloader.figshare.com":
        return parts.path == "/files/" + file_id and not parts.query
    if parts.netloc == "s3-eu-west-1.amazonaws.com":
        path = unquote(parts.path)
        return bool(
            re.fullmatch(r"/pstorage-acs-\d+/" + file_id + "/" + re.escape(name), path)
        )
    return False


def discover_acs_attachments(
    *,
    doi,
    title,
    timeout=30.0,
    max_bytes=100 * 1024 * 1024,
    allow_publisher_title=False,
):
    doi = normalize_doi(doi)
    if not doi.startswith("10.1021/") or (not title and not allow_publisher_title):
        return {"status": "NOT_SUPPORTED", "items": []}
    result = {"status": "NOT_FOUND", "items": [], "diagnostics": [], "errors": []}
    try:
        listing, search_hash = _read_json(
            API + "/search",
            timeout=timeout,
            search={"resource_doi": doi, "page": 1, "page_size": MAX_RECORDS + 1},
        )
        if not isinstance(listing, list) or len(listing) > MAX_RECORDS + 1:
            raise ValueError("figshare_invalid_search_response")
        if len(listing) > MAX_RECORDS:
            result["errors"].append(
                {"status": "PARTIAL", "error": "figshare_record_limit_reached"}
            )
        seen_records, seen_files = set(), set()
        resolved_title = title
        from .supplements import _SUFFIXES, attachment_role

        for entry in listing[:MAX_RECORDS]:
            try:
                identifier = entry.get("id") if isinstance(entry, dict) else None
                if (
                    type(identifier) is not int
                    or identifier < 1
                    or identifier in seen_records
                ):
                    raise ValueError("figshare_invalid_or_duplicate_record")
                seen_records.add(identifier)
                expected_title = resolved_title or entry.get("resource_title")
                _record(entry, identifier, doi, expected_title)
                detail, metadata_hash = _read_json(
                    API + f"/{identifier}", timeout=timeout
                )
                _record(detail, identifier, doi, expected_title)
                if (
                    detail.get("is_public") is not True
                    or detail.get("is_confidential") is not False
                    or detail.get("is_embargoed") is not False
                    or detail.get("status") != "public"
                ):
                    raise ValueError("figshare_record_not_public")
                resolved_title = expected_title
                if allow_publisher_title:
                    result["parent_title"] = resolved_title
                files = detail.get("files")
                if not isinstance(files, list) or len(files) > MAX_FILES:
                    raise ValueError("figshare_file_manifest_exceeds_limit")
                for file in files:
                    try:
                        if not isinstance(file, dict):
                            raise ValueError("figshare_invalid_file")
                        name, file_id = file.get("name"), file.get("id")
                        if (
                            not isinstance(name, str)
                            or not name
                            or name in {".", ".."}
                            or "/" in name
                            or "\\" in name
                            or any(ord(c) < 32 for c in name)
                            or type(file_id) is not int
                            or file_id < 1
                        ):
                            raise ValueError("figshare_invalid_file_identity")
                        extension = PurePosixPath(name).suffix.casefold()
                        size, checksum = file.get("size"), file.get("computed_md5")
                        if (
                            file.get("is_link_only") is not False
                            or extension not in _SUFFIXES
                        ):
                            raise ValueError("figshare_file_not_supported")
                        if type(size) is not int or size < 1 or size > max_bytes:
                            raise ValueError("figshare_file_exceeds_byte_limit")
                        if not isinstance(checksum, str) or not re.fullmatch(
                            r"[a-fA-F0-9]{32}", checksum
                        ):
                            raise ValueError("figshare_file_checksum_missing")
                        evidence = {
                            "record_id": identifier,
                            "version": detail.get("version"),
                            "file_id": file_id,
                            "filename": name,
                            "computed_md5": checksum.casefold(),
                            "size_bytes": size,
                            "resource_doi": doi,
                            "supplement_doi": detail["doi"],
                            "metadata_url": API + f"/{identifier}",
                            "metadata_sha256": metadata_hash,
                            "search_sha256": search_hash,
                        }
                        item = {
                            "url": file.get("download_url"),
                            "page": detail["url_public_html"],
                            "role": attachment_role(name) or "SUPPLEMENT",
                            "extension": extension,
                            "label": name,
                            "expected_md5": checksum.casefold(),
                            "expected_size": size,
                            "association_basis": BASIS,
                            "evidence": evidence,
                        }
                        if not isinstance(item["url"], str) or not file_url_allowed(
                            item["url"], item
                        ):
                            raise ValueError("figshare_file_host_not_covered")
                        if file_id in seen_files:
                            continue
                        if len(result["items"]) >= MAX_FILES:
                            raise ValueError("figshare_file_limit_reached")
                        seen_files.add(file_id)
                        result["items"].append(item)
                    except (ValueError, TypeError) as exc:
                        result["errors"].append(
                            {"status": "PARTIAL", "error": str(exc)}
                        )
            except (ValueError, TypeError) as exc:
                result["errors"].append(
                    {
                        "status": "FAILED",
                        "error": str(exc)
                        if isinstance(exc, ValueError)
                        else type(exc).__name__,
                    }
                )
        result["status"] = (
            "DISCOVERED"
            if result["items"]
            else "FAILED"
            if result["errors"]
            else "NOT_FOUND"
        )
    except Exception as exc:
        result["status"] = "FAILED"
        result["errors"].append({"status": "FAILED", "error": type(exc).__name__})
    result["diagnostics"].append(
        {
            "status": result["status"],
            "transport": "http",
            "source": "official_ACS_Figshare",
            "discovered": len(result["items"]),
        }
    )
    return result
