from urllib.parse import quote

from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataParseError,
)
from aletheia_nexus.acquire.metadata.transport import get_json
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata

CROSSREF_API = "https://api.crossref.org/v1"


def _first_text(
    value: object,
) -> str | None:
    """Return the first text value from a Crossref list."""

    if value is None:
        return None

    if not isinstance(value, list):
        raise TypeError("Crossref list field must be a list")

    if not value:
        return None

    first = value[0]

    if not isinstance(first, str):
        raise TypeError("Crossref list field must contain strings")

    return first or None


def _optional_text(
    work: dict,
    field: str,
) -> str | None:
    """Return one optional Crossref text field."""

    value = work.get(field)

    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError(f"Crossref {field} must be a string")

    return value or None


def _author_name(
    author: object,
) -> str:
    """Convert one Crossref author object into a readable name."""

    if not isinstance(author, dict):
        raise TypeError("Crossref author must be an object")

    literal_name = author.get("name")

    if literal_name is not None:
        if not isinstance(literal_name, str):
            raise TypeError("Crossref author name must be a string")

        return literal_name

    given = author.get("given")
    family = author.get("family")

    if given is not None and not isinstance(given, str):
        raise TypeError("Crossref author given name must be a string")

    if family is not None and not isinstance(family, str):
        raise TypeError("Crossref author family name must be a string")

    return " ".join(part for part in (given, family) if part)


def _authors(
    work: dict,
) -> tuple[str, ...]:
    """Return normalized Crossref author names."""

    authors = work.get("author", [])

    if authors is None:
        return ()

    if not isinstance(authors, list):
        raise TypeError("Crossref author field must be a list")

    return tuple(name for author in authors if (name := _author_name(author)))


def _issn(
    work: dict,
) -> tuple[str, ...]:
    """Return validated Crossref ISSN values."""

    values = work.get("ISSN", [])

    if values is None:
        return ()

    if not isinstance(values, list):
        raise TypeError("Crossref ISSN must be a list")

    if not all(isinstance(value, str) for value in values):
        raise TypeError("Crossref ISSN must contain strings")

    return tuple(values)


def _publication_date(
    work: dict,
) -> tuple[str | None, int | None]:
    """Extract the best available Crossref publication date."""

    for field in (
        "published",
        "published-online",
        "published-print",
        "issued",
    ):
        record = work.get(field)

        if record is None:
            continue

        if not isinstance(record, dict):
            raise TypeError(f"Crossref {field} must be an object")

        date_parts = record.get("date-parts")

        if not date_parts:
            continue

        if (
            not isinstance(date_parts, list)
            or not date_parts
            or not isinstance(date_parts[0], list)
            or not date_parts[0]
        ):
            raise TypeError(f"Crossref {field} date-parts are invalid")

        parts = date_parts[0]

        if not all(
            isinstance(part, int) and not isinstance(part, bool) for part in parts
        ):
            raise TypeError(f"Crossref {field} date-parts must contain integers")

        year = parts[0]

        date = "-".join(
            str(part) if index == 0 else f"{part:02d}"
            for index, part in enumerate(parts)
        )

        return date, year

    return None, None


def parse_crossref_work(
    work: dict,
) -> PaperMetadata:
    """Convert one Crossref work record into PaperMetadata."""

    if not isinstance(work, dict):
        raise MetadataParseError("Crossref work record must be an object")

    try:
        published_date, year = _publication_date(work)

        return PaperMetadata(
            doi=normalize_doi(work["DOI"]),
            title=_first_text(work.get("title")),
            authors=_authors(work),
            journal=_first_text(work.get("container-title")),
            issn=_issn(work),
            published_date=published_date,
            year=year,
            publisher=_optional_text(
                work,
                "publisher",
            ),
            work_type=_optional_text(
                work,
                "type",
            ),
            volume=_optional_text(
                work,
                "volume",
            ),
            issue=_optional_text(
                work,
                "issue",
            ),
            pages=_optional_text(
                work,
                "page",
            ),
            url=_optional_text(
                work,
                "URL",
            ),
        )

    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
    ) as exc:
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

    params = {"mailto": mailto} if mailto else None

    data = get_json(
        (f"{CROSSREF_API}/works/{quote(doi, safe='')}"),
        context=f"Crossref metadata for DOI {doi}",
        params=params,
        mailto=mailto,
    )

    message = data.get("message")

    if not isinstance(message, dict):
        raise MetadataParseError(
            f"Crossref response has invalid structure for DOI: {doi}"
        )

    return parse_crossref_work(message)
