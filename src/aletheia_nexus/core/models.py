from dataclasses import dataclass


@dataclass(frozen=True)
class MetadataLink:
    """A deposited resource link, not a promise of access or verified content."""

    url: str
    source: str
    relation: str = "full_text"
    content_type: str | None = None
    content_version: str | None = None
    intended_application: str | None = None


@dataclass(frozen=True)
class PaperMetadata:
    """Normalized metadata for one scholarly work."""

    doi: str
    title: str | None
    authors: tuple[str, ...]
    journal: str | None
    issn: tuple[str, ...]
    published_date: str | None
    year: int | None
    publisher: str | None
    work_type: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    url: str | None
    links: tuple[MetadataLink, ...] = ()
