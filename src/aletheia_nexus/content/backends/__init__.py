"""Extraction backends for the content parsing pipeline."""

from aletheia_nexus.content.backends.adaptive import (
    AdaptiveOcrBackend,
    AdaptiveOcrConfig,
)
from aletheia_nexus.content.backends.base import (
    ExtractionBackend,
    RegionExtractionBackend,
)
from aletheia_nexus.content.backends.native import NativePdfBackend
from aletheia_nexus.content.backends.tesseract import (
    TesseractOcrBackend,
    TesseractOcrConfig,
)

__all__ = [
    "AdaptiveOcrBackend",
    "AdaptiveOcrConfig",
    "ExtractionBackend",
    "NativePdfBackend",
    "RegionExtractionBackend",
    "TesseractOcrBackend",
    "TesseractOcrConfig",
]
