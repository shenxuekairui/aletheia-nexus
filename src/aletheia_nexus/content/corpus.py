"""Directory-based research search. No database, embeddings, or remote service."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from aletheia_nexus.content.artifact import ParsedArtifact
from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.query import match_score, query_terms
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path


@dataclass
class CorpusDocument:
    path: Path
    pdf: Path
    artifact: ParsedArtifact
    document: dict[str, object]


@dataclass
class Corpus:
    root: Path
    documents: list[CorpusDocument]
    unsearched: list[dict[str, object]]
    duplicates: list[dict[str, object]]

    @property
    def coverage(self) -> dict[str, object]:
        statuses = Counter(item.document["status"] for item in self.documents)
        return {
            "completed": statuses["PARSED"],
            "partial": statuses["PARTIAL"],
            "failed": sum("artifact" in item for item in self.unsearched),
            "searched_documents": len(self.documents),
            "unsearched": self.unsearched,
            "duplicates": self.duplicates,
            "partial_documents": [
                {
                    "artifact": item.path.relative_to(self.root).as_posix(),
                    "status": item.document["status"],
                    "quality": item.document["quality"],
                    "warnings": item.document["warnings"],
                    "errors": item.document["errors"],
                }
                for item in self.documents
                if item.document["status"] != "PARSED"
            ],
            "complete": not self.unsearched
            and not statuses["PARTIAL"]
            and not statuses["FAILED"],
        }


def load_corpus(root: str | Path) -> Corpus:
    directory = Path(root).resolve()
    if not directory.is_dir():
        raise ValueError(f"corpus is not a directory: {directory}")
    pdfs: dict[str, list[Path]] = {}
    unsearched: list[dict[str, object]] = []
    for pdf in sorted(directory.rglob("*.pdf")):
        if not pdf.resolve().is_relative_to(directory):
            unsearched.append(
                {
                    "pdf": pdf.relative_to(directory).as_posix(),
                    "reason": "PDF link points outside the selected corpus directory",
                }
            )
            continue
        try:
            pdfs.setdefault(sha256_file(pdf), []).append(pdf)
        except OSError as exc:
            unsearched.append(
                {"pdf": pdf.relative_to(directory).as_posix(), "reason": str(exc)}
            )
    candidates: dict[str, list[CorpusDocument]] = {}
    seen: set[str] = set()
    for path in sorted(directory.rglob("*.parsed.json")):
        if not path.resolve().is_relative_to(directory):
            continue
        try:
            artifact = ParsedArtifact.load(path)
            document = artifact.document
            source = document["source"]
            digest = source["pdf_sha256"]
            seen.add(digest)
            matches = pdfs.get(digest, [])
            if not matches:
                raise ValueError("source PDF is missing or changed")
            pdf_locator = source.get("locators", {}).get("pdf")
            located = (path.parent / pdf_locator).resolve() if pdf_locator else None
            if located is not None and located.is_file() and located not in matches:
                raise ValueError("recorded PDF locator now points to a different file")
            pdf = located if located in matches else matches[0]
            sidecar_locator = source.get("locators", {}).get("acquisition_sidecar")
            sidecar = (
                path.parent / sidecar_locator
                if sidecar_locator
                else acquisition_sidecar_path(pdf)
            )
            if (
                not sidecar.is_file()
                or sha256_file(sidecar) != source["acquisition_sidecar_sha256"]
            ):
                # Relocation may have moved json/ sidecars along with their PDF.
                sidecar = acquisition_sidecar_path(pdf)
            if (
                not sidecar.is_file()
                or sha256_file(sidecar) != source["acquisition_sidecar_sha256"]
            ):
                raise ValueError(
                    "source identity/role record is missing or changed; reparse explicitly"
                )
            gated = validate_parser_input(pdf, source["doi"], sidecar_path=sidecar)
            if (
                gated.doi != source["doi"]
                or gated.document_role != source.get("document_role", "ARTICLE")
                or gated.parent != source.get("parent")
            ):
                raise ValueError(
                    "parsed document role or parent disagrees with its source record"
                )
            if document["schema"] == "aletheia-nexus/parsed-document/v3" and any(
                source.get(key) != getattr(gated, key)
                for key in ("title", "article_id", "identity_basis")
            ):
                raise ValueError("parsed identity disagrees with its source record")
            if document["status"] == "FAILED":
                raise ValueError("parsing failed; this document was not searched")
            candidates.setdefault(digest, []).append(
                CorpusDocument(path, pdf, artifact, document)
            )
        except (OSError, ValueError) as exc:
            unsearched.append(
                {"artifact": path.relative_to(directory).as_posix(), "reason": str(exc)}
            )
    documents: list[CorpusDocument] = []
    duplicates: list[dict[str, object]] = []
    for digest, copies in sorted(candidates.items()):
        identities = {
            json.dumps(
                {
                    "doi": item.document["source"].get("doi"),
                    "document_role": item.document["source"].get(
                        "document_role", "ARTICLE"
                    ),
                    "parent": item.document["source"].get("parent"),
                },
                sort_keys=True,
            )
            for item in copies
        }
        if len(identities) > 1:
            unsearched.append(
                {
                    "pdf_sha256": digest,
                    "reason": "conflicting identities/roles for identical PDF bytes",
                }
            )
            continue
        copies.sort(
            key=lambda item: (
                item.document["created_at"],
                item.document["artifact_id"],
                str(item.path),
            ),
            reverse=True,
        )
        chosen = copies[0]
        documents.append(chosen)
        duplicate_paths = [
            p.relative_to(directory).as_posix() for p in pdfs[digest] if p != chosen.pdf
        ]
        duplicate_parses = [
            item.path.relative_to(directory).as_posix() for item in copies[1:]
        ]
        if duplicate_paths or duplicate_parses:
            duplicates.append(
                {
                    "pdf_sha256": digest,
                    "pdfs": duplicate_paths,
                    "parsed_artifacts": duplicate_parses,
                }
            )
    for digest, paths in sorted(pdfs.items()):
        if digest not in seen:
            unsearched.append(
                {
                    "pdfs": [p.relative_to(directory).as_posix() for p in paths],
                    "reason": "not parsed",
                }
            )
    return Corpus(directory, documents, unsearched, duplicates)


def content_units(document: dict[str, object]) -> list[dict[str, object]]:
    """Paragraphs and observed tables, with table captions kept in the same unit."""
    blocks = {block["id"]: block for block in document["blocks"]}
    anchors = {anchor["id"]: anchor for anchor in document.get("anchors", [])}
    units = []
    consumed: set[str] = set()
    for table in document["tables"]:
        ids = list(
            dict.fromkeys(
                [table["caption_block_id"], *table.get("object_block_ids", [])]
            )
        )
        if len(ids) < 2:
            continue
        selected = [
            blocks[bid]
            for bid in ids
            if bid in blocks
            and not blocks[bid].get("content_region", "").endswith("alternative")
        ]
        ids = [b["id"] for b in selected]
        if selected:
            last = max(b["order"] for b in selected)
            page = max(b["page"] for b in selected)
            following = [
                b
                for b in document["blocks"]
                if b["page"] in {page, page + 1}
                and b["order"] > last
                and not b.get("content_region", "").endswith("alternative")
            ][:6]
            # Include an immediately following table footnote and its continuation.
            if following and re.match(
                r"^(?:[a-z*†‡](?=[A-Z])|(?i:(?:[a-z*†‡]\s*)?(?:reaction conditions?|conditions?|notes?|NMR|yields?\s+(?:were|are)|\w*determined)\b))",
                following[0]["text"],
            ):
                for block in following:
                    if block["kind"] in {"heading", "caption"}:
                        break
                    if (
                        block is not following[0]
                        and selected[-1]["text"].rstrip().endswith((".", "。"))
                        and not re.match(r"^[a-z*†‡](?=[A-Z])", block["text"])
                    ):
                        break
                    selected.append(block)
                    ids.append(block["id"])
        selected.sort(key=lambda block: block["order"])
        if not selected:
            continue
        cells = table.get("cells", [])
        numeric_counts = Counter(
            c["row"] for c in cells if re.match(r"^[−+±\-]?\s*\d", c["text"])
        )
        numeric_rows = {row for row, count in numeric_counts.items() if count >= 2}
        first_data = min(numeric_rows, default=0)
        cell_ids = {c["block_id"] for c in cells}
        context_ids = {b["id"] for b in selected if b["id"] not in cell_ids}
        header_ids = {c["block_id"] for c in cells if c["row"] < first_data}
        segments = []
        for row in sorted(numeric_rows):
            row_ids = {
                c["block_id"]
                for c in cells
                if c["row"] <= row < c["row"] + c.get("row_span", 1)
            }
            members = [
                b for b in selected if b["id"] in row_ids | header_ids | context_ids
            ]
            segments.append(
                {
                    "row": row,
                    "block_ids": [b["id"] for b in members],
                    "text": "\n".join(b["text"] for b in members),
                }
            )
        units.append(
            {
                "id": table["id"],
                "kind": "table",
                "uncertain": table.get("uncertain", True),
                "block_ids": [b["id"] for b in selected],
                "text": "\n".join(b["text"] for b in selected),
                "row_contexts": segments,
            }
        )
        consumed.update(ids)
    # Associate image text with its existing source-object/caption evidence.
    # Co-occurrence is useful for retrieval, but does not interpret plotted data.
    for figure in document.get("figures", []):
        caption = blocks.get(figure["caption_block_id"])
        objects = [
            obj
            for obj in figure.get("source_objects", [])
            if obj.get("bbox")
            and (obj["bbox"][2] - obj["bbox"][0]) * (obj["bbox"][3] - obj["bbox"][1])
            < 0.65
        ]
        if caption is None or not objects:
            continue
        members = [caption]
        for block in document["blocks"]:
            if (
                block["id"] == caption["id"]
                or block["id"] in consumed
                or block.get("content_region", "").endswith("alternative")
            ):
                continue
            anchor = anchors.get(block.get("anchor_id"), {})
            if any(
                obj.get("page") == block["page"]
                and _contains_reading(obj.get("bbox"), anchor.get("bbox"))
                for obj in objects
            ):
                members.append(block)
        if len(members) < 2:
            continue
        members.sort(key=lambda b: b["order"])
        units.append(
            {
                "id": figure["id"],
                "kind": "figure",
                "uncertain": True,
                "block_ids": [b["id"] for b in members],
                "text": "\n".join(b["text"] for b in members),
                "interpretation_status": "source-region-not-interpreted",
            }
        )
        # A caption or an individual image label remains a direct search unit.
        # The region provides additional context without replacing that hit.
    units.extend(
        {
            "id": block["id"],
            "kind": block["kind"],
            "block_ids": [block["id"]],
            "text": block["text"],
        }
        for block in document["blocks"]
        if block["id"] not in consumed
    )
    # Bounded nearby prose helps find conditions split across paragraph blocks.
    # Do not cross pages, headings or table/image regions, and do not combine
    # OCR alternatives with primary text to manufacture an AND match.
    primary = [
        b
        for b in document["blocks"]
        if not b.get("content_region", "").endswith("alternative")
    ]
    for index, start in enumerate(primary):
        members = []
        for block in primary[index : index + 4]:
            if (
                block["page"] != start["page"]
                or block["id"] in consumed
                or block["kind"] not in {"paragraph", "text", "equation"}
                or block.get("content_region", "body") != "body"
            ):
                break
            if sum(len(b["text"]) for b in members) + len(block["text"]) > 2400:
                break
            members.append(block)
        if len(members) >= 2:
            units.append(
                {
                    "id": f"context:{start['id']}:{members[-1]['id']}",
                    "kind": "context",
                    "block_ids": [b["id"] for b in members],
                    "text": "\n".join(b["text"] for b in members),
                    "interpretation_status": "nearby-context-not-interpreted",
                }
            )
    return units


def search_corpus(
    corpus: Corpus | str | Path,
    query: str,
    *,
    mode: str = "and",
    exact: bool = False,
    limit: int = 20,
    role: str | None = None,
    section_type: str | None = None,
) -> dict[str, object]:
    terms = query_terms(query, exact=exact)
    if limit < 1 or mode not in {"and", "or"}:
        raise ValueError("limit must be positive; mode must be and or or")
    if role not in {None, "ARTICLE", "SUPPLEMENT"}:
        raise ValueError("role must be ARTICLE or SUPPLEMENT")
    loaded = corpus if isinstance(corpus, Corpus) else load_corpus(corpus)
    hits = []
    alternative_ids: set[str] = set()
    searched_documents = 0
    searched_units = 0
    excluded = []
    for entry in loaded.documents:
        document = entry.document
        source = document["source"]
        if role and source.get("document_role", "ARTICLE") != role:
            excluded.append(
                {
                    "pdf": entry.pdf.relative_to(loaded.root).as_posix(),
                    "reason": "document role filter",
                }
            )
            continue
        blocks = {b["id"]: b for b in document["blocks"]}
        anchors = {a["id"]: a for a in document["anchors"]}
        sections = {
            bid: section
            for section in document["sections"]
            for bid in section["block_ids"]
        }
        document_units = 0
        for unit in content_units(document):
            section = sections.get(unit["block_ids"][0])
            if section_type and (
                not section or section["semantic_type"] != section_type
            ):
                continue
            document_units += 1
            score = match_score(unit["text"], terms, mode=mode)
            if score is None:
                continue
            matching_rows = []
            for row in unit.get("row_contexts", []):
                row_score = match_score(row["text"], terms, mode=mode)
                if row_score is not None:
                    matching_rows.append({**row, "score": row_score})
            if matching_rows:
                score = max(r["score"] for r in matching_rows)
            if unit["kind"] == "context":
                score -= 0.05  # Prefer a direct match over surrounding prose.
            evidence = [anchors[blocks[bid]["anchor_id"]] for bid in unit["block_ids"]]
            stable = hashlib.sha256(
                (document["artifact_id"] + ":" + unit["id"]).encode()
            ).hexdigest()
            hits.append(
                {
                    "id": "hit:" + stable,
                    "artifact": entry.path.relative_to(loaded.root).as_posix(),
                    "parsed_artifact_id": document["artifact_id"],
                    "source": source,
                    "pdf": entry.pdf.relative_to(loaded.root).as_posix(),
                    "status": document["status"],
                    "unit_id": unit["id"],
                    "kind": unit["kind"],
                    "block_ids": unit["block_ids"],
                    "text": unit["text"],
                    "pages": sorted({e["page"] for e in evidence}),
                    "evidence": evidence,
                    "score": score,
                    "matching_rows": matching_rows,
                    "interpretation_status": unit.get(
                        "interpretation_status", "not-interpreted"
                    ),
                    "section": section["heading"] if section else None,
                    "uncertain": unit.get("uncertain", False)
                    or any(
                        blocks[bid].get("uncertain", False) for bid in unit["block_ids"]
                    ),
                }
            )
            if all(
                blocks[bid].get("content_region")
                in {"ocr-alternative", "native-alternative"}
                for bid in unit["block_ids"]
            ):
                alternative_ids.add("hit:" + stable)
        searched_units += document_units
        if document_units:
            searched_documents += 1
        else:
            excluded.append(
                {
                    "pdf": entry.pdf.relative_to(loaded.root).as_posix(),
                    "reason": "no content units in selected scope",
                }
            )
    # A short OCR alternative must not crowd out other evidence just because it
    # has a higher word density than the matching paragraph at the same place.
    # Keep every reading; defer only alternatives already represented spatially
    # by another hit for this query. Unique recovered matches keep their rank.
    primary_by_page: dict[tuple[str, int], list[dict]] = {}
    for hit in hits:
        if hit["id"] not in alternative_ids:
            for anchor in hit["evidence"]:
                primary_by_page.setdefault(
                    (hit["parsed_artifact_id"], anchor["page"]), []
                ).append(anchor)
    repeated_readings: set[str] = set()
    for hit in hits:
        if hit["kind"] in {"context", "figure"} and any(
            other["parsed_artifact_id"] == hit["parsed_artifact_id"]
            and other["kind"] not in {"context", "figure"}
            and other["id"] not in alternative_ids
            and set(other["block_ids"]) <= set(hit["block_ids"])
            for other in hits
        ):
            repeated_readings.add(hit["id"])
    # Sliding windows of the same passage must not occupy the entire result
    # page. Keep them available after distinct passages; do not discard text.
    distinct_contexts = []
    for hit in sorted(hits, key=lambda h: (-h["score"], h["id"])):
        if hit["kind"] != "context" or hit["id"] in repeated_readings:
            continue
        if any(
            other["parsed_artifact_id"] == hit["parsed_artifact_id"]
            and len(set(other["block_ids"]) & set(hit["block_ids"]))
            >= min(len(other["block_ids"]), len(hit["block_ids"])) / 2
            for other in distinct_contexts
        ):
            repeated_readings.add(hit["id"])
        else:
            distinct_contexts.append(hit)
    for hit in hits:
        if hit["id"] in alternative_ids and all(
            any(
                _contains_reading(primary.get("bbox"), anchor.get("bbox"))
                for primary in primary_by_page.get(
                    (hit["parsed_artifact_id"], anchor["page"]), []
                )
            )
            for anchor in hit["evidence"]
        ):
            repeated_readings.add(hit["id"])
    hits.sort(
        key=lambda h: (
            h["id"] in repeated_readings,
            -h["score"],
            h["source"].get("title") or "",
            h["source"]["pdf_sha256"],
            h["pages"],
            h["id"],
        )
    )
    total = len(hits)
    hits = [{"number": n, **hit} for n, hit in enumerate(hits[:limit], 1)]
    return {
        "schema": "aletheia-nexus/search-results/v1",
        "query": {
            "text": query,
            "terms": list(terms),
            "mode": mode,
            "exact": exact,
            "role": role,
            "section_type": section_type,
        },
        "coverage": loaded.coverage,
        "search_scope": {
            "searched_documents": searched_documents,
            "searched_units": searched_units,
            "excluded_documents": excluded,
        },
        "total_hits": total,
        "returned_hits": len(hits),
        "limit": limit,
        "hits": hits,
        "interpretation": "No hit means no literal match in the searched content; incomplete coverage is not evidence of absence.",
    }


def _contains_reading(primary: list | None, alternative: list | None) -> bool:
    if primary is None or alternative is None:
        return False
    x0, y0, x1, y1 = alternative
    area = max(0, x1 - x0) * max(0, y1 - y0)
    intersection = max(0, min(primary[2], x1) - max(primary[0], x0)) * max(
        0, min(primary[3], y1) - max(primary[1], y0)
    )
    return area > 0 and intersection / area >= 0.8
