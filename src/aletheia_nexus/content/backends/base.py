"""Backend contract for native, OCR, or future layout extractors."""

from typing import Any, Protocol

from aletheia_nexus.content.models import PageLayout


class ExtractionBackend(Protocol):
    name: str
    version: str

    def extract_page(self, page: Any, page_number: int) -> PageLayout: ...
