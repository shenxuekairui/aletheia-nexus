"""Optional 300-DPI Tesseract OCR backend with conservative preprocessing."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from importlib import metadata
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from typing import Any

from pypdf import PdfWriter

from aletheia_nexus.content.backends.superscripts import raised_glyph_box
from aletheia_nexus.content.geometry import PageGeometry, raster_bbox_to_canonical
from aletheia_nexus.content.models import LayoutLine, PageLayout, PageRegion


@dataclass(frozen=True)
class TesseractOcrConfig:
    """Rendering and preprocessing controls for scientific-page OCR."""

    dpi: int = 300
    languages: str = "eng"
    page_segmentation_mode: int = 3
    detect_orientation: bool = True
    deskew: bool = True
    binarize: bool = True
    timeout_seconds: int = 120
    max_raster_pixels: int = 50_000_000
    renderer_command: str = "pdftoppm"
    tesseract_command: str = "tesseract"
    tessdata_dir: str | None = None
    image_ocr: str = "tesseract"

    def __post_init__(self) -> None:
        if self.image_ocr not in {"tesseract", "rapidocr"}:
            raise ValueError("image_ocr must be tesseract or rapidocr")
        if self.dpi < 300:
            raise ValueError("OCR dpi must be at least 300")
        if not self.languages.strip():
            raise ValueError("OCR languages cannot be empty")
        if not 0 <= self.page_segmentation_mode <= 13:
            raise ValueError("page_segmentation_mode must be between 0 and 13")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if (
            isinstance(self.max_raster_pixels, bool)
            or not isinstance(self.max_raster_pixels, int)
            or self.max_raster_pixels < 1
        ):
            raise ValueError("max_raster_pixels must be a positive integer")
        if not self.renderer_command or not self.tesseract_command:
            raise ValueError("renderer and tesseract commands are required")


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        executable = Path(command[0]).name
        raise RuntimeError(f"OCR executable is unavailable: {executable}") from exc
    except subprocess.CalledProcessError as exc:
        # Tool output may contain local temporary paths. Keep persisted warnings
        # diagnostic but portable and safe to publish.
        executable = Path(command[0]).name
        raise RuntimeError(
            f"OCR command failed: {executable} exited with status {exc.returncode}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"OCR command timed out after {timeout} seconds") from exc


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unavailable"


def _command_name(command: str) -> str:
    """Return a portable executable basename without retaining local directories."""

    return Path(PureWindowsPath(command).name).name


def _tool_version(command: str, *args: str, timeout: int) -> str:
    try:
        result = _run([command, *args], timeout=timeout)
    except RuntimeError:
        return "unavailable"
    lines = (result.stdout + result.stderr).splitlines()
    return lines[0].strip() if lines else "unknown"


def _otsu_threshold(image: Any) -> int:
    histogram = image.histogram()[:256]
    total = sum(histogram)
    weighted_total = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0
    best_variance = -1.0
    best = 127
    for threshold, count in enumerate(histogram):
        background_weight += count
        if not background_weight:
            continue
        foreground_weight = total - background_weight
        if not foreground_weight:
            break
        background_sum += threshold * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_total - background_sum) / foreground_weight
        variance = (
            background_weight
            * foreground_weight
            * (background_mean - foreground_mean) ** 2
        )
        if variance > best_variance:
            best_variance = variance
            best = threshold
    return best


def _projection_score(image: Any) -> float:
    width, height = image.size
    pixels = image.load()
    rows = [sum(1 for x in range(width) if pixels[x, y] == 0) for y in range(height)]
    if not rows:
        return 0.0
    mean = sum(rows) / len(rows)
    return sum((value - mean) ** 2 for value in rows) / len(rows)


def _deskew_angle(image: Any) -> float:
    from PIL import Image

    sample = image.copy()
    sample.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    threshold = _otsu_threshold(sample)
    binary = sample.point(lambda value: 0 if value <= threshold else 255, mode="1")
    best_angle = 0.0
    best_score = _projection_score(binary)
    for half_degrees in range(-6, 7):
        angle = half_degrees / 2
        if angle == 0:
            continue
        rotated = binary.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=255)
        score = _projection_score(rotated)
        if score > best_score:
            best_angle = angle
            best_score = score
    return best_angle


def _orientation_rotation(image_path: Path, config: TesseractOcrConfig) -> int:
    result = _run(
        [
            config.tesseract_command,
            str(image_path),
            "stdout",
            "--psm",
            "0",
            "-l",
            "osd",
            *(["--tessdata-dir", config.tessdata_dir] if config.tessdata_dir else []),
        ],
        timeout=config.timeout_seconds,
    )
    match = re.search(r"Rotate:\s*(0|90|180|270)", result.stdout + result.stderr)
    return int(match.group(1)) if match else 0


def _parse_tsv(
    payload: str,
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    image_width: int,
    image_height: int,
    engine_id: str,
    original_image_width: int | None = None,
    original_image_height: int | None = None,
    orientation_rotation: int = 0,
    deskew_angle: float = 0.0,
    include_word_positions: bool = False,
) -> tuple[LayoutLine, ...]:
    words: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    # A literal OCR quote must not swallow subsequent TSV records.
    for row in csv.DictReader(
        io.StringIO(payload), delimiter="\t", quoting=csv.QUOTE_NONE
    ):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        try:
            if float(row.get("conf", "-1")) < 0:
                continue
            words[(row["block_num"], row["par_num"], row["line_num"])].append(row)
        except (KeyError, TypeError, ValueError):
            continue

    result: list[LayoutLine] = []
    for rows in words.values():
        rows.sort(key=lambda item: int(item["left"]))
        text = " ".join(str(item["text"]).strip() for item in rows).strip()
        if not text:
            continue
        left = min(int(item["left"]) for item in rows)
        top = min(int(item["top"]) for item in rows)
        right = max(int(item["left"]) + int(item["width"]) for item in rows)
        bottom = max(int(item["top"]) + int(item["height"]) for item in rows)
        confidences = [float(item["conf"]) / 100 for item in rows]
        confidence = sum(confidences) / len(confidences)
        canonical = _prepared_bbox_to_canonical(
            (left, top, right, bottom),
            prepared_width=image_width,
            prepared_height=image_height,
            original_width=original_image_width or image_width,
            original_height=original_image_height or image_height,
            orientation_rotation=orientation_rotation,
            deskew_angle=deskew_angle,
        )
        x0, y0, x1, y1 = (
            canonical[0] * page_width,
            canonical[1] * page_height,
            canonical[2] * page_width,
            canonical[3] * page_height,
        )
        if x1 <= x0 or y1 <= y0:
            continue
        height_points = max(y1 - y0, 1.0)
        word_spans = []
        if include_word_positions and not orientation_rotation and not deskew_angle:
            offset = 0
            for row in rows:
                word = row["text"].strip()
                start = max(0, int(row["left"]) / image_width * page_width)
                end = min(
                    page_width,
                    (int(row["left"]) + int(row["width"])) / image_width * page_width,
                )
                if end <= start:
                    word_spans = []
                    break  # Incomplete word geometry cannot justify filtering.
                word_spans.append((offset, offset + len(word), start, end))
                offset += len(word) + 1
        result.append(
            LayoutLine(
                text=text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                font_size=height_points,
                extraction_method="tesseract-tsv-ocr",
                extraction_confidence=max(0.0, min(1.0, confidence)),
                source_engines=(engine_id,),
                # Temporary word positions for native-gap filtering. Public
                # extraction clears them before native table-splitting logic.
                glyph_spans=tuple(word_spans),
                # A confident sentence must not hide one poorly read number or
                # unit. Keep line confidence separate from this review flag.
                uncertain=confidence < 0.85
                or any(
                    float(row["conf"]) < 50
                    and any(c.isalnum() or c in "%‰±−" for c in row["text"])
                    for row in rows
                ),
            )
        )
    return tuple(result)


def _native_gap_readings(
    line: LayoutLine,
    layout: PageLayout,
    native: PageLayout,
    regions: tuple[PageRegion, ...] = (),
):
    """Check observed words, not whitespace between native table columns."""

    def uncovered(x0, x1):
        box = (
            x0 / layout.width,
            line.y0 / layout.height,
            x1 / layout.width,
            line.y1 / layout.height,
        )
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area <= 0:
            return False
        for region in regions:
            a, b, c, d = region.bbox
            overlap = max(0, min(box[2], c) - max(box[0], a)) * max(
                0, min(box[3], d) - max(box[1], b)
            )
            if overlap >= 0.35 * min(area, (c - a) * (d - b)):
                return True  # Keep observed words inside painted figures.
        covered = 0.0
        for other in native.lines:
            a, b, c, d = (
                other.x0 / native.width,
                other.y0 / native.height,
                other.x1 / native.width,
                other.y1 / native.height,
            )
            covered += max(0, min(box[2], c) - max(box[0], a)) * max(
                0, min(box[3], d) - max(box[1], b)
            )
        return covered / area < 0.35

    if not line.glyph_spans:
        return [line] if uncovered(line.x0, line.x1) else []
    groups = []
    current = []
    for span in line.glyph_spans:
        if uncovered(span[2], span[3]):
            # OCR line segmentation can bridge table columns or neighbouring
            # plot panels. Keep physically separated word groups independent;
            # a wide whitespace gap does not establish an experiment relation.
            if current and span[2] - current[-1][3] > line.font_size * 2.5:
                groups.append(current)
                current = []
            current.append(span)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return [
        replace(
            line,
            text=line.text[group[0][0] : group[-1][1]],
            x0=min(span[2] for span in group),
            x1=max(span[3] for span in group),
            glyph_spans=(),
            # The confidence belongs to the original OCR line, not to a
            # newly isolated word. Keep partial readings explicitly uncertain.
            uncertain=line.uncertain
            or line.text[group[0][0] : group[-1][1]] != line.text,
            extraction_method=(
                "tesseract-tsv-ocr-word-region"
                if line.text[group[0][0] : group[-1][1]] != line.text
                else line.extraction_method
            ),
        )
        for group in groups
    ]


def _clear_ocr_word_positions(layout: PageLayout) -> PageLayout:
    return replace(
        layout,
        lines=tuple(
            replace(line, glyph_spans=()) if line.glyph_spans else line
            for line in layout.lines
        ),
    )


def _retry_candidate(line: LayoutLine) -> bool:
    """Limit retries to short low-confidence measurements, not page numbers."""
    return (
        line.content_region == "body"
        and line.extraction_method != "tesseract-superscript-retry"
        and line.extraction_confidence < 0.8
        and len("".join(line.text.split())) <= 40
        and re.search(
            r"[%‰]|[0-9]\s*(?:m?[AV]|m?mol|m?[Ll]|[μµu]?[Ag]|[ck]?m|[shK]|°[CF])(?:\b|(?=[+\-−/²³]))",
            line.text,
        )
        is not None
    )


def _rotate_point(
    x: float,
    y: float,
    *,
    angle: float,
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[float, float]:
    """Apply Pillow-compatible visual rotation between centered canvases."""

    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    source_x, source_y = source_size[0] / 2, source_size[1] / 2
    target_x, target_y = target_size[0] / 2, target_size[1] / 2
    centered_x, centered_y = x - source_x, y - source_y
    return (
        cosine * centered_x + sine * centered_y + target_x,
        -sine * centered_x + cosine * centered_y + target_y,
    )


def _prepared_bbox_to_canonical(
    box: tuple[float, float, float, float],
    *,
    prepared_width: int,
    prepared_height: int,
    original_width: int,
    original_height: int,
    orientation_rotation: int,
    deskew_angle: float,
) -> tuple[float, float, float, float]:
    """Invert OCR preprocessing before mapping evidence to the PDF page."""

    corners = (
        (box[0], box[1]),
        (box[0], box[3]),
        (box[2], box[1]),
        (box[2], box[3]),
    )
    oriented_size = (prepared_width, prepared_height)
    if orientation_rotation in {90, 270}:
        oriented_size = (original_height, original_width)
    elif orientation_rotation in {0, 180}:
        oriented_size = (original_width, original_height)
    else:
        raise ValueError("orientation rotation must be 0, 90, 180, or 270")

    restored: list[tuple[float, float]] = []
    for x, y in corners:
        if deskew_angle:
            x, y = _rotate_point(
                x,
                y,
                angle=-deskew_angle,
                source_size=(prepared_width, prepared_height),
                target_size=oriented_size,
            )
        if orientation_rotation:
            x, y = _rotate_point(
                x,
                y,
                angle=orientation_rotation,
                source_size=oriented_size,
                target_size=(original_width, original_height),
            )
        restored.append((x, y))
    xs = [point[0] for point in restored]
    ys = [point[1] for point in restored]
    return raster_bbox_to_canonical(
        (min(xs), min(ys), max(xs), max(ys)),
        image_width=original_width,
        image_height=original_height,
    )


class TesseractOcrBackend:
    """Render one PDF page, preprocess it, and return positioned OCR lines."""

    name = "tesseract-ocr"

    def __init__(self, config: TesseractOcrConfig | None = None) -> None:
        self.config = config or TesseractOcrConfig()
        timeout = min(self.config.timeout_seconds, 10)
        version = _tool_version(
            self.config.tesseract_command,
            "--version",
            timeout=timeout,
        )
        self.version = version.removeprefix("tesseract ").strip() or "unknown"
        self.renderer_version = _tool_version(
            self.config.renderer_command,
            "-v",
            timeout=timeout,
        )
        self.traineddata = self._traineddata_identity(timeout)
        model_id = hashlib.sha256(
            repr(tuple(sorted(self.traineddata.items()))).encode()
        ).hexdigest()[:12]
        self.evidence_engine_id = f"{self.name}@{self.version}+data.{model_id}"

    def _traineddata_identity(self, timeout: int) -> dict[str, str]:
        directory = self.config.tessdata_dir or os.environ.get("TESSDATA_PREFIX")
        if not directory:
            try:
                result = _run(
                    [self.config.tesseract_command, "--list-langs"], timeout=timeout
                )
                match = re.search(
                    r'List of available languages in "([^"]+)"',
                    result.stdout + result.stderr,
                )
                directory = match.group(1) if match else None
            except RuntimeError:
                pass
        languages = set(self.config.languages.split("+"))
        if self.config.detect_orientation:
            languages.add("osd")
        identities = {}
        for language in sorted(languages):
            try:
                if not directory:
                    raise FileNotFoundError
                with (Path(directory) / f"{language}.traineddata").open("rb") as stream:
                    identities[language] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
            except OSError:
                identities[language] = "unavailable"
        return identities

    @property
    def execution_identity(self) -> dict[str, object]:
        configuration = asdict(self.config)
        # Persist executable basenames, never machine-specific absolute paths.
        configuration["renderer_command"] = _command_name(self.config.renderer_command)
        configuration["tesseract_command"] = _command_name(
            self.config.tesseract_command
        )
        configuration["tessdata_dir"] = (
            "explicit" if self.config.tessdata_dir else "default"
        )
        image_identity = {}
        if self.config.image_ocr == "rapidocr":
            from aletheia_nexus.content.backends.rapid_images import execution_identity

            image_identity = execution_identity()
        return {
            "adapter_version": "1.8.2",
            "image_annotation_version": "1.1.0",
            "configuration": configuration,
            "image_ocr_identity": image_identity,
            "traineddata_sha256": self.traineddata,
            "runtime_dependencies": {
                "tesseract": self.version,
                "poppler": self.renderer_version,
                "pillow": _package_version("Pillow"),
                "pypdf": _package_version("pypdf"),
            },
        }

    def extract_image_annotations(self, page: Any, page_number: int) -> PageLayout:
        """Read source-resolution footers independently of whole-page OCR."""
        if self.config.image_ocr == "rapidocr":
            from aletheia_nexus.content.backends.rapid_images import (
                extract_image_annotations,
            )

            return extract_image_annotations(
                page, page_number, self.config.max_raster_pixels
            )
        from PIL import Image, ImageOps

        from aletheia_nexus.content.backends.image_annotations import (
            footer_band,
            length_label_words,
            upright_images,
        )

        geometry = PageGeometry.from_page(page)
        lines = []
        warnings = []
        with TemporaryDirectory(prefix="an-image-label-") as directory:
            root = Path(directory)
            for index, (name, image, bounds) in enumerate(
                upright_images(page, geometry, self.config.max_raster_pixels)
            ):
                band = footer_band(image)
                if band is None:
                    continue
                cropped, box = band
                prepared = ImageOps.expand(
                    cropped.resize(
                        (cropped.width * 4, cropped.height * 4),
                        Image.Resampling.LANCZOS,
                    ),
                    border=20,
                    fill=255,
                )
                path = root / f"label-{index}.png"
                prepared.save(path)
                result = _run(
                    [
                        self.config.tesseract_command,
                        str(path),
                        "stdout",
                        "-l",
                        self.config.languages,
                        *(
                            ["--tessdata-dir", self.config.tessdata_dir]
                            if self.config.tessdata_dir
                            else []
                        ),
                        "--psm",
                        "7",
                        "-c",
                        "tessedit_create_tsv=1",
                    ],
                    timeout=self.config.timeout_seconds,
                )
                rows = [
                    r
                    for r in csv.DictReader(
                        io.StringIO(result.stdout),
                        delimiter="\t",
                        quoting=csv.QUOTE_NONE,
                    )
                    if r.get("level") == "5" and (r.get("text") or "").strip()
                ]
                found = False
                # A comparison or multi-value legend must not be reduced to
                # isolated, apparently confident length labels.
                candidates = length_label_words(rows)
                for group in candidates:
                    text = " ".join(word["text"].strip() for word in group)
                    confidence = min(float(r["conf"]) for r in group) / 100
                    if confidence < 0.5:
                        continue
                    left = min(int(r["left"]) for r in group)
                    top = min(int(r["top"]) for r in group)
                    right = max(int(r["left"]) + int(r["width"]) for r in group)
                    bottom = max(int(r["top"]) + int(r["height"]) for r in group)
                    sx = (bounds[2] - bounds[0]) / image.width
                    sy = (bounds[3] - bounds[1]) / image.height
                    x0 = bounds[0] + (box[0] + (left - 20) / 4) * sx
                    x1 = bounds[0] + (box[0] + (right - 20) / 4) * sx
                    y0 = bounds[3] - (box[1] + (bottom - 20) / 4) * sy
                    y1 = bounds[3] - (box[1] + (top - 20) / 4) * sy
                    lines.append(
                        LayoutLine(
                            text=text,
                            x0=x0,
                            y0=y0,
                            x1=x1,
                            y1=y1,
                            font_size=max(y1 - y0, 1),
                            extraction_method="tesseract-image-label",
                            extraction_confidence=confidence,
                            source_engines=(self.evidence_engine_id + "+image-label",),
                            content_region="figure",
                            uncertain=confidence < 0.85,
                        )
                    )
                    found = True
                # A generic footer can be a legend or ordinary prose. Only
                # flag an observed length reading that failed confidence;
                # unrecognized image content retains the existing image-wide
                # completeness warning instead of creating speculative tasks.
                if candidates and not found:
                    warnings.append(
                        {
                            "code": "IMAGE_LABEL_UNRESOLVED",
                            "page": page_number,
                            "bbox": [
                                bounds[0] / geometry.width,
                                (
                                    bounds[3]
                                    - box[3] / image.height * (bounds[3] - bounds[1])
                                )
                                / geometry.height,
                                bounds[2] / geometry.width,
                                (
                                    bounds[3]
                                    - box[1] / image.height * (bounds[3] - bounds[1])
                                )
                                / geometry.height,
                            ],
                            "detail": f"page {page_number}: {name}: isolated image footer has no reliable length reading",
                        }
                    )
        return PageLayout(
            page=page_number,
            width=geometry.width,
            height=geometry.height,
            media_box=geometry.media_box,
            crop_box=geometry.crop_box,
            rotation=geometry.rotation,
            lines=tuple(lines),
            warnings=tuple(warnings),
        )

    def extract_page(self, page: Any, page_number: int) -> PageLayout:
        return _clear_ocr_word_positions(self._extract_page(page, page_number))

    def extract_regions(
        self,
        page: Any,
        page_number: int,
        regions: tuple[PageRegion, ...],
        *,
        native_layout: PageLayout | None = None,
    ) -> PageLayout:
        """Keep figure context; mask isolated damaged text in page coordinates."""
        if not regions or any(
            not all(math.isfinite(v) for v in region.bbox)
            or not (
                0 <= region.bbox[0] < region.bbox[2] <= 1
                and 0 <= region.bbox[1] < region.bbox[3] <= 1
            )
            for region in regions
        ):
            raise ValueError("OCR regions require nonempty normalized page boxes")
        figures = tuple(r for r in regions if r.region_type == "figure")
        text = tuple(r for r in regions if r.region_type != "figure")
        layouts = []
        if figures:
            # Masking surrounding text changes Tesseract's figure segmentation:
            # labels can vanish or adjacent captions can merge. Retain its
            # original page context, then select only observed figure readings.
            vector_layout = (
                native_layout
                if self.config.image_ocr == "rapidocr"
                and native_layout is not None
                and any(o.object_type == "vector-text" for o in native_layout.objects)
                else None
            )
            full = (
                self._extract_page(page, page_number, vector_layout=vector_layout)
                if vector_layout is not None
                else self._extract_page(page, page_number)
            )

            def in_figure(line):
                box = (
                    line.x0 / full.width,
                    line.y0 / full.height,
                    line.x1 / full.width,
                    line.y1 / full.height,
                )
                area = (box[2] - box[0]) * (box[3] - box[1])
                for region in figures:
                    x0, y0, x1, y1 = region.bbox
                    overlap = max(0, min(box[2], x1) - max(box[0], x0)) * max(
                        0, min(box[3], y1) - max(box[1], y0)
                    )
                    denominator = min(area, (x1 - x0) * (y1 - y0))
                    if denominator > 0 and overlap / denominator >= 0.35:
                        return True
                return False

            selected = []
            for line in full.lines:
                if line.glyph_spans and native_layout is not None:
                    selected.extend(
                        _native_gap_readings(line, full, native_layout, figures)
                    )
                elif in_figure(line):
                    selected.append(line)
                elif native_layout is not None:
                    # Vector lettering has no image object. Preserve its words
                    # without also importing poorer OCR of adjacent native cells.
                    selected.extend(_native_gap_readings(line, full, native_layout))
            layouts.append(
                replace(
                    full,
                    lines=tuple(selected),
                    warnings=full.warnings
                    + (
                        {
                            "code": "OCR_FIGURE_READINGS_SCOPED",
                            "page": page_number,
                            "regions": [list(r.bbox) for r in figures],
                            "detail": f"Retained {len(selected)} of {len(full.lines)} page-context OCR lines at painted images or native-text gaps; readable native prose is not a competing reading.",
                        },
                    ),
                )
            )
        if text:
            layouts.append(self._extract_page(page, page_number, text))
        return _clear_ocr_word_positions(
            replace(
                layouts[0],
                lines=tuple(line for layout in layouts for line in layout.lines),
                warnings=tuple(w for layout in layouts for w in layout.warnings),
            )
        )

    def _extract_page(
        self,
        page: Any,
        page_number: int,
        regions: tuple[PageRegion, ...] = (),
        *,
        vector_layout: PageLayout | None = None,
    ) -> PageLayout:
        geometry = PageGeometry.from_page(page)
        page_width = geometry.width
        page_height = geometry.height
        try:
            user_unit = float(getattr(page, "user_unit", 1.0) or 1.0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("PDF page has an invalid /UserUnit") from exc
        if not math.isfinite(user_unit) or user_unit <= 0:
            raise RuntimeError("PDF page has an invalid /UserUnit")
        scale = self.config.dpi / 72 * user_unit
        expected_pixels = math.ceil(page_width * scale) * math.ceil(page_height * scale)
        if expected_pixels > self.config.max_raster_pixels:
            raise RuntimeError(
                "OCR raster budget exceeded: "
                f"{expected_pixels} pixels > {self.config.max_raster_pixels}"
            )
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "Tesseract OCR requires the 'ocr' optional dependencies"
            ) from exc
        warnings: list[dict[str, str]] = []
        with TemporaryDirectory(prefix="an-ocr-") as directory:
            root = Path(directory)
            one_page_pdf = root / "page.pdf"
            writer = PdfWriter()
            writer.add_page(page)
            with one_page_pdf.open("wb") as stream:
                writer.write(stream)
            prefix = root / "rendered"
            _run(
                [
                    self.config.renderer_command,
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-r",
                    str(self.config.dpi),
                    "-png",
                    "-cropbox",
                    "-singlefile",
                    str(one_page_pdf),
                    str(prefix),
                ],
                timeout=self.config.timeout_seconds,
            )
            rendered = prefix.with_suffix(".png")
            rendered_image = Image.open(rendered)
            original_width, original_height = rendered_image.size
            actual_pixels = original_width * original_height
            if actual_pixels > self.config.max_raster_pixels:
                rendered_image.close()
                raise RuntimeError(
                    "OCR raster budget exceeded after rendering: "
                    f"{actual_pixels} pixels > {self.config.max_raster_pixels}"
                )
            vector_lines = ()
            if vector_layout is not None:
                from aletheia_nexus.content.backends.rapid_vectors import (
                    read_vector_annotations,
                )

                try:
                    vector_lines = read_vector_annotations(
                        rendered_image, vector_layout
                    )
                except Exception as exc:
                    warnings.append(
                        {
                            "code": "OCR_BACKEND_FAILED",
                            "page": page_number,
                            "detail": f"Local vector OCR failed; the native and Tesseract readings remain available: {exc}",
                        }
                    )
            image = rendered_image.convert("L")
            rendered_image.close()
            if regions:
                masked = Image.new("L", image.size, 255)
                for region in regions:
                    x0, y0, x1, y1 = region.bbox
                    box = (
                        math.floor(x0 * image.width),
                        math.floor((1 - y1) * image.height),
                        math.ceil(x1 * image.width),
                        math.ceil((1 - y0) * image.height),
                    )
                    masked.paste(image.crop(box), box)
                image.close()
                image = masked
                warnings.append(
                    {
                        "code": "OCR_REGIONS_SCOPED",
                        "page": page_number,
                        "regions": [
                            {"bbox": list(r.bbox), "reason": r.reason} for r in regions
                        ],
                        "detail": "Only requested image/damaged-text ink was submitted to OCR; native page coordinates retained.",
                    }
                )

            rotation = 0
            if self.config.detect_orientation and not regions:
                try:
                    rotation = _orientation_rotation(rendered, self.config)
                except RuntimeError as exc:
                    warnings.append(
                        {
                            "code": "OCR_ORIENTATION_UNCERTAIN",
                            "detail": f"page {page_number}: {exc}",
                        }
                    )
                if rotation:
                    image = image.rotate(-rotation, expand=True, fillcolor=255)
                    warnings.append(
                        {
                            "code": "OCR_ORIENTATION_CORRECTED",
                            "detail": f"page {page_number}: rotated {rotation} degrees clockwise",
                        }
                    )

            deskew_angle = 0.0
            if self.config.deskew and not regions:
                proposed_angle = _deskew_angle(image)
                if abs(proposed_angle) >= 0.25:
                    deskew_angle = proposed_angle
                    image = image.rotate(
                        deskew_angle,
                        resample=Image.Resampling.BICUBIC,
                        expand=False,
                        fillcolor=255,
                    )
                    warnings.append(
                        {
                            "code": "OCR_DESKEW_APPLIED",
                            "detail": f"page {page_number}: deskewed by {deskew_angle:.2f} degrees",
                        }
                    )

            if self.config.binarize:
                threshold = _otsu_threshold(image)
                image = image.point(
                    lambda value: 0 if value <= threshold else 255,
                    mode="1",
                )
            prepared = root / "prepared.png"
            image.save(prepared)
            result = _run(
                [
                    self.config.tesseract_command,
                    str(prepared),
                    "stdout",
                    "-l",
                    self.config.languages,
                    *(
                        ["--tessdata-dir", self.config.tessdata_dir]
                        if self.config.tessdata_dir
                        else []
                    ),
                    "--psm",
                    # Masked word regions are sparse, unrelated text fragments.
                    # Ordinary page segmentation can join separate columns.
                    str(
                        11
                        if regions and self.config.page_segmentation_mode == 3
                        else self.config.page_segmentation_mode
                    ),
                    "-c",
                    "tessedit_create_tsv=1",
                ],
                timeout=self.config.timeout_seconds,
            )
            engine_id = self.evidence_engine_id
            if not result.stdout.startswith("level\tpage_num\t"):
                raise RuntimeError(
                    "Tesseract did not return TSV; check the OCR installation and language data"
                )
            lines = _parse_tsv(
                result.stdout,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                image_width=image.width,
                image_height=image.height,
                engine_id=engine_id,
                original_image_width=original_width,
                original_image_height=original_height,
                orientation_rotation=rotation,
                deskew_angle=deskew_angle,
                include_word_positions=True,
            )
            lines = self._retry_unit_superscripts(
                image,
                result.stdout,
                lines,
                root,
            )
            # Short scientific lines can be missed by page segmentation
            # (for example, a percentage at the end of a paragraph). Re-read only
            # a few low-confidence lines; this is not another full-page model.
            if not rotation and not deskew_angle:
                lines = self._retry_short_lines(
                    image, lines, root, page_width, page_height
                )
        return PageLayout(
            page=page_number,
            width=page_width,
            height=page_height,
            media_box=geometry.media_box,
            crop_box=geometry.crop_box,
            rotation=geometry.rotation,
            lines=vector_lines + lines,
            warnings=tuple(warnings),
        )

    def _retry_unit_superscripts(self, image, payload, lines, root):
        """Re-read visible raised ink after a low-confidence per-length unit."""
        from PIL import Image, ImageOps

        rows = list(
            csv.DictReader(io.StringIO(payload), delimiter="\t", quoting=csv.QUOTE_NONE)
        )
        groups = {}
        for row in rows:
            if row.get("level") == "5" and (row.get("text") or "").strip():
                try:
                    if float(row.get("conf", "-1")) >= 0:
                        key = (row["block_num"], row["par_num"], row["line_num"])
                        groups.setdefault(key, []).append(row)
                except (KeyError, TypeError, ValueError):
                    continue  # Match the records accepted by _parse_tsv.
        output = list(lines)
        attempts = 0
        for index, words in enumerate(groups.values()):
            if index >= len(lines):
                break
            originals = sorted(words, key=lambda r: int(r["left"]))
            replacement = [r["text"].strip() for r in originals]
            if " ".join(replacement) != lines[index].text:
                continue  # A malformed/empty TSV box was dropped during parsing.
            for position, word in enumerate(originals):
                if attempts >= 3:
                    break
                text = word["text"].strip()
                if float(word["conf"]) >= 50 or not re.search(
                    r"[A-Za-zµμΩ]+/[cmnuµμ]?m$", text
                ):
                    continue
                x, y, width, height = (
                    int(word[k]) for k in ("left", "top", "width", "height")
                )
                box = raised_glyph_box(image, (x, y, x + width, y + height))
                if box is None:
                    continue
                attempts += 1
                cropped = image.crop(box).convert("L")
                cropped = cropped.resize(
                    (cropped.width * 3, cropped.height * 3), Image.Resampling.BICUBIC
                )
                cropped = ImageOps.expand(cropped, border=20, fill=255)
                path = root / f"superscript-{attempts}.png"
                cropped.save(path)
                try:
                    result = _run(
                        [
                            self.config.tesseract_command,
                            str(path),
                            "stdout",
                            "-l",
                            self.config.languages,
                            *(
                                ["--tessdata-dir", self.config.tessdata_dir]
                                if self.config.tessdata_dir
                                else []
                            ),
                            "--psm",
                            "10",
                            "-c",
                            "tessedit_create_tsv=1",
                        ],
                        timeout=self.config.timeout_seconds,
                    )
                    readings = [
                        r
                        for r in csv.DictReader(
                            io.StringIO(result.stdout),
                            delimiter="\t",
                            quoting=csv.QUOTE_NONE,
                        )
                        if r.get("level") == "5" and (r.get("text") or "").strip()
                    ]
                    if len(readings) != 1 or float(readings[0]["conf"]) < 90:
                        continue
                    digit = readings[0]["text"].strip()
                    if not re.fullmatch(r"[0-9]", digit):
                        continue
                except (RuntimeError, ValueError, KeyError):
                    continue
                replacement[position] = text + digit.translate(
                    str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
                )
            updated = " ".join(replacement)
            original = lines[index]
            if updated != original.text:
                output[index] = replace(
                    original,
                    text=updated,
                    glyph_spans=(),
                    extraction_method="tesseract-superscript-retry",
                    source_engines=(
                        *original.source_engines,
                        self.evidence_engine_id + "+superscript-retry",
                    ),
                    uncertain=True,
                )
                output.append(
                    replace(original, content_region="ocr-alternative", uncertain=True)
                )
        return tuple(output)

    def _retry_short_lines(self, image, lines, root, page_width, page_height):
        from PIL import Image, ImageOps

        candidates = sorted(
            (i for i, line in enumerate(lines) if _retry_candidate(line)),
            key=lambda i: lines[i].extraction_confidence,
        )[:3]
        output = list(lines)
        for index in candidates:
            original = lines[index]
            box = (
                max(0, math.floor(original.x0 / page_width * image.width) - 4),
                max(0, math.floor((1 - original.y1 / page_height) * image.height) - 4),
                min(image.width, math.ceil(original.x1 / page_width * image.width) + 4),
                min(
                    image.height,
                    math.ceil((1 - original.y0 / page_height) * image.height) + 4,
                ),
            )
            cropped = image.crop(box).convert("L")
            cropped = cropped.resize(
                (cropped.width * 2, cropped.height * 2), Image.Resampling.BICUBIC
            )
            cropped = ImageOps.expand(cropped, border=12, fill=255)
            path = root / f"line-{index}.png"
            cropped.save(path)
            try:
                result = _run(
                    [
                        self.config.tesseract_command,
                        str(path),
                        "stdout",
                        "-l",
                        self.config.languages,
                        *(
                            ["--tessdata-dir", self.config.tessdata_dir]
                            if self.config.tessdata_dir
                            else []
                        ),
                        "--psm",
                        "7",
                        "-c",
                        "tessedit_create_tsv=1",
                    ],
                    timeout=self.config.timeout_seconds,
                )
                recovered = _parse_tsv(
                    result.stdout,
                    page_number=1,
                    page_width=cropped.width,
                    page_height=cropped.height,
                    image_width=cropped.width,
                    image_height=cropped.height,
                    engine_id=self.evidence_engine_id + "+line-retry",
                )
            except (RuntimeError, ValueError):
                continue  # The original positioned reading is still available.
            if len(recovered) != 1:
                continue
            candidate = recovered[0]
            if not any(c.isdigit() for c in candidate.text) or any(
                sign in original.text and sign not in candidate.text for sign in "%‰"
            ):
                continue
            if (
                candidate.extraction_confidence < 0.85
                or candidate.extraction_confidence
                < original.extraction_confidence + 0.1
            ):
                continue
            # Undo padding and enlargement before mapping into original PDF
            # coordinates. The retry may recover glyphs outside the first box.
            x0 = (box[0] + (candidate.x0 - 12) / 2) / image.width * page_width
            x1 = (box[0] + (candidate.x1 - 12) / 2) / image.width * page_width
            y0 = (
                1 - (box[1] + (cropped.height - candidate.y0 - 12) / 2) / image.height
            ) * page_height
            y1 = (
                1 - (box[1] + (cropped.height - candidate.y1 - 12) / 2) / image.height
            ) * page_height
            output[index] = replace(
                original,
                text=candidate.text,
                glyph_spans=(),
                x0=max(0, x0),
                y0=max(0, y0),
                x1=min(page_width, x1),
                y1=min(page_height, y1),
                font_size=max(y1 - y0, 1.0),
                extraction_method="tesseract-line-retry",
                extraction_confidence=candidate.extraction_confidence,
                source_engines=candidate.source_engines,
                uncertain=True,
            )
            if "".join(candidate.text.split()) != "".join(original.text.split()):
                output.append(
                    replace(original, content_region="ocr-alternative", uncertain=True)
                )
        return tuple(output)
