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
        selected = [blocks[bid] for bid in ids if bid in blocks]
        if selected:
            last = max(b["order"] for b in selected)
            page = max(b["page"] for b in selected)
            following = [
                b
                for b in document["blocks"]
                if b["page"] in {page, page + 1} and b["order"] > last
            ][:3]
            # Include an immediately following table footnote and its continuation.
            if following and re.match(
                r"^(?:[a-z*†‡]\s*)?(?:reaction conditions?|conditions?|notes?|NMR|yields?\s+(?:were|are)|\w*determined)\b",
                following[0]["text"],
                re.IGNORECASE,
            ):
                for block in following:
                    if block["kind"] in {"heading", "caption"}:
                        break
                    selected.append(block)
                    ids.append(block["id"])
                    if "standard" in block["text"] or "NMR" in block["text"]:
                        break
        selected.sort(key=lambda block: block["order"])
        if not selected:
            continue
        boxes = [
            anchors[b["anchor_id"]]["bbox"]
            for b in selected
            if b.get("anchor_id") in anchors
            and anchors[b["anchor_id"]]["bbox"] is not None
        ]
        if boxes:
            bottom, top = min(box[1] for box in boxes), max(box[3] for box in boxes)
            left, right = min(box[0] for box in boxes), max(box[2] for box in boxes)
            pages = {b["page"] for b in selected}
            for block in document["blocks"]:
                if (
                    block.get("content_region") != "ocr-alternative"
                    or block["page"] not in pages
                    or block["id"] in ids
                ):
                    continue
                box = anchors[block["anchor_id"]]["bbox"]
                if (
                    box
                    and bottom <= (box[1] + box[3]) / 2 <= top
                    and box[0] < right
                    and box[2] > left
                ):
                    selected.append(block)
                    ids.append(block["id"])
        units.append(
            {
                "id": table["id"],
                "kind": "table",
                "uncertain": table.get("uncertain", True),
                "block_ids": [b["id"] for b in selected],
                "text": "\n".join(b["text"] for b in selected),
            }
        )
        consumed.update(ids)
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
