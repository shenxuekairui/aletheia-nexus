from urllib.parse import quote

import httpx

from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata


CROSSREF_API = "https://api.crossref.org/v1"


def _first(value: list | None):
    """Return the first list item, or None."""

    return value[0] if value else None


def _author_name(author: dict) -> str:
    """Convert one Crossref author record into a readable name."""

    if author.get("name"):
        return author["name"]

    return " ".join(
        part
        for part in (
            author.get("given"),
            author.get("family"),
        )
        if part
    )


def _publication_date(work: dict) -> tuple[str | None, int | None]:
    """Extract the best available publication date."""

    for field in (
        "published",
        "published-online",
        "published-print",
        "issued",
    ):
        date_parts = work.get(field, {}).get("date-parts")

        if not date_parts or not date_parts[0]:
            continue

        parts = date_parts[0]
        year = parts[0]

        date = "-".join(
            f"{part:02d}" if index else str(part)
            for index, part in enumerate(parts)
        )

        return date, year

    return None, None


def parse_crossref_work(work: dict) -> PaperMetadata:
    """Convert a Crossref work record into PaperMetadata."""

    try:
        published_date, year = _publication_date(work)

        authors = tuple(
            name
            for author in work.get("author", [])
            if (name := _author_name(author))
        )

        return PaperMetadata(
            doi=normalize_doi(work["DOI"]),
            title=_first(work.get("title")),
            authors=authors,
            journal=_first(work.get("container-title")),
            issn=tuple(work.get("ISSN", [])),
            published_date=published_date,
            year=year,
            publisher=work.get("publisher"),
            work_type=work.get("type"),
            volume=work.get("volume"),
            issue=work.get("issue"),
            pages=work.get("page"),
            url=work.get("URL"),
        )
    except KeyError as exc:
        raise MetadataParseError(
            f"Crossref response is missing required field: {exc}"
        ) from exc
    except Exception as exc:
        raise MetadataParseError(
            f"Failed to parse Crossref work record: {exc}"
        ) from exc


def get_crossref_metadata(
    doi: str,
    *,
    mailto: str | None = None,
) -> PaperMetadata:
    """Retrieve metadata for one DOI from Crossref."""

    doi = normalize_doi(doi)

    params = {}
    if mailto:
        params["mailto"] = mailto

    try:
        response = httpx.get(
            f"{CROSSREF_API}/works/{quote(doi, safe='')}",
            params=params,
            headers={
                "User-Agent": "Aletheia-Nexus/0.3",
            },
            timeout=10.0,
        )
    except httpx.TimeoutException as exc:
        raise MetadataNetworkError(
            f"Timed out while requesting Crossref metadata for DOI: {doi}"
        ) from exc
    except httpx.RequestError as exc:
        raise MetadataNetworkError(
            f"Network error while requesting Crossref metadata for DOI: {doi}"
        ) from exc

    if response.status_code == 404:
        raise MetadataNotFoundError(
            f"Crossref metadata not found for DOI: {doi}"
    )

    if response.status_code == 429:
        raise RateLimitError(
            f"Crossref rate limit exceeded for DOI: {doi}"
    )

    if 400 <= response.status_code < 500:
        raise MetadataRequestError(
            f"Crossref request failed with HTTP {response.status_code} for DOI: {doi}"
    )

    if 500 <= response.status_code < 600:
        raise MetadataServiceError(
            f"Crossref server error {response.status_code} for DOI: {doi}"
    )

    try:
        data = response.json()
    except ValueError as exc:
        raise MetadataParseError(
            f"Crossref returned invalid JSON for DOI: {doi}"
        ) from exc

    if "message" not in data or not isinstance(data["message"], dict):
        raise MetadataParseError(
            f"Crossref response has invalid structure for DOI: {doi}"
        )

    return parse_crossref_work(data["message"])