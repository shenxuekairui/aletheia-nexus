from abc import ABC, abstractmethod
from pathlib import Path

from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
)
from aletheia_nexus.core.models import PaperMetadata


class BaseBrowserProvider(ABC):
    """Interface for site-specific providers using the local browser session."""

    name: str
    priority: int

    @abstractmethod
    def is_applicable(
        self,
        *,
        doi: str,
        metadata: PaperMetadata | None,
        expected_title: str | None,
        config: BrowserAccessConfig,
    ) -> bool:
        """Return whether this provider should run for the current paper."""

    @abstractmethod
    def fetch(
        self,
        *,
        doi: str,
        context,
        page,
        output_dir: str | Path,
        config: BrowserAccessConfig,
        metadata: PaperMetadata | None = None,
        expected_title: str | None = None,
        metadata_mailto: str | None = None,
    ) -> BrowserAccessAttempt:
        """Retrieve and validate one paper through an existing browser context."""
