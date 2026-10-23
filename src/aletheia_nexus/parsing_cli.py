"""Shared options for single-document and corpus parsing commands."""

from __future__ import annotations

import argparse

from aletheia_nexus.content.backends import (
    AdaptiveOcrBackend,
    TesseractOcrBackend,
    TesseractOcrConfig,
)
from aletheia_nexus.content.parser import ParserConfig


def add_parsing_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-pages", type=int, default=2000)
    parser.add_argument("--max-blocks", type=int, default=200_000)
    parser.add_argument("--max-text-characters", type=int, default=20_000_000)
    parser.add_argument(
        "--no-merge-paragraph-lines",
        action="store_true",
        help="Keep each positioned PDF text line as a separate block.",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable native-first selective OCR through Poppler and Tesseract.",
    )
    parser.add_argument("--ocr-languages", default="eng")
    parser.add_argument(
        "--ocr-tessdata-dir",
        help="Directory of local Tesseract language models (for example tessdata_best).",
    )
    parser.add_argument("--ocr-dpi", type=int, default=300)
    parser.add_argument(
        "--image-ocr",
        choices=("tesseract", "rapidocr"),
        default="tesseract",
        help="Local source-image OCR; rapidocr requires the image-ocr extra.",
    )
    parser.add_argument(
        "--ocr-alternative-tessdata-dir",
        help="Optional second local model directory; keep differing OCR readings for review.",
    )
    parser.add_argument("--tesseract-command", default="tesseract")
    parser.add_argument("--renderer-command", default="pdftoppm")
    parser.add_argument("--ocr-max-raster-pixels", type=int, default=50_000_000)


def parser_config(args: argparse.Namespace) -> ParserConfig:
    return ParserConfig(
        max_pages=args.max_pages,
        max_blocks=args.max_blocks,
        max_text_characters=args.max_text_characters,
        merge_paragraph_lines=not args.no_merge_paragraph_lines,
    )


def parsing_backend(args: argparse.Namespace) -> AdaptiveOcrBackend | None:
    if not args.ocr:
        return None
    model_dirs = [args.ocr_tessdata_dir]
    if args.ocr_alternative_tessdata_dir:
        model_dirs.append(args.ocr_alternative_tessdata_dir)
    return AdaptiveOcrBackend(
        ocr_backends=tuple(
            TesseractOcrBackend(
                TesseractOcrConfig(
                    languages=args.ocr_languages,
                    image_ocr=args.image_ocr,
                    tessdata_dir=model_dir,
                    dpi=args.ocr_dpi,
                    tesseract_command=args.tesseract_command,
                    renderer_command=args.renderer_command,
                    max_raster_pixels=args.ocr_max_raster_pixels,
                )
            )
            for model_dir in model_dirs
        )
    )
