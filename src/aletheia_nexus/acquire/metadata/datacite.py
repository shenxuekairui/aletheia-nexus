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


DATACITE_API = "https://api.datacite.org"


def _title(attributes: dict) -> str | None:
    """Return the primary DataCite title."""

    titles = attributes.get("titles", [])

    for item in titles:
        title = item.get("title")
        if title:
            return title

    return None


def _creator_name(creator: dict) -> str:
    """Convert one DataCite creator into a readable name."""

    given = creator.get("givenName")
    family = creator.get("familyName")

    if given or family:
        return " ".join(
            part
            for part in (given, family)
            if part
        )

    return creator.get("name", "")


def _publisher_name(attributes: dict) -> str | None:
    """Return the publisher name."""

    publisher = attributes.get("publisher")

    if isinstance(publisher, str):
        return publisher

    if isinstance(publisher, dict):
        return publisher.get("name")

    return None


def _publication_date(
    attributes: dict,
) -> tuple[str | None, int | None]:
    """Extract publication date and year."""

    dates = attributes.get("dates", [])

    for item in dates:
        if item.get("dateType") == "Issued":
            date = item.get("date")

            if date:
                try:
                    year = int(date[:4])
                except (TypeError, ValueError):
                    year = None

                return date, year

    year = attributes.get("publicationYear")

    if isinstance(year, int):
        return str(year), year

    return None, None


def _container_field(
    attributes: dict,
    field: str,
) -> str | None:
    """Return one field from the DataCite container."""

    container = attributes.get("container")

    if not isinstance(container, dict):
        return None

    value = container.get(field)

    return value if value else None


def _issn(attributes: dict) -> tuple[str, ...]:
    """Return an ISSN from the container when available."""

    container = attributes.get("container")

    if not isinstance(container, dict):
        return ()

    identifier = container.get("identifier")
    identifier_type = container.get("identifierType")

    if (
        identifier
        and isinstance(identifier_type, str)
        and identifier_type.upper() == "ISSN"
    ):
        return (identifier,)

    return ()


def _work_type(attributes: dict) -> str | None:
    """Return the best available DataCite resource type."""

    types = attributes.get("types")

    if not isinstance(types, dict):
        return None

    return (
        types.get("resourceType")
        or types.get("resourceTypeGeneral")
    )


def parse_datacite_attributes(
    attributes: dict,
) -> PaperMetadata:
    """Convert DataCite attributes into PaperMetadata."""

    try:
        doi = normalize_doi(attributes["doi"])

        authors = tuple(
            name
            for creator in attributes.get("creators", [])
            if (name := _creator_name(creator))
        )

        published_date, year = _publication_date(
            attributes
        )

        return PaperMetadata(
            doi=doi,
            title=_title(attributes),
            authors=authors,
            journal=_container_field(
                attributes,
                "title",
            ),
            issn=_issn(attributes),
            published_date=published_date,
            year=year,
            publisher=_publisher_name(attributes),
            work_type=_work_type(attributes),
            volume=_container_field(
                attributes,
                "volume",
            ),
            issue=_container_field(
                attributes,
                "issue",
            ),
            pages=_container_field(
                attributes,
                "firstPage",
            ),
            url=attributes.get("url"),
        )

    except KeyError as exc:
        raise MetadataParseError(
            f"DataCite response is missing required field: {exc}"
        ) from exc

    except Exception as exc:
        raise MetadataParseError(
            f"Failed to parse DataCite metadata: {exc}"
        ) from exc


def get_datacite_metadata(
    doi: str,
    *,
    mailto: str | None = None,
) -> PaperMetadata:
    """Retrieve metadata for one DOI from DataCite."""

    doi = normalize_doi(doi)

    user_agent = "Aletheia-Nexus/0.3"

    if mailto:
        user_agent += f" (mailto:{mailto})"

    try:
        response = httpx.get(
            f"{DATACITE_API}/dois/{quote(doi, safe='')}",
            headers={
                "User-Agent": user_agent,
            },
            timeout=10.0,
        )

    except httpx.TimeoutException as exc:
        raise MetadataNetworkError(
            f"Timed out while requesting DataCite metadata for DOI: {doi}"
        ) from exc

    except httpx.RequestError as exc:
        raise MetadataNetworkError(
            f"Network error while requesting DataCite metadata for DOI: {doi}"
        ) from exc

    if response.status_code == 404:
        raise MetadataNotFoundError(
            f"DataCite metadata not found for DOI: {doi}"
    )

    if response.status_code == 429:
        raise RateLimitError(
            f"DataCite rate limit exceeded for DOI: {doi}"
    )

    if 400 <= response.status_code < 500:
        raise MetadataRequestError(
            f"DataCite request failed with HTTP {response.status_code} for DOI: {doi}"
    )

    if 500 <= response.status_code < 600:
        raise MetadataServiceError(
            f"DataCite server error {response.status_code} for DOI: {doi}"
    )

    try:
        data = response.json()
    except ValueError as exc:
        raise MetadataParseError(
            f"DataCite returned invalid JSON for DOI: {doi}"
        ) from exc

    try:
        attributes = data["data"]["attributes"]
    except (KeyError, TypeError) as exc:
        raise MetadataParseError(
            f"DataCite response has invalid structure for DOI: {doi}"
        ) from exc

    if not isinstance(attributes, dict):
        raise MetadataParseError(
            f"DataCite response has invalid attributes for DOI: {doi}"
        )

    return parse_datacite_attributes(attributes)