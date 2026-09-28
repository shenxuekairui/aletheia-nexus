"""Validated consumer API for source-linked parsed artifacts."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.schema import validate_parsed_document

_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)


@dataclass(frozen=True)
class SearchHit:
    block_id: str
    text: str
    kind: str
    page: int
    bbox: tuple[float, float, float, float] | None
    section_id: str | None
    section_heading: str | None
    score: float


class ParsedArtifact:
    """Read-only navigation over a validated parsed-document artifact."""

    def __init__(self, document: dict[str, object], *, path: Path | None = None):
        snapshot = deepcopy(document)
        validate_parsed_document(snapshot)
        self._document = snapshot
        self.path = path
        self._blocks = {str(item["id"]): item for item in snapshot["blocks"]}
        self._anchors = {str(item["id"]): item for item in snapshot["anchors"]}
        self._sections = {str(item["id"]): item for item in snapshot["sections"]}
        self._section_by_block: dict[str, dict[str, object]] = {}
        for section in snapshot["sections"]:
            for block_id in section["block_ids"]:
                self._section_by_block[str(block_id)] = section

    def _validate_integrity(self) -> None:
        validate_parsed_document(self._document)

    @property
    def document(self) -> dict[str, object]:
        """Return a validated snapshot, never a mutable alias to canonical state."""

        self._validate_integrity()
        return deepcopy(self._document)

    @classmethod
    def load(cls, path: str | Path) -> "ParsedArtifact":
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read parsed artifact: {exc}") from exc
        return cls(payload, path=source)

    def verify_local_sources(
        self,
        *,
        pdf_path: str | Path | None = None,
        sidecar_path: str | Path | None = None,
    ) -> dict[str, bool]:
        """Recheck local references without changing or reacquiring either file."""

        self._validate_integrity()
        source = self._document["source"]
        locators = source.get("locators", {})
        base = self.path.parent if self.path is not None else None
        checks: dict[str, bool] = {}
        for name, override, hash_key in (
            ("pdf", pdf_path, "pdf_sha256"),
            (
                "acquisition_sidecar",
                sidecar_path,
                "acquisition_sidecar_sha256",
            ),
        ):
            path = Path(override) if override is not None else None
            if path is None and base is not None and isinstance(locators, dict):
                locator = locators.get(name)
                if isinstance(locator, str):
                    path = base / locator
            checks[name] = bool(
                path is not None
                and path.is_file()
                and sha256_file(path) == source[hash_key]
            )
        return checks

    def section_text(self, section_id: str) -> str:
        self._validate_integrity()
        try:
            section = self._sections[section_id]
        except KeyError as exc:
            raise KeyError(f"unknown section: {section_id}") from exc
        return "\n".join(
            str(self._blocks[block_id]["text"]) for block_id in section["block_ids"]
        )

    def locate(self, block_id: str) -> dict[str, object]:
        self._validate_integrity()
        try:
            block = self._blocks[block_id]
        except KeyError as exc:
            raise KeyError(f"unknown block: {block_id}") from exc
        anchor = self._anchors[str(block["anchor_id"])]
        return {
            "block_id": block_id,
            "page": anchor["page"],
            "bbox": anchor["bbox"],
            "bbox_precision": anchor.get("bbox_precision"),
            "text_evidence": anchor["text_evidence"],
            "source_artifact_id": self._document["source"]["artifact_id"],
            "parsed_artifact_id": self._document["artifact_id"],
        }

    def search(
        self,
        query: str,
        *,
        section_type: str | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        self._validate_integrity()
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if limit < 1:
            raise ValueError("limit must be positive")
        phrase = " ".join(query.casefold().split())
        tokens = set(_TOKEN.findall(phrase))
        hits: list[SearchHit] = []
        for block in self._document["blocks"]:
            section = self._section_by_block.get(str(block["id"]))
            if section_type is not None and (
                section is None or section.get("semantic_type") != section_type
            ):
                continue
            text = str(block["text"])
            normalized = " ".join(text.casefold().split())
            block_tokens = set(_TOKEN.findall(normalized))
            overlap = len(tokens & block_tokens)
            if phrase not in normalized and overlap == 0:
                continue
            phrase_bonus = 2.0 if phrase in normalized else 0.0
            coverage = overlap / len(tokens) if tokens else 0.0
            density = overlap / len(block_tokens) if block_tokens else 0.0
            anchor = self._anchors[str(block["anchor_id"])]
            bbox = anchor["bbox"]
            hits.append(
                SearchHit(
                    block_id=str(block["id"]),
                    text=text,
                    kind=str(block["kind"]),
                    page=int(anchor["page"]),
                    bbox=tuple(bbox) if bbox is not None else None,
                    section_id=str(section["id"]) if section else None,
                    section_heading=str(section["heading"]) if section else None,
                    score=round(phrase_bonus + coverage + density, 6),
                )
            )
        hits.sort(key=lambda item: (-item.score, item.page, item.block_id))
        return hits[:limit]


def load_parsed_document(path: str | Path) -> ParsedArtifact:
    return ParsedArtifact.load(path)
