"""Read-only catalogue presentation; every material/source identity stays intact."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

from aletheia_nexus.core.identifiers.doi import normalize_doi

_DISPLAY_FIELDS = (
    "title",
    "title_original",
    "title_zh",
    "custom_name",
    "authors",
    "first_author",
    "year",
    "journal",
)


def _catalog_key(row):
    fingerprint = row.get("pdf_sha256")
    if (
        row.get("integrity") == "verified"
        and row.get("document_role") == "ARTICLE"
        and row.get("identity_basis") == "acquisition_verified"
        and isinstance(fingerprint, str)
        and re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint)
    ):
        try:
            doi = normalize_doi(row.get("doi"))
        except (TypeError, ValueError):
            doi = None
        if doi:
            material = doi + ":" + fingerprint.casefold()
            return "catalog_" + hashlib.sha256(material.encode()).hexdigest()[:24]
    return "source_" + str(row["id"])


def catalog_groups(all_rows, matching_ids=None, selected_ids=None):
    """Project exact raw membership into safe paper rows, never new materials.

    Filter raw sources first and pass their IDs as matching_ids. Only these IDs
    are actionable member_ids. variants/all_member_ids show other available
    sources without adding them to a selection, collection or task. The row id
    always belongs to a matching raw source; catalog_key is display-only.
    """
    matching = None if matching_ids is None else set(matching_ids)
    selected = set(selected_ids or ())
    groups = {}
    for row in all_rows:
        groups.setdefault(_catalog_key(row), []).append(row)
    projected = []
    for key, variants in groups.items():
        members = [row for row in variants if matching is None or row["id"] in matching]
        if not members:
            continue
        primary = members[0]
        result = deepcopy(primary)
        result.update(
            catalog_key=key,
            member_ids=[row["id"] for row in members],
            all_member_ids=[row["id"] for row in variants],
            variants=deepcopy(variants),
            matched_variants=deepcopy(members),
            selected_member_ids=[row["id"] for row in members if row["id"] in selected],
            source_count=len(members),
            all_source_count=len(variants),
            is_catalog_group=len(variants) > 1,
            field_sources={},
            metadata_conflicts={},
        )
        for field in _DISPLAY_FIELDS:
            available = [row for row in variants if row.get(field)]
            if not result.get(field) and available:
                chosen = available[0]
                result[field] = deepcopy(chosen[field])
                result["field_sources"][field] = chosen["id"]
                if field == "title_zh":
                    result["translation"] = deepcopy(chosen.get("translation", {}))
            distinct = {
                json.dumps(row[field], ensure_ascii=False, sort_keys=True, default=str)
                for row in available
            }
            if len(distinct) > 1:
                result["metadata_conflicts"][field] = [
                    {"paper_id": row["id"], "value": deepcopy(row[field])}
                    for row in available
                ]
        result["mixed_fields"] = [
            field
            for field in (
                "folder",
                "tags",
                "collections",
                "parse_status",
                "ocr_status",
                "reading_status",
            )
            if len(
                {
                    json.dumps(row.get(field), sort_keys=True, default=str)
                    for row in members
                }
            )
            > 1
        ]
        projected.append(result)
    return projected
