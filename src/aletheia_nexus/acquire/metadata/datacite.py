from dataclasses import dataclass
from urllib.parse import quote

from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataParseError,
)
from aletheia_nexus.acquire.metadata.transport import get_json
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata

DATACITE_API = "https://api.datacite.org"


@dataclass(frozen=True)
class _PublicationInfo:
    """Normalized publication-container information."""

    journal: str | None = None
    issn: tuple[str, ...] = ()
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None


def _scalar_text(
    value: object,
    *,
    field: str,
) -> str | None:
    """Convert a simple scalar metadata value into text."""

    if value is None:
        return None

    if isinstance(value, bool):
        raise TypeError(f"DataCite {field} must not be boolean")

    if isinstance(value, (str, int, float)):
        text = str(value)
        return text or None

    raise TypeError(f"DataCite {field} must be a scalar value")


def _title(
    attributes: dict,
) -> str | None:
    """Return the primary DataCite title."""

    titles = attributes.get("titles", [])

    if titles is None:
        return None

    if not isinstance(titles, list):
        raise TypeError("DataCite titles must be a list")

    for item in titles:
        if not isinstance(item, dict):
            raise TypeError("DataCite title entries must be objects")

        title = item.get("title")

        if title is None:
            continue

        if not isinstance(title, str):
            raise TypeError("DataCite title must be a string")

        if title:
            return title

    return None


def _creator_name(
    creator: object,
) -> str:
    """Convert one DataCite creator into a readable name."""

    if not isinstance(creator, dict):
        raise TypeError("DataCite creator must be an object")

    given = creator.get("givenName")
    family = creator.get("familyName")

    if given is not None and not isinstance(given, str):
        raise TypeError("DataCite creator givenName must be a string")

    if family is not None and not isinstance(family, str):
        raise TypeError("DataCite creator familyName must be a string")

    if given or family:
        return " ".join(part for part in (given, family) if part)

    name = creator.get("name")

    if name is None:
        return ""

    if not isinstance(name, str):
        raise TypeError("DataCite creator name must be a string")

    return name


def _authors(
    attributes: dict,
) -> tuple[str, ...]:
    """Return normalized DataCite creator names."""

    creators = attributes.get("creators", [])

    if creators is None:
        return ()

    if not isinstance(creators, list):
        raise TypeError("DataCite creators must be a list")

    return tuple(name for creator in creators if (name := _creator_name(creator)))


def _publisher_name(
    attributes: dict,
) -> str | None:
    """Return the publisher name."""

    publisher = attributes.get("publisher")

    if publisher is None:
        return None

    if isinstance(publisher, str):
        return publisher or None

    if isinstance(publisher, dict):
        name = publisher.get("name")

        if name is None:
            return None

        if not isinstance(name, str):
            raise TypeError("DataCite publisher name must be a string")

        return name or None

    raise TypeError("DataCite publisher must be text or an object")


def _publication_date(
    attributes: dict,
) -> tuple[str | None, int | None]:
    """Extract publication date and year."""

    dates = attributes.get("dates", [])

    if dates is None:
        dates = []

    if not isinstance(dates, list):
        raise TypeError("DataCite dates must be a list")

    for item in dates:
        if not isinstance(item, dict):
            raise TypeError("DataCite date entries must be objects")

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

    if year is not None:
        raise TypeError("DataCite publicationYear must be an integer")

    return None, None


def _work_type(
    attributes: dict,
) -> str | None:
    """Return the best available DataCite resource type."""

    types = attributes.get("types")

    if types is None:
        return None

    if not isinstance(types, dict):
        raise TypeError("DataCite types must be an object")

    resource_type = types.get("resourceType")
    general_type = types.get("resourceTypeGeneral")

    if resource_type is not None:
        if not isinstance(resource_type, str):
            raise TypeError("DataCite resourceType must be a string")

        if resource_type:
            return resource_type

    if general_type is not None:
        if not isinstance(general_type, str):
            raise TypeError("DataCite resourceTypeGeneral must be a string")

        return general_type or None

    return None


def _page_range(
    first_page: str | None,
    last_page: str | None,
) -> str | None:
    """Build a page range without inventing missing values."""

    if first_page and last_page:
        if first_page == last_page:
            return first_page

        return f"{first_page}-{last_page}"

    return first_page or last_page


def _related_title(
    item: dict,
) -> str | None:
    """Return the first title from one related item."""

    titles = item.get("titles", [])

    if titles is None:
        return None

    if not isinstance(titles, list):
        raise TypeError("DataCite related-item titles must be a list")

    for title_item in titles:
        if not isinstance(title_item, dict):
            raise TypeError("DataCite related-item title must be an object")

        title = title_item.get("title")

        if title is None:
            continue

        if not isinstance(title, str):
            raise TypeError("DataCite related-item title must be a string")

        if title:
            return title

    return None


