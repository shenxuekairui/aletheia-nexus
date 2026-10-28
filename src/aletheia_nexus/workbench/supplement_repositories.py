"""Discover explicit SI from the official version that supplied a PMC main PDF.

No PMCID lookup, publisher crawling, guessed attachment paths or bucket scan is
performed. Downloading/registering the discovered files remains the existing
attachment pipeline's responsibility.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit
from xml.etree import ElementTree

from aletheia_nexus.acquire.fulltext.transport import retrieve_to_temp
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.urls import redact_url_for_record

_HOST = "pmc-oa-opendata.s3.amazonaws.com"
_BUCKET = "https://" + _HOST
_XLINK = "{http://www.w3.org/1999/xlink}href"
_BASIS = "official_PMC_metadata_DOI_and_JATS_explicit_supplementary_material"
_MAX_DISCOVERY_CANDIDATES = 256
_MAX_DISCOVERED_FILES = 64


def _title(value):
    if not isinstance(value, str):
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum()
    )


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _prefix(record):
    retrieval = record.get("retrieval") or {}
    candidate = record.get("candidate") or {}
    if not isinstance(retrieval, dict) or not isinstance(candidate, dict):
        return None
    # Prefer the actual final origin; a different final origin must not inherit
    # a stale PMC candidate. Candidate-only records may still name a real route.
    value = retrieval.get("final_url") or candidate.get("url")
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc.casefold() != _HOST:
        return None
    match = re.fullmatch(r"/(PMC\d+\.[1-9]\d*)/\1\.pdf", parts.path)
    return match.group(1) if match else None


def _object(value, prefix):
    """Return only the exact object explicitly listed by official metadata."""
    if not isinstance(value, str):
        raise ValueError("官方 PMC 元数据缺少明确的文件地址")
    parts = urlsplit(value)
    if parts.scheme != "s3" or parts.netloc != "pmc-oa-opendata" or parts.fragment:
        raise ValueError("官方 PMC 文件地址不属于受支持的官方存档")
    beginning = "/" + prefix + "/"
    if not parts.path.startswith(beginning):
        raise ValueError("官方 PMC 文件地址与已验证正文版本不一致")
    name = unquote(parts.path[len(beginning) :])
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("官方 PMC 文件地址包含不安全或不受支持的相对路径")
    query = parse_qs(parts.query, keep_blank_values=True)
    checksums = query.get("md5", [])
    if (
        set(query) != {"md5"}
        or len(checksums) != 1
        or not re.fullmatch("[a-fA-F0-9]{32}", checksums[0])
    ):
        raise ValueError("官方 PMC 官方文件清单缺少唯一的完整校验值")
    return (
        name,
        urlunsplit(("https", _HOST, parts.path, parts.query, "")),
        checksums[0].casefold(),
    )


def _read(url, directory, maximum, timeout):
    resource = retrieve_to_temp(
        url,
        output_dir=directory,
        max_bytes=maximum,
        timeout=timeout,
        max_redirects=2,
    )
    try:
        # The shared transport checks every redirect for public network safety.
        # This repository additionally forbids moving evidence off its bucket.
        final, requested = urlsplit(resource.final_url), urlsplit(url)
        if (
            final.scheme != "https"
            or final.netloc.casefold() != _HOST
            or final.path != requested.path
        ):
            raise ValueError("官方 PMC 官方身份材料被重定向到其他来源")
        data = resource.local_path.read_bytes()
        if len(data) > maximum:
            raise ValueError("官方 PMC 身份材料超过大小限制")
        return data, {
            "url": redact_url_for_record(url),
            "final_url": redact_url_for_record(resource.final_url),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
    finally:
        resource.local_path.unlink(missing_ok=True)


def _parent(metadata, article, prefix, doi, expected_title):
    pmcid, version = prefix.split(".")
    if (
        metadata.get("pmcid") != pmcid
        or type(metadata.get("version")) is not int
        or metadata["version"] != int(version)
        or normalize_doi(metadata.get("doi")) != doi
        or metadata.get("is_pmc_openaccess") is not True
        or metadata.get("is_retracted") is not False
    ):
        raise ValueError("官方 PMC 元数据身份、版本或开放获取状态与正文不一致")
    front = article.find("{*}front/{*}article-meta")
    if _local(article.tag) != "article" or front is None:
        raise ValueError("官方 PMC 文档不是可识别的父文 JATS 记录")
    ids = [node for node in front if _local(node.tag) == "article-id"]
    dois = {
        normalize_doi("".join(node.itertext()).strip())
        for node in ids
        if node.get("pub-id-type") == "doi"
    }
    if dois != {doi}:
        raise ValueError("官方 PMC 文档没有唯一匹配的父文 DOI")
    for kind, expected in (("pmcid", pmcid), ("pmcid-ver", prefix)):
        values = {
            "".join(node.itertext()).strip()
            for node in ids
            if node.get("pub-id-type") == kind
        }
        if values and values != {expected}:
            raise ValueError("官方 PMC 文档的存档编号与正文版本不一致")
    titles = front.findall("{*}title-group/{*}article-title")
    title = " ".join(titles[0].itertext()) if len(titles) == 1 else ""
    canonical = _title(metadata.get("title"))
    if (
        not canonical
        or _title(title) != canonical
        or (expected_title and _title(expected_title) != canonical)
    ):
        raise ValueError("官方 PMC 父文题名未能与正文及元数据一致匹配")


def _supplement_nodes(article, context=""):
    for node in article:
        kind = _local(node.tag)
        if kind in {"sub-article", "response", "ref-list"}:
            continue
        title = next(
            (" ".join(c.itertext()) for c in node if _local(c.tag) == "title"), ""
        )
        label = " ".join(filter(None, (context, title)))
        if kind == "supplementary-material":
            yield node, label
        else:
            yield from _supplement_nodes(node, label)


def discover_pmc_attachments(
    source_record: dict,
    *,
    doi: str,
    title: str | None = None,
    timeout: float = 20,
    max_metadata_bytes: int = 1024 * 1024,
    max_xml_bytes: int = 5 * 1024 * 1024,
) -> dict:
    """Return DOI/JATS-bound links, without fetching or registering attachments.

    ``source_record`` must be the original sidecar already checked by the main
    PDF gate. Only its actual official PMC Cloud article-version origin enables
    this route. Missing/ambiguous identities fail independently of main status.
    """
    if not isinstance(source_record, dict) or not (prefix := _prefix(source_record)):
        return {"status": "NOT_SUPPORTED", "items": [], "errors": []}
    page = f"{_BUCKET}/metadata/{prefix}.json"
    provenance = {"source": "official_pmc_cloud", "version_prefix": prefix}
    try:
        doi = normalize_doi(doi)
        target = source_record.get("target") or {}
        identity = source_record.get("identity_validation") or {}
        if not isinstance(target, dict) or not isinstance(identity, dict):
            raise ValueError("官方 PMC 正文来源记录的身份字段不是有效对象")
        if (
            source_record.get("status") != "VERIFIED"
            or identity.get("status") != "MATCH"
            or identity.get("document_role") != "ARTICLE"
            or normalize_doi(target.get("doi")) != doi
        ):
            raise ValueError("官方 PMC 附件路线需要已验证且身份一致的正文来源记录")
        expected_title = title or target.get("expected_title")
        if (
            title
            and target.get("expected_title")
            and _title(title) != _title(target["expected_title"])
        ):
            raise ValueError("官方 PMC 附件的请求题名与已验证正文原题不一致")
        with TemporaryDirectory(prefix="aletheia-pmc-si-") as directory:
            data, metadata_evidence = _read(
                page, directory, max_metadata_bytes, timeout
            )
            metadata = json.loads(data.decode("utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("官方 PMC 官方元数据必须是单个对象")
            # Verify parent metadata before retrieving any linked XML.
            if (
                normalize_doi(metadata.get("doi")) != doi
                or metadata.get("pmcid") != prefix.split(".")[0]
                or type(metadata.get("version")) is not int
                or metadata["version"] != int(prefix.split(".")[1])
                or metadata.get("is_pmc_openaccess") is not True
                or metadata.get("is_retracted") is not False
                or not _title(metadata.get("title"))
                or (
                    expected_title
                    and _title(metadata.get("title")) != _title(expected_title)
                )
            ):
                raise ValueError("官方 PMC 元数据身份、版本或开放获取状态与正文不一致")
            name, xml_url, xml_md5 = _object(metadata.get("xml_url"), prefix)
            if name != prefix + ".xml":
                raise ValueError("官方 PMC 元数据的文档地址与正文版本不一致")
            xml, xml_evidence = _read(xml_url, directory, max_xml_bytes, timeout)
            if hashlib.md5(xml).hexdigest() != xml_md5:
                raise ValueError("官方 PMC 文档内容与官方文件清单的校验值不一致")
            if b"<!ENTITY" in xml.upper():
                raise ValueError("官方 PMC 文档包含不受支持的实体声明")
            article = ElementTree.fromstring(xml)
            _parent(metadata, article, prefix, doi, expected_title)
        provenance.update(
            metadata=metadata_evidence,
            xml=xml_evidence,
            doi=doi,
            title=metadata["title"],
        )
        media = metadata.get("media_urls", [])
        if not isinstance(media, list) or len(media) > 2000:
            raise ValueError("官方 PMC 媒体清单无效或超过安全数量限制")
        # Index names once, without authorizing any URL. Keep all candidates,
        # including duplicates/wrong origins: only the explicit JATS filename
        # selects entries for the unchanged strict _object gate below.
        media_by_name = {}
        for value in media:
            if not isinstance(value, str):
                continue
            try:
                basename = PurePosixPath(unquote(urlsplit(value).path)).name
            except ValueError:
                continue
            media_by_name.setdefault(basename, []).append(value)
        # Reuse existing role and extension policy without a second downloader.
        from .supplements import _SUFFIXES, attachment_role

        items, errors, seen = [], [], set()
        scanned, scanned_nodes, truncated = 0, 0, False
        for node, context in _supplement_nodes(article):
            if scanned_nodes >= _MAX_DISCOVERY_CANDIDATES:
                truncated = True
                errors.append(
                    {
                        "status": "PARTIAL",
                        "error": "官方 PMC 补充材料节点达到安全扫描上限，仍有节点未核对。",
                        "page": page,
                    }
                )
                break
            scanned_nodes += 1
            label = " ".join(
                filter(
                    None,
                    (context, node.get("content-type"), " ".join(node.itertext())),
                )
            )[:2000].strip()
            links = (child.get(_XLINK) for child in node.iter() if child.get(_XLINK))
            has_link = False
            for href in links:
                has_link = True
                if scanned >= _MAX_DISCOVERY_CANDIDATES:
                    truncated = True
                    errors.append(
                        {
                            "status": "PARTIAL",
                            "error": "官方 PMC 补充材料候选达到安全扫描上限，仍有链接未核对。",
                            "page": page,
                        }
                    )
                    break
                scanned += 1
                try:
                    decoded = unquote(href)
                    if (
                        not decoded
                        or urlsplit(href).scheme
                        or decoded != PurePosixPath(decoded).name
                        or "\\" in decoded
                        or decoded in {".", ".."}
                    ):
                        raise ValueError(
                            "官方 PMC 补充材料链接不是受支持的本版本相对文件"
                        )
                    matches = [
                        _object(value, prefix)
                        for value in media_by_name.get(decoded, ())
                    ]
                    if len(matches) != 1:
                        raise ValueError("官方 PMC 补充材料与官方媒体清单无法唯一对应")
                    _, url, expected_md5 = matches[0]
                    extension = Path(decoded).suffix.casefold()
                    if extension not in _SUFFIXES:
                        raise ValueError("官方 PMC 补充材料的文件类型尚未支持")
                    if url in seen:
                        continue
                    if len(items) >= _MAX_DISCOVERED_FILES:
                        truncated = True
                        errors.append(
                            {
                                "status": "PARTIAL",
                                "error": "官方 PMC 补充材料数量达到安全上限，仍有文件未核对。",
                                "page": page,
                            }
                        )
                        break
                    seen.add(url)
                    items.append(
                        {
                            "url": url,
                            "role": attachment_role(label, href) or "SUPPLEMENT",
                            "label": label or "补充材料",
                            "extension": extension,
                            "page": page,
                            "association_basis": _BASIS,
                            "expected_md5": expected_md5,
                            "evidence": {**provenance, "relative_file": href},
                        }
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    errors.append({"status": "FAILED", "error": str(exc), "page": page})
            if truncated:
                break
            if not has_link:
                errors.append(
                    {
                        "status": "FAILED",
                        "error": "官方 PMC 补充材料节点缺少明确文件链接",
                        "page": page,
                    }
                )
        return {
            "status": "PARTIAL"
            if truncated
            else "DISCOVERED"
            if items
            else "FAILED"
            if errors
            else "NOT_FOUND",
            "items": items,
            "errors": errors,
            "partial": bool(errors),
            "truncated": truncated,
            "scanned_candidates": scanned,
            "scanned_nodes": scanned_nodes,
            "page_url": page,
            "parent_identity": _BASIS,
            "provenance": provenance,
        }
    except (
        OSError,
        ValueError,
        RuntimeError,
        TypeError,
        ElementTree.ParseError,
    ) as exc:
        return {
            "status": "FAILED",
            "items": [],
            "errors": [{"status": "FAILED", "error": str(exc), "page": page}],
            "page_url": page,
            "provenance": provenance,
        }
