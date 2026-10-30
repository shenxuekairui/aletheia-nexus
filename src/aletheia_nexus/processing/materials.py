"""Task overlays and bounded page images; never rewrite source artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
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
BUILDER_VERSION = "5"
MODEL_PROJECTION_VERSION = "2"


def _model_warnings(document: dict) -> list[dict]:
    """Summarize repeated diagnostics without merging different readings."""
    grouped = {}
    for warning in document.get("warnings", []):
        page = warning.get("page")
        if page is not None and page not in document["pages_requested"]:
            continue
        detail = " ".join((warning.get("detail") or "").split())
        # Some parser diagnostics repeat the separately recorded page in prose.
        # Do not generalize other numbers: they may describe different failures.
        if page is not None:
            detail = detail.removeprefix(f"page {page}: ")
        key = (warning.get("code"), detail)
        item = grouped.setdefault(
            key, {"code": key[0], "detail": detail, "pages": [], "count": 0}
        )
        if page not in item["pages"]:
            item["pages"].append(page)
        item["count"] += 1
    return list(grouped.values())


def _model_figures(document: dict) -> list[dict]:
    """Retain existing figure links and expose adjacent text as context only."""
    blocks = document["blocks"]
    by_id = {block["id"]: block for block in blocks}
    pages = {page["page"]: page for page in document.get("pages", [])}
    figures = []
    for figure in document.get("figures", []):
        item = {
            key: figure.get(key)
            for key in (
                "id",
                "caption",
                "caption_block_id",
                "interpretation_status",
                "association",
            )
        }
        linked_ids = set(figure.get("object_block_ids", []))
        regions = []
        for obj in figure.get("source_objects", []):
            linked_ids.update(obj.get("annotation_block_ids", []))
            regions.append(
                {
                    "page": obj["page"],
                    "bbox": obj.get("bbox"),
                    "coordinate_system": pages.get(obj["page"], {}).get(
                        "coordinate_system"
                    ),
                }
            )
        linked_ids.update(
            block["id"] for block in blocks if block.get("object_ref") == figure["id"]
        )
        item["linked_block_ids"] = [b["id"] for b in blocks if b["id"] in linked_ids]
        item["source_regions"] = regions
        item["adjacent_block_ids"] = []
        caption = by_id.get(figure.get("caption_block_id"))
        if caption is not None:
            evidence = caption.get("evidence", {})
            item["caption_location"] = {
                "page": caption["page"],
                "bbox": evidence.get("bbox"),
                "coordinate_system": evidence.get("coordinate_system"),
            }
            index = blocks.index(caption)
            item["adjacent_block_ids"] = [
                blocks[i]["id"]
                for i in (index - 1, index + 1)
                if 0 <= i < len(blocks) and blocks[i]["page"] == caption["page"]
            ]
        item["pages"] = sorted(
            {region["page"] for region in regions}
            | {by_id[bid]["page"] for bid in item["linked_block_ids"]}
            | ({caption["page"]} if caption is not None else set())
        )
        figures.append(item)
    return figures


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
                "image_pages": sorted(
                    {
                        image["page"]
                        for image in package["images"]
                        if image["source_id"] == document["id"]
                    }
                ),
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
                "figures": _model_figures(document),
                "warnings": _model_warnings(document),
                "notes": document["notes"],
                "corrections": document["corrections"],
            }
        )
    return {
        "projection_version": MODEL_PROJECTION_VERSION,
        "reading_guidance": [
            "Parser warnings and not-interpreted describe unverified automated "
            "transcription, not an inability to read supplied images. Inspect the "
            "actual page images listed in each document's image_pages for relevant "
            "figure values, symbols and relationships. Image availability alone "
            "does not establish legibility or scientific correctness.",
            "Figure linked_block_ids and source_regions retain parser associations. "
            "Adjacent_block_ids are same-page reading-order context, which may "
            "include caption continuations or unrelated text; verify the relation "
            "rather than treating adjacency as a confirmed caption extension.",
            "Warnings are grouped by code and detail with affected pages and "
            "occurrence counts; full diagnostics remain in the local package.",
        ],
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
    # A freshly loaded artifact has not escaped this function. Read its validated
    # defensive snapshot once; each property access otherwise validates and
    # deep-copies the entire document for the same identity/correction checks.
    artifact_document = artifact.document if artifact else None
    existing = artifact_document["source"] if artifact_document else None
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
        if artifact_document["schema"].endswith("/v3") and any(
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
    if mode != "direct" and (not artifact or artifact_document["status"] == "FAILED"):
        raise ProcessingError("parser_problem")
    for key in ("pages", "image_pages"):
        if any(p > gated.page_count for p in config.get(key, [])):
            raise ProcessingError("page_out_of_bounds")
    corrections = config.get("corrections", [])
    blocks = (
        {b["id"]: b for b in artifact_document["blocks"]} if artifact_document else {}
    )
    if len({c["block_id"] for c in corrections}) != len(corrections):
        raise ValueError("one correction per block per task revision")
    for correction in corrections:
        block = blocks.get(correction["block_id"])
        if block is None or block["text"] != correction["original"]:
            raise ValueError("correction must retain the exact original block reading")
    return Source(deepcopy(config), pdf, gated.sidecar_path, identity, artifact)


def render_page(
    pdf: Path,
    page: int,
    *,
    scale: int = 1600,
    crop: tuple[int, int, int, int] | None = None,
) -> bytes:
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
                    str(scale),
                    *(
                        [
                            "-x",
                            str(crop[0]),
                            "-y",
                            str(crop[1]),
                            "-W",
                            str(crop[2]),
                            "-H",
                            str(crop[3]),
                        ]
                        if crop
                        else []
                    ),
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


def render_page_tiles(pdf: Path, page: int) -> list[dict]:
    """Overview plus four overlapping crops in displayed CropBox coordinates.

    Use Poppler's own pixel crop, including page rotation, without a new imaging
    dependency. The overview preserves context; each crop retains small text.
    Normalized boxes have a top-left origin and refer to the displayed page.
    """
    overview = render_page(pdf, page, scale=3200)
    if len(overview) < 24 or overview[12:16] != b"IHDR":
        raise ProcessingError("invalid_page_image")
    width, height = struct.unpack(">II", overview[16:24])
    if not (1 <= width <= 3200 and 1 <= height <= 3200):
        raise ProcessingError("page_image_budget_exceeded")
    pieces = [{"bytes": overview, "region": [0, 0, 1, 1], "view": "overview"}]
    for y0, y1 in ((0, 0.55), (0.45, 1)):
        for x0, x1 in ((0, 0.55), (0.45, 1)):
            left, top = int(width * x0), int(height * y0)
            right, bottom = (
                min(width, int(width * x1 + 0.5)),
                min(height, int(height * y1 + 0.5)),
            )
            data = render_page(
                pdf, page, scale=3200, crop=(left, top, right - left, bottom - top)
            )
            pieces.append(
                {
                    "bytes": data,
                    "region": [
                        left / width,
                        top / height,
                        right / width,
                        bottom / height,
                    ],
                    "view": "tile",
                }
            )
    return pieces


def render_page_region(pdf: Path, page: int, region: list[float]) -> dict:
    """Render a requested region in the displayed, rotated CropBox space.

    This selects source pixels only. The caller decides relevance and whether
    axes/captions/context are sufficient; bounds do not establish support.
    """
    if (
        not isinstance(region, (list, tuple))
        or len(region) != 4
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in region)
        or not 0 <= region[0] < region[2] <= 1
        or not 0 <= region[1] < region[3] <= 1
    ):
        raise ProcessingError("invalid_page_region")
    overview = render_page(pdf, page, scale=3200)
    if len(overview) < 24 or overview[12:16] != b"IHDR":
        raise ProcessingError("invalid_page_image")
    width, height = struct.unpack(">II", overview[16:24])
    if not (1 <= width <= 3200 and 1 <= height <= 3200):
        raise ProcessingError("page_image_budget_exceeded")
    left, top = math.floor(width * region[0]), math.floor(height * region[1])
    right, bottom = math.ceil(width * region[2]), math.ceil(height * region[3])
    pixels = (left, top, right - left, bottom - top)
    data = (
        overview
        if pixels == (0, 0, width, height)
        else render_page(pdf, page, scale=3200, crop=pixels)
    )
    return {
        "bytes": data,
        "requested_region": list(region),
        "region": [left / width, top / height, right / width, bottom / height],
        "coordinates": "displayed-cropbox-normalized-top-left",
        "full_render_size": [width, height],
        "crop_pixels_xywh": list(pixels),
        "renderer": "pdftoppm-cropbox-region3200/v1",
        "view": "region",
    }


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
    image_count = sum(
        len(image_pages[s.config["id"]])
        * (5 if s.config.get("image_layout") == "page_and_tiles" else 1)
        for s in sources
    )
    if image_count > task["budget"]["max_images"]:
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
        # Text and image selection are independent. Coverage includes either,
        # but the evidence pack above still contains only selected text pages.
        covered_pages = sorted(set(selected[sid]) | set(image_pages[sid]))
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
                "pages_requested": covered_pages,
                "omitted_pages": sorted(
                    set(range(1, source.identity["page_count"] + 1))
                    - set(covered_pages)
                ),
                "notes": source.config.get("notes", []),
                "corrections": source.config.get("corrections", []),
            }
        )
        entry.setdefault("parsed_artifact_id", None)
        entry.setdefault("blocks", [])
        for page in image_pages[sid]:
            tiled = source.config.get("image_layout") == "page_and_tiles"
            pieces = (
                render_page_tiles(source.pdf, page)
                if tiled
                else [{"bytes": render_page(source.pdf, page)}]
            )
            for piece in pieces:
                data = piece["bytes"]
                descriptor = {
                    "source_id": sid,
                    "page": page,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "renderer": "pdftoppm-cropbox-tiles3200/v1"
                    if tiled
                    else "pdftoppm-cropbox-scale1600/v1",
                }
                if tiled:
                    descriptor.update(
                        region=piece["region"],
                        view=piece["view"],
                        coordinates="displayed-cropbox-normalized-top-left",
                    )
                images.append({**descriptor, "bytes": data})
                image_manifest.append(descriptor)
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