def _related_issn(
    item: dict,
) -> tuple[str, ...]:
    """Return ISSN information from one related item."""

    identifier = item.get("relatedItemIdentifier")

    if identifier is None:
        return ()

    if not isinstance(identifier, dict):
        raise TypeError("DataCite relatedItemIdentifier must be an object")

    identifier_type = identifier.get("relatedItemIdentifierType")
    value = identifier.get("relatedItemIdentifier")

    if identifier_type is None or value is None:
        return ()

    if not isinstance(identifier_type, str):
        raise TypeError("DataCite related identifier type must be a string")

    if not isinstance(value, str):
        raise TypeError("DataCite related identifier must be a string")

    if identifier_type.upper() == "ISSN" and value:
        return (value,)

    return ()


def _related_publication_info(
    item: dict,
) -> _PublicationInfo:
    """Parse one IsPublishedIn related item."""

    first_page = _scalar_text(
        item.get("firstPage"),
        field="firstPage",
    )
    last_page = _scalar_text(
        item.get("lastPage"),
        field="lastPage",
    )

    return _PublicationInfo(
        journal=_related_title(item),
        issn=_related_issn(item),
        volume=_scalar_text(
            item.get("volume"),
            field="volume",
        ),
        issue=_scalar_text(
            item.get("issue"),
            field="issue",
        ),
        pages=_page_range(
            first_page,
            last_page,
        ),
    )


def _container_publication_info(
    attributes: dict,
) -> _PublicationInfo:
    """Parse legacy/convenience container information."""

    container = attributes.get("container")

    if container is None:
        return _PublicationInfo()

    if not isinstance(container, dict):
        raise TypeError("DataCite container must be an object")

    title = container.get("title")

    if title is not None and not isinstance(title, str):
        raise TypeError("DataCite container title must be a string")

    identifier = container.get("identifier")
    identifier_type = container.get("identifierType")

    issn: tuple[str, ...] = ()

    if identifier is not None or identifier_type is not None:
        if not isinstance(identifier, str):
            raise TypeError("DataCite container identifier must be a string")

        if not isinstance(identifier_type, str):
            raise TypeError("DataCite container identifierType must be a string")

        if identifier_type.upper() == "ISSN" and identifier:
            issn = (identifier,)

    first_page = _scalar_text(
        container.get("firstPage"),
        field="firstPage",
    )
    last_page = _scalar_text(
        container.get("lastPage"),
        field="lastPage",
    )

    return _PublicationInfo(
        journal=title or None,
        issn=issn,
        volume=_scalar_text(
            container.get("volume"),
            field="volume",
        ),
        issue=_scalar_text(
            container.get("issue"),
            field="issue",
        ),
        pages=_page_range(
            first_page,
            last_page,
        ),
    )


def _has_publication_data(
    info: _PublicationInfo,
) -> bool:
    """Return whether publication information contains usable data."""

    return any(
        (
            info.journal,
            info.issn,
            info.volume,
            info.issue,
            info.pages,
        )
    )


def _publication_info(
    attributes: dict,
) -> _PublicationInfo:
    """
    Resolve publication-container information from one coherent source.

    Modern IsPublishedIn metadata is preferred. Legacy container
    information is used only when no usable IsPublishedIn record exists.
    """

    related_items = attributes.get(
        "relatedItems",
        [],
    )

    if related_items is None:
        related_items = []

    if not isinstance(related_items, list):
        raise TypeError("DataCite relatedItems must be a list")

    for item in related_items:
        if not isinstance(item, dict):
            raise TypeError("DataCite relatedItems entries must be objects")

        if item.get("relationType") != "IsPublishedIn":
            continue

        info = _related_publication_info(item)

        if _has_publication_data(info):
            return info

    return _container_publication_info(attributes)


def parse_datacite_attributes(
    attributes: dict,
) -> PaperMetadata:
    """Convert DataCite attributes into PaperMetadata."""

    if not isinstance(attributes, dict):
        raise MetadataParseError("DataCite attributes must be an object")

    try:
        doi = normalize_doi(attributes["doi"])

        published_date, year = _publication_date(attributes)

        publication = _publication_info(attributes)

        url = attributes.get("url")

        if url is not None and not isinstance(url, str):
            raise TypeError("DataCite url must be a string")

        return PaperMetadata(
            doi=doi,
            title=_title(attributes),
            authors=_authors(attributes),
            journal=publication.journal,
            issn=publication.issn,
            published_date=published_date,
            year=year,
            publisher=_publisher_name(attributes),
            work_type=_work_type(attributes),
            volume=publication.volume,
            issue=publication.issue,
            pages=publication.pages,
            url=url or None,
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise MetadataParseError(f"Failed to parse DataCite metadata: {exc}") from exc


def get_datacite_metadata(
    doi: str,
    *,
    mailto: str | None = None,
) -> PaperMetadata:
    """Retrieve metadata for one DOI from DataCite."""

    doi = normalize_doi(doi)

    data = get_json(
        (f"{DATACITE_API}/dois/{quote(doi, safe='')}"),
        context=f"DataCite metadata for DOI {doi}",
        mailto=mailto,
    )

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
