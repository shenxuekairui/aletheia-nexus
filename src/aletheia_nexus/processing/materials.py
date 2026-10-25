"""Task overlays and bounded page images; never rewrite source artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from aletheia_nexus.content.artifact import ParsedArtifact
from aletheia_nexus.content.corpus import Corpus, CorpusDocument, search_corpus
from aletheia_nexus.content.evidence import build_evidence_pack
from aletheia_nexus.content.gate import sha256_file, validate_parser_input

from .contracts import digest
from .provider import ProcessingError

PACKAGE_SCHEMA = "aletheia-nexus/task-package/v1"
BUILDER_VERSION = "2"


def model_material(package: dict) -> dict:
    """Keep readings and table relationships; retain detailed geometry locally.

    The full package remains the audit artifact. Repeating anchors, diagnostics and
    alternative texts in multiple views needlessly consumes the model's context.
    """
    documents = []
    for document in package["documents"]:
        source = document["source"]
        documents.append(
            {
                "id": document["id"],
                "source": {
                    key: source.get(key)
                    for key in ("title", "doi", "document_role", "page_count", "parent")
                },
                "pages_requested": document["pages_requested"],
                "omitted_pages": document["omitted_pages"],
                "blocks": [
                    {
                        key: block.get(key)
                        for key in (
                            "id",
                            "page",
                            "text",
                            "kind",
                            "uncertain",
                            "content_region",
                        )
                    }
                    for block in document["blocks"]
                ],
                "tables": document.get("tables", []),
                "figures": [
                    {
                        key: figure.get(key)
                        for key in (
                            "id",
                            "caption",
                            "caption_block_id",
                            "interpretation_status",
                        )
                    }
                    for figure in document.get("figures", [])
                ],
                "warnings": [
                    {key: warning.get(key) for key in ("code", "detail", "page")}
                    for warning in document.get("warnings", [])
                    if warning.get("page") in [None, *document["pages_requested"]]
                ],
                "notes": document["notes"],
                "corrections": document["corrections"],
            }
        )
    return {
        "artifact_id": package.get("artifact_id"),
        "parent_id": package.get("parent_id"),
        "mode": package.get("mode"),
        "documents": documents,
        "images": package["images"],
    }


@dataclass
class Source:
    config: dict
    pdf: Path
    sidecar: Path
    identity: dict
    artifact: ParsedArtifact | None

    def verify(self) -> None:
        if (
            sha256_file(self.pdf) != self.identity["pdf_sha256"]
            or sha256_file(self.sidecar) != self.identity["acquisition_sidecar_sha256"]
        ):
            raise ProcessingError("source_changed")
        if self.artifact is not None:
            current = ParsedArtifact.load(self.artifact.path)
            if current.document["artifact_id"] != self.artifact.document["artifact_id"]:
                raise ProcessingError("parsed_artifact_changed")


def load_source(config: dict, base: Path, mode: str) -> Source:
    artifact = None
    if config.get("artifact") and not (mode == "direct" and config.get("pdf")):
        artifact = ParsedArtifact.load((base / config["artifact"]).resolve())
    existing = artifact.document["source"] if artifact else None
    locators = existing.get("locators", {}) if existing else {}

    def locate(key: str, locator: str) -> Path | None:
        if config.get(key):
            return (base / config[key]).resolve()
        if artifact and locators.get(locator):
            return (artifact.path.parent / locators[locator]).resolve()
        return None

    pdf = locate("pdf", "pdf")
    if pdf is None:
        raise ProcessingError("source_pdf_required")
    gated = validate_parser_input(
        pdf, sidecar_path=locate("sidecar", "acquisition_sidecar")
    )
    identity = {
        "artifact_id": "an:source:sha256:" + gated.pdf_sha256,
        "pdf_sha256": gated.pdf_sha256,
        "acquisition_sidecar_sha256": gated.sidecar_sha256,
        "doi": gated.doi,
        "title": gated.title,
        "article_id": gated.article_id,
        "page_count": gated.page_count,
        "document_role": gated.document_role,
        "identity_basis": gated.identity_basis,
        "parent": gated.parent,
    }
    if existing:
        for key in ("pdf_sha256", "acquisition_sidecar_sha256", "doi", "page_count"):
            if existing[key] != identity[key]:
                raise ProcessingError("source_identity_mismatch")
        if artifact.document["schema"].endswith("/v3") and any(
            existing.get(k) != identity[k]
            for k in (
                "document_role",
                "parent",
                "title",
                "article_id",
                "identity_basis",
            )
        ):
            raise ProcessingError("source_identity_mismatch")
    if mode != "direct" and (not artifact or artifact.document["status"] == "FAILED"):
        raise ProcessingError("parser_problem")
    for key in ("pages", "image_pages"):
        if any(p > gated.page_count for p in config.get(key, [])):
            raise ProcessingError("page_out_of_bounds")
    corrections = config.get("corrections", [])
    blocks = {b["id"]: b for b in artifact.document["blocks"]} if artifact else {}
    if len({c["block_id"] for c in corrections}) != len(corrections):
        raise ValueError("one correction per block per task revision")
    for correction in corrections:
        block = blocks.get(correction["block_id"])
        if block is None or block["text"] != correction["original"]:
            raise ValueError("correction must retain the exact original block reading")
    return Source(deepcopy(config), pdf, gated.sidecar_path, identity, artifact)


def render_page(pdf: Path, page: int) -> bytes:
    """Render only one CropBox page at bounded dimensions; no OCR or network."""
    binary = shutil.which("pdftoppm")
    if not binary:
        raise ProcessingError("page_renderer_unavailable")
    with TemporaryDirectory(prefix="an-page-") as temporary:
        prefix = Path(temporary) / "page"
        try:
            subprocess.run(
                [
                    binary,
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    "-cropbox",
                    "-scale-to",
                    "1600",
                    "-png",
                    str(pdf),
                    str(prefix),
                ],
                check=True,
                timeout=60,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            data = prefix.with_suffix(".png").read_bytes()
        except (OSError, subprocess.SubprocessError):
            raise ProcessingError("page_render_failed") from None
    if len(data) > 12_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ProcessingError("page_image_budget_exceeded")
    return data


def _corpus(sources: list[Source]) -> Corpus:
    entries = [
        CorpusDocument(s.artifact.path, s.pdf, s.artifact, s.artifact.document)
        for s in sources
        if s.artifact
    ]
    paths = [str(p.parent) for e in entries for p in (e.path, e.pdf)]
    try:
        root = Path(os.path.commonpath(paths)) if paths else Path.cwd()
    except ValueError:
        raise ValueError(
            "one material group must use the same filesystem drive"
        ) from None
    return Corpus(root, entries, [], [])


def build_package(
    task: dict,
    sources: list[Source],
    *,
    additions: dict[str, list[int]] | None = None,
    parent_id: str | None = None,
    reason: str = "initial selection",
) -> tuple[dict, list[dict]]:
    additions = additions or {}
    if set(additions) - {s.config["id"] for s in sources}:
        raise ProcessingError("supplement_outside_scope")
    selected = {}
    image_pages = {}
    for source in sources:
        source.verify()
        config = source.config
        sid = config["id"]
        count = source.identity["page_count"]
        extra = additions.get(sid, [])
        if any(type(p) is not int or not 1 <= p <= count for p in extra):
            raise ProcessingError("page_out_of_bounds")
        pages = config.get("pages")
        if pages is None and task.get("query") and task["mode"] != "direct":
            report = search_corpus(
                _corpus([source]), task["query"], mode="or", limit=10
            )
            selected_pack = (
                build_evidence_pack(
                    _corpus([source]),
                    report=report,
                    selectors=[str(h["number"]) for h in report["hits"]],
                    context_pages=task["context_pages"],
                )
                if report["hits"]
                else None
            )
            pages = (
                selected_pack["included"][0]["pages_requested"] if selected_pack else []
            )
        if pages is None:
            pages = list(range(1, count + 1))
        selected[sid] = sorted(set(pages) | set(extra))
        visual = config.get("image_pages", [])
        if task["mode"] == "direct":
            visual = config.get("image_pages", config.get("pages", []))
            selected[sid] = sorted(set(visual) | set(extra))
        if task["mode"] == "direct" or task["verify_original"]:
            visual = sorted(set(visual) | set(selected[sid]))
        elif task["mode"] == "hybrid":
            visual = sorted(set(visual) | set(extra))
        if task["mode"] in {"local", "parsed"}:
            if visual or task["verify_original"]:
                raise ValueError("page image inputs require hybrid or direct mode")
            visual = []
        image_pages[sid] = visual
    if sum(map(len, image_pages.values())) > task["budget"]["max_images"]:
        raise ProcessingError("image_budget_exceeded")
    parsed = [s for s in sources if s.artifact and task["mode"] != "direct"]
    evidence = (
        build_evidence_pack(
            _corpus(parsed),
            document_pages={
                s.artifact.document["artifact_id"]: selected[s.config["id"]]
                for s in parsed
            },
        )
        if parsed
        else {"included": []}
    )
    by_id = {e["parsed_artifact_id"]: e for e in evidence["included"]}
    documents = []
    images = []
    image_manifest = []
    for source in sources:
        sid = source.config["id"]
        entry = (
            deepcopy(by_id.get(source.artifact.document["artifact_id"], {}))
            if source in parsed
            else {}
        )
        # Locators are local metadata, never part of remote material.
        for key in ("pdf", "artifact", "source"):
            entry.pop(key, None)
        entry.update(
            {
                "id": sid,
                "source": source.identity,
                "locators": {
                    "pdf": str(source.pdf),
                    "sidecar": str(source.sidecar),
                    "artifact": str(source.artifact.path) if source.artifact else None,
                },
                "pages_requested": selected[sid],
                "omitted_pages": sorted(
                    set(range(1, source.identity["page_count"] + 1))
                    - set(selected[sid])
                ),
                "notes": source.config.get("notes", []),
                "corrections": source.config.get("corrections", []),
            }
        )
        entry.setdefault("parsed_artifact_id", None)
        entry.setdefault("blocks", [])
        for page in image_pages[sid]:
            data = render_page(source.pdf, page)
            identity = hashlib.sha256(data).hexdigest()
            images.append(
                {"source_id": sid, "page": page, "bytes": data, "sha256": identity}
            )
            image_manifest.append(
                {
                    "source_id": sid,
                    "page": page,
                    "sha256": identity,
                    "renderer": "pdftoppm-cropbox-scale1600/v1",
                }
            )
        source.verify()
        documents.append(entry)
    package = {
        "schema": PACKAGE_SCHEMA,
        "builder_version": BUILDER_VERSION,
        "task_id": task["id"],
        "task_fingerprint": digest(task),
        "mode": task["mode"],
        "parent_id": parent_id,
        "reason": reason,
        "additions": additions,
        "documents": documents,
        "images": image_manifest,
    }
    if (
        len(json.dumps(model_material(package), ensure_ascii=False))
        > task["budget"]["max_input_characters"]
    ):
        raise ProcessingError("material_budget_exceeded")
    package["artifact_id"] = "an:task-package:sha256:" + digest(package)
    return package, images
