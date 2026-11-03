"""Follow only explicit supplementary landing pages, with a fresh DOI gate."""

from __future__ import annotations

import hashlib

import httpx

from aletheia_nexus.acquire.fulltext.resolution.transport import retrieve_page
from aletheia_nexus.core.urls import redact_url_for_record


def expand_supplement_pages(discovery, *, fetch, doi, title, timeout):
    from .supplements import _official_link, discover_attachments

    files, errors, diagnostics, seen = [], [], [], set()

    def exclusions(page):
        for item in page.get("excluded", []):
            diagnostics.append({"status": "EXCLUDED_ATTACHMENT", **item})
            if item.get("role") and item["reason"] in {
                "attachment_extension_not_supported",
                "publisher_attachment_identity_mismatch",
            }:
                errors.append({"status": "UNHANDLED_ATTACHMENT", **item})

    exclusions(discovery)
    truncated = discovery.get("truncated", False)
    pages = 0
    for item in discovery.get("items", []):
        if item.get("kind") != "page":
            files.append(item)
            continue
        if pages >= 2:
            truncated = True
            errors.append(
                {
                    "status": "SUPPLEMENT_PAGE_LIMIT",
                    "page": redact_url_for_record(item["url"]),
                }
            )
            continue
        pages += 1
        try:
            # Gate each redirect before network I/O for native HTTP, just like
            # file delivery. Custom/browser transports are checked again below.
            class OfficialPageClient(httpx.Client):
                def stream(self, method, url, *args, **kwargs):
                    if not _official_link(item["url"], str(url)):
                        raise ValueError("attachment_redirect_host_not_covered")
                    return super().stream(method, url, *args, **kwargs)

            if fetch is retrieve_page:
                with OfficialPageClient(follow_redirects=False) as client:
                    page = fetch(
                        item["url"],
                        timeout=timeout,
                        max_bytes=5 * 1024**2,
                        client=client,
                    )
            else:
                page = fetch(item["url"], timeout=timeout, max_bytes=5 * 1024**2)
            if not _official_link(item["url"], page.final_url) or any(
                not _official_link(item["url"], hop.to_url)
                for hop in getattr(page, "redirects", ())
            ):
                raise ValueError("attachment_redirect_host_not_covered")
            if not page.text or page.body_truncated:
                raise ValueError("invalid_supplement_landing_page")
            child = discover_attachments(
                page.text, page.final_url, doi=doi, title=title
            )
            exclusions(child)
            diagnostics.append(
                {
                    "status": child["status"],
                    "page": redact_url_for_record(page.final_url),
                    "source": "explicit_supplement_landing_page",
                }
            )
            if child["status"] != "DISCOVERED":
                errors.append(
                    {
                        "status": child["status"],
                        "page": redact_url_for_record(page.final_url),
                    }
                )
                continue
            truncated |= child.get("truncated", False)
            for candidate in child["items"]:
                if candidate.get("kind") == "page":
                    errors.append(
                        {
                            "status": "SUPPLEMENT_PAGE_DEPTH_LIMIT",
                            "page": redact_url_for_record(candidate["url"]),
                        }
                    )
                    truncated = True
                elif candidate["url"] not in seen:
                    seen.add(candidate["url"])
                    files.append(
                        {
                            **candidate,
                            "page": redact_url_for_record(page.final_url),
                            "evidence": {
                                "article_page": discovery["page_url"],
                                "supplement_page": redact_url_for_record(
                                    page.final_url
                                ),
                                "supplement_page_url_sha256": hashlib.sha256(
                                    item["url"].encode()
                                ).hexdigest(),
                            },
                        }
                    )
        except Exception as exc:
            errors.append(
                {
                    "status": "SUPPLEMENT_PAGE_FAILED",
                    "page": redact_url_for_record(item["url"]),
                    "error": type(exc).__name__,
                }
            )
    unique = {item["url"]: item for item in files}
    if len(unique) > 256:
        truncated = True
    return {
        "items": list(unique.values())[:256],
        "errors": errors,
        "diagnostics": diagnostics,
        "truncated": truncated,
    }
