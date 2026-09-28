"""Deterministic, model-agnostic views derived from parsed-document/v2."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from aletheia_nexus.content.artifact import ParsedArtifact

AI_EXPORT_SCHEMA = "aletheia-nexus/ai-export/v1"
EXPORTER_NAME = "canonical-document-exporter"
EXPORTER_VERSION = "1.0.0"


@dataclass(frozen=True)
class ChunkConfig:
    """Deterministic structure-aware chunking controls."""

    max_characters: int = 6000

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_characters, bool)
            or not isinstance(self.max_characters, int)
            or self.max_characters < 256
        ):
            raise ValueError("max_characters must be an integer of at least 256")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _artifact(value: ParsedArtifact | dict[str, object]) -> ParsedArtifact:
    return value if isinstance(value, ParsedArtifact) else ParsedArtifact(value)


def _split_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        boundary = remaining.rfind(" ", 0, limit + 1)
        if boundary < limit // 2:
            boundary = limit
        pieces.append(remaining[:boundary].rstrip())
        remaining = remaining[boundary:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def structure_aware_chunks(
    value: ParsedArtifact | dict[str, object],
    *,
    config: ChunkConfig | None = None,
) -> dict[str, object]:
    """Build chunks that preserve section and semantic-block boundaries."""

    artifact = _artifact(value)
    document = artifact.document
    selected = config or ChunkConfig()
    anchors = {str(item["id"]): item for item in document["anchors"]}
    section_by_block: dict[str, dict[str, object]] = {}
    for section in document["sections"]:
        for block_id in section["block_ids"]:
            section_by_block[str(block_id)] = section

    groups: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_section: str | None = None
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars, current_section
        if current:
            groups.append(current)
        current = []
        current_chars = 0
        current_section = None

    for block in sorted(document["blocks"], key=lambda item: int(item["order"])):
        block_id = str(block["id"])
        section = section_by_block.get(block_id)
        section_id = str(section["id"]) if section else None
        kind = str(block["kind"])
        text = str(block["text"])
        isolated = kind in {"heading", "caption", "equation", "reference"}
        if current and (
            section_id != current_section
            or isolated
            or current_chars + 2 + len(text) > selected.max_characters
        ):
            flush()
        if isolated:
            groups.append([block])
            continue
        if not current:
            current_section = section_id
        current.append(block)
        current_chars += len(text) + (2 if current_chars else 0)
    flush()

    chunks: list[dict[str, object]] = []
    for group in groups:
        combined = "\n\n".join(str(block["text"]) for block in group)
        for part_index, text in enumerate(
            _split_text(combined, selected.max_characters), start=1
        ):
            evidence = []
            for block in group:
                anchor = anchors[str(block["anchor_id"])]
                evidence.append(
                    {
                        "block_id": block["id"],
                        "anchor_id": anchor["id"],
                        "page": anchor["page"],
                        "bbox": anchor["bbox"],
                        "coordinate_system": anchor["coordinate_system"],
                    }
                )
            section = section_by_block.get(str(group[0]["id"]))
            chunk_payload = {
                "source_artifact_id": document["source"]["artifact_id"],
                "parsed_artifact_id": document["artifact_id"],
                "block_ids": [block["id"] for block in group],
                "part": part_index,
                "text": text,
            }
            chunks.append(
                {
                    "id": f"chunk:{_fingerprint(chunk_payload)[:24]}",
                    "kind": (
                        str(group[0]["kind"]) if len(group) == 1 else "section-content"
                    ),
                    "section": (
                        {
                            "id": section["id"],
                            "heading": section["heading"],
                            "semantic_type": section["semantic_type"],
                        }
                        if section
                        else None
                    ),
                    "text": text,
                    "evidence": evidence,
                }
            )

    configuration = asdict(selected)
    result: dict[str, object] = {
        "schema": AI_EXPORT_SCHEMA,
        "kind": "structure-aware-chunks",
        "source_artifact_id": document["source"]["artifact_id"],
        "parsed_artifact_id": document["artifact_id"],
        "exporter": {
            "name": EXPORTER_NAME,
            "version": EXPORTER_VERSION,
            "configuration": configuration,
            "configuration_fingerprint": _fingerprint(configuration),
        },
        "chunks": chunks,
    }
    result["artifact_id"] = f"an:derived:sha256:{_fingerprint(result)}"
    return result


def export_markdown(
    value: ParsedArtifact | dict[str, object],
    *,
    config: ChunkConfig | None = None,
) -> str:
    export = structure_aware_chunks(value, config=config)
    lines = [
        "---",
        f"schema: {AI_EXPORT_SCHEMA}",
        f"derived_artifact_id: {export['artifact_id']}",
        f"parsed_artifact_id: {export['parsed_artifact_id']}",
        f"source_artifact_id: {export['source_artifact_id']}",
        f"exporter: {EXPORTER_NAME}@{EXPORTER_VERSION}",
        f"configuration_fingerprint: {export['exporter']['configuration_fingerprint']}",
        "---",
        "",
    ]
    for chunk in export["chunks"]:
        section = chunk.get("section")
        if section and chunk["kind"] == "heading":
            lines.extend((f"## {chunk['text']}", ""))
        else:
            lines.extend((str(chunk["text"]), ""))
        for evidence in chunk["evidence"]:
            bbox = evidence["bbox"]
            bbox_text = (
                "unpositioned"
                if bbox is None
                else ",".join(f"{float(value):.6f}" for value in bbox)
            )
            lines.append(
                f"<!-- source block={evidence['block_id']} anchor={evidence['anchor_id']} "
                f"page={evidence['page']} bbox={bbox_text} -->"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_jsonl(
    value: ParsedArtifact | dict[str, object],
    *,
    config: ChunkConfig | None = None,
) -> str:
    export = structure_aware_chunks(value, config=config)
    manifest = {key: value for key, value in export.items() if key != "chunks"}
    records = [{"record_type": "manifest", **manifest}]
    records.extend({"record_type": "chunk", **chunk} for chunk in export["chunks"])
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for record in records
    )


def serialize_chunks(
    value: ParsedArtifact | dict[str, object],
    *,
    config: ChunkConfig | None = None,
) -> str:
    return (
        json.dumps(
            structure_aware_chunks(value, config=config),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def write_ai_export(path: str | Path, payload: str, *, overwrite: bool = False) -> Path:
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"AI export already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
