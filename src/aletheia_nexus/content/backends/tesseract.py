"""Optional 300-DPI Tesseract OCR backend with conservative preprocessing."""

from __future__ import annotations

import csv
import io
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pypdf import PdfWriter

from aletheia_nexus.content.models import LayoutLine, PageLayout


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
    renderer_command: str = "pdftoppm"
    tesseract_command: str = "tesseract"

    def __post_init__(self) -> None:
        if self.dpi < 300:
            raise ValueError("OCR dpi must be at least 300")
        if not self.languages.strip():
            raise ValueError("OCR languages cannot be empty")
        if not 0 <= self.page_segmentation_mode <= 13:
            raise ValueError("page_segmentation_mode must be between 0 and 13")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
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
        raise RuntimeError(f"OCR executable is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown OCR failure").strip()
        raise RuntimeError(f"OCR command failed: {detail[:500]}") from exc


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
) -> tuple[LayoutLine, ...]:
    words: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(payload), delimiter="\t"):
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
        height_points = max((bottom - top) / image_height * page_height, 1.0)
        result.append(
            LayoutLine(
                text=text,
                x0=left / image_width * page_width,
                y0=(1 - bottom / image_height) * page_height,
                x1=right / image_width * page_width,
                y1=(1 - top / image_height) * page_height,
                font_size=height_points,
                extraction_method="tesseract-tsv-ocr",
                extraction_confidence=max(0.0, min(1.0, confidence)),
                source_engines=(engine_id,),
                uncertain=confidence < 0.85,
            )
        )
    return tuple(result)


class TesseractOcrBackend:
    """Render one PDF page, preprocess it, and return positioned OCR lines."""

    name = "tesseract-ocr"

    def __init__(self, config: TesseractOcrConfig | None = None) -> None:
        self.config = config or TesseractOcrConfig()
        try:
            version_result = _run(
                [self.config.tesseract_command, "--version"],
                timeout=min(self.config.timeout_seconds, 10),
            )
            version_lines = (version_result.stdout + version_result.stderr).splitlines()
            version = version_lines[0] if version_lines else "unknown"
        except RuntimeError:
            version = "unavailable"
        self.version = version.removeprefix("tesseract ").strip() or "unknown"

    def extract_page(self, page: Any, page_number: int) -> PageLayout:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "Tesseract OCR requires the 'ocr' optional dependencies"
            ) from exc

        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
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
                    "-singlefile",
                    str(one_page_pdf),
                    str(prefix),
                ],
                timeout=self.config.timeout_seconds,
            )
            rendered = prefix.with_suffix(".png")
            image = Image.open(rendered).convert("L")

            rotation = 0
            if self.config.detect_orientation:
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

            if self.config.deskew:
                angle = _deskew_angle(image)
                if abs(angle) >= 0.25:
                    image = image.rotate(
                        angle,
                        resample=Image.Resampling.BICUBIC,
                        expand=False,
                        fillcolor=255,
                    )
                    warnings.append(
                        {
                            "code": "OCR_DESKEW_APPLIED",
                            "detail": f"page {page_number}: deskewed by {angle:.2f} degrees",
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
                    "--psm",
                    str(self.config.page_segmentation_mode),
                    "tsv",
                ],
                timeout=self.config.timeout_seconds,
            )
            engine_id = f"{self.name}@{self.version}"
            lines = _parse_tsv(
                result.stdout,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                image_width=image.width,
                image_height=image.height,
                engine_id=engine_id,
            )
        return PageLayout(
            page=page_number,
            width=page_width,
            height=page_height,
            lines=lines,
            warnings=tuple(warnings),
        )
