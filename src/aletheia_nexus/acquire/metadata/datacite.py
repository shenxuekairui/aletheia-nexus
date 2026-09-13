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
        if not isinstance(item, dict):
            continue

        title = item.get("title")

        if isinstance(title, str) and title:
            return title

    return None


def _creator_name(creator: dict) -> str:
    """Convert one DataCite creator into a readable name."""

    if not isinstance(creator, dict):
        raise TypeError(
            "DataCite creator must be an object"
        )

    given = creator.get("givenName")
    family = creator.get("familyName")

    if given or family:
        return " ".join(
            part
            for part in (given, family)
            if isinstance(part, str) and part
        )

    name = creator.get("name")

    return name if isinstance(name, str) else ""


def _publisher_name(
    attributes: dict,
) -> str | None:
    """Return the publisher name."""

    publisher = attributes.get("publisher")

    if isinstance(publisher, str):
        return publisher

    if isinstance(publisher, dict):
        name = publisher.get("name")
        return name if isinstance(name, str) else None

    return None


def _publication_date(
    attributes: dict,
) -> tuple[str | None, int | None]:
    """Extract publication date and year."""

    dates = attributes.get("dates", [])

    if isinstance(dates, list):
        for item in dates:
            if not isinstance(item, dict):
                continue

            if item.get("dateType") != "Issued":
                continue

            date = item.get("date")

            if not isinstance(date, str) or not date:
                continue

            try:
                year = int(date[:4])
            except ValueError:
                year = None

            return date, year

    year = attributes.get("publicationYear")

    if isinstance(year, int) and not isinstance(year, bool):
        return str(year), year

    return None, None


def _published_in_item(
    attributes: dict,
) -> dict | None:
    """Return the primary IsPublishedIn related item."""

    related_items = attributes.get(
        "relatedItems",
        [],
    )

    if not isinstance(related_items, list):
        return None

    for item in related_items:
        if (
            isinstance(item, dict)
            and item.get("relationType") == "IsPublishedIn"
        ):
            return item

    return None


def _legacy_container(
    attributes: dict,
) -> dict:
    """Return the legacy/convenience container object."""

    container = attributes.get("container")

    return container if isinstance(container, dict) else {}


def _related_title(item: dict) -> str | None:
    """Return the first title from a related item."""

    titles = item.get("titles", [])

    if not isinstance(titles, list):
        return None

    for title_item in titles:
        if not isinstance(title_item, dict):
            continue

        title = title_item.get("title")

        if isinstance(title, str) and title:
            return title

    return None


def _publication_field(
    attributes: dict,
    field: str,
) -> str | None:
    """Return a publication field from relatedItems or container."""

    related_item = _published_in_item(
        attributes
    )

    if related_item:
        value = related_item.get(field)

        if value is not None:
            return str(value)

    value = _legacy_container(
        attributes
    ).get(field)

    if value is None:
        return None

    return str(value)


def _journal(
    attributes: dict,
) -> str | None:
    """Return the journal or publication container title."""

    related_item = _published_in_item(
        attributes
    )

    if related_item:
        title = _related_title(
            related_item
        )

        if title:
            return title

    title = _legacy_container(
        attributes
    ).get("title")

    return title if isinstance(title, str) else None


def _issn(
    attributes: dict,
) -> tuple[str, ...]:
    """Return publication ISSN when available."""

    related_item = _published_in_item(
        attributes
    )

    if related_item:
        identifier = related_item.get(
            "relatedItemIdentifier"
        )

        if isinstance(identifier, dict):
            identifier_type = identifier.get(
                "relatedItemIdentifierType"
            )

            value = identifier.get(
                "relatedItemIdentifier"
            )

            if (
                isinstance(identifier_type, str)
                and identifier_type.upper() == "ISSN"
                and isinstance(value, str)
                and value
            ):
                return (value,)

    container = _legacy_container(
        attributes
    )

    identifier = container.get("identifier")
    identifier_type = container.get(
        "identifierType"
    )

    if (
        isinstance(identifier_type, str)
        and identifier_type.upper() == "ISSN"
        and isinstance(identifier, str)
        and identifier
    ):
        return (identifier,)

    return ()


def _pages(
    attributes: dict,
) -> str | None:
    """Return page information without mixing metadata sources."""

    related_item = _published_in_item(
        attributes
    )

    if related_item:
        first_page = related_item.get(
            "firstPage"
        )
        last_page = related_item.get(
            "lastPage"
        )

        if first_page is not None:
            first_page = str(first_page)

        if last_page is not None:
            last_page = str(last_page)

        if first_page or last_page:
            if (
                first_page
                and last_page
                and first_page != last_page
            ):
                return f"{first_page}-{last_page}"

            return first_page or last_page

    container = _legacy_container(
        attributes
    )

    first_page = container.get(
        "firstPage"
    )
    last_page = container.get(
        "lastPage"
    )

    if first_page is not None:
        first_page = str(first_page)

    if last_page is not None:
        last_page = str(last_page)

    if first_page and last_page:
        if first_page == last_page:
            return first_page

        return f"{first_page}-{last_page}"

    return first_page or last_page


def _work_type(
    attributes: dict,
) -> str | None:
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

    if not isinstance(attributes, dict):
        raise MetadataParseError(
            "DataCite attributes must be an object"
        )

    try:
        doi = normalize_doi(
            attributes["doi"]
        )

        creators = attributes.get(
            "creators",
            [],
        )

        if not isinstance(creators, list):
            raise TypeError(
                "DataCite creators must be a list"
            )

        authors = tuple(
            name
            for creator in creators
            if (name := _creator_name(creator))
        )

        published_date, year = (
            _publication_date(attributes)
        )

        return PaperMetadata(
            doi=doi,
            title=_title(attributes),
            authors=authors,
            journal=_journal(attributes),
            issn=_issn(attributes),
            published_date=published_date,
            year=year,
            publisher=_publisher_name(
                attributes
            ),
            work_type=_work_type(
                attributes
            ),
            volume=_publication_field(
                attributes,
                "volume",
            ),
            issue=_publication_field(
                attributes,
                "issue",
            ),
            pages=_pages(attributes),
            url=attributes.get("url"),
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
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

    return parse_datacite_attributes(
        attributes
    )