"""Backend contract for native, OCR, or future layout extractors."""

from typing import Any, Protocol

from aletheia_nexus.content.models import PageLayout, PageRegion


class ExtractionBackend(Protocol):
    name: str
    version: str

    def extract_page(self, page: Any, page_number: int) -> PageLayout: ...


class RegionExtractionBackend(Protocol):
    """Contract for table, formula, or figure-specific region extraction."""

    name: str
    version: str
    supported_regions: frozenset[str]

    def extract_region(
        self, page: Any, page_number: int, region: PageRegion
    ) -> PageLayout: ...
